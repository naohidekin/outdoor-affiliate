"""Read-only and opt-in execution contracts for the local operator CLI."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import unittest

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
