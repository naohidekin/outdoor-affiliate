"""Mixed-topic deterministic contracts; no network, model, DB or publication."""
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ledger import fingerprint, valid_review
from quality import inspect_bundle
from topic_selection import (JST, NonproductSourceHold, bind_nonproduct_theme, collect_primary_sources,
                             editorial_context, editorial_signals,
                             nonproduct_affiliate_review, reverify_bound_public_sources, select_proposals,
                             validate_nonproduct_bundle, validate_proposals)


NOW = datetime(2026, 11, 20, 10, tzinfo=JST)


def feed():
    def source(source_id, url, excerpt, scope):
        raw = {'id': source_id, 'url': url, 'canonicalUrl': url,
               'checkedAt': NOW.isoformat(), 'httpStatus': 200, 'excerpt': excerpt,
               'claimScope': scope}
        canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return {**raw, 'id': 'public:' + source_id, 'title': source_id,
                'kind': 'public-primary', 'scope': scope,
                'receiptSha256': hashlib.sha256(canonical.encode()).hexdigest(),
                'excerptSha256': hashlib.sha256(excerpt.encode()).hexdigest()}
    sources = [source('coleman-care', 'https://www.coleman.co.jp/customersupport/faq/',
                      '十分に乾燥させてから保管します。', 'tent-care'),
               source('montbell-layering', 'https://www.montbell.jp/generalpage/disp.php?id=507',
                      'レイヤリングは肌着、中間着、上着を重ねる考え方です。',
                      'layering-concept-only')]
    return {'status': 'verified', 'sources': sources, 'illustrations': [], 'reason': None}


FACET_KEYS = ('garments', 'brands', 'problems', 'seasons', 'intents', 'gearTypes')


def topic_facets(text):
    text = str(text).casefold()
    facets = {key: [] for key in FACET_KEYS}
    mappings = {
        'garments': [('base_layer', ('重ね着', 'ベースレイヤー', 'ウェア'))],
        'brands': [('coleman', ('コールマン', 'coleman')),
                   ('montbell', ('モンベル', 'montbell')),
                   ('thermos', ('サーモス', 'thermos'))],
        'problems': [('care', ('乾燥', '乾かす')), ('washing', ('洗濯', '洗う')),
                     ('compatibility', ('部品', 'パッキン', '適合'))],
        'seasons': [('autumn', ('秋',)), ('winter', ('冬',))],
        'intents': [('comparison', ('比較', ' vs ', '違い')),
                    ('care', ('方法', '手順', 'どう')), ('parts_lookup', ('部品', 'パッキン', '適合'))],
        'gearTypes': [('tent', ('テント',)), ('sleeping_bag', ('寝袋', 'シュラフ')),
                      ('bottle', ('水筒', 'ボトル')), ('chair', ('チェア',))],
    }
    for key, choices in mappings.items():
        facets[key] = [value for value, words in choices if any(word in text for word in words)]
    return facets


def demand_signal(signal_id, facets, *, query_count=3, clicks=5, impressions=40):
    value = {key: list(facets.get(key, [])) for key in FACET_KEYS}
    return {'id': signal_id, 'kind': 'own_site_query_demand', 'facets': value,
            'queryCount': query_count,
            'metrics': {'clicks': clicks, 'impressions': impressions,
                        'ctr': clicks / impressions if impressions else 0,
                        'averagePosition': 8.0},
            'period': {'startDate': '2026-10-23', 'endDate': '2026-11-19',
                       'dateBasis': 'America/Los_Angeles'},
            'coverage': {'status': 'partial', 'scope': 'own_site_search_sample'},
            'previous': None,
            'limitations': 'own-site search sample; not market search volume'}


def signals():
    return [
        demand_signal('demand:tent', topic_facets('テントを乾燥する手順')),
        demand_signal('demand:layer', topic_facets('ウェアの重ね着を確認する方法')),
        *[{'id': item['id'], 'kind': 'public_reference'} for item in feed()['sources']],
    ]


def choose(proposals, *, evidence=None, existing=None, queued=None, source_feed=None, limit=3):
    return select_proposals(
        proposals, signals=evidence if evidence is not None else signals(),
        existing=existing or [], queued=queued or [], feed=source_feed or feed(),
        limit=limit, classify_topic=topic_facets)


def proposal(slug, question, priority=80, **updates):
    value = {'slug': slug, 'title': question, 'categoryId': 'camp-howto', 'productIds': [],
             'topicType': 'knowhow', 'query': question, 'readerQuestion': question,
             'intent': 'informational', 'outline': ['準備', '手順', '保管'], 'priority': priority,
             'overlapRationale': '既存とは別の読者課題', 'selectionReason': 'own-site evidence',
             'sourceIds': ['demand:tent', 'public:coleman-care'], 'proposedAction': 'new',
             'overlapArticleIds': [], 'needsStatus': 'not_applicable'}
    value.update(updates)
    return value


