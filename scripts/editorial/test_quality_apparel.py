"""Offline bundle gate for retained apparel source bindings."""
import copy
import unittest

from quality import inspect_bundle
from test_quality import bundle


def apparel_bundle():
    value = bundle()
    product = value["products"][0]
    product.update(brand="mont-bell", categoryId="down",
                   specs={"model": "1101493", "apparelClass": "down", "gender": "Men's",
                          "material": "7デニール ナイロン", "weight": "130g",
                          "optionState": "fixed", "color": "BK", "size": "S",
                          "rakutenOptionState": "fixed", "rakutenVariant": "RT-1101493-BK-S",
                          "rakutenColor": "BK", "rakutenSize": "S",
                          "amazonOptionState": "fixed", "amazonVariant": "B012345678",
                          "amazonColor": "BK", "amazonSize": "S"})
    value["article"]["categoryId"] = "down"
    binding = {"class": "down", "brand": "mont-bell", "model": "1101493",
               "gender": "Men's", "fabric": "7デニール ナイロン", "weight": "130g",
               "optionState": "fixed", "color": "BK", "size": "S",
               "canonicalVariant": "1101493:BK:S", "colors": ["BK"], "sizes": ["S"],
               "sourceKind": "json-ld-product",
               "imageUrls": [value["images"][0]["url"]]}
    value["images"][0]["apparelBinding"] = copy.deepcopy(binding)
    rakuten_binding = dict(binding, sourceKind="rakuten-primary-product-dom",
                           merchantChannel="rakuten", merchantOptionState="fixed",
                           merchantVariant="RT-1101493-BK-S", merchantColor="BK",
                           merchantSize="S", colors=["BK"], sizes=["S"])
    amazon_binding = dict(binding, sourceKind="amazon-primary-product-dom",
                          merchantChannel="amazon", merchantOptionState="fixed",
                          merchantVariant="B012345678", merchantColor="BK",
                          merchantSize="S", colors=["BK"], sizes=["S"])
    value["references"] = [
        {"productId": "tent-a", "kind": "manufacturer", "channel": None,
         "url": "https://webshop.montbell.jp/goods/disp.php?product_id=1101493",
         "checkedAt": "2026-11-15T22:00:00+09:00", "apparelBinding": copy.deepcopy(binding)},
        {"productId": "tent-a", "kind": "purchase", "channel": "rakuten",
         "url": "https://item.rakuten.co.jp/shop/tent/",
         "checkedAt": "2026-11-15T22:00:00+09:00", "apparelBinding": rakuten_binding},
        {"productId": "tent-a", "kind": "purchase", "channel": "amazon",
         "url": "https://www.amazon.co.jp/dp/B012345678/?tag=camp78-22",
         "checkedAt": "2026-11-15T22:00:00+09:00", "apparelBinding": amazon_binding},
    ]
    return value


class ApparelBundleTests(unittest.TestCase):
    def test_complete_bound_apparel_metadata_passes_offline_only(self):
        result = inspect_bundle(apparel_bundle())
        self.assertTrue(result["passed"], result)

    def test_missing_wrong_model_color_size_or_image_binding_fails(self):
        mutations = (
            lambda b: b["references"][0]["apparelBinding"].update(model="11014930"),
            lambda b: b["references"][1]["apparelBinding"].update(colors=[]),
            lambda b: b["references"][2]["apparelBinding"].update(sizes=[]),
            lambda b: b["images"][0].pop("apparelBinding"),
            lambda b: b["images"][0]["apparelBinding"].update(
                imageUrls=["https://official.example/wrong-product.jpg"]),
        )
        for mutate in mutations:
            data = apparel_bundle()
            mutate(data)
            result = inspect_bundle(data)
            self.assertFalse(result["passed"], result)
            self.assertTrue(any("apparel" in failure for failure in result["failures"]), result)

    def test_broad_wear_missing_or_invalid_class_fails_closed(self):
        for value in (None, "unknown-layer"):
            data = apparel_bundle()
            data["products"][0]["categoryId"] = "wear"
            if value is None:
                data["products"][0]["specs"].pop("apparelClass")
            else:
                data["products"][0]["specs"]["apparelClass"] = value
            result = inspect_bundle(data)
            self.assertFalse(result["passed"], result)
            self.assertTrue(any("classification" in failure for failure in result["failures"]), result)


if __name__ == "__main__":
    unittest.main()
