"""Offline apparel identity and source-hold contracts."""
import copy
import html
import hashlib
import json
import unittest

from apparel_identity import (ApparelIdentityError, apparel_class, apparel_contract,
                              binding_matches_product, claim_binding, inspect_apparel_page,
                              official_domains, public_binding)
from apparel_identity import MONTBELL_EXCERPT_LIMIT


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


def montbell_dom():
    return '''<h2 class="ttlType01">Plasma Men's</h2><div id="maindataCont">
    <div>品番 #1101493 ブランド モンベル 価格 ¥27,940 在庫あり</div>
    <a href="/common/images/product/prod_k/k_1101493_bk.jpg"></a>
    <select name="sel_size"><option value="S">S</option></select>
    <input name="all_color" value="BK"><input name="product_id" value="1101493"></div>
    <nav>ナビゲーション</nav><h3 class="ttlType02c">商品情報</h3>
    <div class="column1 type01"><div class="innerCont"><p>1000フィルパワーのダウンを封入。
    メーカー調べ（後加工なしの天然の状態）。Light＆Fast。</p>
    <script>var unrelated = "おすすめ商品";</script><style>.x {color:red}</style>
    <nav>ナビゲーション</nav><span hidden>隠れた在庫あり</span>
    </div></div><div class="column1 type01"><div class="innerCont">
    <h4 class="ttlType03">仕様</h4><p>【素材】7デニール ナイロン<br>
    【平均重量】130g<br>【収納サイズ】1.1L<br>【特長】ポケット2個（腰）／スタッフバッグ付き<br></p>
    </div></div><div><h4 class="ttlType03">機能</h4><p>機能欄は対象外</p></div>
    <h3>関連商品</h3><p>別商品は900フィルパワー 在庫あり</p>'''


SPIRAL = 'スパイラル スランテックカフ（特許取得済）'
DETAILS = {
    '1107704': [(SPIRAL, '袖口の縫い目を斜めにすることで、伸縮性を妨げません。'),
                ('フラットシーマー', '主要な接合部に使用し、肌あたりを良くしています。')],
    '1114881': [('素材の特徴＜シャミース＞',
                 '<strong>薄手ながらも保温性に優れる</strong><br />人間の毛髪の10分の1の繊維間に空気を蓄えます。'
                 '<br />通気性とストレッチ性を備えます。'),
                ('着丈はそのままでゆったり着られる＜リラックスサイズ＞', '着丈はそのままで身幅にゆとりがあります。'),
                ('注意事項（38-990）', '摩擦により毛羽が抜け落ちることがあります。衣料用ブラシ等で取り除いてください。'),
                (SPIRAL, '袖口の縫い目を斜めにすることで、伸縮性を妨げません。')],
}


def detail_fixture(model='1107704'):
    image = 'https://webshop.montbell.jp/common/images/product/prod_k/k_' + model + '_bk.jpg'
    current = product(imageUrl=image, specs={'model': model})
    source = montbell_dom().replace('1101493', model)
    sections = ''.join('<div><h4 class="ttlType03">' + heading + '</h4>'
                       '<img alt="別モデル1109999 比較図"/><p class="marginTop5">' + text + '</p></div>'
                       for heading, text in DETAILS[model])
    source = source.replace('<h3>関連商品</h3>', '<h3 class="ttlType02c">詳細情報</h3>' + sections
        + '<h4>白いシャツに透けにくい「ライトグレー」のインナーカラー</h4>'
          '<p>写真はジオライン クールメッシュ VネックTシャツ Men\'s</p>'
          '<h3>お手入れ</h3><h4>' + SPIRAL + '</h4><p>対象外のお手入れ 在庫あり</p>'
          '<h3>関連商品</h3>')
    return current, 'https://webshop.montbell.jp/goods/disp.php?product_id=' + model, source


