"""Mont-bell primary DOM scopes survive void tags without absorbing page chrome."""
import unittest

from apparel_identity import _MontbellProduct, inspect_apparel_page
from test_apparel_identity import montbell_dom, product


URL = 'https://webshop.montbell.jp/goods/disp.php?product_id=1101493'
IMAGE = 'https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg'


def page():
    return montbell_dom().replace(
        '<h2 class="ttlType01">Plasma Men\'s</h2>',
        '<h2 class="ttlType01">Plasma<br><span>Men\'s</span>'
        '<img src="gender-icon.jpg"></h2>'
        '<div>STOCK_UI_ONLY</div><script>AFTER_TITLE_SCRIPT</script>')


class MontbellProductScopeTests(unittest.TestCase):
    def test_heading_br_and_nested_span_do_not_absorb_stock_related_or_scripts(self):
        parsed = _MontbellProduct(page())
        self.assertEqual("Plasma Men's", ' '.join(parsed.title_parts))
        self.assertNotIn('STOCK_UI_ONLY', ''.join(parsed.title_parts))
        self.assertNotIn('AFTER_TITLE_SCRIPT', ''.join(parsed.title_parts))
        self.assertNotIn('別商品', ''.join(parsed.title_parts))

    def test_inputs_and_images_do_not_keep_primary_scope_open_into_related_products(self):
        source = page() + '''<aside><input name="product_id" value="9999999">
        <input name="all_color" value="WRONG"><select name="sel_size">
        <option value="WRONG">WRONG</option></select>
        <img src="/common/images/product/prod_k/k_9999999_bk.jpg"></aside>'''
        parsed = _MontbellProduct(source)
        self.assertEqual(['1101493'], parsed.product_ids)
        self.assertEqual([['BK']], parsed.color_sets)
        self.assertEqual(['S'], parsed.sizes)
        self.assertNotIn('別商品', ''.join(parsed.main_text))
        self.assertEqual(['/common/images/product/prod_k/k_1101493_bk.jpg'], parsed.images)
        binding = inspect_apparel_page(product(imageUrl=IMAGE), URL, source, IMAGE)
        self.assertIsNotNone(binding)
        self.assertEqual(('7デニール ナイロン', '130g', ['S'], ['BK']),
                         (binding['fabric'], binding['weight'], binding['sizes'], binding['colors']))

    def test_closing_heading_ancestor_unwinds_unclosed_span_and_ignores_unmatched_end_tag(self):
        source = page().replace("<span>Men's</span>", "<span>Men's</unknown>")
        parsed = _MontbellProduct(source)
        self.assertEqual("Plasma Men's", ' '.join(parsed.title_parts))
        binding = inspect_apparel_page(product(imageUrl=IMAGE), URL, source, IMAGE)
        self.assertIsNotNone(binding)

    def test_void_spelling_and_spec_br_keep_material_weight_and_size_checks_strict(self):
        for br in ('<br>', '<br/>', '<br />', '<br></br>'):
            with self.subTest(br=br):
                source = page().replace('<br>', br)
                current = product(imageUrl=IMAGE)
                self.assertIsNotNone(inspect_apparel_page(current, URL, source, IMAGE))
                for old, new in [('130g', '131g'), ('7デニール ナイロン', '別素材'),
                                 ('value="1101493"', 'value="9999999"'),
                                 ('<option value="S">S</option>', '')]:
                    with self.subTest(changed=old):
                        self.assertIsNone(inspect_apparel_page(
                            current, URL, source.replace(old, new), IMAGE))


if __name__ == '__main__':
    unittest.main()
