"""Offline, sanitized primary DOM contracts; no JS or live catalogue changes."""
import unittest

from goldwin_na62650 import inspect_goldwin_na62650, URL, FABRIC, WEIGHT


IMAGE = 'https://itemimg.goldwin.co.jp/itemimg/GDW01/A0GDW0001QCX/02_V901.jpg'


def product():
    return dict(brand='THE NORTH FACE', categoryId='fleece',
                specs=dict(model='NA62650', gender="Men's", optionState='selectable',
                           fabric=FABRIC, weight=WEIGHT))


def fixture():
    return '''<html><head><link rel="canonical" href="URL"></head>
<body id="A0GDW0001QCX"><div id="item_detail">
<h1 class="item_detail_productname">デナリジャケット（メンズ）</h1>
<li class="item_detail_sex">メンズ</li><li class="item_detail_category">フリース</li>
<li class="item_detail_mkcode">NA62650</li>
<div id="item_detail_left"><div class="variationImg" data-vcbcode="V901">
<img alt="THE NORTH FACE(ザ・ノース・フェイス) ｜デナリジャケット（メンズ）"
 bigImage="IMAGE" src="IMAGE"></div></div>
<article id="item_detail_right"><div id="select_color_size_area">
<input class="cart_color_radio" name="color" value="V901" dispcColorCode="unused"
 dispColorCode="K" vcbname="ブラック">
<input class="cart_size_radio" name="size" value="A853" vcaname="L">
</div></article>
<div class="item_detail_table"><dl><dt>Fabric</dt><dd>FABRIC</dd>
<dt>Size</dt><dd>L</dd><dt>Weight</dt><dd>WEIGHT</dd><dt>Color</dt><dd>ブラック</dd>
</dl></div></div></body></html>'''.replace('URL', URL).replace('IMAGE', IMAGE).replace(
        'FABRIC', FABRIC).replace('WEIGHT', WEIGHT)


