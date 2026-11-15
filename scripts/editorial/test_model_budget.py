"""Durable model-attempt budget contracts using only temporary SQLite fixtures."""
from datetime import datetime, timedelta, timezone
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from model_budget import BudgetHold, DEFAULTS, ModelBudget
from production_schedule import ProductionSchedule


JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 18, 10, tzinfo=JST)


def config(**values):
    result = copy.deepcopy(DEFAULTS)
    for name, value in values.items():
        group, key = name.split('__', 1)
        if group == 'request':
            result['requestInputBytes'] = value
        else:
            result[group][key] = value
    return result


class ModelBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        self.root.mkdir()
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,data TEXT)')
        self.schedule = ProductionSchedule()

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def payload(text='hello', max_tokens=10):
        return {'model': 'fixture-model', 'max_tokens': max_tokens,
                'messages': [{'role': 'user', 'content': text}]}

    def test_scope_is_required_and_same_payload_retries_persist_across_startup(self):
        limits = config(article__calls=2, period__calls=10)
        budget = ModelBudget(self.root, self.schedule, limits)
        with self.assertRaisesRegex(RuntimeError, 'model budget scope required'):
            budget.reserve(self.payload())
        with budget.scope('article-1', 'draft', NOW):
            first = budget.reserve(self.payload())
            second = budget.reserve(self.payload())
        self.assertNotEqual(first, second)

        restarted = ModelBudget(self.root, self.schedule, limits)
        with restarted.scope('article-1', 'polish', NOW), self.assertRaises(BudgetHold) as held:
            restarted.reserve(self.payload())
        self.assertEqual('article_calls_cap', held.exception.reason_code)
        self.assertEqual('article', held.exception.budget_scope)
        self.assertEqual(3, held.exception.projected)
        self.assertEqual('model_budget_hold', str(held.exception))
        summary = restarted.inspect(NOW)
        self.assertEqual(2, summary['period']['calls'])
        self.assertEqual(2, summary['articles']['article-1']['calls'])
        self.assertEqual(2, summary['reservationsByStatus']['reserved'])

    def test_standalone_budget_without_jobs_table_keeps_ordinary_scope_contract(self):
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            db.execute('DROP TABLE jobs')
        budget = ModelBudget(self.root, self.schedule)
        with budget.scope('ordinary-standalone', 'draft', NOW):
            reservation = budget.reserve(self.payload())
        self.assertIsInstance(reservation, str)

    def test_exact_usage_replaces_upper_bounds_and_unknown_keeps_reservation(self):
        budget = ModelBudget(self.root, self.schedule)
        with budget.scope('article-1', 'draft', NOW):
            exact = budget.reserve(self.payload('known', max_tokens=100))
            unknown = budget.reserve(self.payload('unknown', max_tokens=200))
        before = budget.inspect(NOW)
        self.assertEqual(300, before['period']['outputTokens'])
        settled = budget.settle(exact, {
            'input_tokens': 10, 'output_tokens': 7,
            'cache_creation_input_tokens': 3, 'cache_read_input_tokens': 2,
        }, outcome='success')
        self.assertEqual(15, settled['chargedInputTokens'])
        self.assertEqual(7, settled['chargedOutputTokens'])
        unresolved = budget.settle(unknown, {'input_tokens': 'bad'}, outcome='failed')
        self.assertEqual('unknown', unresolved['status'])
        after = budget.inspect(NOW)
        self.assertEqual(207, after['period']['outputTokens'])
        self.assertGreater(after['period']['inputTokens'], 15)
        self.assertEqual({'settled': 1, 'unknown': 1}, after['reservationsByStatus'])
        self.assertEqual('already_unknown', budget.settle(
            unknown, {'input_tokens': 1, 'output_tokens': 1})['status'])

    def test_article_and_period_caps_are_atomic_under_concurrency(self):
        limits = config(article__calls=4, period__calls=1)
        first = ModelBudget(self.root, self.schedule, limits)
        second = ModelBudget(self.root, self.schedule, limits)

        def attempt(budget, article):
            try:
                with budget.scope(article, 'draft', NOW):
                    return 'reserved', budget.reserve(self.payload())
            except BudgetHold as error:
                return 'held', error.reason_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda args: attempt(*args),
                                     ((first, 'article-1'), (second, 'article-2'))))
        self.assertEqual(['held', 'reserved'], sorted(value[0] for value in outcomes))
        self.assertIn('period_calls_cap', [value[1] for value in outcomes])
        self.assertEqual(1, first.inspect(NOW)['period']['calls'])

    def test_request_byte_hold_and_warning_events_are_content_free_and_deduplicated(self):
        probe = self.payload('x' * 100)
        permissive = ModelBudget(self.root, self.schedule)
        with permissive.scope('probe', 'draft', NOW):
            probe_id = permissive.reserve(probe)
        estimated = permissive.inspect(NOW)['articles']['probe']['inputTokens']
        limits = config(request__inputBytes=estimated, article__inputTokens=estimated * 2,
                        period__inputTokens=estimated * 10)
        budget = ModelBudget(self.root, self.schedule, limits)
        with budget.scope('article-1', 'draft', NOW):
            budget.reserve(probe)
            budget.reserve(probe)
        warnings = budget.pending_events()
        article_warnings = [event for event in warnings
                            if event['level'] == 'warning' and event['budgetScope'] == 'article']
        self.assertEqual(1, len(article_warnings))
        rendered = str(warnings)
        self.assertNotIn('x' * 20, rendered)
        self.assertNotIn('fixture-model', rendered)

        too_large = self.payload('y' * 101)
        with budget.scope('article-2', 'draft', NOW), self.assertRaises(BudgetHold) as held:
            budget.reserve(too_large)
        self.assertEqual('request_input_bytes_cap', held.exception.reason_code)
        self.assertNotIn('article-2', budget.inspect(NOW)['articles'])
        # The independent probe reservation remains durable and is not released by this hold.
        self.assertEqual('unknown', permissive.settle(probe_id, outcome='unknown')['status'])

    def test_claimed_unknown_event_is_terminal_and_never_pending_again(self):
        limits = config(article__calls=1, period__calls=10)
        budget = ModelBudget(self.root, self.schedule, limits)
        with budget.scope('article-1', 'draft', NOW):
            budget.reserve(self.payload())
            with self.assertRaises(BudgetHold):
                budget.reserve(self.payload())
        event = next(item for item in budget.pending_events() if item['level'] == 'hold')
        claimed = budget.claim_event(event['id'])
        self.assertEqual('in_flight', claimed['status'])
        self.assertIsNone(budget.claim_event(event['id']))
        terminal = budget.finish_event(event['id'], verified=False)
        self.assertEqual('unknown', terminal['status'])
        self.assertNotIn(event['id'], [item['id'] for item in budget.pending_events()])

    def test_jst_periods_are_separate_and_config_is_fail_closed(self):
        sunday_utc = datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc)  # Monday JST.
        budget = ModelBudget(self.root, self.schedule)
        with budget.scope('article-1', 'draft', sunday_utc):
            budget.reserve(self.payload())
        self.assertEqual('2026-11-09', budget.inspect(sunday_utc)['periodKey'])
        self.assertEqual(0, budget.inspect(NOW)['period']['calls'])
        self.assertNotIn('article-1', budget.inspect(NOW)['articles'])
        for invalid in (
                {'article': {'calls': -1}},
                {'period': 'many'},
                {'requestInputBytes': 0},
                {'unknown': 1}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'invalid model budget config'):
                ModelBudget(self.root, self.schedule, invalid)
        with self.assertRaisesRegex(ValueError, 'invalid model payload'):
            with budget.scope('article-1', 'draft', NOW):
                budget.reserve({'messages': []})

    def test_import_usage_is_idempotent_and_uses_aware_record_period(self):
        budget = ModelBudget(self.root, self.schedule)
        records = [{
            'responseId': 'response-1', 'articleId': 'article-imported',
            'stage': 'draft', 'at': '2026-11-18T10:00:00+09:00',
            'usage': {'input_tokens': 10, 'output_tokens': 4,
                      'cache_read_input_tokens': 3},
        }, {
            'responseId': 'response-2', 'articleId': 'article-imported',
            'stage': 'polish', 'at': '2026-11-18T11:00:00+09:00',
            'input': 7, 'output': 2,
        }]
        self.assertEqual({'imported': 2, 'existing': 0}, budget.import_usage(records))
        self.assertEqual({'imported': 0, 'existing': 2}, budget.import_usage(records))
        summary = ModelBudget(self.root, self.schedule).inspect(NOW)
        self.assertEqual({'calls': 2, 'inputTokens': 20, 'outputTokens': 6},
                         summary['period'])
        self.assertEqual(summary['period'], summary['articles']['article-imported'])
        self.assertEqual(2, summary['reservationsByStatus']['imported'])

    def test_import_without_article_is_period_only_legacy_unattributed(self):
        budget = ModelBudget(self.root, self.schedule)
        record = {'responseId': 'legacy-1', 'stage': 'maintenance',
                  'at': '2026-11-18T12:00:00+09:00', 'input': 9, 'output': 3}
        self.assertEqual({'imported': 1, 'existing': 0}, budget.import_usage([record]))
        summary = budget.inspect(NOW)
        self.assertEqual({'calls': 1, 'inputTokens': 9, 'outputTokens': 3},
                         summary['period'])
        self.assertEqual({}, summary['articles'])
        self.assertEqual(summary['period'], summary['legacyUnattributed'])
        bad = dict(record, responseId='legacy-missing-usage', input=None)
        with self.assertRaisesRegex(ValueError, 'invalid model usage record'):
            budget.import_usage([bad])

    def test_article_cap_blocks_changed_inputs_same_period_but_allows_next_period(self):
        limits = config(article__calls=1, period__calls=10)
        budget = ModelBudget(self.root, self.schedule, limits)
        with budget.scope('article-1', 'draft', NOW):
            budget.reserve(self.payload())
        with budget.scope('article-1', 'polish', NOW), self.assertRaises(BudgetHold) as held:
            budget.reserve(self.payload('changed input'))
        self.assertEqual('article_calls_cap', held.exception.reason_code)
        next_period = NOW + timedelta(days=7)
        with budget.scope('article-1', 'polish', next_period):
            budget.reserve(self.payload('legitimate next-period update'))
        self.assertEqual(1, budget.inspect(next_period)['articles']['article-1']['calls'])

    def test_supplemental_batch_call_cap_is_atomic_across_articles_and_periods(self):
        limits = config(article__calls=200, period__calls=200)
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            for index in range(3):
                job = {'id': f'article-extra-{index}', 'kind': 'supplemental_article',
                       'batchId': 'apparel-2026-11-16', 'batchCallCap': 96}
                db.execute('INSERT INTO jobs VALUES (?,?)',
                           (job['id'], json.dumps(job, separators=(',', ':'))))
        budget = ModelBudget(self.root, self.schedule, limits)
        for index in range(95):
            at = NOW if index < 50 else NOW + timedelta(days=7)
            with budget.scope(f'article-extra-{index % 3}', 'draft', at):
                budget.reserve(self.payload(str(index)))

        def attempt(article):
            local = ModelBudget(self.root, self.schedule, limits)
            try:
                with local.scope(article, 'polish', NOW + timedelta(days=14)):
                    local.reserve(self.payload(article))
                return 'reserved'
            except BudgetHold as error:
                return error.reason_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ('article-extra-0', 'article-extra-1')))
        self.assertEqual(['batch_calls_cap', 'reserved'], sorted(outcomes))
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            total = db.execute('SELECT count(*) FROM model_budget_reservations WHERE article_id LIKE ?',
                               ('article-extra-%',)).fetchone()[0]
        self.assertEqual(96, total)

    def test_actual_overshoot_is_charged_and_held_before_downstream_effects(self):
        budget = ModelBudget(self.root, self.schedule, config(article__inputTokens=1000))
        with budget.scope('article-1', 'final_review', NOW):
            reservation = budget.reserve(self.payload())
        with self.assertRaises(BudgetHold):
            budget.settle(reservation, {'input_tokens': 1001, 'output_tokens': 5})
        self.assertEqual(1001, budget.inspect(NOW)['period']['inputTokens'])
        self.assertTrue(any(e['level'] == 'hold' for e in budget.pending_events()))

    def test_live_response_id_prevents_later_usage_import_double_count(self):
        budget = ModelBudget(self.root, self.schedule)
        with budget.scope('article-1', 'draft', NOW):
            reservation = budget.reserve(self.payload())
        settled = budget.settle(reservation, {'input_tokens': 11, 'output_tokens': 5},
                                response_id='response-live-1')
        self.assertEqual('settled', settled['status'])
        record = {'responseId': 'response-live-1', 'articleId': 'article-1',
                  'stage': 'draft', 'at': NOW.isoformat(),
                  'usage': {'input_tokens': 11, 'output_tokens': 5}}
        self.assertEqual({'imported': 0, 'existing': 1}, budget.import_usage([record]))
        self.assertEqual(1, budget.inspect(NOW)['period']['calls'])
        conflict = copy.deepcopy(record)
        conflict['usage']['output_tokens'] = 6
        with self.assertRaisesRegex(ValueError, 'model usage response conflict'):
            budget.import_usage([conflict])

    def test_article_warning_and_hold_have_separate_events_next_period(self):
        budget = ModelBudget(self.root, self.schedule, config(article__calls=1))
        for at in (NOW, NOW + timedelta(days=7)):
            with budget.scope('article-1', 'draft', at):
                budget.reserve(self.payload())
                with self.assertRaises(BudgetHold):
                    budget.reserve(self.payload())
        for level in ('warning', 'hold'):
            matching = [e for e in budget.pending_events()
                        if e['budgetScope'] == 'article' and e['level'] == level
                        and e['dimension'] == 'calls']
            self.assertEqual(2, len(matching))
            self.assertEqual(2, len({e['periodKey'] for e in matching}))


if __name__ == '__main__':
    unittest.main()
