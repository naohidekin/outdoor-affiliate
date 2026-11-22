"""Real cached stages and normal final-review path; no providers/public writes."""
import copy
from contextlib import redirect_stdout
from datetime import datetime
import fcntl
from io import StringIO
import json
import unittest
from unittest.mock import Mock, patch

from ledger import fingerprint
from models import ModelError
from runtime import atomic
from test_revision_workflow import baseline, spec
import test_revision_workflow as workflow
import revision_purchase_na_resume as recovery


class PurchaseNAResumeTests(unittest.TestCase):
    tearDown = workflow.RevisionWorkflowTests.tearDown
    context = workflow.RevisionWorkflowTests.context
    fake_evidence = workflow.RevisionWorkflowTests.fake_evidence

    def setUp(self):
        workflow.RevisionWorkflowTests.setUp(self)
        self.config['executionPolicy'] = {'mode': 'deterministic', 'suspended': False}
        self.base = json.loads(json.dumps(baseline()).replace('tent-a', 'fp-003'))
        specification = spec(self.base)
        for key in ('baseProducts', 'candidateProducts'):
            specification[key][0]['amazonUrl'] = ''
        self.job = self.runtime.ledger.request_revision(specification)
        self.fake_evidence()
        for mock in (self.models.draft, self.runtime.catalog.gather_revision):
            mock.return_value = json.loads(json.dumps(mock.return_value).replace('tent-a', 'fp-003'))
        data = self.runtime.catalog.gather_revision.return_value
        candidate = self.models.draft.return_value
        data.update(products=copy.deepcopy(candidate['products']), catalog=copy.deepcopy(candidate['products']))
        data['evidence'] = {'products': [{'productId': 'fp-003', 'destinations': [{
            'channel': 'rakuten', 'url': candidate['products'][0]['affiliateUrl'], 'verified': True}]}]}
        self.live = self.context(self.base)
        self.runtime._context = Mock(side_effect=lambda: copy.deepcopy(self.live))
        self.models.draft.side_effect = ModelError('Article length outside existing SKILL limits')
        with patch('purchase_evidence.require_prewrite_purchase_evidence'):
            self.runtime._produce_requested_revision()
            old = self.runtime.stage_journal.status(job_id=self.job['id'])['records'][0]['stageKey']
            self.models.draft.side_effect = None
            routes = self.runtime._model_routes()
            routes['implementationHashes']['models.py'] = 'approved-prompt-change'
            self.runtime._model_routes = Mock(return_value=routes)
            self.assertEqual('attention', self.runtime.retry_corrected_stage(self.job['id'], 'draft', old)['status'])
        self.before = self.journal()
        draft = next(r for r in self.before if r['stage'] == 'draft' and r['status'] == 'succeeded')
        polish = next(r for r in self.before if r['stage'] == 'polish')
        self.source_file = next((self.runtime.root / 'research/artifacts' / self.job['id']).glob('*/source.json'))
        self.source = json.loads(self.source_file.read_text())['bundle']
        pins = patch.multiple(recovery, JOB=self.job['id'], SOURCE=fingerprint(self.source),
                              DRAFT=draft['stageKey'], DRAFT_SHA=draft['outputHash'],
                              POLISH=polish['stageKey'], POLISH_SHA=polish['outputHash'])
        pins.start(); self.addCleanup(pins.stop)
        self.evidence = [{'productId': 'fp-003', 'channel': 'amazon', 'status': 'NA',
                          'reason': '今回の検証済みAmazonリンクなし。在庫・取扱の有無は未確認。',
                          'checkedAt': datetime.now(recovery.JST).isoformat(), 'reviewedBy': 'Astra'}]
        self.models.draft.reset_mock()
        self.models.polish = Mock(side_effect=AssertionError('paid polish must not run'))
        self.models.review = Mock(wraps=self.models.review)

    def journal(self):
        with self.runtime.ledger._tx() as db:
            return [json.loads(v) for v, in db.execute("SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]

    def resume(self):
        return self.runtime.resume_revision_review_after_purchase_na(self.job['id'], self.evidence, 'current-owner-request')

    def assert_unspent(self):
        self.models.draft.assert_not_called(); self.models.polish.assert_not_called()
        self.models.review.assert_not_called()
        self.assertFalse((self.runtime.root / 'revision-purchase-na-resumes' / (self.job['id'] + '.json')).exists())

    def test_only_metadata_changes_normal_final_review_and_owner_gates(self):
        result = self.resume()
        self.models.draft.assert_not_called(); self.models.polish.assert_not_called()
        self.models.review.assert_called_once()
        saved = self.runtime.ledger.get_job(self.job['id'])
        self.assertEqual('review', saved['stage'])
        self.assertIsNone(saved['approval']); self.assertIsNone(saved['publication'])
        self.assertEqual([], self.writes)
        for field in ('brief', 'products', 'images', 'references'):
            self.assertEqual(self.source[field], saved['bundle'][field])
        self.assertEqual(self.evidence, saved['bundle']['purchaseEvidence'])
        for old in self.before:
            self.assertEqual(old, next(r for r in self.journal() if r['stageKey'] == old['stageKey']))
        self.assertEqual(1, len([r for r in self.journal() if r['stage'] == 'final_review']))
        receipt = json.loads((self.runtime.root / 'revision-purchase-na-resumes' / (self.job['id'] + '.json')).read_text())
        self.assertEqual('completed', receipt['status'])
        self.assertEqual(fingerprint(receipt['freshProof']), receipt['freshProofSha256'])
        with self.assertRaises(ValueError): self.resume()

    def test_fresh_source_changes_or_failure_hold_before_final(self):
        fresh = self.runtime.catalog.gather_revision.return_value
        original = copy.deepcopy(fresh)
        for field in ('products', 'images', 'references'):
            fresh[field] = []
            with self.assertRaises(ValueError): self.resume()
            fresh.clear(); fresh.update(copy.deepcopy(original))
        fresh['checks']['facts'] = False
        with self.assertRaises(ValueError): self.resume()
        self.assert_unspent()

    def test_na_stale_wrong_channel_or_extra_evidence_hold(self):
        for change in ({'checkedAt': '2026-01-01T00:00:00+09:00'}, {'productId': 'other'},
                       {'channel': 'rakuten'}, {'status': 'verified'}, {'reason': ''}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                recovery.resume(self.runtime, self.job['id'], [dict(self.evidence[0], **change)], 'owner')
        self.assert_unspent()

    def test_tampered_artifact_or_success_payload_is_rejected(self):
        original = self.source_file.read_bytes()
        source = copy.deepcopy(self.source); source['brief']['facts'].append('unverified')
        atomic(self.source_file, {'kind': 'source', 'bundle': source})
        with self.assertRaises(ValueError): self.resume()
        self.source_file.write_bytes(original)
        with self.runtime.ledger._tx() as db:
            raw = next(r for r in self.before if r['stageKey'] == recovery.POLISH)
            raw['output']['polished']['content'] += 'changed'
            db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(raw), recovery.POLISH))
        with self.assertRaises(ValueError): self.resume()
        self.assert_unspent()

    def test_final_attempt_unknown_budget_and_baseline_drift_are_not_rearmed(self):
        self.live['revisionArticles'][0]['content'] += 'changed'
        with self.assertRaises(ValueError): self.resume()
        self.assert_unspent()
        self.live['revisionArticles'][0]['content'] = self.base['content']
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO meta VALUES (?,?)', ('stage_journal:v1:final', json.dumps(
                {'jobId': self.job['id'], 'stage': 'final_review', 'status': 'failed'})))
        with self.assertRaises(ValueError): self.resume()
        self.assert_unspent()

    def test_final_failure_keeps_claim_and_no_new_writer_or_polish(self):
        self.models.review.side_effect = ModelError('review-failed')
        with self.assertRaises(ModelError): self.resume()
        receipt = json.loads((self.runtime.root / 'revision-purchase-na-resumes' / (self.job['id'] + '.json')).read_text())
        self.assertEqual('requires_reconciliation', receipt['status'])
        with self.assertRaises(ValueError): self.resume()
        self.models.draft.assert_not_called(); self.models.polish.assert_not_called()

    def test_unknown_effect_budget_manager_and_suspension_hold(self):
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (self.job['id'], 'publish', 'unknown', '{}'))
        with self.assertRaises(ValueError): self.resume()
        with self.runtime.ledger._tx() as db:
            db.execute('DELETE FROM effects')
            db.execute('INSERT INTO meta VALUES (?,?)', ('editorial_manager:active', json.dumps({'status': 'executing'})))
        with self.assertRaises(ValueError): self.resume()
        with self.runtime.ledger._tx() as db:
            db.execute('DELETE FROM meta WHERE key=?', ('editorial_manager:active',))
        alias = self.runtime._budget_article_id(self.job['id'])
        with self.runtime.model_budget.scope(alias, 'draft'):
            self.runtime.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
        with self.assertRaises(ValueError): self.resume()
        self.config['executionPolicy']['suspended'] = True
        with self.assertRaisesRegex(ValueError, 'execution_suspended'): self.resume()
        self.assert_unspent()

    def test_normal_same_article_budget_cap_applies_to_first_final_attempt(self):
        from model_budget import BudgetHold
        alias = self.runtime._budget_article_id(self.job['id'])
        for _ in range(32):
            with self.runtime.model_budget.scope(alias, 'draft'):
                rid = self.runtime.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
                self.runtime.model_budget.settle(rid, usage={'input_tokens': 0, 'output_tokens': 0})
        self.models.review.side_effect = lambda *_: self.runtime.model_budget.reserve(
            {'model': 'fixture', 'max_tokens': 1, 'messages': []})
        with self.assertRaises(BudgetHold): self.resume()
        self.assertEqual(1, len([r for r in self.journal() if r['stage'] == 'final_review']))
        self.models.draft.assert_not_called(); self.models.polish.assert_not_called()

    def test_future_missing_na_stops_before_any_paid_stage(self):
        self.models.draft.reset_mock(); self.models.polish.reset_mock()
        with self.assertRaises(ValueError):
            self.runtime._make_article(self.runtime.ledger.get_job(self.job['id']), self.live)
        self.assertEqual(self.before, self.journal())
        self.assert_unspent()

    def test_operator_cli_dry_run_is_read_only_and_execute_holds_runner_lock(self):
        import operations
        from runtime import Runtime
        config_path = self.runtime.root / 'test-config.json'
        evidence_path = self.runtime.root / 'test-na.json'
        atomic(config_path, self.config); atomic(evidence_path, self.evidence)
        args = ['--state-root', str(self.runtime.root), '--config', str(config_path),
                '--job-id', self.job['id'], '--purchase-na-json', str(evidence_path),
                '--operator-reference', 'current-owner-request', 'resume-revision-review-after-purchase-na']
        with patch('runtime.Runtime.__init__', side_effect=AssertionError('dry run cannot construct Runtime')), \
                redirect_stdout(StringIO()) as out:
            operations.main(args)
        self.assertFalse(json.loads(out.getvalue())['executed'])
        self.assert_unspent()
        original = self.runtime.resume_revision_review_after_purchase_na
        def under_lock(*values):
            with (self.runtime.root / 'runtime.flock').open('a') as second:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original(*values)
        with patch('runtime.Runtime', wraps=Runtime, return_value=self.runtime), \
                patch.object(self.runtime, 'resume_revision_review_after_purchase_na', side_effect=under_lock), \
                redirect_stdout(StringIO()):
            operations.main(args + ['--execute'])
        self.models.draft.assert_not_called(); self.models.polish.assert_not_called()
        self.models.review.assert_called_once()


if __name__ == '__main__':
    unittest.main()
