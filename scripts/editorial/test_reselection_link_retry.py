"""Exact replacement job only: one corrected draft with unchanged budgets/history."""
import json
import unittest
from unittest.mock import Mock

from models import ModelError
from runtime import Runtime
from stage_journal import StageBlocked
import test_supplemental_reselection as fixture


class ReselectionLinkRetryTests(unittest.TestCase):
    tearDown = fixture.ReselectionTests.tearDown
    history = fixture.ReselectionTests.history
    prepare = fixture.ReselectionTests.prepare
    apply = fixture.ReselectionTests.apply

    def setUp(self):
        fixture.ReselectionTests.setUp(self)
        self.receipt = self.apply()
        self.job = self.runtime.ledger.get_job(self.receipt['newJobId'])
        self.inputs = {'dependencies': {'articleContext': 'old-first-five'}, 'schemaVersion': 1}
        with self.assertRaises(ModelError):
            self.runtime._run_model_stage(self.job, 'draft', self.inputs,
                lambda: (_ for _ in ()).throw(ModelError('Unknown or self internal article link')), 'fixture')
        self.runtime.ledger.set_stage(self.job['id'], 'error', {'reason': 'Unknown or self internal article link'})
        self.job = self.runtime.ledger.get_job(self.job['id'])
        self.old = self.runtime.stage_journal.status(job_id=self.job['id'])['records'][0]
        self.operation = Mock(return_value={'revalidated': 'fixture'})

    def run_corrected(self):
        def make(job, context):
            self.runtime._run_model_stage(job, 'draft', dict(self.inputs, dependencies={'articleContext': 'corrected-five'}),
                                          self.operation, 'fixture')
        self.runtime._make_article = Mock(side_effect=make)
        return self.runtime.retry_corrected_stage(self.job['id'], 'draft', self.old['stageKey'])

    def test_corrected_exact_job_inherits_only_remaining_attempt(self):
        self.run_corrected()
        self.operation.assert_called_once()
        records = self.runtime.stage_journal.status(job_id=self.job['id'])['records']
        old = next(r for r in records if r['stageKey'] == self.old['stageKey'])
        for key, value in self.old.items():
            if key != 'updatedAt': self.assertEqual(value, old[key])
        new = next(r for r in records if r.get('predecessorKey') == self.old['stageKey'])
        self.assertEqual(('succeeded', 2, 2), (new['status'], new['attempts'], new['maxAttempts']))
        self.assertEqual(self.old['stageKey'], new['predecessorKey'])
        self.assertEqual(self.old['jobId'], new['jobId'])
        self.assertEqual(self.receipt['plan']['oldJobId'], self.runtime._budget_article_id(self.job['id']))
        with self.assertRaises((ValueError, StageBlocked)): self.run_corrected()

    def test_missing_receipt_other_job_error_or_exhausted_lineage_cannot_use_case(self):
        for change in ({'id': 'other'}, {'batchSlot': 1}, {'budgetArticleId': 'fresh'},
                       {'error': {'reason': 'different validation'}}, {'review': {}}, {'batchCallCap': 97}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Runtime.validate_corrected_retry(dict(self.job, **change), 'draft', self.old['stageKey'],
                    [self.old], reselection_receipt=self.receipt)
        with self.assertRaises(ValueError):
            Runtime.validate_corrected_retry(self.job, 'draft', self.old['stageKey'], [self.old])
        for changed in ({'attempts': 2}, {'status': 'unknown'}, {'successorKey': 'spent'}):
            with self.subTest(changed=changed), self.assertRaises(StageBlocked):
                Runtime.validate_corrected_retry(self.job, 'draft', self.old['stageKey'],
                    [dict(self.old, **changed)], reselection_receipt=self.receipt)

    def test_source_drift_holds_before_model_and_keeps_old_attempt(self):
        self.context['products'][1]['specs']['weight'] = '999g'
        self.runtime._make_article = Mock()
        self.runtime.retry_corrected_stage(self.job['id'], 'draft', self.old['stageKey'])
        self.runtime._make_article.assert_not_called()
        self.assertEqual([self.old], self.runtime.stage_journal.status(job_id=self.job['id'])['records'])
        self.operation.assert_not_called()

    def test_other_stage_unknown_is_not_a_draft_retry(self):
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO meta VALUES (?,?)', ('stage_journal:v1:unknown-polish',
                json.dumps({'jobId': self.job['id'], 'stage': 'polish', 'status': 'unknown'})))
        with self.assertRaises(ValueError): self.run_corrected()
        self.operation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
