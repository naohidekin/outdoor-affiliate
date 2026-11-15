import json
import copy
import hashlib
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
    def run_check(self, jobs=None, send=None, results=None, cost_text='使用量：fixture',
                  buffer_posting_enabled=False):
        def delivery(text): self.sent.append(text); return {'verified':True,'message_ts':'1793000000.123456'}
        return verify_period(self.root,self.jobs if jobs is None else jobs,'2026-11-20',self.scope,
            send or delivery,now=self.now,cost_text=cost_text,results=results,
            buffer_posting_enabled=buffer_posting_enabled)

    def test_exact_three_reviews_and_delivery_send_one_result_without_approving(self):
        self.assertEqual('verified',self.run_check()['status'])
        self.assertEqual('verified',self.run_check()['status'])
        self.assertEqual(1,len(self.sent))
        self.assertIn('公開は本人承認後',self.sent[0])
        self.assertFalse(any(j.get('approval') for j in self.jobs))

    def test_buffer_ready_notice_and_receipt_bind_route_cost_and_exact_text_before_send(self):
        observed_presend = {}
        def delivery(text):
            self.sent.append(text)
            observed_presend.update(json.loads((self.root/'production-verifications'/
                '2026-11-20-slack-ready.json').read_text()))
            return {'verified':True,'message_ts':'1793000000.123456'}
        result = self.run_check(send=delivery, cost_text='このタスクの使用量・費用：fixture',
                                buffer_posting_enabled=True)
        self.assertEqual('verified', result['status'])
        route = ('SNSは別の本人対象版承認後にBuffer予約、予約後はX実投稿を確認。'
                 '直接X投稿は停止中。')
        self.assertIn(route, self.sent[0])
        self.assertNotIn('SNSは別承認、X投稿は停止中です。', self.sent[0])
        receipt = json.loads((self.root/'production-verifications'/
                              '2026-11-20-slack-ready.json').read_text())
        self.assertEqual('このタスクの使用量・費用：fixture', receipt['reportedCostText'])
        self.assertEqual(self.sent[0], receipt['expectedText'])
        self.assertEqual(hashlib.sha256(self.sent[0].encode()).hexdigest(), receipt['textHash'])
        self.assertEqual('in_flight', observed_presend['status'])
        self.assertEqual(receipt['reportedCostText'], observed_presend['reportedCostText'])
        self.assertEqual(receipt['expectedText'], observed_presend['expectedText'])
        self.assertEqual(receipt['textHash'], observed_presend['textHash'])
        self.run_check(cost_text='変更後の費用', buffer_posting_enabled=True)
        self.assertEqual(1, len(self.sent))

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

    def test_error_job_sends_bounded_failure_once_and_returns_handled_id(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[0].update(stage='error', error={'reason':'source_validation_failed',
                                            'inputKey':'source-v2'})
        result = self.run_check(jobs)
        self.assertEqual('blocked', result['status'])
        self.assertEqual('blocked', result['healthStatus'])
        self.assertEqual('verified', result['notificationStatus'])
        self.assertEqual(['article-0'], result['handledAttentionJobIds'])
        self.assertEqual([], result['handledGlobalReasons'])
        self.assertEqual(1, len(self.sent))
        text = self.sent[0]
        for expected in ('article-0', 'source_validation_failed', '確認済み事実',
                         '商品・画像・リンク証跡', '自動再試行せず', '使用量：fixture', '公開は本人承認後',
                         'X投稿は停止中'):
            self.assertIn(expected, text)
        self.assertEqual('blocked', self.run_check(jobs)['status'])
        self.assertEqual(1, len(self.sent))

    def test_buffer_failure_notice_describes_separate_owner_approval_and_native_check(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[0].update(stage='error', error={'reason':'source_validation_failed'})
        self.run_check(jobs, buffer_posting_enabled=True)
        self.assertIn(
            'SNSは別の本人対象版承認後にBuffer予約、予約後はX実投稿を確認。直接X投稿は停止中。',
            self.sent[0])
        self.assertNotIn('SNSは別承認、X投稿は停止中です。', self.sent[0])
        marker = next((self.root/'production-verifications'/'2026-11-20-failures').glob('*.json'))
        receipt = json.loads(marker.read_text())
        self.assertEqual('使用量：fixture', receipt['reportedCostText'])
        self.assertEqual(self.sent[0], receipt['expectedText'])
        self.assertEqual('blocked', self.run_check(
            jobs, buffer_posting_enabled=True)['status'])
        self.assertEqual(1, len(self.sent))

    def test_held_error_reports_but_normal_owner_review_wait_does_not(self):
        held = copy.deepcopy(self.jobs)
        held[1].update(stage='held', error={'reason':'render_verification_failed'})
        self.assertEqual('blocked', self.run_check(held)['status'])
        review = copy.deepcopy(self.jobs)
        review[1].update(stage='review', error=None)
        other_root = Path(tempfile.mkdtemp(dir=self.tmp.name))
        Ledger(other_root, 'owner')
        result = verify_period(other_root, review, '2026-11-20', self.scope,
                               lambda text: self.sent.append(text), now=self.now,
                               cost_text='fixture', results=None)
        self.assertEqual('waiting', result['status'])

    def test_period_scoped_research_failure_without_job_is_deduplicated(self):
        raw = 'Model request deadline exceeded'
        results = [{'status':'attention','reason':raw,
                    'production':{'status':'blocked','reason':raw}}]
        first = self.run_check(jobs=[], results=results)
        self.assertEqual('blocked', first['status'])
        self.assertEqual([raw], first['handledGlobalReasons'])
        self.assertIn('モデル応答・timeout記録', self.sent[0])
        self.assertNotIn(raw, self.sent[0])
        self.assertEqual([], first['handledAttentionJobIds'])
        self.assertIn('制作候補の調査段階', self.sent[0])
        self.run_check(jobs=[], results=results)
        self.assertEqual(1, len(self.sent))

    def test_budget_hold_is_excluded_and_cost_failure_does_not_skip_notice(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[0].update(stage='error', error={'reason':'model_budget_hold'})
        self.assertEqual('waiting', self.run_check(jobs)['status'])
        self.assertEqual([], self.sent)
        jobs[0]['error'] = {'reason':'model_stage_failed'}
        result = self.run_check(jobs, cost_text=lambda: (_ for _ in ()).throw(ValueError('no cost')))
        self.assertEqual('blocked', result['status'])
        self.assertIn('使用量・費用・予算残量: 未取得', self.sent[0])

    def test_render_and_delivery_failures_get_only_specific_manual_checks(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[0].update(stage='error', error={'reason':'render_verification_failed'})
        jobs[1].update(stage='held', error={'reason':'delivery_receipt_unknown'})
        result = self.run_check(jobs)
        self.assertEqual('blocked', result['status'])
        self.assertIn('renderer出力・readback', self.sent[0])
        self.assertIn('送達receipt・対象scope', self.sent[0])

    def test_changed_failure_notifies_and_repaired_three_ready_gets_success_receipt(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[0].update(stage='error', error={'reason':'source_failed','inputKey':'one'})
        self.run_check(jobs)
        jobs[0]['error'] = {'reason':'stage_failed','inputKey':'two'}
        self.run_check(jobs)
        self.assertEqual(2, len(self.sent))
        self.assertEqual('verified', self.run_check()['status'])
        self.assertEqual(3, len(self.sent))

    def test_failure_before_target_hour_is_not_due(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[0].update(stage='error', error={'reason':'source_failed'})
        result = verify_period(self.root, jobs, '2026-11-20', self.scope,
                               lambda text: self.sent.append(text),
                               now=self.now.replace(hour=8, minute=59), results=[])
        self.assertEqual('not_due', result['status'])
        self.assertEqual([], self.sent)

    def test_unknown_failure_notification_is_never_retried(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[2].update(stage='error', error={'reason':'final_review_failed'})
        def unknown(text):
            self.sent.append(text)
            raise TimeoutError()
        first = self.run_check(jobs, send=unknown)
        second = self.run_check(jobs)
        self.assertEqual('unknown', first['notificationStatus'])
        self.assertEqual('unknown', second['notificationStatus'])
        self.assertEqual(1, len(self.sent))

    def test_next_period_jobless_root_failure_is_not_attached_to_target_period(self):
        results = [{'status':'attention','reason':'next_week_research_failed',
                    'production':{'status':'blocked','reason':'next_week_research_failed'}}]
        result = verify_period(self.root, [], '2026-11-20', self.scope,
                               lambda text: self.sent.append(text),
                               now=datetime(2026,11,27,9,tzinfo=JST), results=results)
        self.assertEqual('waiting', result['status'])
        self.assertEqual([], self.sent)

    def test_unknown_receipt_binds_presend_cost_actions_and_exact_body_hash(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[0].update(stage='error', error={'reason':'render_verification_failed'})
        def unknown(text):
            self.sent.append(text)
            raise TimeoutError()
        result = self.run_check(jobs, send=unknown, cost_text='費用証跡：$1.2345')
        self.assertEqual('unknown', result['notificationStatus'])
        marker = next((self.root/'production-verifications'/'2026-11-20-failures').glob('*.json'))
        receipt = json.loads(marker.read_text())
        self.assertEqual('費用証跡：$1.2345', receipt['reportedCostText'])
        self.assertIn('renderer出力・readback', receipt['nextActions'][0]['action'])
        self.assertEqual(self.sent[0], receipt['expectedText'])
        expected_hash = hashlib.sha256(self.sent[0].encode()).hexdigest()
        self.assertEqual(expected_hash, receipt['textHash'])
        self.assertEqual({'verified':False,'messageId':None,'textHash':expected_hash},
                         receipt['nativeSlack'])

    def test_cost_fallback_is_persisted_before_send(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[1].update(stage='error', error={'reason':'source_failed'})
        self.run_check(jobs, cost_text=lambda: (_ for _ in ()).throw(ValueError()))
        marker = next((self.root/'production-verifications'/'2026-11-20-failures').glob('*.json'))
        receipt = json.loads(marker.read_text())
        self.assertEqual('使用量・費用・予算残量: 未取得', receipt['reportedCostText'])
