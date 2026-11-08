"""Source-scope tests; no network, credentials, or publishing."""
import unittest
import json

from primary_firepit import extract_primary, fixed_amazon_identity


class PrimaryFirepitTests(unittest.TestCase):
    def test_uniflame_exact_identity_and_qualified_fields(self):
        html = '<article id="product"><div id="item"><p class="item-code">No.683040</p><h1 class="item-name">ファイアグリル</h1></div><ul class="item-spec"><li><dl><dt>重量</dt><dd>約2.7kg</dd></dl></li><li><dl><dt>分散耐荷重</dt><dd>約20kg</dd></dl></li></ul></article>'
        product = {'id': 'fp-002', 'brand': 'ユニフレーム', 'specs': {'型番': '683040'}}
        url = 'https://www.uniflame.co.jp/product/683040'
        result = extract_primary(product, url, html)
        self.assertEqual(result['specs']['分散耐荷重'], '約20kg')
        self.assertIsNone(extract_primary(product, url, html.replace('No.683040', 'No.683095')))
        self.assertIsNone(extract_primary(product, url, html.replace('id="product"', 'id="recommendations"')))
        self.assertIsNone(extract_primary(product, 'https://evil.example/product/683040', html))
        self.assertIsNone(extract_primary(product, url, '<script>' + html + '</script>'))

    def test_picogrill_exact_sku_not_recommendation(self):
        html = '<div class="product-info-default"><h1 class="product-info-title-desktop">ピコグリル 398</h1><span class="model-number-text">0398.SP</span><div class="product-info-description"><div class="tab-body active"><strong>人数</strong><br>1-4<br><strong>商品内容</strong><br>串2本<br><strong>重量</strong><br>総量：495g<br>フレームと火床：365g<br><strong>サイズ</strong><br>380 x 250 x 250mm<br><strong>材質</strong><br>ステンレス鋼、高強度<br><strong>調理</strong><br>最大2.5L</div></div></div>'
        product = {'id': 'fp-001', 'brand': 'ピコグリル', 'specs': {'型番': '0398.SP'}}
        url = 'https://www.picogrill.ch/grill/PICOGRILL-398.html?language=jp'
        result = extract_primary(product, url, html)
        self.assertEqual(result['specs']['重量'], '総量：495g フレームと火床：365g')
        self.assertIsNone(extract_primary(product, url, html.replace('0398.SP', '0498.SP')))
        self.assertIsNone(extract_primary(product, url.replace('398.html', '498.html'), html))
        self.assertIsNone(extract_primary(product, url, html.replace('ピコグリル 398', 'ピコグリル 498') + '<aside>ピコグリル 398 0398.SP</aside>'))

    def test_named_tokyo_model_only_on_fixed_official_scope(self):
        html = '<div data-parts="item-detail"><h2 class="item-detail_itemTitle_abc">TokyoCamp焚火台"HAKOSUKA"</h2><p class="item-detail_description_abc">【商品詳細】・付属品：本体、収納ケース・重量：約985g・素材：ステンレス</p></div>'
        product = {'id': 'fp-004', 'brand': 'TokyoCamp', 'specs': {'型番': 'HAKOSUKA'}}
        url = 'https://shop.tokyocamp.ooo/items/51325629'
        self.assertEqual(extract_primary(product, url, html)['specs']['重量'], '約985g')
        self.assertIsNone(extract_primary(product, url, html.replace('HAKOSUKA', 'HAKOSUKA Titanium Model')))
        self.assertIsNone(extract_primary(product, url, html.replace('本体、収納ケース', 'ケースのみ')))
        self.assertIsNone(extract_primary(product, url.replace('51325629', '51325630'), html))
        self.assertIsNone(extract_primary(product, url, html + html))

    def test_unverified_ranger_not_inferred_from_retailer(self):
        product = {'id': 'fp-005', 'brand': 'ソロストーブ', 'specs': {'型番': 'SSRAN-SD-2'}}
        self.assertIsNone(extract_primary(product, 'https://item.rakuten.co.jp/upi-outdoor/ssran-sd-2/', '<h1>SSRAN-SD-2 Ranger kit</h1>'))

    def test_ranger_official_product_jsonld_and_kit_scope(self):
        url = 'https://store.upioutdoor.com/products/solo-stove-ranger-kit-2'
        title = 'SOLO STOVE RANGER KIT 2.0 / ソロストーブ レンジャーキット 2.0'
        metadata = json.dumps({'@type': 'Product', 'url': url, 'name': title, 'sku': 'SSRAN-SD-2'})
        html = '<script type="application/ld+json">' + metadata + '</script><div id="main"><section data-section-type="product-single"><h1 class="product-single__title">' + title + '</h1></section><div class="spec-area"><div class="spec-item"><h4 class="spec-item__heading">内容</h4><p class="spec-item__text">本体、レンジャー専用スタンド、収納袋、日本語説明書</p></div><div class="spec-item"><h4 class="spec-item__heading">重量</h4><p class="spec-item__text">約7.5kg</p></div></div></div>'
        product = {'id': 'fp-005', 'brand': 'ソロストーブ', 'specs': {'型番': 'SSRAN-SD-2'}}
        self.assertEqual(extract_primary(product, url, html)['specs']['重量'], '約7.5kg')
        self.assertIsNone(extract_primary(product, url, html.replace('KIT 2.0', 'KIT 1.0')))
        self.assertIsNone(extract_primary(product, url, html.replace('本体、レンジャー専用スタンド、収納袋、日本語説明書', '本体のみ')))
        self.assertIsNone(extract_primary(product, url, html.replace('"sku": "SSRAN-SD-2"', '"sku": "SSRAN"')))
        self.assertIsNone(extract_primary(product, url, html.replace('class="spec-area"', 'class="related-products"')))

    def test_official_image_scope_and_duplicate_spec_fail_closed(self):
        product = {'id': 'fp-002', 'brand': 'ユニフレーム', 'specs': {'型番': '683040'}}
        url = 'https://www.uniflame.co.jp/product/683040'
        html = '<base href="https://www.uniflame.co.jp/"><article id="product"><div id="item"><p class="item-code">No.683040</p><h1 class="item-name">ファイアグリル</h1></div><div id="visualWrap"><img src="/official.jpg"><img src="https://evil.example/other.jpg"></div><ul class="item-spec"><li><dl><dt>重量</dt><dd>約2.7kg</dd></dl></li></ul></article><aside><img src="https://www.uniflame.co.jp/neighbor.jpg"></aside>'
        nav_only = html.replace('<div id="visualWrap">', '<nav><div id="visualWrap">').replace('</ul></article>', '</ul></nav></article>')
        self.assertIsNone(extract_primary(product, url, nav_only))
        self.assertEqual(extract_primary(product, url, html)['imageUrls'], ['https://www.uniflame.co.jp/official.jpg'])
        self.assertIsNone(extract_primary(product, url, html.replace('https://www.uniflame.co.jp/\">', 'https://evil.example/\">')))
        self.assertIsNone(extract_primary(product, url, html.replace('</ul>', '<li><dl><dt>重量</dt><dd>3kg</dd></dl></li></ul>')))


