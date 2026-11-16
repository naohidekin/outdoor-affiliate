"""Catalog apparel requests must fail closed before generic gear matching."""
import hashlib
import unittest

from catalog import Catalog
from test_catalog import PNG, response
from test_apparel_identity import product, montbell_dom


class CatalogApparelTests(unittest.TestCase):
    def test_exact_montbell_description_is_public_reference_not_catalog_certification(self):
        url = 'https://webshop.montbell.jp/goods/disp.php?product_id=1101493'
        current = product(imageUrl='https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg',
                          description='Unsupported catalogue warmth', price=999, rating=5, availability='in-stock')
        for source, expected in ((montbell_dom(), True),
                                 (montbell_dom().replace('>機能<', '>詳細<'), False),
                                 (montbell_dom().replace('value="1101493"', 'value="11014930"'), False)):
            with self.subTest(expected=expected, source=source[:100]):
                def fetch(target, *_):
                    return response(PNG, 'image/png') if target == current['imageUrl'] else response(source)
                result = Catalog({}, fetch, source_hints={current['id']: [url]}).gather(
                    {'productIds': [current['id']]}, {'products': [current]})
                refs = [ref for ref in result['references'] if ref['kind'] == 'manufacturer-description']
                self.assertEqual(int(expected), len(refs))
                if expected:
                    ref = refs[0]
                    self.assertEqual((current['id'], url, url, '1101493'),
                                     (ref['productId'], ref['url'], ref['sourceUrl'], ref['model']))
                    self.assertEqual(hashlib.sha256(ref['text'].encode('utf-8')).hexdigest(), ref['excerptSHA256'])
                    self.assertIn('ポケット2個（腰）', ref['text'])
                    self.assertNotIn('Unsupported catalogue warmth', ref['text'])
                    self.assertIn('not verified personal experience', ' '.join(ref['conditions']))
                detail = result['evidence']['products'][0]
                self.assertEqual(['description', 'rating', 'price', 'availability'], detail['unverifiedFields'])

    def test_broad_wear_missing_or_invalid_class_never_falls_back_to_gear(self):
        for explicit in (None, "unknown-layer"):
            specs = {"model": "1101493", "gender": "Men's", "material": "nylon",
                     "weight": "130g", "optionState": "selectable"}
            if explicit is not None:
                specs["apparelClass"] = explicit
            product = {"id": "wear-1", "name": "mont-bell 1101493", "brand": "mont-bell",
                       "categoryId": "wear", "specs": specs,
                       "imageUrl": "https://images.example/1101493.png",
                       "affiliateUrl": "", "amazonUrl": ""}

            def fetch(url, *_):
                if "images.example" in url:
                    return response(PNG, "image/png")
                return response('<title>mont-bell 1101493</title><p>1101493 weight: 130g</p>'
                                '<img src="https://images.example/1101493.png">')

            result = Catalog({}, fetch, source_hints={
                "wear-1": ["https://webshop.montbell.jp/goods/disp.php?product_id=1101493"]
            }).gather({"productIds": ["wear-1"]}, {"products": [product]})
            self.assertEqual(result["apparelSourcing"]["status"], "hold")
            self.assertFalse(result["checks"]["facts"])
            self.assertFalse(result["checks"]["images"])
            self.assertFalse(any(ref["kind"] == "manufacturer" for ref in result["references"]))


if __name__ == "__main__":
    unittest.main()
