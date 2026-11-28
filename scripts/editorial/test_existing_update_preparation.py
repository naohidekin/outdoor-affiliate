"""Offline routine existing-improvement preparation contracts."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from existing_update_preparation import prepare_existing_update, public_revision_reference
from ledger import Ledger, canonical, fingerprint
from model_budget import ModelBudget
from revisions import validated_context

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 28, 9, tzinfo=JST)


def article(status='published'):
    return {'id': 'article-024', 'slug': 'firepit-beginner-guide',
            'title': '焚き火台の選び方', 'categoryId': 'firepit',
            'content': '公開済みの本文です。', 'excerpt': '既存記事',
            'productIds': ['product-1'], 'status': status,
            'createdAt': '2026-01-01T00:00:00+09:00',
            'updatedAt': '2026-11-20T00:00:00+09:00',
            'publishedAt': '2026-01-02T00:00:00+09:00'}


def product():
    return {'id': 'product-1', 'name': 'Verified firepit',
            'categoryId': 'firepit', 'updatedAt': '2026-11-20T00:00:00+09:00'}


def opportunity(url='https://camp-gear-lab.com/articles/firepit-beginner-guide'):
    return {'action': 'improve_existing', 'url': url,
            'reason': '表示実績と平均掲載順位を根拠に既存記事の見出し・内容を確認',
            'gsc': {'clicks': 4.0, 'impressions': 100.0, 'ctr': .04,
                    'position': 8.0, 'metricScope': 'page'},
            'ga4': {'path': '/articles/firepit-beginner-guide', 'sessions': 20.0,
                    'engagedSessions': 15.0, 'keyEvents': 1.0,
                    'sourcePeriod': {'startDate': '2026-10-20',
                                     'endDate': '2026-11-16',
                                     'dateBasis': 'Asia/Tokyo'}},
            'cannibalizationCheck': 'required', 'publication': 'manual_review'}


def analytics(target=None):
    target = target or opportunity()
    pages = [
        {'url': 'https://camp-gear-lab.com/articles/winner-one', 'clicks': 30.0,
         'impressions': 80.0, 'ctr': .3, 'position': 1.0},
        {'url': 'https://camp-gear-lab.com/articles/winner-two', 'clicks': 20.0,
         'impressions': 80.0, 'ctr': .2, 'position': 2.0},
        {'url': 'https://camp-gear-lab.com/articles/winner-three', 'clicks': 10.0,
         'impressions': 80.0, 'ctr': .1, 'position': 4.0},
        {'url': target['url'], 'clicks': target['gsc']['clicks'],
         'impressions': target['gsc']['impressions'], 'ctr': target['gsc']['ctr'],
         'position': target['gsc']['position']},
    ]
    dates = {'startDate': '2026-10-20', 'endDate': '2026-11-16'}
    return {'schemaVersion': 1, 'status': 'ok', 'collectedAt': NOW.isoformat(),
            'evidence': {
                'current': {**dates, 'dateBasis': 'America/Los_Angeles',
                            'status': 'ok', 'siteUrl': 'https://camp-gear-lab.com/',
                            'pages': pages, 'candidates': []},
                'previous': None,
                'ga4': {**dates, 'dateBasis': 'Asia/Tokyo',
                        'status': 'ok', 'landingPages': [],
                        'coverageVerified': True}},
            'opportunities': [target], 'uncertainty': [],
            'provenance': {'source': 'Google collector snapshot',
                           'operationTimezone': 'Asia/Tokyo'}}


class CatalogFake:
    def __init__(self, now=NOW, failure=None):
        self.now, self.failure = now, failure
        self.gather_revision = Mock(side_effect=self._gather)

    def _gather(self, theme, live, binding):
        if self.failure:
            raise self.failure
        pid = theme['productIds'][0]
        return {'blocked': False, 'productIds': [pid],
                'checks': {'facts': True, 'images': True, 'affiliate': True},
                'evidence': {'products': [{
                    'productId': pid, 'facts': True, 'images': True,
                    'affiliate': True, 'checkedAt': self.now.isoformat()}]},
                'products': copy.deepcopy(binding['candidateProducts']),
                'references': [], 'images': []}


class ExistingUpdatePreparationTests(unittest.TestCase):
    def test_public_reference_is_bounded_and_never_becomes_source_evidence(self):
        base = article()
        before = copy.deepcopy(base)
        value = public_revision_reference(base)
        self.assertFalse(value['isFactualEvidence'])
        self.assertEqual(base['content'], value['article']['content'])
        self.assertEqual(fingerprint(base), value['baseArticleHash'])
        self.assertEqual(fingerprint(value['article']), value['referenceHash'])
        self.assertEqual(before, base)
        self.assertNotIn('generationMeta', value['article'])

    def test_draft_or_oversized_public_reference_requires_upper_editor(self):
        for base in (article('draft'), dict(article(), content='本文' * 10000)):
            with self.assertRaises(ValueError):
                public_revision_reference(base)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'state'
        self.ledger = Ledger(self.root, 'owner')
        self.catalog = CatalogFake()
        self.runtime = SimpleNamespace(ledger=self.ledger, catalog=self.catalog)
        self.live = {'articles': [article()], 'products': [product()]}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, metrics=None, live=None):
        return prepare_existing_update(
            self.runtime, metrics or analytics(), live or self.live, now=NOW)

    def manual_spec(self):
        base = article()
        products = [product()]
        return {'baseArticle': base, 'changeSummary': '手動訂正',
                'editorialCorrectionInstructions': '確認済み事実だけを訂正する。',
                'verifiedAuthorFacts': [], 'targetProductIds': ['product-1'],
                'productRemovalReasons': {}, 'baseProducts': products,
                'candidateProducts': copy.deepcopy(products)}

    def test_queues_one_generic_revision_and_preserves_manual_gates(self):
        result = self.prepare()
        self.assertEqual('queued', result['status'])
        self.assertEqual('article-024', result['selectedId'])
        self.assertIsNotNone(result['revisionJobId'])
        job = self.ledger.get_job(result['revisionJobId'])
        self.assertEqual('candidate', job['stage'])
        self.assertIsNone(job['review'])
        self.assertIsNone(job.get('astraReview'))
        self.assertIsNone(job['approval'])
        self.assertIsNone(job['publication'])
        self.assertEqual(result['period'], job['week'])
        self.assertEqual(result['budgetArticleId'], job['budgetArticleId'])
        binding = job['revisionContext']['analysisBinding']
        self.assertEqual('America/Los_Angeles',
                         binding['metricsReceipt']['currentPeriod']['dateBasis'])
        self.assertEqual('Asia/Tokyo',
                         binding['metricsReceipt']['ga4Period']['dateBasis'])
        self.assertEqual('unconnected', binding['metricsReceipt']['intentEvidence']['status'])
        self.assertFalse(binding['constraints']['causalGuarantee'])
        self.assertEqual(job['revisionContext']['baseProducts'],
                         job['revisionContext']['candidateProducts'])

    def test_once_per_period_and_same_input_never_repeats_source_call(self):
        first = self.prepare()
        changed = analytics()
        changed['opportunities'][0]['gsc']['impressions'] = 999
        second = self.prepare(changed)
        self.assertEqual(first, second)
        self.assertEqual(1, self.catalog.gather_revision.call_count)
        routine = [job for job in self.ledger.list_jobs()
                   if (job.get('revisionContext') or {}).get('analysisBinding')]
        self.assertEqual(1, len(routine))

    def test_direct_analysis_request_is_rejected_and_period_stays_single(self):
        prepared = self.prepare()
        job = self.ledger.get_job(prepared['revisionJobId'])
        specification = {key: copy.deepcopy(value)
                         for key, value in job['revisionContext'].items()
                         if key not in ('kind', 'baseHash', 'productPatches')}
        other_root = Path(self.temp.name) / 'other-state'
        other = Ledger(other_root, 'owner')
        with self.assertRaisesRegex(ValueError, 'claimed improvement attempt'):
            other.request_revision(specification, now=NOW)
        self.assertEqual([], other.list_jobs())
        with self.assertRaisesRegex(ValueError, 'claimed improvement attempt'):
            self.ledger.request_revision(specification, now=NOW)
        routine = [saved for saved in self.ledger.list_jobs()
                   if (saved.get('revisionContext') or {}).get('analysisBinding', {}).get('period')
                   == prepared['period']]
        self.assertEqual([prepared['revisionJobId']], [saved['id'] for saved in routine])

    def test_analysis_binding_rejects_stale_base_hash(self):
        result = self.prepare()
        job = self.ledger.get_job(result['revisionJobId'])
        raw = {key: copy.deepcopy(value) for key, value in job['revisionContext'].items()
               if key not in ('kind', 'baseHash', 'productPatches')}
        raw['analysisBinding']['baseArticleHash'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'baseline hash'):
            validated_context(raw)

    def test_analysis_binding_rejects_source_id_receipt_mismatch(self):
        result = self.prepare()
        job = self.ledger.get_job(result['revisionJobId'])
        raw = {key: copy.deepcopy(value) for key, value in job['revisionContext'].items()
               if key not in ('kind', 'baseHash', 'productPatches')}
        raw['analysisBinding']['sourceProof']['sourceId'] = 'catalog-gather:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'source proof'):
            validated_context(raw)

    def test_top_three_click_winner_is_protected(self):
        target = opportunity('https://camp-gear-lab.com/articles/winner-three')
        metrics = analytics(target)
        result = self.prepare(metrics)
        self.assertEqual('hold', result['status'])
        self.assertIn('winner_protected', result['sourceHoldReasons'])
        self.catalog.gather_revision.assert_not_called()
        self.assertEqual([], self.ledger.list_jobs())

    def test_pending_revision_blocks_without_reusing_it(self):
        pending = self.ledger.request_revision(self.manual_spec(), now=NOW)
        result = self.prepare()
        self.assertEqual('hold', result['status'])
        self.assertIn('pending_revision', result['sourceHoldReasons'])
        self.catalog.gather_revision.assert_not_called()
        self.assertEqual([pending['id']], [job['id'] for job in self.ledger.list_jobs()])

    def test_source_failure_is_durable_hold_and_not_retried(self):
        self.catalog.failure = ValueError('private source detail')
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first, second)
        self.assertEqual('hold', first['status'])
        self.assertEqual(['source_verification_failed'], first['sourceHoldReasons'])
        self.assertEqual(1, self.catalog.gather_revision.call_count)
        self.assertNotIn('private source detail', canonical(first))

    def test_unpublished_target_holds_before_source_or_job(self):
        live = {'articles': [article('draft')], 'products': [product()]}
        result = self.prepare(live=live)
        self.assertEqual('hold', result['status'])
        self.assertIn('target_not_published_with_full_article',
                      result['sourceHoldReasons'])
        self.catalog.gather_revision.assert_not_called()

    def test_unsafe_target_url_is_blocked(self):
        target = opportunity('https://camp-gear-lab.com/articles/firepit-beginner-guide?private=1')
        result = self.prepare(analytics(target))
        self.assertEqual('hold', result['status'])
        self.assertIn('unsafe_target_url', result['sourceHoldReasons'])
        self.catalog.gather_revision.assert_not_called()

    def test_existing_article_and_period_budget_are_not_reset(self):
        budget = ModelBudget(self.root, self.ledger.production_schedule)
        alias = 'article:' + fingerprint({'slug': article()['slug']})
        with budget.scope(alias, 'draft', NOW):
            reservation = budget.reserve({'model': 'offline', 'max_tokens': 10,
                                          'messages': [{'role': 'user', 'content': 'fixture'}]})
        budget.settle(reservation, {'input_tokens': 4, 'output_tokens': 2},
                      outcome='success', response_id='existing-response')
        before = budget.inspect(NOW)
        result = self.prepare()
        after = budget.inspect(NOW)
        self.assertEqual('queued', result['status'])
        self.assertEqual(before['period'], after['period'])
        self.assertEqual(before['articles'][alias], after['articles'][alias])
        self.assertEqual(alias, result['budgetArticleId'])

    def test_unknown_related_budget_holds_without_source_call(self):
        budget = ModelBudget(self.root, self.ledger.production_schedule)
        alias = 'article:' + fingerprint({'slug': article()['slug']})
        with budget.scope(alias, 'draft', NOW):
            reservation = budget.reserve({'model': 'offline', 'max_tokens': 10,
                                          'messages': [{'role': 'user', 'content': 'fixture'}]})
        budget.settle(reservation, None, outcome='unknown')
        result = self.prepare()
        self.assertEqual('hold', result['status'])
        self.assertIn('related_budget_requires_reconciliation',
                      result['sourceHoldReasons'])
        self.catalog.gather_revision.assert_not_called()

    def test_attempt_and_result_rows_are_immutable(self):
        result = self.prepare()
        with sqlite3.connect(self.ledger.db_path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE existing_improvement_results SET data='{}' WHERE period=?",
                           (result['period'],))


if __name__ == '__main__':
    unittest.main()
