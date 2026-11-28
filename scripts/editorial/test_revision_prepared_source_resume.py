"""Offline prepared-source recovery tests; no provider or merchant requests."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from ledger import canonical, fingerprint
from revisions import validated_context
import revision_prepared_source_resume as recovery


JST = recovery.timestamp().tzinfo
OLD = datetime(2026, 11, 29, 0, 38, 45, tzinfo=JST)
FRESH = datetime(2026, 11, 29, 0, 43, 5, tzinfo=JST)
NOW = datetime(2026, 11, 29, 1, 0, tzinfo=JST)
IDS = [f'burner-s-{index:03d}' for index in range(1, 11)] + [recovery.TARGET]


class LedgerFake:
    def __init__(self, job, grant):
        self.job, self.grant = job, grant
        self.db_path = None

    def get_job(self, _id):
        return copy.deepcopy(self.job)

    def validate_existing_improvement_owner_grant(self, value):
        if value != self.grant:
            raise ValueError('owner grant')
        return copy.deepcopy(value)

    def set_stage(self, _id, stage, error):
        self.job.update(stage=stage, error=copy.deepcopy(error))
        return copy.deepcopy(self.job)


class BudgetFake:
    config = copy.deepcopy(recovery.BUDGET_CAPS)

    @staticmethod
    def _period_key(_now):
        return recovery.PERIOD


class JournalFake:
    @staticmethod
    def status(**_kwargs):
        return {'records': []}


class RuntimeFake:
    def __init__(self, root, job, grant, context, target):
        self.root = Path(root)
        self.ledger = LedgerFake(job, grant)
        self.ledger.db_path = self.root / 'ledger.sqlite'
        self.model_budget = BudgetFake()
        self.stage_journal = JournalFake()
        self.clock = lambda: NOW
        self.catalog = Mock()
        self.catalog.gather.return_value = copy.deepcopy(target)
        self.catalog.gather_revision = Mock(side_effect=AssertionError('full gather forbidden'))
        self.catalog._public.side_effect = lambda value: copy.deepcopy(value)
        self.models = Mock()
        self.models._safe_public = Mock(return_value='{}')
        self.env = {}
        self._live = copy.deepcopy(context)
        self.saved = 0
        self.delivery_source = None
        self._database()

    def _database(self):
        with sqlite3.connect(self.ledger.db_path) as db:
            db.execute('CREATE TABLE requests (request_id TEXT,job_id TEXT,kind TEXT,data TEXT)')
            db.execute('CREATE TABLE effects (job_id TEXT,kind TEXT,status TEXT,data TEXT)')
            db.execute('''CREATE TABLE model_budget_reservations (
                reservation_id TEXT,response_id TEXT,source_hash TEXT,article_id TEXT,
                stage TEXT,period_key TEXT,model TEXT,status TEXT,reserved_input_tokens INTEGER,
                reserved_output_tokens INTEGER,actual_input_tokens INTEGER,
                actual_output_tokens INTEGER,outcome TEXT,created_at TEXT,settled_at TEXT)''')
            for index, stage in enumerate(('draft', 'final_review', 'polish')):
                db.execute('INSERT INTO model_budget_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                    'import-' + stage, 'response-' + stage, 'source-' + stage,
                    'article:fixture', stage, recovery.PERIOD, 'fixture', 'imported',
                    0, 0, 100 + index, 10 + index, 'success',
                    '2026-11-20T00:00:00+09:00', '2026-11-20T00:00:00+09:00'))

    @staticmethod
    def _require_running():
        return None

    @staticmethod
    def _model_routes():
        return {'draft': {'requested': 'fixture'}, 'polish': {'requested': 'fixture'},
                'final_review': {'requested': 'fixture'}}

    @staticmethod
    def _wise_context(value):
        return copy.deepcopy(value)

    @staticmethod
    def _budget_article_id(_id):
        return 'article:fixture'

    def _context(self):
        return copy.deepcopy(self._live)

    def _save_usage(self):
        self.saved += 1

    def _make_article(self, job, context, *, prepared_revision_source=None):
        self.delivery_source = recovery.consume_prepared_source(
            prepared_revision_source, self, job, context, job['revisionContext'])
        return {'status': 'awaiting_astra_review'}


class PreparedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        products = []
        for index, product_id in enumerate(IDS):
            products.append({
                'id': product_id, 'name': 'SOTO アミカス SOD-320' if product_id == recovery.TARGET else f'Burner {index}',
                'brand': 'SOTO', 'categoryId': 'burner',
                'specs': {'model': 'SOD-320' if product_id == recovery.TARGET else f'M-{index}'},
                'imageUrl': f'https://maker.example/{product_id}.jpg',
                'affiliateUrl': f'https://item.rakuten.co.jp/shop/{index}/',
                'amazonUrl': f'https://www.amazon.co.jp/dp/B000000{index:02d}/?tag=camp78-22',
                'price': 1, 'description': '', 'rating': 0, 'availability': None,
                'updatedAt': '2026-11-28T23:00:00+09:00'})
        base = {
            'id': 'article-005', 'slug': 'single-burner-ranking', 'status': 'published',
            'title': 'Single burners', 'content': 'published body', 'categoryId': 'burner',
            'productIds': list(IDS), 'createdAt': '2026-01-01T00:00:00+09:00',
            'updatedAt': '2026-11-01T00:00:00+09:00',
            'publishedAt': '2026-01-02T00:00:00+09:00'}
        raw = {'baseArticle': base, 'changeSummary': 'verified route correction',
               'editorialCorrectionInstructions': 'keep all products and verified facts',
               'verifiedAuthorFacts': [], 'targetProductIds': list(IDS),
               'productRemovalReasons': {}, 'baseProducts': copy.deepcopy(products),
               'candidateProducts': copy.deepcopy(products)}
        self.binding = validated_context(raw)
        self.grant = {'ownerId': 'U', 'taskRef': 'owner-task:fixture',
                      'instructionSha256': 'a' * 64,
                      'instructionReceiptSha256': 'b' * 64}
        self.job = {'id': recovery.JOB, 'kind': 'article_revision', 'stage': 'error',
                    'week': recovery.PERIOD, 'theme': {'slug': base['slug'],
                    'title': base['title'], 'categoryId': 'burner', 'productIds': list(IDS)},
                    'revisionContext': self.binding, 'budgetArticleId': 'article:fixture',
                    'error': {'reason': recovery.SOURCE_REASON,
                              'catalogAmendmentRecovery': 'catalog_amendment_blocked'},
                    'bundle': None, 'revision': None, 'review': None, 'astraReview': None,
                    'approval': None, 'publication': None, 'social': None}
        self.failed = self._source(OLD, passed=False)
        self.target = self._target(FRESH)
        context = {'revisionArticles': [base], 'articles': [base],
                   'products': copy.deepcopy(products), 'wisePolicy': {'id': 'wise'},
                   'editorialRules': 'rules', 'categories': [], 'clicks': []}
        self.runtime = RuntimeFake(self.temp.name, self.job, self.grant, context, self.target)
        self._write(self.runtime.root / 'research' / (recovery.JOB + '.json'), self.failed)
        attempt = {'kind': 'revision_catalog_amendment_v1', 'jobId': recovery.JOB,
                   'newSpecHash': fingerprint(self.binding),
                   'ownerGrantSha256': fingerprint(self.grant)}
        attempt_path = self.runtime.root / 'revision-catalog-amendment-attempts' / (recovery.JOB + '.json')
        self._write(attempt_path, attempt)
        result = {'kind': 'revision_catalog_amendment_result_v1', 'status': 'blocked',
                  'jobId': recovery.JOB, 'reason': recovery.SOURCE_REASON,
                  'attemptReceiptSha256': hashlib.sha256(attempt_path.read_bytes()).hexdigest()}
        self._write(self.runtime.root / 'revision-catalog-amendment-results' /
                    (recovery.JOB + '.json'), result)
        aliases = self._aliases()
        self.constants = patch.multiple(recovery, SPEC=fingerprint(self.binding),
            FAILED_SOURCE_SHA256=hashlib.sha256(
                (canonical(self.failed) + '\n').encode()).hexdigest(),
            OWNER_GRANT=fingerprint(self.grant), OWNER_RECEIPT='b' * 64, ALIASES=aliases)
        self.constants.start()
        self.addCleanup(self.constants.stop)

    @staticmethod
    def _write(path, value):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(canonical(value) + '\n')
        path.chmod(0o600)

    def _aliases(self):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            cursor = db.execute('SELECT * FROM model_budget_reservations ORDER BY reservation_id')
            names = [item[0] for item in cursor.description]
            return [{'reservationId': row['reservation_id'], 'dataHash': fingerprint(row)}
                    for row in (dict(zip(names, values)) for values in cursor.fetchall())]

    def _source(self, checked, passed):
        products = copy.deepcopy(self.binding['candidateProducts'])
        details, refs, images = [], [], []
        for product in products:
            target = product['id'] == recovery.TARGET
            image_ok = passed or not target
            details.append({'productId': product['id'], 'model': product['specs']['model'],
                'facts': True, 'images': image_ok, 'affiliate': True,
                'claims': [{'field': 'model', 'verified': True, 'checkedAt': checked.isoformat()}],
                'destinations': [
                    {'channel': 'rakuten', 'url': product['affiliateUrl'],
                     'verified': True, 'checkedAt': checked.isoformat()},
                    {'channel': 'amazon', 'url': product['amazonUrl'],
                     'verified': True, 'checkedAt': checked.isoformat()}],
                'issues': [] if image_ok else ['manufacturer page unavailable'],
                'checkedAt': checked.isoformat()})
            refs.append({'productId': product['id'], 'kind': 'manufacturer',
                         'url': 'https://maker.example/' + product['id'],
                         'checkedAt': checked.isoformat(), 'text': product['specs']['model']})
            if image_ok:
                images.append({'productId': product['id'], 'url': product['imageUrl'],
                               'checkedAt': checked.isoformat(), 'verified': True,
                               'sha256': str(len(images) + 1).zfill(64), 'size': 54719,
                               'contentType': 'image/jpeg'})
        return {'theme': copy.deepcopy(self.job['theme']), 'productIds': list(IDS),
                'products': products, 'catalog': copy.deepcopy(products),
                'checks': {'facts': True, 'images': passed, 'affiliate': True},
                'evidence': {'products': details}, 'references': refs, 'images': images,
                'existingArticles': [], 'categories': [], 'merchantClicks': [],
                'blocked': not passed}

    def _target(self, checked):
        full = self._source(checked, passed=True)
        index = IDS.index(recovery.TARGET)
        for key in ('products', 'catalog'):
            full[key] = [full[key][index]]
        full['productIds'] = [recovery.TARGET]
        full['theme']['productIds'] = [recovery.TARGET]
        full['evidence']['products'] = [full['evidence']['products'][index]]
        full['references'] = [row for row in full['references'] if row['productId'] == recovery.TARGET]
        full['images'] = [row for row in full['images'] if row['productId'] == recovery.TARGET]
        return full

    def _collect(self):
        return recovery.collect_target(self.runtime, self.grant, now=NOW)

    def test_collects_only_target_and_preserves_original_ttl(self):
        result = self._collect()
        self.assertEqual(('verified', recovery.TARGET),
                         (result['status'], result['targetProductId']))
        theme, context = self.runtime.catalog.gather.call_args.args
        self.assertEqual([recovery.TARGET], theme['productIds'])
        self.assertEqual(self.binding['candidateProducts'], context['products'])
        plan = recovery.prepare(self.runtime, self.grant, now=NOW)
        self.assertEqual((OLD + timedelta(hours=6)).isoformat(),
                         plan['preparedSourceTtl'])
        self.assertEqual([pid for pid in IDS if pid != recovery.TARGET],
                         plan['reusedProductIds'])
        with self.assertRaisesRegex(ValueError, 'target_already_collected'):
            self._collect()
        self.assertEqual(1, self.runtime.catalog.gather.call_count)

    def test_execute_merges_only_target_proofs_and_uses_runtime_capability(self):
        self._collect()
        old_attempt = (self.runtime.root / 'revision-catalog-amendment-attempts' /
                       (recovery.JOB + '.json')).read_bytes()
        result = recovery.execute(self.runtime, self.grant, now=NOW)
        self.assertEqual('completed', result['status'])
        merged = self.runtime.delivery_source
        self.assertEqual(self.failed['products'], merged['products'])
        self.assertEqual(self.failed['catalog'], merged['catalog'])
        old_rows = {row['productId']: row for row in self.failed['evidence']['products']}
        new_rows = {row['productId']: row for row in merged['evidence']['products']}
        self.assertEqual({pid: old_rows[pid] for pid in IDS if pid != recovery.TARGET},
                         {pid: new_rows[pid] for pid in IDS if pid != recovery.TARGET})
        self.assertEqual(self.target['evidence']['products'][0], new_rows[recovery.TARGET])
        self.assertEqual({'facts': True, 'images': True, 'affiliate': True}, merged['checks'])
        self.assertEqual(set(recovery.GATHERED_FIELDS), set(merged))
        self.assertFalse(any(key in merged for key in
            ('ownerGrant', 'sourceArchives', 'assembledAt', 'preparedSourceTtl')))
        self.runtime.models._safe_public.assert_called_once_with(merged)
        self.runtime.catalog.gather_revision.assert_not_called()
        self.assertEqual(old_attempt, (self.runtime.root /
            'revision-catalog-amendment-attempts' / (recovery.JOB + '.json')).read_bytes())
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(self.runtime, self.grant, now=NOW)

    def test_rejects_stale_reused_future_or_nonpositive_target_before_claim(self):
        cases = ('stale', 'future', 'target_false', 'target_old_cache')
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                if case in ('stale', 'future'):
                    checked = NOW - timedelta(hours=6) if case == 'stale' else NOW + timedelta(seconds=1)
                    self.failed['evidence']['products'][0]['checkedAt'] = checked.isoformat()
                    self._write(self.runtime.root / 'research' / (recovery.JOB + '.json'), self.failed)
                elif case == 'target_false':
                    self.target['checks']['images'] = False
                    self.target['blocked'] = True
                    self.runtime.catalog.gather.return_value = self.target
                else:
                    self.target['evidence']['products'][0]['checkedAt'] = OLD.isoformat()
                    for key in ('references', 'images'):
                        for row in self.target[key]:
                            row['checkedAt'] = OLD.isoformat()
                    self.runtime.catalog.gather.return_value = self.target
                with self.assertRaises(ValueError):
                    self._collect()
                self.assertFalse((self.runtime.root / 'revision-prepared-source-targets' /
                                  (recovery.JOB + '.json')).exists())

    def test_fresh_target_requires_nonempty_timestamped_claims_and_exact_routes(self):
        cases = ('claims_empty', 'destinations_empty', 'claim_time', 'route_missing')
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                detail = self.target['evidence']['products'][0]
                if case == 'claims_empty':
                    detail['claims'] = []
                elif case == 'destinations_empty':
                    detail['destinations'] = []
                elif case == 'claim_time':
                    detail['claims'][0]['checkedAt'] = OLD.isoformat()
                else:
                    detail['destinations'].pop()
                self.runtime.catalog.gather.return_value = self.target
                with self.assertRaisesRegex(ValueError, 'target_not_strictly_verified'):
                    self._collect()

    def test_observed_failed_source_sha_rejects_semantically_valid_tamper(self):
        changed = copy.deepcopy(self.failed)
        changed['existingArticles'] = [{'id': 'unrelated'}]
        self._write(self.runtime.root / 'research' / (recovery.JOB + '.json'), changed)
        with self.assertRaisesRegex(ValueError, 'failed_source_sha'):
            self._collect()
        self.runtime.catalog.gather.assert_not_called()

    def test_arbitrary_prepared_dict_cannot_bypass_runtime_boundary(self):
        with self.assertRaisesRegex(ValueError, 'capability'):
            recovery.consume_prepared_source({}, self.runtime, self.job,
                                              self.runtime._context(), self.binding)

    def test_scope_ignores_unrelated_rows_but_binds_editorial_inputs(self):
        self._collect()
        self.runtime._live['clicks'] = [{'productId': 'unrelated', 'clicks': 99}]
        self.runtime._live['articles'].append({'id': 'unrelated'})
        self.assertEqual('ready', recovery.prepare(
            self.runtime, self.grant, now=NOW)['status'])
        self.runtime._live['editorialRules'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'context_scope_drift'):
            recovery.prepare(self.runtime, self.grant, now=NOW)

    def test_ordinary_revision_still_uses_full_gather(self):
        import test_revision_workflow as workflow
        fixture = workflow.RevisionWorkflowTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        base = workflow.baseline()
        job = fixture.request(base)
        fixture.fake_evidence()
        fixture.runtime._make_article(job, fixture.context(base))
        fixture.runtime.catalog.gather_revision.assert_called_once()


if __name__ == '__main__':
    unittest.main()
