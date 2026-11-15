from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ledger import FLAGS, Ledger
from supplemental_verification import verify_supplemental_batch


JST = timezone(timedelta(hours=9))


class SupplementalVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name) / 'state'
        self.ledger = Ledger(self.root, 'owner')
        self.scope = dict(team_id='T',app_id='A',user_id='owner',channel_id='C',
                          thread_ts='1793000000.000001')
        self.now = datetime(2026,11,16,12,tzinfo=JST)
        self.sent = []; self.jobs = []
        for slot in range(1,4):
            revision = str(slot) * 64
            self.jobs.append(dict(id=f'extra-{slot}',kind='supplemental_article',
                batchId='apparel-2026-11-16',batchSlot=slot,stage='review',
                theme={'title':f'ウェア記事{slot}'},revision=revision,error=None,
                review=dict(score=8,passed=True,evidence={name:True for name in FLAGS},
                    fingerprint=revision,polish=dict(model='gemini-3.8-flash',validated=True))))

    def tearDown(self): self.tmp.cleanup()

    def deliver(self, count=3):
        for index, job in enumerate(self.jobs[:count], 1):
            request = dict(request_id=f'req-{index}',article_id=job['id'],
                           manifest_hash=job['revision'],status='created')
            with self.ledger._tx() as db:
                db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                           (request['request_id'],job['id'],'article',json.dumps(request)))
            self.ledger.mark_delivered(request['request_id'],
                {'scope':self.scope,'parts':[{'verified':True}]},f'179300000{index}.123456')

    def verify(self, jobs=None, source_state=None):
        return verify_supplemental_batch(
            self.root,self.jobs if jobs is None else jobs,'apparel-2026-11-16',
            self.scope,lambda text:self.sent.append(text) or
            {'verified':True,'message_ts':'1793000099.123456'},now=self.now,
            not_before='2026-11-16T09:00:00+09:00',cost_text='追加batch費用fixture',
            source_state=source_state)

    def test_per_article_progress_then_all_three_exact_deliveries_notify_once(self):
        self.deliver(2)
        partial = self.verify()
        self.assertEqual('waiting',partial['status'])
        self.assertEqual(['slack_ready','slack_ready','awaiting_slack'],
                         [item['status'] for item in partial['articles']])
        self.assertEqual(2,len(self.sent))
        self.assertEqual('waiting',self.verify()['status'])
        job = self.jobs[2]; request = dict(request_id='req-3',article_id=job['id'],
            manifest_hash=job['revision'],status='created')
        with self.ledger._tx() as db:
            db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                       ('req-3',job['id'],'article',json.dumps(request)))
        self.ledger.mark_delivered('req-3',{'scope':self.scope,'parts':[{'verified':True}]},
                                   '1793000003.123456')
        ready = self.verify(); self.verify()
        self.assertEqual('verified',ready['status'])
        self.assertEqual(3,len(self.sent))
        self.assertTrue(all('本文・画像を含む対象版' in text for text in self.sent))
        self.assertTrue(all('本人承認ではありません' in text for text in self.sent))
        receipt = json.loads((self.root/'supplemental-verifications'/
                              'apparel-2026-11-16-ready.json').read_text())
        self.assertEqual('追加batch費用fixture',receipt['reportedCostText'])
        self.assertEqual(hashlib.sha256(self.sent[-1].encode()).hexdigest(),receipt['textHash'])

    def test_progress_reports_current_published_state_without_blanket_preapproval_claim(self):
        self.jobs[0]['approval'] = {'revision':self.jobs[0]['revision'],'action':'approved',
                                    'user_id':'owner'}
        self.jobs[0]['publication'] = {'revision':self.jobs[0]['revision'],'verified':True,
            'readback':{'verified':True,'fingerprint':self.jobs[0]['revision']}}
        self.deliver(1)
        result = self.verify()
        self.assertEqual('waiting',result['status'])
        self.assertEqual(1,len(self.sent))
        self.assertIn('公開確認済み',self.sent[0])
        self.assertNotIn('本人承認前',self.sent[0])

    def test_job_failure_notifies_once_with_action_and_cost(self):
        jobs = [dict(job) for job in self.jobs]
        jobs[0].update(stage='error',error={'reason':'image_verification_failed'})
        first = self.verify(jobs); second = self.verify(jobs)
        self.assertEqual('blocked',first['status']); self.assertEqual('blocked',second['status'])
        self.assertEqual(1,len(self.sent))
        self.assertIn('本文・商品画像の確認',self.sent[0])
        self.assertIn('追加batch費用fixture',self.sent[0])
        self.assertEqual(['extra-1'],first['handledAttentionJobIds'])

    def test_source_hold_uses_existing_notice_without_duplicate(self):
        source = {'slots':[{'slot':1,'status':'source_hold','reason':'catalog_product_not_verified'},
                           {'slot':2,'status':'source_hold','reason':'missing_required_destination'},
                           {'slot':3,'status':'source_hold','reason':'apparel_identity_invalid'}]}
        result = self.verify(jobs=[],source_state=source)
        self.assertEqual('source_hold',result['status'])
        self.assertEqual('existing_source_notice',result['notificationStatus'])
        self.assertEqual([],self.sent)


if __name__ == '__main__': unittest.main()
