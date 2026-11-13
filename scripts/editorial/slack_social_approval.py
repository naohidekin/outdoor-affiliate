"""Explicit trusted-local-operator Slack approval, no network/model/post calls.

Caller must read the authenticated owner message and its referenced presentation.
JSON evidence is not authentication. Never expose this as automatic text parsing.
"""
import json
import re
from decimal import Decimal
from ledger import (SCOPE, canonical, fingerprint, require, timestamp,
                    valid_review, valid_social_mode, valid_social_images)


def approve_social_from_slack_message(ledger, evidence, expected_scope):
    require(isinstance(evidence,dict) and set(evidence)=={'source','scope','message_ts','text','observed_at','context','absence'}, 'exact Slack evidence required')
    require(evidence['source']=='slack_owner_message', 'original Slack source required')
    scope=evidence['scope']
    require(isinstance(scope,dict) and set(scope)==set(SCOPE) and all(isinstance(scope[k],str) and scope[k] and scope[k]==expected_scope.get(k) for k in SCOPE) and scope['user_id']==ledger.owner_id, 'owner Slack scope mismatch')
    require(re.fullmatch(r'(?:<@[A-Z0-9]+>\s*)?上の[２2]記事はGO[。.]?',evidence['text'].strip()), 'explicit two article GO required')
    timestamp(evidence['observed_at'])
    ctx=evidence['context'];require(isinstance(ctx,dict) and set(ctx)=={'message_ts','text','items','interveningMessages','threadReadThroughTs','threadObservationReference'},'exact presentation context required')
    # Deictic 'above two' is accepted only for an immediately preceding presentation.
    # Caller must read the full thread interval; competing intervening content fails closed.
    require(ctx['threadReadThroughTs']==evidence['message_ts'] and isinstance(ctx['threadObservationReference'],str) and ctx['threadObservationReference'].strip(), 'complete thread readback through approval required')
    require(ctx['interveningMessages']==[], 'intervening thread content makes above-two ambiguous')
    for ts in (evidence['message_ts'],ctx['message_ts']):
        require(isinstance(ts,str) and re.fullmatch(r'\d+\.\d+',ts), 'exact Slack timestamp required')
    require(Decimal(ctx['message_ts'])<Decimal(evidence['message_ts']), 'presentation must precede owner approval')
    require(isinstance(ctx['text'],str) and ctx['text'].strip(),'original presentation text required')
    items=ctx['items'];require(isinstance(items,list) and len(items)==2,'finite two item binding required')
    fields={'item','article_id','revision','targetAccountId','textHash','imageSha256s','replyText'}
    require(all(isinstance(i,dict) and set(i)==fields for i in items),'exact item binding required')
    require([i['item'] for i in items]==[4,5] and len({i['article_id'] for i in items})==2,'items 4 and 5 must be distinct')
    absence=evidence['absence'];require(isinstance(absence,dict) and set(absence)=={'checked_at','articleIds','regularPublisher','savedAlternateRoute','publicPlatform','evidenceReferences'},'absence evidence required')
    require(isinstance(absence['evidenceReferences'],list) and len(absence['evidenceReferences'])>=1 and all(isinstance(x,str) and x.strip() for x in absence['evidenceReferences']),'retained absence references required')
    require(absence['articleIds']==[i['article_id'] for i in items] and all(absence[k] is True for k in ('regularPublisher','savedAlternateRoute','publicPlatform')),'unconfirmed publication prohibits approval')
    require(timestamp(absence['checked_at'])<=timestamp(evidence['observed_at']),'absence observation chronology invalid')
    frozen=json.loads(canonical(evidence));key='slack-social-message:'+fingerprint({'scope':scope,'message_ts':evidence['message_ts']})
    with ledger._tx() as db:
        prior=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        if prior: require(json.loads(prior[0])==frozen,'source message binding conflict')
        jobs=[]
        for item in items:
            job=ledger._get(db,item['article_id']);ledger._current(job)
            pub=job.get('publication') or {};readback=pub.get('readback') or {};social=job.get('social') or {};p=social.get('proposal') or {};rev=item['revision']
            require(pub.get('verified') is True and pub.get('revision')==job['revision'] and readback.get('verified') is True and readback.get('fingerprint')==job['revision'],'current verified article required')
            require(social.get('revision')==rev and fingerprint(p)==rev,'exact social revision required')
            valid_review(social.get('review'),rev);valid_social_mode(p);valid_social_images(job,p)
            require(p.get('platform')=='x' and p.get('deliveryMode')=='auto_x' and ledger.target_account_id and p.get('targetAccountId')==ledger.target_account_id,'configured X target required')
            require(p.get('url')==pub.get('url') and p.get('replyText')==pub.get('url'),'exact published URL required')
            binding=dict(item=item['item'],article_id=job['id'],revision=rev,targetAccountId=p['targetAccountId'],textHash=fingerprint(p['text']),imageSha256s=[x['sha256'] for x in p['images']],replyText=p['replyText'])
            require(binding==item,'proposal binding mismatch')
            require(p['text'] in ctx['text'] and p['replyText'] in ctx['text'] and all(x['url'] in ctx['text'] for x in p['images']),'exact presented text links and images required')
            require(not social.get('publication') and not db.execute('SELECT 1 FROM effects WHERE job_id=? AND kind=?',(job['id'],'social')).fetchone(),'prior social effect requires reconciliation')
            for folder in ('social-publications','social-outbox'):
                marker=ledger.root/folder/(rev+'.json');require(not marker.exists() and not marker.is_symlink(),'prior social journal requires reconciliation')
            approval=social.get('approval')
            if prior:
                require(job['stage']=='social_approved' and approval and approval.get('request_id')==key and approval.get('evidence')==frozen,'replay state conflict')
            else:
                require(not approval and job['stage'] in ('social_review','social_held'),'social approval state unavailable')
            jobs.append(job)
        if prior:return jobs
        for job in jobs:
            job['social']['approval']=dict(action='approved',user_id=ledger.owner_id,request_id=key,revision=job['social']['revision'],source='slack_owner_message',evidence=frozen,at=timestamp().isoformat())
            job['stage']='social_approved'
            # Deliberately retain delivery-unknown files and request/event history.
            # Existing button decide cannot use an undelivered request.
            ledger._put(db,job,'slack_owner_message_social_approval')
        db.execute('INSERT INTO meta VALUES (?,?)',(key,canonical(frozen)))
        return jobs
