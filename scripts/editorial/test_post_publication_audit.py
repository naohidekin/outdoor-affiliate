"""Offline contracts: public bytes, identity, transport failures and isolation."""
import copy
import hashlib
import json
import struct
import unittest
import zlib
from unittest.mock import patch

from catalog import Catalog
from post_publication_audit import PostPublicationAudit, _merchant_identity, _audit_model


SITE = 'https://camp-gear-lab.com/articles/stove'
AMAZON = 'https://www.amazon.co.jp/dp/B012345678?tag=owner-22'
RAKUTEN = 'https://hb.afl.rakuten.co.jp/ichiba/owner/shop?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fshop%2Fst310%2F'
ENV = {'AMAZON_PARTNER_TAG': 'owner-22', 'RAKUTEN_AFFILIATE_ID': 'owner', 'SECRET': 'do-not-output'}
def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
PNG = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b''))
DIGEST = hashlib.sha256(PNG).hexdigest()


def fixture():
    body = '## Stove\n\nApproved body.\n\n{{product:p1}}'
    digest = hashlib.sha256(body.encode()).hexdigest()
    product = {'id': 'p1', 'name': 'SOTO ST-310', 'brand': 'SOTO', 'categoryId': 'burner', 'specs': {'model': 'ST-310'},
               'imageUrl': 'https://images.example/stove.png', 'amazonUrl': AMAZON, 'affiliateUrl': RAKUTEN}
    bundle = {'article': {'title': 'Approved title', 'slug': 'stove', 'content': body, 'productIds': ['p1']},
              'products': [product], 'images': [{'productId': 'p1', 'url': product['imageUrl'],
              'verified': True, 'sha256': DIGEST, 'size': len(PNG), 'contentType': 'image/png'}]}
    html = f'<html><head></head><body><main><article data-review-content-sha256="{digest}"><h1>Approved title</h1><div class="article-body"><h2>Stove</h2><p>Approved body.</p></div></article></main></body></html>'
    return {'bundle': bundle, 'publication': {'url': SITE, 'contentHash': digest, 'verified': True}}, html


class FakeCatalog:
    def __init__(self, html):
        self.html, self.calls, self.merchant = html, [], '<title>SOTO ST-310 stove</title>'

    def request(self, url, headers=None, allowed_domains=None, exact_domains=False):
        self.calls.append((url, headers, allowed_domains))
        if url == SITE:
            return {'url': url, 'status': 200, 'headers': {'content-type': 'text/html'}, 'body': self.html.encode()}
        if url == 'https://images.example/stove.png':
            return {'url': url, 'status': 200, 'headers': {'content-type': 'image/png'}, 'body': PNG}
        final = AMAZON if url == AMAZON else 'https://item.rakuten.co.jp/shop/st310/'
        return {'url': final, 'status': 200, 'headers': {'content-type': 'text/html; charset=EUC-JP'},
                'body': self.merchant.encode('euc_jp')}

    def image_digest(self, url):
        return {'sha256': 'a' * 64, 'size': 100, 'contentType': 'image/png'}


