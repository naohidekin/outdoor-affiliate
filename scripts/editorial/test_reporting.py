"""Offline scheduling, durable report receipts and calendar collection contracts."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from reporting import Reporter, slot, editorial_report, seo_status, JST
from test_analytics import snapshot


class SlackFake:
    def __init__(self):
        self.messages = []
        self.fail = False

    def notice(self, text):
        self.messages.append(text)
        if self.fail:
            raise TimeoutError('credential must never be persisted')
        return {'verified': True, 'message_ts': '1793700000.123456'}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config = dict(stateRoot=str(root / 'private'), seoStateRoot=str(root / 'seo'), reportsEnabled=True)
        self.slack = SlackFake()
        self.reporter = Reporter(self.config, self.slack)
        self.now = datetime(2026, 11, 5, 20, tzinfo=JST)

    def tearDown(self):
        self.tmp.cleanup()

    def test_slots_use_jst_and_only_current_week_or_previous_calendar_month(self):
        self.assertIsNone(slot('weekly', datetime(2026, 11, 2, 19, 59, tzinfo=JST)))
        self.assertEqual(slot('weekly', datetime(2026, 11, 2, 11, tzinfo=timezone.utc)), '2026-11-02')
        self.assertEqual(slot('weekly', datetime(2026, 11, 8, 23, tzinfo=JST)), '2026-11-02')
        self.assertIsNone(slot('weekly', datetime(2026, 11, 9, 19, tzinfo=JST)))
        self.assertIsNone(slot('editorial', datetime(2026, 11, 5, 19, 59, tzinfo=JST)))
        self.assertEqual(slot('editorial', self.now), '2026-11-02')
        self.assertEqual(slot('editorial', datetime(2026, 11, 8, 21, tzinfo=JST)), '2026-11-02')
        self.assertIsNone(slot('monthly', self.now.replace(hour=19)))
        self.assertEqual(slot('monthly', self.now), '2026-10')
        self.assertEqual(slot('monthly', self.now.replace(day=30)), '2026-10')
        self.assertIsNone(slot('monthly', datetime(2026, 12, 1, 21, tzinfo=JST)))
        self.assertEqual(slot('monthly', datetime(2027, 1, 5, 20, tzinfo=JST)), '2026-12')
        with self.assertRaises(ValueError):
            slot('weekly', datetime(2026, 11, 2, 20))

    def test_disabled_is_default_and_creates_no_receipt_or_send(self):
        cfg = dict(self.config)
        cfg.pop('reportsEnabled')
        self.assertEqual(Reporter(cfg, self.slack).send('weekly', now=self.now)['status'], 'disabled')
        self.assertEqual(self.slack.messages, [])
        self.assertFalse((Path(cfg['stateRoot']) / 'reports').exists())

    def test_manual_and_tick_share_receipt_across_restart_no_duplicate(self):
        monday_morning = datetime(2026, 11, 2, 9, tzinfo=JST)
        self.assertEqual(self.reporter.send('weekly', now=monday_morning)['status'], 'not_due')
        self.assertEqual(self.reporter.send('weekly', now=monday_morning, manual=True)['status'], 'verified')
        self.assertEqual(Reporter(self.config, self.slack).send('weekly', now=self.now)['status'], 'already_verified')
        self.assertEqual(len(self.slack.messages), 1)
        marker = Path(self.config['stateRoot']) / 'reports/weekly/2026-11-02.json'
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(marker.read_text())['status'], 'verified')
        self.assertIn('直近7日の編集作業', self.slack.messages[0])
        self.assertIn('直近28日', self.slack.messages[0])
        self.assertIn('0件とは判定しません', self.slack.messages[0])

    def test_unknown_send_and_inflight_never_auto_resend(self):
        self.slack.fail = True
        self.assertEqual(self.reporter.send('editorial', now=self.now)['status'], 'requires_reconciliation')
        self.slack.fail = False
        self.assertEqual(Reporter(self.config, self.slack).send('editorial', now=self.now, manual=True)['status'], 'requires_reconciliation')
        self.assertEqual(len(self.slack.messages), 1)
        marker = Path(self.config['stateRoot']) / 'reports/editorial/2026-11-02.json'
        self.assertNotIn('credential', marker.read_text())
        self.assertEqual(json.loads(marker.read_text())['status'], 'in_flight')

    def test_monthly_snapshot_is_separate_and_unequal_months_are_reported(self):
        data = snapshot('2026-10-01', '2026-10-31')
        data['collectedAt'] = self.now.isoformat()
        data['previous'].update(startDate='2026-09-01', endDate='2026-09-30')
        data['ga4'].update(startDate='2026-10-01', endDate='2026-10-31')
        data['previousGa4'] = copy.deepcopy(data['ga4'])
        data['previousGa4'].update(startDate='2026-09-01', endDate='2026-09-30')
        source = Path(self.config['seoStateRoot']) / 'metrics/latest.json'
        source.parent.mkdir(parents=True)
        source.write_text('canonical must not change')
        calls = []
        def collect(period, now):
            calls.append((period, now))
            return data
        reporter = Reporter(self.config, self.slack, collector=collect)
        self.assertEqual(reporter.send('monthly', now=self.now)['status'], 'verified')
        self.assertEqual(calls[0][0], '2026-10')
        self.assertEqual(source.read_text(), 'canonical must not change')
        saved = Path(self.config['stateRoot']) / 'analytics/monthly/2026-10/snapshot.json'
        self.assertEqual(json.loads(saved.read_text()), data)
        self.assertIn('2026-10-01〜2026-10-31', self.slack.messages[0])
        self.assertIn('2026-09-01〜2026-09-30', self.slack.messages[0])
        reporter.send('monthly', now=self.now)
        self.assertEqual(len(calls), 1)

    def test_missing_monthly_data_warns_without_zero_or_raw_errors(self):
        reporter = Reporter(self.config, self.slack, collector=lambda *_: (_ for _ in ()).throw(ValueError('secret')))
        self.assertEqual(reporter.send('monthly', now=self.now)['status'], 'data_pending')
        text = self.slack.messages[0]
        self.assertIn('確定データ待ち', text)
        self.assertNotIn('secret', text)
        self.assertNotIn('クリック: 0', text)
        self.assertIn('未接続', text)
        self.assertEqual(reporter.send('monthly', now=self.now)['status'], 'data_pending')
        self.assertEqual(len(self.slack.messages), 1)
        data = snapshot('2026-10-01', '2026-10-31')
        data['collectedAt'] = self.now.isoformat()
        data['previous'].update(startDate='2026-09-01', endDate='2026-09-30')
        reporter.collector = lambda *_: data
        self.assertEqual(reporter.send('monthly', now=self.now, manual=True)['status'], 'verified')
        self.assertEqual(len(self.slack.messages), 2)
        self.assertEqual(reporter.send('monthly', now=self.now)['status'], 'already_verified')

    def test_editorial_keeps_carried_pending_and_counts_publication_timestamp(self):
        jobs = [dict(week='2026-10-26', stage='review', theme={'title': '繰越記事'}),
                dict(week='2026-10-26', stage='social_review', theme={'title': '繰越SNS'}),
                dict(week='2026-10-26', stage='published', theme={'title': '今週公開'},
                     publication={'verified': True, 'at': '2026-11-03T19:52:00+09:00'}),
                dict(week='2026-11-02', stage='published', theme={'title': '過去公開'},
                     publication={'verified': True, 'at': '2026-10-31T19:00:00+09:00'})]
        text = editorial_report(jobs, now=self.now)
        self.assertIn('期間内の公開確認済み: 1件', text)
        self.assertIn('確認待ち（繰越含む）: 1件', text)
        self.assertIn('繰越記事', text)
        self.assertNotIn('過去公開', text)
        self.assertIn('新しい承認ボタンは発行していません', text)

    def test_seo_status_uses_bounded_metadata_not_historical_prose(self):
        root = Path(self.config['seoStateRoot'])
        (root / 'reports').mkdir(parents=True)
        (root / 'reports/latest.json').write_text(json.dumps(dict(generatedAt='2026-11-05T14:01:00+09:00',
            executionStatus='healthy', modelExecuted=False, reason='raw internal reason', report='run-old.md')))
        (root / 'reports/run-old.md').write_text('October historical work must not be copied')
        (root / 'usage.json').write_text(json.dumps({'actualInvoiceUsd': None, 'secret': 'never expose'}))
        text = seo_status(root)
        self.assertIn('正常', text)
        self.assertIn('Astraの新しい判断は行っていません', text)
        self.assertIn('実費未確定', text)
        self.assertNotIn('historical work', text)
        self.assertNotIn('never expose', text)
        self.assertNotIn('raw internal', text)

    def test_monthly_subprocess_is_bounded_and_uses_only_supplied_env(self):
        cfg = dict(self.config, seoRepo='/configured/seo')
        reporter = Reporter(cfg, self.slack, env={'GOOGLE_CREDENTIALS': 'test-only', 'ANTHROPIC_API_KEY': 'unrelated'})
        with patch('reporting.subprocess.run', return_value=SimpleNamespace(returncode=0,
                stdout=json.dumps({'schemaVersion': 1}))) as run:
            reporter._collect_month('2026-10', self.now)
        self.assertEqual(run.call_args.kwargs['timeout'], 240)
        self.assertEqual(run.call_args.kwargs['env']['GOOGLE_CREDENTIALS'], 'test-only')
        self.assertNotIn('ANTHROPIC_API_KEY', run.call_args.kwargs['env'])
        self.assertNotIn('--env-file', run.call_args.args[0])
        with patch('reporting.subprocess.run', side_effect=TimeoutError('raw secret')):
            with self.assertRaisesRegex(ValueError, '^monthly_collection_unavailable$'):
                reporter._collect_month('2026-10', self.now)

    def test_unverified_receipt_is_not_success_and_never_retried(self):
        with patch.object(self.slack, 'notice', return_value={'verified': False, 'message_ts': '1793700000.123456'}) as post:
            self.assertEqual(self.reporter.send('weekly', now=self.now)['status'], 'requires_reconciliation')
            self.assertEqual(self.reporter.send('weekly', now=self.now)['status'], 'requires_reconciliation')
        self.assertEqual(post.call_count, 1)

    def test_unavailable_monthly_daily_refresh_does_not_repeat_warning(self):
        calls = []
        def unavailable(*args):
            calls.append(args)
            raise ValueError('unavailable')
        reporter = Reporter(self.config, self.slack, collector=unavailable)
        reporter.send('monthly', now=self.now)
        reporter.send('monthly', now=self.now.replace(hour=21))
        reporter.send('monthly', now=self.now.replace(day=6))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.slack.messages), 1)

    def test_partial_monthly_current_sources_warn_once_then_full_report_can_complete(self):
        for missing in ('ga4', 'current'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as root:
                config = dict(self.config, stateRoot=str(Path(root) / 'private'))
                slack = SlackFake()
                complete = snapshot('2026-10-01', '2026-10-31')
                complete['collectedAt'] = self.now.isoformat()
                complete['previous'].update(startDate='2026-09-01', endDate='2026-09-30')
                partial = copy.deepcopy(complete)
                partial[missing] = {'status': 'unavailable'}
                calls = []
                def collect(*args):
                    calls.append(args)
                    return partial if len(calls) < 3 else complete
                reporter = Reporter(config, slack, collector=collect)
                self.assertEqual(reporter.send('monthly', now=self.now)['status'], 'data_pending')
                marker = Path(config['stateRoot']) / 'reports/monthly/2026-10.json'
                self.assertEqual(json.loads(marker.read_text())['status'], 'verified_unavailable')
                self.assertEqual(reporter.send('monthly', now=self.now, manual=True)['status'], 'data_pending')
                self.assertEqual(len(slack.messages), 1)
                self.assertEqual(reporter.send('monthly', now=self.now, manual=True)['status'], 'verified')
                self.assertEqual(json.loads(marker.read_text())['status'], 'verified')
                self.assertEqual(len(slack.messages), 2)
                self.assertEqual(reporter.send('monthly', now=self.now, manual=True)['status'], 'already_verified')
                self.assertEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
