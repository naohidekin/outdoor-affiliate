"""Sanitized 1101606/1128733 primary DOM observed on Native 2026-11-23.

Keeps #contents > primary identity > 商品情報 > column1/innerCont > 仕様/p,
including literal source material lines. No live requests or merchant changes.
"""
import copy
import html
import unittest

from apparel_identity import inspect_apparel_page
from test_apparel_identity import montbell_dom, product as legacy_product


FABRICS = {
    '1101606': ('表地：20デニール・バリスティック®ナイロン・リップストップ[はっ水加工・帯電防止加工]\n'
                '裏地：20デニール・バリスティック®ナイロン・タフタ[帯電防止加工]\n'
                '保温材：800フィルパワー・EXダウン'),
    '1128733': ('スーパー ドライテック3レイヤー［表：30デニール・バリスティック®ナイロン・リップストップ］\n'
                '透湿性: 40,000g/m²・24hrs（JIS L-1099B-1法・参考値）\n'
                '耐水圧: 20,000mm以上'),
}
WEIGHTS = {'1101606': '354g', '1128733': '254g'}
MATERIAL_LINKS = {
    '1101606': {'maker09': 'バリスティック®', 'maker41': 'EXダウン'},
    '1128733': {'maker09': 'バリスティック®', 'maker86': 'スーパー ドライテック'},
}


def current(model):
    return {'id': 'private-' + model, 'brand': 'mont-bell', 'categoryId': 'wear',
            'specs': {'apparelClass': 'down' if model == '1101606' else 'hardshell',
                      'model': model, 'gender': "Men's", 'optionState': 'selectable',
                      'material': FABRICS[model], 'weight': WEIGHTS[model]},
            'imageUrl': 'https://webshop.montbell.jp/common/images/product/prod_c/c_' + model + '_bk.jpg'}


def fixture(model):
    title = 'ライトアルパインダウン パーカ' if model == '1101606' else 'ストームクルーザー ジャケット'
    material = html.escape(FABRICS[model]).replace('\n', '<br>\n')
    return (f'<div id="contents"><h2 class="ttlType01">{title} Men\'s</h2>'
            f'<div id="maindataCont"><div>品番 #{model} ブランド モンベル</div>'
            f'<input name="product_id" value="{model}"><input name="all_color" value="BK">'
            '<select name="sel_size"><option value="L">L</option></select>'
            f'<a href="/common/images/product/prod_c/c_{model}_bk.jpg"></a></div>'
            '<h3 class="ttlType02c marginBottom5">商品情報</h3>'
            '<div class="column1 type01"><div class="innerCont"><p>主商品の説明。</p></div></div>'
            '<div class="column1 type01"><div class="innerCont">'
            f'<h4 class="ttlType03">仕様</h4><p>【素材】{material}<br>\n'
            f'【平均重量】{WEIGHTS[model]}<br>\n【カラー】ブラック(BK)<br>\n【サイズ】L<br>\n</p>'
            '</div></div><div class="column1 type01"><div class="innerCont iconArea">'
            '<h4 class="ttlType03">機能</h4></div></div>'
            '<h3 class="ttlType02c">詳細情報</h3><p>素材の説明。</p>'
            '<h3 class="ttlType02c">関連商品</h3><div class="related innerCont">別商品1109999</div></div>')


def inspect(value, source):
    url = 'https://webshop.montbell.jp/goods/disp.php?product_id=' + value['specs']['model']
    return inspect_apparel_page(value, url, source, value['imageUrl'])


