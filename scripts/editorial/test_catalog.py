"""Offline catalogue, evidence and SSRF contracts; no real HTTP or env reads."""
import copy
import struct
import zlib
import hashlib
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from catalog import Catalog, CatalogError, safe_url, model_matches, _image_type, _affiliate_route, _Page, _spec_evidence

ENV = {'SUPABASE_URL': 'https://db.example', 'SUPABASE_SERVICE_ROLE_KEY': 'SECRET',
       'BRAVE_API_KEY': 'BRAVE', 'RAKUTEN_APP_ID': 'APP', 'RAKUTEN_ACCESS_KEY': 'KEY'}
def png_chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))

PNG = (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
       + png_chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + png_chunk(b'IEND', b''))



def products():
    return [dict(id=f'p{i}', name=f'SOTO Stove ST-30{i}', brand='SOTO', categoryId='stove',
                 specs={'model': f'ST-30{i}', 'weight': '200g'}, price=100, description='catalog only',
                 imageUrl=f'https://images.example/{i}.png',
                 affiliateUrl=f'https://item.rakuten.co.jp/shop/st30{i}/', amazonUrl='') for i in range(3)]


def response(body, kind='text/html', status=200, headers=None):
    return dict(status=status, headers=dict({'content-type': kind}, **(headers or {})),
                body=body.encode() if isinstance(body, str) else body)


