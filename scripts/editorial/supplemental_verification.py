"""Deterministic supplemental-batch Slack readiness and stop reporting."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from production_verification import verified_article_deliveries
from reporting import _atomic


JST = timezone(timedelta(hours=9))
QUALITY_RESULT = '対象版の品質確認: 本文審査・商品情報・使用画像・PC/スマホ表示・楽天/Amazon購入導線は既存の必須検査を通過。'


def _usage(cost_text):
    try:
        value = cost_text() if callable(cost_text) else cost_text
        if not isinstance(value,str) or not value.strip(): raise ValueError()
        return value
    except Exception:
        return '追加batchの使用量・費用・予算残量: 未取得'


def _safe_text(value, fallback):
    value = re.sub(r'[<>\r\n]',' ',str(value or '')).strip()
    return value[:160] or fallback


def _action(reason):
    lowered = reason.lower()
    if any(word in lowered for word in ('image','render','readback')):
        return '本文・商品画像の確認結果を見直し、同じ対象版の再開可否を手動確認します。'
    if any(word in lowered for word in ('source','product','affiliate','link')):
        return '商品情報と購入先の確認結果を見直し、未確認のまま本文作成を進めません。'
    if any(word in lowered for word in ('model','timeout','budget')):
        return 'モデル処理記録と残予算を確認し、自動再試行せず再開可否を判断します。'
    return '停止位置の入力と確認結果を見直し、自動再試行せず再開可否を判断します。'


def _cause(reason):
    lowered = reason.lower()
    if any(word in lowered for word in ('image','render','readback')):
        return '本文または商品画像の確認ゲートで停止'
    if any(word in lowered for word in ('source','product','affiliate','link')):
        return '商品情報または購入先の確認ゲートで停止'
    if 'budget' in lowered:
        return '設定済みモデル予算の上限で停止'
    if any(word in lowered for word in ('model','timeout')):
        return 'モデル処理の完了を確認できず停止'
    return '制作確認ゲートで停止'


def _current_state(job):
    publication = job.get('publication') if isinstance(job.get('publication'),dict) else {}
    readback = publication.get('readback') if isinstance(publication.get('readback'),dict) else {}
    if (publication.get('verified') is True and publication.get('revision') == job.get('revision')
            and readback.get('verified') is True
            and readback.get('fingerprint') == job.get('revision')):
        return '公開確認済み（SNSの承認・予約状態は別確認）'
    approval = job.get('approval') if isinstance(job.get('approval'),dict) else {}
    if (approval.get('revision') == job.get('revision')
            and approval.get('action') in ('approved',None) and approval.get('user_id')):
        return '本人承認済み（公開結果は未確認）'
    return 'Slack送達は本人承認ではありません（承認・公開は未確認）'


def _claim(path, initial):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try: fd = os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError: return None
    with os.fdopen(fd,'w') as stream:
        json.dump(initial,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
    return initial


def _send_once(path, receipt, text, send):
    if _claim(path,receipt) is None:
        try: saved = json.loads(path.read_text())
        except (OSError,ValueError): saved = {'status':'unknown'}
        return 'verified' if saved.get('status') == 'verified' else 'unknown'
    try:
        delivered = send(text)
        receipt['status'] = ('verified' if isinstance(delivered,dict)
                             and delivered.get('verified') is True
                             and delivered.get('message_ts') else 'unknown')
        if receipt['status'] == 'verified': receipt['messageTs'] = delivered['message_ts']
    except Exception: receipt['status'] = 'unknown'
    _atomic(path,receipt)
    return receipt['status']


def verify_supplemental_batch(root,jobs,batch_id,scope,send,*,now=None,not_before,
                              cost_text='',source_state=None):
    now = now or datetime.now(JST)
    if (not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None
            or not isinstance(batch_id,str) or not re.fullmatch(r'[a-z0-9-]{3,80}',batch_id)):
        raise ValueError('invalid supplemental verification input')
    start = datetime.fromisoformat(str(not_before).replace('Z','+00:00'))
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError('invalid supplemental notBefore')
    if now.astimezone(JST) < start.astimezone(JST):
        return {'status':'not_due','batchId':batch_id,'articles':[]}
    selected = sorted([job for job in jobs if isinstance(job,dict)
                       and job.get('kind') == 'supplemental_article'
                       and job.get('batchId') == batch_id],key=lambda job:job.get('batchSlot',99))
    db_path = Path(root) / 'ledger.sqlite3'
    if db_path.is_file():
        from supplemental_reselection import active_jobs
        with sqlite3.connect(db_path) as db:
            selected = sorted(active_jobs(db, jobs, batch_id), key=lambda job: job['batchSlot'])
    if (len(selected) > 3 or len({job.get('batchSlot') for job in selected}) != len(selected)
            or any(job.get('batchSlot') not in (1,2,3) for job in selected)
            or any(re.fullmatch(r'[a-f0-9]{64}',str(job.get('revision',''))) is None
                   for job in selected)):
        raise ValueError('invalid supplemental batch jobs')
    evidence = verified_article_deliveries(root,selected,scope)
    by_slot = {job['batchSlot']:job for job in selected}
    source_slots = {item.get('slot'):item for item in (source_state or {}).get('slots',[])
                    if isinstance(item,dict)}
    progress = []
    for slot in (1,2,3):
        job = by_slot.get(slot)
        if job is None:
            source = source_slots.get(slot,{})
            progress.append({'slot':slot,'id':None,'title':None,
                             'status':'source_hold' if source.get('status') == 'source_hold'
                             else 'awaiting_source','reason':source.get('reason')})
            continue
        status = ('slack_ready' if job['id'] in evidence else
                  'blocked' if job.get('stage') in ('error','held') and job.get('error') else
                  'awaiting_slack' if job.get('stage') == 'review' else job.get('stage','working'))
        progress.append({'slot':slot,'id':job['id'],
                         'title':_safe_text((job.get('theme') or {}).get('title'),job['id']),
                         'status':status,'reason':(job.get('error') or {}).get('reason'),
                         'currentState':_current_state(job)})
    failures = [item for item in progress if item['status'] == 'blocked']
    root = Path(root)
    usage = _usage(cost_text)
    progress_notifications = []
    ready_count = sum(item['status'] == 'slack_ready' for item in progress)
    for item in ([] if ready_count == 3 else
                 [value for value in progress if value['status'] == 'slack_ready']):
        job = by_slot[item['slot']]
        text = ('【追加ウェア記事・Slack準備済み '+str(ready_count)+'/3】\n・'+item['title']
                +'\n本文・画像を含む対象版をSlackへ送達済みです。'
                +'\n'+QUALITY_RESULT
                +'\n現在状態: '+item['currentState']+'。\n\n'+usage)
        receipt = {'status':'in_flight','batchId':batch_id,'at':now.isoformat(),
                   'article':evidence[job['id']],'reportedCostText':usage,
                   'expectedText':text,'textHash':hashlib.sha256(text.encode()).hexdigest()}
        status = _send_once(root/'supplemental-verifications'/batch_id/
                            (str(item['slot'])+'-'+job['revision']+'-ready.json'),
                            receipt,text,send)
        progress_notifications.append({'id':job['id'],'slot':item['slot'],'status':status})
    if failures:
        identity = [{key:item.get(key) for key in ('id','slot','status','reason')} for item in failures]
        digest = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        lines = ['【追加ウェア記事・制作停止】']
        actions = []
        for item in failures:
            action = _action(str(item.get('reason') or 'unknown'))
            cause = _cause(str(item.get('reason') or 'unknown'))
            actions.append({'id':item['id'],'slot':item['slot'],'action':action})
            lines += [f'・{item["title"]}',f'  確認状況: 本文・商品画像を含む制作処理が停止しています。',
                      f'  確認済み事実: {cause}。',
                      '  原因判断: 停止ゲートは確認済みですが、根本原因は未確定です。',
                      f'  次の対応: {action}']
        text = '\n'.join(lines)+'\n品質基準・予算上限・本人承認条件は変更しません。\n\n'+usage
        receipt = {'status':'in_flight','batchId':batch_id,'at':now.isoformat(),
                   'failures':identity,'nextActions':actions,'reportedCostText':usage,
                   'expectedText':text,'textHash':hashlib.sha256(text.encode()).hexdigest()}
        status = _send_once(root/'supplemental-verifications'/batch_id/'failures'/
                            (digest+'.json'),receipt,text,send)
        return {'status':'blocked','batchId':batch_id,'articles':progress,
                'notificationStatus':status,'progressNotifications':progress_notifications,
                'handledAttentionJobIds':sorted(item['id'] for item in failures)}
    if len(evidence) == 3 and len(selected) == 3:
        lines = ['【追加ウェア3記事・Slack確認済み】',
                 '本文・画像を含む対象版をSlackへ送達済みです。']
        lines += ['・'+item['title']+'／'+item['currentState'] for item in progress]
        lines += [QUALITY_RESULT]
        lines += ['記事ごとの本人承認・公開・SNS状態は上記の現在状態を正本とします。']
        text = '\n'.join(lines)+'\n\n'+usage
        receipt = {'status':'in_flight','batchId':batch_id,'at':now.isoformat(),
                   'articles':[evidence[job['id']] for job in selected],
                   'reportedCostText':usage,'expectedText':text,
                   'textHash':hashlib.sha256(text.encode()).hexdigest()}
        status = _send_once(root/'supplemental-verifications'/
                            (batch_id+'-ready.json'),receipt,text,send)
        return {'status':'verified' if status == 'verified' else 'requires_reconciliation',
                'batchId':batch_id,'articles':progress,'notificationStatus':status,
                'progressNotifications':progress_notifications,'handledAttentionJobIds':[]}
    source_hold = any(item['status'] == 'source_hold' for item in progress)
    return {'status':'source_hold' if source_hold else 'waiting','batchId':batch_id,
            'articles':progress,'notificationStatus':'existing_source_notice' if source_hold else None,
            'progressNotifications':progress_notifications,'handledAttentionJobIds':[]}
