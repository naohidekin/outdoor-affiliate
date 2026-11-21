"""Synthetic bounded HTML contracts for the six fixed official sources; no IO/network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import topic_selection as topics
from test_topic_selection import NOW, proposal, nonproduct_bundle

WASH = 'https://www.coleman.co.jp/customersupport/faq/?category=sleeping-bag'
PARTS = 'https://www.thermos.jp/goods/pdpts'
PRODUCT = 'https://www.thermos.jp/goods/ptpds'
SNOW = 'https://www.snowpeak.co.jp/contents/campstarterbook/'


class ExpandedPrimarySourceTests(unittest.TestCase):
    def setUp(self):
        self.blocks = {
            'https://www.coleman.co.jp/customersupport/faq/': ['テントの汚れを落として十分に乾燥してから保管します。'],
            SNOW: ['撤収後の道具は十分に乾燥させてから保管することを確認します。'],
            'https://www.montbell.jp/generalpage/disp.php?id=507': ['レイヤリングは肌着、中間着、上着を重ねる考え方です。'],
            WASH: ['ウォッシャブルアイコン付きは洗濯機で丸洗いできます。素材は全て化繊で、その他の多くは手洗いですが縫付ラベルに従ってください。'],
            PARTS: ['製品の品番・色名・JANコードの一部で検索が可能です。',
                    '製品に適合する交換用部品を探す場合は製品の品番を確認してください。',
                    '条件をスペースで区切ったAND検索の表記を確認してください。',
                    '英数字は半角、漢字・ひらがな・カタカナは全角で入力してください。'],
            PRODUCT: ['交換用部品名・JANコードの一部で検索が可能です。',
                      '交換用部品の品番と部品名の表記を確認してください。',
                      '検索する語句のAND条件とスペースの表記を確認してください。',
                      '英数字は半角、漢字・ひらがな・カタカナは全角で入力してください。'],
        }
        self.calls = []

    def request(self, url, headers):
        self.calls.append(url)
        if url in topics.FIT_EXAMPLES:
            from test_topic_selection_fit_sources import fit_html
            return {'status': 200, 'url': url, 'headers': {'content-type': 'text/html'},
                    'body': fit_html(url).encode()}
        return {'status': 200, 'url': url, 'headers': {'content-type': 'text/html; charset=utf-8'},
                'body': ('<html><script>品番 色名 JAN fake</script>' + ''.join('<p>' + b + '</p>'
                         for b in self.blocks[url]) + '</html>').encode()}

    def collect(self, request=None):
        with tempfile.TemporaryDirectory() as directory:
            return topics.collect_primary_sources(request or self.request, period='2026-11-20',
                output_path=Path(directory) / 'sources.json', now=NOW)

    def test_eight_exact_urls_have_unique_explicit_ids_and_unchanged_old_six_scopes(self):
        feed = self.collect()
        self.assertEqual('verified', feed['status'])
        self.assertEqual(set(topics.PUBLIC_SOURCE_ALLOWLIST), set(self.calls))
        self.assertEqual(8, len(set(s['id'] for s in feed['sources'])))
        by_url = {s['url']: s for s in feed['sources']}
        self.assertEqual('public:coleman-care', by_url['https://www.coleman.co.jp/customersupport/faq/']['id'])
        self.assertEqual('public:coleman-synthetic-wash', by_url[WASH]['id'])
        self.assertEqual('public:thermos-product-parts', by_url[PARTS]['id'])
        self.assertEqual('public:thermos-parts-product', by_url[PRODUCT]['id'])
        self.assertEqual(['tent-care', 'camp-care', 'layering-concept-only'],
                         [s['scope'] for s in feed['sources'][:3]])
        self.assertEqual('wash', topics._scope_family(by_url[WASH]['scope']))
        self.assertEqual('parts', topics._scope_family(by_url[PARTS]['scope']))

    def test_thermos_joins_up_to_four_exact_paragraphs_and_rechecks_every_one(self):
        feed = self.collect()
        for url in (PARTS, PRODUCT):
            reference = next(s for s in feed['sources'] if s['url'] == url)
            self.assertEqual('\n\n'.join(self.blocks[url]), reference['excerpt'])
            self.assertLessEqual(len(reference['excerpt']), 500)
            self.assertEqual('verified', topics.reverify_bound_public_sources(self.request, [reference], now=NOW)['status'])
            old = self.blocks[url][-1]
            self.blocks[url][-1] = old + 'changed'
            with self.assertRaisesRegex(topics.NonproductSourceHold, 'recheck_changed'):
                topics.reverify_bound_public_sources(self.request, [reference], now=NOW)
            self.blocks[url][-1] = old
            self.blocks[url].append('検索時の表記と部品名は別途確認することを示す追加の段落です。')
            again = next(s for s in self.collect()['sources'] if s['url'] == url)
            self.assertEqual(reference['excerpt'], again['excerpt'])

    def test_thermos_actual_width_rule_is_bound_as_the_fourth_paragraph(self):
        rule = '英数字は半角、漢字・ひらがな・カタカナは全角で入力してください。'
        feed = self.collect()
        for url in (PARTS, PRODUCT):
            with self.subTest(url=url):
                reference = next(s for s in feed['sources'] if s['url'] == url)
                self.assertEqual(4, len(reference['excerpt'].split('\n\n')))
                self.assertEqual(rule, reference['excerpt'].split('\n\n')[-1])
                self.assertEqual('\n\n'.join(self.blocks[url]), reference['excerpt'])
                self.assertLessEqual(len(reference['excerpt']), 500)

    def test_bad_canonical_status_and_missing_anchor_never_fallback(self):
        for mode in ('redirect', 'status', 'anchor'):
            def request(url, headers):
                value = self.request(url, headers)
                if url == PARTS:
                    if mode == 'redirect':
                        value['url'] = 'https://www.thermos.jp/support/parts.html'
                    elif mode == 'status':
                        value['status'] = 503
                    else:
                        value['body'] = '<p>部品を探す際の一般的な案内だけでは確認語が揃いません。</p>'.encode()
                return value
            result = self.collect(request)
            self.assertEqual('partial', result['status'])
            self.assertNotIn(PARTS, [s['url'] for s in result['sources']])
        self.calls = []
        with self.assertRaises(topics.NonproductSourceHold):
            topics.reverify_bound_public_sources(self.request, [{'url': 'https://www.thermos.jp/support/parts.html'}], now=NOW)
        self.assertEqual([], self.calls)

    def candidates(self, feed):
        wash = proposal('coleman-wash-decision', 'コールマン化繊寝袋が洗えるかラベルで判断するには？',
            outline=['化繊寝袋とウォッシャブルアイコン', '洗濯機か手洗いかの表示確認', '縫付ラベル'],
            sourceIds=['gsc:one', 'public:coleman-synthetic-wash'])
        parts = proposal('thermos-parts-lookup', 'サーモスのパッキンや部品を品番から探すには？',
            outline=['製品の品番と色名', 'JANとAND検索', '交換用部品名の表記'],
            sourceIds=['gsc:one', 'public:thermos-product-parts', 'public:thermos-parts-product'])
        return wash, parts

    def select(self, candidates, feed):
        signals = [{'id': 'gsc:one', 'kind': 'gsc'}] + [{'id': s['id'], 'kind': 'public_reference'} for s in feed['sources']]
        return topics.select_proposals(candidates, signals=signals, existing=[], queued=[], feed=feed, limit=1)

    def test_narrow_wash_and_parts_accept_their_sources_and_reject_cross_use(self):
        feed = self.collect()
        wash, parts = self.candidates(feed)
        for p in (wash, parts):
            self.assertEqual('selected', self.select([p], feed)['status'])
            bound = topics.bind_nonproduct_theme(p, feed)
            self.assertCountEqual(p['sourceIds'][1:], [s['id'] for s in bound['nonProductContract']['references']])
            self.assertTrue(topics.gather_nonproduct(bound, {'articles': [], 'categories': []})['checks']['facts'])
        for p, ids in ((wash, parts['sourceIds']), (parts, wash['sourceIds'])):
            bad = dict(p, sourceIds=ids)
            self.assertEqual('nonproduct_claim_scope_mismatch', self.select([bad], feed)['decisions'][0]['reason'])
            with self.assertRaises(topics.TopicSelectionError):
                topics.bind_nonproduct_theme(bad, feed)

    def test_outlines_cannot_expand_decision_into_down_or_unverified_washing_steps(self):
        feed = self.collect()
        wash, parts = self.candidates(feed)
        for topic in ('ダウンの洗い方', '水温と洗剤', '手洗い手順', '乾燥機の設定', '寝袋の洗い方', '手洗いする方法'):
            bad = dict(wash, outline=wash['outline'][:3] + [topic])
            self.assertNotEqual('selected', self.select([bad], feed)['status'])
        for topic in ('パッキン交換手順', '分解修理', '洗剤と漂白'):
            bad = dict(parts, outline=parts['outline'][:2] + [topic])
            self.assertNotEqual('selected', self.select([bad], feed)['status'])
        # The specialized decision page cannot cover added generic drying/storage claims.
        broad_care = dict(wash, outline=wash['outline'] + ['乾燥と保管の手順'])
        self.assertEqual('nonproduct_outline_scope_uncovered', self.select([broad_care], feed)['decisions'][0]['reason'])
        excluded_only_in_rationale = dict(wash, selectionReason='ダウン、水温、洗剤、乾燥機の手順は扱わない判断ガイド')
        self.assertEqual('selected', self.select([excluded_only_in_rationale], feed)['status'])

    def test_reverification_refuses_relabelled_new_scope_or_colliding_source_id(self):
        feed = self.collect()
        original = next(s for s in feed['sources'] if s['url'] == PARTS)
        for field, value in (('scope', 'camp-care'), ('claimScope', 'tent-care'),
                             ('id', 'public:montbell-layering')):
            bad = dict(original, **{field: value})
            self.calls = []
            with self.assertRaisesRegex(topics.NonproductSourceHold, 'recheck_changed'):
                topics.reverify_bound_public_sources(self.request, [bad], now=NOW)
            self.assertEqual([], self.calls)

    def test_original_three_receipts_and_saved_bundle_remain_compatible(self):
        feed = self.collect()
        for reference in feed['sources'][:3]:
            url = reference['url']
            raw_id = {'https://www.coleman.co.jp/customersupport/faq/': 'coleman-care',
                      SNOW: 'snowpeak-care',
                      'https://www.montbell.jp/generalpage/disp.php?id=507': 'montbell-layering'}[url]
            receipt = {'id': raw_id, 'url': url, 'canonicalUrl': url, 'checkedAt': NOW.isoformat(),
                       'httpStatus': 200, 'excerpt': self.blocks[url][0], 'claimScope': reference['scope']}
            self.assertEqual(topics._sha(topics._canonical(receipt)), reference['receiptSha256'])
            self.assertEqual('public:' + raw_id, reference['id'])
        self.assertEqual('verified', topics.reverify_bound_public_sources(self.request, feed['sources'][:3], now=NOW)['status'])
        self.assertEqual('nonproduct', topics.validate_nonproduct_bundle(nonproduct_bundle())['articleType'])

    def test_tumbler_related_links_prioritize_published_category_without_body_leak(self):
        feed = self.collect()
        _, parts = self.candidates(feed)
        parts['categoryId'] = 'tumbler'
        theme = topics.bind_nonproduct_theme(parts, feed)
        def article(slug, category='tent', status='published'):
            return {'id': slug + '-id', 'slug': slug, 'title': slug + ' title',
                    'categoryId': category, 'status': status, 'excerpt': slug + ' excerpt',
                    'content': 'FULL_BODY_MUST_NOT_LEAK', 'internalMetadata': 'PRIVATE_METADATA'}
        articles = [article('tent-' + str(i)) for i in range(6)] + [
            article('bottle-second-name', 'tumbler'), article(theme['slug'], 'tumbler'),
            article('bottle-first-name', 'tumbler'), article('draft-bottle', 'tumbler', 'draft')]
        catalog = {'articles': articles, 'categories': [{'id': 'tumbler'}]}
        before = copy.deepcopy(catalog)
        gathered = topics.gather_nonproduct(theme, catalog)
        rows = gathered['existingArticles']
        self.assertEqual(['bottle-second-name', 'bottle-first-name', 'tent-0', 'tent-1', 'tent-2'],
                         [r['slug'] for r in rows])
        self.assertTrue(all(set(r) == {'title', 'slug', 'categoryId', 'excerpt'} for r in rows))
        self.assertNotIn('FULL_BODY_MUST_NOT_LEAK', json.dumps(gathered))
        self.assertNotIn('PRIVATE_METADATA', json.dumps(gathered))
        self.assertEqual(before, catalog)
        # No same-category articles: retain the original fallback ordering.
        fallback = topics.gather_nonproduct(dict(theme, categoryId='other'), catalog)
        self.assertEqual(['tent-' + str(i) for i in range(5)], [r['slug'] for r in fallback['existingArticles']])

    def test_related_source_change_mints_new_key_but_same_regathered_image_clock_does_not(self):
        from runtime import Runtime
        from stage_journal import StageJournal
        feed = self.collect()
        _, parts = self.candidates(feed)
        theme = topics.bind_nonproduct_theme(dict(parts, categoryId='tumbler'), feed)
        articles = [{'status': 'published', 'slug': 'tent-' + str(i), 'categoryId': 'tent'} for i in range(5)]
        articles += [{'status': 'published', 'slug': 'bottle', 'categoryId': 'tumbler'}]
        catalog = {'articles': articles}
        gathered = topics.gather_nonproduct(theme, catalog)
        image = {'sha256': 'a' * 64, 'checkedAt': 'first', 'rendererEvidence': {'contentHash': 'b' * 64}}
        gathered['images'] = [copy.deepcopy(image)]
        gathered['evidence']['ownedIllustrations'] = [copy.deepcopy(image)]
        def key(value):
            return StageJournal.key('job', 'draft', {'dependencies': {'source': Runtime._source_dependencies(value)},
                                                    'schemaVersion': {'stage': 1}})
        repeated = topics.gather_nonproduct(theme, catalog)
        repeated['images'] = [dict(image, checkedAt='second')]
        repeated['evidence']['ownedIllustrations'] = [dict(image, checkedAt='second')]
        self.assertEqual(key(gathered), key(repeated))
        old = copy.deepcopy(gathered)
        old['existingArticles'] = [{'title': a.get('title'), 'slug': a['slug'],
            'categoryId': a['categoryId'], 'excerpt': a.get('excerpt')} for a in articles[:5]]
        self.assertNotEqual(key(old), key(gathered))

    def test_nonproduct_validation_binds_new_scope_ids_and_receipts(self):
        feed = self.collect()
        _, parts = self.candidates(feed)
        theme = topics.bind_nonproduct_theme(parts, feed)
        bundle = nonproduct_bundle()
        bundle['article'].update(slug=parts['slug'], title=parts['title'])
        bundle['references'] = theme['nonProductContract']['references']
        bundle['images'][0]['referenceIds'] = [s['id'] for s in bundle['references']]
        bundle['article']['generationMeta']['editorialContext'] = topics.editorial_context(theme, bundle['images'])
        self.assertEqual('nonproduct', topics.validate_nonproduct_bundle(bundle)['articleType'])
        for field, value in (('claimScope', 'camp-care'), ('id', 'public:montbell-layering')):
            bad = copy.deepcopy(bundle)
            bad['references'][0][field] = value
            with self.assertRaises(topics.TopicSelectionError):
                topics.validate_nonproduct_bundle(bad)


if __name__ == '__main__':
    unittest.main()
