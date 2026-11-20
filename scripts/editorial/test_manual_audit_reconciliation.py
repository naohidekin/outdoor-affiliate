"""Fixed-path manual proof closes history without resetting automatic attempts."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from record_reconciliation import (prepare_reconciliation, check_reconciliation_plan,
                                   apply_reconciliation, project_reconciliations)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


class ManualAuditReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle = {'article': {'content': 'approved body'},
                       'products': [{'id': 'p1', 'affiliateUrl': 'https://example.com/raku', 'amazonUrl': 'https://example.com/amazon'}],
                       'images': [{'productId': 'p1'}]}
        self.job = {'id': 'article-fixture', 'revision': sha(canonical(self.bundle)), 'bundle': self.bundle}
        revision = self.job['revision']
        self.job['publication'] = {'revision': revision, 'verified': True, 'url': '/fixture',
            'at': '2026-11-20T10:08:00+09:00', 'readback': {'verified': True, 'fingerprint': revision}}
        self.save_job()
        bound = {key: self.job[key] for key in ('id', 'revision', 'publication')}
        self.audit_key = sha(canonical(bound))
        self.source_path = 'post-publication-audits/' + self.audit_key + '.json'
        self.source = dict(bound, auditKey=self.audit_key, status='failed',
            completedAt='2026-11-20T11:22:00+09:00', nextAttemptAt=None,
            attempts=[{'status': 'failed'}] * 3,
            result={'status': 'failed', 'passed': False, 'checks': [
                {'name': 'approved_body', 'status': 'passed'},
                {'name': 'destination.0.rakuten', 'status': 'failed'}]})
        self.source_raw = self.put(self.source_path, self.source)
        self.manual_path = 'operator-reconciliations/' + self.job['id'] + '-' + revision + '-audit.json'
        names = ['public_title', 'approved_body', 'image.0', 'product_image_binding.0',
                 'desktop', 'mobile', 'desktop.binding', 'mobile.binding',
                 'desktop.prose', 'mobile.prose', 'desktop.product_image.0', 'mobile.product_image.0',
                 'desktop.click.0.rakuten', 'desktop.click.0.amazon',
                 'mobile.click.0.rakuten', 'mobile.click.0.amazon',
                 'destination.0.rakuten', 'destination.0.amazon']
        self.manual = dict(bound, readOnly=True, auditKey=self.audit_key,
            sourceAuditSHA256=sha(self.source_raw), at='2026-11-20T11:30:00+09:00',
            result={'status': 'passed', 'passed': True, 'issues': [],
                    'checks': [{'name': name, 'status': 'passed'} for name in names]})

    def tearDown(self):
        self.tmp.cleanup()

    def save_job(self):
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT)')
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (self.job['id'], canonical(self.job).decode()))

    def put(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical(value)
        path.write_bytes(raw)
        return raw

    def entry(self, value=None, path=None):
        path = path or self.manual_path
        raw = self.put(path, self.manual if value is None else value)
        bound = {key: self.job[key] for key in ('id', 'revision', 'publication')}
        return {'recordType': 'post_publication_audit', 'jobId': self.job['id'], 'revision': self.job['revision'],
                'source': {'kind': 'json', 'path': self.source_path, 'sha256': sha(self.source_raw)},
                'proofs': [{'kind': 'same_version_audit_passed',
                    'record': {'kind': 'json', 'path': path, 'sha256': sha(raw)},
                    'job': {'kind': 'sqlite_publication', 'path': 'ledger.sqlite3',
                            'id': self.job['id'], 'sha256': sha(canonical(bound))}}]}

    def test_additive_prepare_check_apply_keeps_original_three_attempts_and_database(self):
        entry = self.entry()
        db_before = (self.root / 'ledger.sqlite3').read_bytes()
        plan = prepare_reconciliation(self.root, [entry])
        self.assertEqual('checked', check_reconciliation_plan(self.root, plan)['status'])
        result = apply_reconciliation(self.root, plan, now=datetime(2026, 11, 20, 11, 31, tzinfo=timezone(timedelta(hours=9))))
        self.assertEqual('applied', result['status'])
        self.assertEqual(self.source_raw, (self.root / self.source_path).read_bytes())
        self.assertEqual(db_before, (self.root / 'ledger.sqlite3').read_bytes())
        self.assertEqual(3, len(json.loads((self.root / self.source_path).read_text())['attempts']))
        projected = project_reconciliations(self.root)
        self.assertEqual(1, projected['historicalReconciledCounts']['postPublicationAudits'])

    def test_wrong_binding_failed_checks_and_unbound_source_hash_are_rejected(self):
        changes = [('id', 'another'), ('revision', 'another'), ('publication', {}),
                   ('auditKey', 'a' * 64), ('sourceAuditSHA256', 'b' * 64), ('readOnly', False),
                   ('at', '2026-11-20T10:00:00+09:00')]
        for key, value in changes:
            bad = copy.deepcopy(self.manual)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare_reconciliation(self.root, [self.entry(bad)])
        for key, value in (('passed', False), ('status', 'failed'), ('issues', ['unresolved'])):
            bad = copy.deepcopy(self.manual)
            bad['result'][key] = value
            with self.assertRaises(ValueError):
                prepare_reconciliation(self.root, [self.entry(bad)])

    def test_arbitrary_paths_selectors_partial_checks_and_duplicate_names_are_rejected(self):
        for path in ('reports/looks-passed.json', 'operator-reconciliations/other-audit.json',
                     'operator-reconciliations/nested/' + Path(self.manual_path).name):
            with self.subTest(path=path), self.assertRaises(ValueError):
                prepare_reconciliation(self.root, [self.entry(path=path)])
        for missing in [check['name'] for check in self.manual['result']['checks']]:
            bad = copy.deepcopy(self.manual)
            bad['result']['checks'] = [c for c in bad['result']['checks'] if c['name'] != missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                prepare_reconciliation(self.root, [self.entry(bad)])
        bad = copy.deepcopy(self.manual)
        bad['result']['checks'].append(copy.deepcopy(bad['result']['checks'][0]))
        with self.assertRaises(ValueError):
            prepare_reconciliation(self.root, [self.entry(bad)])

    def test_social_card_requires_manifest_and_metadata_checks(self):
        self.job['bundle']['article']['generationMeta'] = {'socialCard': {'url': 'https://example.com/card.png'}}
        self.save_job()
        with self.assertRaises(ValueError):
            prepare_reconciliation(self.root, [self.entry()])
        good = copy.deepcopy(self.manual)
        good['result']['checks'].extend([{'name': name, 'status': 'passed'} for name in ('social_manifest', 'social_metadata')])
        self.assertEqual('planned', prepare_reconciliation(self.root, [self.entry(good)])['status'])

    def test_original_noncore_failed_or_unverified_check_cannot_be_omitted(self):
        for status in ('failed', 'unverified'):
            source = copy.deepcopy(self.source)
            source['result']['checks'].append({'name': 'desktop.heading.0', 'status': status})
            self.source_raw = self.put(self.source_path, source)
            proof = copy.deepcopy(self.manual)
            proof['sourceAuditSHA256'] = sha(self.source_raw)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'core checks required'):
                prepare_reconciliation(self.root, [self.entry(proof)])
            proof['result']['checks'].append({'name': 'desktop.heading.0', 'status': 'passed'})
            self.assertEqual('planned', prepare_reconciliation(self.root, [self.entry(proof)])['status'])

    def test_changed_proof_source_or_publication_after_prepare_invalidates_plan(self):
        plan = prepare_reconciliation(self.root, [self.entry()])
        self.manual['result']['checks'][0]['status'] = 'failed'
        self.put(self.manual_path, self.manual)
        with self.assertRaises(ValueError):
            check_reconciliation_plan(self.root, plan)
        self.manual['result']['checks'][0]['status'] = 'passed'
        plan = prepare_reconciliation(self.root, [self.entry()])
        changed = copy.deepcopy(self.source)
        changed['attempts'].append({'status': 'failed'})
        self.put(self.source_path, changed)
        with self.assertRaises(ValueError):
            check_reconciliation_plan(self.root, plan)
        self.put(self.source_path, self.source)
        plan = prepare_reconciliation(self.root, [self.entry()])
        self.job['publication']['url'] = '/changed-publication'
        self.save_job()
        with self.assertRaises(ValueError):
            check_reconciliation_plan(self.root, plan)


if __name__ == '__main__':
    unittest.main()
