"""Regression fixtures from the 2026-11-13 official primary DOM recheck.

These test exact candidate values, not weaker product identity or fuzzy specs.
No network, model calls, or production state changes.
"""
import unittest
from catalog import _Page, _primary_identity, _spec_evidence


class ReresearchPrimaryTests(unittest.TestCase):
    def test_us1900_requires_official_numeric_part_number(self):
        html = ('<title>ツインバーナーUS-1900 - ユニフレーム</title>'
                '<article id="product"><div id="item"><p>No.610305</p></div>'
                '<ul class="item-spec"><li><dl><dt>最大火力</dt>'
                '<dd>プレミアムガス：3,900kcal/h×2 レギュラーガス：3,000kcal/h×2</dd>'
                '</dl></li></ul></article>')
        p = _Page(html)
        self.assertTrue(_primary_identity(p, '610305', 'ユニフレーム'))
        self.assertIsNone(_primary_identity(p, 'US-1900', 'ユニフレーム'))
        self.assertIsNotNone(_spec_evidence(p, '610305', '最大火力',
            'プレミアムガス：3,900kcal/h×2 レギュラーガス：3,000kcal/h×2', True, 'ユニフレーム'))
        self.assertIsNone(_spec_evidence(p, '610305', '最大火力', '3,900kcal/h×2', True, 'ユニフレーム'))
        self.assertIsNone(_primary_identity(_Page(html.replace('No.610305', 'No.610350')), '610305', 'ユニフレーム'))

    def test_primus_2245_keeps_pack_dimension_order_and_suffix(self):
        html = ('<title>2245ランタン点火装置付: PRIMUS</title><div class="block-goods-detail">'
                '<dl class="block-goods-code"><dt>商品コード</dt><dd>IP-2245A-S</dd></dl>'
                '<dl class="block-goods-comment2"><dd>【重量】200g【収納サイズ】8.3×8.3×12.7cm（縦×横×奥行）</dd></dl></div>')
        p = _Page(html)
        self.assertTrue(_primary_identity(p, 'IP-2245A-S', 'プリムス'))
        self.assertIsNotNone(_spec_evidence(p, 'IP-2245A-S', '収納サイズ', '8.3×8.3×12.7cm（縦×横×奥行）', True, 'プリムス'))
        self.assertIsNone(_spec_evidence(p, 'IP-2245A-S', '収納サイズ', '8.3×8.3×12.7cm', True, 'プリムス'))
        self.assertIsNone(_primary_identity(_Page(html.replace('IP-2245A-S', 'IP-2245B-S')), 'IP-2245A-S', 'プリムス'))

    def test_soto_233_does_not_drop_fuel_conditions_or_accept_case_set(self):
        html = ('<title>虫の寄りにくいランタン ST-233 - SOTO</title>'
                '<article class="pdContents"><section class="pdContents__info">'
                '<dl class="pd__specification"><dd><ul><li><h3>使用時間</h3>'
                '<p>約3.0時間（ST-760使用時） 約3.5時間（ST-700使用時）</p>'
                '</li></ul></dd></dl></section></article>')
        p = _Page(html)
        self.assertTrue(_primary_identity(p, 'ST-233', 'SOTO'))
        self.assertIsNotNone(_spec_evidence(p, 'ST-233', '使用時間', '約3.0時間（ST-760使用時） 約3.5時間（ST-700使用時）', True, 'SOTO'))
        self.assertIsNone(_spec_evidence(p, 'ST-233', '使用時間', '約3.0時間', True, 'SOTO'))
        self.assertIsNone(_primary_identity(_Page(html.replace('ST-233 -', 'ST-233CS -')), 'ST-233', 'SOTO'))

    def test_uk4075_olive_exact_header_not_related_black(self):
        html = ('<title>CS ストリングライト（オリーブ） - キャプテンスタッグ</title>'
                '<main id="main"><header class="item_area_head"><p class="product_id">UK-4075</p></header>'
                '<section class="item_main"><div class="txt_product_spec"><table><tr>'
                '<th>重量(約)</th><td>190g</td></tr></table></div></section>'
                '<section class="sec_other_item"><p>UK-4074</p></section></main>')
        p = _Page(html)
        self.assertTrue(_primary_identity(p, 'UK-4075', 'キャプテンスタッグ'))
        self.assertIsNotNone(_spec_evidence(p, 'UK-4075', '重量(約)', '190g', True, 'キャプテンスタッグ'))
        self.assertIsNone(_primary_identity(p, 'UK-4074', 'キャプテンスタッグ'))
        self.assertIsNone(_spec_evidence(p, 'UK-4075', '防水', 'IPX4', True, 'キャプテンスタッグ'))


if __name__ == '__main__':
    unittest.main()
