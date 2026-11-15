"""Catalog apparel requests must fail closed before generic gear matching."""
import unittest

from catalog import Catalog
from test_catalog import PNG, response


class CatalogApparelTests(unittest.TestCase):
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
