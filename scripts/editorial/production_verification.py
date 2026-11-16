"""One requested production-period check inside the existing runner; no AI calls."""
from datetime import datetime, timedelta, timezone, date
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from ledger import valid_review, SCOPE
from reporting import _atomic

JST = timezone(timedelta(hours=9))


def _safe(value, fallback='unknown'):
    value = value if isinstance(value, str) else ''
    value = re.sub(r'[^A-Za-z0-9_.:-]', '_', value)[:160]
    return value or fallback


def _failure_item(job, reason, *, stage=None, input_key=None, global_failure=False):
    error = job.get('error') if isinstance(job, dict) else None
    error = error if isinstance(error, dict) else {}
    raw_reason = reason if isinstance(reason, str) else str(reason)
    return {
        'jobId': None if global_failure else job.get('id'),
        'title': ('制作候補の調査段階' if global_failure else
                  re.sub(r'[<>\r\n]', ' ', str((job.get('theme') or {}).get('title')
                                                or job.get('id') or '記事'))[:120]),
        'stage': _safe(stage or job.get('stage') or 'research'),
        'revision': _safe(job.get('revision'), 'none'),
        'inputKey': _safe(input_key or error.get('inputKey') or error.get('stageKey'), 'none'),
        'reason': _safe(raw_reason),
        'rawReason': raw_reason,
    }


def _next_step(reason):
    reason = reason.lower()
    if any(token in reason for token in ('source','product','image','link','affiliate')):
        target = '商品・画像・リンク証跡'
    elif any(token in reason for token in ('model','timeout','deadline','transport')):
        target = 'モデル応答・timeout記録'
    elif 'render' in reason or 'readback' in reason:
        target = 'renderer出力・readback'
    elif any(token in reason for token in ('delivery','deliver','slack','receipt')):
        target = '送達receipt・対象scope'
    else:
        target = '入力・証跡・stage状態'
    return f'{target}を手動確認し、自動再試行せず明示的に再開します。'


def _social_route(buffer_posting_enabled):
    return ('SNSは別の本人対象版承認後にBuffer予約、予約後はX実投稿を確認。直接X投稿は停止中。'
            if buffer_posting_enabled else 'SNSは別承認、X投稿は停止中です。')


def _failures(jobs, period, results, now):
    selected = [j for j in jobs if j.get('week') == period and j.get('kind') not in
                ('article_revision', 'supplemental_article')]
    by_id = {job.get('id'): job for job in selected}
    target_start = datetime.combine(date.fromisoformat(period),datetime.min.time(),JST).replace(hour=9)
    global_window = target_start <= now.astimezone(JST) < target_start + timedelta(days=7)
    found = []
    for job in selected:
        error = job.get('error')
        reason = error.get('reason') if isinstance(error, dict) else None
        if job.get('stage') in ('error', 'held') and reason and reason != 'model_budget_hold':
            found.append(_failure_item(job, reason))
    for result in results or []:
        if not isinstance(result, dict):
            continue
        production = result.get('production')
        if isinstance(production, dict):
            articles = production.get('articles')
            if isinstance(articles, list):
                for article in articles:
                    if not isinstance(article, dict) or article.get('status') not in ('blocked', 'attention'):
                        continue
                    reason, job = article.get('reason'), by_id.get(article.get('id'))
                    if job and reason and reason != 'model_budget_hold':
                        found.append(_failure_item(job, reason, stage=article.get('stage'),
                                                   input_key=article.get('inputKey')))
            elif production.get('status') == 'blocked' and global_window:
                reason = production.get('reason') or result.get('reason')
                if reason and reason != 'model_budget_hold':
                    found.append(_failure_item({}, reason, global_failure=True))
        job = by_id.get(result.get('id'))
        reason = result.get('reason')
        if job and result.get('status') in ('blocked', 'attention') and reason != 'model_budget_hold':
            found.append(_failure_item(job, reason, stage=result.get('stage'),
                                       input_key=result.get('inputKey')))
    unique = {}
    for item in found:
        key = json.dumps({k:item[k] for k in ('jobId','stage','revision','inputKey','reason')},
                         sort_keys=True,separators=(',',':'))
        unique[key] = item
    return [unique[key] for key in sorted(unique)]


