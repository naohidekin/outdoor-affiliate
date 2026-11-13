import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from ledger import Ledger
from stage_journal import (OperationResult, StageBlocked, StageJournal, StageUnknown,
                           normalize_dependencies, read_status)


class SimulatedCrash(BaseException):
    pass


class StageJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'private-ledger'
        self.ledger = Ledger(self.root, 'owner')
        self.journal = StageJournal(self.ledger)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def inputs(content='one', dependency='route-v1'):
        return {
            'content': content,
            'dependencies': {'modelRoute': dependency, 'code': 'abc123'},
            'schemaVersion': {'input': 1, 'output': 2},
        }

    def test_success_reuse_is_deep_copied_and_makes_zero_new_calls(self):
        calls = []

        def operation():
            calls.append('called')
            return {'nested': ['original']}

        first = self.journal.run('job-1', 'draft', self.inputs(), operation)
        first['nested'].append('caller mutation')
        second = self.journal.run('job-1', 'draft', self.inputs(), operation)
        self.assertEqual({'nested': ['original']}, second)
        self.assertEqual(['called'], calls)
        status = self.journal.status(job_id='job-1')
        self.assertEqual(1, status['byStage']['draft']['hits'])
        self.assertNotIn('output', status['records'][0])

    def test_changed_content_or_exact_dependency_invalidates_cache(self):
        calls = []
        for inputs in (self.inputs(), self.inputs('two'), self.inputs('two', 'route-v2')):
            self.journal.run('job-1', 'draft', inputs,
                             lambda value=len(calls): calls.append(value) or {'call': value})
        self.assertEqual([0, 1, 2], calls)
        self.assertEqual(3, self.journal.status()['counts']['succeeded'])

    def test_crash_leaves_inflight_and_blocks_even_changed_inputs(self):
        with self.assertRaises(SimulatedCrash):
            self.journal.run('job-1', 'research', self.inputs(),
                             lambda: (_ for _ in ()).throw(SimulatedCrash()))
        calls = []
        with self.assertRaises(StageUnknown):
            self.journal.run('job-1', 'research', self.inputs('changed'),
                             lambda: calls.append(True))
        self.assertEqual([], calls)
        self.journal.reconcile_in_flight('job-1', 'research', self.inputs(), outcome='failed')
        self.journal.run('job-1', 'research', self.inputs('changed'),
                         lambda: calls.append(True) or {'ok': True})
        self.assertEqual([True], calls)

    def test_corrupt_or_unknown_prefix_record_blocks_changed_input(self):
        with self.ledger._tx() as db:
            db.execute('INSERT INTO meta VALUES (?,?)', ('stage_journal:v1:corrupt', '{bad'))
        with self.assertRaises(StageUnknown):
            self.journal.run('job-1', 'draft', self.inputs(), lambda: {'unsafe': True})
        with self.ledger._tx() as db:
            db.execute("DELETE FROM meta WHERE key='stage_journal:v1:corrupt'")
        self.journal.run('job-1', 'draft', self.inputs(), lambda: {'ok': True})
        key = self.journal.key('job-1', 'draft', self.inputs())
        with self.ledger._tx() as db:
            record = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            record['status'] = 'mystery'
            db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(record), key))
        with self.assertRaises(StageUnknown):
            self.journal.run('job-1', 'draft', self.inputs('changed'), lambda: {'unsafe': True})

    def test_provider_unknown_preserves_inflight_reservation(self):
        class OutcomeUnknown(RuntimeError):
            outcome_unknown = True
        with self.assertRaises(StageUnknown):
            self.journal.run('job-1', 'draft', self.inputs(),
                             lambda: (_ for _ in ()).throw(OutcomeUnknown('private')))
        self.assertEqual('in_flight', self.journal.status(job_id='job-1')['records'][0]['status'])

    def test_known_failure_is_not_automatically_rerun_and_original_survives(self):
        calls = []

        def fail():
            calls.append(True)
            raise LookupError('private failure detail')

        with self.assertRaisesRegex(LookupError, 'private failure detail'):
            self.journal.run('job-1', 'quality', self.inputs(), fail)
        with self.assertRaises(StageBlocked):
            self.journal.run('job-1', 'quality', self.inputs(), fail)
        self.assertEqual([True], calls)
        raw = self.ledger.db_path.read_bytes()
        self.assertNotIn(b'private failure detail', raw)

    def test_operation_unknown_stays_inflight_and_cannot_retry_or_change_input(self):
        inputs = self.inputs()
        with self.assertRaises(StageUnknown):
            self.journal.run('job-1', 'publish', inputs,
                             lambda: (_ for _ in ()).throw(StageUnknown('provider outcome unknown')))
        with self.assertRaises(StageUnknown):
            self.journal.retry_failed('job-1', 'publish', inputs, lambda: {'bad': 'retry'})
        with self.assertRaises(StageUnknown):
            self.journal.run('job-1', 'publish', self.inputs('changed'),
                             lambda: {'bad': 'new input'})
        record = self.journal.status()['records'][0]
        self.assertEqual('in_flight', record['status'])
        self.assertEqual(1, record['attempts'])

    def test_explicit_retry_is_same_key_and_hard_capped(self):
        calls = []

        def fail():
            calls.append(True)
            raise RuntimeError('no')

        with self.assertRaises(RuntimeError):
            self.journal.run('job-1', 'polish', self.inputs(), fail)
        with self.assertRaises(RuntimeError):
            self.journal.retry_failed('job-1', 'polish', self.inputs(), fail)
        with self.assertRaises(StageBlocked) as caught:
            self.journal.retry_failed('job-1', 'polish', self.inputs(), fail)
        self.assertEqual('exhausted', caught.exception.status)
        self.assertEqual(2, len(calls))
        self.assertEqual(2, self.journal.status()['records'][0]['attempts'])

    def test_tampered_cached_output_fails_closed(self):
        inputs = self.inputs()
        self.journal.run('job-1', 'draft', inputs, lambda: {'safe': True})
        key = self.journal.key('job-1', 'draft', inputs)
        with self.ledger._tx() as db:
            record = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            record['output']['safe'] = False
            db.execute('UPDATE meta SET value=? WHERE key=?',
                       (json.dumps(record, sort_keys=True, separators=(',', ':')), key))
        with self.assertRaises(StageUnknown) as caught:
            self.journal.run('job-1', 'draft', inputs, lambda: {'unsafe': True})
        self.assertEqual('corrupt', caught.exception.status)

    def test_secret_inputs_are_only_persisted_as_hashes(self):
        secret = 'SECRET_INPUT_VALUE_42'
        result = self.journal.run('job-1', 'draft', self.inputs(secret),
                                  lambda: OperationResult({'public': 'result'}, {'receipt': 'usage-1'}))
        self.assertEqual({'public': 'result'}, result)
        self.assertNotIn(secret.encode(), self.ledger.db_path.read_bytes())
        with sqlite3.connect(self.ledger.db_path) as db:
            events = '\n'.join(row[0] for row in db.execute(
                "SELECT data FROM events WHERE kind LIKE 'stage_%'"))
        self.assertNotIn(secret, events)

    def test_concurrent_reservation_is_serialized_before_operation(self):
        entered = threading.Event()
        release = threading.Event()
        outcomes = []

        def first_operation():
            entered.set()
            release.wait(5)
            return {'winner': 1}

        def first():
            outcomes.append(self.journal.run('job-1', 'draft', self.inputs(), first_operation))

        thread = threading.Thread(target=first)
        thread.start()
        self.assertTrue(entered.wait(5))
        second_calls = []
        other = StageJournal(Ledger(self.root, 'owner'))
        with self.assertRaises(StageUnknown):
            other.run('job-1', 'draft', self.inputs(),
                      lambda: second_calls.append(True) or {'winner': 2})
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], second_calls)
        self.assertEqual([{'winner': 1}], outcomes)

    def test_usage_accounting_preserves_records_and_status_only_exposes_counts(self):
        inputs = self.inputs()
        key = self.journal.key('job-1', 'draft', inputs)
        self.journal.run('job-1', 'draft', inputs, lambda: {'ok': True})
        records = [{'responseId': 'r-1', 'requestedModel': 'requested-x',
                    'actualModel': None, 'usage': {'input_tokens': 3},
                    'actualInvoiceUsd': None}]
        self.journal.record_usage('job-1', 'draft', key, records, reason='initial')
        status = read_status(self.ledger.db_path)
        self.assertEqual({'stageAttempts': 1, 'responseReceipts': 1,
                          'missingUsageAttempts': 0, 'hits': 0, 'records': 1},
                         status['byStage']['draft'])
        self.assertNotIn('usageBatches', status['records'][0])
        with self.ledger._tx() as db:
            stored = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        self.assertEqual(records, stored['usageBatches'][0]['records'])
        self.assertIsNone(stored['usageBatches'][0]['records'][0]['actualModel'])

    def test_usage_projects_anthropic_cache_creation_and_ignores_extensions(self):
        inputs = self.inputs()
        key = self.journal.key('job-1', 'draft', inputs)
        self.journal.run('job-1', 'draft', inputs, lambda: {'ok': True})
        self.journal.record_usage('job-1', 'draft', key, [{
            'responseId': 'r-cache', 'model': 'claude', 'requestedModel': 'claude',
            'actualModel': 'claude', 'input': 7, 'output': 2, 'actualUSD': None,
            'providerExtension': {'private': 'ignored'},
            'usage': {'input_tokens': 7, 'output_tokens': 2,
                      'cache_creation_input_tokens': 5,
                      'cache_creation': {'ephemeral_5m_input_tokens': 3,
                                         'ephemeral_1h_input_tokens': 2,
                                         'future_private_field': 'ignored'},
                      'future_usage_field': {'private': 'ignored'}},
        }])
        with self.ledger._tx() as db:
            stored = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        saved = stored['usageBatches'][0]['records'][0]
        self.assertNotIn('providerExtension', saved)
        self.assertNotIn('future_usage_field', saved['usage'])
        self.assertEqual(5, saved['usage']['cache_creation_input_tokens'])
        self.assertEqual({'ephemeral_5m_input_tokens': 3, 'ephemeral_1h_input_tokens': 2},
                         saved['usage']['cache_creation'])
        self.journal.record_usage('job-1', 'draft', key,
                                  [{'responseId': 'r-2', 'secretBody': 'do not persist'}])
        self.assertNotIn(b'do not persist', self.ledger.db_path.read_bytes())

    def test_empty_usage_slice_is_missing_measurement_not_zero_calls(self):
        inputs = self.inputs()
        key = self.journal.key('job-1', 'draft', inputs)
        self.journal.run('job-1', 'draft', inputs, lambda: {'ok': True})
        self.journal.record_usage('job-1', 'draft', key, [], reason='initial')
        status = self.journal.status()
        self.assertEqual(1, status['byStage']['draft']['stageAttempts'])
        self.assertEqual(0, status['byStage']['draft']['responseReceipts'])
        self.assertEqual(1, status['byStage']['draft']['missingUsageAttempts'])
        self.assertTrue(status['records'][0]['missingUsage'])

    def test_normalization_is_explicit_and_exact_path_only(self):
        dependencies = {'checkedAt': 'clock', 'nested': {'checkedAt': 'keep'},
                        'article': {'createdAt': 'created', 'updatedAt': 'updated'},
                        'preview': {'path': '/tmp/private', 'other': 1}}
        self.assertEqual(dependencies, normalize_dependencies(dependencies))
        normalized = normalize_dependencies(
            dependencies, omit_paths=('checkedAt', 'article.createdAt', 'preview.path'))
        self.assertEqual({'checkedAt': 'keep'}, normalized['nested'])
        self.assertEqual({'updatedAt': 'updated'}, normalized['article'])
        self.assertEqual({'other': 1}, normalized['preview'])
        with self.assertRaises(ValueError):
            normalize_dependencies(dependencies, omit_paths=('nested.checkedAt',))


if __name__ == '__main__':
    unittest.main()
