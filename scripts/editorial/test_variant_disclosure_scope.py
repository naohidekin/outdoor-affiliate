"""The observed linked variation grants no seller-wide option claim."""
import unittest
from runtime import Runtime

class VariantDisclosureScopeTests(unittest.TestCase):
    def test_fixed_is_scoped_to_link_initial_selection(self):
        gathered={'products':[{'id':'p','name':'Product'}], 'evidence':{'products':[
            {'productId':'p','destinations':[
                {'channel':'amazon','apparelBinding':{'merchantOptionState':'fixed'}},
                {'channel':'rakuten','apparelBinding':{'merchantOptionState':'selectable'}}]}]}}
        text=Runtime._apparel_variant_disclosures(gathered)
        self.assertEqual(1,len(text))
        self.assertIn('この記事のリンク先で確認した選択内容',text[0])
        self.assertIn('Amazonは初期選択で確認したバリエーション',text[0])
        self.assertIn('各販売先の全選択肢を示すものではありません',text[0])
        self.assertNotIn('Amazonは確認済みの固定バリエーション',text[0])

    def test_same_states_keep_no_extra_disclosure(self):
        gathered={'evidence':{'products':[{'productId':'p','destinations':[
            {'channel':'amazon','apparelBinding':{'merchantOptionState':'selectable'}},
            {'channel':'rakuten','apparelBinding':{'merchantOptionState':'selectable'}}]}]}}
        self.assertEqual([],Runtime._apparel_variant_disclosures(gathered))

if __name__=='__main__': unittest.main()