class FixedAmazonIdentityTests(unittest.TestCase):
    def test_fixed_tent_primary_overview_brand_not_pagewide(self):
        title = 'ランドロック [6人用] TP-671R'
        html = '<span id="productTitle">' + title + '</span><div id="productOverview_feature_div"><table><tr><td>ブランド</td><td>Snow Peak(スノーピーク)</td></tr></table></div>'
        url = 'https://www.amazon.co.jp/dp/B01N5FYL0K?tag=owner-22'
        check = lambda body=html, pid='tent-f03', model='TP-671R', target=url: fixed_amazon_identity(pid, model, target, body, title)
        self.assertIsNotNone(check())
        self.assertIsNone(check(pid='unrelated'))
        self.assertIsNone(check(model='TP-672'))
        self.assertIsNone(check(target='https://evil.example/dp/B01N5FYL0K'))
        accessory = html.replace(title, 'ランドロック TP-671R 専用グランドシート')
        self.assertIsNone(fixed_amazon_identity('tent-f03', 'TP-671R', url, accessory, 'Amazon.co.jp: ランドロック TP-671R 専用グランドシート'))
        contradiction = html.replace('</table>', '<tr><th>メーカー型番</th><td>TP-259</td></tr></table>')
        self.assertIsNone(check(body=contradiction))
        for bad in (html.replace('Snow Peak(スノーピーク)', 'Other'),
                    html.replace('id="productOverview_feature_div"', 'id="related"'),
                    html.replace('<div id=', '<nav><div id=') + '</nav>',
                    html.replace(title, 'ランドロック X TP-672'),
                    html + '<span id="productTitle">TP-672</span>',
                    html.replace('</table>', '<tr><td>ブランド</td><td>Other</td></tr></table>')):
            self.assertIsNone(check(body=bad))

    def test_tokyo_exact_primary_model_table_and_brand(self):
        title = 'Tokyo Camp 焚き火台 折りたたみ式 軽量985g ステンレス製'
        html = '<span id="productTitle">' + title + '</span><div id="productDetails_expanderTables_depthRightSections"><table class="prodDetTable"><tr><th>品番・型番</th><td>HAKOSUKA</td></tr><tr><th>メーカー型番</th><td>HAKOSUKA01</td></tr><tr><th>ブランド名</th><td>Tokyo Camp</td></tr></table></div>'
        url = 'https://www.amazon.co.jp/dp/B08CZWJ7P8?tag=owner-22'
        check = lambda body=html, target=url: fixed_amazon_identity('fp-004', 'HAKOSUKA', target, body, title)
        self.assertIsNotNone(check())
        for bad in (html.replace('HAKOSUKA</td>', 'HAKOSUKA-TI</td>'),
                    html.replace('HAKOSUKA01', 'OTHER'),
                    html.replace('id="productDetails_expanderTables_depthRightSections"', 'id="recommendations"'),
                    html.replace('<div id=', '<aside><div id=') + '</aside>',
                    html.replace('焚き火台', 'チタン焚き火台'),
                    html.replace('<td>Tokyo Camp</td>', '<td>Other</td>')):
            self.assertIsNone(check(body=bad))
        self.assertIsNone(check(target=url.replace('B08CZWJ7P8', 'B012345678')))


