"""Explicit remaining revision attempts, real journal/budget, no providers."""
import copy
import hashlib
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from models import ModelError, ModelOutcomeUnknown
from runtime import Runtime, atomic
from stage_journal import StageBlocked
import test_revision_workflow as workflow
from test_revision_workflow import baseline


class CorrectedRevisionRetryTests(unittest.TestCase):
    tearDown = workflow.RevisionWorkflowTests.tearDown
    request = workflow.RevisionWorkflowTests.request
    context = workflow.RevisionWorkflowTests.context
    fake_evidence = workflow.RevisionWorkflowTests.fake_evidence

    def setUp(self):
        workflow.RevisionWorkflowTests.setUp(self)
        self.config['executionPolicy'] = {'mode': 'deterministic', 'suspended': False}
        self.base = baseline()
        self.job = self.request(self.base)
        self.fake_evidence()
        self.live = self.context(self.base)
        self.runtime._context = Mock(side_effect=lambda: copy.deepcopy(self.live))
        self.models.draft.side_effect = ModelError('Article length outside existing SKILL limits')
        self.assertEqual('attention', self.runtime._produce_requested_revision()['status'])
        self.models.draft.side_effect = None
        self.models.draft.reset_mock()
        self.old = self.records()[0]['stageKey']
        self.runtime.stage_journal.record_usage(self.job['id'], 'draft', self.old,
                                               [{'responseId': 'paid-first'}, {'responseId': 'paid-repair'}])
        self.original = copy.deepcopy(self.records()[0])
        self.failure = copy.deepcopy(self.runtime.ledger.get_job(self.job['id'])['error'])
        self.marker = self.runtime.root / 'revision-production-attempts' / (self.job['id'] + '.json')
        self.marker_bytes = self.marker.read_bytes()
        self.retry_marker = (self.runtime.root / 'revision-stage-retries' / self.job['id'] /
                             (hashlib.sha256(self.old.encode()).hexdigest() + '.json'))
        # A new prompt/source dependency is permitted only in the corrected route.
        routes = self.runtime._model_routes()
        routes['implementationHashes']['models.py'] = 'changed-approved-prompt'
        self.runtime._model_routes = Mock(return_value=routes)

    def records(self):
        return self.runtime.stage_journal.status(job_id=self.job['id'], stage='draft')['records']

    def retry(self):
        return self.runtime.retry_corrected_stage(self.job['id'], 'draft', self.old)

    def test_changed_inputs_reach_review_once_keep_history_marker_and_scope(self):
        fresh = self.runtime.catalog.gather_revision.return_value
        fresh['references'].append({'kind': 'verified-test-source', 'url': 'https://maker.example/fresh'})
        self.runtime.catalog.gather_revision.reset_mock()
        result = self.retry()
        self.assertEqual('completed', result['status'])
        self.runtime.catalog.gather_revision.assert_called_once()
        self.models.draft.assert_called_once()
        self.assertIn('existingArticle', self.models.draft.call_args.args[1])
        records = self.records()
        parent = next(r for r in records if r['stageKey'] == self.old)
        child = next(r for r in records if r.get('predecessorKey') == self.old)
        for key, value in self.original.items():
            if key != 'updatedAt':
                self.assertEqual(value, parent[key], key)
        self.assertEqual(('succeeded', 2, 2, 1),
                         (child['status'], child['attempts'], child['maxAttempts'], child['inheritedAttempts']))
        self.assertNotEqual(parent['dependencyHash'], child['dependencyHash'])
        self.assertEqual(self.marker_bytes, self.marker.read_bytes())
        saved = self.runtime.ledger.get_job(self.job['id'])
        self.assertEqual('review', saved['stage'])
        self.assertEqual(self.job['revisionContext'], saved['revisionContext'])
        self.assertIsNone(saved['approval']); self.assertIsNone(saved['publication'])
        self.assertEqual([], self.writes)
        with self.assertRaises((ValueError, StageBlocked)):
            self.retry()

    def test_source_hold_stops_before_model_and_never_enqueues_natural_retry(self):
        fresh = self.runtime.catalog.gather_revision.return_value
        fresh['checks']['facts'] = False
        result = self.retry()
        self.assertEqual('attention', result['status'])
        self.models.draft.assert_not_called()
        self.assertEqual([self.original], self.records())
        self.assertEqual(self.marker_bytes, self.marker.read_bytes())
        self.assertTrue(self.retry_marker.exists())
        saved = self.runtime.ledger.get_job(self.job['id'])
        self.assertEqual('error', saved['stage'])
        self.assertEqual(self.failure, saved['error']['originalFailure'])

    def test_changed_article_baseline_stops_before_source_or_model(self):
        self.live['revisionArticles'][0]['content'] += ' changed'
        self.runtime.catalog.gather_revision.reset_mock()
        self.assertEqual('attention', self.retry()['status'])
        self.runtime.catalog.gather_revision.assert_not_called()
        self.models.draft.assert_not_called()
        self.assertEqual([self.original], self.records())

    def test_changed_product_baseline_stops_before_source_or_model(self):
        self.live['products'][0]['updatedAt'] = '2026-11-23T00:00:00+09:00'
        self.runtime.catalog.gather_revision.reset_mock()
        self.assertEqual('attention', self.retry()['status'])
        self.runtime.catalog.gather_revision.assert_not_called()
        self.models.draft.assert_not_called()

    def test_eligibility_never_widens_unknown_exhausted_or_nonlength_failures(self):
        job = self.runtime.ledger.get_job(self.job['id'])
        for change in ({'status': 'in_flight'}, {'status': 'unknown'}, {'status': 'succeeded'},
                       {'attempts': 2}, {'maxAttempts': 3}, {'successorKey': 'spent'}, {'predecessorKey': 'prior'}):
            with self.subTest(change=change), self.assertRaises((ValueError, StageBlocked)):
                Runtime.validate_corrected_retry(job, 'draft', self.old, [dict(self.original, **change)])
        for change in ({'error': {'reason': 'provider failure'}}, {'bundle': {}}, {'review': {}},
                       {'approval': {}}, {'publication': {}}, {'stage': 'candidate'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Runtime.validate_corrected_retry(dict(job, **change), 'draft', self.old, [self.original])
        bad = copy.deepcopy(job); bad['revisionContext']['baseHash'] = '0' * 64
        with self.assertRaises(ValueError):
            Runtime.validate_corrected_retry(bad, 'draft', self.old, [self.original])
        with self.assertRaises(ValueError):
            Runtime.validate_corrected_retry(job, 'polish', self.old, [self.original])

    def test_blocked_production_and_unspent_retry_markers_remain_required(self):
        for marker in ({'status': 'unknown'}, {'status': 'in_flight'},
                       {'status': 'blocked', 'reason': 'unrelated'}):
            atomic(self.marker, marker)
            with self.assertRaises(ValueError): self.retry()
        self.marker.write_bytes(self.marker_bytes)
        atomic(self.retry_marker, {'status': 'blocked'})
        with self.assertRaises(ValueError): self.retry()
        self.models.draft.assert_not_called()

    def test_unresolved_effect_budget_manager_or_other_stage_stops_before_reservation(self):
        alias = self.runtime._budget_article_id(self.job['id'])
        for status in ('reserved', 'unknown'):
            with self.runtime.model_budget.scope(alias, 'draft'):
                rid = self.runtime.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
            with self.runtime.ledger._tx() as db:
                db.execute('UPDATE model_budget_reservations SET status=? WHERE reservation_id=?', (status, rid))
            with self.assertRaises(ValueError): self.retry()
            with self.runtime.ledger._tx() as db:
                db.execute('DELETE FROM model_budget_reservations WHERE reservation_id=?', (rid,))
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (self.job['id'], 'publish', 'unknown', '{}'))
        with self.assertRaises(ValueError): self.retry()
        with self.runtime.ledger._tx() as db:
            db.execute('DELETE FROM effects')
            db.execute('INSERT INTO meta VALUES (?,?)', ('editorial_manager:unknown', json.dumps({'status': 'executing'})))
        with self.assertRaises(ValueError): self.retry()
        self.assertFalse(self.retry_marker.exists())
        self.models.draft.assert_not_called()
        with self.runtime.ledger._tx() as db:
            db.execute('DELETE FROM meta WHERE key=?', ('editorial_manager:unknown',))
        with self.assertRaises(Exception):
            self.runtime.stage_journal.run(self.job['id'], 'polish', {'dependencies': {}, 'schemaVersion': 1},
                lambda: (_ for _ in ()).throw(ModelOutcomeUnknown('uncertain')))
        with self.assertRaises(ValueError): self.retry()
        self.assertFalse(self.retry_marker.exists())

    def manager_receipt(self, raw):
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('editorial_manager:held', raw))

    def manager_job(self, id, *, slug=None):
        job = copy.deepcopy(self.job)
        job['id'] = id
        if slug is not None:
            job['kind'] = 'article'
            job['theme']['slug'] = slug
            job.pop('revisionContext', None)
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO jobs VALUES (?,?)', (id, json.dumps(job)))
        return job

    def test_unrelated_held_manager_record_passes_without_metadata_changes(self):
        other = self.request(baseline(id='article-005', slug='single-burner-ranking'))
        raw = json.dumps({'status': 'requires_reconciliation', 'action': {'job_id': other['id']},
                          'usage': {'output_tokens': 19}, 'oldEvidence': ['retain']}, indent=2)
        self.manager_receipt(raw)
        self.assertFalse(self.runtime._revision_manager_blocks(json.dumps({
            'status': 'requires_reconciliation', 'action': {'jobId': other['id']}}), self.job))
        with self.runtime.ledger._tx() as db:
            before = db.execute("SELECT key,value FROM meta WHERE key LIKE 'editorial_manager:%'").fetchall()
        self.assertEqual('completed', self.retry()['status'])
        with self.runtime.ledger._tx() as db:
            self.assertEqual(before, db.execute("SELECT key,value FROM meta WHERE key LIKE 'editorial_manager:%'").fetchall())
        self.assertEqual(self.marker_bytes, self.marker.read_bytes())

    def test_related_or_unknown_manager_scope_blocks_without_spending(self):
        same_id = self.manager_job('older-revision-for-same-article')
        same_slug = self.manager_job('different-id', slug=self.base['slug'])
        other = self.request(baseline(id='article-005', slug='single-burner-ranking'))
        receipts = [{'status': status, 'action': {'job_id': other['id']}}
                    for status in ('evaluating', 'executing')]
        receipts += [{'status': 'requires_reconciliation', 'action': {'job_id': id}}
                     for id in (self.job['id'], self.base['id'], self.base['slug'],
                                same_id['id'], same_slug['id'], 'missing-job', None, [], '')]
        receipts += [{'status': 'requires_reconciliation', 'action': {}},
                     {'status': 'requires_reconciliation', 'action': 'broken'},
                     {'status': 'requires_reconciliation', 'action': {'job_id': other['id'], 'jobId': self.job['id']}},
                     [], {}]
        for receipt in receipts + ['malformed-json']:
            raw = '{' if receipt == 'malformed-json' else json.dumps(receipt)
            with self.subTest(receipt=receipt):
                self.manager_receipt(raw)
                with self.assertRaises(ValueError):
                    self.retry()
                with self.runtime.ledger._tx() as db:
                    self.assertEqual(raw, db.execute('SELECT value FROM meta WHERE key=?',
                                     ('editorial_manager:held',)).fetchone()[0])
                self.assertFalse(self.retry_marker.exists())
        self.models.draft.assert_not_called()
        self.assertEqual([self.original], self.records())

    def assert_budget_cap(self, scope):
        from model_budget import BudgetHold
        budget = self.runtime.model_budget
        alias = self.runtime._budget_article_id(self.job['id'])
        payload = {'model': 'fixture', 'max_tokens': 1, 'messages': []}
        cap = 32 if scope == 'article' else 128
        for i in range(cap):
            article = alias if scope == 'article' else 'prior-fixture-' + str(i // 32)
            with budget.scope(article, 'draft'):
                rid = budget.reserve(payload)
                budget.settle(rid, usage={'input_tokens': 0, 'output_tokens': 0})
        caught = []
        def request(*_):
            try:
                budget.reserve(payload)
            except BudgetHold as error:
                caught.append(error)
                raise
            self.fail('budget allowed a provider request')
        self.models.draft.side_effect = request
        self.assertEqual('attention', self.retry()['status'])
        saved = self.runtime.ledger.get_job(self.job['id'])
        self.assertEqual('model_budget_hold', saved['error']['reason'])
        self.assertEqual(scope + '_calls_cap', caught[0].reason_code)
        self.assertEqual(alias, caught[0].article_id)
        child = next(r for r in self.records() if r.get('predecessorKey') == self.old)
        self.assertEqual(('failed', 2, 2), (child['status'], child['attempts'], child['maxAttempts']))

    def test_same_public_slug_article_32_cap_is_preserved(self):
        self.assert_budget_cap('article')

    def test_shared_period_128_cap_is_preserved(self):
        self.assert_budget_cap('period')

    def test_unknown_result_consumes_remaining_attempt_without_rearming(self):
        self.models.draft.side_effect = ModelOutcomeUnknown('uncertain provider outcome')
        self.assertEqual('attention', self.retry()['status'])
        child = next(r for r in self.records() if r.get('predecessorKey') == self.old)
        self.assertEqual(2, child['attempts'])
        self.assertEqual('unknown', json.loads(self.retry_marker.read_text())['status'])
        with self.assertRaises((ValueError, StageBlocked)): self.retry()

    def test_old_exact_retry_still_rejects_changed_inputs(self):
        self.assertEqual('attention', self.runtime.retry_stage(self.job['id'], 'draft', self.old)['status'])
        self.assertEqual([self.original], self.records())
        self.models.draft.assert_not_called()

    def test_suspended_runtime_cannot_spend_operator_retry(self):
        self.config['executionPolicy']['suspended'] = True
        with self.assertRaisesRegex(ValueError, 'execution_suspended'):
            self.retry()
        self.assertFalse(self.retry_marker.exists())
        self.models.draft.assert_not_called()

    def test_existing_operator_cli_is_dry_run_until_execute_and_holds_runtime_lock(self):
        import fcntl
        import operations
        config_path = self.runtime.root / 'operator-test-config.json'
        atomic(config_path, self.config)
        args = ['--state-root', str(self.runtime.root), '--config', str(config_path),
                '--job-id', self.job['id'], '--stage', 'draft', '--input-key', self.old,
                'retry-corrected-stage']
        before = self.runtime.ledger.db_path.read_bytes()
        output = StringIO()
        with redirect_stdout(output), patch('runtime.Runtime.__init__', side_effect=AssertionError('construct')):
            operations.main(args)
        self.assertFalse(json.loads(output.getvalue())['executed'])
        self.assertEqual(before, self.runtime.ledger.db_path.read_bytes())
        self.models.draft.assert_not_called()
        original = self.runtime._make_article
        def checked(*values):
            with (self.runtime.root / 'runtime.flock').open('a') as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original(*values)
        output = StringIO()
        with redirect_stdout(output), patch('runtime.Runtime', wraps=Runtime, return_value=self.runtime), \
                patch.object(self.runtime, '_make_article', side_effect=checked):
            operations.main(args[:-1] + ['--execute', args[-1]])
        self.assertEqual('completed', json.loads(output.getvalue())['status'])
        self.assertEqual([], self.writes)


if __name__ == '__main__':
    unittest.main()