class MontbellFullMaterialTests(unittest.TestCase):
    def test_observed_inline_material_glossary_links_preserve_exact_primary_text(self):
        for model, links in MATERIAL_LINKS.items():
            source = fixture(model)
            for code, label in links.items():
                anchor = (f'<a href="/material/aboutmaterial/maker/{code}.html" class="fancy_material" '
                          f'data-fancybox="iframe_material" data-type="iframe" '
                          f'data-custom-class="material" title="{label}">{label}</a>')
                source = source.replace(label, anchor)
            self.assertIsNotNone(inspect(current(model), source))
            self.assertIsNone(inspect(current(model), source.replace('/material/aboutmaterial/',
                              'https://other.example/material/aboutmaterial/')))
            self.assertIsNone(inspect(current(model), source.replace('maker09.html', 'maker99.html')))
            self.assertIsNone(inspect(current(model), source.replace('class="fancy_material"',
                              'class="related"')))

    def test_full_primary_block_binds_all_lines_and_weight_for_both_models(self):
        for model in FABRICS:
            with self.subTest(model=model):
                binding = inspect(current(model), fixture(model))
                self.assertIsNotNone(binding)
                self.assertEqual(FABRICS[model], binding['fabric'])
                self.assertEqual(WEIGHTS[model], binding['weight'])

    def test_shortened_missing_or_changed_contract_cannot_omit_source_claims(self):
        for model in FABRICS:
            for field, value in [('material', FABRICS[model].split('\n')[0]),
                                 ('material', FABRICS[model].replace('800', '900').replace('40,000', '60,000')),
                                 ('weight', '100g'), ('material', None), ('weight', None)]:
                p = current(model)
                if value is None:
                    del p['specs'][field]
                else:
                    p['specs'][field] = value
                with self.subTest(model=model, field=field, value=value):
                    self.assertIsNone(inspect(p, fixture(model)))

    def test_changed_qualifiers_or_component_in_primary_source_reject(self):
        mutations = {'1101606': [('裏地：20', '裏地：30'), ('保温材：800', '保温材：900'),
                                  ('帯電防止加工', '別の加工')],
                     '1128733': [('40,000', '60,000'), ('20,000mm以上', '20,000mm未満'),
                                  ('参考値', '保証値'), ('JIS L-1099B-1法', '別試験法')]}
        for model, edits in mutations.items():
            for old, new in edits:
                with self.subTest(model=model, old=old):
                    self.assertIsNone(inspect(current(model), fixture(model).replace(old, new)))

    def test_related_hidden_ambiguous_or_foreign_model_blocks_are_not_primary(self):
        for model in FABRICS:
            source = fixture(model)
            start = source.index('<div class="column1 type01"><div class="innerCont"><h4')
            end = source.index('</p></div></div>', start) + len('</p></div></div>')
            block = source[start:end]
            cases = [source[:start] + source[end:] + block,
                     source.replace(block, '<div class="related">' + block + '</div>'),
                     source.replace(block, '<aside>' + block + '</aside>'),
                     source.replace(block, '<div hidden>' + block + '</div>'),
                     source.replace(block, block + block),
                     source.replace('【素材】', '【素材】別型番1109999 '),
                     source.replace('id="contents"', 'id="recommendations"'),
                     source.replace('value="' + model + '"', 'value="1109999"')]
            for index, changed in enumerate(cases):
                with self.subTest(model=model, case=index):
                    self.assertIsNone(inspect(current(model), changed))

    def test_material_must_end_at_next_heading_not_weight_or_other_sections(self):
        for model in FABRICS:
            p = current(model)
            p['specs']['material'] += '\n【平均重量】' + WEIGHTS[model]
            self.assertIsNone(inspect(p, fixture(model)))

    def test_legacy_multiline_contract_does_not_gain_full_block_support(self):
        p = legacy_product(imageUrl='https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg')
        source = montbell_dom().replace('【平均重量】',
            '保温材：1000フィルパワー・EXダウン<br>\n【平均重量】')
        p['specs']['material'] += '\n保温材：1000フィルパワー・EXダウン'
        self.assertIsNone(inspect(p, source))

    def test_mixed_old_new_product_roots_cannot_repair_each_others_contracts(self):
        old = montbell_dom()
        for model in FABRICS:
            for source in (old + fixture(model), fixture(model) + old):
                self.assertIsNone(inspect(current(model), source))
                legacy = legacy_product(imageUrl='https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg')
                self.assertIsNone(inspect(legacy, source))
        self.assertIsNone(inspect(current('1101606'), fixture('1101606') + fixture('1128733')))

    def test_full_block_whitespace_normalization_keeps_line_order_and_conditions(self):
        for model in FABRICS:
            p = current(model)
            p['specs']['material'] = p['specs']['material'].replace('\n', '\r\n  ')
            self.assertIsNotNone(inspect(p, fixture(model)))
            p['specs']['material'] = '\n'.join(reversed(FABRICS[model].splitlines()))
            self.assertIsNone(inspect(p, fixture(model)))

    def test_legacy_single_line_and_first_material_block_remain_compatible(self):
        p = legacy_product(imageUrl='https://webshop.montbell.jp/common/images/product/prod_k/k_1101493_bk.jpg')
        for source in [montbell_dom(), montbell_dom().replace('【平均重量】',
                       '保温材：1000フィルパワー・EXダウン<br>\n【平均重量】')]:
            self.assertIsNotNone(inspect(p, source))
            wrong = copy.deepcopy(p); wrong['specs']['material'] = '別の素材'
            self.assertIsNone(inspect(wrong, source))

    def test_catalog_gather_uses_full_material_for_facts_and_photo_without_merchant_pass(self):
        from catalog import Catalog
        from test_catalog import PNG, response
        for model in FABRICS:
            p = current(model)
            p.update(affiliateUrl='', amazonUrl='')
            url = 'https://webshop.montbell.jp/goods/disp.php?product_id=' + model
            def fetch(target, *_):
                return response(PNG, 'image/png') if target == p['imageUrl'] else response(fixture(model))
            gathered = Catalog({}, fetch, {p['id']: [url]}).gather(
                {'productIds': [p['id']]}, {'products': [p]})
            self.assertTrue(gathered['checks']['facts'])
            self.assertTrue(gathered['checks']['images'])
            self.assertFalse(gathered['checks']['affiliate'])


if __name__ == '__main__':
    unittest.main()
