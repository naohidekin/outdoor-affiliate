"""Sanitized observed R1 DOM, actual selectors and flat linked colour schema."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from official_patagonia_apparel import inspect_official_patagonia as inspect, R1_URL, R1_TITLE
from official_browser_source import load_r1_capture, r1_fallback_fetcher, BrowserSourceHold

IMAGE = ('https://dis.patagonia.jp/dw/image/v2/BDJB_PRD/on/demandware.static/-/'
         'Sites-patagonia-master/default/dw2bb7ec95/images/hi-res/40275_BLK.jpg'
         '?sw=1400&sh=1400&sfrm=png&q=90&bgcolor=f3f4ef')
MATERIAL = '中空糸を使用した5.7オンス・リサイクル・ポリエステル100％のジャカード・フリース。'
DESCRIPTION = 'R1 エア・ジャケットはリサイクル・ポリエステル100％素材を使用。'
JST = timezone(timedelta(hours=9))


def product():
    return {'brand': 'Patagonia', 'categoryId': 'fleece', 'specs': {
        'model': '40275', 'gender': "Men's", 'optionState': 'selectable',
        'weight': '340 g (12 oz)', 'fabric': MATERIAL}}


def schema():
    return [dict(**{'@type': 'ProductGroup', '@id': '#40275'}, productGroupID='40275',
        name=R1_TITLE, url=R1_URL, brand={'@type': 'Brand', 'name': 'Patagonia'},
        variesBy=['https://schema.org/color'], color=['BLK'], image=IMAGE, description=DESCRIPTION),
        {'@type': 'Product', 'isVariantOf': {'@id': '#40275'}, 'name': R1_TITLE + ' - Black',
         'color': 'Black', 'mpn': '40275-BLK', 'sku': '40275-BLK', 'image': IMAGE,
         'offers': {'@type': 'Offer', 'image': IMAGE,
                    'url': R1_URL + '?dwvar_40275_color=BLK'}}]


def fixture(data=None):
    return ('<html><head><link rel="canonical" href="' + R1_URL + '">'
        '<script type="application/ld+json">' + json.dumps(schema() if data is None else data)
        + '</script></head><body><div class="page page-pdp product-detail" data-pid="40275">'
        '<h1 id="product-title">' + R1_TITLE + '</h1><span>| 製品番号 40275</span>'
        '<button class="product-swatch" data-color="BLK" data-attr="BLK" data-attr-value="BLK" '
        'data-caption="Black" aria-label="カラー Black"></button>'
        '<label class="pdp-size-select" for="size-S" data-size="S" data-attr-value="S" '
        'data-size-url="https://www.patagonia.jp/on/demandware.store/Sites-patagonia-jp-Site/'
        'ja_JP/Product-Variation?pid=40275&amp;dwvar_40275_size=S&amp;dwvar_40275_color=BLK">'
        '<input type="radio" name="size" id="size-S" value="S" aria-hidden="true"></label>'
        '<article>' + DESCRIPTION + '</article><div id="collapsible-1">'
        '<ul><li><h3 class="content-feature__heading">重さ</h3>'
        '<p class="content-feature__description">340 g (12 oz)</p></li></ul></div>'
        '<div class="accordion-content collapse" id="collapsible-2"><ul>'
        '<li class="pdp__content-feature no-header"><p class="content-feature__description">'
        + MATERIAL + '</p></li></ul></div></div>'
        '<aside>別商品40256 レビュー 素材も重量も対象外</aside></body></html>')


class OfficialPatagoniaTests(unittest.TestCase):
    def test_primary_dom_and_group_prove_selectable_but_not_fixed_sku(self):
        b = inspect(product(), R1_URL, fixture(), IMAGE)
        self.assertIsNotNone(b)
        self.assertEqual(('40275', ['Black'], ['S']), (b['model'], b['colors'], b['sizes']))
        self.assertEqual('patagonia-primary-product-dom', b['sourceKind'])
        self.assertEqual(DESCRIPTION, b['manufacturerExcerpt']['text'])
        self.assertNotIn('レビュー', b['manufacturerExcerpt']['text'])
        p = product(); p['specs'].update(optionState='fixed', color='Black', size='S')
        self.assertIsNone(inspect(p, R1_URL, fixture(), IMAGE))

    def test_exact_url_contract_and_primary_model_gender(self):
        for url in (R1_URL+'?x=1', R1_URL+'/', R1_URL.replace('patagonia.jp','patagonia.jp.example')):
            self.assertIsNone(inspect(product(), url, fixture()))
        for key, value in (('model', '40256'), ('gender', "Women's"), ('weight', '100g'), ('fabric', 'nylon')):
            p = product(); p['specs'][key] = value
            self.assertIsNone(inspect(p, R1_URL, fixture()))
        for old, new in (('data-pid="40275"', 'data-pid="40256"'),
                         ('製品番号 40275', '製品番号 40256'),
                         ('id="product-title"', 'id="related-title"'),
                         ('メンズ・R1', 'ウィメンズ・R1')):
            self.assertIsNone(inspect(product(), R1_URL, fixture().replace(old, new)))

    def test_missing_or_ambiguous_primaries_cannot_be_repaired_by_recommendations(self):
        for extra in ('<div class="page-pdp product-detail" data-pid="40275"></div>',
                      '<link rel="canonical" href="'+R1_URL+'">'):
            self.assertIsNone(inspect(product(), R1_URL, fixture().replace('</body>',extra+'</body>')))
        self.assertIsNone(inspect(product(), R1_URL, fixture().replace('class="page page-pdp product-detail"','class="related"')))
        self.assertIsNone(inspect(product(), R1_URL, fixture().replace('<h1 id=', '<h1 hidden id=')))

    def test_chart_only_or_other_product_size_urls_never_prove_options(self):
        for old, new in (('class="pdp-size-select"', 'class="size-chart"'),
                         ('pid=40275&amp;', 'pid=40256&amp;'),
                         ('dwvar_40275_size=S', 'dwvar_40275_size=M'),
                         ('dwvar_40275_color=BLK', 'dwvar_40275_color=BLK&amp;dwvar_40275_color=LYTN'),
                         ('data-color="BLK"', 'data-color="OTHER"')):
            self.assertIsNone(inspect(product(), R1_URL, fixture().replace(old, new)))

    def test_linked_variants_and_images_cannot_mix_models(self):
        for changes in ({'sku':'40256-BLK'}, {'mpn':'40256-BLK'}, {'image':IMAGE.replace('40275','40256')},
                        {'color':'Other'}, {'name':'Related product'}):
            r = schema(); r[1].update(changes)
            self.assertIsNone(inspect(product(), R1_URL, fixture(r)))
        r = schema(); r.append(copy.deepcopy(r[1]))
        self.assertIsNone(inspect(product(), R1_URL, fixture(r)))
        r = schema(); r.append(copy.deepcopy(r[0]))
        self.assertIsNone(inspect(product(), R1_URL, fixture(r)))
        for image in (IMAGE+'&extra=1', '\n'+IMAGE, IMAGE.replace('40275','40256')):
            self.assertIsNone(inspect(product(), R1_URL, fixture(), image))

    def test_primary_facts_missing_hidden_or_only_in_reviews_are_not_proof(self):
        for old, new in (('id="collapsible-1"', 'id="reviews"'),
                         ('id="collapsible-2"', 'hidden id="collapsible-2"'),
                         ('>重さ</h3>', '>発送重量</h3>'),
                         ('<article>', '<article hidden>')):
            self.assertIsNone(inspect(product(), R1_URL, fixture().replace(old,new)))
        self.assertIsNone(inspect(product(),R1_URL,'<title>Hang Tight! Routing to checkout...</title>'))

    def test_nested_other_product_tile_cannot_supply_primary_weight(self):
        html = fixture().replace('<div id="collapsible-1">',
            '<div class="product-tile" data-pid="40256"><div id="collapsible-1">')
        html = html.replace('</p></li></ul></div>', '</p></li></ul></div></div>', 1)
        self.assertIsNone(inspect(product(), R1_URL, html))

    def test_color_sku_must_keep_exact_declared_model_prefix(self):
        for sku in ('BLK', '40275X-BLK', '40256-BLK', None):
            data = schema(); data[1].update(sku=sku, mpn=sku)
            self.assertIsNone(inspect(product(), R1_URL, fixture(data)))

    def test_hidden_ancestors_and_nested_hidden_facts_are_not_primary_proof(self):
        html = fixture()
        for changed in (
            html.replace('<body>', '<body hidden>'),
            html.replace('>340 g (12 oz)</p>', '><span hidden>340 g (12 oz)</span></p>'),
            html.replace('<article>' + DESCRIPTION, '<article><span hidden>' + DESCRIPTION + '</span>'),
            html.replace('>' + MATERIAL + '</p>', '><span style="display:none">' + MATERIAL + '</span></p>'),
            html.replace('<h1 id="product-title">' + R1_TITLE, '<h1 id="product-title"><span hidden>' + R1_TITLE + '</span>'),
        ):
            self.assertIsNone(inspect(product(), R1_URL, changed))


class CatalogPatagoniaIntegrationTests(unittest.TestCase):
    def test_explicit_fresh_capture_adapter_reaches_catalog_with_no_merchant_pass(self):
        from catalog import Catalog
        from test_catalog import PNG, response
        current = product()
        current.update(id='r1-capture-40275', name=R1_TITLE, imageUrl=IMAGE,
                       affiliateUrl='', amazonUrl='')
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); body = fixture().encode()
            source = root/'40275-browser-dom.html'; source.write_bytes(body)
            receipt = dict(schemaVersion=1, model='40275', requestedUrl=R1_URL, finalUrl=R1_URL,
                transport='managed-chrome-rendered-dom', captureCount=1, domReadPasses=2,
                readChunkChars=80000, identicalPasses=True, capturedAtJST=datetime.now(JST).isoformat(),
                domBytes=len(body), domSHA256=hashlib.sha256(body).hexdigest(), path=str(source))
            path = root/'receipt.json'; path.write_text(json.dumps(receipt))
            calls = []
            def upstream(url, *_):
                calls.append(url)
                return response(PNG, 'image/png') if url == IMAGE else response('<title>Hang Tight!</title>')
            fetch = r1_fallback_fetcher(current, path, upstream)
            gathered = Catalog({}, fetch, source_hints={current['id']: [R1_URL]}).gather(
                {'productIds': [current['id']]}, {'products': [current]})
            self.assertTrue(gathered['checks']['facts'])
            self.assertTrue(gathered['checks']['images'])
            self.assertFalse(gathered['checks']['affiliate'])
            self.assertEqual(1, calls.count(R1_URL))
            receipt['capturedAtJST'] = (datetime.now(JST)-timedelta(minutes=16)).isoformat()
            path.write_text(json.dumps(receipt))
            with self.assertRaises(BrowserSourceHold):
                fetch(R1_URL, {}, 20)

    def test_exact_manufacturer_binding_and_photo_gather_but_merchants_stay_missing(self):
        from catalog import Catalog
        from test_catalog import PNG, response
        from apparel_identity import binding_matches_product, public_binding
        current = product()
        current.update(id='r1-40275', name=R1_TITLE, imageUrl=IMAGE,
                       affiliateUrl='', amazonUrl='')
        calls = []
        def fetch(url, *_):
            calls.append(url)
            return response(PNG, 'image/png') if url == IMAGE else response(fixture())
        result = Catalog({}, fetch, source_hints={current['id']: [R1_URL]}).gather(
            {'productIds': [current['id']]}, {'products': [current]})
        self.assertTrue(result['checks']['facts'])
        self.assertTrue(result['checks']['images'])
        self.assertFalse(result['checks']['affiliate'])
        self.assertIn(IMAGE, calls)
        self.assertTrue(any(r['kind'] == 'manufacturer' for r in result['references']))
        self.assertTrue(any(r['kind'] == 'manufacturer-description' for r in result['references']))
        binding = inspect(current, R1_URL, fixture(), IMAGE)
        retained = public_binding(binding)
        self.assertTrue(binding_matches_product(retained, current))
        wrong = copy.deepcopy(current); wrong['specs']['model'] = '40256'
        self.assertFalse(binding_matches_product(retained, wrong))
        wrong = copy.deepcopy(current); wrong['brand'] = 'Other'
        self.assertFalse(binding_matches_product(retained, wrong))
        checkout = Catalog({}, lambda *_: response('<title>Hang Tight! Routing to checkout...</title>'),
            source_hints={current['id']: [R1_URL]}).gather(
                {'productIds': [current['id']]}, {'products': [current]})
        self.assertFalse(checkout['checks']['facts'])
        self.assertFalse(checkout['checks']['images'])
        self.assertFalse(checkout['checks']['affiliate'])


class BrowserCaptureTests(unittest.TestCase):
    def test_checkout_response_uses_one_fresh_renderer_capture_and_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);body=fixture().encode();source=root/'40275-browser-dom.html';source.write_bytes(body)
            receipt=dict(schemaVersion=1,model='40275',requestedUrl=R1_URL,finalUrl=R1_URL,
                transport='managed-chrome-rendered-dom',captureCount=1,domReadPasses=2,
                readChunkChars=80000,identicalPasses=True,capturedAtJST=datetime.now(JST).isoformat(),
                domBytes=len(body),domSHA256=hashlib.sha256(body).hexdigest(),path=str(source))
            path=root/'receipt.json';path.write_text(json.dumps(receipt));calls=[]
            def checkout(url,headers,timeout):
                calls.append(url)
                return {'status':200,'headers':{'content-type':'text/html'},'body':b'<title>Hang Tight!</title>'}
            response=r1_fallback_fetcher(product(),path,checkout)(R1_URL,{},20)
            self.assertEqual([R1_URL],calls)
            self.assertEqual(body,response['body'])
            self.assertEqual(receipt,response['sourceProvenance'])
            self.assertEqual(receipt['domSHA256'],response['headers']['x-editorial-source-dom-sha256'])
            self.assertIsNone(response['originHttpStatus'])

    def test_adapter_prefers_actual_normal_html_and_never_retries_missing_capture(self):
        calls=[]
        def success(url,headers,timeout):
            calls.append(url)
            return {'status':200,'headers':{'content-type':'text/html'},'body':fixture().encode()}
        f=r1_fallback_fetcher(product(),'/nonexistent/receipt.json',success)
        self.assertEqual(fixture().encode(),f(R1_URL,{'User-Agent':'Mozilla/5.0'},20)['body'])
        self.assertEqual([R1_URL],calls)
        calls.clear()
        def checkout(url,headers,timeout):
            calls.append(url)
            return {'status':200,'headers':{'content-type':'text/html'},'body':b'<title>Hang Tight!</title>'}
        f=r1_fallback_fetcher(product(),'/nonexistent/receipt.json',checkout)
        with self.assertRaises(BrowserSourceHold):f(R1_URL,{},20)
        self.assertEqual([R1_URL],calls)
        with self.assertRaises(BrowserSourceHold):f(R1_URL,{'Authorization':'not-a-real-secret'},20)
        self.assertEqual([R1_URL],calls)

    def test_fresh_exact_url_model_and_full_dom_hash_are_required(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); html = fixture().encode(); path = root/'40275-browser-dom.html'
            path.write_bytes(html); now = datetime(2026,11,23,1,0,tzinfo=JST)
            receipt = dict(schemaVersion=1, model='40275', requestedUrl=R1_URL, finalUrl=R1_URL,
                transport='managed-chrome-rendered-dom', captureCount=1,domReadPasses=2,
                readChunkChars=80000,identicalPasses=True,capturedAtJST=now.isoformat(),
                domBytes=len(html),domSHA256=hashlib.sha256(html).hexdigest(),path=str(path))
            receipt_path=root/'receipt.json'
            def load(value):
                receipt_path.write_text(json.dumps(value))
                return load_r1_capture(product(),receipt_path,IMAGE,now=now)
            result=load(receipt)
            self.assertIsNotNone(result)
            self.assertEqual(html.decode(),result['html'])
            for key,value in (('model','40256'),('requestedUrl',R1_URL+'?x=1'),
                              ('finalUrl','https://example.com/'),('domSHA256','0'*64),
                              ('domBytes',len(html)-1),('identicalPasses',False),('captureCount',2),
                              ('capturedAtJST',(now-timedelta(minutes=16)).isoformat()),
                              ('capturedAtJST',(now+timedelta(seconds=1)).isoformat()),
                              ('capturedAtJST',now.replace(tzinfo=None).isoformat())):
                self.assertIsNone(load(dict(receipt,**{key:value})),key)
            path.write_bytes(html+b'changed')
            self.assertIsNone(load(receipt))
            bad=b'<html><title>Hang Tight!</title></html>';path.write_bytes(bad)
            self.assertIsNone(load(dict(receipt,domBytes=len(bad),domSHA256=hashlib.sha256(bad).hexdigest())))


if __name__ == '__main__':
    unittest.main()
