"""Rakuten filename-free apparel images require scoped metadata and decoded bytes."""
import binascii
import copy
import hashlib
import json
import struct
import unittest
import zlib

from apparel_identity import binding_matches_product, inspect_apparel_page, public_binding
from catalog import Catalog, CatalogError, verify_apparel_merchant_raster
from post_publication_audit import _apparel_merchant_identity


URL = 'https://item.rakuten.co.jp/spray/1101539-2627/'
IMAGE = 'https://tshop.r10s.jp/spray/cabinet/12601790/imgrc0122448935.jpg'
OG = 'https://shop.r10s.jp/spray/cabinet/12601790/imgrc0122448935.jpg'


def product():
    return {
        'id': 'active-layer-montbell-1101539',
        'name': "U.L. Thermawrap Jacket Men's",
        'brand': 'mont-bell', 'categoryId': 'active-layer',
        'specs': {'model': '1101539', 'apparelClass': 'active-layer',
                  'gender': "Men's", 'fabric': 'nylon', 'weight': '229g',
                  'optionState': 'selectable', 'rakutenOptionState': 'selectable'},
        'imageUrl': 'https://webshop.montbell.jp/images/1101539-bk.jpg',
        'affiliateUrl': URL,
    }


def png(width=400, height=400):
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', binascii.crc32(kind + data) & 0xffffffff))
    rows = b''.join(b'\0' + b'\x22\x55\x88' * width for _ in range(height))
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(
        b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def source(*, sku='spray:1101539-2627', images=None, og=OG,
           recommendation_image=None, duplicate_primary=False):
    images = list(images if images is not None else [
        'https://tshop.r10s.jp/spray/cabinet/12601790/imgrc01224489%02d.jpg' % n
        for n in (36, 42, 43, 37, 41, 40, 39, 38, 35)])
    title = ("【mont-bell】 モンベル 【U.L. Thermawrap Jacket Men's】 "
             'U.L.サーマラップ ジャケット メンズ #1101539 / メンズ / 男性用')
    metas = ''.join('<meta itemprop="image" content="' + image + '">' for image in images)
    node = ('<div itemscope itemtype="http://schema.org/Product">'
            f'<meta itemprop="name" content="{title}">'
            f'<meta itemprop="sku" content="{sku}">{metas}</div>')
    if duplicate_primary:
        node += node
    recommendation = ('<aside><div itemscope itemtype="http://schema.org/Product">'
                      '<meta itemprop="name" content="別商品">'
                      '<meta itemprop="sku" content="other:999">'
                      f'<meta itemprop="image" content="{recommendation_image}">'
                      '</div></aside>') if recommendation_image else ''
    selectors = {'variantSelectors': [
        {'label': 'カラー', 'values': [{'value': value} for value in ('BK', 'NV', 'OG24')]},
        {'label': 'サイズ', 'values': [{'value': value} for value in ('S', 'M', 'L', 'XL')]},
    ]}
    og_meta = f'<meta property="og:image" content="{og}">' if og else ''
    return (f'<link rel="canonical" href="{URL}">{og_meta}{node}{recommendation}'
            '<script>window.__x={"itemInfoSku":'
            + json.dumps(selectors, ensure_ascii=False) + '};</script>')


class FetchCatalog(Catalog):
    def __init__(self, body, redirect_to=None):
        self.body = body
        self.redirect_to = redirect_to
        self.calls = []
        super().__init__({}, self.fetch)

    def fetch(self, url, headers, timeout):
        self.calls.append(url)
        if self.redirect_to and url != self.redirect_to:
            return {'status': 302, 'headers': {'location': self.redirect_to},
                    'body': b''}
        return {'status': 200, 'headers': {'content-type': 'image/png'},
                'body': self.body}


class RakutenPrimaryImageTests(unittest.TestCase):
    def inspect(self, html):
        return inspect_apparel_page(product(), URL, html,
                                    source_role='purchase', channel='rakuten')

    def test_nine_image_primary_node_uses_unique_og_asset_and_decoded_proof(self):
        candidate = self.inspect(source())
        self.assertEqual([OG], candidate['imageUrls'])
        self.assertEqual('rakuten-primary-og-raster-v1', candidate['imageIdentityMode'])
        self.assertFalse(binding_matches_product(candidate, product(), 'rakuten'))
        catalog = FetchCatalog(png())
        verified = verify_apparel_merchant_raster(catalog, candidate, URL)
        self.assertTrue(binding_matches_product(verified, product(), 'rakuten'))
        self.assertEqual([OG], catalog.calls)
        proof = verified['merchantImageProof']
        self.assertEqual((OG, OG, 400, 400, 'image/png'),
                         (proof['sourceUrl'], proof['finalUrl'], proof['width'],
                          proof['height'], proof['contentType']))
        self.assertEqual(hashlib.sha256(png()).hexdigest(), proof['sha256'])

    def test_known_cdn_alias_proves_membership_but_never_authorizes_redirect(self):
        candidate = self.inspect(source())
        self.assertEqual([OG], candidate['imageUrls'])
        with self.assertRaises(CatalogError):
            verify_apparel_merchant_raster(
                FetchCatalog(png(), redirect_to=IMAGE), candidate, URL)

    def test_wrong_sku_recommendation_other_shop_missing_and_ambiguous_hold(self):
        cases = {
            'wrong-sku': source(sku='spray:wrong'),
            'recommendation-only': source(images=[], recommendation_image=IMAGE),
            'other-shop': source(images=[IMAGE.replace('/spray/', '/other/')],
                                 og=OG.replace('/spray/', '/other/')),
            'missing-image': source(images=[]),
            'missing-og': source(og=''),
            'og-not-in-node': source(og=OG.replace('8935', '9999')),
            'path-case-mismatch': source(
                images=[IMAGE.replace('imgrc0122448935', 'IMGRC0122448935')]),
            'duplicate-primary': source(duplicate_primary=True),
            'placeholder': source(
                images=['https://tshop.r10s.jp/spray/cabinet/noimage.jpg'],
                og='https://shop.r10s.jp/spray/cabinet/noimage.jpg'),
        }
        for name, html in cases.items():
            with self.subTest(name=name):
                self.assertIsNone(self.inspect(html))

    def test_malformed_or_tiny_raster_never_completes_identity(self):
        candidate = self.inspect(source())
        for body in (b'not-an-image', png(1, 1), png()[:-8]):
            with self.subTest(size=len(body)), self.assertRaises(CatalogError):
                verify_apparel_merchant_raster(FetchCatalog(body), candidate, URL)

    def test_old_filename_token_fast_path_is_unchanged_and_needs_no_extra_get(self):
        old_image = 'https://tshop.r10s.jp/spray/cabinet/1101539-main.jpg'
        binding = self.inspect(source(images=[old_image], og=''))
        self.assertNotIn('imageIdentityMode', binding)
        self.assertEqual([old_image], binding['imageUrls'])
        self.assertTrue(binding_matches_product(binding, product(), 'rakuten'))
        catalog = FetchCatalog(b'not-called')
        self.assertIs(binding, verify_apparel_merchant_raster(catalog, binding, URL))
        self.assertEqual([], catalog.calls)

    def test_post_audit_reuses_same_raster_proof_and_detects_byte_change(self):
        candidate = self.inspect(source())
        verified = verify_apparel_merchant_raster(FetchCatalog(png()), candidate, URL)
        references = [{'kind': 'purchase', 'productId': product()['id'],
                       'channel': 'rakuten', 'url': URL,
                       'apparelBinding': public_binding(verified)}]
        decision, actual = _apparel_merchant_identity(
            product(), 'rakuten', URL, source(), references, FetchCatalog(png()))
        self.assertEqual('passed', decision['status'])
        self.assertEqual(verified['merchantImageProof'], actual['merchantImageProof'])
        decision, _ = _apparel_merchant_identity(
            product(), 'rakuten', URL, source(), references, FetchCatalog(png(401, 400)))
        self.assertEqual(('failed', 'merchant_apparel_binding_mismatch'),
                         (decision['status'], decision['reason']))


if __name__ == '__main__':
    unittest.main()
