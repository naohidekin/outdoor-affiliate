"""Captain UK primary-product DOM regression and adversarial identity tests."""
import unittest
from catalog import Catalog, _Page, _primary_identity, _spec_evidence
from test_catalog import PNG

SOURCE = 'https://www.captainstag.net/products/UK-4004.html'
IMAGE = 'https://www.captainstag.net/item_img/l/UK-4004.png'


def fixture(code='UK-4004', extra='', header=None, image=True):
    # Captured maker selectors/ordering: product_id is a sibling of item_main,
    # not a page-title SKU. Values retain the official spec table wordings.
    return ('<title>リムーブ LEDランタンDX - アウトドア・キャンプ用品 - キャプテンスタッグ</title>'
            '<main id="main">' + (header if header is not None else
            '<header class="item_area_head"><p class="product_id">'+code+'</p>'
            '<h1><em>リムーブ LEDランタンDX</em></h1></header>') +
            '<section class="item_main"><div class="item_area"><div class="item_main_image">' +
            ('<img src="'+IMAGE+'">' if image else '') + '</div></div>'
            '<div class="txt_product_spec"><table><tr><th scope="row">重量(約)</th>'
            '<td>780g（乾電池含まず）</td></tr></table></div></section>'+extra+'</main>')


class CaptainUkTests(unittest.TestCase):
    def identity(self, html, model='UK-4004'):
        return _primary_identity(_Page(html), model, 'キャプテンスタッグ')

    def gather(self, html):
        def fetch(url, *_):
            return {'status': 200, 'headers': {'content-type': 'text/html' if url == SOURCE else 'image/png'},
                    'body': html.encode() if url == SOURCE else PNG}
        product = {'id': 'led-tent-009', 'name': 'キャプテンスタッグ リムーブ LEDランタンDX UK-4004',
                   'brand': 'キャプテンスタッグ', 'categoryId': 'light', 'specs': {'model': 'UK-4004',
                   '重量(約)': '780g（乾電池含まず）'}, 'imageUrl': IMAGE}
        return Catalog({}, fetcher=fetch, source_hints={product['id']: [SOURCE]}).gather(
            {'productIds': [product['id']]}, {'products': [product]})

    def test_actual_primary_header_and_table_bind_exact_uk_model(self):
        html = fixture()
        self.assertTrue(self.identity(html))
        page = _Page(html)
        self.assertIsNotNone(_spec_evidence(page, 'UK-4004', '重量(約)', '780g（乾電池含まず）', True, 'キャプテンスタッグ'))
        self.assertTrue(self.gather(html)['checks']['facts'])
        self.assertTrue(self.gather(html)['checks']['images'])

    def test_wrong_primary_model_and_substring_rejected(self):
        for code in ('UK-4005', 'UK-40040'):
            with self.subTest(code=code):
                self.assertFalse(self.identity(fixture(code)))
                self.assertFalse(self.gather(fixture(code))['checks']['facts'])

    def test_navigation_aside_or_recommendation_code_cannot_authorize_table(self):
        header = '<header class="item_area_head"><p class="product_id">UK-4004</p></header>'
        for tag, attrs in (('nav', ''), ('aside', ''), ('section', ' class="sec_other_item"')):
            with self.subTest(tag=tag):
                html = fixture(header='', extra='<'+tag+attrs+'>'+header+'</'+tag+'>')
                self.assertFalse(self.identity(html))
        self.assertFalse(self.identity(fixture(header='')+'<p>UK-4004</p>'))

    def test_duplicate_or_conflicting_primary_models_fail_closed(self):
        for code in ('UK-4004', 'UK-4005', 'M-8249'):
            with self.subTest(code=code):
                extra = '<header class="item_area_head"><p class="product_id">'+code+'</p></header>'
                self.assertFalse(self.identity(fixture(extra=extra)))

    def test_recommendation_model_does_not_override_legitimate_primary(self):
        extra = '<section class="sec_other_item"><p class="product_id">UK-4005</p></section>'
        self.assertTrue(self.identity(fixture(extra=extra)))

    def test_primary_table_outside_main_or_only_recommendations_rejected(self):
        html = fixture().replace('<main id="main">', '<main id="other">')
        self.assertFalse(self.identity(html))
        html = fixture().replace('<section class="item_main">', '<section class="item_main sec_other_item">')
        self.assertFalse(self.identity(html))

    def test_image_still_requires_dom_membership(self):
        result = self.gather(fixture(image=False))
        self.assertTrue(result['checks']['facts'])
        self.assertFalse(result['checks']['images'])

    def test_wrong_brand_title_does_not_authorize_primary_table(self):
        self.assertFalse(self.identity(fixture().replace('キャプテンスタッグ</title>', 'OTHER</title>')))

    def test_m_primary_model_still_supported(self):
        self.assertTrue(self.identity(fixture('M-8249'), model='M-8249'))


if __name__ == '__main__':
    unittest.main()