class CatalogFirepitIntegrationTests(unittest.TestCase):
    """Minimal real-source structure; synthetic image/merchant transport only."""
    def run_gather(self, pid, model, brand, url, html, specs, image,
                   merchant_title=None, merchant_body='', source_requires_ua=False, merchant_url=None):
        from unittest.mock import patch
        from catalog import Catalog, MAKERS
        from test_catalog import PNG, response
        merchant = merchant_url or 'https://www.amazon.co.jp/dp/B012345678?tag=owner-22'
        product = dict(id=pid, name=brand + ' ' + model, brand=brand,
                       categoryId='firepit', price=0,
                       specs={'型番': model, **specs}, imageUrl=image,
                       amazonUrl=merchant, affiliateUrl='', yahooUrl='')
        def fetch(target, *_):
            if target == url:
                if source_requires_ua and (not _[0].get('User-Agent') or _[0].get('Accept') != 'text/html'):
                    return response('{"error":"rate_limited"}', 'application/json', status=429)
                return response(html)
            if target == image:
                return response(PNG, 'image/png')
            if target == merchant:
                return response('<title>' + (merchant_title or brand + ' ' + model) + '</title><main>' + merchant_body + '</main>')
            return response('', status=404)
        with patch.dict(MAKERS, {'picogrill': ('picogrill.ch',), 'ピコグリル': ('picogrill.ch',),
                                'tokyocamp': ('tokyocamp.ooo',), 'ソロストーブ': ('store.upioutdoor.com',)}):
            return Catalog({'AMAZON_PARTNER_TAG': 'owner-22'}, fetcher=fetch,
                           source_hints={pid: [url]}).gather({'productIds': [pid]}, {'products': [product]})

    def test_tokyo_named_model_requires_actual_official_scope(self):
        image = 'https://baseec-img-mng.akamaized.net/images/item/origin/product.png'
        html = '<div data-parts="item-detail"><h2 class="item-detail_itemTitle_dfed4c9a">TokyoCamp焚火台"HAKOSUKA"</h2><p class="item-detail_description_dfed4c9a">【商品詳細】・付属品：本体、収納ケース・重量：約985g・素材：ステンレス</p><img src="' + image + '"></div>'
        args = ('fp-004', 'HAKOSUKA', 'TokyoCamp', 'https://shop.tokyocamp.ooo/items/51325629')
        result = self.run_gather(*args, html, {'重量': '約985g', '付属品': '本体、収納ケース', '素材': 'ステンレス'}, image)
        self.assertEqual(result['checks'], {'facts': True, 'images': True, 'affiliate': True})
        for bad in (html.replace('HAKOSUKA', 'HAKOSUKA Titanium Model'),
                    html.replace('約985g', '約560g'), html.replace('data-parts="item-detail"', 'data-parts="related"')):
            result = self.run_gather(*args, bad, {'重量': '約985g'}, image)
            self.assertFalse(result['checks']['facts'])
        # Actual Amazon primary-table shape: named model is absent from title.
        table = '<div id="productDetails_expanderTables_depthRightSections"><table class="prodDetTable"><tr><th>品番・型番</th><td>HAKOSUKA</td></tr><tr><th>メーカー型番</th><td>HAKOSUKA01</td></tr><tr><th>ブランド名</th><td>Tokyo Camp</td></tr></table></div>'
        kwargs = dict(merchant_title='Tokyo Camp 焚き火台 折りたたみ式', merchant_body='<span id="productTitle">Tokyo Camp 焚き火台 折りたたみ式</span>' + table, merchant_url='https://www.amazon.co.jp/dp/B08CZWJ7P8?tag=owner-22')
        self.assertTrue(self.run_gather(*args, html, {'重量': '約985g'}, image, **kwargs)['checks']['affiliate'])
        kwargs['merchant_body'] = kwargs['merchant_body'].replace('HAKOSUKA</td>', 'OTHER</td>')
        self.assertFalse(self.run_gather(*args, html, {'重量': '約985g'}, image, **kwargs)['checks']['affiliate'])
        # No generic ASCII/digit model relaxation for unrelated products.
        result = self.run_gather('other', 'HAKOSUKA', 'TokyoCamp', args[-1], html, {'重量': '約985g'}, image)
        self.assertFalse(result['checks']['facts'])

    def test_uniflame_official_body_field_qualifiers_remain_exact(self):
        image = 'https://www.uniflame.co.jp/photo.png'
        html = '<article id="product"><div id="item"><p class="item-code">No.683040</p><h1 class="item-name">ファイアグリル</h1></div><div id="visualWrap"><img src="' + image + '"></div><ul class="item-spec"><li><dl><dt>分散耐荷重</dt><dd>約20kg</dd></dl></li></ul></article>'
        args = ('fp-002', '683040', 'ユニフレーム', 'https://www.uniflame.co.jp/product/683040', html)
        self.assertEqual(self.run_gather(*args, {'分散耐荷重': '約20kg'}, image)['checks'], {'facts': True, 'images': True, 'affiliate': True})
        self.assertFalse(self.run_gather(*args, {'耐荷重': '約20kg'}, image)['checks']['facts'])
        self.assertFalse(self.run_gather(*args, {'分散耐荷重': '20kg'}, image)['checks']['facts'])
        self.assertTrue(self.run_gather(*args, {'分散耐荷重': '約20kg'}, image,
                                       source_requires_ua=True)['checks']['facts'])

    def test_picogrill_official_sku_to_398_merchant_alias_rejects_parts(self):
        image = 'https://www.picogrill.ch/body.png'
        html = '<div class="product-info-default"><h1 class="product-info-title-desktop">ピコグリル 398</h1><span class="model-number-text">0398.SP</span><div id="image-collection-container"><img src="' + image + '"></div><div class="product-info-description"><div class="tab-body active"><strong>人数</strong><br>1-4<br><strong>商品内容</strong><br>串2本<br><strong>重量</strong><br>総量：495g<br>フレームと火床：365g<br><strong>サイズ</strong><br>380 x 250 x 250mm<br><strong>材質</strong><br>ステンレス鋼、高強度<br><strong>調理</strong><br>最大2.5L</div></div></div>'
        args = ('fp-001', '0398.SP', 'ピコグリル', 'https://www.picogrill.ch/grill/PICOGRILL-398.html?language=jp', html, {'重量': '総量：495g フレームと火床：365g'}, image)
        result = self.run_gather(*args, merchant_title='Picogrill 398 genuine firepit',
                                 merchant_body='<p>Picogrill 398 付属品：串2本</p>')
        self.assertEqual(result['checks'], {'facts': True, 'images': True, 'affiliate': True})
        binding = result['evidence']['products'][0]['destinations'][0]['identityBinding']
        self.assertEqual(binding['manufacturerModel'], '0398.SP')
        self.assertTrue(binding['bundleVerified'])
        self.assertFalse(self.run_gather(*args, merchant_title='Picogrill 398 genuine firepit')['checks']['affiliate'])
        for title in ('Picogrill 398 スピット 2本セット', 'Picogrill 398 replacement tray', 'Picogrill 398 compatible grid',
                      'Picogrill 498 firepit', 'Picogrill 1398 firepit'):
            self.assertFalse(self.run_gather(*args, merchant_title=title)['checks']['affiliate'])

        for body in ('<main><p>本体のみ</p></main><nav><p>Picogrill 398 串2本</p></nav>', '<p>Picogrill 398 付属品：串1本</p><aside><p>Picogrill 398 付属品：串2本</p></aside>', '<p>付属品：串1本、串2本</p>', '<main><p>商品型番 Picogrill 498 付属品：串2本</p></main>', '<p>Picogrill 398 付属品：串2本 商品型番 Picogrill 498</p>'):
            self.assertFalse(self.run_gather(*args, merchant_title='Picogrill 398 焚き火台', merchant_body=body)['checks']['affiliate'])

    def test_ranger_kit_merchant_identity_requires_matching_body_scope(self):
        url = 'https://store.upioutdoor.com/products/solo-stove-ranger-kit-2'
        title = 'SOLO STOVE RANGER KIT 2.0 / ソロストーブ レンジャーキット 2.0'
        image = 'https://store.upioutdoor.com/cdn/shop/products/body.png'
        metadata = json.dumps({'@type': 'Product', 'url': url, 'name': title, 'sku': 'SSRAN-SD-2'})
        html = '<script type="application/ld+json">' + metadata + '</script><div id="main"><section data-section-type="product-single"><h1 class="product-single__title">' + title + '</h1><img class="media-gallery__image" src="' + image + '"></section><div class="spec-area"><div class="spec-item"><h4 class="spec-item__heading">内容</h4><p class="spec-item__text">本体、レンジャー専用スタンド、収納袋、日本語説明書</p></div><div class="spec-item"><h4 class="spec-item__heading">重量</h4><p class="spec-item__text">約7.5kg</p></div></div></div>'
        args = ('fp-005', 'SSRAN-SD-2', 'ソロストーブ', url, html, {'重量': '約7.5kg'}, image)
        result = self.run_gather(*args, merchant_title=title,
                                 merchant_body='<p>商品番号：SSRAN-SD-2 レンジャー専用スタンド付</p>')
        self.assertEqual(result['checks'], {'facts': True, 'images': True, 'affiliate': True})
        self.assertFalse(self.run_gather(*args, merchant_title=title, merchant_body='<main><p>商品番号 SSRANJP</p></main><nav>SSRAN-SD-2 専用スタンド</nav>')['checks']['affiliate'])
        self.assertFalse(self.run_gather(*args, merchant_title=title, merchant_body='<p>本体のみ SSRAN-SD-2</p>')['checks']['affiliate'])
        self.assertFalse(self.run_gather(*args, merchant_title=title.replace('2.0', '2.01'), merchant_body='<p>SSRAN-SD-2 専用スタンド</p>')['checks']['affiliate'])


if __name__ == '__main__':
    unittest.main()
