import unittest
from unittest.mock import patch
from heater_purchase_identity import is_accessory_destination


class HeaterPurchaseIdentityTests(unittest.TestCase):
    def test_actual_reflector_and_bag_urls_remain_rejected_even_with_body_title(self):
        for pid, url in (
            ('stove-paseco-wkh3100s', 'https://item.rakuten.co.jp/paseco/reflector/?tracking=x'),
            ('stove-toyotomi-rb251', 'https://item.rakuten.co.jp/minatodenk/mt-0025081/')):
            self.assertTrue(is_accessory_destination(pid, 'PASECO WKH-3100S 石油ストーブ本体', url))

    def test_compatible_model_in_accessory_title_is_not_a_heater(self):
        titles = ('PASECO WKH-3100S 専用反射板',
                  'トヨトミ レインボーストーブ専用 ストーブバッグ RBG-3 (対応機種:RB-251)',
                  'ALPACA TS-77NC 用替え芯', 'WKH-3100S carrying case',
                  'WKH-3100S 本体別売')
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(is_accessory_destination('stove-paseco-wkh3100s', title,
                                                        'https://item.rakuten.co.jp/shop/other/'))

    def test_explicit_bundled_bag_does_not_make_the_body_an_accessory(self):
        for title in ('アルパカ プラス ストーブ（専用バッグ付）TS-77NC',
                      'WKH-3100S 石油ストーブ 収納ケース付き',
                      'コイズミ 電気敷毛布 KDS-50229CT',
                      'トヨトミ レインボーストーブ RB-251'):
            with self.subTest(title=title):
                self.assertFalse(is_accessory_destination('stove-alpaca-ts77nc', title,
                                                         'https://item.rakuten.co.jp/shop/body/'))

    def test_unrelated_product_scope_is_unchanged(self):
        self.assertFalse(is_accessory_destination('a-real-carrying-bag', '収納バッグ',
                                                 'https://item.rakuten.co.jp/shop/bag/'))

    def _gather_purchase(self, final_url, title):
        from catalog import Catalog
        from test_catalog import PNG, response
        link = 'https://hb.afl.rakuten.co.jp/ichiba/owner/?pc=' + final_url
        image = 'https://images.example/heater.png'
        product = dict(id='stove-paseco-wkh3100s', name='PASECO WKH-3100S',
                       brand='PASECO', categoryId='stove', specs={'model': 'WKH-3100S'},
                       imageUrl=image, affiliateUrl=link, amazonUrl='')
        def fetch(url, *_):
            if url == link:
                return response('', status=302, headers={'location': final_url})
            if url == image:
                return response(PNG, 'image/png')
            return response('<title>' + title + '</title>')
        with patch('merchant_identity.inspect_merchant_identity', return_value={'status': 'passed'}):
            return Catalog({'RAKUTEN_AFFILIATE_ID': 'owner'}, fetch).gather(
                {'productIds': [product['id']]}, {'products': [product]})

    def test_later_positive_identity_cannot_override_accessory_rejection(self):
        value = self._gather_purchase('https://item.rakuten.co.jp/paseco/reflector/',
                                     'PASECO WKH-3100S 純正反射板')
        self.assertFalse(value['evidence']['products'][0]['destinations'][0]['verified'])
        self.assertFalse(any(r['kind'] == 'purchase' for r in value['references']))

    def test_normal_bundled_body_still_uses_existing_positive_route(self):
        value = self._gather_purchase('https://item.rakuten.co.jp/shop/body/',
                                     'PASECO WKH-3100S 石油ストーブ 専用バッグ付')
        self.assertTrue(value['evidence']['products'][0]['destinations'][0]['verified'])