class CatalogTests(unittest.TestCase):
    def test_required_notice_fresh_quotes_and_manufacturer_redirect_scope(self):
        product = products()[0]
        notice = 'https://soto.shinfuji.co.jp/news/discontinued/'
        final = 'https://soto.shinfuji.co.jp/news/final/'
        quotes = ['2026.07.30', 'ST-300 生産終了 後継機種：ST-301']
        calls = []
        def fetch(url, *_):
            calls.append(url)
            if url == notice:
                return response('', status=302, headers={'location': final})
            if url == final:
                return response('<p>2026.07.30</p><table><tr><td>ST-300</td>'
                                '<td>生産終了</td><td>後継機種：ST-301</td></tr></table>'
                                '<script>not public evidence</script>')
            return response('')
        catalog = Catalog({}, fetch, source_notices={'p0': [{'url': notice, 'quotes': quotes}]})
        for _ in range(2):
            result = catalog.gather({'productIds': ['p0']}, {'products': [product]})
            refs = [r for r in result['references'] if r['kind'] == 'manufacturer-notice']
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]['text'], ' '.join(quotes))
            self.assertEqual(refs[0]['url'], final)
            self.assertEqual(refs[0]['productId'], 'p0')
            self.assertTrue(refs[0]['checkedAt'])
            self.assertNotIn('script', refs[0]['text'])
        self.assertEqual(calls.count(notice), 2)
        self.assertEqual(calls.count(final), 2)
        calls.clear()
        def external_redirect(url, *_):
            calls.append(url)
            return response('', status=302, headers={'location': 'https://evil.example/notice'})
        with self.assertRaisesRegex(CatalogError, '^required notice unavailable$'):
            Catalog({}, external_redirect, source_notices={'p0': [{'url': notice, 'quotes': quotes}]}).gather(
                {'productIds': ['p0']}, {'products': [product]})
        self.assertEqual(calls, [notice])

    def test_required_notice_missing_quote_or_http_failure_never_returns_certification(self):
        product = products()[0]
        notice = 'https://soto.shinfuji.co.jp/news/discontinued/'
        for reply, quotes in [
                (response('<p>ST-300 生産終了</p>'), ['ST-300 生産終了', '後継機種：ST-301']),
                (response('<script>ST-300 生産終了</script>'), ['ST-300 生産終了']),
                (response('unavailable', status=503), ['ST-300 生産終了']),
                (response('ST-300 生産終了', kind='application/json'), ['ST-300 生産終了']),
                (response('<p>ST-300 生産終了</p>'), [])]:
            with self.subTest(status=reply['status'], quotes=quotes):
                with self.assertRaisesRegex(CatalogError, '^required notice unavailable$'):
                    Catalog({}, lambda *a: reply, source_notices={'p0': [{'url': notice, 'quotes': quotes}]}).gather(
                        {'productIds': ['p0']}, {'products': [product]})

    def test_legacy_japanese_html_charset(self):
        from catalog import _decode_html
        html = '<meta charset="EUC-JP"><title>スノーピーク GS600</title>'
        self.assertIn('スノーピーク', _decode_html(html.encode('euc_jp'), 'text/html'))
        html = '<title>スノーピーク GS600</title>'
        self.assertEqual(_decode_html(html.encode('shift_jis'), 'text/html; charset=Shift_JIS'), html)
        with self.assertRaises(CatalogError):
            _decode_html(b'<meta charset="utf-7">+not-html', 'text/html')

    def test_marketing_keys_cannot_be_certified_as_specs(self):
        self.assertIsNone(_spec_evidence(_Page('<p>ST-310 benefit: best stove</p>'),
                                         'ST-310', 'benefit', 'best stove'))

    def test_japanese_model_boundaries_preserve_exact_ascii_sku(self):
        self.assertTrue(model_matches('GS600', 'スノーピークGS600バーナー'))
        for title in ['GS600KH', 'GS6000', 'GS-600', 'XGS600']:
            self.assertFalse(model_matches('GS600', title))

    def test_structured_maker_specs_use_primary_identity_and_exact_scoped_values(self):
        soto = _Page('''<title>SOTO SOD-310</title><p>RELATED SOD-320 重量 500g</p>
            <article class="pdContents"><section class="pdContents__info">
            <dl class="toggleTarget pd__specification"><dt>製品仕様</dt><dd><div><li><h3>重量</h3><p>350g</p></li>
            <li><h3>使用燃料</h3><p>OD缶 SOD-750T</p></li>
            <aside>※1 気温25℃、無風時</aside></div></dd></dl></section></article>''')
        weight = _spec_evidence(soto, 'SOD-310', '重量', '350g', primary_identity=True, brand='SOTO')
        self.assertEqual(weight['value'], '350g')
        self.assertIn('気温25℃', weight['conditions'][0])
        self.assertIsNotNone(_spec_evidence(soto, 'SOD-310', '使用燃料', 'OD缶 SOD-750T', primary_identity=True, brand='SOTO'))
        self.assertIsNone(_spec_evidence(soto, 'SOD-310', '重量', '500g', primary_identity=True, brand='SOTO'))
        snow = _Page('''<title>スノーピーク HOME＆CAMPバーナー カーキ</title>
            <div id="tab-size">
            <dl><dt>メーカー品番</dt><dd>GS-600KH (店舗でお問い合わせの際には、上記品番をお伝え下さい。)</dd></dl>
            <dl><dt>サイズ</dt><dd>301×346×120mm</dd></dl><dl><dt>素材</dt><dd>ステンレス</dd></dl></div>''')
        from catalog import _primary_identity
        self.assertEqual(_primary_identity(snow, 'GS-600KH', 'snow peak'), 'メーカー品番')
        self.assertIsNotNone(_spec_evidence(snow, 'GS-600KH', 'model', 'GS-600KH', primary_identity=True, brand='snow peak'))
        self.assertIsNotNone(_spec_evidence(snow, 'GS-600KH', '素材', 'ステンレス', primary_identity=True, brand='snow peak'))
        self.assertIsNone(_primary_identity(_Page('<title>スノーピーク HOME＆CAMPバーナー</title><p>おすすめ GS-600KH</p>'), 'GS-600KH', 'snow peak'))
        conflict = _Page('<title>SOTO ST-310</title><article class="pdContents"><section class="pdContents__info">'
                         '<dl class="pd__specification"><li><h3>重量</h3><p>350g</p></li>'
                         '<li><h3>重量</h3><p>380g</p></li></dl></section></article>')
        self.assertIsNone(_spec_evidence(conflict, 'ST-310', '重量', '350g', primary_identity=True, brand='SOTO'))

    def test_source_hint_fetches_official_page_but_never_certifies_by_url_alone(self):
        product = products()[0]
        hint = 'https://soto.shinfuji.co.jp/products/st300/'
        calls = []
        def fetch(url, headers, timeout):
            calls.append(url)
            if url == hint:
                return response('<title>SOTO ST-300</title><article class="pdContents"><section class="pdContents__info">'
                                '<dl class="pd__specification"><li><h3>weight</h3><p>200g</p></li></dl></section></article>')
            return response('not found')
        ctx = Catalog({}, fetch, {'p0': [hint, 'https://evil.example/item']}).gather(
            {'productIds': ['p0']}, {'products': [product]})
        self.assertIn(hint, calls)
        self.assertNotIn('https://evil.example/item', calls)
        self.assertTrue(ctx['evidence']['products'][0]['facts'])
        self.assertTrue(any(r['kind'] == 'manufacturer-spec' and '200g' in r['text'] for r in ctx['references']))
        bad = Catalog({}, lambda *a: response('<title>SOTO ST-300</title>'), {'p0': [hint]}).gather(
            {'productIds': ['p0']}, {'products': [product]})
        self.assertFalse(bad['evidence']['products'][0]['facts'])

    def test_complete_hints_skip_optional_search_but_fetch_image_and_purchase(self):
        product = products()[0]
        hint = 'https://soto.shinfuji.co.jp/products/st300/'
        calls = []
        def fetch(url, headers, timeout):
            calls.append(url)
            if 'api.search.brave.com' in url:
                return response('{"web":{"results":[]}}', 'application/json')
            if 'openapi.rakuten.co.jp' in url:
                return response('{"Items":[]}', 'application/json')
            if url == hint:
                return response('<title>SOTO ST-300</title><article class="pdContents"><section class="pdContents__info">'
                                '<dl class="pd__specification"><li><h3>weight</h3><p>200g</p></li></dl>'
                                '</section></article>'
                                '<img src="https://images.example/0.png">')
            if url == product['imageUrl']:
                return response(PNG, 'image/png')
            return response('<title>SOTO ST-300</title>')
        product['imageUrl'] = 'https://images.example/0.png'
        complete = Catalog(ENV, fetch, {'p0': [hint]}).gather(
            {'productIds': ['p0']}, {'products': [product]})
        self.assertTrue(complete['evidence']['products'][0]['facts'])
        self.assertIn(product['imageUrl'], calls)
        self.assertIn(product['affiliateUrl'], calls)
        self.assertFalse(any('api.search.brave.com' in url or 'openapi.rakuten.co.jp' in url for url in calls))
        calls.clear()
        product['imageUrl'] = 'https://images.example/other.png'
        Catalog(ENV, fetch, {'p0': [hint]}).gather({'productIds': ['p0']}, {'products': [product]})
        self.assertTrue(any('api.search.brave.com' in url for url in calls))
        self.assertTrue(any('openapi.rakuten.co.jp' in url for url in calls))
        calls.clear()
        product['imageUrl'] = 'https://images.example/0.png'
        product['specs']['weight'] = '201g'
        Catalog(ENV, fetch, {'p0': [hint]}).gather({'productIds': ['p0']}, {'products': [product]})
        self.assertTrue(any('api.search.brave.com' in url for url in calls))

    def test_gather_rejects_structured_model_contradiction_despite_matching_title(self):
        from catalog import _primary_identity
        html = ('<title>SOTO ST-310</title><article class="pdContents"><section class="pdContents__info">'
                '<dl class="pd__specification"><li><h3>型番</h3><p>ST-340</p></li>'
                '<li><h3>重量</h3><p>380g</p></li></dl></section></article>')
        page = _Page(html)
        self.assertIsNone(_primary_identity(page, 'ST-310', 'SOTO'))
        self.assertIsNone(_spec_evidence(page, 'ST-310', '重量', '380g', primary_identity=True, brand='SOTO'))
        product = products()[0]
        product.update(name='SOTO ST-310', specs={'model': 'ST-310', '重量': '380g'})
        hint = 'https://soto.shinfuji.co.jp/products/st-310/'
        ctx = Catalog({}, lambda url, *_: response(html if url == hint else ''),
                      {'p0': [hint]}).gather({'productIds': ['p0']}, {'products': [product]})
        evidence = ctx['evidence']['products'][0]
        self.assertFalse(evidence['facts'])
        self.assertFalse(next(c for c in evidence['claims'] if c['field'] == '重量')['verified'])
        self.assertFalse(any(r['kind'] == 'manufacturer-spec' for r in ctx['references']))

    def test_related_h2_model_and_dl_cannot_supply_primary_soto_spec(self):
        from catalog import _primary_identity
        html = ('<title>SOTO ST-310</title><article class="pdContents"><section class="pdContents__info">'
                '<dl class="pd__specification"><li><h3>重量</h3><p>200g</p></li></dl>'
                '</section><h2>SOTO ST-340</h2><dl><dt>最大火力</dt><dd>3.3kW</dd></dl></article>')
        page = _Page(html)
        self.assertEqual(_primary_identity(page, 'ST-310', 'SOTO'), 'title')
        self.assertIsNone(_spec_evidence(page, 'ST-310', '最大火力', '3.3kW',
                                          primary_identity=True, brand='SOTO'))
        self.assertIsNone(_primary_identity(_Page('<title>SOTO ST-310</title><h2>SOTO ST-340</h2>'
                                                 '<dl><dt>最大火力</dt><dd>3.3kW</dd></dl>'), 'ST-310', 'SOTO'))
        product = products()[0]
        product.update(name='SOTO ST-310', specs={'model': 'ST-310', '重量': '200g', '最大火力': '3.3kW'})
        hint = 'https://soto.shinfuji.co.jp/products/st-310/'
        ctx = Catalog({}, lambda url, *_: response(html if url == hint else ''), {'p0': [hint]}).gather(
            {'productIds': ['p0']}, {'products': [product]})
        self.assertFalse(ctx['evidence']['products'][0]['facts'])
        self.assertFalse(next(c for c in ctx['evidence']['products'][0]['claims'] if c['field'] == '最大火力')['verified'])

    def test_generic_maker_keeps_exact_same_row_model_proof(self):
        from catalog import _primary_identity
        page = _Page('<title>Coleman ST-310 Stove</title><dl><dt>model</dt><dd>ST-310</dd>'
                     '<dt>weight</dt><dd>350g</dd></dl>')
        self.assertEqual(_primary_identity(page, 'ST-310', 'Coleman'), 'title')
        self.assertIsNotNone(_spec_evidence(page, 'ST-310', 'weight', '350g',
                                             primary_identity=True, brand='Coleman'))

    def test_snowpeak_and_uniflame_ignore_specs_outside_primary_container(self):
        from catalog import _primary_identity
        snow = _Page('<title>スノーピーク HOME＆CAMP バーナー</title><div id="tab-size">'
                     '<dl><dt>メーカー品番</dt><dd>GS-600KH</dd></dl>'
                     '<dl><dt>重量</dt><dd>1.4kg</dd></dl></div>'
                     '<div id="related"><dl><dt>最大火力</dt><dd>3.3kW</dd></dl></div>')
        self.assertEqual(_primary_identity(snow, 'GS-600KH', 'スノーピーク'), 'メーカー品番')
        self.assertIsNone(_spec_evidence(snow, 'GS-600KH', '最大火力', '3.3kW',
                                          primary_identity=True, brand='スノーピーク'))
        uniflame = _Page('<title>ユニフレーム US-1900</title><article id="product">'
                         '<ul class="item-spec"><li><dl><dt>重量</dt><dd>約3.9kg</dd></dl></li></ul>'
                         '<ul class="item-char"><li><dl><dt>最大火力</dt><dd>3,900kcal/h</dd></dl></li></ul>'
                         '</article><footer><dl><dt>点火方式</dt><dd>圧電点火</dd></dl></footer>')
        self.assertEqual(_primary_identity(uniflame, 'US-1900', 'ユニフレーム'), 'title')
        self.assertIsNotNone(_spec_evidence(uniflame, 'US-1900', '重量', '約3.9kg',
                                             primary_identity=True, brand='ユニフレーム'))
        for key, value in [('最大火力', '3,900kcal/h'), ('点火方式', '圧電点火')]:
            self.assertIsNone(_spec_evidence(uniflame, 'US-1900', key, value,
                                              primary_identity=True, brand='ユニフレーム'))

    def test_yahoo_search_title_match_is_not_a_verified_purchase_destination(self):
        product = products()[0]
        product['yahooUrl'] = 'https://shopping.yahoo.co.jp/search?p=SOTO+ST-300'
        ctx = Catalog({}, lambda *a: response('<title>SOTO ST-300</title>')).gather(
            {'productIds': ['p0']}, {'products': [product]})
        destination = next(d for d in ctx['evidence']['products'][0]['destinations'] if d['channel'] == 'yahoo')
        self.assertFalse(destination['verified'])

    def test_readonly_explicit_fields_and_no_click_personal_data(self):
        calls = []
        def fetch(url, headers, timeout):
            calls.append((url, headers))
            table = urlsplit(url).path.split('/')[-1]
            return response(json.dumps([{'id': 'p', 'image_url': 'https://img.example/p', 'category_id': 'c'}] if table == 'products' else []), 'application/json')
        result = Catalog(ENV, fetch).catalog()
        self.assertEqual(set(result), {'articles', 'products', 'categories', 'clicks'})
        self.assertEqual(result['products'][0]['imageUrl'], 'https://img.example/p')
        for url, _ in calls:
            fields = parse_qs(urlsplit(url).query)['select'][0]
            self.assertNotIn('*', fields)
            self.assertFalse({'ip', 'ua'} & set(fields.split(',')))
        self.assertEqual(len(calls), 4)

    def test_secret_errors_and_health(self):
        def fail(*args):
            raise RuntimeError('SECRET BRAVE APP KEY')
        c = Catalog(ENV, fail)
        with self.assertRaisesRegex(CatalogError, '^catalog request failed$'):
            c.catalog()
        health = c.health()
        self.assertTrue(health['envKeys']['BRAVE_API_KEY'])
        self.assertNotIn('SECRET', json.dumps(health))

    def test_ssrf_rejects_private_dns_and_unsafe_literals(self):
        for url in ['http://example.com', 'https://user:pass@example.com', 'https://127.1',
                    'https://127.0.0.1', 'https://[::ffff:127.0.0.1]', 'https://localhost', 'https://x.local']:
            with self.subTest(url=url), self.assertRaises(CatalogError):
                safe_url(url)
        with patch('catalog.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('10.0.0.1', 443))]):
            with self.assertRaises(CatalogError):
                safe_url('https://public.example')

    def test_model_requires_full_boundary_not_shared_word(self):
        self.assertFalse(model_matches('ST-310', 'SOTO Stove ST-3100'))
        self.assertFalse(model_matches('', 'SOTO Stove'))
        self.assertTrue(model_matches('ST-310', 'SOTO ST-310 Stove'))

    def test_gather_fail_closed_unknown_mixed_and_missing_proof(self):
        cat = dict(products=products(), articles=[], categories=[], clicks=[])
        c = Catalog({}, lambda *a: response('unrelated'))
        ctx = c.gather({'productIds': ['p0', 'p1', 'p2']}, cat)
        self.assertEqual(ctx['checks'], dict(facts=False, images=False, affiliate=False))
        self.assertTrue(ctx['blocked'])
        self.assertEqual(ctx['products'], cat['products'])
        for ids in [['p0', 'p1', 'new'], [], ['p0'] * 3]:
            with self.assertRaises(CatalogError):
                c.gather({'productIds': ids}, cat)
        mixed = copy.deepcopy(cat)
        mixed['products'][0]['categoryId'] = 'tent'
        with self.assertRaises(CatalogError):
            c.gather({'productIds': ['p0', 'p1', 'p2']}, mixed)

    def test_verified_image_bytes_and_maker_model_specs_evidence(self):
        def fetch(url, headers, timeout):
            if 'api.search.brave' in url:
                i = parse_qs(urlsplit(url).query)['q'][0].split('ST-30')[1][0]
                return response(json.dumps({'web': {'results': [{'url': f'https://soto.shinfuji.co.jp/products/st30{i}/'}]}}), 'application/json')
            if 'app.rakuten' in url or 'openapi.rakuten' in url:
                return response('{"Items":[]}', 'application/json')
            if 'images.example' in url:
                return response(PNG, 'image/png')
            i = urlsplit(url).path.rstrip('/').split('st30')[-1]
            if not i.isdigit():
                return response('missing')
            return response(f'<title>SOTO ST-30{i} Stove</title><article class="pdContents">'
                            f'<section class="pdContents__info"><dl class="pd__specification">'
                            f'<li><h3>weight</h3><p>200g</p></li></dl></section></article>'
                            f'<img src="https://images.example/{i}.png">')
        ctx = Catalog(ENV, fetch).gather({'productIds': ['p0', 'p1', 'p2']}, dict(products=products()))
        self.assertTrue(ctx['checks']['facts'])
        self.assertTrue(ctx['checks']['images'])
        self.assertEqual(ctx['images'][0]['sha256'], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(ctx['images'][0]['size'], len(PNG))
        self.assertTrue(ctx['references'][0]['checkedAt'].endswith('+09:00'))
        self.assertNotIn('BRAVE', json.dumps(ctx))

    def test_redirect_private_target_blocked_even_injected(self):
        c = Catalog({}, lambda *a: response('', status=302, headers={'location': 'https://127.0.0.1/secret'}))
        with self.assertRaises(CatalogError):
            c.request('https://example.com')

    def test_pinned_transport_tries_second_validated_public_address(self):
        public = [(10, 1, 6, '', ('2001:4860:4860::8888', 443)),
                  (2, 1, 6, '', ('8.8.8.8', 443))]
        with patch('catalog.socket.getaddrinfo', return_value=public), patch('catalog._PinnedHTTPS') as conn:
            instance = conn.return_value
            instance.request.side_effect = [OSError(65, 'No route to host'), None]
            result = instance.getresponse.return_value
            result.status = 200
            result.getheaders.return_value = [('content-type', 'text/html')]
            result.read.return_value = b'<title>OK</title>'
            fetched = Catalog({}).request('https://maker.example/item')
            self.assertEqual(fetched['body'], b'<title>OK</title>')
            self.assertEqual([call.args[1] for call in conn.call_args_list],
                             ['2001:4860:4860::8888', '8.8.8.8'])

    def test_secret_reflection_never_leaves_context_or_authenticated_redirect(self):
        secret = 'private-service-role-test-token'
        c = Catalog(dict(ENV, SUPABASE_SERVICE_ROLE_KEY=secret), lambda *a: response(''))
        cat = dict(products=products())
        cat['products'][0]['description'] = secret
        with self.assertRaises(CatalogError):
            c.gather({'productIds': ['p0', 'p1', 'p2']}, cat)
        redirected = Catalog(ENV, lambda *a: response('', status=302, headers={'location': 'https://other.example/'}))
        with self.assertRaises(CatalogError):
            redirected.request('https://openapi.rakuten.co.jp/api?applicationId=APP&accessKey=KEY')

    def test_gather_bounds_article_context_and_clicks_to_selected_products(self):
        cat = dict(products=products(), articles=[{'id': str(i), 'slug': str(i), 'title': 'title', 'content': 'x' * 10000,
                    'categoryId': 'stove', 'status': 'published'} for i in range(20)],
                   clicks=[{'productId': 'unselected', 'store': 'amazon'}, {'productId': 'p0', 'store': 'rakuten'}])
        ctx = Catalog({}, lambda *a: response('')).gather({'productIds': ['p0', 'p1', 'p2']}, cat)
        self.assertLessEqual(len(ctx['existingArticles']), 5)
        self.assertTrue(all('content' not in a for a in ctx['existingArticles']))
        self.assertEqual(ctx['merchantClicks'], [{'productId': 'p0', 'store': 'rakuten', 'clicks': 1}])

    def test_fake_image_headers_and_invalid_affiliate_account_fail(self):
        self.assertIsNone(_image_type(b'\x89PNG\r\n\x1a\n' + b'x' * 100))
        self.assertIsNone(_image_type(PNG[:-4] + b'fail'))
        self.assertEqual(_image_type(PNG), 'image/png')
        self.assertFalse(_affiliate_route('rakuten', 'https://item.rakuten.co.jp/shop/item/', {}))
        self.assertFalse(_affiliate_route('amazon', 'https://www.amazon.co.jp/dp/B012345678?tag=other-22', {'AMAZON_PARTNER_TAG': 'owner-22'}))
        self.assertTrue(_affiliate_route('amazon', 'https://www.amazon.co.jp/dp/B012345678?tag=owner-22', {'AMAZON_PARTNER_TAG': 'owner-22'}))

    def test_public_affiliate_ids_app_id_and_short_values_are_not_secrets(self):
        env = dict(ENV, RAKUTEN_AFFILIATE_ID='public-owner-id', AMAZON_PARTNER_TAG='public-tag-22',
                   RAKUTEN_APP_ID='100', RAKUTEN_ACCESS_KEY='short')
        cat = dict(products=products())
        for p in cat['products']:
            p['affiliateUrl'] = 'https://hb.afl.rakuten.co.jp/ichiba/public-owner-id/?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fa%2Fb%2F'
            p['amazonUrl'] = 'https://www.amazon.co.jp/dp/B012345678?tag=public-tag-22'
            p['description'] = '100 short description'
        ctx = Catalog(env, lambda *a: response('unverified')).gather({'productIds': ['p0', 'p1', 'p2']}, cat)
        self.assertEqual(ctx['products'], cat['products'])
        for key in ('SUPABASE_SERVICE_ROLE_KEY', 'BRAVE_API_KEY', 'RAKUTEN_ACCESS_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY'):
            secret = 'private-api-token-for-test-' + key
            with self.subTest(key=key), self.assertRaisesRegex(CatalogError, 'credential reflection refused'):
                Catalog({key: secret})._public({'text': secret})

    def test_spec_requires_model_and_named_value_in_same_small_unit(self):
        for html in [
            '<title>SOTO ST-310</title><p>ST-310 weight: 200g</p><p>ST-320 weight: 350g</p>',
            '<p>ST-310 weight: 200g; packed weight: 350g</p>',
            '<p>ST-310</p><p>weight: 350g</p>',
            '<tr><td>ST-310</td><td>ST-320</td><td>weight</td><td>350g</td></tr>',
            '<dl><dt>model</dt><dd>ST-310</dd><dt>weight</dt><dd>200g</dd></dl><dl><dt>model</dt><dd>ST-320</dd><dt>weight</dt><dd>350g</dd></dl>',
        ]:
            with self.subTest(html=html):
                self.assertIsNone(_spec_evidence(_Page(html), 'ST-310', 'weight', '350g'))
        for html in [
            '<tr><th>ST-310</th><th>weight</th><td>350g</td></tr>',
            '<dl><dt>model</dt><dd>ST-310</dd><dt>重量</dt><dd>350g</dd></dl>',
            '<p>ST-310 重量：350g</p>',
        ]:
            with self.subTest(html=html):
                self.assertIsNotNone(_spec_evidence(_Page(html), 'ST-310', 'weight', '350g'))

    def test_explicit_guide_one_or_two_products_auto_selection_still_needs_three(self):
        cat = {'products': products()}
        c = Catalog({}, lambda *a: response('unverified'))
        for ids in [['p0'], ['p0', 'p1']]:
            self.assertEqual(c.gather({'productIds': ids}, cat)['productIds'], ids)
        with self.assertRaises(CatalogError):
            c.gather({'categoryId': 'stove'}, {'products': products()[:2]})
        self.assertEqual(len(c.gather({'categoryId': 'stove'}, cat)['catalog']), 3)

    def test_gather_rejects_other_product_weight_even_when_title_matches(self):
        def fetch(url, headers, timeout):
            if 'api.search.brave' in url:
                i = parse_qs(urlsplit(url).query)['q'][0].split('ST-30')[1][0]
                return response(json.dumps({'web': {'results': [{'url': f'https://soto.shinfuji.co.jp/st30{i}/'}]}}), 'application/json')
            if 'openapi.rakuten' in url:
                return response('{"Items":[]}', 'application/json')
            if 'images.example' in url:
                return response(PNG, 'image/png')
            i = urlsplit(url).path.rstrip('/').split('st30')[-1]
            if not i.isdigit():
                return response('missing')
            return response(f'<title>SOTO ST-30{i}</title><p>model: ST-30{i}; weight: 200g</p><p>ST-999 weight: 350g</p>')
        ps = products()
        for p in ps:
            p['specs']['weight'] = '350g'
        ctx = Catalog(ENV, fetch).gather({'productIds': ['p0', 'p1', 'p2']}, {'products': ps})
        self.assertFalse(ctx['checks']['facts'])
        for p in ctx['evidence']['products']:
            self.assertFalse(next(c for c in p['claims'] if c['field'] == 'weight')['verified'])

    def test_image_digest_rejects_oversize_and_rechecks_redirect_dns_before_connect(self):
        c = Catalog({}, lambda *a: response(PNG + b'x' * (8 * 1024 * 1024), 'image/png'))
        with self.assertRaises(CatalogError):
            c.image_digest('https://images.example/a.png')
        c = Catalog({}, lambda *a: response(PNG, 'image/png'))
        self.assertEqual(c.image_digest('https://images.example/a.png')['sha256'], hashlib.sha256(PNG).hexdigest())
        public = [(2, 1, 6, '', ('8.8.8.8', 443))]
        private = [(2, 1, 6, '', ('10.0.0.1', 443))]
        with patch('catalog.socket.getaddrinfo', side_effect=[public, private]) as dns, patch('catalog._PinnedHTTPS') as conn:
            res = conn.return_value.getresponse.return_value
            res.status = 302
            res.getheaders.return_value = [('location', 'https://other.example/private.png')]
            res.read.return_value = b''
            with self.assertRaises(CatalogError):
                Catalog({}).image_digest('https://images.example/a.png')
            self.assertEqual(dns.call_count, 2)
            self.assertEqual(conn.call_count, 1)
            self.assertEqual(conn.call_args[0], ('images.example', '8.8.8.8'))


if __name__ == '__main__':
    unittest.main()
