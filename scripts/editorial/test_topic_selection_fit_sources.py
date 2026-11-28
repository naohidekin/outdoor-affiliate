"""Offline, real-shaped H1/fit-table fixtures for the two exact Thermos pages."""
import copy
from pathlib import Path
import tempfile
import unittest

import topic_selection as t
from test_topic_selection import NOW, nonproduct_bundle, proposal


def fit_html(url):
    x = t.FIT_EXAMPLES[url]
    return ('<!doctype html><html><body><main class="contents">'
        '<h1 class="mod-head01 mb50"><span class="mod-head01-inner">' + x['part'] +
        '<span class="mod-head01-small mt20"><span class="_code">JANコード：' + x['partJan'] +
        '</span><span class="_price">fixture price must not enter excerpt</span></span></span></h1>'
        '<form><h2>適合製品一覧</h2><h3>販売中の製品のみ表示</h3><div id="list_area">'
        '<div class="mod-tblWrap"><table class="mod-tbl01"><thead><tr><th>品番</th><th>色名</th>'
        '<th>JANコード</th></tr></thead><tbody><tr><td>' + x['model'] + '</td><td>' +
        x['color'] + '</td><td>' + x['productJan'] + '</td></tr></tbody></table></div></div>'
        '</form></main></body></html>')


def registered_reference(url, excerpt, now=NOW):
    """Complete synthetic receipt for a real registered URL/ID/scope."""
    raw = {'id': t.SOURCE_IDS[url], 'url': url, 'canonicalUrl': url,
           'checkedAt': now.isoformat(), 'httpStatus': 200, 'excerpt': excerpt,
           'claimScope': t.PUBLIC_SOURCE_ALLOWLIST[url]}
    return {**raw, 'id': 'public:' + raw['id'], 'title': raw['id'],
            'kind': 'public-primary', 'scope': raw['claimScope'],
            'excerptSha256': t._sha(excerpt), 'receiptSha256': t._sha(t._canonical(raw))}


def fixture_feed():
    from test_topic_selection_expanded_sources import ExpandedPrimarySourceTests
    fixture = ExpandedPrimarySourceTests()
    fixture.setUp()
    with tempfile.TemporaryDirectory() as tmp:
        return t.collect_primary_sources(fixture.request, period='2026-11-20',
            output_path=Path(tmp) / 'source.json', now=NOW)


def request_from_feed(feed):
    def request(url, headers):
        ref = next(r for r in feed['sources'] if r['url'] == url)
        html = fit_html(url) if url in t.FIT_EXAMPLES else (
            '<html>' + ''.join('<p>' + p + '</p>' for p in ref['excerpt'].split('\n\n')) + '</html>')
        return {'status': 200, 'url': url, 'headers': {'content-type': 'text/html'}, 'body': html.encode()}
    return request


