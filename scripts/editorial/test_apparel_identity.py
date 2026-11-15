"""Offline apparel identity and source-hold contracts."""
import copy
import html
import json
import unittest

from apparel_identity import (ApparelIdentityError, apparel_class, apparel_contract,
                              binding_matches_product, claim_binding, inspect_apparel_page,
                              official_domains, public_binding)


def product(**changes):
    value = {
        "id": "down-montbell-1101493", "name": "Plasma 1000 Down Jacket Men's",
        "brand": "mont-bell", "categoryId": "down",
        "specs": {"model": "1101493", "apparelClass": "down", "gender": "Men's",
                  "material": "7デニール ナイロン", "weight": "130g",
                  "optionState": "selectable"},
        "imageUrl": "https://webshop.montbell.jp/images/1101493-bk.jpg",
    }
    for key, item in changes.items():
        if key == "specs":
            value["specs"].update(item)
        else:
            value[key] = item
    return value


def jsonld(value, url="https://webshop.montbell.jp/goods/disp.php?product_id=1101493"):
    node = {"@context": "https://schema.org", "@type": "Product", "url": url,
            "brand": {"@type": "Brand", "name": "モンベル"}, "model": "1101493",
            "gender": "Men's", "material": "7デニール ナイロン", "weight": "130g",
            "image": ["https://webshop.montbell.jp/images/1101493-bk.jpg"],
            "hasVariant": [
                {"@type": "Product", "sku": "1101493-BK-S", "color": "BK", "size": "S",
                 "image": "https://webshop.montbell.jp/images/1101493-bk.jpg"},
                {"@type": "Product", "sku": "1101493-BK-M", "color": "BK", "size": "M"},
            ]}
    node.update(value)
    return '<script type="application/ld+json">' + json.dumps(node, ensure_ascii=False) + '</script>'