def nonproduct_bundle():
    theme = bind_nonproduct_theme(proposal('tent-dry', 'テントを乾かす手順は？'), feed())
    image_bytes = b'fixture-image'
    image = {'id': 'illustration:fixture', 'role': 'eyecatch',
             'ownership': 'owned_editorial_illustration', 'depictsRealProduct': False,
             'referenceIds': ['public:coleman-care'], 'compositionSha256': 'a' * 64,
             'url': 'https://db.example.com/card.png', 'finalUrl': 'https://db.example.com/card.png',
             'sha256': hashlib.sha256(image_bytes).hexdigest(), 'size': len(image_bytes),
             'contentType': 'image/png', 'width': 1200, 'height': 630, 'verified': True,
             'checkedAt': NOW.isoformat(), 'rendererEvidence': {'version': 'editorial-illustration-v1'}}
    context = editorial_context(theme, [image])
    return {'article': {'id': 'a', 'slug': 'tent-dry', 'title': 'テントの乾かし方',
                        'content': '## 準備\n調査記事です。\n[設営](/articles/setup) [保管](/articles/store)',
                        'excerpt': 'テントを乾かして保管する手順を一次情報から整理します。',
                        'metaDescription': 'テントを乾かして保管する基本手順を一次情報に基づいて分かりやすく整理します。',
                        'faqs': [{'question': f'質問{i}', 'answer': '一次情報を確認します。'} for i in range(3)],
                        'productIds': [], 'categoryId': 'camp-howto', 'author': 'ギア男',
                        'eyecatch': image['url'], 'generationMeta': {'editorialContext': context}},
            'products': [], 'images': [image],
            'references': copy.deepcopy(theme['nonProductContract']['references']),
            'brief': {'purpose': '手順整理', 'reader': '初心者', 'conclusion': '乾燥して保管',
                      'headings': ['準備'], 'facts': [], 'numbers': [], 'links': [],
                      'requiredExpressions': [], 'protected': [], 'style': 'ですます',
                      'length': '3000〜5000字', 'cta': '一次情報を確認', 'format': 'guide'},
            'commercialRoute': {'status': 'not_applicable', 'reason': 'verified_nonproduct_article',
                                'verifiedBy': 'deterministic_contract_v1'}}


