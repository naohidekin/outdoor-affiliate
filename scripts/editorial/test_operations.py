"""Read-only and opt-in execution contracts for the local operator CLI."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import fcntl

import test_deterministic_runtime

import operations
import test_runtime


class OperationsTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config['executionPolicy'] = {
            'mode': 'deterministic', 'suspended': False,
            'exceptions': {'autoAI': False},
        }
        self.config_path = Path(self.tmp.name) / 'config.json'
        self.config_path.write_text(json.dumps(self.config))

    tearDown = test_runtime.RuntimeTests.tearDown

    def test_status_and_plan_read_ledger_without_runtime_construction(self):
        self.runtime.ledger.create_candidate({'slug': 'local', 'title': 'Local'})
        status = operations.status(self.runtime.root)
        plan = operations.plan(self.runtime.root, self.config)
        self.assertEqual('read_only', status['status'])
        self.assertEqual('local', self.runtime.ledger.get_job(status['jobs'][0]['id'])['theme']['slug'])
        self.assertEqual('produce', plan['actions'][0]['kind'])
        self.assertNotIn('keys', status)

    def test_retry_stage_is_dry_run_by_default(self):
        output = StringIO()
        with redirect_stdout(output):
            operations.main(['--state-root', str(self.runtime.root), '--config', str(self.config_path),
                             '--job-id', 'article-id', '--stage', 'polish',
                             '--input-key', 'stage_journal:v1:key', 'retry-stage'])
        value = json.loads(output.getvalue())
        self.assertEqual({'status': 'planned', 'operation': 'retry-stage', 'jobId': 'article-id',
                          'stage': 'polish', 'inputKey': 'stage_journal:v1:key',
                          'executed': False}, value)

    def test_corrected_cli_dryrun_validates_exact_failure_without_mutation(self):
        job, key, _, _ = test_deterministic_runtime.DeterministicRuntimeTests.corrected_fixture(self)
        self.config_path.write_text(json.dumps(self.config))
        before = self.runtime.ledger.db_path.read_bytes()
        output = StringIO()
        args = ['--state-root', str(self.runtime.root), '--config', str(self.config_path),
                '--job-id', job['id'], '--stage', 'draft', '--input-key', key,
                'retry-corrected-stage']
        with redirect_stdout(output), patch('runtime.Runtime.__init__', side_effect=AssertionError('construction')):
            operations.main(args)
        value = json.loads(output.getvalue())
        self.assertEqual('retry-corrected-stage', value['operation'])
        self.assertFalse(value['executed'])
        self.assertEqual(before, self.runtime.ledger.db_path.read_bytes())
        self.assertFalse((self.runtime.root / 'runtime.flock').exists())
        with self.assertRaises(__import__('stage_journal').StageBlocked):
            operations.main([arg if arg != key else 'wrong-key' for arg in args])

    def test_corrected_cli_execute_uses_existing_runtime_lock(self):
        job, key, manifest, context = test_deterministic_runtime.DeterministicRuntimeTests.corrected_fixture(self)
        self.config_path.write_text(json.dumps(self.config))
        args = ['--state-root', str(self.runtime.root), '--config', str(self.config_path),
                '--job-id', job['id'], '--stage', 'draft', '--input-key', key,
                '--execute', 'retry-corrected-stage']
        output = StringIO()
        with (self.runtime.root / 'runtime.flock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with redirect_stdout(output), patch('runtime.Runtime', side_effect=AssertionError('busy')):
                operations.main(args)
        self.assertEqual('busy', json.loads(output.getvalue())['status'])
        output = StringIO()
        with redirect_stdout(output), patch('runtime.Runtime', wraps=test_runtime.Runtime, return_value=self.runtime), \
                patch.object(self.runtime, '_supplemental_manifest', return_value=manifest), \
                patch.object(self.runtime.catalog, 'catalog', return_value=context):
            operations.main(args)
        self.assertEqual('awaiting_approval', json.loads(output.getvalue())['articles'][0]['status'])
        self.assertEqual('review', self.runtime.ledger.get_job(job['id'])['stage'])
        self.assertEqual(1, len(self.slack.deliveries))

    def test_suspended_retry_returns_before_runtime_even_with_execute(self):
        self.config['executionPolicy']['suspended'] = True
        self.config_path.write_text(json.dumps(self.config))
        output = StringIO()
        with redirect_stdout(output):
            operations.main(['--state-root', str(self.runtime.root), '--config', str(self.config_path),
                             '--job-id', 'article-id', '--stage', 'draft',
                             '--input-key', 'stage_journal:v1:key', '--execute', 'retry-stage'])
        self.assertEqual({'status': 'suspended', 'mode': 'deterministic'},
                         json.loads(output.getvalue()))


if __name__ == '__main__':
    unittest.main()