class GoldwinNa62650Tests(unittest.TestCase):
    def test_public_entry_claims_and_retained_scope(self):
        from apparel_identity import (inspect_apparel_page, claim_binding, public_binding,
                                      binding_matches_product)
        p = product()
        b = inspect_apparel_page(p, URL, fixture(), IMAGE)
        self.assertIsNotNone(b)
        self.assertEqual(self.inspect(), b)
        retained = public_binding(b)
        self.assertNotIn('sourceUrl', retained)  # Authority URL stays on the outer reference.
        self.assertTrue(binding_matches_product(retained, p))
        self.assertFalse(binding_matches_product(retained, p, channel='rakuten'))
        for key, value in [('model', 'NA62650'), ('material', FABRIC), ('weight', WEIGHT)]:
            claim = claim_binding(b, key, value)
            self.assertEqual('goldwin-na62650-primary-dom', claim['sourceKind'])
            self.assertIsNone(claim_binding(b, key, value + 'X'))
        for key, value in [('model', 'NA62650X'), ('gender', "Women's"),
                           ('fabric', 'Other'), ('weight', '700g'), ('class', 'hardshell')]:
            wrong = dict(retained, **{key: value})
            self.assertFalse(binding_matches_product(wrong, p))
        # A retained Goldwin proof is never repurposed for another model or fixed SKU.
        for change in ({'model': 'NA62650X'}, {'optionState': 'fixed', 'color': 'ブラック', 'size': 'L'}):
            q = product(); q['specs'].update(change)
            forged = dict(retained, **change)
            self.assertFalse(binding_matches_product(forged, q))
        self.assertIsNone(inspect_apparel_page(p, URL, fixture(), IMAGE,
                                               source_role='purchase', channel='rakuten'))

    def test_retained_goldwin_images_and_options_cannot_escape_known_primary_map(self):
        from apparel_identity import public_binding, binding_matches_product
        retained = public_binding(self.inspect())
        for images in ([IMAGE.replace('goldwin.co.jp', 'goldwin.co.jp.example')],
                       [IMAGE.replace('A0GDW0001QCX', 'OTHER')], [IMAGE + '?extra=1'],
                       [IMAGE.replace('02_V901', '02_AW18')], [], [IMAGE, IMAGE], IMAGE, None):
            with self.subTest(images=images):
                self.assertFalse(binding_matches_product(dict(retained, imageUrls=images), product()))
        for changes in ({'colors': ['未確認色']}, {'colors': ['ブラック', 'ブラック']},
                        {'sizes': ['XXXL']}, {'sizes': ['L', 'L']}):
            self.assertFalse(binding_matches_product(dict(retained, **changes), product()))

    def test_catalog_gather_binds_primary_specs_and_photo_but_not_missing_merchants(self):
        from catalog import Catalog
        from test_catalog import PNG, response
        p = product()
        p.update(id='fleece-tnf-na62650', name='THE NORTH FACE デナリジャケット（メンズ）', imageUrl=IMAGE)
        calls = []
        def fetch(url, headers, timeout):
            calls.append(url)
            if url == IMAGE:
                return response(PNG, 'image/png')
            self.assertEqual(URL, url)
            self.assertEqual('Mozilla/5.0', headers.get('User-Agent'))
            self.assertEqual('text/html', headers.get('Accept'))
            return response(fixture())
        result = Catalog({}, fetch, source_hints={p['id']: [URL]}).gather(
            {'productIds': [p['id']]}, {'products': [p]})
        self.assertTrue(result['checks']['facts'])
        self.assertTrue(result['checks']['images'])
        self.assertFalse(result['checks']['affiliate'])
        self.assertTrue(result['blocked'])
        maker = [r for r in result['references'] if r['kind'] == 'manufacturer']
        self.assertEqual(1, len(maker))
        self.assertEqual('goldwin-na62650-primary-dom', maker[0]['apparelBinding']['sourceKind'])
        claims = result['evidence']['products'][0]['claims']
        for field in ('fabric', 'weight'):
            c = next(c for c in claims if c['field'] == field)
            self.assertTrue(c['verified'])
            self.assertEqual('goldwin-na62650-primary-dom', c['binding']['sourceKind'])

    def test_transport_scope_does_not_expand_to_other_goldwin_models_or_hosts(self):
        from catalog import Catalog
        from test_catalog import response
        for url in (URL + 'X', URL.replace('NA62650', 'NA62651'),
                    URL.replace('goldwin.co.jp', 'goldwin.co.jp.example')):
            calls = []
            def fetch(target, headers, timeout):
                calls.append(headers)
                return response('<html></html>')
            Catalog({}, fetch).request(url)
            self.assertNotIn('User-Agent', calls[0])

    def inspect(self, html=None, p=None, url=URL, image=IMAGE):
        return inspect_goldwin_na62650(p or product(), url, html or fixture(), image)

    def test_primary_facts_options_and_exact_observed_photo(self):
        b = self.inspect()
        self.assertIsNotNone(b)
        self.assertEqual(('NA62650', FABRIC, WEIGHT), (b['model'], b['fabric'], b['weight']))
        self.assertEqual((['ブラック'], ['L'], [IMAGE]), (b['colors'], b['sizes'], b['imageUrls']))
        self.assertEqual('goldwin-na62650-primary-dom', b['sourceKind'])
        self.assertNotIn('sourceVariant', b)  # DOM options are not a selected SKU.

    def test_exact_contract_and_url_only_no_fixed_variant_inference(self):
        for url in (URL + '?color=K', URL + '/', URL.replace('goldwin.co.jp', 'goldwin.co.jp.example')):
            self.assertIsNone(self.inspect(url=url))
        for k, v in [('model', 'NA62650-K'), ('model', 'NA62650A'), ('gender', "Women's"),
                     ('fabric', 'Other'), ('weight', '710g'), ('optionState', 'fixed')]:
            p = product(); p['specs'].update({k: v}, color='ブラック', size='L')
            self.assertIsNone(self.inspect(p=p))
        p = product(); p['brand'] = 'Other'; self.assertIsNone(self.inspect(p=p))

    def test_primary_scope_cannot_be_repaired_by_navigation_related_or_scripts(self):
        for old, new in [('>NA62650</li>', '>NA62650A</li>'), ('>メンズ</li>', '>レディース</li>'),
                         ('>デナリジャケット（メンズ）</h1>', '>Other</h1>'),
                         ('id="A0GDW0001QCX"', 'id="Other"'), ('class="item_detail_table"', 'class="related"')]:
            self.assertIsNone(self.inspect(fixture().replace(old, new)))
        self.assertIsNone(self.inspect(fixture().replace('id="item_detail"', 'id="related"')))
        self.assertIsNone(self.inspect(fixture().replace('<div id="item_detail">', '<div id="item_detail" hidden>')))
        self.assertIsNone(self.inspect(fixture() + fixture()))
        missing = fixture().replace('<li class="item_detail_mkcode">NA62650</li>', '')
        self.assertIsNone(self.inspect(missing + '<aside>NA62650</aside><script>NA62650</script>'))

    def test_options_and_images_are_bound_to_one_primary_product(self):
        for old, new in [('vcaname="L"', 'vcaname="M"'), ('vcbname="ブラック"', 'vcbname="グレー"'),
                         ('data-vcbcode="V901"', 'data-vcbcode="OTHER"'),
                         ('dispColorCode="K"', 'dispColorCode="OTHER"')]:
            self.assertIsNone(self.inspect(fixture().replace(old, new)))
        for image in (IMAGE.replace('goldwin.co.jp', 'goldwin.co.jp.example'), IMAGE + '?extra=1',
                      IMAGE.replace('A0GDW0001QCX', 'OTHER'), IMAGE.replace('https:', 'http:')):
            self.assertIsNone(self.inspect(image=image))
            self.assertIsNone(self.inspect(fixture().replace(IMAGE, image), image=image))
        self.assertIsNone(self.inspect(fixture().replace('name="size"', 'name="unrelated"')))


if __name__ == '__main__':
    unittest.main()
