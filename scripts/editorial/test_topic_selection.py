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


def signals():
    return [{'id': 'gsc:one', 'kind': 'gsc'}, *[{'id': item['id'], 'kind': 'public_reference'}
            for item in feed()['sources']]]


def proposal(slug, question, priority=80, **updates):
    value = {'slug': slug, 'title': question, 'categoryId': 'camp-howto', 'productIds': [],
             'topicType': 'knowhow', 'query': question, 'readerQuestion': question,
             'intent': 'informational', 'outline': ['準備', '手順', '保管'], 'priority': priority,
             'overlapRationale': '既存とは別の読者課題', 'selectionReason': 'own-site evidence',
             'sourceIds': ['gsc:one', 'public:coleman-care'], 'proposedAction': 'new',
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
                              sourceIds=['gsc:one', 'public:montbell-layering'])]
        selected = select_proposals(proposals, signals=signals(), existing=[], queued=[],
                                    feed=feed(), limit=2)
        self.assertEqual(['tent-dry', 'layer-order'], [item['slug'] for item in selected['selected']])

    def test_structured_semantic_overlap_routes_private_update(self):
        existing = [{'id': 'article-tent-care', 'slug': 'tent-maintenance',
                     'title': 'テント撤収後の手入れ', 'readerQuestion': '撤収後の手入れは？'}]
        item = proposal('rainy-tent-care', '雨撤収したテントはどう手入れする？',
                        proposedAction='existing_update', overlapArticleIds=['article-tent-care'])
        result = select_proposals([item], signals=signals(), existing=existing, queued=[],
                                  feed=feed(), limit=3)
        self.assertEqual([], result['selected'])
        self.assertEqual(('existing_update', 'article-tent-care'),
                         (result['decisions'][0]['status'], result['decisions'][0]['existingArticleId']))

    def test_invalid_earlier_proposal_does_not_block_later_valid_one(self):
        bad = proposal('same-question', 'テントを乾かす手順は？', sourceIds=['unknown'])
        good = proposal('valid-question', 'テントを乾かす手順は？')
        result = select_proposals([bad, good], signals=signals(), existing=[], queued=[],
                                  feed=feed(), limit=1)
        self.assertEqual(['valid-question'], [item['slug'] for item in result['selected']])

    def test_regular_pool_with_only_two_qualified_candidates_holds_all_visibly(self):
        items = [proposal('tent-dry', 'テントを乾かす手順は？', 90),
                 proposal('layer-order', '重ね着の順番は？', 89,
                          outline=['肌着', '中間着', '上着'],
                          sourceIds=['gsc:one', 'public:montbell-layering'])]
        result = select_proposals(items, signals=signals(), existing=[], queued=[],
                                  feed=feed(), limit=3)
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
        result = select_proposals([item], signals=signals(), existing=[], queued=[],
                                  feed=feed(), limit=1)
        self.assertEqual('nonproduct_claim_scope_mismatch', result['decisions'][0]['reason'])

    def test_outline_cannot_legitimize_wrong_source_or_expand_uncovered_family(self):
        wrong_source = proposal('layering-care-source', '重ね着の順番は？',
                                outline=['乾燥', '保管', '確認'])
        uncovered_outline = proposal('layering-care-outline', '重ね着の順番は？',
            outline=['肌着', '乾燥と保管', '上着'],
            sourceIds=['gsc:one', 'public:montbell-layering'])
        first = select_proposals([wrong_source], signals=signals(), existing=[], queued=[],
                                 feed=feed(), limit=1)
        second = select_proposals([uncovered_outline], signals=signals(), existing=[], queued=[],
                                  feed=feed(), limit=1)
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
        measured = [{'id': 'gsc-change:one', 'kind': 'own_site_gsc_period_comparison'},
                    {'id': 'public:coleman-care', 'kind': 'public_reference'}]
        selected = select_proposals([item], signals=measured, existing=[], queued=[],
                                    feed=feed(), limit=1)
        self.assertEqual(['gsc-change-topic'], [row['slug'] for row in selected['selected']])

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
        self.assertEqual(('partial', 2, 1),
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