class AuditTests(unittest.TestCase):
    def run_audit(self, job=None, html=None, catalog=None, browser=None):
        original, source = fixture()
        audit = PostPublicationAudit({'repo': '/unused'}, ENV, catalog=catalog or FakeCatalog(html or source))
        with patch.object(audit, '_browser', return_value=browser or {'checks': [
                {'name': 'desktop', 'status': 'passed', 'reason': 'render_verified'},
                {'name': 'mobile', 'status': 'passed', 'reason': 'render_verified'}]}):
            return audit.check(job or original)

    def test_matching_public_bytes_images_and_both_merchants_pass(self):
        result = self.run_audit()
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['issues'], [])
        self.assertNotIn('do-not-output', json.dumps(result))

    def test_hydration_cannot_supply_public_title_or_hash(self):
        job, html = fixture()
        for source in ['<script>' + html + '</script>', '<template>' + html + '</template>',
                       '<!--' + html + '-->', html.replace('<article ', '<aside ').replace('</article>', '</aside>')]:
            with self.subTest(source=source[:15]):
                self.assertEqual(self.run_audit(job, source)['status'], 'failed')

    def test_wrong_body_hash_or_title_fails(self):
        job, html = fixture()
        for source in [html.replace(job['publication']['contentHash'], '0' * 64),
                       html.replace('Approved title', 'Different title')]:
            self.assertEqual(self.run_audit(job, source)['status'], 'failed')

    def test_network_failure_unverified_never_browser_bypass(self):
        job, _ = fixture()
        catalog = FakeCatalog('')
        catalog.request = lambda *a, **k: (_ for _ in ()).throw(ValueError('SECRET raw provider error'))
        result = self.run_audit(job, catalog=catalog)
        self.assertEqual(result['status'], 'unverified')
        self.assertNotIn('SECRET', json.dumps(result))

    def test_wrong_merchant_title_fails_even_correct_asin(self):
        _, html = fixture()
        catalog = FakeCatalog(html)
        catalog.merchant = '<title>SOTO ST-330 stove B012345678</title>'
        self.assertEqual(self.run_audit(catalog=catalog)['status'], 'failed')

    def test_accessory_only_title_and_missing_product_type_rejected(self):
        _, html = fixture()
        for title in ('SOTO ST-310 専用収納ケース（本体は含まれません）',
                      'SOTO ST-310 compatible stove carrying case only', 'SOTO ST-310 sale'):
            catalog = FakeCatalog(html)
            catalog.merchant = '<title>' + title + '</title>'
            result = self.run_audit(catalog=catalog)
            self.assertEqual(result['status'], 'failed', title)

    def test_actual_amicus_single_konro_title_is_positive_type_identity(self):
        product = {'name': 'SOTO アミカス SOD-320 シングルバーナー', 'brand': 'SOTO', 'categoryId': 'burner'}
        title = '【楽天市場】ソト アミカス (SOD-320) キャンプ シングルコンロ SOTO：アルペン楽天市場店'
        self.assertTrue(_merchant_identity(product, 'SOD-320', title))
        self.assertFalse(_merchant_identity(product, 'SOD-320', title + ' 専用収納ケース（本体は含まれません）'))

    def test_firepit_titles_allow_brand_parentheses_and_intervening_words(self):
        p = {'name': 'ユニフレーム ファイアグリル', 'brand': 'ユニフレーム', 'categoryId': 'firepit'}
        self.assertTrue(_merchant_identity(p, '683040', 'Amazon | ユニフレーム(UNIFLAME) ファイアグリル 683040 | キャンプ用グリル・焚火台'))
        p = {'name': 'スノーピーク 焚火台L', 'brand': 'スノーピーク', 'categoryId': 'firepit'}
        self.assertTrue(_merchant_identity(p, 'ST-032RS', 'スノーピーク 焚き火台 焚火台 L 3-4人用 ST-032RS snow peak'))
        self.assertFalse(_merchant_identity(p, 'ST-032RS', 'スノーピーク ST-032R 焚火台'))
        self.assertFalse(_merchant_identity(p, 'ST-032RS', 'スノーピーク ST-032RS 専用収納ケース'))

    def test_firepit_accessory_only_titles_fail_the_full_audit(self):
        job, html = fixture()
        job['bundle']['products'][0].update(name='ユニフレーム ファイアグリル 683040',
            brand='ユニフレーム', categoryId='firepit', specs={'型番': '683040'})
        for title in ('ユニフレーム 683040 焚火台用 焼き網',
                      'ユニフレーム 683040 焚火台用 ロストル',
                      'ユニフレーム 683040 焚き火台 用 焼き網'):
            with self.subTest(title=title):
                catalog = FakeCatalog(html)
                catalog.merchant = '<title>' + title + '</title>'
                result = self.run_audit(job, catalog=catalog)
                self.assertFalse(result['passed'], result)
                self.assertEqual('failed', result['status'], result)
                destinations = [c for c in result['checks'] if c['name'].startswith('destination.')]
                self.assertEqual(2, len(destinations))
                self.assertTrue(all(c['status'] == 'failed' and c['reason'] ==
                    'merchant_destination_or_product_identity_mismatch' for c in destinations), result)
                self.assertTrue(all(c['status'] == 'passed' for c in result['checks']
                                    if not c['name'].startswith('destination.')), result)

    def test_genuine_firepit_and_body_with_accessory_bundles_pass_full_audit(self):
        job, html = fixture()
        job['bundle']['products'][0].update(name='ユニフレーム ファイアグリル 683040',
            brand='ユニフレーム', categoryId='firepit', specs={'型番': '683040'})
        for title in ('ユニフレーム(UNIFLAME) ファイアグリル 683040 キャンプ用グリル・焚火台',
                      'ユニフレーム 683040 焚火台本体 焼き網・ロストル付き',
                      'ユニフレーム 683040 焚火台本体＋焚火台用 焼き網・ロストルセット'):
            with self.subTest(title=title):
                catalog = FakeCatalog(html)
                catalog.merchant = '<title>' + title + '</title>'
                result = self.run_audit(job, catalog=catalog)
                self.assertTrue(result['passed'], result)
                self.assertEqual('passed', result['status'])

    def test_explicit_alphabetic_model_is_not_discarded(self):
        p = {'name': 'TokyoCamp 焚火台 HAKOSUKA', 'brand': 'TokyoCamp', 'categoryId': 'firepit', 'specs': {'型番': 'HAKOSUKA'}}
        self.assertEqual(_audit_model(p), 'HAKOSUKA')
        self.assertTrue(_merchant_identity(p, _audit_model(p), 'Tokyo Camp 焚き火台 HAKOSUKA コンパクト'))
        self.assertFalse(_merchant_identity(p, _audit_model(p), 'Tokyo Camp 焚き火台 マクライト'))
        self.assertEqual(_audit_model(dict(p, specs={'型番': 'OTHER'})), '')

    def test_named_model_absent_from_merchant_is_unverified(self):
        job, html = fixture()
        p = job['bundle']['products'][0]
        p.update(name='TokyoCamp 焚火台 HAKOSUKA', brand='TokyoCamp', categoryId='firepit', specs={'型番': 'HAKOSUKA'})
        cat = FakeCatalog(html)
        cat.merchant = '<title>Tokyo Camp 焚き火台 コンパクト</title>'
        result = self.run_audit(job, catalog=cat)
        self.assertEqual(result['status'], 'unverified')
        self.assertTrue(any(c['reason'] == 'merchant_model_evidence_missing' for c in result['checks']))

    def test_conflicting_firepit_size_is_unverified(self):
        job, html = fixture()
        p = job['bundle']['products'][0]
        p.update(name='スノーピーク 焚火台L', brand='スノーピーク', categoryId='firepit', specs={'型番': 'ST-032RS'})
        cat = FakeCatalog(html)
        cat.merchant = '<title>スノーピーク 焚火台 L ST-032RS 焚き火台 Sサイズ</title>'
        result = self.run_audit(job, catalog=cat)
        self.assertEqual(result['status'], 'unverified')
        self.assertTrue(any(c['reason'] == 'merchant_variant_evidence_conflicting' for c in result['checks']))

    def test_missing_merchant_or_model_is_unverified(self):
        for field in ('amazonUrl', 'affiliateUrl', 'specs'):
            job, _ = fixture()
            job['bundle']['products'][0].pop(field)
            if field == 'specs':
                job['bundle']['products'][0]['name'] = 'SOTO stove'
            self.assertEqual(self.run_audit(job)['status'], 'unverified')

    def test_unsafe_or_different_site_public_url_rejected_before_fetch(self):
        for url in ('http://127.0.0.1/x', 'https://evil.example/articles/stove', SITE + '?token=secret'):
            job, html = fixture()
            job['publication']['url'] = url
            catalog = FakeCatalog(html)
            self.assertEqual(self.run_audit(job, catalog=catalog)['status'], 'failed')
            self.assertEqual(catalog.calls, [])

    def test_image_mismatch_and_browser_unverified_fail_closed(self):
        job, html = fixture()
        catalog = FakeCatalog(html)
        job['bundle']['images'][0]['sha256'] = 'b' * 64
        self.assertEqual(self.run_audit(job, catalog=catalog)['status'], 'failed')
        result = self.run_audit(browser={'checks': [{'name': 'desktop', 'status': 'unverified', 'reason': 'browser_unavailable'}]})
        self.assertFalse(result['passed'])

    def test_social_manifest_required_only_when_bound(self):
        job, html = fixture()
        job['bundle']['article']['generationMeta'] = {'socialCard': {'url': 'https://images.example/card.png'}}
        self.assertEqual(self.run_audit(job, html)['status'], 'failed')

    def test_catalog_blocks_private_redirect_and_does_not_send_credentials(self):
        job, html = fixture()
        calls = []
        def fetch(url, headers, timeout):
            calls.append((url, headers))
            return {'status': 302, 'headers': {'location': 'https://127.0.0.1/private'}, 'body': b''}
        result = self.run_audit(job, catalog=Catalog(ENV, fetcher=fetch))
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {'Accept': 'text/html', 'Cache-Control': 'no-cache'})

    def test_rakuten_exact_tracking_redirect_allowed_but_not_sibling(self):
        job, html = fixture()
        for redirect, expected in [('pt.afl.rakuten.co.jp', 'passed'), ('other.afl.rakuten.co.jp', 'unverified')]:
            def fetch(url, headers, timeout):
                if url == SITE:
                    return {'status': 200, 'headers': {'content-type': 'text/html'}, 'body': html.encode()}
                if url == 'https://images.example/stove.png':
                    return {'status': 200, 'headers': {'content-type': 'image/png'}, 'body': PNG}
                if url == RAKUTEN:
                    return {'status': 302, 'headers': {'location': 'https://' + redirect + '/route'}, 'body': b''}
                if url.startswith('https://' + redirect):
                    return {'status': 302, 'headers': {'location': 'https://item.rakuten.co.jp/shop/st310/'}, 'body': b''}
                return {'status': 200, 'headers': {'content-type': 'text/html'}, 'body': b'<title>SOTO ST-310 stove</title>'}
            catalog = Catalog({}, fetcher=fetch)
            catalog.image_digest = FakeCatalog(html).image_digest
            result = self.run_audit(job, catalog=catalog)
            self.assertEqual(next(c['status'] for c in result['checks'] if c['name'] == 'destination.0.rakuten'), expected)

    def test_image_redirect_unapproved_public_host_never_contacted(self):
        job, html = fixture()
        calls = []
        def fetch(url, headers, timeout):
            calls.append(url)
            if url == SITE:
                return {'status': 200, 'headers': {'content-type': 'text/html'}, 'body': html.encode()}
            if url == 'https://images.example/stove.png':
                return {'status': 302, 'headers': {'location': 'https://unapproved.example/stove.png'}, 'body': b''}
            return {'status': 200, 'headers': {'content-type': 'text/html'}, 'body': b'<title>SOTO ST-310 stove</title>'}
        result = self.run_audit(job, catalog=Catalog({}, fetcher=fetch))
        self.assertEqual(next(c['status'] for c in result['checks'] if c['name'] == 'image.0'), 'unverified')
        self.assertNotIn('https://unapproved.example/stove.png', calls)

    def test_image_redirect_unapproved_subdomain_never_contacted(self):
        job, html = fixture()
        calls = []
        redirected = 'https://unapproved.images.example/stove.png'
        def fetch(url, headers, timeout):
            calls.append(url)
            if url == SITE:
                return {'status': 200, 'headers': {'content-type': 'text/html'}, 'body': html.encode()}
            if url == 'https://images.example/stove.png':
                return {'status': 302, 'headers': {'location': redirected}, 'body': b''}
            if url == redirected:
                return {'status': 200, 'headers': {'content-type': 'image/png'}, 'body': PNG}
            return {'status': 200, 'headers': {'content-type': 'text/html'}, 'body': b'<title>SOTO ST-310 stove</title>'}
        result = self.run_audit(job, catalog=Catalog({}, fetcher=fetch))
        self.assertEqual(next(c['status'] for c in result['checks'] if c['name'] == 'image.0'), 'unverified')
        self.assertNotIn(redirected, calls)


if __name__ == '__main__':
    unittest.main()
