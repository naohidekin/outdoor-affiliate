"""Offline contracts for deterministic model usage and cost reporting."""
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from model_budget import ModelBudget
from production_schedule import ProductionSchedule
from usage_cost_report import JST, usage_cost_report, usage_cost_summary


class UsageCostReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
        self.schedule = dict(weekday=4, hour=9, effectiveFrom='2026-11-13',
                             initialProductionAt='2026-11-11T09:00:00+09:00')
        self.budget_config = {
            'article': {'calls': 10, 'inputTokens': 1000, 'outputTokens': 100},
            'period': {'calls': 20, 'inputTokens': 2000, 'outputTokens': 200},
            'requestInputBytes': 10000, 'warningRatio': .75,
        }
        self.config = {
            'productionSchedule': self.schedule,
            'modelBudget': self.budget_config,
            'modelUsagePricing': {
                'model-a': {'inputUsdPerMillion': 1, 'outputUsdPerMillion': 2,
                            'cacheReadUsdPerMillion': .1, 'cacheWriteUsdPerMillion': 1.25,
                            'source': 'official fixture', 'checkedAt': '2026-11-01T00:00:00+09:00',
                            'ratesValidUntil': '2026-12-31'}
            },
        }
        self.now = datetime(2026, 11, 16, 20, tzinfo=JST)

    def tearDown(self):
        self.tmp.cleanup()

    def _usage_file(self, name, at, calls, **extra):
        folder = self.root / 'usage'
        folder.mkdir(exist_ok=True)
        (folder / name).write_text(json.dumps({'at': at, 'calls': calls, **extra}))

    def test_weekly_fri_thu_deduplicates_stage_receipt_and_keeps_unattributed_old_records(self):
        call = {'responseId': 'r1', 'actualModel': 'model-a', 'articleId': 'article-1',
                'stage': 'draft', 'usage': {'input_tokens': 100, 'output_tokens': 20,
                'cache_read_input_tokens': 30, 'cache_write_input_tokens': 10},
                'actualUSD': .02, 'actualInvoiceUsd': .018}
        self._usage_file('one.json', '2026-11-07T10:00:00+09:00', [call])
        self._usage_file('legacy.json', '2026-11-08T10:00:00+09:00', [{
            'responseId': 'r2', 'model': 'unknown-exact-id',
            'usage': {'input_tokens': 45, 'output_tokens': 5}}])
        stage = {'jobId': 'article-1', 'stage': 'draft', 'usageBatches': [{
            'recordedAt': '2026-11-07T10:01:00+09:00', 'records': [call]}]}
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            db.execute('INSERT INTO meta VALUES (?,?)',
                       ('stage_journal:v1:' + 'a' * 64, json.dumps(stage)))

        result = usage_cost_report(self.root, self.config, kind='weekly', now=self.now)
        self.assertEqual(result['window'], {'start': '2026-11-06', 'end': '2026-11-12',
                                            'timezone': 'Asia/Tokyo', 'basis': 'completed_fri_thu'})
        self.assertEqual(result['totals']['calls'], 2)
        self.assertEqual(result['models']['model-a']['inputTokens'], 100)
        self.assertEqual(result['models']['model-a']['cacheReadTokens'], 30)
        self.assertEqual(result['stages']['draft']['calls'], 1)
        self.assertEqual(result['missingAttribution']['articleCalls'], 1)
        self.assertEqual(result['costs']['actualInvoiceUSD']['value'], .018)
        self.assertEqual(result['costs']['actualUSD']['value'], .02)
        self.assertEqual(result['costs']['estimatedUSD']['basis'], 'current_rate_rough_estimate')
        self.assertEqual(result['costs']['unknownModels'], ['unknown-exact-id'])
        self.assertIsNone(result['subscription']['percent'])
        self.assertEqual(result['subscription']['reason'], 'subscription_denominator_not_available')
        self.assertEqual(result['subscription']['scope'], 'task_attributed_only')
        self.assertIsNone(result['subscription']['chatgptCodex']['percent'])
        text = usage_cost_summary(self.root, self.config, kind='weekly', now=self.now)
        for expected in ('2026/11/06（金）〜2026/11/12（木）', 'model-a', 'unknown-exact-id',
                         '実請求USD', '1/2件のみ', '実測USD', '現行単価による概算',
                         '帰属不明 article 1件／stage 1件', 'サブスク使用率: 算出不可'):
            self.assertIn(expected, text)

    def test_missing_usage_unknown_reservation_and_budget_snapshot_are_explicit(self):
        budget = ModelBudget(self.root, ProductionSchedule(self.schedule), self.budget_config)
        with budget.scope('article-x', 'polish', now=datetime(2026, 11, 13, 10, tzinfo=JST)):
            reservation = budget.reserve({'model': 'model-a', 'max_tokens': 25, 'messages': []})
        budget.settle(reservation, usage=None, outcome='unknown')
        self._usage_file('missing.json', '2026-11-10T10:00:00+09:00', [{
            'responseId': 'r-missing', 'actualModel': None, 'requestedModel': 'model-a',
            'articleId': 'article-x', 'stage': 'final_review', 'usage': None}])
        result = usage_cost_report(self.root, self.config, kind='weekly', now=self.now)
        self.assertEqual(result['missingUsage']['calls'], 1)
        self.assertEqual(result['reservations']['unknownCalls'], 1)
        self.assertEqual(result['reservations']['label'], 'reserved_not_measured')
        self.assertEqual(result['budget']['periodKey'], '2026-11-13')
        self.assertIn('ratios', result['budget']['period'])
        self.assertIn('article-x', result['budget']['articles'])
        text = usage_cost_summary(self.root, self.config, kind='weekly', now=self.now)
        self.assertIn('usage欠測1件', text)
        self.assertIn('予約値のみ・未実測1件', text)
        self.assertIn('現在production period（2026-11-13）', text)

    def test_exact_model_pricing_only_and_invalid_pricing_fails_closed(self):
        self._usage_file('models.json', '2026-11-11T10:00:00+09:00', [{
            'responseId': 'a', 'actualModel': 'model-a-v2',
            'usage': {'input_tokens': 10, 'output_tokens': 1}}])
        result = usage_cost_report(self.root, self.config, kind='weekly', now=self.now)
        self.assertIsNone(result['costs']['estimatedUSD']['value'])
        self.assertEqual(result['costs']['unknownModels'], ['model-a-v2'])
        bad = dict(self.config, modelUsagePricing={'model-a': {'inputUsdPerMillion': 1}})
        with self.assertRaisesRegex(ValueError, 'model_usage_pricing_invalid'):
            usage_cost_report(self.root, bad, kind='weekly', now=self.now)

    def test_production_and_monthly_public_api_windows(self):
        production = usage_cost_report(self.root, self.config, kind='production', now=self.now,
                                       period_key='2026-11-13')
        self.assertEqual((production['window']['start'], production['window']['end']),
                         ('2026-11-13', '2026-11-19'))
        configured = usage_cost_report(self.root, self.config, kind='production', now=self.now)
        self.assertEqual(configured['window']['start'], '2026-11-13')
        monthly = usage_cost_report(self.root, self.config, kind='monthly', now=self.now)
        self.assertEqual((monthly['window']['start'], monthly['window']['end']),
                         ('2026-10-01', '2026-10-31'))
        thursday = usage_cost_report(
            self.root, self.config, kind='weekly',
            now=datetime(2026, 11, 19, 20, tzinfo=JST))
        self.assertEqual((thursday['window']['start'], thursday['window']['end']),
                         ('2026-11-13', '2026-11-19'))

    def test_expired_rate_is_unknown_not_zero_or_stale_estimate(self):
        self._usage_file('expired.json', '2027-01-01T10:00:00+09:00', [{
            'responseId': 'expired', 'actualModel': 'model-a',
            'usage': {'input_tokens': 10, 'output_tokens': 1}}])
        result = usage_cost_report(
            self.root, self.config, kind='production', period_key='2027-01-01',
            now=datetime(2027, 1, 2, 10, tzinfo=JST))
        self.assertIsNone(result['costs']['estimatedUSD']['value'])
        self.assertEqual(result['costs']['unknownModels'], ['model-a'])

    def test_registered_codex_task_counters_are_not_summed_or_exposed_by_id(self):
        folder = self.root / 'task-usage'
        folder.mkdir()
        (folder / 'codex-task.json').write_text(json.dumps({
            'source': 'codex_local_thread_counters',
            'unit': 'local_cumulative_token_counter',
            'observedAt': '2026-11-16T19:55:00+09:00',
            'scope': 'registered_camp_task_threads_only', 'taskAttribution': True,
            'threads': [
                {'id': 'do-not-render-main-id', 'role': 'main', 'counter': 1000,
                 'periodBaseline': 400, 'delta': 600,
                 'baselineAt': '2026-11-13T09:00:00+09:00', 'coveragePartial': True},
                {'id': 'do-not-render-helper-id', 'role': 'helper', 'counter': 300,
                 'periodBaseline': 100, 'delta': 200,
                 'baselineAt': '2026-11-13T09:00:00+09:00', 'coveragePartial': True}],
            'subscriptionPercent': None, 'attributionOverlapUnknown': True,
        }))
        task = usage_cost_report(
            self.root, self.config, kind='weekly', now=self.now
        )['subscription']['chatgptCodex']['taskUsage']
        self.assertEqual(task['main']['delta'], 600)
        self.assertEqual([row['delta'] for row in task['helpers']], [200])
        self.assertNotIn('total', task)
        text = usage_cost_summary(self.root, self.config, kind='weekly', now=self.now)
        self.assertIn('親delta 600', text)
        self.assertIn('helper各delta 200', text)
        self.assertIn('親子重複不明のため合算なし', text)
        self.assertNotIn('do-not-render', text)

    def test_usage_requires_both_sides_and_prices_cache_ttl_without_double_count(self):
        self.config['modelUsagePricing']['model-a'].update(
            cacheWrite5mUsdPerMillion=1.25, cacheWrite1hUsdPerMillion=2)
        self._usage_file('cache.json', '2026-11-10T10:00:00+09:00', [
            {'responseId': 'good', 'actualModel': 'model-a', 'usage': {
                'input_tokens': 100, 'output_tokens': 10,
                'cache_creation_input_tokens': 30,
                'cache_creation': {'ephemeral_5m_input_tokens': 10,
                                   'ephemeral_1h_input_tokens': 20}}},
            {'responseId': 'missing-output', 'actualModel': 'model-a',
             'usage': {'input_tokens': 9}},
            {'responseId': 'gemini-shape', 'actualModel': 'model-a', 'usage': {
                'prompt_tokens': 100, 'completion_tokens': 4, 'cached_prompt_tokens': 25}},
        ])
        result = usage_cost_report(self.root, self.config, kind='weekly', now=self.now)
        self.assertEqual(result['models']['model-a']['cacheWriteTokens'], 30)
        self.assertEqual(result['models']['model-a']['cacheReadTokens'], 25)
        self.assertEqual(result['models']['model-a']['inputTokens'], 175)
        self.assertEqual(result['missingUsage']['calls'], 1)
        expected = (100 + 75) / 1e6 + 14 * 2 / 1e6 + 25 * .1 / 1e6 + 10 * 1.25 / 1e6 + 20 * 2 / 1e6
        self.assertAlmostEqual(result['costs']['estimatedUSD']['value'], expected)

    def test_future_usage_nan_cost_and_missing_budget_db_fail_closed(self):
        self._usage_file('future.json', '2026-11-17T10:00:00+09:00', [{
            'responseId': 'future', 'actualModel': 'model-a',
            'usage': {'input_tokens': 10, 'output_tokens': 1}, 'actualUSD': math.nan}])
        # No budget schema has been initialized in this fixture.
        result = usage_cost_report(self.root, self.config, kind='production', now=self.now,
                                   period_key='2026-11-13')
        self.assertEqual(result['totals']['calls'], 0)
        self.assertIsNone(result['reservations']['unknownCalls'])

    def test_baseline_only_codex_snapshot_shows_counter_not_a_fake_delta(self):
        folder = self.root / 'task-usage'; folder.mkdir()
        (folder / 'codex-task.json').write_text(json.dumps({
            'source': 'codex_local_thread_counters', 'unit': 'local_cumulative_token_counter',
            'observedAt': '2026-11-16T19:55:00+09:00',
            'scope': 'registered_camp_task_threads_only', 'taskAttribution': True,
            'threads': [{'id': 'x', 'role': 'main', 'counter': 1234,
                         'periodBaseline': 1234, 'delta': None, 'status': 'baseline_only',
                         'baselineAt': '2026-11-16T19:00:00+09:00', 'coveragePartial': True}],
            'subscriptionPercent': None, 'attributionOverlapUnknown': True,
        }))
        text = usage_cost_summary(self.root, self.config, kind='weekly', now=self.now)
        self.assertIn('累積counter 1,234', text)
        self.assertIn('期間delta未取得', text)
        self.assertIn('report窓とは別', text)

    def test_budget_article_lines_use_job_title_and_never_raw_sha_scope(self):
        budget = ModelBudget(self.root, ProductionSchedule(self.schedule), self.budget_config)
        sha = 'a' * 64
        with budget.scope(sha, 'draft', now=datetime(2026, 11, 13, 10, tzinfo=JST)):
            reservation = budget.reserve({'model': 'model-a', 'max_tokens': 5, 'messages': []})
        budget.settle(reservation, {'input_tokens': 2, 'output_tokens': 1})
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('INSERT INTO jobs VALUES (?,?)', (sha, json.dumps({
                'id': sha, 'theme': {'slug': 'safe-slug', 'title': '安全な記事名'}})))
        text = usage_cost_summary(self.root, self.config, kind='weekly', now=self.now)
        self.assertIn('記事予算 安全な記事名', text)
        self.assertNotIn(sha, text)

    def test_explicit_null_actual_model_is_unknown_while_legacy_model_is_actual(self):
        self._usage_file('identity.json', '2026-11-10T10:00:00+09:00', [
            {'responseId': 'new', 'actualModel': None, 'model': 'model-a',
             'usage': {'input_tokens': 10, 'output_tokens': 1}},
            {'responseId': 'legacy', 'model': 'model-a',
             'usage': {'input_tokens': 20, 'output_tokens': 2}},
        ])
        result = usage_cost_report(self.root, self.config, kind='weekly', now=self.now)
        self.assertEqual(result['models']['実モデル未確認']['calls'], 1)
        self.assertEqual(result['models']['model-a']['calls'], 1)

    def test_response_id_is_canonicalized_before_adjacent_week_filtering(self):
        call = {'responseId': 'cross-week', 'actualModel': 'model-a',
                'articleId': 'article-1', 'stage': 'draft',
                'usage': {'input_tokens': 100, 'output_tokens': 10}}
        # Canonical usage file wins even though its save timestamp crossed Friday.
        self._usage_file('canonical.json', '2026-11-13T00:01:00+09:00', [call])
        stage = {'jobId': 'article-1', 'stage': 'draft', 'usageBatches': [{
            'recordedAt': '2026-11-12T23:59:00+09:00', 'records': [call]}]}
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            db.execute('INSERT INTO meta VALUES (?,?)',
                       ('stage_journal:v1:' + 'b' * 64, json.dumps(stage)))
        prior = usage_cost_report(self.root, self.config, kind='weekly', now=self.now)
        following = usage_cost_report(
            self.root, self.config, kind='weekly',
            now=datetime(2026, 11, 19, 20, tzinfo=JST))
        self.assertEqual(prior['totals']['calls'] + following['totals']['calls'], 1)
        expected = 100 / 1e6 + 10 * 2 / 1e6
        prior_cost = prior['costs']['estimatedUSD']['value'] or 0
        following_cost = following['costs']['estimatedUSD']['value'] or 0
        self.assertAlmostEqual(prior_cost + following_cost, expected)


if __name__ == '__main__':
    unittest.main()
