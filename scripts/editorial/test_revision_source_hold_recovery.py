"""Offline tests for one explicit pre-model revision source recovery."""
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from ledger import canonical, fingerprint
from runtime import JST
import test_runtime
import revision_source_hold_recovery as recovery
from test_inherited_advice import context as inherited_context
from test_revision_workflow import baseline, spec


NOW = datetime(2026, 11, 28, 22, 30, tzinfo=JST)


class RevisionSourceHoldRecoveryTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        original_renderer = self.runtime.renderer
        def renderer(bundle, job):
            value = original_renderer(bundle, job)
            value['inheritedPresentationContext'] = inherited_context(
                bundle['article']['slug'])
            return value
        self.runtime.renderer = renderer
        self.base = baseline()
        self.job = self.runtime.ledger.request_revision(spec(self.base), now=NOW)
        self.production_period = '2026-11-27'
        self.runtime.ledger.production_schedule.period_key = Mock(
            return_value=self.production_period)
        context = self.runtime._context()
        context['articles'] = [self.base]
        context['revisionArticles'] = [self.base]
        context['products'] = copy.deepcopy(
            self.job['revisionContext']['baseProducts'])
        self.runtime._context = Mock(return_value=context)
        candidate = self.models.draft({}, {})
        candidate['article']['tags'] = []
        candidate['products'] = copy.deepcopy(
            self.job['revisionContext']['candidateProducts'])
        self.models.draft = Mock(return_value=candidate)
        gathered = self.runtime.catalog.gather({}, {})
        gathered.update(
            productIds=list(self.job['theme']['productIds']),
            products=copy.deepcopy(self.job['revisionContext']['baseProducts']),
            images=test_runtime.bundle()['images'],
            checks={'facts': True, 'images': False, 'affiliate': True},
            evidence={'products': [{
                'productId': pid, 'facts': True, 'images': False,
                'affiliate': True} for pid in self.job['theme']['productIds']]})
        self.runtime.catalog.gather_revision = Mock(return_value=gathered)
        result = self.runtime._produce_requested_revision()
        self.assertEqual('attention', result['status'])
        self.assertEqual(0, self.models.draft.call_count)
        self.marker = (self.runtime.root / 'revision-production-attempts' /
                       (self.job['id'] + '.json'))
        self.marker_bytes = self.marker.read_bytes()
        self.failed_source_bytes = (self.runtime.root / 'research' /
                                    (self.job['id'] + '.json')).read_bytes()
        self.grant = self.owner_grant()
        self.imported = self.add_imported_budget_baseline()
        self.authorization = patch.dict(recovery.AUTHORIZED, {self.job['id']: {
            'action': recovery.ACTION,
            'specHash': fingerprint(self.job['revisionContext']),
            'ownerGrantHash': fingerprint(self.grant),
            'instructionReceiptSha256': self.grant['instructionReceiptSha256'],
            'productionPeriod': self.production_period,
            'existingImportedBudgetReceipts': self.imported,
        }})
        self.authorization.start()
        self.addCleanup(self.authorization.stop)

    tearDown = test_runtime.RuntimeTests.tearDown

    def owner_grant(self, instruction='Retry the exact source-held burner revision once after the verified image repair.'):
        owner_id = self.runtime.ledger.owner_id
        receipt = {
            'schemaVersion': 1, 'ownerId': owner_id, 'source': 'codex_task_message',
            'instruction': instruction,
            'instructionSha256': hashlib.sha256(instruction.encode()).hexdigest(),
            'evidence': {'source': 'codex', 'kind': 'task_message',
                         'threadId': '01a19beb-c298-7b23-926f-bbae16a35acd',
                         'turnId': '01a2221b-29ff-7d91-923b-8ce12144715a',
                         'userMessageId': '01a2221b-2ba4-7ff2-9914-a7a627100a67'},
        }
        task_hash = fingerprint(receipt)
        folder = self.runtime.root / 'owner-instructions'
        folder.mkdir(mode=0o700, exist_ok=True)
        raw = (canonical(receipt) + '\n').encode()
        path = folder / (task_hash + '.json')
        path.write_bytes(raw); path.chmod(0o600)
        return {'ownerId': owner_id, 'taskRef': 'owner-task:' + task_hash,
                'instructionSha256': receipt['instructionSha256'],
                'instructionReceiptSha256': hashlib.sha256(raw).hexdigest()}

    def fresh_source(self):
        value = copy.deepcopy(self.runtime.catalog.gather_revision.return_value)
        value['checks']['images'] = True
        for row in value['evidence']['products']:
            row['images'] = True
        return value

    def add_imported_budget_baseline(self):
        budget_id = self.runtime._budget_article_id(self.job['id'])
        stages = ('draft', 'polish', 'final_review')
        rows = []
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            for index, stage in enumerate(stages, 1):
                values = (
                    'import-fixture-' + stage, 'response-fixture-' + stage,
                    'source-' + stage, budget_id, stage, '2026-11-13',
                    'fixture-model', 'imported', 0, 0, 100 * index, 10 * index,
                    'success', '2026-11-20T00:00:00+09:00',
                    '2026-11-20T00:00:00+09:00')
                db.execute('''INSERT INTO model_budget_reservations
                    (reservation_id,response_id,source_hash,article_id,stage,period_key,
                     model,status,reserved_input_tokens,reserved_output_tokens,
                     actual_input_tokens,actual_output_tokens,outcome,created_at,settled_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', values)
            cursor = db.execute(
                'SELECT * FROM model_budget_reservations WHERE article_id=? ORDER BY reservation_id',
                (budget_id,))
            columns = [item[0] for item in cursor.description]
            for values in cursor.fetchall():
                row = dict(zip(columns, values))
                rows.append({'reservationId': row['reservation_id'],
                             'dataHash': fingerprint(row)})
        return rows

    def retry(self):
        return self.runtime.retry_revision_source_hold(
            self.job['id'], fingerprint(self.job['revisionContext']),
            self.grant, expected_current_period=self.production_period, now=NOW)

    def test_exact_source_hold_runs_normal_pipeline_once_and_preserves_old_marker(self):
        self.runtime.catalog.gather_revision.return_value = self.fresh_source()
        self.runtime.catalog.gather_revision.reset_mock()

        dry = self.runtime.prepare_revision_source_hold_retry(
            self.job['id'], fingerprint(self.job['revisionContext']), self.grant,
            expected_current_period=self.production_period, now=NOW)
        self.assertEqual(('ready', self.production_period, 3),
                         (dry['status'], dry['productionPeriod'],
                          len(dry['existingImportedReservationIds'])))
        self.assertFalse((self.runtime.root / 'revision-source-hold-recovery-attempts' /
                          (self.job['id'] + '.json')).exists())

        result = self.retry()

        self.assertEqual('completed', result['status'])
        self.assertNotEqual(self.job['week'], self.production_period)
        self.runtime.catalog.gather_revision.assert_called_once()
        self.models.draft.assert_called_once()
        saved = self.runtime.ledger.get_job(self.job['id'])
        self.assertEqual('review', saved['stage'])
        self.assertIsNone(saved['approval']); self.assertIsNone(saved['publication'])
        self.assertEqual(self.marker_bytes, self.marker.read_bytes())
        attempt = self.runtime.root / 'revision-source-hold-recovery-attempts' / (self.job['id'] + '.json')
        result_path = self.runtime.root / 'revision-source-hold-recovery-results' / (self.job['id'] + '.json')
        attempt_value = json.loads(attempt.read_text())
        archive = self.runtime.root / attempt_value['failedSourceArchive']
        self.assertEqual(self.failed_source_bytes, archive.read_bytes())
        self.assertEqual(0o600, archive.stat().st_mode & 0o777)
        self.assertEqual(hashlib.sha256(self.failed_source_bytes).hexdigest(),
                         attempt_value['failedSourceSha256'])
        self.assertEqual(self.imported,
                         attempt_value['existingImportedBudgetReceipts'])
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            old = db.execute(
                "SELECT count(*) FROM model_budget_reservations WHERE status='imported' "
                "AND article_id=?", (self.runtime._budget_article_id(self.job['id']),)).fetchone()[0]
        self.assertEqual(3, old)
        self.assertEqual(('claimed', 'completed'),
                         (attempt_value['status'],
                          json.loads(result_path.read_text())['status']))
        with self.assertRaises(ValueError):
            self.retry()

    def test_fresh_source_failure_is_durable_and_never_calls_models(self):
        self.runtime.catalog.gather_revision.reset_mock()

        result = self.retry()

        self.assertEqual(('attention', 'blocked'),
                         (result['status'], result['outcome']))
        self.runtime.catalog.gather_revision.assert_called_once()
        self.models.draft.assert_not_called()
        self.assertEqual(self.marker_bytes, self.marker.read_bytes())
        with self.assertRaises(ValueError):
            self.retry()

    def test_wrong_spec_or_owner_grant_never_claims_or_gathers(self):
        self.runtime.catalog.gather_revision.reset_mock()
        bad = self.owner_grant('A different valid task instruction must not authorize this recovery.')
        with self.assertRaises(ValueError):
            self.runtime.retry_revision_source_hold(
                self.job['id'], fingerprint(self.job['revisionContext']), bad,
                expected_current_period=self.production_period, now=NOW)
        with self.assertRaises(ValueError):
            self.runtime.retry_revision_source_hold(
                self.job['id'], '0' * 64, self.grant,
                expected_current_period=self.production_period, now=NOW)
        self.runtime.catalog.gather_revision.assert_not_called()
        self.assertFalse((self.runtime.root / 'revision-source-hold-recovery-attempts' /
                          (self.job['id'] + '.json')).exists())

    def test_stale_expected_production_period_rejects_before_claim(self):
        self.runtime.catalog.gather_revision.reset_mock()
        with self.assertRaisesRegex(ValueError, 'period_changed'):
            self.runtime.retry_revision_source_hold(
                self.job['id'], fingerprint(self.job['revisionContext']), self.grant,
                expected_current_period='2026-11-20', now=NOW)
        self.runtime.catalog.gather_revision.assert_not_called()
        self.assertFalse((self.runtime.root / 'revision-source-hold-recovery-attempts' /
                          (self.job['id'] + '.json')).exists())

    def test_new_unknown_or_additional_shared_budget_row_rejects_before_claim(self):
        budget_id = self.runtime._budget_article_id(self.job['id'])
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            db.execute('''INSERT INTO model_budget_reservations
                (reservation_id,response_id,source_hash,article_id,stage,period_key,
                 model,status,reserved_input_tokens,reserved_output_tokens,
                 actual_input_tokens,actual_output_tokens,outcome,created_at,settled_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('unexpected', None, None, budget_id, 'draft', self.production_period,
                 'fixture', 'unknown', 0, 0, None, None, 'unknown',
                 NOW.isoformat(), NOW.isoformat()))
        with self.assertRaisesRegex(ValueError, 'shared_budget_receipts_changed'):
            self.retry()
        self.assertFalse((self.runtime.root / 'revision-source-hold-recovery-attempts' /
                          (self.job['id'] + '.json')).exists())

    def test_any_current_job_budget_row_rejects_before_claim(self):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            db.execute('''INSERT INTO model_budget_reservations
                (reservation_id,response_id,source_hash,article_id,stage,period_key,
                 model,status,reserved_input_tokens,reserved_output_tokens,
                 actual_input_tokens,actual_output_tokens,outcome,created_at,settled_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('current-job-attempt', None, None, self.job['id'], 'draft',
                 self.production_period, 'fixture', 'unknown', 0, 0, None, None,
                 'unknown', NOW.isoformat(), NOW.isoformat()))
        with self.assertRaisesRegex(ValueError, 'current_job_model_attempt_exists'):
            self.retry()


if __name__ == '__main__':
    unittest.main()
