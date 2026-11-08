"""Offline manager workflow contracts: real SQLite/Runtime, no model or network calls."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_runtime as runtime_fixture
from manager import Manager, Budget, CommandProvider, build_snapshot, semantic_key, expectations
from runtime import JST

NOW = datetime(2026, 11, 8, 22, tzinfo=JST)
BUDGET = Budget(timeout_seconds=2, max_input_bytes=100000, max_output_bytes=16000,
                max_output_tokens=1000, max_calls_per_period=8)


class ManagerTests(unittest.TestCase):
    # Reuse the real runtime fixture, not its inherited tests.
    def setUp(self):
        runtime_fixture.RuntimeTests.setUp(self)
        runtime_fixture.RuntimeTests.configure_production_schedule(self)
        self.manager = Manager(self.runtime.root, budget=BUDGET, expected_model='gpt-6-astra')
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def provider(self, action='wait', job=None, **extra):
        def call(request):
            self.calls.append(request)
            snapshot = request['snapshot']
            target = next((j for j in snapshot['jobs'] if j['id'] == job), None)
            action_data = dict(action=action, jobId=job,
                revision=target['revision'] if target else None, expectations=expectations(target), targetUrl=None)
            action_data.update(extra)
            return dict(requestedModel='gpt-6-astra', actualModel=None,
                        usage={'output_tokens': 12}, actualInvoiceUsd=None,
                        decision=dict(stateFingerprint=request['stateFingerprint'], summary='Agenda only',
                                      actions=[action_data]))
        return call

    def evaluate(self, provider=None, **kwargs):
        return self.manager.evaluate_locked(self.runtime, provider or self.provider(), now=NOW, **kwargs)

    def job(self, stage='candidate'):
        job = self.runtime.ledger.create_candidate({'slug': 'sample'}, now=NOW)
        if stage != 'candidate':
            self.runtime.ledger.set_stage(job['id'], stage)
        return self.runtime.ledger.get_job(job['id'])

    def test_unchanged_across_manager_restart_and_provider_failover(self):
        self.assertEqual('completed', self.evaluate()['status'])
        self.manager = Manager(self.runtime.root, budget=BUDGET, expected_model='different')
        self.assertEqual('unchanged', self.evaluate()['status'])
        self.assertEqual(1, len(self.calls))

    def test_timeout_is_receipted_and_not_retried(self):
        def timeout(request):
            self.calls.append(request)
            raise TimeoutError('private body must not be stored')
        self.assertEqual('provider_failed', self.evaluate(timeout)['status'])
        self.assertEqual('unchanged', self.evaluate()['status'])
        self.assertNotIn('private body', self.runtime.ledger.db_path.read_bytes().decode(errors='ignore'))

    def test_unconfigured_budget_skips_call(self):
        self.manager = Manager(self.runtime.root)
        self.assertEqual('unconfigured', self.evaluate()['status'])
        self.assertEqual([], self.calls)

    def test_wrong_actual_model_and_extra_authority_rejected(self):
        def wrong(request):
            response = self.provider()(request)
            response['actualModel'] = 'gemini'
            return response
        self.assertEqual('invalid_decision', self.evaluate(wrong)['status'])
        self.job()
        self.assertEqual('invalid_decision', self.evaluate(self.provider(approve=True))['status'])

    def test_old_approval_and_gate_failure_never_deliver(self):
        job = self.job('review')
        self.assertEqual('blocked', self.evaluate(self.provider('deliver_reviewed', job['id']))['status'])
        self.assertEqual([], self.slack.deliveries)
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            raw = self.runtime.ledger.get_job(job['id'])
            raw['approval'] = {'revision': 'old', 'action': 'approved', 'user_id': 'SECRET_OWNER'}
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(raw), job['id']))
        self.assertEqual('blocked', self.evaluate(self.provider('deliver_reviewed', job['id']))['status'])
        self.assertEqual([], self.writes)

    def test_error_three_slots_do_not_restart_or_create_parallel_producer(self):
        for n in range(3):
            j = self.runtime.ledger.create_candidate({'slug': str(n)}, now=NOW)
            self.runtime.ledger.set_stage(j['id'], 'error')
        job = self.runtime.ledger.list_jobs()[0]
        self.assertEqual('blocked', self.evaluate(self.provider('produce_existing', job['id']))['status'])
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        self.assertEqual([], self.slack.deliveries)

    def test_held_and_posted_never_reproduce(self):
        job = self.job('held')
        self.assertEqual('blocked', self.evaluate(self.provider('produce_existing', job['id']))['status'])
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            raw = self.runtime.ledger.get_job(job['id'])
            raw['stage'] = 'social_posted'
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(raw), job['id']))
        self.assertEqual('blocked', self.evaluate(self.provider('produce_existing', job['id']))['status'])

    def test_missing_metrics_is_explicit_and_clocks_do_not_trigger(self):
        a = build_snapshot(self.runtime, now=NOW)
        b = build_snapshot(self.runtime, now=NOW + timedelta(minutes=5))
        self.assertEqual(semantic_key(a), semantic_key(b))
        self.assertEqual(['gscCurrent', 'gscPrevious', 'ga4', 'ga4Previous'], a['metrics']['missing'])
        self.assertIsNone(a['metrics']['ga4'])
        self.assertEqual('unknown', a['externalQueue']['status'])

    def test_nonce_owner_body_not_in_provider_snapshot(self):
        job = self.job()
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            raw = self.runtime.ledger.get_job(job['id'])
            raw.update(owner='SECRET_OWNER', nonce='SECRET_NONCE', body='PERSONAL_BODY')
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(raw), job['id']))
        self.runtime.config['productionSchedule']['owner'] = 'SECRET_OWNER'
        self.runtime.config['productionSchedule']['nonce'] = 'SECRET_NONCE'
        self.evaluate()
        text = json.dumps(self.calls)
        for secret in ('SECRET_OWNER', 'SECRET_NONCE', 'PERSONAL_BODY'):
            self.assertNotIn(secret, text)

    def test_stale_expectations_and_unknown_action_rejected(self):
        job = self.job()
        def stale(request):
            response = self.provider('produce_existing', job['id'])(request)
            response['decision']['actions'][0]['expectations']['stage'] = 'old'
            return response
        self.assertEqual('invalid_decision', self.evaluate(stale)['status'])
        self.runtime.ledger.set_stage(job['id'], 'held')
        self.assertEqual('invalid_decision', self.evaluate(self.provider('publish', job['id']))['status'])

    def test_proposal_handler_unknown_not_blindly_restarted(self):
        job = self.job('error')
        invoked = []
        def handler(plan, snapshot):
            invoked.append(plan)
            raise RuntimeError('private attachment body')
        result = self.evaluate(self.provider('improve_existing', job['id']),
                               handlers={'improve_existing': handler})
        self.assertEqual('requires_reconciliation', result['status'])
        self.assertEqual('unchanged', self.evaluate()['status'])
        self.assertEqual(1, len(invoked))

    def test_start_period_uses_normal_producer_once_and_retains_three(self):
        friday = datetime(2026, 11, 13, 9, tzinfo=JST)
        with patch('runtime.datetime') as clock:
            clock.now.return_value = friday
            result = self.manager.evaluate_locked(self.runtime, self.provider('start_period'), now=friday)
        self.assertEqual('completed', result['status'])
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        self.assertEqual('blocked', self.manager.evaluate_locked(self.runtime,
            self.provider('start_period'), now=friday)['status'])
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        self.assertEqual('unchanged', self.manager.evaluate_locked(self.runtime,
            self.provider('start_period'), now=friday)['status'])

    def test_start_period_blocked_by_old_held_capacity(self):
        for n in range(3):
            job = self.runtime.ledger.create_candidate({'slug': str(n)}, now=NOW)
            self.runtime.ledger.set_stage(job['id'], 'held')
        self.assertEqual('blocked', self.manager.evaluate_locked(self.runtime,
            self.provider('start_period'), now=datetime(2026, 11, 13, 9, tzinfo=JST))['status'])
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))

    def test_call_budget_counts_failures_and_survives_restart(self):
        self.manager = Manager(self.runtime.root, budget=Budget(2, 100000, 16000, 1000, 1))
        self.assertEqual('completed', self.evaluate()['status'])
        self.job()
        self.assertEqual('budget_exhausted', self.evaluate()['status'])
        self.assertEqual(1, len(self.calls))

    def test_target_order_matches_ledger_rowid_not_random_id(self):
        first = self.runtime.ledger.create_candidate({'slug': 'first'}, now=NOW)
        second = self.runtime.ledger.create_candidate({'slug': 'second'}, now=NOW)
        snap = build_snapshot(self.runtime, now=NOW)
        self.assertEqual(first['id'], snap['production']['nextCandidateId'])
        self.assertEqual('blocked', self.evaluate(self.provider('produce_existing', second['id']))['status'])

    def metric_data(self):
        from test_analytics import snapshot
        data = snapshot()
        data['collectedAt'] = NOW.isoformat()
        data['current']['pages'] = [dict(url='https://camp-gear-lab.com/articles/topic-' + str(n),
            clicks=0, impressions=100 + n, ctr=0, position=8) for n in range(3)]
        root = self.runtime.root / 'seo'
        (root / 'metrics').mkdir(parents=True, exist_ok=True)
        self.runtime.config['seoStateRoot'] = str(root)
        (root / 'metrics/latest.json').write_text(json.dumps(data))
        return root, data

    def test_verified_opportunity_queues_without_ledger_job(self):
        self.metric_data()
        dispatched = []
        snap = build_snapshot(self.runtime, now=NOW)
        self.assertEqual(3, len(snap['metrics']['opportunities']))
        self.assertIn('gscPeriod', snap['metrics']['opportunities'][0])
        url = snap['metrics']['opportunities'][0]['url']
        def queue(plan, snapshot):
            dispatched.append(plan.target_url)
            return {'status': 'completed'}
        self.assertEqual('completed', self.evaluate(self.provider('improve_existing', targetUrl=url),
            handlers={'improve_existing': queue})['status'])
        self.assertEqual([url], dispatched)
        self.assertEqual([], self.runtime.ledger.list_jobs())

    def test_unknown_opportunity_and_personal_query_rejected(self):
        self.metric_data()
        for url in ('https://evil.example/articles/a', 'https://camp-gear-lab.com/articles/imaginary',
                    'https://camp-gear-lab.com/articles/topic-1?email=private@example.com'):
            self.manager = Manager(self.runtime.root, budget=BUDGET)
            self.assertEqual('invalid_decision', self.evaluate(self.provider('improve_existing', targetUrl=url))['status'])
            # A genuinely changed stage allows the next invalid schema probe.
            job = self.runtime.ledger.create_candidate({'slug': str(len(self.calls))}, now=NOW)
            self.runtime.ledger.set_stage(job['id'], 'rejected')
        self.assertNotIn('private@example', json.dumps(self.calls))

    def test_metric_change_triggers_once_without_collection_clock_churn(self):
        root, data = self.metric_data()
        self.evaluate()
        data['collectedAt'] = (NOW - timedelta(minutes=1)).isoformat()
        (root / 'metrics/latest.json').write_text(json.dumps(data))
        self.assertEqual('unchanged', self.evaluate()['status'])
        data['current']['summary']['impressions'] += 1
        (root / 'metrics/latest.json').write_text(json.dumps(data))
        self.assertEqual('completed', self.evaluate()['status'])
        self.assertEqual(2, len(self.calls))

    def test_atomic_manager_lease_blocks_concurrent_call(self):
        import fcntl
        with (self.runtime.root / 'manager.flock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual('busy', self.evaluate()['status'])
        self.assertEqual([], self.calls)

    def test_actual_evidence_retained_when_model_mismatches(self):
        def wrong(request):
            response = self.provider()(request)
            response['actualModel'] = 'unexpected-model'
            return response
        receipt = self.evaluate(wrong)
        self.assertEqual('invalid_decision', receipt['status'])
        self.assertEqual('unexpected-model', receipt['actualModel'])
        self.assertEqual(12, receipt['usage']['output_tokens'])
        self.assertTrue(receipt['costMissing'])

    def test_retained_normal_candidates_resume_across_friday_without_slot_reset(self):
        jobs = [self.runtime.ledger.create_candidate({'slug': str(n)}, now=NOW) for n in range(3)]
        friday = datetime(2026, 11, 13, 9, tzinfo=JST)
        with patch('runtime.datetime') as clock:
            clock.now.return_value = friday
            receipt = self.manager.evaluate_locked(self.runtime,
                self.provider('produce_existing', jobs[0]['id']), now=friday)
        self.assertEqual('completed', receipt['status'])
        current = self.runtime.ledger.list_jobs()
        self.assertEqual(3, len(current))
        self.assertEqual({j['id']: j['week'] for j in jobs}, {j['id']: j['week'] for j in current})
        self.assertEqual('review', self.runtime.ledger.get_job(jobs[0]['id'])['stage'])
        self.assertEqual(2, sum(j['stage'] == 'candidate' for j in current))
        self.assertTrue(all(j['approval'] is None and j['publication'] is None for j in current))

    def test_posted_job_allows_only_proposal_work_not_reproduction(self):
        job = self.job()
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            raw = self.runtime.ledger.get_job(job['id'])
            raw.update(stage='social_posted', publication={'verified': True},
                       social={'publication': {'verified': True}})
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(raw), job['id']))
        queued = []
        def handler(plan, snapshot):
            queued.append(plan.job_id)
            return {'status': 'completed'}
        self.assertEqual('completed', self.evaluate(self.provider('improve_existing', job['id']),
            handlers={'improve_existing': handler})['status'])
        self.assertEqual([job['id']], queued)
        snapshot = build_snapshot(self.runtime, now=NOW)
        self.assertEqual('posted_immutable', self.manager._blocked('produce_existing', snapshot['jobs'][0], snapshot))
        self.assertEqual('posted_immutable', self.manager._blocked('deliver_reviewed', snapshot['jobs'][0], snapshot))
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)

    def test_review_delivery_uses_runtime_gate_once_without_approval(self):
        from test_quality import bundle
        job = self.job()
        saved = self.runtime.ledger.save_bundle(job['id'], bundle())
        self.runtime.ledger.record_review(job['id'], saved['revision'], dict(
            passed=True, score=8, fingerprint=saved['revision'],
            evidence={k: True for k in ('facts', 'images', 'affiliate', 'medical', 'render')},
            polish=dict(model='gemini-3.8-flash', validated=True)))
        self.assertEqual('completed', self.evaluate(self.provider('deliver_reviewed', job['id']))['status'])
        self.assertEqual(1, len(self.slack.deliveries))
        self.assertEqual('blocked', self.evaluate(self.provider('deliver_reviewed', job['id']))['status'])
        current = self.runtime.ledger.get_job(job['id'])
        self.assertIsNone(current['approval'])
        self.assertIsNone(current['publication'])
        self.assertEqual(1, len(self.slack.deliveries))
        self.assertEqual([], self.writes)

    def test_new_state_during_provider_call_rejects_dispatch(self):
        job = self.job()
        def changed(request):
            response = self.provider('produce_existing', job['id'])(request)
            self.runtime.ledger.set_stage(job['id'], 'held')
            return response
        self.assertEqual('stale', self.evaluate(changed)['status'])
        self.assertEqual('held', self.runtime.ledger.get_job(job['id'])['stage'])
        self.assertEqual([], self.writes)

    def test_old_unknown_research_cannot_be_hidden_by_period_rollover(self):
        folder = self.runtime.root / 'production-attempts'
        folder.mkdir()
        (folder / '2026-11-06.json').write_text(json.dumps({'status': 'in_flight'}))
        self.assertEqual('blocked', self.manager.evaluate_locked(self.runtime,
            self.provider('start_period'), now=datetime(2026, 11, 13, 9, tzinfo=JST))['status'])
        self.assertEqual([], self.runtime.ledger.list_jobs())

    def test_current_config_supplies_optional_target_and_queue_connection(self):
        missing = build_snapshot(self.runtime, now=NOW)
        self.assertIsNone(missing['production']['initialTargetPublishBy'])
        self.assertIsNone(missing['externalQueue']['connected'])
        self.runtime.config['initialTargetPublishBy'] = '2026-11-12'
        self.runtime.config['editorialManager'] = {'externalQueue': dict(
            provider='Buffer', connected=True, status='verified', evidenceFingerprint='a' * 64,
            owner='PRIVATE_OWNER', body='PRIVATE_QUEUE_BODY')}
        current = build_snapshot(self.runtime, now=NOW)
        self.assertEqual('2026-11-12', current['production']['initialTargetPublishBy'])
        self.assertTrue(current['externalQueue']['connected'])
        self.assertEqual('verified', current['externalQueue']['status'])
        self.assertNotEqual(semantic_key(missing), semantic_key(current))
        self.assertNotIn('PRIVATE_', json.dumps(current))
        del self.runtime.config['editorialManager']['externalQueue']['evidenceFingerprint']
        self.assertEqual('unknown', build_snapshot(self.runtime, now=NOW)['externalQueue']['status'])
        self.runtime.config['initialTargetPublishBy'] = '2026-02-30'
        self.assertIsNone(build_snapshot(self.runtime, now=NOW)['production']['initialTargetPublishBy'])

    def test_measured_cache_usage_and_opaque_startup_warning_are_receipted(self):
        def observed(request):
            response = self.provider()(request)
            response['usage'].update(cache_write_input_tokens=17, reasoning_tokens=5)
            response['warnings'] = dict(preTurnErrorCount=4, code='unknown', toolsStartupVerified=False)
            return response
        receipt = self.evaluate(observed)
        self.assertEqual('completed', receipt['status'])
        self.assertEqual(17, receipt['usage']['cache_write_input_tokens'])
        self.assertEqual(5, receipt['usage']['reasoning_tokens'])
        self.assertEqual(dict(preTurnErrorCount=4, code='unknown', toolsStartupVerified=False), receipt['warnings'])
        self.assertIsNone(receipt['actualModel'])
        self.assertIsNone(receipt['actualInvoiceUsd'])
        self.assertEqual('unchanged', self.evaluate()['status'])

    def test_warning_cannot_carry_raw_diagnostics_or_tool_authority(self):
        warnings = (dict(preTurnErrorCount=17, code='unknown', toolsStartupVerified=False),
                    dict(preTurnErrorCount=1, code='unknown', toolsStartupVerified=True),
                    dict(preTurnErrorCount=True, code='unknown', toolsStartupVerified=False),
                    dict(preTurnErrorCount=1, code='unknown', toolsStartupVerified=False, message='PRIVATE_DIAGNOSTIC'))
        for index, warning in enumerate(warnings):
            with self.subTest(case=index):
                if index:
                    self.tearDown()
                    self.setUp()
                def observed(request):
                    response = self.provider()(request)
                    response['warnings'] = warning
                    return response
                self.assertEqual('invalid_decision', self.evaluate(observed)['status'])
                self.assertEqual([], self.runtime.ledger.list_jobs())
                self.assertNotIn('PRIVATE_DIAGNOSTIC', self.runtime.ledger.db_path.read_bytes().decode(errors='ignore'))

    def test_invalidated_delivery_is_historical_not_active_unknown(self):
        job = self.job()
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            raw = self.runtime.ledger.get_job(job['id'])
            raw['revision'] = 'b' * 64
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(raw), job['id']))
            request = dict(request_id='PRIVATE_REQUEST', status='invalidated',
                manifest_hash='a' * 64, expires_at='2026-11-12T09:00:00+09:00')
            db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                ('PRIVATE_REQUEST', job['id'], 'article', json.dumps(request)))
        folder = self.runtime.root / 'deliveries'
        folder.mkdir()
        (folder / 'PRIVATE_REQUEST.json').write_text(json.dumps({'status': 'in_flight'}))
        snap = build_snapshot(self.runtime, now=NOW)
        marker = next(m for m in snap['stateReceipts'] if m['kind'] == 'deliveries')['states'][0]
        self.assertEqual('invalidated', marker['requestStatus'])
        self.assertFalse(marker['currentRevision'])
        self.assertTrue(marker['historicalNonblocking'])
        self.assertEqual([], snap['effects'])
        self.assertNotIn('PRIVATE_REQUEST', json.dumps(snap))
        self.assertIsNone(self.manager._blocked('produce_existing', snap['jobs'][0], snap))

    def test_current_corrected_context_requires_independent_astra_qa(self):
        from test_quality import bundle
        job = self.job()
        saved = self.runtime.ledger.save_bundle(job['id'], bundle())
        review = dict(passed=True, score=8, fingerprint=saved['revision'],
            evidence={k: True for k in ('facts', 'images', 'affiliate', 'medical', 'render')},
            polish=dict(model='gemini-3.8-flash', validated=True))
        self.runtime.ledger.record_review(job['id'], saved['revision'], review)
        before = semantic_key(build_snapshot(self.runtime, now=NOW))
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            raw = self.runtime.ledger.get_job(job['id'])
            raw['catalogCorrectionContext'] = {'privateBody': 'NEVER_SEND_BODY'}
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(raw), job['id']))
        after = build_snapshot(self.runtime, now=NOW)
        self.assertNotEqual(before, semantic_key(after))
        self.assertTrue(after['jobs'][0]['catalogCorrection'])
        self.assertFalse(after['jobs'][0]['reviewPassed'])
        self.assertNotIn('NEVER_SEND_BODY', json.dumps(after))
        self.assertEqual('blocked', self.evaluate(self.provider('deliver_reviewed', job['id']))['status'])
        self.assertEqual([], self.slack.deliveries)


class RunnerTests(unittest.TestCase):
    def test_bounded_runner_timeout_and_oversize(self):
        for code in ('import time; time.sleep(2)', 'print("x"*20000)'):
            provider = CommandProvider((sys.executable, '-c', code), BUDGET.__class__(
                timeout_seconds=.1, max_input_bytes=100000, max_output_bytes=100,
                max_output_tokens=1000, max_calls_per_period=8))
            with self.assertRaises((TimeoutError, ValueError)):
                provider({'hello': 'finite JSON'})

    def test_command_uses_stdin_structured_json(self):
        code = 'import sys,json; print(json.dumps({"echo":json.load(sys.stdin)}))'
        self.assertEqual({'echo': {'x': 1}}, CommandProvider((sys.executable, '-c', code), BUDGET)({'x': 1}))


if __name__ == '__main__':
    unittest.main()
