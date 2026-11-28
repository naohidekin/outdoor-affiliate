"""A display-only repair must never purchase draft/polish again."""
import unittest
from unittest.mock import Mock, patch
import test_runtime as fixtures
from stage_journal import StageBlocked


class RenderResumeCacheGuardTests(unittest.TestCase):
    def setUp(self):
        fixtures.RuntimeTests.setUp(self)
    tearDown = fixtures.RuntimeTests.tearDown

    def seed(self):
        job = self.runtime.ledger.create_candidate({'slug': 'cached-guide'})
        inputs = {'source': 'verified', 'version': 1, 'dependencies': {'source': 'fixture'}, 'schemaVersion': 1}
        result = self.runtime._run_model_stage(job, 'draft', inputs,
                                                lambda: {'body': 'saved'}, 'fixture-model')
        self.assertEqual({'body': 'saved'}, result)
        key = self.runtime.stage_journal.key(job['id'], 'draft', inputs)
        self.runtime._cache_only_stage_keys = {'draft': key}
        return job, inputs

    def test_exact_cached_paid_output_has_no_provider_or_budget_operation(self):
        job, inputs = self.seed()
        operation = Mock(side_effect=AssertionError('must not purchase draft'))
        with patch.object(self.runtime.model_budget, 'scope', side_effect=AssertionError('must not reserve')):
            result = self.runtime._run_model_stage(job, 'draft', inputs, operation, 'fixture-model')
        self.assertEqual({'body': 'saved'}, result)
        operation.assert_not_called()

    def test_changed_input_stops_before_budget_and_new_stage_reservation(self):
        job, inputs = self.seed()
        before = self.runtime.stage_journal.status(job_id=job['id'])
        operation = Mock(side_effect=AssertionError('must not purchase changed draft'))
        with patch.object(self.runtime.model_budget, 'scope', side_effect=AssertionError('must not reserve')):
            with self.assertRaises(StageBlocked):
                self.runtime._run_model_stage(job, 'draft', dict(inputs, version=2), operation, 'fixture-model')
        self.assertEqual(before, self.runtime.stage_journal.status(job_id=job['id']))
        operation.assert_not_called()

    def test_cache_operation_fallback_cannot_cross_budget_boundary(self):
        job, inputs = self.seed()
        operation = Mock(side_effect=AssertionError('must not purchase fallback'))
        def force_operation(_job, _stage, _inputs, callback, **_kwargs):
            return callback()
        with patch.object(self.runtime.stage_journal, 'run', side_effect=force_operation), \
                patch.object(self.runtime.model_budget, 'scope', side_effect=AssertionError('must not reserve')):
            with self.assertRaises(StageBlocked):
                self.runtime._run_model_stage(job, 'draft', inputs, operation, 'fixture-model')
        operation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
