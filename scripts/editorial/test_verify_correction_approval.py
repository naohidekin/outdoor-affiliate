"""Offline actual-ledger authority tests for the corrected publisher verifier."""
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_catalog_correction_runtime as integration
from ledger import fingerprint
from verify_correction_approval import main, verify


class CorrectionApprovalVerifierTests(unittest.TestCase):
    def setUp(self):
        self.fixture = integration.CatalogCorrectionRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.runtime
        self.ledger = self.runtime.ledger
        self.job = self.fixture.approve(self.fixture.produce())
        self.ledger.claim_effect(self.job['id'], 'publish')
        self.env = dict(CAMP_EDITORIAL_STATE_ROOT=str(self.ledger.root), CAMP_EDITORIAL_OWNER_ID='U')
        a = self.job['approval']
        self.request = dict(action='publish-corrected', bundle=copy.deepcopy(self.job['bundle']),
                            revision=self.job['revision'], approval=dict(revision=a['revision'], approverId=a['user_id'],
                            evidence=dict(requestId=a['request_id'], approvedAt=a['at'],
                                          source=a.get('source', 'authenticated-slack-receiver'))))

    def tearDown(self):
        self.fixture.tearDown()

    def mutate_job(self, change):
        with self.ledger._tx() as db:
            job = self.ledger._get(db, self.job['id'])
            change(job)
            self.ledger._put(db, job, 'test')

    def test_actual_slack_approval_verifies_without_modifying_ledger(self):
        before = self.ledger.db_path.read_bytes()
        self.assertTrue(verify(self.request, self.env))
        self.assertEqual(before, self.ledger.db_path.read_bytes())
        self.assertEqual(self.job, self.ledger.get_job(self.job['id']))

    def test_stdin_approval_strings_do_not_grant_authority(self):
        self.mutate_job(lambda job: job.update(approval=None))
        self.assertFalse(verify(self.request, self.env))

    def test_bound_owner_request_time_source_and_manifest_must_match(self):
        for field in ('approverId', 'revision'):
            with self.subTest(field=field):
                req = copy.deepcopy(self.request)
                req['approval'][field] = 'forged'
                self.assertFalse(verify(req, self.env))
        for field in ('requestId', 'approvedAt', 'source'):
            with self.subTest(field=field):
                req = copy.deepcopy(self.request)
                req['approval']['evidence'][field] = 'forged'
                self.assertFalse(verify(req, self.env))
        self.assertFalse(verify(self.request, dict(self.env, CAMP_EDITORIAL_OWNER_ID='wrong')))
        req = copy.deepcopy(self.request)
        req['bundle']['article']['content'] += 'forged'
        self.assertFalse(verify(req, self.env))
        req['revision'] = fingerprint(req['bundle'])
        req['approval']['revision'] = req['revision']
        self.assertFalse(verify(req, self.env))

    def test_actual_stage_publication_fingerprint_context_and_qa_are_required(self):
        for change in (lambda job: job.update(stage='review'),
                       lambda job: job.update(publication={'verified': True}),
                       lambda job: job.update(revision='0' * 64),
                       lambda job: job.pop('catalogCorrectionContext'),
                       lambda job: job.update(astraReview=None)):
            with self.subTest(change=change):
                self.mutate_job(change)
                self.assertFalse(verify(self.request, self.env))
                with self.ledger._tx() as db:
                    self.ledger._put(db, copy.deepcopy(self.job), 'restore')

    def test_missing_failed_unknown_or_complete_effect_never_verifies(self):
        with self.ledger._tx() as db:
            db.execute('DELETE FROM effects WHERE job_id=?', (self.job['id'],))
        self.assertFalse(verify(self.request, self.env))
        for status in ('failed', 'unknown', 'success'):
            with self.subTest(status=status):
                with self.ledger._tx() as db:
                    db.execute('INSERT OR REPLACE INTO effects VALUES (?,?,?,?)',
                               (self.job['id'], 'publish', status, '{}'))
                self.assertFalse(verify(self.request, self.env))

    def test_unknown_or_replayed_journal_blocks_permit(self):
        folder = self.ledger.root / 'catalog-corrections'
        folder.mkdir(mode=0o700)
        journal = folder / ('a' * 64 + '.json')
        for status in ('unknown', 'in_flight'):
            journal.write_text(json.dumps({'status': status}))
            journal.chmod(0o600)
            self.assertFalse(verify(self.request, self.env))
        journal.write_text(json.dumps({'status': 'complete'}))
        self.assertTrue(verify(self.request, self.env))
        journal.rename(folder / (self.job['revision'] + '.json'))
        self.assertFalse(verify(self.request, self.env))

    def test_legacy_codex_actual_record_without_action_is_supported(self):
        approval = copy.deepcopy(self.job['approval'])
        approval.pop('action')
        approval['source'] = 'codex'
        approval['evidence'] = {'source': 'codex', 'text': 'owner actual instruction'}
        self.mutate_job(lambda job: job.update(approval=approval))
        self.request['approval']['evidence']['source'] = 'codex'
        self.assertTrue(verify(self.request, self.env))
        self.mutate_job(lambda job: job['approval'].update(action='held'))
        self.assertFalse(verify(self.request, self.env))

    def test_private_ownership_permissions_missing_root_and_symlinks_fail_closed(self):
        self.assertFalse(verify(self.request, {}))
        for path, wrong_mode, correct_mode in ((self.ledger.root, 0o755, 0o700),
                                               (self.ledger.db_path, 0o644, 0o600)):
            path.chmod(wrong_mode)
            self.assertFalse(verify(self.request, self.env))
            path.chmod(correct_mode)
        with patch('verify_correction_approval.os.getuid', return_value=os.getuid() + 1):
            self.assertFalse(verify(self.request, self.env))
        link = self.ledger.root.parent / 'state-link'
        link.symlink_to(self.ledger.root, target_is_directory=True)
        self.assertFalse(verify(self.request, dict(self.env, CAMP_EDITORIAL_STATE_ROOT=str(link))))
        backup = self.ledger.root / 'original.sqlite3'
        self.ledger.db_path.rename(backup)
        self.ledger.db_path.symlink_to(backup)
        self.assertFalse(verify(self.request, self.env))
        self.ledger.db_path.unlink()
        backup.rename(self.ledger.db_path)
        self.assertFalse(verify(self.request, dict(self.env, CAMP_EDITORIAL_STATE_ROOT=str(self.ledger.root / 'missing'))))
        self.assertFalse((self.ledger.root / 'missing').exists())

    def test_cli_outputs_only_boolean_for_success_and_failure(self):
        for payload, expected in ((json.dumps(self.request), True), ('malformed SECRET', False)):
            with self.subTest(expected=expected), patch.dict(os.environ, self.env, clear=True), \
                    patch('sys.stdin', io.StringIO(payload)), patch('sys.stdout', new_callable=io.StringIO) as out:
                main()
                self.assertEqual({'verified': expected}, json.loads(out.getvalue()))


if __name__ == '__main__':
    unittest.main()
