"""Offline pure diagnostic: never changes a product or pipeline decision."""
import copy
import unittest
from unverified_display_inspector import inspect_unverified_display

class DisplayInspectorTests(unittest.TestCase):
    def test_reports_only_positive_unverified_display_fields_and_id(self):
        products=[{'id':'p1','price':2750,'rating':3.5,'name':'not returned','secret':'not returned'}]
        evidence={'products':[{'productId':'p1','unverifiedFields':['price','rating','description']}]}
        snapshot=copy.deepcopy((products,evidence))
        self.assertEqual(inspect_unverified_display(products,evidence),[
            {'productId':'p1','field':'price','reason':'unverified_display_value'},
            {'productId':'p1','field':'rating','reason':'unverified_display_value'}])
        self.assertEqual((products,evidence),snapshot)
    def test_zero_negative_missing_and_non_numeric_not_reported(self):
        for value in (0,-1,None,False,True,'2750',float('nan'),float('inf'),float('-inf')):
            with self.subTest(value=value):
                self.assertEqual([],inspect_unverified_display([{'id':'p','price':value}],{'products':[{'productId':'p','unverifiedFields':['price']}]}))
    def test_unlisted_fields_and_other_products_do_not_match(self):
        p=[{'id':'p1','price':10,'rating':2}]
        for e in ({'products':[]},{'products':[{'productId':'p1','unverifiedFields':['description']}]},
                  {'products':[{'productId':'p2','unverifiedFields':['price','rating']}]}):
            self.assertEqual([],inspect_unverified_display(p,e))
    def test_duplicate_evidence_deduplicates_and_output_order_is_stable(self):
        row={'productId':'p','unverifiedFields':['rating','price']}
        r=inspect_unverified_display([{'id':'p','price':2,'rating':1}],{'products':[row,row]})
        self.assertEqual(['price','rating'],[x['field'] for x in r])
    def test_invalid_structure_fails_explicitly_not_as_clean_result(self):
        for products,evidence in ((None,{}),([],None),([{}],{'products':[]}),
            ([{'id':'p'},{'id':'p'}],{'products':[]}),([] ,{'products':[{'productId':'p','unverifiedFields':'price'}]})):
            with self.subTest(products=products,evidence=evidence),self.assertRaises(ValueError):
                inspect_unverified_display(products,evidence)