class FitSourceTests(unittest.TestCase):
    def test_fixed_part_and_exact_same_row_capsule_excludes_price_inventory(self):
        for url in t.FIT_EXAMPLES:
            excerpt = t.fit_example_excerpt(url, fit_html(url))
            self.assertEqual(t._fit_capsule(url), excerpt)
            self.assertLessEqual(len(excerpt), 500)
            self.assertNotIn('price', excerpt)
            self.assertNotIn('販売中', excerpt)

    def test_forged_cells_separate_rows_hidden_headers_and_duplicates_reject(self):
        for url, x in t.FIT_EXAMPLES.items():
            html = fit_html(url)
            row = '<tr><td>' + x['model'] + '</td><td>' + x['color'] + '</td><td>' + x['productJan'] + '</td></tr>'
            variants = [
                html.replace(x['partJan'], '0' * 13),
                html.replace(x['part'], 'OTHERパッキンセット'),
                html.replace(x['productJan'], '1' * 13),
                html.replace('<td>' + x['model'] + '</td><td>' + x['color'], '<td>' + x['color'] + '</td><td>' + x['model']),
                html.replace(row, row.replace(x['productJan'], '2' * 13) + row.replace(x['model'], 'OTHER')),
                html.replace(row, row + row),
                html.replace(row, row.replace('<tr>', '<tr hidden>')),
                html.replace(row, row.replace('<tr>', '<tr style="display:none">')),
                html.replace(row, '<script>' + row + '</script>'),
                html.replace('<h1 ', '<h1 hidden '),
                html.replace('<div id="list_area">', '<h2>別商品の関連情報</h2><div id="list_area">'),
                html.replace('<td>' + x['model'], '<td colspan="2">' + x['model']),
                html.replace(row, '<p>' + x['model'] + x['color'] + x['productJan'] + '</p>'),
                html.replace('</h1>', '</h1><h1>duplicate</h1>'),
                html.replace('</td>', '</th>', 1),
            ]
            for i, forged in enumerate(variants):
                with self.subTest(url=url, case=i):
                    self.assertIsNone(t.fit_example_excerpt(url, forged))

    def test_collection_and_reverify_capsule_ignore_price_but_not_codes_or_canonical(self):
        feed = fixture_feed()
        self.assertEqual(9, len(feed['sources']))
        request = request_from_feed(feed)
        for url, item in t.FIT_EXAMPLES.items():
            ref = next(r for r in feed['sources'] if r['url'] == url)
            self.assertEqual('verified', t.reverify_bound_public_sources(request, [ref], now=NOW)['status'])
            for mode in ('price', 'code', 'redirect', 'pdf'):
                def changed(target, headers):
                    value = request(target, headers)
                    if mode == 'price':
                        value['body'] = value['body'].replace(b'fixture price', b'changed price')
                    if mode == 'code':
                        value['body'] = value['body'].replace(item['productJan'].encode(), b'0000000000000')
                    if mode == 'redirect':
                        value['url'] += '&other=1'
                    if mode == 'pdf':
                        value['headers']['content-type'] = 'application/pdf'
                    return value
                if mode == 'price':
                    self.assertEqual('verified', t.reverify_bound_public_sources(changed, [ref], now=NOW)['status'])
                else:
                    with self.assertRaises(t.NonproductSourceHold):
                        t.reverify_bound_public_sources(changed, [ref], now=NOW)

    def test_fit_scope_requires_thermos_primary_and_known_fit_source_id(self):
        fit_id = 'public:' + t.SOURCE_IDS[next(iter(t.FIT_EXAMPLES))]
        theme = proposal('thermos-fit-guide', 'サーモスのパッキンを品番から探すには？',
            outline=['品番と色名で適合例を確認', 'JANの照合', '購入前の確認'],
            sourceIds=['public:thermos-product-parts'])
        self.assertEqual(['thermos-parts-lookup'], t.allowed_claim_scopes(theme))
        theme['sourceIds'].append(fit_id)
        self.assertEqual(['thermos-parts-lookup', 'thermos-parts-fit-example'], t.allowed_claim_scopes(theme))
        for change in ({'title': 'コールマンの部品を検索', 'readerQuestion': 'コールマンの部品を探す'}, {'outline': ['互換の調べ方']},
                       {'outline': ['分解修理']}, {'sourceIds': ['public:made-up-fit']}):
            bad = dict(theme, **change)
            self.assertNotIn('thermos-parts-fit-example', t.allowed_claim_scopes(bad))

    def test_full_contract_and_bundle_refuse_forged_verified_receipts_and_old_image_binding(self):
        feed = fixture_feed()
        theme = proposal('thermos-fit-guide', 'サーモスのパッキンを品番から探すには？',
            outline=['品番と色名で適合例を確認', 'JANの照合', '購入前の確認'],
            sourceIds=['public:thermos-product-parts'] + ['public:' + t.SOURCE_IDS[u] for u in t.FIT_EXAMPLES])
        bound = t.bind_nonproduct_theme(theme, feed)
        t.gather_nonproduct(bound, {})
        for change in ('verified', 'hash', 'missing', 'extra'):
            bad = copy.deepcopy(bound)
            contract = bad['nonProductContract']
            if change == 'verified':
                contract['references'][-1] = {'verified': True}
            elif change == 'hash':
                contract['references'][-1]['excerpt'] += 'free invented claim'
            elif change == 'missing':
                contract['references'].pop()
            else:
                contract['anything'] = True
            with self.assertRaises(t.TopicSelectionError):
                t.gather_nonproduct(bad, {})
        bundle = nonproduct_bundle()
        bundle['article']['title'] = theme['title']
        bundle['references'] = bound['nonProductContract']['references']
        ids = [r['id'] for r in bundle['references']]
        image = bundle['images'][0]
        image['referenceIds'] = ids
        bundle['article']['generationMeta']['editorialContext'] = t.editorial_context(bound, [image])
        with self.assertRaisesRegex(t.TopicSelectionError, 'image_binding'):
            t.validate_nonproduct_bundle(bundle)
        image['rendererEvidence'] = {'passed': True, 'evidencePassed': True, 'networkRequests': 0,
            'sourceIds': ids, 'sourceReceiptSha256': bound['nonProductContract']['sourceReceiptSha256'],
            'contentHash': image['compositionSha256'], 'pngSha256': image['sha256']}
        t.validate_nonproduct_bundle(bundle)
        bundle['article']['title'] = 'テントを乾かす方法'
        with self.assertRaisesRegex(t.TopicSelectionError, 'scope_mismatch'):
            t.validate_nonproduct_bundle(bundle)

    def test_pdpts_bottom_label_is_fifth_block_and_old_excerpt_still_reverifies(self):
        feed = fixture_feed()
        url = 'https://www.thermos.jp/goods/pdpts'
        old = next(r for r in feed['sources'] if r['url'] == url)
        parts = old['excerpt'].split('\n\n')
        location = '製品の品番は底面のラベルで確認してください。'
        self.assertEqual(old['excerpt'] + '\n\n' + location, t._primary_excerpt(url, parts + [location]))
        reader = request_from_feed(feed)
        def request(target, headers):
            value = reader(target, headers)
            value['body'] += ('<p>' + location + '</p>').encode()
            return value
        self.assertEqual('verified', t.reverify_bound_public_sources(request, [old], now=NOW)['status'])

    def test_actual_pdpts_div_location_after_original_four_without_alt_or_hidden_text(self):
        url = 'https://www.thermos.jp/goods/pdpts'
        ref = next(r for r in fixture_feed()['sources'] if r['url'] == url)
        note = '製品の品番・色名はご購入いただいた商品の底面シールや、商品パッケージのJANコード付近に記載されております。'
        html = ('<main>' + ''.join('<li>' + b + '</li>' for b in ref['excerpt'].split('\n\n')) +
                '<div id="list_area"><div style="font-size:1.6rem">' + note + '<br>' +
                '（アルファベットから始まる下記の番号です）<br><img alt="UNVERIFIED OCR"></div></div></main>')
        excerpt = t._primary_excerpt(url, t._lookup_blocks(url, html))
        self.assertEqual(ref['excerpt'] + '\n\n' + note, excerpt)
        self.assertEqual(5, len(excerpt.split('\n\n')))
        self.assertLessEqual(len(excerpt), 500)
        self.assertEqual(ref['excerpt'], t._primary_excerpt(url, t._lookup_blocks(url,
            html.replace('<div style="font-size:1.6rem">', '<div hidden>'))))


if __name__ == '__main__':
    unittest.main()