class ApparelIdentityTests(unittest.TestCase):
    def test_explicit_classification_and_bounded_domains_leave_gear_unchanged(self):
        self.assertEqual(apparel_class(product()), "down")
        self.assertEqual(apparel_class(product(categoryId="wear",
                                               specs={"apparelClass": "down"})), "down")
        self.assertIsNone(apparel_class({"categoryId": "stove", "specs": {"model": "ST-310"}}))
        self.assertEqual(official_domains(product()), ("montbell.jp", "montbell.com"))
        self.assertEqual(official_domains(product(brand="unknown")), ())

    def test_missing_identity_or_fixed_variant_never_builds_contract(self):
        for patch in ({"gender": ""}, {"optionState": ""}, {"model": "Plasma"},
                      {"optionState": "fixed"}):
            with self.subTest(patch=patch), self.assertRaises(ApparelIdentityError):
                apparel_contract(product(specs=patch))
        fixed = product(specs={"optionState": "fixed", "color": "BK", "size": "S"})
        self.assertEqual(apparel_contract(fixed)["canonicalVariant"], "1101493:BK:S")
        unclaimed = product()
        unclaimed["specs"].pop("material")
        unclaimed["specs"].pop("weight")
        contract = apparel_contract(unclaimed)
        self.assertNotIn("fabric", contract)
        self.assertNotIn("weight", contract)

    def test_jsonld_requires_exact_model_fields_options_url_and_image(self):
        current = product()
        url = "https://webshop.montbell.jp/goods/disp.php?product_id=1101493"
        good = inspect_apparel_page(current, url, jsonld({}), current["imageUrl"])
        self.assertTrue(binding_matches_product(public_binding(good), current))
        for change in (
                {"model": "11014930"}, {"gender": "Women's"}, {"material": "似た素材"},
                {"weight": "131g"}, {"url": url + "0"}, {"image": "https://example.com/wrong.jpg"},
                {"hasVariant": [{"@type": "Product", "sku": "x", "color": "BK"}]},
                {"hasVariant": [{"@type": "Product", "sku": "x", "size": "S"}]}):
            with self.subTest(change=change):
                self.assertIsNone(inspect_apparel_page(current, url, jsonld(change),
                                                       current["imageUrl"]))

    def test_http_200_placeholder_and_wrong_product_title_do_not_pass(self):
        url = "https://www.patagonia.jp/product/mens-r1-air/40256.html"
        placeholder = '<title>Hang Tight! Routing to checkout...</title><h1>40256</h1>'
        self.assertIsNone(inspect_apparel_page(
            product(brand="Patagonia", categoryId="active-layer",
                    specs={"model": "40256", "apparelClass": "active-layer"}),
            url, placeholder))
        amazon = '<title>Amazon.co.jp</title><div id="productTitle">1101493</div>'
        self.assertIsNone(inspect_apparel_page(product(),
                                               "https://www.amazon.co.jp/dp/B00M3KGL26", amazon))
        self.assertIsNone(inspect_apparel_page(product(),
                                               "https://example.com/1101493", jsonld({}),
                                               source_role="merchant"))

    def test_fixed_variant_rejects_wrong_color_size_or_variant(self):
        fixed = product(specs={"optionState": "fixed", "color": "BK", "size": "S"})
        url = "https://webshop.montbell.jp/goods/disp.php?product_id=1101493"
        self.assertIsNotNone(inspect_apparel_page(fixed, url, jsonld({})))
        for field, value in (("color", "OF"), ("size", "L")):
            changed = copy.deepcopy(fixed)
            changed["specs"][field] = value
            self.assertIsNone(inspect_apparel_page(changed, url, jsonld({})))

    def test_actual_amazon_primary_dom_binds_child_asin_and_selected_variant(self):
        current = product(categoryId="base-layer", specs={
            "model": "1107704", "apparelClass": "base-layer", "gender": "Men's",
            "optionState": "selectable", "amazonOptionState": "fixed",
            "amazonVariant": "B0DP4DNB51", "amazonColor": "LGY", "amazonSize": "L"})
        state = {"sortedDimValuesForAllDims": {
            "size_name": [{"defaultAsin": "B0DP4DNB51", "dimensionValueState": "SELECTED",
                           "dimensionValueDisplayText": "L"}],
            "color_name": [{"defaultAsin": "B0DP4DNB51", "dimensionValueState": "SELECTED",
                            "dimensionValueDisplayText": "ライトグレー(LGY)"}]}}
        descriptor = html.escape(json.dumps({"key": "desktop-twister-sort-filter-data"}), quote=True)
        body = (f'<link rel="canonical" href="https://www.amazon.co.jp/product/dp/B0DP629XKC">'
                f'<span id="productTitle">[モンベル] メンズ 1107704</span>'
                f'<input type="hidden" name="ASIN" value="B0DP4DNB51">'
                f'<img id="landingImage" alt="モンベル メンズ 1107704" '
                f'data-old-hires="https://m.media-amazon.com/images/I/exact.jpg">'
                f'<script type="a-state" data-a-state="{descriptor}">{json.dumps(state)}</script>')
        verified = inspect_apparel_page(current, "https://www.amazon.co.jp/dp/B0DP4DNB51",
                                        body, source_role="purchase", channel="amazon")
        self.assertEqual(verified["merchantVariant"], "B0DP4DNB51")
        # Amazon's ASIN is source-local; the canonical garment variant remains model/color/size.
        self.assertNotEqual(verified["merchantVariant"], "1107704:LGY:L")
        for field, value in (("amazonVariant", "B0DP629XKC"),
                             ("amazonColor", "DGN"), ("amazonSize", "S")):
            changed = copy.deepcopy(current)
            changed["specs"][field] = value
            self.assertIsNone(inspect_apparel_page(
                changed, "https://www.amazon.co.jp/dp/B0DP4DNB51", body,
                source_role="purchase", channel="amazon"))

    def test_actual_fixed_amazon_dom_without_twister_still_requires_scoped_asin(self):
        current = product(categoryId="fleece", specs={
            "model": "1114881", "apparelClass": "fleece", "gender": "Men's",
            "optionState": "fixed", "color": "グレー", "size": "L",
            "amazonOptionState": "fixed", "amazonVariant": "B0G75V4CC5",
            "amazonColor": "グレー", "amazonSize": "L"})
        body = ('<link rel="canonical" href="https://www.amazon.co.jp/item/dp/B0G75V4CC5">'
                '<span id="productTitle">[モンベル] フリース ジャケット メンズ '
                '1114881 (カラー：グレー)(サイズ：L)</span>'
                '<input type="hidden" name="ASIN" value="B0G75V4CC5">'
                '<img id="landingImage" alt="[モンベル] メンズ 1114881" '
                'data-old-hires="https://m.media-amazon.com/images/I/51TML5BnPBL._AC_SL1000_.jpg">')
        url = "https://www.amazon.co.jp/dp/B0G75V4CC5"
        verified = inspect_apparel_page(current, url, body,
                                        source_role="purchase", channel="amazon")
        self.assertEqual(verified["imageUrls"], [
            "https://m.media-amazon.com/images/I/51TML5BnPBL._AC_SL1000_.jpg"])
        self.assertIsNone(inspect_apparel_page(
            current, url, body.replace('value="B0G75V4CC5"', 'value="B0G75V4CC6"'),
            source_role="purchase", channel="amazon"))
        self.assertIsNone(inspect_apparel_page(
            current, url, body.replace('メンズ', 'レディース'),
            source_role="purchase", channel="amazon"))

    def test_amazon_recommendation_selects_cannot_prove_primary_options(self):
        current = product(specs={"amazonOptionState": "selectable"})
        body = ('<link rel="canonical" href="https://www.amazon.co.jp/item/dp/B00M3KGL26">'
                '<span id="productTitle">[モンベル] メンズ 1101493</span>'
                '<input type="hidden" name="ASIN" value="B00M3KGL26">'
                '<img id="landingImage" alt="[モンベル] メンズ 1101493" src="exact.jpg">'
                '<aside id="recommendations"><select name="color_name">'
                '<option value="wrong-color">wrong</option></select><select name="size_name">'
                '<option value="wrong-size">wrong</option></select></aside>')
        self.assertIsNone(inspect_apparel_page(
            current, "https://www.amazon.co.jp/dp/B00M3KGL26", body,
            source_role="purchase", channel="amazon"))

    def test_rakuten_ignores_only_exact_affiliate_tracking_query(self):
        current = product(specs={
            "optionState": "selectable", "rakutenOptionState": "fixed",
            "rakutenVariant": "shop:1101493-bk-l", "rakutenColor": "BK",
            "rakutenSize": "L"})
        canonical = "https://item.rakuten.co.jp/shop/1101493-bk-l/"
        body = (f'<link rel="canonical" href="{canonical}"><div itemscope '
                'itemtype="http://schema.org/Product"><meta itemprop="name" '
                'content="モンベル メンズ 1101493 BK L"><meta itemprop="sku" '
                'content="shop:1101493-bk-l"><meta itemprop="image" '
                'content="https://tshop.r10s.jp/shop/1101493-bk-l.jpg"></div>')
        tracked = canonical + "?scid=af_pc_etc&sc2id=af_101_0_0"
        self.assertIsNotNone(inspect_apparel_page(
            current, tracked, body, source_role="purchase", channel="rakuten"))
        self.assertIsNone(inspect_apparel_page(
            current, canonical + "?color=BK&size=L", body,
            source_role="purchase", channel="rakuten"))

    def test_montbell_dom_is_primary_scoped_not_whole_page_text(self):
        current = product(imageUrl="https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg")
        url = "https://webshop.montbell.jp/goods/disp.php?product_id=1101493"
        html = '''<h2 class="ttlType01">Plasma Men's</h2><div id="maindataCont">
        <div>品番 #1101493 ブランド モンベル</div>
        <a href="/common/images/product/prod_k/k_1101493_bk.jpg"></a>
        <select name="sel_size"><option value="">選択</option><option value="S">S</option></select>
        <input name="all_color" value="BK"><input name="product_id" value="1101493"></div>
        <div class="column1 type01"><div class="innerCont"><h4 class="ttlType03">仕様</h4>
        <p>【素材】7デニール ナイロン<br>【平均重量】130g<br></p></div></div>'''
        binding = inspect_apparel_page(current, url, html, current["imageUrl"])
        self.assertEqual(binding["sourceKind"], "montbell-product-dom")
        proof = claim_binding(binding, "model", "1101493")
        self.assertEqual(proof["unit"], "bound-apparel-product")
        self.assertEqual(proof["sourceKind"], "montbell-product-dom")
        fixed = product(
            specs={"optionState": "fixed", "color": "BK", "size": "S"},
            imageUrl=current["imageUrl"])
        fixed_binding = inspect_apparel_page(fixed, url, html, fixed["imageUrl"])
        self.assertEqual(fixed_binding["canonicalVariant"], "1101493:BK:S")
        self.assertEqual(fixed_binding["colors"], ["BK"])
        self.assertIsNone(inspect_apparel_page(current, url,
                                               html.replace('value="1101493"', 'value="11014930"'),
                                               current["imageUrl"]))

    def test_selectable_merchant_must_offer_fixed_canonical_color_and_size(self):
        current = product(specs={"optionState": "fixed", "color": "BK", "size": "L",
                                 "rakutenOptionState": "selectable"})
        binding = dict(apparel_contract(current), merchantChannel="rakuten",
                       merchantOptionState="selectable", colors=["ブラック(BK)", "OF"],
                       sizes=["M", "L"], sourceKind="rakuten-primary-product-dom")
        self.assertTrue(binding_matches_product(binding, current, "rakuten"))
        binding["colors"] = ["OF"]
        self.assertFalse(binding_matches_product(binding, current, "rakuten"))


if __name__ == "__main__":
    unittest.main()
