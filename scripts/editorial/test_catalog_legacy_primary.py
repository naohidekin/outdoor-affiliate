"""Scoped primary adapters; synthetic markup follows captured official selectors."""
import unittest
import hashlib
import base64
from unittest.mock import patch
from catalog import Catalog, _Page, _primary_identity, _spec_evidence, _model, MAKERS

JPEG = base64.b64decode('/9j/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKpAB//Z')


class LegacyPrimaryTests(unittest.TestCase):
    def test_snowpeak_40_byte_marker_jpeg_must_not_normalize(self):
        from catalog import _image_type
        bad = b'\xff\xd8\xff\xc0' + b'\x00\x11\x08\x00\x01\x00\x01' + b'\x00'*20 + b'\xff\xda' + b'\x00'*5 + b'\xff\xd9'
        reviewer = bytes.fromhex('ffd8ffc00011080001000103ffda') + b'X'*24 + bytes.fromhex('ffd9')
        for body in (bad,reviewer):
            self.assertEqual(len(body),40)
            self.assertEqual(_image_type(body),'image/jpeg')
            cat = Catalog({},fetcher=lambda *_:{'status':200,'headers':{'content-type':'image'},'body':body})
            with self.assertRaises(ValueError):cat.request('https://img.snowpeak.co.jp/bad.jpg')
            with self.assertRaises(ValueError):cat.image_digest('https://img.snowpeak.co.jp/bad.jpg')

    def test_named_cbjcb_only_for_known_existing_product_explicit_model(self):
        product={'id':'burner-s-009','brand':'イワタニ','name':'イワタニ CB-JCB','specs':{'model':'CB-JCB'}}
        self.assertEqual(_model(product),'CB-JCB')
        self.assertEqual(_model(dict(product,id='unrelated-product')),'')
        self.assertEqual(_model(dict(product,specs={'model':'CB-UNVERIFIED'})),'')

    def test_snowpeak_missing_decoder_fails_closed(self):
        cat = Catalog({},fetcher=lambda *_:{'status':200,'headers':{'content-type':'image'},'body':JPEG})
        with patch('subprocess.run',side_effect=FileNotFoundError()):
            with self.assertRaises(ValueError):cat.image_digest('https://img.snowpeak.co.jp/product.jpg')

    def test_iwatani_public_user_agent_scoped_and_not_forwarded(self):
        calls = []
        def fetch(url, headers, _timeout):
            calls.append((url, headers))
            if url.endswith('/redirect'):
                return {'status':302, 'headers':{'location':'https://other.example/final'}, 'body':b''}
            return {'status':200, 'headers':{'content-type':'text/html'}, 'body':b'public'}
        cat = Catalog({}, fetcher=fetch)
        cat.request('https://www.iwatani.co.jp/jpn/consumer/products/cg/burner/cb-jcb/')
        self.assertEqual(calls[-1][1], {'User-Agent':'Mozilla/5.0'})
        cat.request('https://other.example/public')
        self.assertEqual(calls[-1][1], {})
        cat.request('https://www.iwatani.co.jp/redirect', {'User-Agent':'custom-public-client'})
        self.assertEqual(calls[-2][1], {'User-Agent':'custom-public-client'})
        self.assertEqual(calls[-1][1], {})

    def test_snowpeak_generic_image_mime_requires_valid_binary_exact_host(self):
        # Only the captured maker misconfiguration is normalized. Ordinary
        # hosts and HTML masquerading as images retain the existing rejection.
        from test_catalog import PNG
        def fetch(url, *_):
            return {'status':200, 'headers':{'content-type':'image'}, 'body': PNG if not url.endswith('/bad') else b'<html>not an image</html>'}
        cat = Catalog({}, fetcher=fetch)
        proof = cat.image_digest('https://img.snowpeak.co.jp/product.png')
        self.assertEqual(proof['sha256'], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(proof['contentType'], 'image/png')
        self.assertEqual(proof['declaredContentType'], 'image')
        for url in ('https://other.example/product.png', 'https://unapproved.img.snowpeak.co.jp/product.png', 'https://img.snowpeak.co.jp/bad'):
            with self.assertRaises(ValueError):cat.image_digest(url)

    def test_snowpeak_jpeg_binary_truth_and_dom_membership_still_required(self):
        image = 'https://img.snowpeak.co.jp/product.jpg'
        source = 'https://ec.snowpeak.co.jp/item/test'
        def html(advertised):
            return ('<title>スノーピーク GST-120R</title><div id="tab-size"><dl><dt>メーカー品番</dt><dd>GST-120R</dd></dl><dl><dt>重量</dt><dd>56g</dd></dl></div>' + ('<img src="'+image+'">' if advertised else '')).encode()
        def fetch(url, *_):
            return {'status':200, 'headers':{'content-type':'text/html' if url==source else 'image'}, 'body':html(True) if url==source else JPEG}
        cat = Catalog({}, fetcher=fetch, source_hints={'p': [source]})
        proof = cat.image_digest(image)
        self.assertEqual((proof['contentType'],proof['declaredContentType']), ('image/jpeg','image'))
        product = {'id':'p','name':'スノーピーク GST-120R','brand':'スノーピーク','categoryId':'burner','specs':{'model':'GST-120R','重量':'56g'},'imageUrl':image}
        result = cat.gather({'productIds':['p']},{'products':[product]})
        self.assertTrue(result['checks']['images'])
        self.assertEqual(result['images'][0]['declaredContentType'],'image')
        def absent(url, *_):
            return {'status':200, 'headers':{'content-type':'text/html' if url==source else 'image'}, 'body':html(False) if url==source else JPEG}
        result = Catalog({}, fetcher=absent, source_hints={'p':[source]}).gather({'productIds':['p']},{'products':[product]})
        self.assertFalse(result['checks']['images'])
        for body, mime in ((b'<html>not JPEG</html>','image'),(JPEG[:-2],'image'),(JPEG,'image/png')):
            with self.subTest(mime=mime, length=len(body)):
                def bad(url, *_):return {'status':200,'headers':{'content-type':mime},'body':body}
                with self.assertRaises(ValueError):Catalog({},fetcher=bad).image_digest(image)

    def test_primus_explicit_primary_code_and_bracketed_spec(self):
        html = '<title>ウルトラバーナー: PRIMUS</title><main><div class="block-goods-detail"><h1>ウルトラバーナー</h1><dl class="block-goods-comment2"><dd>【重量】116g 【火力】4.2kw 3600kcal/h</dd></dl><dl class="block-goods-code"><dt>商品コード</dt><dd>P-153</dd></dl></div><aside><dl><dt>重量</dt><dd>999g</dd></dl>P-136S</aside></main>'
        page = _Page(html)
        self.assertTrue(_primary_identity(page, 'P-153', 'プリムス'))
        self.assertIsNotNone(_spec_evidence(page, 'P-153', '重量', '116g', True, 'プリムス'))
        self.assertIsNone(_primary_identity(page, 'P-136S', 'PRIMUS'))
        self.assertIsNone(_spec_evidence(page, 'P-153', '重量', '999g', True, 'プリムス'))
        self.assertIsNone(_primary_identity(_Page(html.replace('P-153</dd>', 'P-136S</dd>')), 'P-153', 'プリムス'))

    def test_msr_numeric_code_must_be_explicit_in_primary_scope(self):
        html = '<title>ウィンドバーナー｜MSR</title><div class="elementor-28641"><h1>ウィンドバーナー</h1><p>品番 36219</p><table class="woocommerce-spec-table"><tr><th>総重量</th><td>465g（ガスカートリッジを除く）</td></tr></table></div><nav>品番 99999</nav>'
        page = _Page(html)
        self.assertTrue(_primary_identity(page, '36219', 'MSR'))
        self.assertIsNotNone(_spec_evidence(page, '36219', '総重量', '465g（ガスカートリッジを除く）', True, 'MSR'))
        for bad in (html.replace('品番 36219', 'レビュー 36219'), html.replace('品番 36219', '品番 99999'), html.replace('<p>品番 36219</p>', '') + '<nav>品番 36219</nav>'):
            self.assertIsNone(_primary_identity(_Page(bad), '36219', 'MSR'))

    def test_jetboil_code_and_specs_not_related_product(self):
        html = '<title>モンベル JETBOILフラッシュ</title><div id="contents"><div id="maindataCont"><h1>JETBOILフラッシュ</h1><table><tr><th>品番</th><td>#1824393</td></tr></table></div><div class="column1 type01"><div class="innerCont"><p>【重量】約371g 【容量】1.0L 【出力】2,269kcal/h</p></div></div></div><aside>品番1824351</aside>'
        page = _Page(html)
        self.assertTrue(_primary_identity(page, '1824393', 'Jetboil'))
        self.assertIsNotNone(_spec_evidence(page, '1824393', '重量', '約371g', True, 'Jetboil'))
        self.assertIsNone(_primary_identity(page, '1824351', 'Jetboil'))
        self.assertIsNone(_primary_identity(_Page(html.replace('#1824393', '#1824351')), '1824393', 'Jetboil'))

    def test_captain_stag_code_and_spec_table_inside_item_main(self):
        html = '<title>オーリック キャプテンスタッグ</title><main id="main"><header class="item_area_head"><p class="product_id">M-7900</p><h1>オーリック</h1></header><section class="item_main"><div class="txt_product_spec"><table><tr><th>重量(約)</th><td>300g（ガスバーナーコンロのみ）</td></tr></table></div></section><section class="sec_other_item">M-7901<table><tr><th>重量(約)</th><td>92g</td></tr></table></section></main>'
        page = _Page(html)
        self.assertTrue(_primary_identity(page, 'M-7900', 'キャプテンスタッグ'))
        self.assertIsNotNone(_spec_evidence(page, 'M-7900', '重量(約)', '300g（ガスバーナーコンロのみ）', True, 'キャプテンスタッグ'))
        self.assertIsNone(_primary_identity(page, 'M-7901', 'キャプテンスタッグ'))
        self.assertIsNone(_spec_evidence(page, 'M-7900', '重量(約)', '92g', True, 'キャプテンスタッグ'))

    def test_explicit_models_no_invented_numeric_from_names(self):
        self.assertEqual(_model({'name':'MSR 36219', 'specs':{'model':'36219'}}), '36219')
        self.assertEqual(_model({'name':'MSR stove 36219'}), '')
        self.assertIn('iwatani-primus.jp', MAKERS.get('プリムス', ()))

    def test_iwatani_product_detail_code_and_table_not_nav(self):
        html = '<title>ジュニアコンパクトバーナー | 岩谷産業</title><main id="main"><dl class="products_detail"><dt>商品コード ：</dt><dd>CB-JCB</dd></dl><section class="sec_box_wrap"><table class="table_style01"><tr><th>商品重量</th><td>約274g</td></tr></table></section></main><nav>CB-JCB</nav>'
        page = _Page(html)
        self.assertTrue(_primary_identity(page, 'CB-JCB', 'イワタニ'))
        self.assertIsNotNone(_spec_evidence(page, 'CB-JCB', '商品重量', '約274g', True, 'イワタニ'))
        self.assertIsNone(_primary_identity(_Page(html.replace('<dd>CB-JCB</dd>', '<dd>CB-JRB-3</dd>')), 'CB-JCB', 'イワタニ'))

    def test_uniflame_explicit_no_610107_without_sku_in_title(self):
        html = '<title>テーブルトップバーナーUS-D Ⅱ | ユニフレーム</title><article id="product"><div id="item"><p>No.610107</p></div><ul class="item-spec"><li><dl><dt>重量</dt><dd>約880g</dd></dl></li></ul></article><nav>No.610107</nav>'
        page = _Page(html)
        self.assertTrue(_primary_identity(page, '610107', 'ユニフレーム'))
        self.assertIsNotNone(_spec_evidence(page, '610107', '重量', '約880g', True, 'ユニフレーム'))
        self.assertIsNone(_primary_identity(_Page(html.replace('<p>No.610107</p>', '<p>No.683040</p>')), '610107', 'ユニフレーム'))


if __name__ == '__main__': unittest.main()