def _notify_failures(root, period, failures, send, now, cost_text,
                     buffer_posting_enabled=False):
    identity = [{k:item[k] for k in ('jobId','stage','revision','inputKey','reason')}
                for item in failures]
    digest = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    marker = root/'production-verifications'/(period+'-failures')/(digest+'.json')
    marker.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    handled_ids = sorted({item['jobId'] for item in failures if item['jobId']})
    global_reasons = sorted({item['rawReason'] for item in failures if not item['jobId']})
    try: fd = os.open(str(marker),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        try: previous = json.loads(marker.read_text())
        except (ValueError,OSError): previous = {'status':'unknown'}
        return {'status':'blocked','healthStatus':'blocked','period':period,
                'notificationStatus':('verified' if previous.get('status')=='verified' else 'unknown'),
                'handledAttentionJobIds':handled_ids,'handledGlobalReasons':global_reasons}
    lines = ['【制作枠の中断確認】'+period+'開始',
             f'観測時刻: {now.astimezone(JST):%Y/%m/%d %H:%M} JST']
    next_actions = []
    for item in failures:
        target = item['title'] + (f'（{item["jobId"]}）' if item['jobId'] else '')
        action = _next_step(item['rawReason'])
        next_actions.append({'jobId':item['jobId'],'stage':item['stage'],'action':action})
        lines += [f'・対象: {target}／stage {item["stage"]}',
                  f'  観測事実: {item["reason"]}で停止',
                  f'  原因: 確認済み事実は停止ゲート {item["reason"]}。根本原因は未確定です。',
                  '  次の対応: '+action]
    lines += ['品質基準とモデル予算上限は維持し、自動で引き上げません。',
              '公開は本人承認後です。' + _social_route(buffer_posting_enabled)]
    try:
        usage = cost_text() if callable(cost_text) else cost_text
        if not isinstance(usage,str) or not usage.strip(): raise ValueError()
    except Exception: usage = '使用量・費用・予算残量: 未取得'
    text = '\n'.join(lines)+'\n\n'+usage
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    receipt = {'status':'in_flight','period':period,'at':now.isoformat(),'failures':identity,
               'reportedCostText':usage,'nextActions':next_actions,
               'expectedText':text,'textHash':text_hash}
    with os.fdopen(fd,'w') as f:
        json.dump(receipt,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    try:
        delivered = send(text)
        receipt['status'] = ('verified' if isinstance(delivered,dict) and delivered.get('verified') is True
                             and delivered.get('message_ts') else 'unknown')
        message_id = delivered.get('message_ts') if receipt['status'] == 'verified' else None
    except Exception: receipt['status'] = 'unknown'
    if receipt['status'] == 'unknown': message_id = None
    receipt['nativeSlack'] = {'verified':receipt['status']=='verified',
                              'messageId':message_id,'textHash':text_hash}
    if message_id: receipt['messageTs'] = message_id
    _atomic(marker,receipt)
    return {'status':'blocked','healthStatus':'blocked','period':period,
            'notificationStatus':receipt['status'],'handledAttentionJobIds':handled_ids,
            'handledGlobalReasons':global_reasons}


def verified_article_deliveries(root, jobs, scope):
    """Read exact reviewed revision + Slack scope/parts evidence without mutation."""
    if (not isinstance(scope, dict) or any(not scope.get(key) for key in SCOPE)
            or not isinstance(jobs, list)):
        return {}
    root = Path(root)
    uri = 'file:' + quote(str(root/'ledger.sqlite3'),safe='/') + '?mode=ro'
    confirmed = {}
    try:
        with sqlite3.connect(uri,uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            for job in jobs:
                if not isinstance(job,dict) or not isinstance(job.get('id'),str):
                    continue
                try: valid_review(job.get('review'),job.get('revision'),job.get('bundle'))
                except (ValueError,TypeError): continue
                requests = db.execute(
                    'SELECT data FROM requests WHERE job_id=? AND kind=? ORDER BY rowid DESC LIMIT 50',
                    (job['id'],'article')).fetchall()
                deliveries = []
                for row in db.execute(
                        'SELECT data FROM events WHERE job_id=? AND kind=? ORDER BY rowid DESC LIMIT 50',
                        (job['id'],'delivered')):
                    try: value = json.loads(row[0])
                    except (TypeError,ValueError): continue
                    if isinstance(value,dict): deliveries.append(value)
                for (raw,) in requests:
                    try: request = json.loads(raw)
                    except (TypeError,ValueError): continue
                    parts_value = request.get('parts',{})
                    part_scope = (parts_value.get('scope',parts_value)
                                  if isinstance(parts_value,dict) else {})
                    parts = parts_value.get('parts') if isinstance(parts_value,dict) else parts_value
                    exact = (request.get('manifest_hash') == job['revision']
                        and request.get('status') in ('delivered','decided')
                        and all(request.get('scope',{}).get(k) == scope.get(k) for k in SCOPE)
                        and all(part_scope.get(k) == request.get('scope',{}).get(k) for k in SCOPE)
                        and any(event.get('status') == 'delivered' and all(event.get(k) == request.get(k)
                            for k in ('request_id','manifest_hash','article_id','scope','parts','card_ts'))
                            for event in deliveries)
                        and re.fullmatch(r'\d{10}\.\d{6}',request.get('card_ts',''))
                        and isinstance(parts,list) and bool(parts)
                        and all(isinstance(p,dict) and p.get('verified') is True for p in parts))
                    if exact:
                        confirmed[job['id']] = {'id':job['id'],'revision':job['revision'],
                                                'cardTs':request['card_ts']}
                        break
    except (OSError,sqlite3.Error):
        return {}
    return confirmed


def verify_period(root, jobs, period, scope, send, *, now=None, cost_text='', results=None,
                  buffer_posting_enabled=False):
    now = now or datetime.now(JST)
    if now.tzinfo is None or not isinstance(period, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',period):
        raise ValueError('invalid production verification period')
    date.fromisoformat(period)
    if now.astimezone(JST) < datetime.combine(date.fromisoformat(period), datetime.min.time(), JST).replace(hour=9):
        return {'status':'not_due','period':period}
    root = Path(root)
    failures = _failures(jobs,period,results,now)
    if failures:
        return _notify_failures(root,period,failures,send,now,cost_text,
                                buffer_posting_enabled)
    selected = [j for j in jobs if j.get('week') == period and j.get('kind') not in
                ('article_revision', 'supplemental_article')]
    if len(selected) != 3:
        return {'status':'waiting','period':period,'candidates':len(selected),'verifiedArticles':0}
    if any(j.get('stage') in ('error','held') and j.get('error') for j in selected):
        return {'status':'waiting','period':period,'candidates':3,'verifiedArticles':0}
    evidence = verified_article_deliveries(root,selected,scope)
    confirmed = [evidence[job['id']] for job in selected if job['id'] in evidence]
    if len(confirmed) != 3:
        return {'status':'waiting','period':period,'candidates':3,'verifiedArticles':len(confirmed)}
    marker = root/'production-verifications'/(period+'-slack-ready.json')
    marker.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try: fd = os.open(str(marker),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        try: previous = json.loads(marker.read_text())
        except (ValueError,OSError): return {'status':'requires_reconciliation','period':period}
        return {'status':'verified' if previous.get('status')=='verified' else 'requires_reconciliation','period':period}
    titles = ['・'+re.sub(r'[<>\r\n]',' ',str(j.get('theme',{}).get('title') or j['id']))[:180] for j in selected]
    try:
        usage = cost_text() if callable(cost_text) else cost_text
        if not isinstance(usage,str) or not usage.strip(): raise ValueError()
    except Exception: usage = '使用量・費用・予算残量: 未取得'
    text = ('【制作枠の到達確認】'+period+'開始\n3記事の品質審査とSlack対象版の送達を確認しました。\n'
        +'\n'.join(titles)+'\n公開は本人承認後です。本人既読・承認は送達成功と区別します。'
        +'\n'+_social_route(buffer_posting_enabled)+'\n\n'+usage)
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    receipt = {'status':'in_flight','period':period,'at':now.isoformat(),'articles':confirmed,
               'reportedCostText':usage,'expectedText':text,'textHash':text_hash}
    with os.fdopen(fd,'w') as f:
        json.dump(receipt,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    try:
        delivered = send(text)
        receipt.update(status='verified' if isinstance(delivered,dict) and delivered.get('verified') is True
                       and delivered.get('message_ts') else 'unknown')
        if receipt['status']=='verified': receipt['messageTs']=delivered['message_ts']
    except Exception: receipt['status']='unknown'
    _atomic(marker,receipt)
    return {'status':'verified' if receipt['status']=='verified' else 'requires_reconciliation','period':period,
            'verifiedArticles':3}
