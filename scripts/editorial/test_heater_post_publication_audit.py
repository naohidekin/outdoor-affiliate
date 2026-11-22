"""Real audit destination checks; known accessory URLs, synthetic titles/HTML.

No HTTP, browser launch, credentials, persistence or production side effects.
"""
from urllib.parse import quote
import unittest
from unittest.mock import patch

from heater_purchase_identity import is_accessory_destination
from post_publication_audit import PostPublicationAudit, _merchant_observation
from test_post_publication_audit import fixture, FakeCatalog, ENV


PASECO = ('stove-paseco-wkh3100s', 'PASECO', 'WKH-3100S', 'PASECO WKH-3100S 石油ストーブ')
TOYOTOMI = ('stove-toyotomi-rb251', 'トヨトミ', 'RB-251', 'トヨトミ RB-251 石油ストーブ')
REFLECTOR = 'https://item.rakuten.co.jp/paseco/reflector/'
BAG = 'https://item.rakuten.co.jp/minatodenk/mt-0025081/'
BODY = 'https://item.rakuten.co.jp/shop/body/'


def run_audit(identity, title, final_url):
    pid, brand, model, name = identity
    job, html = fixture()
    product = job['bundle']['products'][0]
    product.update(id=pid, brand=brand, name=name, categoryId='stove', specs={'model': model},
                   affiliateUrl='https://hb.afl.rakuten.co.jp/ichiba/owner/shop?pc=' + quote(final_url, safe=''))
    job['bundle']['article']['productIds'] = [pid]
    job['bundle']['images'][0]['productId'] = pid

    class OfflineCatalog(FakeCatalog):
        def request(self, url, *args, **kwargs):
            value = super().request(url, *args, **kwargs)
            if url == product['affiliateUrl']:
                value['url'] = final_url
            return value

    catalog = OfflineCatalog(html)
    catalog.merchant = '<title>' + title + '</title>'
    audit = PostPublicationAudit({'repo': '/unused', 'slack': {'user_id': 'OWNER'}}, ENV, catalog=catalog)
    with patch.object(audit, '_browser', return_value={'checks': [
            {'name': viewport, 'status': 'passed', 'reason': 'synthetic-render'}
            for viewport in ('desktop', 'mobile')]}):
        return audit.check(job)


def destination(result, channel='rakuten'):
    return next(c for c in result['checks'] if c['name'] == 'destination.0.' + channel)


def observation(result, channel='rakuten'):
    return next(v for v in result['merchantObservations'] if v['name'] == 'destination.0.' + channel)


class HeaterPostPublicationAuditTests(unittest.TestCase):
    def test_known_accessory_urls_reject_even_body_title_and_query(self):
        for identity, url, title in (
                (PASECO, REFLECTOR + '?tracking=x', 'PASECO WKH-3100S 石油ストーブ本体'),
                (TOYOTOMI, BAG, 'トヨトミ レインボーストーブ RB-251 本体')):
            with self.subTest(url=url):
                result = run_audit(identity, title, url)
                self.assertEqual('failed', destination(result)['status'])
                self.assertEqual('merchant_accessory_only', destination(result)['reason'])
                self.assertFalse(observation(result)['identityMatched'])

    def test_compatible_model_accessory_titles_reject_on_unknown_item_url(self):
        for identity, title in (
                (PASECO, 'PASECO WKH-3100S 対流型石油ストーブ専用 純正反射板 Refector'),
                (TOYOTOMI, 'トヨトミ レインボーストーブ専用 ストーブバッグ RBG-3（対応機種: RB-251）')):
            with self.subTest(title=title):
                result = run_audit(identity, title, BODY)
                self.assertEqual('failed', destination(result)['status'])
                self.assertFalse(observation(result)['identityMatched'])

    def test_positive_title_match_or_primary_fallback_cannot_override_negative(self):
        title = 'PASECO WKH-3100S 石油ストーブ 反射板 Refector'
        for decision in ({'status': 'passed', 'reason': 'synthetic-positive'},
                         {'status': 'unverified', 'reason': 'synthetic-primary-required'}):
            with self.subTest(decision=decision), \
                    patch('merchant_identity.inspect_merchant_identity', return_value=decision), \
                    patch('primary_firepit.fixed_amazon_identity', return_value={'kind': 'synthetic-positive'}):
                result = run_audit(PASECO, title, REFLECTOR)
                for channel in ('rakuten', 'amazon'):
                    self.assertEqual('failed', destination(result, channel)['status'])
                    self.assertFalse(observation(result, channel)['identityMatched'])
                    self.assertFalse(observation(result, channel)['primaryBindingVerified'])

    def test_actual_body_with_explicit_included_bag_uses_existing_positive_checks(self):
        title = 'PASECO WKH-3100S 石油ストーブ 本体＋専用バッグ付'
        self.assertFalse(is_accessory_destination(PASECO[0], title, BODY))
        result = run_audit(PASECO, title, BODY)
        self.assertEqual('passed', destination(result)['status'])
        self.assertTrue(observation(result)['identityMatched'])

    def test_negative_guard_never_creates_positive_model_or_brand_proof(self):
        for title in ('PASECO WKH-9999 石油ストーブ 本体＋専用バッグ付',
                      'OTHER WKH-3100S 石油ストーブ 本体＋専用バッグ付'):
            with self.subTest(title=title):
                self.assertNotEqual('passed', destination(run_audit(PASECO, title, BODY))['status'])

    def test_unrelated_product_scope_and_preliminary_diagnostic(self):
        title = 'PASECO WKH-3100S 石油ストーブ本体'
        unrelated = ('other-product', *PASECO[1:])
        self.assertEqual('passed', destination(run_audit(unrelated, title, REFLECTOR))['status'])
        pid, brand, model, name = PASECO
        product = dict(id=pid, brand=brand, name=name, categoryId='stove', specs={'model': model})
        value = _merchant_observation('destination.0.rakuten', product, model, title, REFLECTOR, True)
        self.assertFalse(value['identityMatched'])
        self.assertTrue(value['modelFound'])
        self.assertTrue(value['brandFound'])


if __name__ == '__main__':
    unittest.main()
