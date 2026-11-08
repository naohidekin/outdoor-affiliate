"""Offline Runtime manager integration, real ledger and existing producer only."""
import copy
from dataclasses import asdict
from datetime import datetime, timedelta
import fcntl
import json
from unittest.mock import Mock, patch
import unittest

import test_runtime
from manager import Budget, build_snapshot, expectations, semantic_key
from runtime import JST

NOW = datetime(2026, 11, 8, 22, tzinfo=JST)
BUDGET = Budget(timeout_seconds=2, max_input_bytes=100000, max_output_bytes=16000,
                max_output_tokens=1000, max_calls_per_period=8)


class ManagerRuntimeTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        test_runtime.RuntimeTests.configure_production_schedule(self)
        self.config['editorialManager'] = dict(enabled=True, command=['synthetic-managed-astra'], budget=asdict(BUDGET))
        self.config['reportsEnabled'] = True
        self.runtime.reporter = Mock()
        self.runtime.reporter.tick.return_value = []
        self.runtime._post_publication_audits = Mock(return_value=[])
        self.runtime._produce_requested_revision = Mock(return_value=None)
        self.runtime._analytics_context = Mock(return_value={})
        self.provider_calls = []

    tearDown = test_runtime.RuntimeTests.tearDown

    def provider(self, action='wait', job_id=None, url=None):
        def call(command, snapshot, prompt, schema, timeout):
            self.provider_calls.append(copy.deepcopy(snapshot))
            job = next((j for j in snapshot['jobs'] if j['id'] == job_id), None)
            return dict(requestedModel='gpt-6-astra', actualModel=None,
                usage={'output_tokens': 12}, actualInvoiceUsd=None,
                decision=dict(stateFingerprint=semantic_key(snapshot), summary='SECRET_RAW_SUMMARY',
                    actions=[dict(action=action, jobId=job_id, targetUrl=url,
                                  revision=job['revision'] if job else None, expectations=expectations(job))]))
        return call

    def tick(self, provider=None, now=NOW):
        with patch('runtime.datetime', wraps=datetime) as clock, patch('manager_cli.call', side_effect=provider or self.provider()) as call:
            clock.now.return_value = now
            result = self.runtime.tick()
        return result, call

    def orders(self):
        with self.runtime.ledger._tx() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT value FROM meta WHERE key LIKE 'editorial_manager_work:%'")]

    def job(self, stage='candidate'):
        job = self.runtime.ledger.create_candidate({'slug': 'source-error', 'title': 'Source'}, now=NOW)
        if stage != 'candidate':
            self.runtime.ledger.set_stage(job['id'], stage, {'reason': 'source_verification_failed'})
        return self.runtime.ledger.get_job(job['id'])

    def test_start_period_from_empty_calls_real_normal_producer_once(self):
        self.runtime.produce = Mock(wraps=self.runtime.produce)
        result, call = self.tick(self.provider('start_period'))
        self.runtime.produce.assert_called_once_with(limit=1)
        call.assert_called_once()
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        self.assertEqual(1, len(self.slack.deliveries))
        self.assertEqual('completed', result['manager']['status'])
        self.runtime._produce_requested_revision.assert_called_once()
        self.runtime.reporter.tick.assert_called_once()

    def test_identical_state_makes_zero_further_provider_calls(self):
        self.runtime.produce = Mock(side_effect=AssertionError('no legacy producer'))
        first, _ = self.tick()
        second, call = self.tick(now=NOW + timedelta(minutes=5))
        self.assertEqual('completed', first['manager']['status'])
        self.assertEqual('unchanged', second['manager']['status'])
        self.assertEqual(1, second['manager']['callsUsed'])
        call.assert_not_called()
        self.runtime.produce.assert_not_called()

    def test_provider_failure_has_no_fallback_and_deduplicates_generic_attention(self):
        self.runtime.produce = Mock(side_effect=AssertionError('no fallback'))
        fail = Mock(side_effect=TimeoutError('RAW_PROVIDER_SECRET'))
        first, call = self.tick(fail)
        second, repeated = self.tick(fail, now=NOW + timedelta(minutes=5))
        self.assertEqual('provider_failed', first['manager']['status'])
        self.assertEqual('unchanged', second['manager']['status'])
        self.assertEqual('provider_failed', second['manager']['receiptStatus'])
        call.assert_called_once()
        repeated.assert_not_called()
        self.runtime.produce.assert_not_called()
        self.assertEqual(1, len(self.slack.notices))
        self.assertNotIn('RAW_PROVIDER_SECRET', json.dumps(second))
        self.assertEqual(2, self.runtime.reporter.tick.call_count)

    def test_approval_publication_and_reports_continue_while_manager_waits_or_fails(self):
        self.config['editorialManager']['enabled'] = False
        with patch('runtime.datetime', wraps=datetime) as clock:
            clock.now.return_value = NOW
            self.runtime.produce(limit=1)
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        test_runtime.RuntimeTests.approve(self, job)
        self.config['editorialManager']['enabled'] = True
        self.config['generationEnabled'] = False
        self.writes.clear()
        result, _ = self.tick(Mock(side_effect=ValueError('provider offline')))
        self.assertEqual(['publish'], [a for a, _ in self.writes])
        self.assertEqual('published', self.runtime.ledger.get_job(job['id'])['stage'])
        self.assertEqual('provider_failed', result['manager']['status'])
        self.runtime.reporter.tick.assert_called_once()

    def test_source_investigation_and_unknown_reconciliation_only_queue_human_work(self):
        job = self.job('error')
        before = copy.deepcopy(job)
        result, _ = self.tick(self.provider('investigate_sources', job['id']))
        self.assertEqual('completed', result['manager']['status'])
        self.assertEqual(1, result['manager']['pendingActionCount'])
        self.assertEqual(before, self.runtime.ledger.get_job(job['id']))
        order = self.orders()[0]
        self.assertEqual('source_verification_failed', order['observedStatus']['errorCode'])
        self.assertEqual('human_needed', order['status'])
        self.assertNotIn('SECRET_RAW_SUMMARY', json.dumps(order))
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (job['id'], 'publish', 'unknown', '{}'))
        result, _ = self.tick(self.provider('reconcile_unknown', job['id']))
        self.assertEqual(2, result['manager']['pendingActionCount'])
        reconciliation = next(o for o in self.orders() if o['action'] == 'reconcile_unknown')
        self.assertEqual('unknown', reconciliation['effects'][0]['status'])
        self.assertEqual(before, self.runtime.ledger.get_job(job['id']))

    def test_error_cannot_be_reset_by_produce_existing(self):
        job = self.job('error')
        self.runtime.produce = Mock(side_effect=AssertionError('no retry'))
        result, _ = self.tick(self.provider('produce_existing', job['id']))
        self.assertEqual('blocked', result['manager']['status'])
        self.assertEqual('error', self.runtime.ledger.get_job(job['id'])['stage'])
        self.runtime.produce.assert_not_called()

    def test_ga4_verified_url_queues_actual_opportunity_without_source_writes(self):
        from test_analytics import snapshot
        data = snapshot()
        data['collectedAt'] = NOW.isoformat()
        root = self.runtime.root / 'seo'
        (root / 'metrics').mkdir(parents=True)
        path = root / 'metrics/latest.json'
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        self.config['seoStateRoot'] = str(root)
        snapshot = build_snapshot(self.runtime, now=NOW)
        opportunity = snapshot['metrics']['opportunities'][0]
        result, _ = self.tick(self.provider('improve_existing', url=opportunity['url']))
        self.assertEqual('completed', result['manager']['status'])
        self.assertEqual(opportunity, self.orders()[0]['opportunity'])
        self.assertEqual(opportunity['url'], result['manager']['pendingActions'][0]['targetUrl'])
        self.assertEqual(0, self.orders()[0]['opportunity']['ga4']['sessions'])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual([], self.runtime.ledger.list_jobs())
        self.assertNotIn('private@example', json.dumps(result['manager']))
        self.assertNotIn('SECRET_RAW_SUMMARY', json.dumps(result))
        self.tick(self.provider('improve_existing', url=opportunity['url']))
        self.assertEqual(1, len(self.orders()))

    def test_missing_or_disabled_config_keeps_legacy_production(self):
        for options in (None, {'enabled': False}):
            with self.subTest(options=options):
                if options is None:
                    self.config.pop('editorialManager', None)
                else:
                    self.config['editorialManager'] = options
                self.runtime.produce = Mock(return_value={'status': 'idle'})
                result, call = self.tick()
                self.runtime.produce.assert_called_once_with(limit=1)
                call.assert_not_called()
                self.assertNotIn('manager', result)

    def test_enabled_unconfigured_manager_never_falls_back(self):
        self.config['editorialManager'].pop('budget')
        self.runtime.produce = Mock(side_effect=AssertionError('no legacy'))
        result, call = self.tick()
        self.assertEqual('unconfigured', result['manager']['status'])
        self.runtime.produce.assert_not_called()
        call.assert_not_called()

    def test_provider_factory_uses_documented_command_schema_and_budget_timeout(self):
        _, call = self.tick()
        args = call.call_args
        self.assertEqual(['synthetic-managed-astra'], args.args[0])
        self.assertEqual('object', args.args[3]['type'])
        self.assertEqual(BUDGET.timeout_seconds, args.kwargs['timeout'])
        self.assertEqual('Camp Gear Lab', args.args[1]['brand'])
        self.assertNotIn('command', json.loads((self.runtime.root / 'health.json').read_text())['manager'])

    def test_existing_candidate_dispatches_only_normal_producer_once(self):
        job = self.job()
        self.runtime.produce = Mock(wraps=self.runtime.produce)
        result, call = self.tick(self.provider('produce_existing', job['id']))
        self.runtime.produce.assert_called_once_with(limit=1)
        self.assertEqual('completed', result['manager']['status'])
        self.assertEqual([job['id']], [j['id'] for j in self.runtime.ledger.list_jobs()])
        self.assertEqual('review', self.runtime.ledger.get_job(job['id'])['stage'])
        call.assert_called_once()

    def test_improvement_job_work_order_is_deduplicated_without_mutating_job(self):
        job = self.job('error')
        first, _ = self.tick(self.provider('improve_existing', job['id']))
        second, call = self.tick(self.provider('improve_existing', job['id']))
        self.assertEqual('completed', first['manager']['status'])
        self.assertEqual('unchanged', second['manager']['status'])
        self.assertEqual(1, len(self.orders()))
        self.assertEqual(job, self.runtime.ledger.get_job(job['id']))
        self.assertEqual('improve_existing', self.orders()[0]['action'])
        call.assert_not_called()
        with self.runtime.ledger._tx() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM events WHERE kind='manager_work_order'").fetchone()[0])

    def test_invalid_enable_or_budget_has_no_provider_or_legacy_fallback(self):
        for options in ({'enabled': 'true'}, {'enabled': True, 'budget': {'timeout_seconds': -1}}, 'invalid'):
            with self.subTest(options=options):
                self.config['editorialManager'] = options
                self.runtime.produce = Mock(side_effect=AssertionError('no fallback'))
                result, call = self.tick()
                self.assertEqual('unconfigured', result['manager']['status'])
                self.runtime.produce.assert_not_called()
                call.assert_not_called()

    def test_manager_cannot_deliver_corrected_article_without_independent_astra_qa(self):
        import test_catalog_correction_runtime
        fixture = test_catalog_correction_runtime.CatalogCorrectionRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        job = fixture.produce()
        fixture.config['editorialManager'] = copy.deepcopy(self.config['editorialManager'])
        fixture.config['generationEnabled'] = False
        self.runtime = fixture.runtime
        result, _ = self.tick(self.provider('deliver_reviewed', job['id']))
        self.assertEqual('blocked', result['manager']['status'])
        self.assertEqual([], fixture.slack.deliveries)
        self.assertEqual([], fixture.writes)
        current = fixture.runtime.ledger.get_job(job['id'])
        self.assertIsNone(current['approval'])
        self.assertIsNone(current.get('astraReview'))
        self.assertEqual('review', current['stage'])

    def test_existing_runtime_lease_held_through_provider_and_dispatch(self):
        held = []
        provider = self.provider('start_period')
        def check(*args, **kwargs):
            with (self.runtime.root / 'runtime.flock').open('a') as competing:
                try:
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.append(False)
                except BlockingIOError:
                    held.append(True)
            return provider(*args, **kwargs)
        with (self.runtime.root / 'runtime.flock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            self.tick(check)
        self.assertEqual([True], held)


if __name__ == '__main__':
    unittest.main()
