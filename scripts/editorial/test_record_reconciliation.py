"""Additive, hash-bound reconciliation contracts for historical records."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import fcntl

from record_inspection import FOLDERS, inspect_records
from record_reconciliation import (apply_reconciliation, check_reconciliation_plan,
                                   prepare_reconciliation, project_reconciliations)


JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=JST)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class RecordReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        self.root.mkdir()
        self.db_path = self.root / 'ledger.sqlite3'
        with sqlite3.connect(self.db_path) as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,data TEXT)')
            db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,job_id TEXT,kind TEXT,data TEXT)')
            db.execute('CREATE TABLE effects(job_id TEXT,kind TEXT,status TEXT,data TEXT)')
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
        for name in FOLDERS + ('deliveries', 'reconciliations', 'social-publications'):
            (self.root / name).mkdir(exist_ok=True)

        self.old_job = self.put_job('revision-old', 'rev-old', '/same-article')
        self.new_job = self.put_job('revision-new', 'rev-new', '/same-article')
        self.manager_job = self.put_job('article-manager', 'rev-manager', '/manager')
        self.index_job = self.put_job('article-index', 'rev-index', '/index')
        self.meta_key = 'editorial_manager_work:' + 'a' * 64
        self.meta_raw = json.dumps({
            'status': 'human_needed', 'action': 'reconcile_unknown',
            'jobId': 'article-manager', 'revision': 'rev-manager',
        }, sort_keys=True, separators=(',', ':'))
        with sqlite3.connect(self.db_path) as db:
            db.execute('INSERT INTO meta VALUES (?,?)', (self.meta_key, self.meta_raw))

        self.blocked = self.put_json('revision-production-attempts/revision-old.json', {
            'status': 'blocked', 'reason': 'render_preview_failed',
            'at': '2026-11-08T12:54:07+09:00',
        })
        self.old_audit_path, self.old_audit = self.put_audit(
            self.old_job, 'failed', False)
        self.new_audit_path, self.new_audit = self.put_audit(
            self.new_job, 'success', True)
        self.old_index = self.put_json('index-tracking/old.json', {
            'id': 'article-index', 'revision': 'rev-index',
            'checks': [{'index': 'not_indexed', 'sitemap': 'current'}],
        })
        self.index_proof = self.put_json(
            'deployments/20261114-readiness/index-readonly.json', [{
                'id': 'article-index', 'sitemapCurrent': True,
                'proof': {'verdict': 'PASS', 'coverageState': 'Submitted and indexed',
                          'googleCanonical': '/index',
                          'lastCrawlTime': '2026-11-14T01:00:00Z'},
            }])
        self.put_json('social-publications/orphan.json', {
            'revision': 'orphan-revision', 'phase': 'mainread',
            'mainId': 'private-main-id', 'replyId': None,
        })

    def tearDown(self):
        self.tmp.cleanup()

    def put_job(self, job_id, revision, url):
        updated = ('2026-11-15T09:37:00+09:00' if job_id == 'revision-new'
                   else '2026-11-09T00:56:00+09:00')
        value = {
            'id': job_id, 'kind': 'article_revision', 'stage': 'published',
            'revision': revision,
            'publication': {'verified': True, 'url': url,
                            'remoteUpdatedAt': updated,
                            'revision': revision,
                            'readback': {'verified': True, 'fingerprint': revision}},
            'revisionContext': {'baseArticle': {'id': 'base:' + url}},
        }
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'))
        with sqlite3.connect(self.db_path) as db:
            db.execute('INSERT INTO jobs VALUES (?,?)', (job_id, raw))
        return raw

    def put_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        path.write_bytes(raw)
        return raw

    def put_audit(self, job_raw, status, passed):
        job = json.loads(job_raw)
        bound = {'id': job['id'], 'revision': job['revision'],
                 'publication': job['publication']}
        key = digest(json.dumps(bound, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')).encode())
        value = dict(bound, schemaVersion=1, auditKey=key, status=status,
                     result={'status': 'passed' if passed else 'failed',
                             'passed': passed,
                             'checks': [{'status': 'passed' if passed else 'failed'}]},
                     attempts=[{'status': status}] * 3,
                     completedAt='2026-11-15T09:45:09+09:00')
        path = 'post-publication-audits/' + key + '.json'
        return path, self.put_json(path, value)

    def json_ref(self, path, raw):
        return {'kind': 'json', 'path': path, 'sha256': digest(raw)}

    def publication_ref(self, job_id, raw):
        job = json.loads(raw)
        projection = {'id': job['id'], 'revision': job['revision'],
                      'publication': job['publication']}
        encoded = json.dumps(projection, sort_keys=True,
                             separators=(',', ':')).encode()
        return {'kind': 'sqlite_publication', 'path': 'ledger.sqlite3',
                'id': job_id, 'sha256': digest(encoded)}

    def entries(self):
        old_job = self.publication_ref('revision-old', self.old_job)
        return [{
            'recordType': 'manager_work_order', 'jobId': 'article-manager',
            'revision': 'rev-manager',
            'source': {'kind': 'sqlite_meta', 'path': 'ledger.sqlite3',
                       'key': self.meta_key, 'sha256': digest(self.meta_raw.encode())},
            'proofs': [{'kind': 'published_same_version',
                        'record': self.publication_ref(
                            'article-manager', self.manager_job)}],
        }, {
            'recordType': 'revision_production_attempt', 'jobId': 'revision-old',
            'revision': 'rev-old',
            'source': self.json_ref(
                'revision-production-attempts/revision-old.json', self.blocked),
            'proofs': [
                {'kind': 'published_same_version', 'record': old_job},
                {'kind': 'superseded_by_published_version', 'sourceJob': old_job,
                 'latestJob': self.publication_ref('revision-new', self.new_job)},
            ],
        }, {
            'recordType': 'post_publication_audit', 'jobId': 'revision-old',
            'revision': 'rev-old',
            'source': self.json_ref(self.old_audit_path, self.old_audit),
            'proofs': [{'kind': 'superseded_by_successful_published_version',
                        'sourceJob': old_job,
                        'latestJob': self.publication_ref('revision-new', self.new_job),
                        'latestAudit': self.json_ref(self.new_audit_path, self.new_audit)}],
        }, {
            'recordType': 'index_tracking', 'jobId': 'article-index',
            'revision': 'rev-index',
            'source': self.json_ref('index-tracking/old.json', self.old_index),
            'proofs': [{'kind': 'same_version_indexed',
                        'record': dict(self.json_ref(
                            'deployments/20261114-readiness/index-readonly.json',
                            self.index_proof), selector={'index': 0}),
                        'job': self.publication_ref('article-index', self.index_job)}],
        }]

    def test_apply_adds_receipt_and_projects_history_without_changing_sources(self):
        before_db = digest(self.db_path.read_bytes())
        before_files = {path: digest((self.root / path).read_bytes()) for path in (
            'revision-production-attempts/revision-old.json',
            self.old_audit_path, 'index-tracking/old.json')}

        plan = prepare_reconciliation(self.root, self.entries())
        self.assertEqual('planned', plan['status'])
        self.assertEqual('checked', check_reconciliation_plan(self.root, plan)['status'])
        applied = apply_reconciliation(self.root, plan, now=NOW)
        self.assertEqual('applied', applied['status'])
        self.assertEqual(4, applied['recordCount'])

        projection = project_reconciliations(self.root)
        self.assertEqual('read_only', projection['status'])
        self.assertEqual({
            'managerWorkOrders': 1, 'revisionProductionAttempts': 1,
            'postPublicationAudits': 1, 'indexTracking': 1,
        }, projection['historicalReconciledCounts'])
        index_overlay = next(item for item in projection['reconciledSources']
                             if item['recordType'] == 'index_tracking')
        self.assertEqual('indexed', index_overlay['proofs'][0]['proofStatus'])
        self.assertEqual('2026-11-14T01:00:00Z',
                         index_overlay['proofs'][0]['observedAt'])
        self.assertTrue(index_overlay['proofs'][0]['readOnly'])
        self.assertEqual({'index': 0},
                         index_overlay['proofs'][0]['evidenceIdentity']['selector'])
        inspected = inspect_records(self.root)
        self.assertEqual(1, inspected['managerWorkOrders']['rawHumanNeededCount'])
        self.assertEqual(0, inspected['managerWorkOrders']['total'])
        self.assertEqual('clear', inspected['managerWorkOrders']['status'])
        self.assertEqual(1, inspected['managerWorkOrders']['historicalReconciledCount'])
        folders = {item['kind']: item for item in inspected['receiptFolders']}
        for name in ('revision-production-attempts', 'post-publication-audits',
                     'index-tracking'):
            self.assertEqual(0, folders[name]['incompleteCount'])
            self.assertEqual(1, folders[name]['historicalReconciledCount'])
        self.assertEqual(1, folders['social-publications']['incompleteCount'])
        self.assertEqual(1, folders['social-publications']['unknownBindingCount'])

        self.assertEqual(before_db, digest(self.db_path.read_bytes()))
        self.assertEqual(before_files, {path: digest((self.root / path).read_bytes())
                                       for path in before_files})

    def test_changed_evidence_invalidates_receipt_and_restores_unresolved_projection(self):
        plan = prepare_reconciliation(self.root, [self.entries()[-1]])
        apply_reconciliation(self.root, plan, now=NOW)
        self.put_json('deployments/20261114-readiness/index-readonly.json', [{
            'id': 'article-index', 'sitemapCurrent': True,
            'proof': {'verdict': 'FAIL', 'coverageState': 'Unknown',
                      'googleCanonical': '/index',
                      'lastCrawlTime': '2026-11-14T01:00:00Z'},
        }])
        projection = project_reconciliations(self.root)
        self.assertEqual('diagnostic_error', projection['status'])
        self.assertEqual(1, projection['invalidReceiptCount'])
        folder = next(item for item in inspect_records(self.root)['receiptFolders']
                      if item['kind'] == 'index-tracking')
        self.assertEqual(1, folder['incompleteCount'])
        self.assertEqual(0, folder['historicalReconciledCount'])

    def test_failed_or_unbound_proof_and_social_success_claim_are_rejected(self):
        bad = self.entries()[-1]
        bad['proofs'][0]['record']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'record hash mismatch'):
            prepare_reconciliation(self.root, [bad])
        social = {
            'recordType': 'social_publication', 'jobId': 'none', 'revision': 'orphan-revision',
            'source': self.json_ref('social-publications/orphan.json',
                                    (self.root / 'social-publications/orphan.json').read_bytes()),
            'proofs': [],
        }
        with self.assertRaisesRegex(ValueError, 'unsupported record type'):
            prepare_reconciliation(self.root, [social])

    def test_publication_proofs_cannot_be_forged_by_allowlisted_json(self):
        job = json.loads(self.manager_job)
        forged = self.put_json('reports/forged-publication.json', {
            'id': job['id'], 'revision': job['revision'],
            'publication': job['publication'],
        })
        entry = self.entries()[0]
        entry['proofs'][0]['record'] = self.json_ref(
            'reports/forged-publication.json', forged)
        with self.assertRaisesRegex(ValueError, 'sqlite publication proof required'):
            prepare_reconciliation(self.root, [entry])

    def test_apply_is_idempotent_but_rejects_naive_jst_timestamp(self):
        plan = prepare_reconciliation(self.root, [self.entries()[0]])
        first = apply_reconciliation(self.root, plan, now=NOW)
        second = apply_reconciliation(self.root, plan, now=NOW)
        self.assertEqual(first['receiptId'], second['receiptId'])
        self.assertEqual('already_applied', second['status'])
        with self.assertRaisesRegex(ValueError, 'aware timestamp required'):
            apply_reconciliation(self.root, plan, now=datetime(2026, 11, 15, 12))

    def test_publication_projection_survives_unrelated_job_progress(self):
        plan = prepare_reconciliation(self.root, [self.entries()[0]])
        job = json.loads(self.manager_job)
        job.update(stage='social_review', approval={'request_id': 'later'})
        with sqlite3.connect(self.db_path) as db:
            db.execute('UPDATE jobs SET data=? WHERE id=?',
                       (json.dumps(job, sort_keys=True, separators=(',', ':')),
                        job['id']))
        self.assertEqual('checked', check_reconciliation_plan(self.root, plan)['status'])

    def test_apply_fails_busy_without_reading_plan_as_current(self):
        plan = prepare_reconciliation(self.root, [self.entries()[0]])
        with (self.root / 'runtime.flock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'runtime lock busy'):
                apply_reconciliation(self.root, plan, now=NOW)

    def test_same_version_readonly_audit_overlay_keeps_original_observation_time(self):
        evidence = self.put_json(
            'deployments/20261114-readiness/revision-old-deployed-audit.json', {
                'id': 'revision-old', 'revision': 'rev-old', 'readOnly': True,
                'at': '2026-11-14T17:51:00+09:00',
                'result': {'status': 'passed', 'passed': True,
                           'checks': [{'status': 'passed'}]},
            })
        entry = {
            'recordType': 'post_publication_audit', 'jobId': 'revision-old',
            'revision': 'rev-old',
            'source': self.json_ref(self.old_audit_path, self.old_audit),
            'proofs': [{'kind': 'same_version_audit_passed',
                        'record': self.json_ref(
                            'deployments/20261114-readiness/revision-old-deployed-audit.json',
                            evidence),
                        'job': self.publication_ref('revision-old', self.old_job)}],
        }
        apply_reconciliation(self.root, prepare_reconciliation(self.root, [entry]), now=NOW)
        overlay = project_reconciliations(self.root)['reconciledSources'][0]
        self.assertEqual({
            'kind': 'same_version_audit_passed', 'proofStatus': 'passed',
            'observedAt': '2026-11-14T17:51:00+09:00', 'readOnly': True,
            'evidenceIdentity': {
                'kind': 'json',
                'path': 'deployments/20261114-readiness/revision-old-deployed-audit.json'},
        }, overlay['proofs'][0])

    def test_passing_standard_audit_requires_nonempty_all_passed_checks(self):
        bad = json.loads(self.new_audit)
        bad['result']['checks'] = []
        raw = self.put_json(self.new_audit_path, bad)
        entry = self.entries()[2]
        entry['proofs'][0]['latestAudit'] = self.json_ref(self.new_audit_path, raw)
        with self.assertRaisesRegex(ValueError, 'passing standard audit required'):
            prepare_reconciliation(self.root, [entry])

    def test_existing_receipt_with_modified_entries_is_not_accepted_as_idempotent(self):
        plan = prepare_reconciliation(self.root, [self.entries()[0]])
        applied = apply_reconciliation(self.root, plan, now=NOW)
        path = self.root / 'record-reconciliations' / (applied['receiptId'] + '.json')
        receipt = json.loads(path.read_text())
        receipt['entries'][0]['revision'] = 'forged-revision'
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'existing reconciliation receipt invalid'):
            apply_reconciliation(self.root, plan, now=NOW)

    def test_json_reference_rejects_ancestor_symlink_outside_state_root(self):
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        evidence = {
            'id': 'revision-old', 'revision': 'rev-old', 'readOnly': True,
            'at': '2026-11-14T17:51:00+09:00',
            'result': {'status': 'passed', 'passed': True,
                       'checks': [{'status': 'passed'}]},
        }
        raw = json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode()
        (outside / 'audit.json').write_bytes(raw)
        (self.root / 'deployments/20261114-readiness/escape').symlink_to(
            outside, target_is_directory=True)
        entry = {
            'recordType': 'post_publication_audit', 'jobId': 'revision-old',
            'revision': 'rev-old',
            'source': self.json_ref(self.old_audit_path, self.old_audit),
            'proofs': [{'kind': 'same_version_audit_passed',
                        'record': self.json_ref(
                            'deployments/20261114-readiness/escape/audit.json', raw),
                        'job': self.publication_ref('revision-old', self.old_job)}],
        }
        with self.assertRaisesRegex(ValueError, 'safe JSON path required'):
            prepare_reconciliation(self.root, [entry])


if __name__ == '__main__':
    unittest.main()
