"""Bounded offline summary contracts; no network, model bodies or source logs."""
from datetime import datetime, timezone
import json
import hashlib
import sqlite3
from pathlib import Path
import tempfile
import unittest

from seo_summary import build_seo_summary, summary, JST, manager_usage, manager_usage_summary

NOW = datetime(2026, 11, 3, 21, tzinfo=JST)


class SeoSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.seo = Path(self.tmp.name) / 'seo'
        self.editorial = Path(self.tmp.name) / 'editorial'
        (self.seo / 'reports').mkdir(parents=True)
        (self.editorial / 'usage').mkdir(parents=True)

    def report(self, day, text, suffix='astra'):
        p = self.seo / 'reports' / f'agent-campgearlab-seo-{day}-{suffix}.md'
        p.write_text(text)
        return p

    def usage(self, runs):
        (self.seo / 'usage.json').write_text(json.dumps(dict(runs=runs)))

    def run_record(self, at, kind='operations', model='gpt-6-astra'):
        return dict(startedAt=at, finishedAt=at, kind=kind, models=[dict(model=model,
            inputTokens=100, cachedInputTokens=30, outputTokens=20,
            codexCreditsEstimate=1.5, apiUsdEstimate=.02)],
            codexCreditsEstimate=1.5, actualUsd=None)

    def build(self, kind='weekly', now=NOW):
        return build_seo_summary(self.seo, self.editorial, kind, now)

    def test_scoped_weekly_latest_three_and_labeled_excerpts_only(self):
        for day in ('2026-10-27', '2026-10-28', '2026-10-30', '2026-11-01', '2026-11-03', '2026-11-04'):
            self.report(day, f'# Astra\n## 実施内容\n施策{day}\n## 判断理由\n未確定期間を避けた\n'
                '## 結果・欠測\nGA4は欠測\n## 次の作業\n確定後に確認\n## 過去実験\n99999 clicks\n')
        (self.seo / 'reports' / 'weekly-2026-11-03.md').write_text('DO NOT COPY')
        result = self.build()
        for day in ('2026-10-30', '2026-11-01', '2026-11-03'):
            self.assertIn('施策' + day, result)
        self.assertNotIn('施策2026-10-28', result)
        self.assertNotIn('施策2026-11-04', result)
        self.assertNotIn('99999', result)
        self.assertNotIn('DO NOT COPY', result)
        for label in ('実施内容', '判断理由', '結果・欠測', '次の作業'):
            self.assertIn(label, result)
        self.assertIn('2026-10-28〜2026-11-03', result)

    def test_monthly_calendar_and_aware_usage_jst_boundary(self):
        self.report('2026-10-01', '**実施内容**: 月初の確認\n**翌週方針**: 確定を待つ')
        self.report('2026-09-30', '実施内容: 前月外')
        self.report('2026-11-01', '実施内容: 当月外')
        self.usage([self.run_record('2026-09-30T15:00:00Z'),
                    self.run_record('2026-10-31T14:59:59Z'),
                    self.run_record('2026-10-31T15:00:00Z')])
        result = self.build('monthly')
        self.assertIn('2026-10-01〜2026-10-31', result)
        self.assertIn('月初の確認', result)
        self.assertNotIn('前月外', result)
        self.assertNotIn('当月外', result)
        self.assertIn('入力200', result)
        self.assertIn('credits推定3', result)

    def test_aggregates_by_kind_model_and_keeps_cost_units_distinct(self):
        self.usage([self.run_record('2026-11-01T10:00:00+09:00'),
                    self.run_record('2026-11-02T10:00:00+09:00'),
                    self.run_record('2026-11-02T10:00:00+09:00', 'implementation', 'gpt-6-sol')])
        (self.editorial / 'usage' / 'a.json').write_text(json.dumps(dict(at=NOW.isoformat(),
            calls=[dict(responseId='msg_privateid', model='claude-sonnet-4-6', input=12, output=5,
                        usage=dict(cache_read_input_tokens=3), actualUSD=None)], actualInvoiceUsd=None)))
        result = self.build()
        self.assertIn('operations / gpt-6-astra', result)
        self.assertIn('入力200', result)
        self.assertIn('implementation / gpt-6-sol', result)
        self.assertIn('編集運用・復旧 / claude-sonnet-4-6', result)
        self.assertIn('入力12', result)
        self.assertIn('キャッシュ入力3', result)
        self.assertIn('API比較推定', result)
        self.assertIn('実費ではない', result)
        self.assertIn('実請求USD: 未確認', result)
        self.assertNotIn('msg_privateid', result)

    def test_unknown_dates_missing_numbers_and_missing_roots_are_not_zero(self):
        self.usage([self.run_record(None), self.run_record('2026-11-01T10:00:00')])
        result = self.build()
        self.assertIn('期間未配分', result)
        self.assertNotIn('入力200', result)
        self.assertIn('記録なし', result)
        result = build_seo_summary(None, None, 'weekly', NOW)
        self.assertIn('記録なし', result)
        self.assertNotIn('実行なし', result)
        self.assertNotIn('実請求USD: 0', result)

    def test_invalid_files_oversized_symlinks_safe_and_output_bounded(self):
        self.report('2026-11-03', '## 実施内容\n' + 'あ' * 6000 + '\n## 判断理由\n理由')
        self.report('2026-11-02', 'x' * (128 * 1024 + 1))
        self.report('2026-99-99', '実施内容: 不正日付')
        (self.seo / 'usage.json').write_text('{bad json')
        (self.editorial / 'usage' / 'bad.json').write_text('[]')
        self.report('2026-11-01', '実施内容: /Users/person/private/key.json exp-secret-id ' + 'a' * 64 + '\n'
                    '判断理由: sourcePaths /tmp/private.log\n結果・欠測: api_key=SECRET_VALUE\n次の作業: 記録確認')
        outside = Path(self.tmp.name) / 'outside'
        outside.write_text('実施内容: SYMLINK_SECRET')
        (self.seo / 'reports' / 'agent-campgearlab-seo-2026-10-31-link.md').symlink_to(outside)
        result = self.build()
        self.assertLessEqual(len(result), 4500)
        self.assertIn('省略', result)
        for private in ('/Users/', '/tmp/', 'SECRET_VALUE', 'exp-secret-id', 'a' * 64, 'SYMLINK_SECRET'):
            self.assertNotIn(private, result)

    def test_finish_preferred_start_fallback_future_excluded_and_missing_partial(self):
        first = self.run_record('2026-10-01T12:00:00+09:00')
        first['finishedAt'] = '2026-11-01T12:00:00+09:00'
        second = self.run_record('2026-11-02T12:00:00+09:00')
        second['finishedAt'] = None
        second['models'][0].update(inputTokens=None, codexCreditsEstimate=None, apiUsdEstimate=None)
        self.usage([first, second, self.run_record('2026-11-04T00:00:00+09:00')])
        result = self.build()
        self.assertIn('入力100', result)
        self.assertIn('既知分', result)
        self.assertNotIn('入力300', result)

    def test_entry_and_usage_file_limits_and_untrusted_model_names(self):
        for i in range(40):
            self.report('2026-11-03', '実施内容: 同日の記録' + str(i), str(i))
            (self.editorial / 'usage' / f'{i:03}.json').write_text(json.dumps(dict(at=NOW.isoformat(),
                calls=[dict(model='/Users/private/model', input=1, output=2)])))
        result = self.build()
        self.assertLessEqual(len(result), 4500)
        self.assertNotIn('/Users/', result)
        self.assertIn('省略', result)
        self.assertIn('入力28', result)

    def test_usage_never_follows_sourcepaths_or_displays_provider_bodies(self):
        outside = Path(self.tmp.name) / 'raw-secret.log'
        outside.write_text('NEVER_READ_RAW_SECRET')
        run = self.run_record(NOW.isoformat())
        run['sourcePaths'] = [str(outside)]
        run['models'][0]['content'] = 'NEVER_RENDER_MODEL_BODY'
        self.usage([run])
        text = self.build()
        self.assertNotIn('NEVER_', text)
        self.assertNotIn('raw-secret', text)
        self.assertIn('入力100', text)

    def test_monthly_leap_and_year_boundary(self):
        self.report('2024-02-29', '実施内容: うるう月の確認')
        text = self.build('monthly', datetime(2024, 3, 1, 0, 1, tzinfo=JST))
        self.assertIn('2024-02-01〜2024-02-29', text)
        self.assertIn('うるう月の確認', text)
        text = self.build('monthly', datetime(2027, 1, 1, 0, 1, tzinfo=JST))
        self.assertIn('2026-12-01〜2026-12-31', text)

    def test_inline_sections_stop_at_blank_but_headed_sections_keep_paragraphs(self):
        self.report('2026-11-03', '実施内容: 当日の変更\n同じ段落の補足\n\n'
            '全実験: 87654件\nサイト全体: 98765 clicks\n\n判断理由: 確定待ち\n\n'
            '週次記事: 77777件\n判断理由: 追加確認\n全実験: 66666件\n## 結果・欠測\n第一段落\n\n第二段落も結果\n'
            '## 無関係な見出し\nEXCLUDED\n')
        text = self.build()
        for expected in ('当日の変更', '同じ段落の補足', '第一段落', '第二段落も結果'):
            self.assertIn(expected, text)
        for excluded in ('87654', '98765', '77777', '66666', 'EXCLUDED'):
            self.assertNotIn(excluded, text)

    def test_quoted_urls_including_encoded_query_are_omitted_entirely(self):
        self.report('2026-11-03', '実施内容: 確認 https://example.com/path%3Ftoken%3DENCODED_SECRET\n'
            '判断理由: https%3A%2F%2Fexample.com%2Fpath%3Fkey%3DENCODED_SECRET2\n'
            '結果: [公式](https://example.com/a?secret=PLAIN_SECRET)\n')
        text = self.build()
        for value in ('https', 'ENCODED_SECRET', 'PLAIN_SECRET', 'example.com'):
            self.assertNotIn(value, text)
        self.assertIn('URL省略', text)

    def test_monthly_twelve_dated_judgments_with_explicit_omitted_count(self):
        for i in range(1, 15):
            self.report(f'2026-10-{i:02}', f'実施内容: 作業{i:02}\n判断理由: 理由{i:02}\n結果: 結果{i:02}')
        text = self.build('monthly')
        for i in range(3, 15):
            self.assertIn(f'2026-10-{i:02}', text)
            self.assertIn(f'作業{i:02}', text)
        self.assertNotIn('作業01', text)
        self.assertIn('2件省略', text)
        self.assertLessEqual(len(text), 6000)

    def test_wrapper_slots_and_invalid_clock(self):
        text = summary(dict(seoStateRoot=str(self.seo), stateRoot=str(self.editorial)), 'weekly', NOW)
        for rule in ('月・木14時', '水曜9時', '月曜20時', '木曜20時', '毎月5日20時'):
            self.assertIn(rule, text)
        with self.assertRaises(ValueError):
            self.build('daily')
        with self.assertRaises(ValueError):
            self.build(now=NOW.replace(tzinfo=None))


class ManagerUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'ledger.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, at TEXT, job_id TEXT, kind TEXT, data TEXT)')

    def record(self, fp, status, at='2026-11-03T20:00:00+09:00', usage=None, kind='manager_receipt', **extra):
        row = dict(stateFingerprint=fp * 64, status=status, requestedModel='gpt-6-astra',
                   actualModel=None, usage=usage, actualInvoiceUsd=None)
        if status in ('budget_exhausted', 'input_limit'):
            row = dict(stateFingerprint=fp * 64, status=status)
        row.update(extra)
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO events(at,kind,data) VALUES (?,?,?)', (at, kind, json.dumps(row)))
            if kind == 'manager_receipt':
                db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('editorial_manager:' + fp * 64, json.dumps(row)))
        return row

    def test_dedup_measured_response_and_failed_missing_without_cost_conversion(self):
        self.record('a', 'evaluating')
        usage = dict(input_tokens=100, output_tokens=20, cached_input_tokens=30,
                     cache_write_input_tokens=7, reasoning_tokens=9)
        for status in ('executing', 'completed', 'completed'):
            self.record('a', status, usage=usage, summary='PRIVATE_BODY', nonce='PRIVATE_NONCE')
        self.record('b', 'evaluating');self.record('b', 'provider_failed')
        self.record('c', 'evaluating');self.record('c', 'invalid_decision', usage=dict(input_tokens=5, output_tokens=2))
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = manager_usage(self.root, now=NOW)
        self.assertEqual((3, 2, 2, 1), tuple(result[k] for k in
            ('reservedCalls', 'responseCalls', 'usageCalls', 'missingUsageCalls')))
        self.assertEqual(dict(input_tokens=105, output_tokens=22, cached_input_tokens=30,
                              cache_write_input_tokens=7, reasoning_tokens=9), result['tokens'])
        self.assertEqual(2, result['missingByField']['reasoning_tokens'])
        self.assertIsNone(result['actualModel']);self.assertIsNone(result['actualInvoiceUsd'])
        self.assertIsNone(result['estimatedCredits'])
        self.assertEqual(3, result['actualModelMissingCalls'])
        text = manager_usage_summary(self.root, now=NOW)
        self.assertIn('要求gpt-6-astra', text);self.assertIn('実モデル未確認', text)
        self.assertIn('入力105', text);self.assertIn('usage未取得1件', text)
        self.assertNotIn('PRIVATE_', text);self.assertNotIn('USD 0', text)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_reservation_period_jst_not_later_event_or_meta_time(self):
        self.record('a', 'evaluating', at='2026-09-30T14:59:59Z')
        self.record('a', 'completed', at='2026-10-02T00:00:00+09:00', usage=dict(input_tokens=900))
        self.record('b', 'evaluating', at='2026-09-30T15:00:00Z')
        self.record('b', 'completed', at='2026-10-01T01:00:00+09:00', usage=dict(input_tokens=10))
        self.record('c', 'evaluating', at='2026-10-31T15:00:00Z')
        self.record('c', 'completed', at='2026-11-01T01:00:00+09:00', usage=dict(input_tokens=800))
        result = manager_usage(self.root, kind='monthly', now=NOW)
        self.assertEqual(1, result['reservedCalls']);self.assertEqual(10, result['tokens']['input_tokens'])
        self.assertEqual('2026-10-01', result['startDate']);self.assertEqual('2026-10-31', result['endDate'])

    def test_only_operating_ledger_receipts_no_implementation_artifacts(self):
        self.record('a', 'evaluating');self.record('a', 'completed', usage=dict(input_tokens=10))
        self.record('b', 'evaluating', kind='operator_reconciliation')
        self.record('b', 'completed', usage=dict(input_tokens=999), kind='operator_reconciliation')
        folder = self.root / 'operator-reconciliations';folder.mkdir()
        (folder / 'connection-test.json').write_text(json.dumps(dict(usage=dict(input_tokens=999999))))
        result = manager_usage(self.root, now=NOW)
        self.assertEqual(1, result['reservedCalls']);self.assertEqual(10, result['tokens']['input_tokens'])

    def test_failed_but_measured_usage_and_missing_fields_not_zero(self):
        self.record('a', 'evaluating');self.record('a', 'provider_failed', usage=dict(input_tokens=0, output_tokens=3))
        result = manager_usage(self.root, now=NOW)
        self.assertEqual(1, result['responseCalls']);self.assertEqual(0, result['tokens']['input_tokens'])
        self.assertIsNone(result['tokens']['reasoning_tokens'])
        self.assertEqual(1, result['missingByField']['reasoning_tokens'])
        self.assertIsNone(result['actualInvoiceUsd'])

    def test_future_naive_malformed_and_no_reservation_are_not_usage_calls(self):
        self.record('a', 'evaluating', at='2026-11-04T00:00:00+09:00')
        self.record('a', 'completed', at='2026-11-04T00:00:01+09:00', usage=dict(input_tokens=999))
        self.record('b', 'evaluating', at='2026-11-03T20:00:00')
        self.record('b', 'completed', at='2026-11-03T20:00:01', usage=dict(input_tokens=999))
        self.record('c', 'budget_exhausted')
        result = manager_usage(self.root, now=NOW)
        self.assertEqual(0, result['reservedCalls']);self.assertIsNone(result['tokens']['input_tokens'])
        self.assertTrue(result['incomplete'])

    def test_missing_corrupt_or_symlink_ledger_is_unknown_and_never_created(self):
        missing = self.root / 'missing'
        result = manager_usage(missing, now=NOW)
        self.assertIsNone(result['reservedCalls']);self.assertFalse(missing.exists())
        self.db.unlink();self.db.write_text('not sqlite raw PRIVATE_ERROR')
        self.assertIsNone(manager_usage(self.root, now=NOW)['reservedCalls'])
        self.assertNotIn('PRIVATE_ERROR', manager_usage_summary(self.root, now=NOW))
        self.db.unlink();self.db.symlink_to(self.root / 'missing-db')
        self.assertIsNone(manager_usage(self.root, now=NOW)['reservedCalls'])

    def test_real_reported_model_and_invoice_are_distinct_from_missing(self):
        self.record('a', 'evaluating')
        self.record('a', 'completed', usage=dict(input_tokens=10), actualModel='gpt-6-astra', actualInvoiceUsd=.02)
        measured = manager_usage(self.root, now=NOW)
        self.assertEqual('gpt-6-astra', measured['actualModel'])
        self.assertEqual(.02, measured['actualInvoiceUsd'])
        self.record('b', 'evaluating');self.record('b', 'provider_failed')
        partial = manager_usage(self.root, now=NOW)
        self.assertIsNone(partial['actualInvoiceUsd'])
        self.assertEqual(.02, partial['measuredInvoiceUsd'])
        self.assertIsNone(partial['actualModel'])
        self.assertEqual(1, partial['actualModelMissingCalls'])

    def test_invalid_numeric_fields_are_missing_and_limits_fail_closed(self):
        self.record('a', 'evaluating')
        self.record('a', 'completed', usage=dict(input_tokens=True, output_tokens=-1,
            cached_input_tokens='20', cache_write_input_tokens=float('inf'), reasoning_tokens=0))
        result = manager_usage(self.root, now=NOW)
        self.assertIsNone(result['tokens']['input_tokens'])
        self.assertIsNone(result['tokens']['output_tokens'])
        self.assertEqual(0, result['tokens']['reasoning_tokens'])
        self.record('b', 'evaluating')
        from unittest.mock import patch
        with patch('seo_summary.MAX_ROWS', 1):
            self.assertIsNone(manager_usage(self.root, now=NOW)['reservedCalls'])

    def test_real_budget_denial_shape_is_separate_from_reserved_and_measured(self):
        self.record('a', 'evaluating')
        self.record('a', 'completed', usage=dict(input_tokens=10, output_tokens=2))
        row = self.record('b', 'budget_exhausted')
        self.assertEqual({'stateFingerprint', 'status'}, set(row))
        self.record('b', 'budget_exhausted')
        result = manager_usage(self.root, now=NOW)
        self.assertEqual(1, result['budgetDeniedCount'])
        self.assertEqual((1, 1, 0), tuple(result[k] for k in ('reservedCalls', 'responseCalls', 'missingUsageCalls')))
        self.assertEqual(10, result['tokens']['input_tokens'])
        self.assertEqual('budget_exhausted', result['status'])
        self.assertEqual('partial', result['measurementStatus'])
        text = manager_usage_summary(self.root, now=NOW)
        self.assertIn('予算拒否1件（予約外）', text)
        self.assertIn('入力10', text)
        self.assertIn('状態:予算上限', text)

    def test_inflight_and_reconciliation_status_is_independent_of_measurements(self):
        self.record('a', 'evaluating')
        self.record('b', 'evaluating')
        measured = dict(input_tokens=10, output_tokens=2, cached_input_tokens=0,
                        cache_write_input_tokens=0, reasoning_tokens=1)
        self.record('b', 'executing', usage=measured)
        self.record('c', 'evaluating')
        self.record('c', 'requires_reconciliation', usage=measured)
        self.record('d', 'budget_exhausted')
        result = manager_usage(self.root, now=NOW)
        self.assertEqual('requires_reconciliation', result['status'])
        self.assertEqual(1, result['stateCounts']['evaluating'])
        self.assertEqual(1, result['stateCounts']['executing'])
        self.assertEqual(1, result['stateCounts']['requires_reconciliation'])
        self.assertEqual(2, result['pendingCalls'])
        self.assertEqual(1, result['reconciliationRequiredCount'])
        self.assertEqual(1, result['budgetDeniedCount'])
        self.assertEqual(3, result['reservedCalls'])
        self.assertEqual(20, result['tokens']['input_tokens'])
        text = manager_usage_summary(self.root, now=NOW)
        self.assertIn('状態:要照合', text)
        self.assertIn('入力20', text)
        self.assertIn('要照合1件', text)
        self.record('a', 'completed', usage=measured)
        self.record('b', 'completed', usage=measured)
        self.record('c', 'completed', usage=measured)
        final = manager_usage(self.root, now=NOW)
        self.assertEqual('ok', final['status'])
        self.assertEqual('available', final['measurementStatus'])
        self.assertEqual(0, final['pendingCalls'])
        self.assertEqual(0, final['reconciliationRequiredCount'])
        self.assertEqual(30, final['tokens']['input_tokens'])

    def test_old_unfinished_execution_is_visible_but_not_billed_in_new_window(self):
        self.record('a', 'evaluating', at='2026-10-01T00:00:00+09:00')
        self.record('a', 'executing', at='2026-10-01T00:00:01+09:00', usage=dict(input_tokens=900))
        result = manager_usage(self.root, now=NOW)
        self.assertEqual('pending', result['status'])
        self.assertEqual(1, result['stateCounts']['executing'])
        self.assertEqual(0, result['reservedCalls'])
        self.assertIsNone(result['tokens']['input_tokens'])
        self.assertEqual('missing', result['measurementStatus'])

    def test_old_failed_state_does_not_override_a_new_completed_state(self):
        self.record('a', 'evaluating');self.record('a', 'provider_failed')
        self.record('b', 'evaluating');self.record('b', 'completed', usage=dict(input_tokens=3))
        result = manager_usage(self.root, now=NOW)
        self.assertEqual('ok', result['status'])
        self.assertEqual(1, result['stateCounts']['provider_failed'])
        self.assertEqual(1, result['missingUsageCalls'])
        self.assertEqual('partial', result['measurementStatus'])
    def test_editorial_window_uses_monday_not_trailing_seven_days(self):
        self.record('a', 'evaluating', at='2026-11-01T20:00:00+09:00')
        self.record('a', 'completed', at='2026-11-01T20:00:01+09:00', usage=dict(input_tokens=50))
        self.record('b', 'evaluating');self.record('b', 'completed', usage=dict(input_tokens=3))
        self.assertEqual(53, manager_usage(self.root, kind='weekly', now=NOW)['tokens']['input_tokens'])
        self.assertEqual(3, manager_usage(self.root, kind='editorial', now=NOW)['tokens']['input_tokens'])


if __name__ == '__main__':
    unittest.main()
