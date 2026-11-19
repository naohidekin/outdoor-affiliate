"""Contract-level flow tests; synthetic data never contacts a provider or merchant."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from runtime import Runtime, atomic, JST
from model_budget import BudgetHold
from test_quality import bundle
from test_topic_selection import (feed as nonproduct_feed, nonproduct_bundle,
                                  proposal as nonproduct_proposal)
from topic_selection import bind_nonproduct_theme


class ModelsFake:
    def __init__(self):
        self.usage = []
        self.fail_polish = False

    def research(self, context):
        return {'themes': [{'slug': 'new-{}'.format(i), 'title': '新記事{}'.format(i)} for i in range(3)]}

    def draft(self, theme, context):
        b = bundle()
        b['brief']['externalSafe'] = True
        return b

    def polish(self, source, brief):
        return {'content': source + ('\n## 勝手な見出し' if self.fail_polish else ''), 'model': 'gemini-3.8-flash'}

    def review(self, b, checks):
        return {'passed': True, 'score': 8.5, 'model': 'upper', 'issues': [], 'evidence': checks,
                'wisePolicy': checks.get('wisePolicy', {}).get('id'),
                'wiseScores': dict(w=3, i=3, s=3, e=3, ai=3, sense=3)}

    def social(self, b, url):
        return {'text': '新記事です。', 'replyText': url, 'url': url, 'images': b['images'], 'platform': 'x'}


class CatalogFake:
    def catalog(self):
        return {'articles': [], 'products': [], 'categories': [], 'clicks': []}

    def gather(self, theme, context):
        return {'catalog': bundle()['products'], 'references': bundle()['references'],
                'checks': {k: True for k in ('facts', 'images', 'affiliate')}}

    def request(self, *_args, **_kwargs):
        raise OSError('offline fixture')


class SlackFake:
    def _call(self, method, data):
        return {'ok': True}

    def __init__(self):
        self.deliveries, self.notices = [], []

    def deliver(self, job, req):
        self.deliveries.append((job, req))
        return [{'verified': True}], '1793000000.123456'

    def notice(self, text):
        self.notices.append(text)


class RuntimeTests(unittest.TestCase):
    def test_final_reviewer_receives_measured_body_length_and_unchanged_format_bounds(self):
        from unittest.mock import patch
        from models import ARTICLE_LENGTHS
        with patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.produce(limit=1)
        candidate, checks = review.call_args.args
        measurement = checks['articleMeasurements']
        self.assertEqual(len(candidate['article']['content']), measurement['contentCharacters'])
        self.assertEqual(ARTICLE_LENGTHS[candidate['brief']['format']],
                         (measurement['minimumCharacters'], measurement['maximumCharacters']))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = base / 'env'
        self.env.write_text('AMAZON_PARTNER_TAG=camp78-22\n')
        self.scope = dict(team_id='T', app_id='A', user_id='U', channel_id='C', thread_ts='1793000000.000001')
        self.config = {'stateRoot': str(base / 'private'), 'envFile': str(self.env),
                       'repo': str(Path(__file__).resolve().parents[2]), 'slack': self.scope,
                       'spoolDir': str(base / 'spool'), 'generationEnabled': True, 'publicationEnabled': True}
        Path(self.config['spoolDir']).mkdir(mode=0o700)
        self.models, self.slack, self.writes = ModelsFake(), SlackFake(), []

        def publish(action, job):
            self.writes.append((action, job['revision']))
            return {'verified': True, 'url': 'https://camp-gear-lab.com/articles/' + job['theme']['slug'],
                    'readback': {'verified': True, 'fingerprint': job['revision']}}
        self.runtime = Runtime(self.config, models=self.models, catalog=CatalogFake(), slack=self.slack,
            renderer=lambda b, j: {'passed': True, 'clicksVerified': {'desktop': [1], 'mobile': [1]}}, publisher=publish)

    def tearDown(self):
        self.tmp.cleanup()

    def configure_production_schedule(self):
        self.config['productionSchedule'] = dict(weekday=4, hour=9, effectiveFrom='2026-11-13',
            initialProductionAt='2026-11-08T00:00:00+09:00')
        # Recreate the runner through its real constructor to verify config wiring.
        old = self.runtime
        self.runtime = Runtime(self.config, models=self.models, catalog=old.catalog, slack=self.slack,
            renderer=old.renderer, publisher=old.publisher)

    def test_configured_manual_produce_uses_period_and_cannot_bypass_caps(self):
        self.configure_production_schedule()
        with patch('runtime.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 7, 22, tzinfo=JST)
            self.assertEqual('idle', self.runtime.produce()['status'])
            self.assertEqual([], self.runtime.ledger.list_jobs())
            for day, key in ((8, '2026-11-06'), (9, '2026-11-06'),
                             (11, '2026-11-06'), (12, '2026-11-06'),
                             (13, '2026-11-13')):
                clock.now.return_value = datetime(2026, 11, day, 9, tzinfo=JST)
                result = self.runtime.produce(limit=99)
                self.assertEqual(0 if day in (9, 11, 12) else 3, len(result['articles']))
                self.assertEqual('idle', self.runtime.produce(limit=99)['status'])
                for job in self.runtime.ledger.list_jobs():
                    if job['week'] == key:
                        self.runtime.ledger.set_stage(job['id'], 'rejected')
                # Released pending slots still cannot bypass the period cap.
                self.assertEqual('idle', self.runtime.produce(limit=99)['status'])
                if day not in (9, 11, 12):
                    self.models.research = lambda context, day=day: {'themes': [
                        {'slug': f'after-{day}-{i}', 'title': '新記事'} for i in range(3)]}
        self.assertEqual(['2026-11-06.json', '2026-11-13.json'],
            sorted(p.name for p in (self.runtime.root / 'production-attempts').glob('*.json')))
        self.assertEqual(6, len(self.runtime.ledger.list_jobs()))

    def test_configured_manual_produce_cannot_bypass_friday_hour(self):
        self.configure_production_schedule()
        with patch('runtime.datetime') as clock:
            for day in (13, 20):
                clock.now.return_value = datetime(2026, 11, day, 8, 59, 59, tzinfo=JST)
                self.assertEqual('idle', self.runtime.produce(limit=99)['status'])
        self.assertEqual([], self.runtime.ledger.list_jobs())
        self.assertFalse((self.runtime.root / 'production-attempts').exists())

    def test_mixed_period_saves_three_and_backfills_one_free_slot_without_research(self):
        self.configure_production_schedule()
        old = [self.runtime.ledger.create_candidate({'slug': f'carry-{i}'},
               f'2026-11-13T09:0{i}:00+09:00') for i in range(2)]
        for job in old:
            self.runtime.ledger.set_stage(job['id'], 'review')
        proposals = []
        topics = [('tent-dry', '雨撤収した幕を乾かすには？', ['汚れを落とす', '乾燥場所', '保管確認']),
                  ('layering', '重ね着の順番は？', ['肌着', '中間着', '上着']),
                  ('sleeping-bag-care', '寝袋を乾燥して保管するには？', ['汚れ確認', '乾燥', '保管'])]
        public_ids = ['public:tent', 'public:layer', 'public:camp']
        for i, (slug, question, outline) in enumerate(topics):
            proposals.append({'slug': slug, 'title': question, 'categoryId': 'tent',
                'productIds': [], 'topicType': 'knowhow', 'query': question,
                'readerQuestion': question, 'intent': 'informational',
                'outline': outline, 'priority': 90-i,
                'overlapRationale': 'distinct', 'selectionReason': 'verified',
                'sourceIds': ['gsc:fixture', public_ids[i]], 'proposedAction': 'new',
                'overlapArticleIds': [], 'needsStatus': 'not_applicable'})
        feed = {'status': 'verified', 'sources': [
                {'id': 'public:tent', 'scope': 'tent-care', 'receiptSha256': 'a' * 64},
                {'id': 'public:layer', 'scope': 'layering-concept-only', 'receiptSha256': 'b' * 64},
                {'id': 'public:camp', 'scope': 'camp-care', 'receiptSha256': 'c' * 64}],
                'illustrations': []}
        research = {'editorialSignals': [{'id': 'gsc:fixture', 'kind': 'gsc'},
            *[{'id': item['id'], 'kind': 'public_reference'} for item in feed['sources']]]}
        self.runtime.catalog.request = lambda *_args, **_kwargs: None
        with patch('runtime.datetime') as clock, \
                patch('runtime.collect_primary_sources', return_value=feed) as collect, \
                patch.object(self.runtime, '_research_context', return_value=research), \
                patch.object(self.models, 'research_mixed', create=True,
                             return_value={'proposals': proposals}) as model, \
                patch.object(self.runtime, '_make_article', side_effect=lambda job, context:
                    self.runtime.ledger.set_stage(job['id'], 'review')) as make:
            clock.now.return_value = datetime(2026, 11, 20, 9, tzinfo=JST)
            first = self.runtime.produce(limit=99)
            self.assertEqual(1, len(first['articles']))
            self.assertEqual(1, make.call_count)
            attempt = self.runtime.root / 'production-attempts' / '2026-11-20.json'
            saved_bytes = attempt.read_bytes()
            saved = json.loads(saved_bytes)
            self.assertEqual([bind_nonproduct_theme(theme, feed) for theme in proposals], saved['themes'])
            self.assertEqual('idle', self.runtime.produce(limit=99)['status'])
            for job in old:
                self.runtime.ledger.set_stage(job['id'], 'rejected')
                self.assertEqual(1, len(self.runtime.produce(limit=99)['articles']))
            self.assertEqual(3, make.call_count)
            self.assertEqual('idle', self.runtime.produce(limit=99)['status'])
            self.assertEqual(saved_bytes, attempt.read_bytes())
        collect.assert_called_once(); model.assert_called_once()
        current = [job for job in self.runtime.ledger.list_jobs() if job['week'] == '2026-11-20']
        self.assertEqual([theme['slug'] for theme in proposals], [job['theme']['slug'] for job in current])
        self.assertTrue(all(job['approval'] is None and job['publication'] is None for job in current))
        receipt = json.loads((self.runtime.root / 'period-receipts' / '2026-11-20.json').read_text())
        self.assertEqual({'knowhow', 'product', 'seasonal_problem'}, set(receipt['genreCoverage']))
        self.assertEqual('no_proposal', receipt['genreCoverage']['product']['unavailableReason'])

    def test_mixed_precall_budget_hold_is_terminal_and_quiet_on_next_tick(self):
        self.configure_production_schedule()
        feed = {'status': 'partial', 'sources': [], 'illustrations': []}
        research = {'editorialSignals': [], 'categories': []}
        hold = BudgetHold(reason_code='period_calls_cap', budget_scope='period',
                          dimension='calls', cap=3, projected=4,
                          article_id='research:2026-11-20', stage='research',
                          period_key='2026-11-20', event_id='budget-event')
        with patch('runtime.datetime') as clock, \
                patch('runtime.require_fresh_daily_metrics'), \
                patch('runtime.collect_primary_sources', return_value=feed) as collect, \
                patch.object(self.runtime, '_research_context', return_value=research), \
                patch.object(self.models, 'research_mixed', create=True,
                             side_effect=hold) as model:
            clock.now.return_value = datetime(2026, 11, 20, 9, tzinfo=JST)
            first = self.runtime.produce()
            second = self.runtime.produce()
        self.assertEqual(('model_budget_hold', True),
                         (first['reason'], first['retryable']))
        self.assertEqual(first, second)
        collect.assert_called_once()
        model.assert_called_once()
        marker = json.loads((self.runtime.root / 'production-attempts' /
                             '2026-11-20.json').read_text())
        self.assertEqual('budget_hold', marker['status'])
        self.assertFalse(marker['transportReservation'])
        self.assertFalse(marker['requestMayHaveOccurred'])
        self.assertFalse(marker['requestOccurred'])

    def test_mixed_budget_hold_after_reservation_requires_reconciliation(self):
        self.configure_production_schedule()
        hold = BudgetHold(reason_code='period_calls_cap', budget_scope='period',
                          dimension='calls', cap=3, projected=4,
                          article_id='research:2026-11-20', stage='research',
                          period_key='2026-11-20', event_id='budget-event-after-request')
        with patch('runtime.datetime') as clock, \
                patch('runtime.require_fresh_daily_metrics'), \
                patch('runtime.collect_primary_sources', return_value={
                    'status': 'partial', 'sources': [], 'illustrations': []}), \
                patch.object(self.runtime, '_research_context', return_value={
                    'editorialSignals': [], 'categories': []}), \
                patch.object(self.runtime.model_budget, 'has_request_reservation',
                             return_value=True), \
                patch.object(self.models, 'research_mixed', create=True,
                             side_effect=hold) as model:
            clock.now.return_value = datetime(2026, 11, 20, 9, tzinfo=JST)
            first = self.runtime.produce()
            second = self.runtime.produce()
        self.assertEqual(('weekly_research_requires_reconciliation', False),
                         (first['reason'], first['retryable']))
        self.assertEqual(first, second)
        model.assert_called_once()
        marker = json.loads((self.runtime.root / 'production-attempts' /
                             '2026-11-20.json').read_text())
        self.assertEqual('budget_hold_after_request', marker['status'])
        self.assertTrue(marker['transportReservation'])
        self.assertTrue(marker['requestMayHaveOccurred'])
        self.assertIsNone(marker['requestOccurred'])

    def test_mixed_insufficient_pool_returns_same_known_hold_without_second_ai_call(self):
        self.configure_production_schedule()
        proposals = [
            {'slug': 'tent-dry-hold', 'title': 'テントを乾燥して保管するには？',
             'categoryId': 'tent', 'productIds': [], 'topicType': 'knowhow',
             'query': 'テント 乾燥 保管', 'readerQuestion': 'テントを乾燥して保管するには？',
             'intent': 'informational', 'outline': ['汚れ確認', '乾燥', '保管'],
             'priority': 90, 'overlapRationale': 'distinct', 'selectionReason': 'verified',
             'sourceIds': ['gsc:fixture', 'public:tent'], 'proposedAction': 'new',
             'overlapArticleIds': [], 'needsStatus': 'not_applicable'},
            {'slug': 'layering-hold', 'title': '重ね着の順番は？',
             'categoryId': 'wear', 'productIds': [], 'topicType': 'knowhow',
             'query': '重ね着 順番', 'readerQuestion': '重ね着の順番は？',
             'intent': 'informational', 'outline': ['肌着', '中間着', '上着'],
             'priority': 89, 'overlapRationale': 'distinct', 'selectionReason': 'verified',
             'sourceIds': ['gsc:fixture', 'public:layer'], 'proposedAction': 'new',
             'overlapArticleIds': [], 'needsStatus': 'not_applicable'}]
        feed = {'status': 'verified', 'sources': [
            {'id': 'public:tent', 'scope': 'tent-care', 'receiptSha256': 'a' * 64},
            {'id': 'public:layer', 'scope': 'layering-concept-only', 'receiptSha256': 'b' * 64}],
            'illustrations': []}
        research = {'editorialSignals': [{'id': 'gsc:fixture', 'kind': 'gsc'},
            {'id': 'public:tent', 'kind': 'public_reference'},
            {'id': 'public:layer', 'kind': 'public_reference'}], 'categories': []}
        with patch('runtime.datetime') as clock, patch('runtime.require_fresh_daily_metrics'), \
                patch('runtime.collect_primary_sources', return_value=feed) as collect, \
                patch.object(self.runtime, '_research_context', return_value=research), \
                patch.object(self.models, 'research_mixed', create=True,
                             return_value={'proposals': proposals}) as model:
            clock.now.return_value = datetime(2026, 11, 20, 9, tzinfo=JST)
            first = self.runtime.produce()
            second = self.runtime.produce()
        expected = {'status': 'blocked', 'reason': 'insufficient_qualified_period_pool',
                    'articles': [], 'eligibleCount': 2, 'unfilled': 1}
        self.assertEqual(expected, first)
        self.assertEqual(expected, second)
        collect.assert_called_once()
        model.assert_called_once()
        marker = json.loads((self.runtime.root / 'production-attempts' /
                             '2026-11-20.json').read_text())
        self.assertEqual('selection_hold', marker['status'])
        self.assertEqual('insufficient_qualified_period_pool', marker['holdReason'])
        self.assertEqual([], self.runtime.ledger.list_jobs())

    def test_supplemental_before_not_before_has_no_catalog_marker_or_model(self):
        self.config['supplementalApparelEnabled'] = True
        calls = []
        self.runtime.catalog.catalog = lambda: calls.append('catalog') or {}
        result = self.runtime.produce_supplemental(
            now=datetime(2026, 11, 16, 8, 59, tzinfo=JST))
        self.assertEqual('not_due', result['status'])
        self.assertEqual([], calls)
        self.assertFalse((self.runtime.root / 'supplemental-batches').exists())
        self.assertEqual({'status': 'awaiting_start', 'batchId': 'apparel-2026-11-16',
                          'notBefore': '2026-11-16T09:00:00+09:00', 'maxArticles': 3,
                          'batchCallCap': 96, 'modelCallsUsed': 0,
                          'modelCallsRemaining': 96, 'ready': 0, 'held': 3},
                         self.runtime._supplemental_health(
                             datetime(2026, 11, 16, 8, 59, tzinfo=JST)))

    def test_supplemental_missing_sources_holds_and_notifies_once_per_state(self):
        self.config['supplementalApparelEnabled'] = True
        now = datetime(2026, 11, 16, 9, tzinfo=JST)
        first = self.runtime.produce_supplemental(now=now)
        second = self.runtime.produce_supplemental(now=now + timedelta(minutes=5))
        self.assertEqual('source_hold', first['status'])
        self.assertEqual('source_hold', second['status'])
        self.assertEqual(1, len([text for text in self.slack.notices
                                if '追加ウェア記事・参照状態' in text]))
        notice = next(text for text in self.slack.notices if '追加ウェア記事・参照状態' in text)
        self.assertIn('確認済み事実:',notice)
        self.assertIn('根本原因は未確定',notice)
        self.assertIn('追加batch実測',notice)
        self.assertNotIn('catalog_product_not_verified',notice)
        marker = json.loads((self.runtime.root / 'supplemental-batches' /
                             'apparel-2026-11-16.json').read_text())
        health = self.runtime._supplemental_health(now + timedelta(minutes=5))
        self.assertEqual(('source_hold', 0, 3),
                         (health['status'], health['ready'], health['held']))
        self.assertEqual('source_hold', marker['status'])
        self.assertEqual({}, marker['articleIds'])
        instructions = self.runtime._context()['instructions']
        self.assertIn('Prioritize owner-requested autumn/winter apparel directions among verified '
                      'eligible products; source evidence and duplication rules override preference.',
                      instructions)

    def test_supplemental_ready_slot_creates_only_one_bound_candidate(self):
        self.config['supplementalApparelEnabled'] = True
        product = {'id': 'apparel-montbell-1101493', 'name': 'Plasma',
            'brand': 'mont-bell', 'categoryId': 'wear',
            'imageUrl': 'https://img.example/item.png',
            'affiliateUrl': 'https://affiliate.example/item',
            'amazonUrl': 'https://amazon.example/item',
            'specs': {'apparelClass': 'down', 'model': '1101493', 'gender': 'unisex',
                      'fabric': 'nylon', 'optionState': 'selectable'}}
        self.runtime.catalog.catalog = lambda: {'articles': [], 'products': [product],
                                                'categories': [], 'clicks': []}
        with patch.object(self.runtime, '_make_article', return_value={'status': 'review'}) as make:
            result = self.runtime.produce_supplemental(
                now=datetime(2026, 11, 16, 9, tzinfo=JST))
        self.assertEqual(1, len(result['articles']))
        jobs = self.runtime.ledger.list_jobs()
        self.assertEqual(1, len(jobs))
        self.assertEqual('supplemental_article', jobs[0]['kind'])
        self.assertEqual(1, jobs[0]['batchSlot'])
        make.assert_called_once()

    def test_mixed_apparel_merchant_variants_require_approval_facing_disclosure(self):
        gathered = {'products':[{'id':'apparel-montbell-1101493','name':'プラズマ1000'}],
                    'evidence':{'products':[{'productId':'apparel-montbell-1101493',
                        'destinations':[
                            {'channel':'rakuten','apparelBinding':{'merchantOptionState':'selectable'}},
                            {'channel':'amazon','apparelBinding':{'merchantOptionState':'fixed'}}]}]}}
        disclosures = self.runtime._apparel_variant_disclosures(gathered)
        self.assertEqual(1,len(disclosures))
        self.assertIn('楽天市場はカラー・サイズ選択式',disclosures[0])
        self.assertIn('Amazonは確認済みの固定バリエーション',disclosures[0])
        self.assertIn('同じカラー・サイズとは限らない',disclosures[0])

    def test_tick_executes_one_supplemental_dispatch_action_once(self):
        self.config['supplementalApparelEnabled'] = True
        self.config['executionPolicy'] = {'mode': 'deterministic', 'suspended': False}
        plan = {'mode': 'deterministic', 'status': 'ready', 'actions': [
            {'kind': 'produce_supplemental', 'jobId': None}], 'blocked': [],
            'exceptionAI': False}
        with patch('runtime.DeterministicDispatcher.plan', return_value=plan), \
                patch.object(self.runtime, 'produce_supplemental',
                             return_value={'status': 'source_hold', 'articles': []}) as produce:
            self.runtime.tick()
        produce.assert_called_once()

    def test_tick_exposes_bounded_supplemental_verification(self):
        self.config['supplementalApparelEnabled'] = True
        self.config['generationEnabled'] = False
        expected = {'status':'waiting','batchId':'apparel-2026-11-16',
                    'articles':[],'handledAttentionJobIds':[]}
        with patch('supplemental_verification.verify_supplemental_batch',
                   return_value=expected) as verify:
            result = self.runtime.tick()
        self.assertEqual(expected,result['supplementalVerification'])
        verify.assert_called_once()

    def test_runtime_budget_path_holds_supplemental_batch_call_97_across_weeks(self):
        self.configure_production_schedule()
        jobs = []
        for slot in range(1, 4):
            theme = {'slug': f'extra-{slot}', 'title': f'Extra {slot}',
                     'categoryId': 'wear', 'productIds': [f'apparel-item-{slot}'],
                     'query': f'extra {slot}', 'selectionReason': 'verified fixture'}
            jobs.append(self.runtime.ledger.create_supplemental_candidate(
                theme, 'apparel-2026-11-16', slot, str(slot) * 64,
                social_eligible_period='2026-11-20',
                now='2026-11-16T09:00:00+09:00'))
        payload = {'model': 'fixture-model', 'max_tokens': 1,
                   'messages': [{'role': 'user', 'content': 'fixture'}]}
        for index in range(96):
            at = (datetime(2026, 11, 16, 10, tzinfo=JST)
                  if index < 48 else datetime(2026, 11, 23, 10, tzinfo=JST))
            job = jobs[index % 3]
            with self.runtime.model_budget.scope(
                    self.runtime._budget_article_id(job['id']), 'draft', at):
                self.runtime.model_budget.reserve(payload)
        self.assertTrue(all(self.runtime._budget_article_id(job['id']) == job['id']
                            for job in jobs))
        with self.assertRaises(BudgetHold) as held:
            self.runtime._measured_model_call(
                jobs[0]['id'], 'polish', 'fixture-model',
                lambda: self.runtime.model_budget.reserve(payload))
        self.assertEqual('batch_calls_cap', held.exception.reason_code)

    def test_configured_tick_due_and_catchup(self):
        self.configure_production_schedule()
        for day, hour, due in ((7, 23, False), (8, 0, True), (9, 8, True), (9, 9, True),
                               (11, 9, True), (13, 8, False), (13, 9, True),
                               (16, 9, True), (20, 9, True)):
            with self.subTest(day=day, hour=hour), patch('runtime.datetime') as clock, \
                    patch.object(self.runtime, 'produce', return_value={'status': 'idle'}) as produce:
                clock.now.return_value = datetime(2026, 11, day, hour, tzinfo=JST)
                self.runtime.tick()
                self.assertEqual(int(due), produce.call_count)

    def test_daily_metrics_collection_runs_before_tick_production(self):
        self.config.update(dailyMetricsEnabled=True,seoStateRoot=str(Path(self.tmp.name)/'seo'),
                           seoRepo=str(Path(self.tmp.name)/'repo'))
        self.configure_production_schedule(); events=[]
        with patch('runtime.datetime') as clock, \
                patch('runtime.collect_daily_metrics',side_effect=lambda *a,**k: events.append('metrics') or {'status':'success'}), \
                patch.object(self.runtime,'produce',side_effect=lambda *a,**k: events.append('produce') or {'status':'idle'}):
            clock.now.return_value=datetime(2026,11,20,9,tzinfo=JST)
            self.runtime.tick()
        self.assertEqual(['metrics','produce'],events)

    def test_new_research_freshness_gate_precedes_context_and_weekly_attempt(self):
        self.config.update(dailyMetricsEnabled=True,seoStateRoot=str(Path(self.tmp.name)/'seo'),
                           seoRepo=str(Path(self.tmp.name)/'repo'))
        self.configure_production_schedule()
        with patch('runtime.datetime') as clock, \
                patch('runtime.require_fresh_daily_metrics',side_effect=ValueError('daily_metrics_not_fresh')) as fresh, \
                patch.object(self.runtime,'_context') as context:
            clock.now.return_value=datetime(2026,11,20,9,tzinfo=JST)
            with self.assertRaisesRegex(ValueError,'daily_metrics_not_fresh'):
                self.runtime.produce()
        fresh.assert_called_once();context.assert_not_called()
        self.assertFalse((self.runtime.root/'production-attempts'/'2026-11-20.json').exists())

    def test_existing_candidate_resumes_without_daily_freshness_gate(self):
        candidate=self.runtime.ledger.create_candidate({'slug':'already-selected'},
                                                        '2026-11-19T09:00:00+09:00')
        self.config.update(dailyMetricsEnabled=True,seoStateRoot=str(Path(self.tmp.name)/'seo'),
                           seoRepo=str(Path(self.tmp.name)/'repo'))
        self.configure_production_schedule()
        with patch('runtime.datetime') as clock, \
                patch('runtime.require_fresh_daily_metrics',side_effect=ValueError('daily_metrics_not_fresh')) as fresh:
            clock.now.return_value=datetime(2026,11,20,9,tzinfo=JST)
            result=self.runtime.produce(limit=1)
        fresh.assert_called_once()
        self.assertEqual(candidate['id'],result['articles'][0]['id'])
        self.assertFalse((self.runtime.root/'production-attempts'/'2026-11-20.json').exists())

    def test_daily_collection_failure_does_not_block_existing_owner_approved_publication(self):
        self.runtime.produce(limit=1);job=next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        self.config['generationEnabled']=False;self.approve(job)
        self.config.update(dailyMetricsEnabled=True,seoStateRoot=str(Path(self.tmp.name)/'seo'),
                           seoRepo=str(Path(self.tmp.name)/'repo'))
        with patch('runtime.collect_daily_metrics',return_value={'status':'failed'}):
            result=self.runtime.tick()
        self.assertEqual('failed',result['dailyMetrics']['status'])
        self.assertEqual('attention',result['status'])
        self.assertIn({'id':'daily-metrics','status':'attention',
                       'reason':'daily_metrics_collection_failed'},result['results'])
        attention=lambda: [text for text in self.slack.notices
                           if text.startswith('【記事制作が止まっています】')]
        self.assertEqual(1,len(attention()))
        self.assertEqual('published',self.runtime.ledger.get_job(job['id'])['stage'])
        self.assertEqual(1,[action for action,_ in self.writes].count('publish'))
        with patch('runtime.collect_daily_metrics',return_value={'status':'already_failed'}):
            second=self.runtime.tick()
        self.assertEqual('attention',second['status'])
        self.assertEqual(1,len(attention()))

    def test_internal_validation_failures_stay_in_health_without_owner_notice(self):
        self.config['generationEnabled'] = False
        from attention_presentation import INTERNAL_REASONS
        for index, reason in enumerate(sorted(INTERNAL_REASONS)):
            candidate = self.runtime.ledger.create_candidate({'slug': 'internal-quality-'+str(index)},
                                                            '2026-11-16T09:00:00+09:00')
            self.runtime.ledger.set_stage(candidate['id'], 'error', {'reason': reason})
            result = self.runtime.tick()
            self.assertEqual('error', self.runtime.ledger.get_job(candidate['id'])['stage'])
            self.assertFalse(any(text.startswith('【記事制作が止まっています】') for text in self.slack.notices))
        self.assertTrue(any(j.get('error') for j in result['articles']))
        self.assertEqual([], self.models.usage)

    def test_pending_candidates_resume_without_rewriting_legacy_slots(self):
        candidate = self.runtime.ledger.create_candidate({'slug': 'pending'},
            datetime(2026, 11, 4, 9, tzinfo=JST))
        self.configure_production_schedule()
        # Three pending slots stop fresh research but must not stop old candidates.
        for i in range(2):
            self.runtime.ledger.create_candidate({'slug': f'other-{i}'}, '2026-11-09T09:00:00+09:00')
        with patch('runtime.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 13, 9, tzinfo=JST)
            result = self.runtime.produce(limit=1)
        self.assertEqual(candidate['id'], result['articles'][0]['id'])
        self.assertEqual('2026-11-02', self.runtime.ledger.get_job(candidate['id'])['week'])
        self.assertIsNone(self.runtime.ledger.get_job(candidate['id'])['approval'])
        self.assertFalse((self.runtime.root / 'production-attempts').exists())

    def test_configured_unpublished_cap_blocks_manual_next_period(self):
        self.configure_production_schedule()
        with patch('runtime.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 9, 9, tzinfo=JST)
            self.assertEqual(3, len(self.runtime.produce(limit=99)['articles']))
            before = self.runtime.ledger.list_jobs()
            clock.now.return_value = datetime(2026, 11, 13, 9, tzinfo=JST)
            self.assertEqual('idle', self.runtime.produce(limit=99)['status'])
        self.assertEqual(before, self.runtime.ledger.list_jobs())
        self.assertFalse((self.runtime.root / 'production-attempts' / '2026-11-13.json').exists())

    def test_configured_production_excludes_and_preserves_held_revisions(self):
        from test_revision_workflow import baseline, spec
        self.configure_production_schedule()
        held = []
        for id, slug in (('article-024', 'firepit-beginner-guide'),
                         ('article-005', 'single-burner-ranking'),
                         ('article-002', 'landlock-vs-landnest-shelter')):
            job = self.runtime.ledger.request_revision(spec(baseline(id, slug)),
                now='2026-11-09T09:00:00+09:00')
            self.runtime.ledger.set_stage(job['id'], 'held')
            held.append(self.runtime.ledger.get_job(job['id']))
        with patch('runtime.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 9, 9, tzinfo=JST)
            self.assertEqual(3, len(self.runtime.produce(limit=99)['articles']))
        self.assertEqual(6, len(self.runtime.ledger.list_jobs()))
        self.assertEqual(held, [self.runtime.ledger.get_job(j['id']) for j in held])
        with self.assertRaisesRegex(ValueError, 'weekly candidate cap'):
            self.runtime.ledger.create_candidate({'slug': 'fourth'}, '2026-11-11T09:00:00+09:00')

    def test_configured_attempt_marker_is_reconciled_in_same_period(self):
        self.configure_production_schedule()
        marker = self.runtime.root / 'production-attempts' / '2026-11-13.json'
        atomic(marker, {'status': 'in_flight', 'original': True})
        before = marker.read_bytes()
        with patch('runtime.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 16, 9, tzinfo=JST)
            with self.assertRaisesRegex(ValueError, 'weekly_research_requires_reconciliation'):
                self.runtime.produce()
        self.assertEqual(before, marker.read_bytes())

    def test_invalid_production_schedule_fails_closed(self):
        for schedule in (None, {}, {'weekday': 7}):
            with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                Runtime(dict(self.config, productionSchedule=schedule), models=self.models,
                    catalog=CatalogFake(), slack=self.slack)

    def test_render_receipt_keeps_parsed_failure_and_sanitizes_unavailable_output(self):
        from ledger import fingerprint
        b = bundle()
        job = {'id': 'preview-receipt-test'}
        receipt = self.runtime.root / 'previews' / job['id'] / fingerprint(b) / 'result.json'
        for stdout, error, expected in (
                (json.dumps({'passed': False, 'issues': ['missing FAQ']}), 'render_preview_failed',
                 {'passed': False, 'issues': ['missing FAQ']}),
                ('', 'render_preview_unavailable', None),
                ('PRIVATE RAW OUTPUT', 'render_preview_unavailable', None),
                ('[]', 'render_preview_unavailable', None),
                (json.dumps({'passed': True}), None, {'passed': True})):
            with self.subTest(stdout=stdout), patch('runtime.subprocess.run') as run:
                run.return_value.stdout = stdout
                run.return_value.stderr = 'PRIVATE STDERR'
                run.return_value.returncode = 0
                if error:
                    with self.assertRaisesRegex(ValueError, '^' + error + '$'):
                        Runtime._render(self.runtime, b, job)
                else:
                    self.assertEqual(expected, Runtime._render(self.runtime, b, job))
                observed = json.loads(receipt.read_text())
                self.assertEqual(expected or {'passed': False, 'reason': 'render_preview_unavailable',
                                             'returncode': 0}, observed)
                self.assertNotIn('PRIVATE', receipt.read_text())
                self.assertEqual(0o600, receipt.stat().st_mode & 0o777)

    def approve(self, job, user='U'):
        req = self.slack.deliveries[-1][1]
        if req['article_id'] != job['id']:
            req = next(r for j, r in self.slack.deliveries if j['id'] == job['id'])
        event = dict(req['payload'], **self.scope)
        event.update(user_id=user, event_id='event-' + req['request_id'],
                     action_id='camp_review_approve', message_ts='1793000000.123456')
        atomic(Path(self.config['spoolDir']) / (req['request_id'] + '.json'), event)

    def test_three_drafts_then_only_owner_approved_version_publishes(self):
        result = self.runtime.produce()
        self.assertEqual(3, len(result['articles']))
        self.assertEqual(['stage'] * 3, [a for a, _ in self.writes])
        self.assertEqual(3, len(self.slack.deliveries))
        self.assertTrue(all(j['approval'] is None for j in self.runtime.ledger.list_jobs()))
        self.config['generationEnabled'] = False
        job = self.runtime.ledger.list_jobs()[0]
        self.approve(job)
        self.runtime.tick()
        self.assertEqual(1, [a for a, _ in self.writes].count('publish'))
        self.runtime.tick()
        self.assertEqual(1, [a for a, _ in self.writes].count('publish'))
        self.assertTrue(any(r['kind'] == 'social' for _, r in self.slack.deliveries))

    def test_nonproduct_actual_make_article_requires_separate_article_and_social_approval(self):
        self.config.update(socialCardsEnabled=True, prewriteDisplayGateEnabled=True,
                           socialGenerationEnabled=True, socialReviewEnabled=True)
        self.configure_production_schedule()
        draft = nonproduct_bundle()
        theme = bind_nonproduct_theme(
            nonproduct_proposal('tent-dry-runtime', 'テントを乾かす手順は？'),
            nonproduct_feed())
        job = self.runtime.ledger.create_candidate(
            theme, datetime(2026, 11, 20, 9, tzinfo=JST))
        illustration = copy.deepcopy(draft['images'][0])

        class EditorialCards:
            def build_editorial_illustration(inner, selected, references, receipt):
                self.assertEqual(theme['outline'], selected['outline'])
                self.assertEqual(theme['nonProductContract']['references'], references)
                self.assertEqual(theme['nonProductContract']['sourceReceiptSha256'], receipt)
                return copy.deepcopy(illustration)

        self.runtime.social_cards = EditorialCards()
        excerpt = theme['nonProductContract']['references'][0]['excerpt']
        self.runtime.catalog.request = lambda url, _headers: {
            'url': url, 'status': 200, 'headers': {'content-type': 'text/html; charset=utf-8'},
            'body': ('<html><body><p>' + excerpt + '</p></body></html>').encode()}
        self.models.draft = lambda selected, gathered: copy.deepcopy(draft)
        self.runtime.renderer = lambda built, current: {
            'passed': True, 'clicksVerified': {'desktop': [], 'mobile': []},
            'sponsoredCtaCount': {'desktop': 0, 'mobile': 0},
            'allAnchorsVerified': True}

        def publish(action, current):
            self.writes.append((action, current['revision']))
            context = current['bundle']['article']['generationMeta']['editorialContext']
            return {'verified': True,
                    'url': 'https://camp-gear-lab.com/articles/' + current['theme']['slug'],
                    'readback': {'verified': True, 'fingerprint': current['revision'],
                                 'productIds': [], 'editorialContext': context,
                                 'commercialRoute': {'status': 'not_applicable', 'measured': False,
                                     'sponsoredCtaCount': 0, 'reason': 'verified_nonproduct_article',
                                     'verifiedBy': 'deterministic_contract_v1'},
                                 'imageProofs': [{key: current['bundle']['images'][0][key]
                                     for key in ('id', 'url', 'sha256', 'size', 'contentType')}]}}

        self.runtime.publisher = publish
        delivered = self.runtime._make_article(job, self.runtime._context())
        current = self.runtime.ledger.get_job(job['id'])
        self.assertEqual('delivered', delivered['status'])
        self.assertEqual('review', current['stage'])
        self.assertEqual([], current['bundle']['article']['productIds'])
        self.assertEqual('not_applicable', current['review']['evidence']['affiliate']['applicability'])
        source_checks = list((self.runtime.root / 'source-rechecks' / job['id']).glob('*.json'))
        self.assertEqual(1, len(source_checks))
        self.assertEqual('verified', json.loads(source_checks[0].read_text())['status'])
        self.assertEqual(theme['nonProductContract'], current['theme']['nonProductContract'])
        article_request = self.slack.deliveries[-1][1]
        self.assertEqual('article', article_request['kind'])
        self.assertEqual(current['revision'], article_request['manifest_hash'])

        with patch('runtime.collect_daily_metrics', return_value={'status': 'success'}), \
                patch.object(self.runtime, '_post_publication_audits', return_value=[]):
            self.runtime.tick()
        self.assertNotIn('publish', [action for action, _ in self.writes])

        self.approve(current)
        self.runtime.consume()
        approved = self.runtime.ledger.get_job(job['id'])
        bad_readback = {'verified': True, 'fingerprint': approved['revision'],
                        'productIds': [], 'editorialContext':
                        approved['bundle']['article']['generationMeta']['editorialContext'],
                        'commercialRoute': {'status': 'not_applicable', 'measured': False,
                            'sponsoredCtaCount': 0, 'reason': 'verified_nonproduct_article',
                            'verifiedBy': 'deterministic_contract_v1'}}
        with self.assertRaisesRegex(ValueError, 'nonproduct public metadata readback required'):
            self.runtime.ledger.record_publication(job['id'], approved['revision'], {
                'verified': True, 'url': 'https://camp-gear-lab.com/articles/' + theme['slug'],
                'readback': bad_readback})
        self.assertEqual('approved', self.runtime.ledger.get_job(job['id'])['stage'])
        with patch('runtime.collect_daily_metrics', return_value={'status': 'success'}), \
                patch.object(self.runtime, '_post_publication_audits', return_value=[]):
            self.runtime.tick()
            published = self.runtime.ledger.get_job(job['id'])
            self.assertEqual('published', published['stage'])
            from ledger import fingerprint
            audit_key = fingerprint({'id': published['id'], 'revision': published['revision'],
                                     'publication': published['publication']})
            audit = {'schemaVersion': 1, 'status': 'success', 'id': published['id'],
                     'revision': published['revision'], 'auditKey': audit_key,
                     'publication': published['publication'], 'result': {
                         'passed': True, 'status': 'passed', 'issues': [], 'checks': [
                             {'name': 'approved_body', 'status': 'passed',
                              'reason': 'approved_body_hash_exact'},
                             {'name': 'desktop.merchant', 'status': 'not_applicable',
                              'reason': 'verified_nonproduct_article'},
                             {'name': 'mobile.merchant', 'status': 'not_applicable',
                              'reason': 'verified_nonproduct_article'}]}}
            path = self.runtime.root / 'post-publication-audits' / (audit_key + '.json')
            forged = copy.deepcopy(audit)
            forged['result']['checks'].pop()
            atomic(path, forged)
            self.assertFalse(self.runtime._social_audit_success(published))
            atomic(path, audit)
            self.assertTrue(self.runtime._social_audit_success(published))
            self.runtime.tick()
        social_review = self.runtime.ledger.get_job(job['id'])
        self.assertEqual('social_review', social_review['stage'])
        self.assertIsNone(social_review['social']['approval'])
        social_request = self.slack.deliveries[-1][1]
        self.assertEqual('social', social_request['kind'])
        self.assertNotEqual(article_request['manifest_hash'], social_request['manifest_hash'])

        self.approve(social_review)
        self.runtime.consume()
        social_approved = self.runtime.ledger.get_job(job['id'])
        self.assertEqual('social_approved', social_approved['stage'])
        self.assertNotEqual(social_approved['approval']['revision'],
                            social_approved['social']['approval']['revision'])

    def test_nonproduct_source_changed_or_unavailable_holds_before_ai(self):
        self.configure_production_schedule()
        theme = bind_nonproduct_theme(
            nonproduct_proposal('tent-source-recheck', 'テントを乾かす手順は？'),
            nonproduct_feed())
        job = self.runtime.ledger.create_candidate(
            theme, datetime(2026, 11, 20, 9, tzinfo=JST))
        self.runtime.social_cards = Mock()
        original_contract = copy.deepcopy(theme['nonProductContract'])
        with patch('runtime.datetime') as clock, patch.object(self.models, 'draft') as draft, \
                patch.object(self.models, 'review') as review:
            clock.now.return_value = datetime(2026, 11, 20, 9, tzinfo=JST)
            self.runtime.catalog.request = lambda url, _headers: {
                'url': url, 'status': 200, 'headers': {'content-type': 'text/html'},
                'body': '<html><p>別の内容へ変更されました。</p></html>'.encode()}
            changed = self.runtime.produce(limit=1)
            self.assertEqual('nonproduct_source_recheck_changed', changed['articles'][0]['reason'])
            self.assertEqual('held', self.runtime.ledger.get_job(job['id'])['stage'])

            self.runtime.ledger.set_stage(job['id'], 'candidate')
            self.runtime.catalog.request = Mock(side_effect=OSError('offline'))
            unavailable = self.runtime.produce(limit=1)
            self.assertEqual('nonproduct_source_recheck_unavailable',
                             unavailable['articles'][0]['reason'])
            self.assertEqual('held', self.runtime.ledger.get_job(job['id'])['stage'])
            draft.assert_not_called()
            review.assert_not_called()
            self.runtime.social_cards.build_editorial_illustration.assert_not_called()
        self.assertEqual(original_contract,
                         self.runtime.ledger.get_job(job['id'])['theme']['nonProductContract'])
        self.assertFalse((self.runtime.root / 'source-rechecks' / job['id']).exists())

    def test_foreign_owner_never_publishes(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        self.approve(next(j for j in self.runtime.ledger.list_jobs() if j['bundle']), user='other')
        self.runtime.tick()
        self.assertNotIn('publish', [a for a, _ in self.writes])

    def test_changed_image_invalidates_delivered_approval(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        self.approve(job)
        changed = copy.deepcopy(job['bundle'])
        changed['images'][0]['url'] = 'https://images.example.com/new.jpg'
        self.runtime.ledger.save_bundle(job['id'], changed, job['revision'])
        self.runtime.tick()
        self.assertNotIn('publish', [a for a, _ in self.writes])

    def test_failed_protected_polish_never_reaches_slack_or_draft_db(self):
        self.models.fail_polish = True
        self.runtime.produce(limit=1)
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)
        self.assertEqual(1, sum(j['stage'] == 'error' for j in self.runtime.ledger.list_jobs()))

    def test_unknown_publish_is_not_retried_after_restart(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        self.approve(next(j for j in self.runtime.ledger.list_jobs() if j['bundle']))
        attempts = []
        def lost(action, job):
            attempts.append(action)
            raise TimeoutError('unknown')
        self.runtime.publisher = lost
        self.runtime.tick()
        self.runtime.tick()
        self.assertEqual(['publish'], attempts)

    def test_delivery_uncertainty_never_auto_resends(self):
        self.runtime.produce(limit=1)
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        # Re-delivery of an already-read-back article is a no-op.
        self.assertEqual('already_delivered', self.runtime.deliver(job['id'])['status'])
        self.assertEqual(1, len(self.slack.deliveries))

    def published_job(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        self.approve(job)
        self.runtime.tick()
        return self.runtime.ledger.get_job(job['id'])

    def test_bad_spool_is_quarantined_and_valid_approval_continues(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        spool = Path(self.config['spoolDir'])
        (spool / '000-broken.json').write_text('{')
        (spool / '001-array.json').write_text('[]')
        self.approve(job)
        result = self.runtime.tick()
        self.assertEqual(1, result['decisions'])
        self.assertEqual('published', self.runtime.ledger.get_job(job['id'])['stage'])
        self.assertEqual(2, len(list((spool / 'editorial-quarantine').glob('*.json'))))

    def test_expired_verified_delivery_gets_new_nonce_and_old_card_is_invalid(self):
        self.runtime.produce(limit=1)
        job, old = self.slack.deliveries[-1]
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            row = json.loads(db.execute('SELECT data FROM requests WHERE id=?', (old['request_id'],)).fetchone()[0])
            row['expires_at'] = (datetime.now(JST) - timedelta(seconds=1)).isoformat()
            db.execute('UPDATE requests SET data=? WHERE id=?', (json.dumps(row), old['request_id']))
        self.assertEqual('delivered', self.runtime.deliver(job['id'])['status'])
        new = self.slack.deliveries[-1][1]
        self.assertNotEqual(old['nonce'], new['nonce'])
        event = dict(old['payload'], **self.scope, event_id='expired-card', action_id='camp_review_approve', card_ts='1793000000.123456')
        with self.assertRaises(ValueError):
            self.runtime.ledger.decide(event, self.scope)

    def test_unknown_delivery_stays_attention_and_notice_is_not_repeated(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job, req = self.slack.deliveries[-1]
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            row = json.loads(db.execute('SELECT data FROM requests WHERE id=?', (req['request_id'],)).fetchone()[0])
            row['status'] = 'created'
            row['expires_at'] = (datetime.now(JST) - timedelta(days=1)).isoformat()
            db.execute('UPDATE requests SET data=? WHERE id=?', (json.dumps(row), req['request_id']))
        for _ in range(2):
            self.assertEqual('attention', self.runtime.tick()['status'])
        self.assertEqual(1, len(self.slack.deliveries))
        self.assertEqual(1, len(self.slack.notices))
        health = json.loads((self.runtime.root / 'health.json').read_text())
        self.assertEqual('attention', health['status'])

    @staticmethod
    def with_card(b):
        b = copy.deepcopy(b)
        manifest = dict(url='https://img.example/card.png', sha256='a' * 64, size=1200,
                        contentType='image/png', width=1200, height=630,
                        templateVersion='test-v1', sources=[])
        b['article'].setdefault('generationMeta', {})['socialCard'] = manifest
        b['images'].append(dict(manifest, role='social-card', verified=True))
        return b

    def test_card_build_is_opt_in_and_precedes_render_review_and_stage(self):
        class Cards:
            def build(inner, b):
                self.assertIn('content', b['article'])
                return self.with_card(b)
        self.runtime.social_cards = Cards()
        self.config['socialCardsEnabled'] = True
        seen = []
        self.runtime.renderer = lambda b, j: (seen.append(copy.deepcopy(b)) or {'passed': True, 'clicksVerified': True})
        self.runtime.produce()
        self.assertEqual(len(seen), 3)
        for job in self.runtime.ledger.list_jobs():
            self.assertEqual(job['bundle']['images'][-1]['role'], 'social-card')
            self.assertIn('socialCard', job['bundle']['article']['generationMeta'])
        self.assertEqual([x[0] for x in self.writes], ['stage'] * 3)

    def test_enabled_card_build_failure_never_renders_or_stages(self):
        self.config['socialCardsEnabled'] = True
        class Cards:
            def build(inner, b):
                return b
        self.runtime.social_cards = Cards()
        with patch.object(self.runtime, 'renderer') as render:
            self.runtime.produce()
            render.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_social_uses_only_bound_card_and_requires_public_meta_readback(self):
        job = self.published_job()
        job['bundle'] = self.with_card(job['bundle'])
        with patch.object(self.models, 'social') as generate:
            with self.assertRaisesRegex(ValueError, 'social_card_public_readback_missing'):
                self.runtime.make_social(job)
            generate.assert_not_called()
        job['publication']['readback']['socialCard'] = job['bundle']['article']['generationMeta']['socialCard']
        with patch.object(self.models, 'review', wraps=self.models.review) as review, patch.object(self.runtime.ledger, 'record_social'), patch.object(self.runtime, 'deliver'):
            self.runtime.make_social(job)
        self.assertEqual(review.call_args.args[0]['proposal']['images'], [job['bundle']['images'][-1]])
        job['bundle']['images'].pop()
        with self.assertRaisesRegex(ValueError, 'social_card_evidence_missing'):
            self.runtime.make_social(job)

    def test_social_new_claim_image_and_url_never_become_review_evidence(self):
        job = self.published_job()
        for change in ({'text': 'この製品は900gです。'}, {'replyText': 'https://evil.example/other'},
                       {'images': [{'url': 'https://evil.example/image.png', 'verified': True}]}):
            with self.subTest(change=change):
                proposal = self.models.social(job['bundle'], job['publication']['url'])
                proposal.update(change)
                with patch.object(self.models, 'social', return_value=proposal), patch.object(self.models, 'review') as review:
                    with self.assertRaises(ValueError):
                        self.runtime.make_social(job)
                    review.assert_not_called()

    def test_social_binding_rejects_unverified_or_stale_publication(self):
        job = self.published_job()
        for mutation in ({'verified': False}, {'readback': {'verified': True, 'fingerprint': 'stale'}}):
            changed = copy.deepcopy(job)
            changed['publication'].update(mutation)
            with patch.object(self.models, 'social') as generate:
                with self.assertRaises(ValueError):
                    self.runtime.make_social(changed)
                generate.assert_not_called()

    def test_social_review_receives_proposal_surface_and_independent_format_evidence(self):
        job = self.published_job()
        with patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.make_social(job)
        checks = review.call_args.args[1]
        self.assertEqual(checks['reviewKind'], 'social')
        self.assertEqual(checks['publicationReadback'], job['publication'])
        proof = checks['independentSocialFormat']
        self.assertEqual(proof['platform'], 'x')
        self.assertEqual(proof['weightedLength'], sum(1 if ord(c) < 128 else 2 for c in '新記事です。'))
        self.assertEqual(proof['maxWeightedLength'], 280)
        self.assertTrue(all(proof[k] for k in ('formatVerified', 'imagesVerified', 'urlBindingVerified')))
        self.assertIn('not the source article browser', proof['surface'])

    def test_article_original_and_candidate_saved_and_original_sent_to_review(self):
        source = bundle()['article']['content']
        with patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.produce(limit=1)
        checks = review.call_args.args[1]
        self.assertEqual(source, checks['sourceContent'])
        artifacts = list((self.runtime.root / 'research' / 'artifacts').rglob('*.json'))
        self.assertEqual(2, len(artifacts))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in artifacts))
        self.assertEqual({'source', 'candidate'}, {json.loads(p.read_text())['kind'] for p in artifacts})

    def test_health_has_state_and_real_review_model_without_private_payload(self):
        job = self.published_job()
        health = self.runtime.tick()
        summary = next(a for a in health['articles'] if a['id'] == job['id'])
        self.assertEqual({'model': 'upper', 'score': 8.5, 'passed': True}, summary['review'])
        self.assertTrue(summary['publication']['verified'])
        self.assertEqual('approved', summary['approval']['action'])
        self.assertEqual('social_review', summary['social']['status'])
        encoded = json.dumps(health)
        self.assertNotIn('nonce', encoded)
        self.assertNotIn(job['bundle']['article']['content'], encoded)

    def test_preflight_preservation_failure_never_writes_ready(self):
        self.models.fail_polish = True
        with self.assertRaises(ValueError):
            self.runtime.preflight()
        self.assertFalse((self.runtime.root / 'preflight.json').exists())

    def test_source_failure_retries_same_slot_without_more_candidates(self):
        with patch.object(self.runtime.catalog, 'gather', return_value={'checks': {'facts': False}}):
            self.runtime.produce(limit=1)
        failed = next(j for j in self.runtime.ledger.list_jobs() if j['stage'] == 'error')
        self.assertTrue(self.runtime.retry(failed['id'])['sameWeeklySlot'])
        self.runtime.produce()
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        self.assertEqual('review', self.runtime.ledger.get_job(failed['id'])['stage'])

    def test_failed_research_is_not_billed_again_on_each_tick(self):
        with patch.object(self.models, 'research', side_effect=ValueError('provider_unavailable')) as call:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    self.runtime.produce()
        self.assertEqual(1, call.call_count)

    def test_final_review_receives_product_specific_evidence(self):
        gathered = self.runtime.catalog.gather({}, {})
        gathered['evidence'] = {'products': [{'productId': 'p1', 'claims': [{'field': 'weight', 'verified': True}]}]}
        with patch.object(self.runtime.catalog, 'gather', return_value=gathered), patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.produce(limit=1)
        self.assertEqual(gathered['evidence'], review.call_args.args[1]['source'])

    def test_existing_medical_gate_blocks_faq_risk_before_slack_or_db(self):
        unsafe = bundle()
        unsafe['faqs'] = unsafe['article']['faqs']
        unsafe['article']['faqs'][0]['answer'] = '低温やけどと凍傷について。'
        with patch.object(self.models, 'draft', return_value=unsafe):
            self.runtime.produce(limit=1)
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)

    def test_research_counts_only_recent_aware_clicks_and_labels_metric(self):
        now = datetime.now(JST)
        context = {'products': [], 'articles': [], 'queuedThemes': [], 'instructions': '', 'clicks': [
            {'clickedAt': (now - timedelta(days=days)).isoformat(), 'pagePath': '/a', 'store': 'rakuten'}
            for days in (1, 60, -1)] + [{'clickedAt': '2026-11-03T12:00:00', 'pagePath': '/a', 'store': 'rakuten'}]}
        result = self.runtime._research_context(context)
        self.assertEqual([{'article': '/a', 'store': 'rakuten', 'clicks': 1}], result['merchantClicks'])
        self.assertIn('not purchases', result['observation']['metric'])

    def test_analytics_context_exports_separate_period_bound_existing_improvements(self):
        root = Path(self.tmp.name) / 'seo'
        root.mkdir()
        (root / 'backlog.json').write_text('legacy backlog')
        (root / 'experiments.json').write_text('legacy experiments')
        self.config['seoStateRoot'] = str(root)
        analytics = {'schemaVersion': 1, 'status': 'ok', 'collectedAt': datetime.now(JST).isoformat(),
            'evidence': {'current': {'startDate': '2026-10-01', 'endDate': '2026-10-28',
                'dateBasis': 'America/Los_Angeles', 'siteUrl': 'https://camp-gear-lab.com/',
                'country': 'jpn', 'searchType': 'web', 'summary': {'clicks': 3}},
                'previous': None, 'ga4': None},
            'opportunities': [{'action': 'improve_existing', 'url': 'https://camp-gear-lab.com/articles/a'}],
            'uncertainty': ['Seasonality unverified'], 'provenance': {'source': 'sanitized metrics'}}
        context = dict(products=[], articles=[], queuedThemes=[], instructions='', clicks=[])
        with patch.object(self.runtime.analytics, 'load_context', return_value=analytics):
            researched = self.runtime._research_context(context)
        self.assertEqual(researched['analytics'], analytics)
        self.assertIn('not become a new duplicate article', researched['instructions'])
        self.assertIn('not seasonal-demand evidence', researched['instructions'])
        private = self.runtime.root / 'analytics/improvements/latest.json'
        exported = root / 'editorial-insights/latest.json'
        self.assertEqual(json.loads(private.read_text()), json.loads(exported.read_text()))
        queue = json.loads(exported.read_text())
        self.assertEqual(queue['evidence'], analytics['evidence'])
        self.assertEqual(queue['status'], 'ok')
        self.assertEqual((root / 'backlog.json').read_text(), 'legacy backlog')
        self.assertEqual((root / 'experiments.json').read_text(), 'legacy experiments')
        with patch.object(self.runtime.analytics, 'load_context', return_value=dict(analytics,
                status='unavailable', collectedAt=None, opportunities=[])):
            self.runtime._analytics_context()
        self.assertEqual(json.loads(exported.read_text())['status'], 'unavailable')
        self.assertEqual(json.loads(exported.read_text())['opportunities'], [])

    def test_report_failure_is_visible_without_changing_approval_or_publication(self):
        self.config.update(generationEnabled=False, publicationEnabled=False, reportsEnabled=True)
        before = self.runtime.ledger.list_jobs()
        with patch.object(self.runtime.reporter, 'tick', return_value=[
                {'kind': 'weekly', 'status': 'requires_reconciliation'}]) as report:
            result = self.runtime.tick()
        self.assertEqual(result['status'], 'attention')
        self.assertTrue(result['reportAttention'])
        report.assert_called_once()
        self.assertEqual(self.runtime.ledger.list_jobs(), before)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.slack.deliveries, [])

    def test_reports_disabled_default_and_tick_due_receipts_prevent_repeat(self):
        self.config.update(generationEnabled=False, publicationEnabled=False)
        with patch.object(self.runtime.reporter, 'tick') as report:
            self.runtime.tick()
            report.assert_not_called()
        self.config['reportsEnabled'] = True
        self.runtime.reporter.config['reportsEnabled'] = True
        # Thu 20 JST, also after this month's day-5 slot. Monthly collector is
        # stubbed, never a provider call; unavailable data is a warning only.
        now = datetime(2026, 11, 12, 20, tzinfo=JST)
        with patch('runtime.datetime', wraps=datetime) as clock, patch.object(self.slack, 'notice',
                return_value={'verified': True, 'message_ts': '1793700000.123456'}) as send:
            clock.now.return_value = now
            self.runtime.tick()
            self.runtime.tick()
        self.assertEqual(send.call_count, 3)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.slack.deliveries, [])
        self.assertFalse(list((self.runtime.root / 'deliveries').glob('*')))

    def test_candidate_correction_keeps_id_week_slot_and_event(self):
        job = self.runtime.ledger.create_candidate({'slug': 'correction', 'title': '実測'})
        fixed = self.runtime.ledger.revise_candidate(job['id'], '仕様の調査候補', '実測は未実施')
        self.assertEqual(job['week'], fixed['week'])
        self.assertEqual(job['id'], fixed['id'])
        self.assertEqual(1, len(self.runtime.ledger.list_jobs()))
        self.runtime.ledger.save_bundle(job['id'], bundle())
        with self.assertRaises(ValueError):
            self.runtime.ledger.revise_candidate(job['id'], '別内容', '勝手な変更')

    def auto_social_job(self):
        source = bundle()
        source['images'][0].update(sha256='a' * 64, size=10)
        with patch.object(self.models, 'draft', return_value=source):
            job = self.published_job()
        self.config.update(targetAccountId='123', socialPostingEnabled=False)
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        self.approve(job)
        self.runtime.consume()
        return self.runtime.ledger.get_job(job['id'])

    @staticmethod
    def social_receipt(job):
        proposal = job['social']['proposal']
        return dict(verified=True, status='verified', fingerprint=job['social']['revision'], accountId='123',
            mainId='111', replyId='222', readback={
                'main': dict(verified=True, id='111', authorId='123', text=proposal['text'],
                             mediaKeys=['3_333'], replyTo=None),
                'reply': dict(verified=True, id='222', authorId='123', text=proposal['replyText'],
                              mediaKeys=[], replyTo='111'),
                'media': {'verified': True, 'items': [{'mediaId': '333', 'mediaKey': '3_333', 'sha256': 'a' * 64}]}})

    def test_auto_mode_account_are_assigned_before_review_not_model_metadata(self):
        job = self.published_job()
        self.config['targetAccountId'] = '123'
        with patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.make_social(job)
        proposal = review.call_args.args[0]['proposal']
        self.assertEqual(proposal['deliveryMode'], 'auto_x')
        self.assertEqual(proposal['targetAccountId'], '123')
        saved = self.runtime.ledger.get_job(job['id'])['social']
        self.assertEqual(saved['revision'], __import__('ledger').fingerprint(proposal))
        self.assertEqual(saved['review']['fingerprint'], saved['revision'])

    def test_disabled_auto_approval_waits_auth_without_handoff_notice_or_publisher(self):
        job = self.auto_social_job()
        before = copy.deepcopy(job['social']['approval'])
        with patch.object(self.runtime, 'publish_social') as publish:
            notices = len(self.slack.notices)
            for _ in range(2):
                result = self.runtime.tick()
                self.assertTrue(any(r.get('status') == 'waiting_auth' and r.get('reason') == 'social_posting_disabled'
                                    for r in result['results']))
            publish.assert_not_called()
        self.assertEqual(len(self.slack.notices), notices)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['social']['approval'], before)
        self.assertFalse((self.runtime.root / 'social-outbox').exists())
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_approved')

    def test_legacy_manual_approval_never_autoposts_or_makes_manual_handoff_from_tick(self):
        job = self.published_job()
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        self.approve(job)
        self.runtime.consume()
        self.config.update(targetAccountId='123', socialPostingEnabled=True)
        with patch.object(self.runtime, 'publish_social') as publish:
            result = self.runtime.tick()
            publish.assert_not_called()
        self.assertTrue(any(r.get('reason') == 'legacy_social_requires_mode_migration' for r in result['results']))
        self.assertFalse((self.runtime.root / 'social-outbox').exists())

    def test_runtime_migration_requires_fixed_target_no_model_call_or_send(self):
        job = self.published_job()
        self.runtime.make_social(job)
        self.config['targetAccountId'] = '123'
        before_deliveries = len(self.slack.deliveries)
        with patch.object(self.models, 'review') as review:
            with self.assertRaisesRegex(ValueError, 'social_target_mismatch'):
                self.runtime.enable_social_autopost(job['id'], '999')
            migrated = self.runtime.enable_social_autopost(job['id'], '123')
            review.assert_not_called()
        self.assertEqual(migrated['stage'], 'social_review')
        self.assertEqual(len(self.slack.deliveries), before_deliveries)
        self.assertIsNone(migrated['social']['approval'])

    def test_x_success_is_recorded_once_and_health_contains_verified_urls(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class Publisher:
            calls = 0
            def publish(inner, current):
                inner.calls += 1
                return self.social_receipt(current)
        publisher = Publisher()
        self.runtime.social_publisher = publisher
        with patch.object(self.slack, 'notice', return_value={'verified': True, 'message_ts': '1793700000.123456'}) as notify:
            first = self.runtime.tick()
            self.runtime.tick()
        self.assertEqual(publisher.calls, 1)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_posted')
        social = next(j for j in first['articles'] if j['id'] == job['id'])['social']
        self.assertEqual(social['publication']['mainUrl'], 'https://x.com/i/web/status/111')
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM effects WHERE kind='social'").fetchone()[0], 0)

    def test_crash_after_x_success_before_ledger_resumes_publisher_journal(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class JournalPublisher:
            calls = 0
            writes = 0
            receipt = None
            def publish(inner, current):
                inner.calls += 1
                if inner.receipt is None:
                    inner.writes += 1
                    inner.receipt = self.social_receipt(current)
                return copy.deepcopy(inner.receipt)
        publisher = JournalPublisher()
        self.runtime.social_publisher = publisher
        with patch.object(self.runtime.ledger, 'record_social_publication', side_effect=RuntimeError('local crash')):
            self.runtime.tick()
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_approved')
        with patch.object(self.slack, 'notice', return_value={'verified': True, 'message_ts': '1793700000.123456'}):
            self.runtime.tick()
        self.assertEqual(publisher.calls, 2)
        self.assertEqual(publisher.writes, 1)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_posted')

    def test_posted_notification_unknown_does_not_repost_x_or_resend_notice(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class Publisher:
            calls = 0
            def publish(inner, current):
                inner.calls += 1
                return self.social_receipt(current)
        publisher = Publisher()
        self.runtime.social_publisher = publisher
        sent = []
        def notice(text):
            if text.startswith('【X投稿確認済み】'):
                sent.append(text)
                raise TimeoutError('Slack result unknown')
            return {'verified': True, 'message_ts': '1793700000.123456'}
        with patch.object(self.slack, 'notice', side_effect=notice):
            for _ in range(3):
                self.runtime.tick()
        self.assertEqual(len(sent), 1)
        self.assertEqual(publisher.calls, 1)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_posted')
        marker = self.runtime.root / 'social-posted-notices' / (job['social']['revision'] + '.json')
        self.assertEqual(json.loads(marker.read_text())['status'], 'in_flight')

    def test_auth_failure_and_changed_target_never_record_social_publication(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class Publisher:
            calls = 0
            def publish(inner, current):
                inner.calls += 1
                raise ValueError('x_account_mismatch')
        publisher = Publisher()
        self.runtime.social_publisher = publisher
        self.config['targetAccountId'] = '999'
        with self.assertRaises(ValueError):
            self.runtime.publish_social(job)
        self.assertEqual(publisher.calls, 0)
        self.config['targetAccountId'] = '123'
        with self.assertRaisesRegex(ValueError, 'x_account_mismatch'):
            self.runtime.publish_social(job)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_approved')
        self.assertNotIn('publication', self.runtime.ledger.get_job(job['id'])['social'])


if __name__ == '__main__':
    unittest.main()
