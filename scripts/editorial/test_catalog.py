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
            return response(f'<title>SOTO ST-30{i} Stove</title><p>model: ST-30{i}; weight: 200g</p><img src="https://images.example/{i}.png">')
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
