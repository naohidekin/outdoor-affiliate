"""Safety and classification tests for the read-only record inspector."""
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import operations
from record_inspection import FOLDERS, MAX_FILE_BYTES, inspect_records


class RecordInspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        self.root.mkdir()
        self.db = self.root / 'ledger.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,data TEXT)')
            db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,job_id TEXT,kind TEXT,data TEXT)')
            db.execute('CREATE TABLE effects(job_id TEXT,kind TEXT,status TEXT,data TEXT)')
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO meta VALUES (?,?)', ('owner_id', 'PRIVATE_OWNER'))
        for name in FOLDERS + ('deliveries',):
            (self.root / name).mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def put_job(self, id='job-1', revision='rev-current'):
        job = {'id': id, 'stage': 'review', 'revision': revision,
               'theme': {'title': 'Safe title'}, 'publication': {},
               'approval': {'revision': revision}, 'social': {'revision': 'social-current'}}
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO jobs VALUES (?,?)', (id, json.dumps(job)))
        return job

    def put_request(self, id, status, revision, *, verified=False):
        request = {'request_id': id, 'article_id': 'job-1', 'manifest_hash': revision,
                   'nonce': 'SECRET_NONCE', 'content': 'PRIVATE BODY', 'status': status}
        if verified:
            request['parts'] = {'parts': [{'verified': True}, {'verified': True}]}
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                       (id, 'job-1', 'article', json.dumps(request)))

    def test_current_unknown_and_old_invalidated_are_classified_without_capabilities(self):
        self.put_job()
        self.put_request('current-private-id', 'created', 'rev-current')
        self.put_request('old-private-id', 'invalidated', 'rev-old')
        (self.root / 'deliveries/current-private-id.json').write_text(
            json.dumps({'status': 'in_flight', 'request_id': 'current-private-id'}))
        value = inspect_records(self.root)
        self.assertEqual('current_delivery_unconfirmed',
                         value['deliveries']['unresolved'][0]['safeReasonCode'])
        self.assertEqual(1, value['deliveries']['historicalNonblockingCount'])
        rendered = json.dumps(value)
        for secret in ('current-private-id', 'old-private-id', 'SECRET_NONCE', 'PRIVATE BODY', 'PRIVATE_OWNER'):
            self.assertNotIn(secret, rendered)

    def test_delivered_ledger_with_verified_parts_and_unfinished_journal_is_not_resend(self):
        self.put_job()
        self.put_request('private-id', 'delivered', 'rev-current', verified=True)
        (self.root / 'deliveries/private-id.json').write_text('{"status":"in_flight"}')
        item = inspect_records(self.root)['deliveries']['unresolved'][0]
        self.assertEqual('ledger_delivered_journal_unfinished', item['safeReasonCode'])
        self.assertEqual('unconfirmed', item['status'])

    def test_unknown_publish_workorder_duplicates_and_receipt_article_binding(self):
        self.put_job()
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', ('job-1', 'publish', 'unknown', '{}'))
            db.execute('INSERT INTO meta VALUES (?,?)', ('editorial_manager:x', json.dumps({'status': 'executing'})))
            order = json.dumps({'status': 'human_needed', 'action': 'reconcile_unknown',
                                'jobId': 'job-1', 'revision': 'rev-current'})
            db.execute('INSERT INTO meta VALUES (?,?)', ('editorial_manager_work:a', order))
            db.execute('INSERT INTO meta VALUES (?,?)', ('editorial_manager_work:b', order))
        (self.root / 'post-publication-audits/a.json').write_text(
            json.dumps({'status': 'requires_reconciliation', 'id': 'job-1', 'body': 'PRIVATE'}))
        value = inspect_records(self.root)
        self.assertEqual('effect_outcome_unconfirmed', value['unresolvedEffects'][0]['safeReasonCode'])
        self.assertEqual(1, value['managerExecutions']['counts']['executing'])
        self.assertEqual(2, value['managerWorkOrders']['groups'][0]['count'])
        audit = next(f for f in value['receiptFolders'] if f['kind'] == 'post-publication-audits')
        self.assertEqual('job-1', audit['records'][0]['articleId'])
        self.assertNotIn('PRIVATE', json.dumps(value))

    def test_known_statusless_receipt_schemas_are_conservative(self):
        self.put_job()
        (self.root / 'social-publications/social.json').write_text(json.dumps({
            'phase': 'verified', 'revision': 'social-current', 'account': 'private-account',
            'mainId': 'private-id', 'pending': None}))
        (self.root / 'social-publications/mainread.json').write_text(json.dumps({
            'phase': 'mainread', 'revision': 'social-current', 'mainId': 'private-main',
            'replyId': None, 'pending': None}))
        (self.root / 'index-tracking/complete.json').write_text(json.dumps({
            'id': 'job-1', 'checks': [{'sitemap': 'current', 'index': 'indexed'}]}))
        (self.root / 'index-tracking/legacy.json').write_text(json.dumps({
            'id': 'job-1', 'checks': []}))
        value = inspect_records(self.root)
        social = next(f for f in value['receiptFolders'] if f['kind'] == 'social-publications')
        tracking = next(f for f in value['receiptFolders'] if f['kind'] == 'index-tracking')
        self.assertEqual(1, social['incompleteCount'])
        self.assertEqual(0, social['unknownBindingCount'])
        self.assertEqual('mainread', social['records'][0]['status'])
        self.assertEqual(1, tracking['incompleteCount'])
        self.assertEqual('unknown', tracking['records'][0]['status'])
        rendered = json.dumps(value)
        for private in ('private-account', 'private-id', 'private-main'):
            self.assertNotIn(private, rendered)

    def test_database_bytes_unchanged_cli_ignores_config_env_and_credentials(self):
        self.put_job()
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        (self.root / '.env').write_text('TOKEN=do-not-read')
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == '.env':
                raise AssertionError('credential access')
            return original(path, *args, **kwargs)
        output = StringIO()
        with patch.object(Path, 'open', guarded), patch.dict('os.environ', {'PRIVATE_TOKEN': 'no'}, clear=True), redirect_stdout(output):
            operations.main(['--state-root', str(self.root), '--config', str(self.root / '.env'), 'records'])
        value = json.loads(output.getvalue())
        self.assertEqual('read_only', value['status'])
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assertNotIn('do-not-read', output.getvalue())

    def test_full_article_records_fit_but_finite_oversize_is_diagnostic(self):
        job = self.put_job()
        job['bundle'] = {'article': {'title': 'Large normal article', 'content': 'x' * 70000}}
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job), job['id']))
        normal = inspect_records(self.root)
        self.assertEqual('read_only', normal['status'])
        self.assertEqual('Large normal article', normal['jobs'][0]['title'])
        job['bundle']['article']['content'] = 'x' * (MAX_FILE_BYTES + 1)
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job), job['id']))
        oversized = inspect_records(self.root)
        self.assertEqual('diagnostic_error', oversized['status'])
        self.assertEqual([], oversized['jobs'])
        self.assertIn('record_oversized', [item['code'] for item in oversized['diagnostics']])

    def test_missing_and_corrupt_are_diagnostics_not_zero(self):
        missing = Path(self.tmp.name) / 'missing'
        missing.mkdir()
        value = inspect_records(missing)
        self.assertEqual('diagnostic_error', value['status'])
        self.assertEqual('ledger_missing_or_invalid', value['diagnostics'][0]['code'])
        partial = Path(self.tmp.name) / 'partial'
        partial.mkdir()
        with sqlite3.connect(partial / 'ledger.sqlite3') as db:
            db.execute('CREATE TABLE jobs(id TEXT,data TEXT)')
        table_error = inspect_records(partial)
        self.assertEqual('required_tables_missing', table_error['diagnostics'][0]['code'])
        self.db.write_text('not sqlite PRIVATE_ERROR')
        corrupt = inspect_records(self.root)
        self.assertEqual('diagnostic_error', corrupt['status'])
        self.assertEqual('ledger_corrupt_or_unreadable', corrupt['diagnostics'][-1]['code'])
        self.assertNotIn('PRIVATE_ERROR', json.dumps(corrupt))


if __name__ == '__main__':
    unittest.main()