class TopicSelectionTests(unittest.TestCase):
    def test_unrelated_informational_topics_remain_eligible(self):
        proposals = [proposal('tent-dry', 'テントを乾かす手順は？', 90),
                     proposal('layer-order', '重ね着の順番は？', 89,
                              outline=['肌着', '中間着', '上着'],
                              sourceIds=['demand:layer', 'public:montbell-layering'])]
        selected = choose(proposals, limit=2)
        self.assertEqual(['tent-dry', 'layer-order'], [item['slug'] for item in selected['selected']])

    def test_relevant_measured_need_beats_unrelated_priority_100(self):
        chair = demand_signal('demand:chair', topic_facets('チェアの選び方'),
                              query_count=40, clicks=100, impressions=1000)
        evidence = [chair, *signals()]
        unrelated = proposal('priority-only', 'テントを乾かす手順は？', 100,
                             sourceIds=['demand:chair', 'public:coleman-care'])
        relevant = proposal('relevant-lower', 'テントを乾かす手順は？', 20)

        result = choose([unrelated, relevant], evidence=evidence, limit=1)

        self.assertEqual(['relevant-lower'], [item['slug'] for item in result['selected']])
        first = next(row for row in result['decisions']
                     if row['proposal']['slug'] == 'priority-only')
        self.assertEqual(('rejected', 'relevant_search_need_required', 'unknown'),
                         (first['status'], first['reason'], first['needBasis']))

    def test_verified_seasonal_apparel_preference_precedes_observed_strength_and_ai_priority(self):
        general = demand_signal('demand:general-tent', topic_facets(
            'テントを乾燥する手順'), query_count=100, clicks=100, impressions=1000)
        preferred = demand_signal('demand:autumn-layer', topic_facets(
            '秋のウェア重ね着を確認する方法'), query_count=1, clicks=1, impressions=10)
        high_priority = proposal(
            'general-high-count', 'テントを乾かす手順は？', 100,
            sourceIds=['demand:general-tent', 'public:coleman-care'])
        owner_preferred = proposal(
            'autumn-apparel', '秋のウェア重ね着を確認する方法は？', 1,
            categoryId='wear', productIds=['wear-one'], topicType='seasonal_problem',
            query='秋 ウェア 重ね着', readerQuestion='秋の重ね着をどう確認する？',
            sourceIds=['demand:autumn-layer'], needsStatus='seasonal_hypothesis')

        result = choose([high_priority, owner_preferred],
                        evidence=[general, preferred, signals()[-2]], limit=1)

        self.assertEqual(['autumn-apparel'], [item['slug'] for item in result['selected']])
        chosen = next(row for row in result['decisions']
                      if row['proposal']['slug'] == 'autumn-apparel')
        self.assertEqual(['seasonal', 'apparel'],
                         chosen['scoreRationale']['preferenceReasons'])
        self.assertEqual(1, chosen['scoreRationale']['aiPriority'])

    def test_hidden_faq_duplicate_routes_exact_existing_update(self):
        existing = [{
            'id': 'article-hidden-answer', 'slug': 'tent-maintenance',
            'title': 'テント撤収後の手入れ', 'categoryId': 'camp-howto',
            'updatedAt': '2026-11-01T10:00:00+09:00', 'contentSha256': 'b' * 64,
            'headings': ['撤収', '乾燥'], 'conclusion': '乾かして保管します。',
            'faqQuestions': [f'別の質問{i}' for i in range(8)] + ['テントを乾かす手順は？'],
            'sections': [{'heading': '保管', 'text': '乾燥後に収納します。'}],
        }]

        result = choose([proposal('hidden-faq', 'テントを乾かす手順は？')],
                        existing=existing, limit=1)

        decision = result['decisions'][0]
        self.assertEqual(('existing_update', 'article-hidden-answer', 'tent-maintenance'),
                         (decision['status'], decision['existingArticleId'],
                          decision['existingSlug']))
        self.assertEqual('rich_existing_content_overlap', decision['reason'])
        self.assertEqual(('2026-11-01T10:00:00+09:00', 'b' * 64),
                         (decision['baseVersion'], decision['contentHash']))

    def test_duplicate_covered_only_in_faq_answer_routes_update(self):
        existing = [{
            'id': 'article-faq-answer', 'slug': 'tent-faq-answer',
            'title': 'テント撤収後の確認', 'categoryId': 'camp-howto',
            'headings': ['よくある確認'], 'faqQuestions': ['帰宅後はどうする？'],
            'faqs': [{'question': '帰宅後はどうする？',
                      'answer': 'テントを乾かす手順は？を整理し、保管前に確認します。'}],
            'conclusion': '', 'sections': [], 'bodyCoverage': 'full',
            'contentSha256': 'c' * 64, 'faqsSha256': 'd' * 64,
        }]

        result = choose([proposal('faq-answer-duplicate', 'テントを乾かす手順は？')],
                        existing=existing, limit=1)

        self.assertEqual('existing_update', result['decisions'][0]['status'])
        self.assertEqual('full', result['decisions'][0]['existingCoverage']['bodyCoverage'])

    def test_generic_faq_in_other_category_does_not_create_false_duplicate(self):
        existing = [{
            'id': 'article-tent-generic', 'slug': 'tent-generic', 'title': 'テントの比較',
            'categoryId': 'tent', 'headings': [], 'faqQuestions': ['何が違う？'],
            'faqs': [{'question': '何が違う？', 'answer': 'テントの仕様を比較します。'}],
            'conclusion': '', 'sections': [],
        }]
        item = proposal('wear-comparison', '秋冬ウェアはコールマンとモンベルでどう違う？',
                        categoryId='wear', productIds=['coleman-a', 'montbell-b'],
                        topicType='product', query='コールマン モンベル 秋冬ウェア 比較',
                        readerQuestion='何が違う？', sourceIds=['demand:comparison'])
        demand = demand_signal('demand:comparison', topic_facets(
            '秋冬ウェア コールマン vs モンベル 比較'))

        result = choose([item], evidence=[demand], existing=existing, limit=1)

        self.assertEqual(['wear-comparison'], [row['slug'] for row in result['selected']])

    def test_two_brand_comparison_is_not_duplicate_of_one_brand_generic_faq(self):
        existing = [{
            'id': 'article-one-brand', 'slug': 'coleman-wear',
            'title': 'コールマンの秋冬ウェア', 'categoryId': 'wear',
            'headings': [], 'faqQuestions': ['何が違う？'],
            'faqs': [{'question': '何が違う？', 'answer': 'コールマンの仕様を確認します。'}],
            'conclusion': '', 'sections': [],
        }]
        item = proposal('two-brand-distinct', '秋冬ウェアはコールマンとモンベルでどう違う？',
                        categoryId='wear', productIds=['coleman-a', 'montbell-b'],
                        topicType='product', query='コールマン モンベル 秋冬ウェア 比較',
                        readerQuestion='何が違う？', sourceIds=['demand:comparison'])
        demand = demand_signal('demand:comparison', topic_facets(
            '秋冬ウェア コールマン vs モンベル 比較'))

        result = choose([item], evidence=[demand], existing=existing, limit=1)

        self.assertEqual(['two-brand-distinct'], [row['slug'] for row in result['selected']])

    def test_narrow_part_lookup_without_exact_target_holds(self):
        parts = demand_signal('demand:parts', topic_facets(
            'サーモス水筒のパッキン部品の適合を確認する方法'))
        item = proposal(
            'thermos-one-part', 'サーモス水筒のパッキン部品だけを確認する方法',
            categoryId='tumbler', productIds=['bottle-one'], topicType='product',
            sourceIds=['demand:parts'])

        result = choose([item], evidence=[parts], limit=1)

        self.assertEqual([], result['selected'])
        self.assertEqual(('hold', 'narrow_topic_target_unknown'),
                         (result['decisions'][0]['status'], result['decisions'][0]['reason']))
        self.assertNotIn('existingArticleId', result['decisions'][0])

    def test_narrow_label_never_routes_across_explicit_garment_contradiction(self):
        from search_demand import classify_topic
        demand = demand_signal('demand:fleece-label', classify_topic(
            'フリースの洗濯表示を確認する'))
        item = proposal(
            'fleece-wash-label', 'フリースの洗濯表示を確認するには？',
            categoryId='wear', productIds=['fleece-one'], topicType='product',
            query='フリース 洗濯表示', readerQuestion='フリースのラベルをどう読む？',
            sourceIds=['demand:fleece-label'])
        existing = [{
            'id': 'article-down-label', 'slug': 'down-wash-label',
            'title': 'ダウンの洗濯表示を確認する方法', 'categoryId': 'wear',
            'headings': ['ダウンのケアラベル'], 'faqQuestions': ['ラベルはどう読む？'],
            'faqs': [], 'conclusion': 'ダウンの表示を確認します。', 'sections': [],
        }]

        result = select_proposals([item], signals=[demand], existing=existing,
                                  queued=[], feed=feed(), limit=1)

        self.assertEqual(('hold', 'narrow_topic_target_unknown'),
                         (result['decisions'][0]['status'], result['decisions'][0]['reason']))
        self.assertNotIn('existingArticleId', result['decisions'][0])

    def test_distinct_two_brand_comparison_remains_new_candidate(self):
        comparison = demand_signal('demand:comparison', topic_facets(
            '秋冬ウェア コールマン vs モンベル 比較'))
        existing = [{
            'id': 'article-coleman-wear', 'slug': 'coleman-base-layer',
            'title': 'コールマンのベースレイヤー選び', 'categoryId': 'wear',
            'headings': ['サイズの確認'], 'faqQuestions': [],
            'conclusion': 'コールマンの仕様を確認します。', 'sections': [],
        }]
        item = proposal(
            'coleman-montbell-compare', '秋冬ウェアはコールマンとモンベルでどう違う？',
            30, categoryId='wear', productIds=['coleman-a', 'montbell-b'],
            topicType='product', query='コールマン モンベル 秋冬ウェア 比較',
            readerQuestion='秋冬のベースレイヤーを2ブランドで比較したい',
            sourceIds=['demand:comparison'])

        result = choose([item], evidence=[comparison], existing=existing, limit=1)

        self.assertEqual(['coleman-montbell-compare'],
                         [row['slug'] for row in result['selected']])
        decision = result['decisions'][0]
        self.assertEqual('direct_matched_query_group', decision['needBasis'])
        self.assertIn('brand_comparison', decision['scoreRationale']['preferenceReasons'])

    def test_unrelated_high_traffic_page_proxy_is_not_demand(self):
        page = {'id': 'gsc:chair-high', 'kind': 'gsc',
                'locator': 'https://camp-gear-lab.com/articles/chair-guide',
                'metrics': {'clicks': 500, 'impressions': 5000, 'ctr': .1,
                            'averagePosition': 2}}
        existing = [{'id': 'article-chair', 'slug': 'chair-guide',
                     'url': page['locator'], 'title': 'キャンプチェアの選び方',
                     'categoryId': 'chair', 'headings': [], 'faqQuestions': [],
                     'conclusion': '', 'sections': []}]
        item = proposal('tent-from-chair', 'テントを乾かす手順は？', 100,
                        sourceIds=['gsc:chair-high', 'public:coleman-care'])

        result = choose([item], evidence=[page, signals()[-2]], existing=existing, limit=1)

        self.assertEqual('relevant_search_need_required', result['decisions'][0]['reason'])
        self.assertEqual('unknown', result['decisions'][0]['needBasis'])

    def test_measured_change_requires_the_change_page_itself_to_match(self):
        change = {'id': 'gsc-change:chair', 'kind': 'own_site_gsc_period_comparison',
                  'locator': 'https://camp-gear-lab.com/articles/chair-guide',
                  'metrics': {'impressions': {'current': 100, 'previous': 80}}}
        existing = [{'id': 'article-chair', 'slug': 'chair-guide',
                     'title': 'キャンプチェアの選び方', 'categoryId': 'chair',
                     'headings': [], 'faqQuestions': [], 'conclusion': '', 'sections': []}]
        item = proposal('autumn-tent-dry', '秋にテントを乾かす手順は？',
                        topicType='seasonal_problem', needsStatus='measured_change',
                        sourceIds=['demand:autumn-tent', 'gsc-change:chair', 'public:coleman-care'])
        demand = demand_signal('demand:autumn-tent', topic_facets('秋にテントを乾燥する手順'))

        result = choose([item], evidence=[demand, change, signals()[-2]],
                        existing=existing, limit=1)

        self.assertEqual('measured_change_evidence_required', result['decisions'][0]['reason'])
        self.assertEqual('direct_matched_query_group', result['decisions'][0]['needBasis'])

    def test_search_demand_export_never_includes_raw_query_or_fake_zero_trend(self):
        facets = topic_facets('テントを乾燥する手順')
        analytics = {'evidence': {'current': {
            'status': 'ok', 'startDate': '2026-10-23', 'endDate': '2026-11-19',
            'dateBasis': 'America/Los_Angeles', 'pages': [],
            'searchDemand': {'status': 'available',
                'period': {'startDate': '2026-10-23', 'endDate': '2026-11-19',
                           'dateBasis': 'America/Los_Angeles'},
                'coverage': {'status': 'partial', 'scope': 'own_site_search_sample',
                             'rawQuery': 'raw private query'},
                'groups': [{**demand_signal('gsc-demand:' + 'a' * 64, facets),
                            'querySamples': ['raw private query']}]},
        }, 'previous': {
            'status': 'ok', 'startDate': '2026-09-25', 'endDate': '2026-10-22',
            'dateBasis': 'America/Los_Angeles', 'pages': [],
            'searchDemand': {'status': 'available',
                'period': {'startDate': '2026-09-25', 'endDate': '2026-10-22',
                           'dateBasis': 'America/Los_Angeles'},
                'coverage': {'status': 'partial', 'scope': 'own_site_search_sample'},
                'groups': []}}, 'ga4': None}}

        exported = [item for item in editorial_signals(analytics, feed())
                    if item['kind'] == 'own_site_query_demand']

        self.assertEqual(1, len(exported))
        self.assertIsNone(exported[0]['previous'])
        self.assertNotIn('trend', exported[0])
        self.assertNotIn('raw private query', json.dumps(exported, ensure_ascii=False))

    def test_real_search_projection_keeps_pacific_period_and_exports_group(self):
        from search_demand import project_search_demand
        period = {'startDate': '2026-10-23', 'endDate': '2026-11-19',
                  'dateBasis': 'America/Los_Angeles'}
        demand = project_search_demand([
            {'query': '冬 フリース 比較 PRIVATE_QUERY_CANARY', 'clicks': 4,
             'impressions': 100, 'ctr': .04, 'position': 8}], period)
        analytics = {'evidence': {'current': {
            **period, 'status': 'ok', 'pages': [], 'searchDemand': demand}}}

        exported = [item for item in editorial_signals(analytics, feed())
                    if item['kind'] == 'own_site_query_demand']

        self.assertEqual(1, len(exported))
        self.assertEqual(period, exported[0]['period'])
        self.assertNotIn('PRIVATE_QUERY_CANARY', json.dumps(exported, ensure_ascii=False))

    def test_only_same_window_same_facets_get_previous_demand_measurement(self):
        facets = topic_facets('テントを乾燥する手順')
        current = demand_signal('gsc-demand:' + 'a' * 64, facets)
        current['facetId'] = 'facet-one'
        previous = demand_signal('gsc-demand:' + 'b' * 64, facets, query_count=2,
                                 clicks=1, impressions=10)
        previous['facetId'] = 'facet-one'
        analytics = {'evidence': {
            'current': {'status': 'ok', 'startDate': '2026-10-23', 'endDate': '2026-11-19',
                        'dateBasis': 'America/Los_Angeles', 'pages': [],
                        'searchDemand': {'status': 'available', 'period': current['period'],
                                         'coverage': current['coverage'], 'groups': [current]}},
            'previous': {'status': 'ok', 'startDate': '2026-09-25', 'endDate': '2026-10-22',
                         'dateBasis': 'America/Los_Angeles', 'pages': [],
                         'searchDemand': {'status': 'available', 'period': previous['period'],
                                          'coverage': previous['coverage'], 'groups': [previous]}},
            'ga4': None}}
        analytics['evidence']['previous']['searchDemand']['period'] = {
            'startDate': '2026-09-25', 'endDate': '2026-10-22',
            'dateBasis': 'America/Los_Angeles'}

        exported = next(item for item in editorial_signals(analytics, feed())
                        if item['kind'] == 'own_site_query_demand')

        self.assertEqual(2, exported['previous']['queryCount'])
        self.assertEqual(10, exported['previous']['metrics']['impressions'])

        analytics['evidence']['previous']['searchDemand']['period']['dateBasis'] = 'Asia/Tokyo'
        mismatched = next(item for item in editorial_signals(analytics, feed())
                          if item['kind'] == 'own_site_query_demand')
        self.assertIsNone(mismatched['previous'])

    def test_same_brand_with_conflicting_gear_is_not_relevant_demand(self):
        chair = demand_signal('demand:coleman-chair', topic_facets('コールマン チェアの選び方'))
        item = proposal('coleman-tent-dry', 'コールマンのテントを乾かす手順は？',
                        sourceIds=['demand:coleman-chair', 'public:coleman-care'])

        result = choose([item], evidence=[chair, signals()[-2]], limit=1)

        self.assertEqual(('rejected', 'relevant_search_need_required', 'unknown'),
                         (result['decisions'][0]['status'], result['decisions'][0]['reason'],
                          result['decisions'][0]['needBasis']))

    def test_two_brand_comparison_cannot_claim_single_brand_demand(self):
        single = demand_signal('demand:coleman-wear', topic_facets('コールマン 秋冬ウェア 比較'))
        item = proposal(
            'two-brand-with-one-demand', '秋冬ウェアはコールマンとモンベルでどう違う？',
            categoryId='wear', productIds=['coleman-a', 'montbell-b'], topicType='product',
            query='コールマン モンベル 秋冬ウェア 比較',
            readerQuestion='秋冬ウェアをコールマンとモンベルで比較したい',
            sourceIds=['demand:coleman-wear'])

        result = choose([item], evidence=[single], limit=1)

        self.assertEqual('relevant_search_need_required', result['decisions'][0]['reason'])
        self.assertEqual('unknown', result['decisions'][0]['needBasis'])

    def test_empty_demand_group_is_unknown_not_zero_demand(self):
        empty = demand_signal('demand:empty', topic_facets('テントを乾燥する手順'),
                              query_count=0, clicks=0, impressions=0)
        item = proposal('empty-demand', 'テントを乾かす手順は？',
                        sourceIds=['demand:empty', 'public:coleman-care'])

        result = choose([item], evidence=[empty, signals()[-2]], limit=1)

        self.assertEqual('relevant_search_need_required', result['decisions'][0]['reason'])
        self.assertEqual('unknown', result['decisions'][0]['needBasis'])

    def test_query_count_without_positive_clicks_or_impressions_is_unknown(self):
        from search_demand import classify_topic
        missing = {
            'id': 'demand:unmeasured', 'kind': 'own_site_query_demand',
            'facets': classify_topic('テントの手入れ'), 'queryCount': 1,
            'metrics': {'clicks': None, 'impressions': None, 'ctr': None,
                        'averagePosition': None},
        }
        item = proposal('unmeasured-tent-care', 'テントを手入れするには？',
                        sourceIds=['demand:unmeasured', 'public:coleman-care'])

        result = select_proposals(
            [item], signals=[missing, {'id': 'public:coleman-care',
                                      'kind': 'public_reference'}],
            existing=[], queued=[], feed=feed(), limit=1)

        self.assertEqual('relevant_search_need_required', result['decisions'][0]['reason'])
        self.assertEqual('unknown', result['decisions'][0]['needBasis'])

    def test_pole_joint_cleaning_without_covered_update_target_holds(self):
        item = proposal('pole-joint-clean', 'テントポールのジョイントを掃除するには？')

        result = choose([item], limit=1)

        self.assertEqual(('hold', 'narrow_topic_target_unknown'),
                         (result['decisions'][0]['status'], result['decisions'][0]['reason']))

    def test_structured_semantic_overlap_routes_private_update(self):
        existing = [{'id': 'article-tent-care', 'slug': 'tent-maintenance',
                     'title': 'テント撤収後の手入れ', 'readerQuestion': '撤収後の手入れは？'}]
        item = proposal('rainy-tent-care', '雨撤収したテントはどう手入れする？',
                        proposedAction='existing_update', overlapArticleIds=['article-tent-care'])
        result = choose([item], existing=existing, limit=3)
        self.assertEqual([], result['selected'])
        self.assertEqual(('existing_update', 'article-tent-care'),
                         (result['decisions'][0]['status'], result['decisions'][0]['existingArticleId']))

    def test_invalid_earlier_proposal_does_not_block_later_valid_one(self):
        bad = proposal('same-question', 'テントを乾かす手順は？', sourceIds=['unknown'])
        good = proposal('valid-question', 'テントを乾かす手順は？')
        result = choose([bad, good], limit=1)
        self.assertEqual(['valid-question'], [item['slug'] for item in result['selected']])

    def test_regular_pool_with_only_two_qualified_candidates_holds_all_visibly(self):
        items = [proposal('tent-dry', 'テントを乾かす手順は？', 90),
                 proposal('layer-order', '重ね着の順番は？', 89,
                          outline=['肌着', '中間着', '上着'],
                          sourceIds=['demand:layer', 'public:montbell-layering'])]
        result = choose(items, limit=3)
        self.assertEqual('hold', result['status'])
        self.assertEqual([], result['selected'])
        self.assertEqual(2, result['eligibleCount'])
        self.assertEqual(1, result['unfilled'])
        self.assertEqual('insufficient_qualified_period_pool', result['holdReason'])
        self.assertEqual({'hold'}, {row['status'] for row in result['decisions']})

    def test_contract_rejects_unknown_overlap_id(self):
        item = proposal('x-topic', '別の質問', proposedAction='existing_update',
                        overlapArticleIds=['missing'])
        with self.assertRaisesRegex(ValueError, 'proposal_contract'):
            validate_proposals([item], catalog_ids=set(), existing_ids={'known'})

    def test_every_accepted_outline_is_directly_renderable_without_truncation(self):
        accepted = validate_proposals([proposal('renderable', '図解できる質問')],
                                      catalog_ids=set(), existing_ids=set())[0]
        self.assertTrue(3 <= len(accepted['outline']) <= 5)
        self.assertTrue(all(0 < len(text) <= 40 for text in accepted['outline']))
        too_long = proposal('too-long', '長すぎる見出し', outline=['準備', '手順', 'あ' * 41])
        with self.assertRaisesRegex(ValueError, 'proposal_contract'):
            validate_proposals([too_long], catalog_ids=set(), existing_ids=set())

    def test_unknown_category_and_unrenderable_title_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'proposal_contract'):
            validate_proposals([proposal('unknown-category', 'テントを乾かすには？')],
                               catalog_ids=set(), category_ids={'tent'})
        with self.assertRaisesRegex(ValueError, 'proposal_contract'):
            validate_proposals([proposal('long-title', 'テント' * 30)],
                               catalog_ids=set(), category_ids={'camp-howto'})

    def test_mixed_validator_preserves_legacy_unverified_firsthand_title_guard(self):
        banned = ('実測', '実証', '検証済み', '実体験', '愛用', '使って', '使った',
                  '使用歴', 'tested', 'hands.on')
        for index, term in enumerate(banned):
            with self.subTest(term=term), self.assertRaisesRegex(ValueError, 'proposal_contract'):
                validate_proposals([proposal(
                    f'firsthand-{index}', 'テントを乾燥して保管するには？',
                    categoryId='tent', title=term + 'テント乾燥')],
                    catalog_ids=set(), category_ids={'tent'})

    def test_seasonal_problem_with_verified_products_keeps_product_route(self):
        item = proposal('rain-setup', '雨の日の設営で必要な道具は？', topicType='seasonal_problem',
                        productIds=['verified-tarp'], needsStatus='seasonal_hypothesis')
        accepted = validate_proposals([item], catalog_ids={'verified-tarp'}, existing_ids=set())[0]
        self.assertEqual(['verified-tarp'], accepted['productIds'])

    def test_cross_scope_nonproduct_reference_is_rejected(self):
        item = proposal('layering-wrong-source', '重ね着の順番は？',
                        outline=['肌着', '中間着', '上着'])
        result = choose([item], limit=1)
        self.assertEqual('nonproduct_claim_scope_mismatch', result['decisions'][0]['reason'])

    def test_outline_cannot_legitimize_wrong_source_or_expand_uncovered_family(self):
        wrong_source = proposal('layering-care-source', '重ね着の順番は？',
                                outline=['乾燥', '保管', '確認'])
        uncovered_outline = proposal('layering-care-outline', '重ね着の順番は？',
            outline=['肌着', '乾燥と保管', '上着'],
            sourceIds=['demand:layer', 'public:montbell-layering'])
        first = choose([wrong_source], limit=1)
        second = choose([uncovered_outline], limit=1)
        self.assertEqual('nonproduct_claim_scope_mismatch', first['decisions'][0]['reason'])
        self.assertEqual('nonproduct_outline_scope_uncovered', second['decisions'][0]['reason'])

    def test_gsc_comparison_zero_baseline_is_not_infinite_growth(self):
        analytics = {'evidence': {'current': {'status': 'ok', 'startDate': '2026-10-23',
            'endDate': '2026-11-19', 'dateBasis': 'Asia/Tokyo',
            'pages': [{'url': 'https://camp-gear-lab.com/articles/a', 'clicks': 3,
                       'impressions': 20, 'ctr': .15, 'position': 8}]},
            'previous': {'status': 'ok', 'startDate': '2026-09-25', 'endDate': '2026-10-22',
            'dateBasis': 'Asia/Tokyo', 'pages': [{'url': 'https://camp-gear-lab.com/articles/a',
            'clicks': 0, 'impressions': 10, 'ctr': 0, 'position': 10}]}, 'ga4': None}}
        change = next(item for item in editorial_signals(analytics, feed())
                      if item['kind'] == 'own_site_gsc_period_comparison')
        self.assertIsNone(change['metrics']['clicks']['relativeChange'])
        self.assertIn('averagePosition', change['metrics'])
        self.assertNotIn('position', change['metrics'])
        self.assertIn('not market demand', change['limitations'])

    def test_measured_gsc_period_comparison_is_valid_demand_evidence(self):
        item = proposal('gsc-change-topic', 'テント乾燥記事の表示変化をどう改善する？',
                        sourceIds=['gsc-change:one', 'public:coleman-care'])
        measured = [{'id': 'gsc-change:one', 'kind': 'own_site_gsc_period_comparison',
                     'locator': 'https://camp-gear-lab.com/articles/tent-site-guide',
                     'metrics': {'clicks': {'current': 3, 'previous': 1}}},
                    {'id': 'public:coleman-care', 'kind': 'public_reference'}]
        existing = [{'id': 'article-tent-site', 'slug': 'tent-site-guide',
                     'title': 'テントの設営場所を選ぶ', 'categoryId': 'camp-howto',
                     'headings': [], 'faqQuestions': [], 'conclusion': '', 'sections': []}]
        selected = choose([item], evidence=measured, existing=existing, limit=1)
        self.assertEqual(['gsc-change-topic'], [row['slug'] for row in selected['selected']])
        self.assertEqual('related_page_proxy', selected['decisions'][0]['needBasis'])

    def test_primary_source_partial_failure_does_not_claim_full_coverage(self):
        def request(url, _headers):
            if 'snowpeak' in url:
                raise OSError('fixture unavailable')
            text = ('乾燥させてから保管するための十分に長い確認文章です。'
                    if 'coleman' in url else
                    'レイヤリングという考え方を説明するための十分に長い確認文章です。')
            return {'url': url, 'status': 200,
                    'headers': {'content-type': 'text/html; charset=utf-8'},
                    'body': ('<html><p>' + text + '</p></html>').encode()}
        with tempfile.TemporaryDirectory() as root:
            result = collect_primary_sources(request, period='2026-11-20',
                output_path=Path(root) / 'receipt.json', now=NOW)
        self.assertEqual(('partial', 2, 6),
                         (result['status'], len(result['sources']), len(result['sourceFailures'])))

    def test_primary_source_missing_or_non200_status_is_never_treated_as_verified(self):
        def request(url, _headers):
            status = None if 'coleman' in url else 503
            return {'url': url, 'status': status,
                    'headers': {'content-type': 'text/html; charset=utf-8'},
                    'body': '<html><p>乾燥して保管し、レイヤリングも確認します。</p></html>'.encode()}
        with tempfile.TemporaryDirectory() as root:
            result = collect_primary_sources(request, period='2026-11-20',
                output_path=Path(root) / 'receipt.json', now=NOW)
        self.assertEqual('unavailable', result['status'])
        self.assertEqual([], result['sources'])
        self.assertEqual({None, 503}, {item['httpStatus'] for item in result['sourceFailures']})

    def test_noncontiguous_fallback_paragraphs_reverify_exactly_from_same_response(self):
        urls = {
            'coleman': 'https://www.coleman.co.jp/customersupport/faq/',
            'snowpeak': 'https://www.snowpeak.co.jp/contents/campstarterbook/',
            'montbell': 'https://www.montbell.jp/generalpage/disp.php?id=507'}
        snow_parts = (
            '撤収後の道具は十分に乾燥させる手順を確認してください。',
            '収納する前に状態を確かめて適切に保管してください。')
        bodies = {
            urls['coleman']: '<p>テントは汚れを落とし、十分に乾燥させてから収納します。</p>',
            urls['snowpeak']: '<p>' + snow_parts[0] + '</p><aside>別の説明です。</aside><p>' + snow_parts[1] + '</p>',
            urls['montbell']: '<p>レイヤリングは肌着、中間着、上着を重ねる考え方です。</p>'}
        def request(url, _headers):
            return {'url': url, 'status': 200,
                    'headers': {'content-type': 'text/html; charset=utf-8'},
                    'body': ('<html><body>' + bodies[url] + '</body></html>').encode()}
        with tempfile.TemporaryDirectory() as root:
            collected = collect_primary_sources(request, period='2026-11-20',
                output_path=Path(root) / 'receipt.json', now=NOW)
        snow = next(item for item in collected['sources'] if item['id'] == 'public:snowpeak-care')
        self.assertEqual('\n\n'.join(snow_parts), snow['excerpt'])
        self.assertEqual('verified', reverify_bound_public_sources(
            request, [snow], now=NOW)['status'])
        original = bodies[urls['snowpeak']]
        for changed in (original.replace('<p>' + snow_parts[0] + '</p>', ''),
                        original.replace(snow_parts[1], snow_parts[1] + '変更')):
            with self.subTest(changed=changed), self.assertRaisesRegex(
                    NonproductSourceHold, 'nonproduct_source_recheck_changed'):
                bodies[urls['snowpeak']] = changed
                reverify_bound_public_sources(request, [snow], now=NOW)
        bodies[urls['snowpeak']] = original

    def test_nonproduct_quality_and_typed_ledger_na(self):
        bundle = nonproduct_bundle()
        self.assertEqual('nonproduct', validate_nonproduct_bundle(bundle)['articleType'])
        self.assertTrue(inspect_bundle(bundle)['passed'], inspect_bundle(bundle))
        revision = fingerprint(bundle)
        review = {'passed': True, 'score': 8, 'fingerprint': revision,
                  'polish': {'model': 'gemini-3.8-flash', 'validated': True},
                  'evidence': {'facts': True, 'images': True, 'medical': True, 'render': True,
                               'affiliate': nonproduct_affiliate_review(bundle)}}
        valid_review(review, revision, bundle)
        with self.assertRaisesRegex(ValueError, 'typed nonproduct'):
            valid_review(review, revision)

    def test_empty_products_never_blanket_pass_and_hidden_commerce_fails(self):
        bundle = nonproduct_bundle()
        bundle['article']['generationMeta'].pop('editorialContext')
        self.assertFalse(inspect_bundle(bundle)['passed'])
        bundle = nonproduct_bundle()
        bundle['article']['content'] += '\n[購入](https://www.amazon.co.jp/dp/B012345678)'
        self.assertFalse(inspect_bundle(bundle)['passed'])


if __name__ == '__main__':
    unittest.main()
