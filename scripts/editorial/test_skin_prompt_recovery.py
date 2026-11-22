"""Offline eligibility and existing corrected-lineage integration; no providers."""
import copy
import unittest
from unittest.mock import patch

from models import ModelError
from runtime import Runtime
from stage_journal import StageBlocked
import test_runtime


JOB = 'article-b1059cbd51d84cee93adbdc6'
BATCH = 'winter-depth-2026-11-22'
OLD = 'stage_journal:v1:aa5d8885296281a0a41b548269e72fe7d44a44e47797cdd5c20bc505d80d6710'
ERROR = 'exact failed stage inputs changed'


def historical_validation(*args):
    # Simulate only the retired authorized digest during this read-only check.
    # Journal/budget hashing outside validation remains real and unpatched.
    with patch('runtime.hashlib.sha256') as digest:
        digest.return_value.hexdigest.return_value = '144fcbca061d8ebd8be8c67c8241a40b53c0ba1f27dc1d52f885c88eb081bf44'
        return Runtime.validate_corrected_retry(*args)


def job_fixture():
    return dict(id=JOB, kind='supplemental_article', batchId=BATCH,
                batchCallCap=96, stage='error', bundle=None, approval=None,
                publication=None, error={'reason': ERROR})


def record_fixture():
    return dict(stageKey=OLD, jobId=JOB, stage='draft', status='failed',
                attempts=1, maxAttempts=2)


class SkinPromptEligibilityTests(unittest.TestCase):
    def test_only_exact_job_batch_error_key_and_draft_are_eligible(self):
        job, record = job_fixture(), record_fixture()
        original = copy.deepcopy((job, record))
        historical_validation(job, 'draft', OLD, [record])
        self.assertEqual(original, (job, record))
        for change in ({'id': 'other'}, {'batchId': 'apparel-2026-11-22'},
                       {'batchId': 'winter-depth-other'}, {'kind': 'article_revision'},
                       {'batchCallCap': 97}, {'stage': 'candidate'},
                       {'error': {'reason': 'unrelated failure'}},
                       {'bundle': {}}, {'approval': {}}, {'publication': {}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                historical_validation(dict(job, **change), 'draft', OLD, [record])
        for stage, key in [('polish', OLD), ('final_review', OLD), ('draft', OLD + '0')]:
            with self.subTest(stage=stage, key=key), self.assertRaises(ValueError):
                historical_validation(job, stage, key, [record])

    def test_unknown_inflight_exhausted_or_previously_bound_lineages_rejected(self):
        job, record = job_fixture(), record_fixture()
        changes = [{'status': status} for status in ('unknown', 'in_flight', 'succeeded')]
        changes += [{'attempts': 2}, {'attempts': 0}, {'maxAttempts': 3},
                    {'successorKey': 'already-used'}, {'predecessorKey': 'prior'},
                    {'jobId': 'other'}, {'stage': 'polish'}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(StageBlocked):
                historical_validation(job, 'draft', OLD, [dict(record, **change)])
        for records in ([], [record, dict(record, stageKey='other')]):
            with self.assertRaises(StageBlocked):
                historical_validation(job, 'draft', OLD, records)

    def test_prompt_scope_is_pinned_to_authorized_models_bytes(self):
        with self.assertRaisesRegex(ValueError, 'prompt_change_recovery_inputs_changed'):
            Runtime.validate_corrected_retry(job_fixture(), 'draft', OLD, [record_fixture()])
        with patch('runtime.Path.read_bytes', return_value=b'unapproved prompt'):
            with self.assertRaisesRegex(ValueError, 'prompt_change_recovery_inputs_changed'):
                Runtime.validate_corrected_retry(job_fixture(), 'draft', OLD, [record_fixture()])
        with patch('runtime.Path.read_bytes', side_effect=OSError('unavailable')):
            with self.assertRaisesRegex(ValueError, 'prompt_change_recovery_inputs_unavailable'):
                Runtime.validate_corrected_retry(job_fixture(), 'draft', OLD, [record_fixture()])


class SkinPromptLineageTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown

    def test_operator_route_reuses_remaining_lineage_attempt_and_preserves_history(self):
        job = job_fixture()
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, job, 'synthetic_skin_failure')
        old_inputs = {'content': 'fixture', 'dependencies': {'prompt': 'prior'}, 'schemaVersion': 1}
        with self.assertRaises(ModelError):
            self.runtime.stage_journal.run(JOB, 'draft', old_inputs,
                lambda: (_ for _ in ()).throw(ModelError('original known draft failure')))
        journal = self.runtime.stage_journal
        generated_key = journal.key(JOB, 'draft', old_inputs)
        # Synthetic persisted historical receipt, under the authorized old key.
        with self.runtime.ledger._tx() as db:
            old = journal._load(db, generated_key)
            db.execute('DELETE FROM meta WHERE key=?', (generated_key,))
            old['stageKey'] = OLD
            journal._save(db, OLD, old)
        journal.record_usage(JOB, 'draft', OLD, [{'responseId': 'historical-fixture'}], reason='initial')
        with self.runtime.ledger._tx() as db:
            before = copy.deepcopy(journal._load(db, OLD))
        new_inputs = dict(old_inputs, dependencies={'prompt': 'current'})
        def produce(**kwargs):
            self.assertEqual({'limit': 1, 'job_id': JOB}, kwargs)
            def operation():
                # Charge the unchanged real budget implementation; no model call.
                reservation = self.runtime.model_budget.reserve(
                    {'model': 'fixture', 'max_tokens': 1, 'messages': []})
                self.runtime.model_budget.settle(reservation,
                    usage={'input_tokens': 0, 'output_tokens': 0}, response_id='synthetic-recovery')
                return {'content': 'synthetic result'}
            result = self.runtime._run_model_stage(job, 'draft', new_inputs, operation, 'fixture')
            return {'status': 'fixture_completed', 'output': result}
        with patch.object(self.runtime, 'validate_corrected_retry', side_effect=historical_validation), \
                patch.object(self.runtime, 'produce_supplemental', side_effect=produce), \
                patch.object(journal, 'retry_corrected_failed', wraps=journal.retry_corrected_failed) as retry:
            result = self.runtime.retry_corrected_stage(JOB, 'draft', OLD)
        self.assertEqual('fixture_completed', result['status'])
        retry.assert_called_once()
        self.assertEqual((JOB, 'draft', OLD, new_inputs), retry.call_args.args[:4])
        with self.runtime.ledger._tx() as db:
            prior = journal._load(db, OLD)
            successor = journal._load(db, prior['successorKey'])
            calls = db.execute('SELECT count(*) FROM model_budget_reservations').fetchone()[0]
        for field, value in before.items():
            if field != 'updatedAt':
                self.assertEqual(value, prior[field], field)
        self.assertEqual(('failed', 1, 2), (prior['status'], prior['attempts'], prior['maxAttempts']))
        self.assertEqual(('succeeded', 2, 2, OLD, 1),
            (successor['status'], successor['attempts'], successor['maxAttempts'],
             successor['predecessorKey'], successor['inheritedAttempts']))
        self.assertEqual(1, calls)
        with patch.object(self.runtime, 'validate_corrected_retry', side_effect=historical_validation):
            with self.assertRaises(StageBlocked):
                self.runtime.retry_corrected_stage(JOB, 'draft', OLD)
        self.assertIsNone(self.runtime.ledger.get_job(JOB)['approval'])
        self.assertIsNone(self.runtime.ledger.get_job(JOB)['publication'])
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)


if __name__ == '__main__':
    unittest.main()