class ApparelIdentityTests(unittest.TestCase):
    def test_named_details_are_scoped_hashed_manufacturer_claims_for_only_two_models(self):
        for model in DETAILS:
            current, url, source = detail_fixture(model)
            binding = inspect_apparel_page(current, url, source, current['imageUrl'])
            details = binding.get('manufacturerDetails', [])
            self.assertEqual([h for h, _ in DETAILS[model]], [d['heading'] for d in details])
            for detail in details:
                self.assertEqual((url, model), (detail['sourceUrl'], detail['model']))
                self.assertEqual(hashlib.sha256(detail['text'].encode()).hexdigest(), detail['excerptSHA256'])
                self.assertIn('詳細情報', detail['scope'])
                self.assertIn('manufacturer', ' '.join(detail['conditions']))
                self.assertLessEqual(len(detail['text']), 1800)
            for excluded in ('1109999', '写真は', '在庫', '対象外', '<strong>'):
                self.assertNotIn(excluded, ''.join(d['text'] for d in details))
            self.assertIn('manufacturerExcerpt', binding)
            other = source.replace(model, '1101493')
            other_product = product(imageUrl=current['imageUrl'].replace(model, '1101493'))
            self.assertNotIn('manufacturerDetails', inspect_apparel_page(
                other_product, url.replace(model, '1101493'), other, other_product['imageUrl']))

    def test_details_omit_ambiguous_malformed_oversize_and_mixed_sections(self):
        current, url, source = detail_fixture()
        text = DETAILS['1107704'][0][1]
        for bad in ('価格 ¥1000', '在庫あり', '税込100円', '関連商品 1109999',
                    '写真は別モデル', '文' * 1801, '<p>閉じ忘れ',
                    '<strong>未閉鎖', text + '</p>混入<p>'):
            with self.subTest(bad=bad[:30]):
                binding = inspect_apparel_page(current, url, source.replace(text, bad), current['imageUrl'])
                self.assertNotIn(SPIRAL, [d['heading'] for d in binding.get('manufacturerDetails', [])])
                self.assertIn('manufacturerExcerpt', binding)
        for bad_source in (source + '<h3>詳細情報</h3>',
                           source.replace('<h3>お手入れ</h3>', '<h4>' + SPIRAL + '</h4><p>重複</p><h3>お手入れ</h3>'),
                           source.replace('>詳細情報</h3>', '>情報</h3>')):
            binding = inspect_apparel_page(current, url, bad_source, current['imageUrl'])
            self.assertNotIn('manufacturerDetails', binding)

    def test_details_hidden_content_and_identity_mismatch_never_leak(self):
        current, url, source = detail_fixture()
        text = DETAILS['1107704'][0][1]
        hidden = ('<span hidden>在庫あり 1109999</span><nav>関連商品</nav>'
                  '<script>unsafe()</script><span style="display:none">写真は別物</span>')
        binding = inspect_apparel_page(current, url, source.replace(text, text + hidden), current['imageUrl'])
        self.assertEqual(text, binding['manufacturerDetails'][0]['text'])
        for bad in (source.replace('>詳細情報</h3>', ' hidden>詳細情報</h3>'),
                    source.replace('<h4 class="ttlType03">' + SPIRAL,
                                   '<h4 hidden class="ttlType03">' + SPIRAL)):
            binding = inspect_apparel_page(current, url, bad, current['imageUrl'])
            self.assertNotIn(SPIRAL, [d['heading'] for d in binding.get('manufacturerDetails', [])])
        for bad_url, bad_source, image in ((url + '0', source, current['imageUrl']),
                (url, source.replace('value="1107704"', 'value="1109999"'), current['imageUrl']),
                (url, source, current['imageUrl'].replace('1107704', '1109999'))):
            self.assertIsNone(inspect_apparel_page(current, bad_url, bad_source, image))

    def test_montbell_excerpt_stops_at_first_functions_or_detail_heading(self):
        current = product(imageUrl='https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg')
        url = 'https://webshop.montbell.jp/goods/disp.php?product_id=1101493'
        for boundary in ('機能', '詳細情報'):
            with self.subTest(boundary=boundary):
                source = montbell_dom().replace('<h4 class="ttlType03">機能</h4>',
                    '<h3 class="ttlType02c">詳細情報</h3>' if boundary == '詳細情報' else
                    '<h4 class="ttlType03">機能</h4>')
                source += '<h3>詳細情報</h3><p>別モデルのクールメッシュ</p><h4>機能</h4>'
                excerpt = inspect_apparel_page(current, url, source, current['imageUrl'])['manufacturerExcerpt']
                self.assertTrue(excerpt['scope'].endswith('before first ' + boundary))
                self.assertIn('ポケット2個（腰）', excerpt['text'])
                self.assertNotIn('機能欄', excerpt['text'])
                self.assertNotIn('クールメッシュ', excerpt['text'])

    def test_montbell_excerpt_bound_to_exact_identity_and_full_qualified_source(self):
        current = product(imageUrl='https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg')
        url = 'https://webshop.montbell.jp/goods/disp.php?product_id=1101493'
        binding = inspect_apparel_page(current, url, montbell_dom(), current['imageUrl'])
        excerpt = binding['manufacturerExcerpt']
        self.assertEqual((url, '1101493'), (excerpt['sourceUrl'], excerpt['model']))
        self.assertEqual(hashlib.sha256(excerpt['text'].encode('utf-8')).hexdigest(), excerpt['excerptSHA256'])
        for value in ('1000フィルパワー', 'メーカー調べ（後加工なしの天然の状態）',
                      'Light＆Fast', '【平均重量】130g', '1.1L', 'ポケット2個（腰）'):
            self.assertIn(value, excerpt['text'])
        for value in ('価格', '在庫', 'ナビゲーション', 'var unrelated', 'color:red', '機能欄', '900フィルパワー'):
            self.assertNotIn(value, excerpt['text'])
        self.assertNotIn('manufacturerExcerpt', public_binding(binding))
        for bad_url, bad_html in ((url + '0', montbell_dom()),
                                  (url, montbell_dom().replace('value="1101493"', 'value="11014930"')),
                                  (url, montbell_dom().replace('130g', '131g'))):
            with self.subTest(url=bad_url, html=bad_html):
                self.assertIsNone(inspect_apparel_page(current, bad_url, bad_html, current['imageUrl']))

    def test_montbell_excerpt_missing_ambiguous_oversize_or_commercial_scope_is_not_exposed(self):
        current = product(imageUrl='https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg')
        url = 'https://webshop.montbell.jp/goods/disp.php?product_id=1101493'
        for source in (
                montbell_dom().replace('商品情報', '説明'),
                montbell_dom().replace('>機能<', '>詳細<'),
                montbell_dom().replace('>仕様<', '>データ<'),
                montbell_dom() + '<h3>商品情報</h3>',
                montbell_dom().replace('1000フィルパワー', '文' * (MONTBELL_EXCERPT_LIMIT + 1)),
                montbell_dom().replace('1000フィルパワー', '<!--' + 'x' * 32001 + '-->1000フィルパワー'),
                montbell_dom().replace('1000フィルパワー', '価格 ¥1000 在庫あり'),
                montbell_dom().replace('1000フィルパワー', '<h3>関連商品</h3>1000フィルパワー')):
            with self.subTest(source=source[:100]):
                binding = inspect_apparel_page(current, url, source, current['imageUrl'])
                self.assertNotIn('manufacturerExcerpt', binding or {})

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
