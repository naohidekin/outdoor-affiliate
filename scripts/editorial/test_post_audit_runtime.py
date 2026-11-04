"""Post-publication scheduling tests: temporary state, fake audit and Slack only."""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

from ledger import fingerprint
from runtime import Runtime, atomic, JST
import test_runtime
from test_quality import bundle


class AuditorFake:
    def __init__(self, *results):
        self.results = list(results) or [{'passed': True, 'checks': {'page': True}}]
        self.calls = []

    def check(self, job):
        self.calls.append(copy.deepcopy(job))
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)


class PostAuditRuntimeTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown

    def seed(self, slug='soto', stage='social_held'):
        job = self.runtime.ledger.create_candidate({'slug': slug, 'title': slug})
        b = bundle()
        revision = fingerprint(b)
        job.update(bundle=b, revision=revision, approval={'revision': revision},
                   stage=stage, social={'revision': 'held', 'proposal': {'deliveryMode': 'auto_x'}},
                   publication={'verified': True, 'revision': revision, 'url': 'https://example.test/' + slug,
                                'at': '2026-11-04T12:00:00+09:00',
                                'readback': {'verified': True, 'fingerprint': revision}})
        self.save_job(job)
        return job

    def save_job(self, job):
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, job, 'test_seed')

    def enable(self, *results):
        self.config.update(generationEnabled=False, postPublicationAuditEnabled=True,
                           postPublicationAuditSince='2026-11-04T00:00:00+09:00')
        self.runtime.post_auditor = AuditorFake(*results)
        self.slack.notice = lambda text: (self.slack.notices.append(text) or {'verified': True})
        # Any unexpected model or publisher call is a test failure.
        self.runtime.models = unittest.mock.Mock()
        self.runtime.models.usage = []
        self.runtime.publisher = unittest.mock.Mock(side_effect=AssertionError('publishing forbidden'))

    def receipts(self):
        return list((self.runtime.root / 'post-publication-audits').glob('*.json'))

    def due(self):
        for path in self.receipts():
            value = json.loads(path.read_text())
            value['nextAttemptAt'] = (datetime.now(JST) - timedelta(seconds=1)).isoformat()
            atomic(path, value)

    def test_disabled_by_default_and_constructor_injection(self):
        self.seed()
        auditor = AuditorFake()
        self.config['generationEnabled'] = False
        self.runtime.post_auditor = auditor
        self.runtime.tick()
        self.assertEqual([], auditor.calls)
        runtime = Runtime(self.config, models=self.models, catalog=self.runtime.catalog,
                          slack=self.slack, post_auditor=auditor)
        self.assertIs(runtime.post_auditor, auditor)

    def test_success_final_private_one_per_tick_and_held_unchanged(self):
        first, second = self.seed(), self.seed('second')
        self.enable()
        health = self.runtime.tick()
        self.assertEqual(1, len(self.runtime.post_auditor.calls))
        self.assertEqual('success', health['postPublicationAudits'][0]['status'])
        self.runtime.tick()
        self.runtime.tick()
        self.assertEqual(2, len(self.runtime.post_auditor.calls))
        self.assertEqual([], self.slack.notices)
        for job in (first, second):
            self.assertEqual(job, self.runtime.ledger.get_job(job['id']))
        for path in self.receipts():
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.runtime.models.assert_not_called()
        self.assertEqual([], self.runtime.models.mock_calls)

    def test_failures_bounded_quiet_and_health_attention(self):
        job = self.seed()
        self.enable({'passed': False, 'issues': [{'code': 'missing_image'}]})
        for _ in range(4):
            health = self.runtime.tick()
        self.assertEqual('attention', health['status'])
        self.assertEqual(1, len(self.runtime.post_auditor.calls))
        self.assertEqual(1, len(self.slack.notices))
        for _ in range(4):
            self.due()
            self.runtime.tick()
        self.assertEqual(3, len(self.runtime.post_auditor.calls))
        self.assertEqual(1, len(self.slack.notices))
        self.assertEqual(job, self.runtime.ledger.get_job(job['id']))
        self.assertTrue(health['postPublicationAudits'][0]['action'])

    def test_changed_outcome_recovery_notifies_once(self):
        self.seed()
        self.enable({'passed': False, 'issues': ['broken']}, {'passed': True})
        self.runtime.tick()
        self.due()
        health = self.runtime.tick()
        self.runtime.tick()
        self.assertEqual(2, len(self.slack.notices))
        self.assertEqual('completed', health['status'])

    def test_publication_metadata_and_revision_each_bind_new_audit(self):
        job = self.seed()
        self.enable()
        self.runtime.tick()
        job['publication']['readback']['manualOG'] = 'different-actual-publication'
        self.save_job(job)
        self.runtime.tick()
        job['revision'] = 'b' * 64
        job['publication']['revision'] = job['revision']
        job['publication']['readback']['fingerprint'] = job['revision']
        self.save_job(job)
        self.runtime.tick()
        self.assertEqual(3, len(self.runtime.post_auditor.calls))
        self.assertEqual(3, len(self.receipts()))

    def test_unverified_publication_not_audited(self):
        job = self.seed()
        job['publication']['readback']['verified'] = False
        self.save_job(job)
        self.enable()
        self.runtime.tick()
        self.assertEqual([], self.runtime.post_auditor.calls)

    def test_interrupted_check_requires_reconciliation_without_retry(self):
        self.seed()
        self.enable(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.runtime.tick()
        health = self.runtime.tick()
        self.runtime.tick()
        self.assertEqual(1, len(self.runtime.post_auditor.calls))
        self.assertEqual('requires_reconciliation', health['postPublicationAudits'][0]['status'])
        self.assertEqual('attention', health['status'])
        self.assertEqual(1, len(self.slack.notices))

    def test_unknown_slack_delivery_never_blind_retries_even_on_recovery(self):
        self.seed()
        self.enable({'passed': False, 'issues': ['broken']}, {'passed': True})
        self.slack.notice = unittest.mock.Mock(side_effect=TimeoutError('delivery unknown'))
        self.runtime.tick()
        self.due()
        health = self.runtime.tick()
        self.runtime.tick()
        self.assertEqual(1, self.slack.notice.call_count)
        self.assertEqual('attention', health['status'])
        self.assertEqual('requires_reconciliation', health['postPublicationAudits'][0]['notificationStatus'])

    def test_external_block_unverified_and_check_exception_actionable(self):
        for result in ({'passed': False, 'status': 'unverified', 'issues': ['external_403_captcha']},
                       TimeoutError('external_check_unavailable')):
            with self.subTest(result=result):
                job = self.seed(str(len(self.runtime.ledger.list_jobs())))
                self.enable(result)
                health = self.runtime.tick()
                summary = next(a for a in health['postPublicationAudits'] if a['id'] == job['id'])
                self.assertEqual('unverified', summary['status'])
                self.assertEqual('attention', health['status'])
                self.assertTrue(summary['result']['issues'])

    def test_failure_does_not_skip_existing_social_quality_branch(self):
        job = self.seed(stage='published')
        job['social'] = None
        self.save_job(job)
        self.enable({'passed': False, 'issues': ['bad']})
        self.runtime.make_social = unittest.mock.Mock()
        self.runtime.tick()
        self.runtime.make_social.assert_called_once()

    def test_slack_is_concise_japanese_and_never_raw_evidence(self):
        self.seed()
        self.enable({'passed': False, 'issues': [
            {'code': 'missing_image', 'reason': 'SECRET provider response'},
            {'code': 'post_audit_check_unavailable', 'reason': 'SECRET exception'},
            *[{'code': 'unknown_private_code', 'details': 'SECRET'} for _ in range(8)]],
            'checks': {'private': 'SECRET'}})
        self.runtime.tick()
        text = self.slack.notices[0]
        self.assertIn('不一致', text)
        self.assertIn('30分後', text)
        self.assertIn('画像', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('missing_image', text)
        self.assertNotIn('failed', text)
        self.assertNotIn('{', text)
        self.assertLessEqual(len([line for line in text.splitlines() if line.startswith('・')]), 5)

    def test_inconsistent_or_incomplete_result_never_passes_health(self):
        job = self.seed()
        for result in ({'passed': True, 'status': 'failed'}, {'passed': True, 'status': 'checking'},
                       {'passed': True, 'verified': False}, {'checks': []}):
            with self.subTest(result=result):
                job['publication']['testMetadata'] = result
                self.save_job(job)
                self.enable(result)
                health = self.runtime.tick()
                summary = next(a for a in health['postPublicationAudits'] if a['id'] == job['id'])
                self.assertNotEqual('success', summary['status'])
                self.assertEqual('attention', health['status'])

    def test_unverified_slack_receipt_and_interrupted_notice_do_not_resend(self):
        self.seed()
        self.enable({'passed': False, 'issues': ['broken']})
        self.slack.notice = unittest.mock.Mock(return_value=None)
        self.runtime.tick()
        notice = next((self.runtime.root / 'post-audit-notifications').glob('*.json'))
        marker = json.loads(notice.read_text())
        marker['status'] = 'in_flight'
        atomic(notice, marker)
        self.runtime.tick()
        self.assertEqual(1, self.slack.notice.call_count)
        self.assertEqual('requires_reconciliation', json.loads(notice.read_text())['status'])

    def test_default_auditor_keeps_production_deadline_wrapper(self):
        job = self.seed()
        self.enable()
        self.runtime.post_auditor = None
        with patch('post_publication_audit.PostPublicationAudit') as constructor:
            constructor.return_value.check.return_value = {'passed': True, 'status': 'passed', 'checks': []}
            self.runtime.tick()
            constructor.assert_called_once_with(self.config, self.runtime.env)
            constructor.return_value.check.assert_called_once_with(job)

    def test_wrapper_check_reasons_identify_product_and_store_without_raw_issues(self):
        job = self.seed()
        job['bundle']['products'][0]['name'] = 'SOTO ST-310'
        self.save_job(job)
        self.enable({'passed': False, 'status': 'failed', 'issues': ['SECRET raw issue'], 'checks': [
            {'name': 'destination.0.amazon', 'status': 'failed',
             'reason': 'merchant_destination_or_product_identity_mismatch'},
            {'name': 'destination.0.rakuten', 'status': 'unverified',
             'reason': 'merchant_challenge_unverified'},
            {'name': 'desktop', 'status': 'passed', 'reason': 'SECRET passed check'},
            {'name': 'approved_body', 'status': 'failed', 'reason': 'approved_body_hash_mismatch'}]})
        self.runtime.tick()
        text = self.slack.notices[0]
        self.assertIn('SOTO ST-310／Amazon', text)
        self.assertIn('SOTO ST-310／楽天', text)
        self.assertIn('アクセス制限', text)
        self.assertIn('本文', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('merchant_', text)

    def test_malformed_receipt_preserved_notified_once_other_job_continues(self):
        job, other = self.seed(), self.seed('other')
        self.enable()
        key = fingerprint({'id': job['id'], 'revision': job['revision'], 'publication': job['publication']})
        path = self.runtime.root / 'post-publication-audits' / (key + '.json')
        path.parent.mkdir(mode=0o700)
        path.write_text('{SECRET malformed')
        with patch.object(self.runtime.ledger, 'list_jobs', return_value=[job, other]):
            health = self.runtime.tick()
            self.runtime.tick()
        self.assertEqual('{SECRET malformed', path.read_text())
        self.assertEqual([other], self.runtime.post_auditor.calls)
        self.assertEqual('attention', health['status'])
        self.assertEqual(1, len(self.slack.notices))
        self.assertIn('Codex', self.slack.notices[0])
        self.assertNotIn('SECRET', self.slack.notices[0])

    def test_global_fault_unknown_or_interrupted_notice_never_retries(self):
        self.enable()
        self.slack.notice = unittest.mock.Mock(side_effect=TimeoutError('SECRET'))
        with patch.object(self.runtime, '_post_publication_audits', side_effect=ValueError('SECRET')):
            for _ in range(2):
                health = self.runtime.tick()
            self.assertEqual(1, self.slack.notice.call_count)
            marker = self.runtime.root / 'post-audit-notifications' / 'engine-fault.json'
            value = json.loads(marker.read_text())
            self.assertEqual('unknown', value['status'])
            value['status'] = 'in_flight'
            atomic(marker, value)
            self.runtime.tick()
            self.assertEqual(1, self.slack.notice.call_count)
            self.assertEqual('attention', health['status'])

    def test_historical_job_skipped_new_publication_included(self):
        old, new = self.seed('old'), self.seed('new')
        old['publication']['at'] = '2025-01-01T00:00:00+09:00'
        self.save_job(old)
        self.enable()
        self.runtime.tick()
        self.runtime.tick()
        self.assertEqual([new], self.runtime.post_auditor.calls)
        self.assertEqual([], self.slack.notices)

    def test_explicit_backfill_includes_only_listed_historical_job(self):
        old, backfill = self.seed('old'), self.seed('backfill')
        for job in (old, backfill):
            job['publication']['at'] = '2025-01-01T00:00:00+09:00'
            self.save_job(job)
        self.enable()
        self.config['postPublicationAuditBackfillIds'] = [backfill['id']]
        self.runtime.tick()
        self.runtime.tick()
        self.assertEqual([backfill['id']], [j['id'] for j in self.runtime.post_auditor.calls])

    def test_scope_requires_aware_cutoff_and_valid_backfill_list(self):
        self.seed()
        self.enable()
        for cutoff in (None, 'bad', '2026-11-04T00:00:00'):
            with self.subTest(cutoff=cutoff):
                self.config['postPublicationAuditSince'] = cutoff
                self.assertEqual('attention', self.runtime.tick()['status'])
        self.config['postPublicationAuditSince'] = '2026-11-04T00:00:00+09:00'
        self.config['postPublicationAuditBackfillIds'] = 'article-id'
        self.assertEqual('attention', self.runtime.tick()['status'])
        self.assertEqual([], self.runtime.post_auditor.calls)
        self.assertEqual(1, len(self.slack.notices))

    def test_publication_scope_date_unknown_notifies_and_other_job_continues(self):
        bad, good = self.seed('bad-date'), self.seed('good-date')
        self.enable()
        # UTC timestamp equals the JST activation cutoff, and is included.
        good['publication']['at'] = '2026-11-03T15:00:00Z'
        self.save_job(good)
        for value in (None, 'bad-date', '2026-11-04T00:00:00'):
            bad['publication']['at'] = value
            self.save_job(bad)
            health = self.runtime.tick()
            self.assertEqual('attention', health['status'])
        self.assertEqual([good['id']], [j['id'] for j in self.runtime.post_auditor.calls])
        self.assertEqual(1, len(self.slack.notices))

    def test_final_browser_reason_codes_are_readable_and_positive_check_silent(self):
        job = self.seed()
        text = self.runtime._post_audit_message(job, {
            'status': 'failed', 'nextAttemptAt': None, 'result': {'checks': [
                {'name': 'desktop', 'status': 'failed', 'reason': 'approved_prose_mismatch'},
                {'name': 'mobile', 'status': 'failed', 'reason': 'visible_product_image_not_rendered'},
                {'name': 'desktop', 'status': 'failed', 'reason': 'approved_product_image_not_rendered'},
                {'name': 'mobile', 'status': 'passed', 'reason': 'approved_prose_exact'}]}})
        self.assertIn('本文が承認内容と一致しません', text)
        self.assertIn('公開画面に商品画像が表示されていません', text)
        self.assertIn('承認した商品画像が公開画面に表示されていません', text)
        self.assertNotIn('詳細はCodex', text)
        self.assertNotIn('approved_', text)
        self.assertEqual(3, sum(line.startswith('・') for line in text.splitlines()))


if __name__ == '__main__':
    unittest.main()
