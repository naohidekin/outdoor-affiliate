import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from ledger import Ledger, FLAGS
from production_verification import verify_period

JST = timezone(timedelta(hours=9))

class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.ledger = Ledger(self.root, 'owner')
        self.scope = dict(team_id='T',app_id='A',user_id='owner',channel_id='C',thread_ts='1793000000.000001')
        self.sent = []
        self.jobs = []
        for n in range(3):
            revision = str(n) * 64
            job = dict(id='article-'+str(n),week='2026-11-20',theme={'title':'記事'+str(n)},revision=revision,
                review=dict(score=8,passed=True,evidence={f:True for f in FLAGS},
                    fingerprint=revision,polish=dict(model='gemini-3.8-flash',validated=True)))
            self.jobs.append(job)
            request = dict(request_id=str(n),article_id=job['id'],manifest_hash=revision,status='created')
            with self.ledger._tx() as db:
                db.execute('INSERT INTO requests VALUES (?,?,?,?)',(str(n),job['id'],'article',json.dumps(request)))
            self.ledger.mark_delivered(str(n),{'scope':self.scope,'parts':[{'verified':True}]},'1793000000.123456')
        self.now = datetime(2026,11,20,12,tzinfo=JST)

    def tearDown(self): self.tmp.cleanup()
    def run_check(self, jobs=None, send=None):
        def delivery(text): self.sent.append(text); return {'verified':True,'message_ts':'1793000000.123456'}
        return verify_period(self.root,self.jobs if jobs is None else jobs,'2026-11-20',self.scope,
            send or delivery,now=self.now,cost_text='使用量：fixture')

    def test_exact_three_reviews_and_delivery_send_one_result_without_approving(self):
        self.assertEqual('verified',self.run_check()['status'])
        self.assertEqual('verified',self.run_check()['status'])
        self.assertEqual(1,len(self.sent))
        self.assertIn('公開は本人承認後',self.sent[0])
        self.assertFalse(any(j.get('approval') for j in self.jobs))

    def test_partial_or_stale_delivery_never_claims_success(self):
        self.assertEqual('waiting',self.run_check(self.jobs[:2])['status'])
        self.jobs[0]['revision']='f'*64
        self.assertEqual('waiting',self.run_check()['status'])
        self.assertEqual([],self.sent)

    def test_unknown_notification_is_not_repeated(self):
        def delivery(text): self.sent.append(text); raise TimeoutError()
        self.assertEqual('requires_reconciliation',self.run_check(send=delivery)['status'])
        self.assertEqual('requires_reconciliation',self.run_check()['status'])
        self.assertEqual(1,len(self.sent))

    def test_modified_delivery_part_scope_is_not_verified(self):
        with self.ledger._tx() as db:
            request=json.loads(db.execute('SELECT data FROM requests WHERE id=?',('0',)).fetchone()[0])
            request['parts']['scope']['channel_id']='OTHER'
            db.execute('UPDATE requests SET data=? WHERE id=?',(json.dumps(request),'0'))
        self.assertEqual('waiting',self.run_check()['status'])
        self.assertEqual([],self.sent)
