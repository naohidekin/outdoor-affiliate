"""One requested production-period check inside the existing runner; no AI calls."""
from datetime import datetime, timedelta, timezone, date
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from ledger import valid_review, SCOPE
from reporting import _atomic

JST = timezone(timedelta(hours=9))


def verify_period(root, jobs, period, scope, send, *, now=None, cost_text=''):
    now = now or datetime.now(JST)
    if now.tzinfo is None or not isinstance(period, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',period):
        raise ValueError('invalid production verification period')
    date.fromisoformat(period)
    if now.astimezone(JST) < datetime.combine(date.fromisoformat(period), datetime.min.time(), JST).replace(hour=9):
        return {'status':'not_due','period':period}
    root = Path(root)
    selected = [j for j in jobs if j.get('week') == period and j.get('kind') != 'article_revision']
    if len(selected) != 3:
        return {'status':'waiting','period':period,'candidates':len(selected),'verifiedArticles':0}
    confirmed = []
    uri = 'file:' + quote(str(root/'ledger.sqlite3'),safe='/') + '?mode=ro'
    with sqlite3.connect(uri,uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        for job in selected:
            try: valid_review(job.get('review'),job.get('revision'))
            except (ValueError,TypeError): continue
            requests = db.execute('SELECT data FROM requests WHERE job_id=? AND kind=? ORDER BY rowid DESC LIMIT 50',
                                  (job['id'],'article')).fetchall()
            deliveries = [json.loads(row[0]) for row in db.execute(
                'SELECT data FROM events WHERE job_id=? AND kind=? ORDER BY rowid DESC LIMIT 50',
                (job['id'],'delivered'))]
            for (raw,) in requests:
                request = json.loads(raw)
                parts = request.get('parts',{})
                part_scope = parts.get('scope',parts) if isinstance(parts,dict) else {}
                parts = parts.get('parts') if isinstance(parts,dict) else parts
                exact = (request.get('manifest_hash') == job['revision']
                    and request.get('status') in ('delivered','decided')
                    and all(request.get('scope',{}).get(k) == scope.get(k) and scope.get(k) for k in SCOPE)
                    and all(part_scope.get(k) == request.get('scope',{}).get(k) for k in SCOPE)
                    and any(event.get('status') == 'delivered' and all(event.get(k) == request.get(k)
                        for k in ('request_id','manifest_hash','article_id','scope','parts','card_ts'))
                        for event in deliveries)
                    and re.fullmatch(r'\d{10}\.\d{6}',request.get('card_ts',''))
                    and isinstance(parts,list) and bool(parts)
                    and all(isinstance(p,dict) and p.get('verified') is True for p in parts))
                if exact:
                    confirmed.append({'id':job['id'],'revision':job['revision'],'cardTs':request['card_ts']})
                    break
    if len(confirmed) != 3:
        return {'status':'waiting','period':period,'candidates':3,'verifiedArticles':len(confirmed)}
    marker = root/'production-verifications'/(period+'-slack-ready.json')
    marker.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try: fd = os.open(str(marker),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        try: previous = json.loads(marker.read_text())
        except (ValueError,OSError): return {'status':'requires_reconciliation','period':period}
        return {'status':'verified' if previous.get('status')=='verified' else 'requires_reconciliation','period':period}
    receipt = {'status':'in_flight','period':period,'at':now.isoformat(),'articles':confirmed}
    with os.fdopen(fd,'w') as f:
        json.dump(receipt,f);f.flush();os.fsync(f.fileno())
    titles = ['・'+re.sub(r'[<>\r\n]',' ',str(j.get('theme',{}).get('title') or j['id']))[:180] for j in selected]
    text = ('【制作枠の到達確認】'+period+'開始\n3記事の品質審査とSlack対象版の送達を確認しました。\n'
        +'\n'.join(titles)+'\n公開は本人承認後です。本人既読・承認は送達成功と区別します。'
        +'\nSNSは別承認、X投稿は停止中です。')
    try:
        text += '\n\n' + (cost_text() if callable(cost_text) else cost_text)
        delivered = send(text)
        receipt.update(status='verified' if isinstance(delivered,dict) and delivered.get('verified') is True
                       and delivered.get('message_ts') else 'unknown')
        if receipt['status']=='verified': receipt['messageTs']=delivered['message_ts']
    except Exception: receipt['status']='unknown'
    _atomic(marker,receipt)
    return {'status':'verified' if receipt['status']=='verified' else 'requires_reconciliation','period':period,
            'verifiedArticles':3}
