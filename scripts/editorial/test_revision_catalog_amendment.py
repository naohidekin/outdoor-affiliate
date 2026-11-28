"""Offline tests for the exact pre-model burner purchase-route amendment."""
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock, patch

from ledger import canonical, fingerprint
from runtime import JST
import revision_catalog_amendment as amendment
from stage_journal import StageUnknown
import test_runtime
from test_inherited_advice import context as inherited_context
from test_revision_workflow import baseline, spec


NOW = datetime(2026, 11, 28, 23, 20, tzinfo=JST)
IDS = [
    'burner-s-002', 'burner-s-004', 'burner-s-001', 'burner-s-008',
    'burner-s-003', 'burner-s-009', 'rakuten-brave-6-4953571093208',
    'burner-s-007', 'burner-s-006', 'burner-s-005',
    'rakuten-brave-6-p11021',
]


class RevisionCatalogAmendmentTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        original_renderer = self.runtime.renderer

        def renderer(bundle, job):
            value = original_renderer(bundle, job)
            value['inheritedPresentationContext'] = inherited_context(
                bundle['article']['slug'])
            return value

        self.runtime.renderer = renderer
        self.period = '2026-11-27'
        self.runtime.model_budget._period_key = Mock(return_value=self.period)
        base = baseline('article-005', 'single-burner-ranking')
        base['productIds'] = list(IDS)
        raw = spec(base)
        raw['changeSummary'] = 'burner-s-008の検証済み楽天購入先を訂正する。'
        raw['editorialCorrectionInstructions'] = (
            '公開済み記事を保持し、burner-s-008の楽天購入先だけを訂正する。')
        products = raw['baseProducts']
        for index, product in enumerate(products):
            product.update(
                categoryId='burner',
                affiliateUrl=('https://hb.afl.rakuten.co.jp/ichiba/owner/'
                              f'?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fshop%2F{index}%2F'),
                amazonUrl=f'https://www.amazon.co.jp/dp/B0000000{index:02d}/?tag=camp78-22',
                updatedAt='2026-11-28T20:00:00+09:00')
        by_id = {product['id']: product for product in products}
        by_id['burner-s-001']['amazonUrl'] = ''
        by_id['burner-s-006']['affiliateUrl'] = ''
        candidates = copy.deepcopy(products)
        s008 = next(product for product in candidates if product['id'] == 'burner-s-008')
        s008.update(affiliateUrl='https://hb.afl.rakuten.co.jp/ichiba/owner/'
                    '?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fnaturum%2F3036876%2F',
                    updatedAt='2026-11-28T22:18:32.046122+09:00')
        raw['candidateProducts'] = candidates
        self.job = self.runtime.ledger.request_revision(raw, now=NOW)
        self.old_context = copy.deepcopy(self.job['revisionContext'])
        self.alias = self.runtime._budget_article_id(self.job['id'])
        self.imported = self._add_imported_aliases()

        source = self._source_v2()
        self.source_path = self.runtime.root / 'research' / (self.job['id'] + '.json')
        self.source_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.source_path.write_text(canonical(source) + '\n')
        self.source_path.chmod(0o600)
        self.source_bytes = self.source_path.read_bytes()

        marker = {'status': 'blocked',
                  'reason': 'source_product_image_or_affiliate_verification_incomplete'}
        self.marker_path = (self.runtime.root / 'revision-production-attempts' /
                            (self.job['id'] + '.json'))
        self._secure_write(self.marker_path, marker)

        attempt = {
            'schemaVersion': 1, 'kind': 'revision_source_hold_recovery',
            'action': 'retry_full_fresh_revision_source_once', 'status': 'claimed',
            'jobId': self.job['id'], 'productionPeriod': self.period,
            'specHash': fingerprint(self.old_context), 'budgetArticleId': self.alias,
            'existingImportedBudgetReceipts': self.imported,
        }
        self.prior_attempt_path = (self.runtime.root /
            'revision-source-hold-recovery-attempts' / (self.job['id'] + '.json'))
        self._secure_write(self.prior_attempt_path, attempt)
        prior_attempt_sha = hashlib.sha256(self.prior_attempt_path.read_bytes()).hexdigest()
        result = {
            'schemaVersion': 1, 'kind': 'revision_source_hold_recovery_result',
            'action': attempt['action'], 'status': 'blocked', 'jobId': self.job['id'],
            'attemptReceiptSha256': prior_attempt_sha,
            'reason': 'purchase evidence required',
        }
        self.prior_result_path = (self.runtime.root /
            'revision-source-hold-recovery-results' / (self.job['id'] + '.json'))
        self._secure_write(self.prior_result_path, result)
        self.runtime.ledger.set_stage(self.job['id'], 'error', {
            'reason': 'purchase evidence required',
            'originalFailure': {'reason':
                'source_product_image_or_affiliate_verification_incomplete'},
            'sourceHoldRecovery': 'blocked',
        })
        self.job = self.runtime.ledger.get_job(self.job['id'])
        self.grant = self._owner_grant()
        auth = {
            'oldJobHash': fingerprint(self.job),
            'oldSpecHash': fingerprint(self.old_context),
            'researchSha256': hashlib.sha256(self.source_bytes).hexdigest(),
            'sourceRecoveryAttemptSha256': prior_attempt_sha,
            'sourceRecoveryResultSha256': hashlib.sha256(
                self.prior_result_path.read_bytes()).hexdigest(),
            'productionMarkerSha256': hashlib.sha256(
                self.marker_path.read_bytes()).hexdigest(),
            'budgetArticleId': self.alias, 'productionPeriod': self.period,
            'existingImportedBudgetReceipts': copy.deepcopy(self.imported),
            'ownerGrantFingerprint': fingerprint(self.grant),
            'ownerGrantReceiptSha256': self.grant['instructionReceiptSha256'],
        }
        self.authorization = patch.dict(amendment.AUTHORIZED,
                                        {self.job['id']: auth}, clear=True)
        self.authorization.start()
        self.addCleanup(self.authorization.stop)
        context = self.runtime._context()
        context.update(articles=[base], revisionArticles=[base],
                       products=copy.deepcopy(self.old_context['baseProducts']))
        self.runtime._context = Mock(return_value=context)
        self.runtime.catalog.gather_revision = Mock()

    tearDown = test_runtime.RuntimeTests.tearDown

    def _secure_write(self, path, value):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(canonical(value) + '\n')
        path.chmod(0o600)

    def _owner_grant(self, instruction='fixture owner instruction'):
        receipt = {
            'schemaVersion': 1, 'ownerId': self.runtime.ledger.owner_id,
            'source': 'codex_task_message', 'instruction': instruction,
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
        path.write_bytes(raw)
        path.chmod(0o600)
        return {'ownerId': self.runtime.ledger.owner_id,
                'taskRef': 'owner-task:' + task_hash,
                'instructionSha256': receipt['instructionSha256'],
                'instructionReceiptSha256': hashlib.sha256(raw).hexdigest()}

    def _add_imported_aliases(self):
        rows = []
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            for index, stage in enumerate(('draft', 'polish', 'final_review'), 1):
                values = (
                    'import-' + stage, 'response-' + stage, 'source-' + stage,
                    self.alias, stage, self.period, 'fixture-model', 'imported',
                    0, 0, index * 100, index * 10, 'success',
                    '2026-11-20T00:00:00+09:00',
                    '2026-11-20T00:00:00+09:00')
                db.execute('''INSERT INTO model_budget_reservations
                    (reservation_id,response_id,source_hash,article_id,stage,period_key,
                     model,status,reserved_input_tokens,reserved_output_tokens,
                     actual_input_tokens,actual_output_tokens,outcome,created_at,settled_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', values)
            cursor = db.execute(
                'SELECT * FROM model_budget_reservations WHERE article_id=? ORDER BY reservation_id',
                (self.alias,))
            columns = [item[0] for item in cursor.description]
            for values in cursor.fetchall():
                row = dict(zip(columns, values))
                rows.append({'reservationId': row['reservation_id'],
                             'dataHash': fingerprint(row)})
        return rows

    def _source_v2(self):
        products = copy.deepcopy(self.old_context['candidateProducts'])
        details = []
        for product in products:
            destinations = []
            for channel, field in (('rakuten', 'affiliateUrl'),
                                   ('amazon', 'amazonUrl')):
                if product.get(field):
                    destinations.append({'channel': channel, 'url': product[field],
                                         'verified': True, 'checkedAt': NOW.isoformat()})
            details.append({'productId': product['id'], 'facts': True,
                            'images': True, 'affiliate': True,
                            'checkedAt': NOW.isoformat(), 'destinations': destinations,
                            'issues': []})
        return {'productIds': list(IDS), 'products': products,
                'catalog': copy.deepcopy(products),
                'checks': {'facts': True, 'images': True, 'affiliate': True},
                'evidence': {'products': details}, 'blocked': False,
                'images': [], 'references': []}

    def _prepare(self):
        return self.runtime.prepare_revision_catalog_amendment(
            self.job['id'], self.grant, expected_current_period=self.period,
            now=NOW)

    def _execute(self):
        return self.runtime.resume_revision_after_catalog_amendment(
            self.job['id'], self.grant, expected_current_period=self.period,
            now=NOW)

    def test_prepare_is_read_only_and_builds_exact_three_patch_context(self):
        before_job = self.runtime.ledger.get_job(self.job['id'])
        before_events = self._event_count()

        plan = self._prepare()

        self.assertEqual('ready', plan['status'])
        self.assertEqual(['burner-s-001', 'burner-s-008', 'burner-s-006'],
                         plan['productPatchIds'])
        self.assertEqual(self.alias, plan['budgetArticleId'])
        self.assertEqual(before_job, self.runtime.ledger.get_job(self.job['id']))
        self.assertEqual(before_events, self._event_count())
        self.runtime.catalog.gather_revision.assert_not_called()
        self.assertFalse((self.runtime.root / 'revision-catalog-amendment-attempts' /
                          (self.job['id'] + '.json')).exists())

    def test_execute_archives_source_amends_once_and_calls_normal_pipeline(self):
        self.runtime._make_article = Mock(return_value={'status': 'awaiting_astra_review'})
        old_attempt = self.prior_attempt_path.read_bytes()
        old_result = self.prior_result_path.read_bytes()
        old_marker = self.marker_path.read_bytes()

        result = self._execute()

        self.assertEqual('completed', result['status'])
        self.runtime._make_article.assert_called_once()
        amended = self.runtime._make_article.call_args.args[0]
        self.assertEqual(self.job['id'], amended['id'])
        self.assertEqual(self.job['week'], amended['week'])
        self.assertEqual(self.job.get('budgetArticleId'), amended.get('budgetArticleId'))
        self.assertEqual(self.job['error'], amended['error'])
        self.assertEqual(self.old_context['baseProducts'],
                         amended['revisionContext']['baseProducts'])
        patches = {item['id']: item for item in amended['revisionContext']['productPatches']}
        self.assertEqual({'burner-s-001', 'burner-s-008', 'burner-s-006'}, set(patches))
        self.assertEqual(self.old_context['productPatches'][0], patches['burner-s-008'])
        self.assertEqual(amendment.S001_AMAZON,
                         patches['burner-s-001']['fields']['amazonUrl'])
        self.assertEqual(amendment.S006_RAKUTEN,
                         patches['burner-s-006']['fields']['affiliateUrl'])
        self.assertIsNone(amended['approval'])
        self.assertIsNone(amended['publication'])
        self.assertIsNone(amended['social'])
        self.assertEqual(old_attempt, self.prior_attempt_path.read_bytes())
        self.assertEqual(old_result, self.prior_result_path.read_bytes())
        self.assertEqual(old_marker, self.marker_path.read_bytes())
        attempt = json.loads((self.runtime.root /
            'revision-catalog-amendment-attempts' / (self.job['id'] + '.json')).read_text())
        archive = self.runtime.root / attempt['sourceArchive']
        self.assertEqual(self.source_bytes, archive.read_bytes())
        self.assertEqual(0o600, archive.stat().st_mode & 0o777)
        old_job_archive = self.runtime.root / attempt['oldJobArchive']
        old_context_archive = self.runtime.root / attempt['oldContextArchive']
        self.assertEqual(canonical(self.job).encode(), old_job_archive.read_bytes())
        self.assertEqual(canonical(self.job['revisionContext']).encode(),
                         old_context_archive.read_bytes())
        self.assertEqual(hashlib.sha256(old_job_archive.read_bytes()).hexdigest(),
                         attempt['oldJobArchiveSha256'])
        self.assertEqual(hashlib.sha256(old_context_archive.read_bytes()).hexdigest(),
                         attempt['oldContextArchiveSha256'])
        self.assertEqual(3, self._alias_row_count())
        with self.assertRaises(ValueError):
            self._execute()

    def test_prewrite_failure_is_blocked_without_model_usage_or_retry(self):
        self.runtime._make_article = Mock(side_effect=ValueError(
            'source_product_image_or_affiliate_verification_incomplete'))

        result = self._execute()

        self.assertEqual(('attention', 'blocked'),
                         (result['status'], result['outcome']))
        self.assertEqual(0, self._current_job_budget_rows())
        saved = self.runtime.ledger.get_job(self.job['id'])
        self.assertEqual('error', saved['stage'])
        self.assertEqual('catalog_amendment_blocked',
                         saved['error']['catalogAmendmentRecovery'])
        with self.assertRaises(ValueError):
            self._execute()

    def test_unknown_or_unverified_delivery_requires_reconciliation(self):
        failures = (
            Mock(side_effect=StageUnknown('unknown model result')),
            Mock(return_value={'status': 'unverified'}),
        )
        for operation in failures:
            with self.subTest(result=repr(operation.side_effect or operation.return_value)):
                self.tearDown()
                self.setUp()
                self.runtime._make_article = operation

                result = self._execute()

                self.assertEqual(('attention', 'requires_reconciliation'),
                                 (result['status'], result['outcome']))
                saved = self.runtime.ledger.get_job(self.job['id'])
                self.assertEqual('catalog_amendment_requires_reconciliation',
                                 saved['error']['catalogAmendmentRecovery'])

    def test_ledger_rejects_change_outside_catalog_amendment_fields(self):
        eligible = amendment._eligibility(
            self.runtime, self.job['id'], self.grant, self.period, NOW)
        amended, claim = copy.deepcopy(eligible[2]), copy.deepcopy(eligible[3])
        amended['verifiedAuthorFacts'] = ['not authorized']
        amended = amendment.validated_context(amendment._raw_context(amended))
        claim['newSpecHash'] = fingerprint(amended)

        with self.assertRaisesRegex(ValueError, 'protected context'):
            self.runtime.ledger.amend_unstarted_revision_catalog(
                self.job['id'], claim['oldJobHash'], claim['oldSpecHash'],
                amendment._raw_context(amended), claim)

    def test_stale_job_source_receipt_alias_or_side_effect_rejects_before_claim(self):
        cases = ('job', 'source', 'receipt', 'alias', 'request', 'effect',
                 'usage', 'stage', 'caps')
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                if case == 'job':
                    self.runtime.ledger.set_stage(self.job['id'], 'error',
                                                  {'reason': 'changed'})
                elif case == 'source':
                    self.source_path.write_bytes(self.source_bytes + b' ')
                elif case == 'receipt':
                    self.prior_result_path.write_bytes(
                        self.prior_result_path.read_bytes() + b' ')
                elif case == 'alias':
                    with sqlite3.connect(self.runtime.ledger.db_path) as db:
                        db.execute("UPDATE model_budget_reservations SET outcome='changed' "
                                   'WHERE reservation_id=?', ('import-draft',))
                elif case == 'request':
                    with sqlite3.connect(self.runtime.ledger.db_path) as db:
                        db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                                   ('r', self.job['id'], 'article', '{}'))
                elif case == 'effect':
                    with sqlite3.connect(self.runtime.ledger.db_path) as db:
                        db.execute('INSERT INTO effects VALUES (?,?,?,?)',
                                   (self.job['id'], 'publication', 'failed', '{}'))
                elif case == 'usage':
                    with sqlite3.connect(self.runtime.ledger.db_path) as db:
                        db.execute('''INSERT INTO model_budget_reservations
                            (reservation_id,article_id,stage,period_key,model,status,
                             reserved_input_tokens,reserved_output_tokens,created_at)
                            VALUES (?,?,?,?,?,?,?,?,?)''',
                            ('current', self.job['id'], 'draft', self.period,
                             'fixture', 'settled', 0, 0, NOW.isoformat()))
                elif case == 'stage':
                    with sqlite3.connect(self.runtime.ledger.db_path) as db:
                        db.execute('INSERT INTO meta VALUES (?,?)', (
                            'stage_journal:v1:fixture', canonical({
                                'jobId': self.job['id'], 'stage': 'draft',
                                'status': 'failed'})))
                else:
                    self.runtime.model_budget.config['article']['calls'] = 31
                with self.assertRaises(ValueError):
                    self._prepare()
                self.runtime.catalog.gather_revision.assert_not_called()
                self.assertFalse((self.runtime.root /
                    'revision-catalog-amendment-attempts' /
                    (self.job['id'] + '.json')).exists())

    def test_other_valid_owner_grant_rejects_before_claim(self):
        other = self._owner_grant('different valid owner instruction')
        with self.assertRaisesRegex(ValueError, 'owner_grant'):
            self.runtime.prepare_revision_catalog_amendment(
                self.job['id'], other, expected_current_period=self.period,
                now=NOW)
        self.runtime.catalog.gather_revision.assert_not_called()

    def _event_count(self):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            return db.execute('SELECT count(*) FROM events').fetchone()[0]

    def _alias_row_count(self):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            return db.execute('SELECT count(*) FROM model_budget_reservations '
                              'WHERE article_id=?', (self.alias,)).fetchone()[0]

    def _current_job_budget_rows(self):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            return db.execute('SELECT count(*) FROM model_budget_reservations '
                              'WHERE article_id=?', (self.job['id'],)).fetchone()[0]


if __name__ == '__main__':
    unittest.main()
