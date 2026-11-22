"""Literal response reuse consumes validation lineage, not another writer call."""
import copy
from contextlib import redirect_stdout
import fcntl
import hashlib
from io import StringIO
import json
import unittest
from unittest.mock import Mock, patch

from ledger import fingerprint
from runtime import atomic
from stage_journal import StageBlocked
import reselection_saved_draft as saved
import test_reselection_link_retry as fixture
from test_models import bundle


class SavedDraftTests(unittest.TestCase):
    tearDown = fixture.ReselectionLinkRetryTests.tearDown
    history = fixture.ReselectionLinkRetryTests.history
    prepare = fixture.ReselectionLinkRetryTests.prepare
    apply = fixture.ReselectionLinkRetryTests.apply

    def setUp(self):
        fixture.ReselectionLinkRetryTests.setUp(self)
        candidate = bundle()
        pid = self.job['theme']['productIds'][0]
        candidate = json.loads(json.dumps(candidate).replace('tent-a', pid))
        candidate['article'].pop('id')
        candidate['article']['slug'] = self.job['theme']['slug']
        candidate['article']['categoryId'] = 'wear'
        self.raw = {'article': candidate['article'], 'brief': candidate['brief']}
        product = self.products[1]
        self.source = {'theme': self.job['theme'], 'products': [product], 'catalog': [product],
            'references': candidate['references'], 'images': [{'productId': pid, 'url': product['imageUrl']}],
            'existingArticles': [{'slug': 'other-old'}], 'editorialLearnings': [],
            'checks': {'facts': True, 'images': True, 'affiliate': True}}
        self.fresh = copy.deepcopy(self.source)
        self.fresh['existingArticles'] = [{'slug': 'setup'}, {'slug': 'pack'}]
        self.artifact_path = self.runtime.root / 'model-artifacts' / (hashlib.sha256(saved.RESPONSE.encode()).hexdigest() + '.json')
        atomic(self.artifact_path, {'responseId': saved.RESPONSE, 'model': 'claude-opus-4-8',
                                  'content': json.dumps(self.raw), 'usage': {'input_tokens': 41240, 'output_tokens': 6406}})
        atomic(self.runtime.root / 'research' / (self.job['id'] + '.json'), self.source)
        pins = patch.multiple(saved, JOB=self.job['id'], OLD_KEY=self.old['stageKey'],
            ARTIFACT_SHA=hashlib.sha256(self.artifact_path.read_bytes()).hexdigest(), SOURCE_SHA=fingerprint(self.source))
        pins.start(); self.addCleanup(pins.stop)
        self.writer = Mock(side_effect=AssertionError('writer must not run'))

    def execute(self):
        def make(job, _context):
            inputs = {'dependencies': {'source': self.runtime._source_dependencies(self.fresh)}, 'schemaVersion': 1}
            local = self.runtime._explicit_stage_retry['savedOutputLocalRevalidation']
            local.bind(job, self.fresh, inputs)
            self.output = self.runtime._run_model_stage(job, 'draft', inputs, self.writer, 'claude-opus-4-8')
        self.runtime._make_article = Mock(side_effect=make)
        return self.runtime.retry_saved_reselection_draft(self.job['id'], self.old['stageKey'])

    def test_literal_pass_preserves_old_failure_and_no_writer_usage_or_budget_reservation(self):
        with self.runtime.ledger._tx() as db:
            before = db.execute('SELECT * FROM model_budget_reservations').fetchall()
        self.execute(); self.writer.assert_not_called()
        records = self.runtime.stage_journal.status(job_id=self.job['id'])['records']
        child = next(r for r in records if r.get('predecessorKey') == self.old['stageKey'])
        self.assertEqual(('succeeded', 2, 2), (child['status'], child['attempts'], child['maxAttempts']))
        self.assertTrue(child['usageReferencePresent'])
        self.assertEqual(0, child.get('responseReceiptCount', 0))
        self.assertEqual(self.raw['article']['content'], self.output['article']['content'])
        self.assertEqual(self.raw['brief'], self.output['brief'])
        with self.runtime.ledger._tx() as db:
            full = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (child['stageKey'],)).fetchone()[0])
            self.assertEqual(0, full['usageReference']['writerApiCalls'])
            self.assertFalse(full['usageReference']['paidUsageReplayed'])
            self.assertEqual(before, db.execute('SELECT * FROM model_budget_reservations').fetchall())
        receipt = json.loads((self.runtime.root / 'saved-output-local-revalidations' / (self.job['id'] + '.json')).read_text())
        self.assertEqual(child['stageKey'], receipt['newStageKey'])
        self.assertEqual(fingerprint({k: v for k, v in receipt.items() if k not in ('status', 'bindingSha256')}),
                         full['usageReference']['receiptBindingSha256'])
        with self.assertRaises((ValueError, FileExistsError, StageBlocked)): self.execute()

    def test_any_non_navigation_source_change_holds_before_local_stage_or_writer(self):
        self.fresh['catalog'][0]['specs']['weight'] = '999g'
        self.execute()
        self.writer.assert_not_called()
        self.assertEqual([self.old], self.runtime.stage_journal.status(job_id=self.job['id'])['records'])
        receipt = json.loads((self.runtime.root / 'saved-output-local-revalidations' / (self.job['id'] + '.json')).read_text())
        self.assertEqual('requires_reconciliation', receipt['status'])

    def test_artifact_tamper_refuses_before_producer_and_scope_never_generalizes(self):
        self.artifact_path.write_text(self.artifact_path.read_text() + ' ')
        with self.assertRaises(ValueError): self.execute()
        self.runtime._make_article.assert_not_called()
        for id, key in ((self.job['id'] + 'other', self.old['stageKey']), (self.job['id'], 'other-key')):
            with self.assertRaises(ValueError): saved.load(self.runtime.root, id, key)

    def test_unfixed_context_is_rejected_by_current_pure_validator(self):
        self.fresh['existingArticles'] = [{'slug': 'still-missing'}]
        self.execute()
        self.writer.assert_not_called()
        self.assertEqual([self.old], self.runtime.stage_journal.status(job_id=self.job['id'])['records'])

    def test_normal_builder_runs_polish_and_retains_structural_gate_after_local_draft(self):
        self.runtime.catalog.gather = Mock(side_effect=lambda *_: copy.deepcopy(self.fresh))
        self.models.draft = self.writer
        self.models.polish = Mock(wraps=self.models.polish)
        self.models.review = Mock(wraps=self.models.review)
        result = self.runtime.retry_saved_reselection_draft(self.job['id'], self.old['stageKey'])
        self.writer.assert_not_called()
        self.models.polish.assert_called_once()
        self.models.review.assert_not_called()
        self.assertEqual('article_structure_or_affiliate_failed', result['articles'][0]['reason'])
        records = self.runtime.stage_journal.status(job_id=self.job['id'])['records']
        self.assertEqual('succeeded', next(r for r in records if r['stage'] == 'polish')['status'])

    def test_operator_cli_planning_is_readonly_execution_uses_runner_lease(self):
        import operations
        from runtime import Runtime
        config_path = self.runtime.root / 'saved-draft-config.json'
        atomic(config_path, self.config)
        args = ['--state-root', str(self.runtime.root), '--config', str(config_path), '--job-id', self.job['id'],
                '--stage', 'draft', '--input-key', self.old['stageKey'], 'retry-saved-reselection-draft']
        with patch('runtime.Runtime.__init__', side_effect=AssertionError('dry-run cannot create Runtime')), \
                redirect_stdout(StringIO()) as out:
            operations.main(args)
        self.assertFalse(json.loads(out.getvalue())['executed'])
        self.assertFalse((self.runtime.root / 'saved-output-local-revalidations').exists())
        self.runtime.catalog.gather = Mock(side_effect=lambda *_: copy.deepcopy(self.fresh))
        self.models.draft = self.writer
        original = self.runtime.retry_saved_reselection_draft
        def under_lock(*values):
            with (self.runtime.root / 'runtime.flock').open('a') as other:
                with self.assertRaises(BlockingIOError): fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original(*values)
        with patch('runtime.Runtime', wraps=Runtime, return_value=self.runtime), \
                patch.object(self.runtime, 'retry_saved_reselection_draft', side_effect=under_lock), \
                redirect_stdout(StringIO()):
            operations.main(args + ['--execute'])
        self.writer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
