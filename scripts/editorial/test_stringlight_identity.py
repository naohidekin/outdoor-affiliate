# coding: utf-8
import unittest
from post_publication_audit import _merchant_identity

class StringLightIdentityTests(unittest.TestCase):
    product = {'brand': 'キャプテンスタッグ', 'name': 'キャプテンスタッグ CS ストリングライト UK-4075（オリーブ）', 'categoryId': 'light'}
    def test_observed_merchant_word_order(self):
        for title in ('CS ストリングライト オリーブ UK-4075 CAPTAIN STAG（キャプテンスタッグ）', 'キャプテンスタッグ(CAPTAIN STAG) LEDライト ランタン CS ストリングライト オリーブ UK-4075', 'キャプテンスタッグ UK-4075 string lights'):
            self.assertTrue(_merchant_identity(self.product, 'UK-4075', title))
    def test_wrong_identity_and_accessories_fail(self):
        for title in ('キャプテンスタッグ ストリングライト UK-4076', 'OTHER ストリングライト UK-4075', 'キャプテンスタッグ UK-4075 ストリングライト 専用ケース', 'キャプテンスタッグ UK-4075 ランタン', 'キャプテンスタッグ UK-4075 ストリングライト用 交換パーツ', 'キャプテンスタッグ UK-4075 ストリングライト用ケース', 'キャプテンスタッグ UK-4075 string lights用ケース', 'キャプテンスタッグ UK-4075 string lights用 交換パーツ'):
            self.assertFalse(_merchant_identity(self.product, 'UK-4075', title), title)
    def test_other_light_category_does_not_gain_string_permission(self):
        p = dict(self.product, name='キャプテンスタッグ CS 特殊ライト UK-4075')
        self.assertFalse(_merchant_identity(p, 'UK-4075', 'キャプテンスタッグ ストリングライト UK-4075'))
