# coding: utf-8
import unittest

from merchant_identity import inspect_merchant_identity


class MerchantIdentityTests(unittest.TestCase):
    def test_named_body_with_included_case_is_not_a_case_only_listing(self):
        product = {'name': 'イワタニ ジュニアコンパクトバーナー CB-JCB',
                   'brand': 'イワタニ', 'categoryId': 'burner'}
        self.assertEqual(inspect_merchant_identity(product, 'CB-JCB',
            'Iwatani イワタニ ジュニアコンパクトバーナー 日本製 ケース付き CB-JCB')['status'], 'passed')
        for title in ('Iwatani CB-JCB バーナー用ケース付き',
                      'Iwatani CB-JCB バーナー専用収納ケース付き',
                      'Iwatani CB-JCB 専用収納ケース付き バーナー',
                      'Iwatani CB-JCB バーナー ケース付属品',
                      'Iwatani CB-JCB バーナー対応インナーマット ケース付き',
                      'Iwatani CB-JCB バーナー ケース付き 本体なし'):
            self.assertNotEqual(inspect_merchant_identity(product, 'CB-JCB', title)['status'], 'passed')

    def test_accessory_bundle_requires_explicit_body_evidence(self):
        product = {'name': 'Snow Peak ランドロック', 'brand': 'Snow Peak', 'categoryId': 'tent'}
        for title in ('Snow Peak TP-671R tent footprint bundle',
                      'Snow Peak TP-671R テント対応インナーマットセット'):
            with self.subTest(title=title):
                self.assertEqual(inspect_merchant_identity(product, 'TP-671R', title)['status'], 'failed')

    def test_matching_body_accepts_explicit_japanese_english_brand_alias(self):
        product = {
            'name': 'スノーピーク 焚火台L',
            'brand': 'スノーピーク',
            'categoryId': 'firepit',
        }

        self.assertEqual(
            inspect_merchant_identity(
                product,
                'ST-032RS',
                'Snow Peak 焚き火台 L ST-032RS 3-4人用',
            ),
            {'status': 'passed', 'reason': 'merchant_identity_confirmed'},
        )

    def test_wrong_model_is_failed(self):
        product = {'name': 'SOTO アミカス', 'brand': 'SOTO', 'categoryId': 'burner'}

        self.assertEqual(
            inspect_merchant_identity(product, 'SOD-320', 'SOTO アミカス SOD-310 シングルバーナー'),
            {'status': 'failed', 'reason': 'merchant_model_mismatch'},
        )

    def test_wrong_numeric_model_is_failed(self):
        product = {
            'name': 'ユニフレーム ファイアグリル',
            'brand': 'ユニフレーム',
            'categoryId': 'firepit',
        }

        self.assertEqual(
            inspect_merchant_identity(product, '683040', 'ユニフレーム ファイアグリル 683041 焚火台'),
            {'status': 'failed', 'reason': 'merchant_model_mismatch'},
        )

    def test_brand_text_is_not_mistaken_for_accessory_noun(self):
        product = {
            'name': 'ユニフレーム ファイアグリル',
            'brand': 'ユニフレーム',
            'categoryId': 'firepit',
        }

        self.assertEqual(
            inspect_merchant_identity(
                product,
                '683040',
                'ユニフレーム(UNIFLAME) ファイアグリル 683040 キャンプ用グリル・焚火台',
            ),
            {'status': 'passed', 'reason': 'merchant_identity_confirmed'},
        )

    def test_spaced_japanese_brand_is_removed_before_accessory_scan(self):
        product = {
            'name': 'ユニフレーム ファイアグリル',
            'brand': 'ユニフレーム',
            'categoryId': 'firepit',
        }

        self.assertEqual(
            inspect_merchant_identity(
                product,
                '683040',
                'ユニ フレーム 683040 ファイアグリル 焚火台',
            ),
            {'status': 'passed', 'reason': 'merchant_identity_confirmed'},
        )

    def test_accessory_only_listing_is_failed(self):
        product = {'name': 'SOTO アミカス', 'brand': 'SOTO', 'categoryId': 'burner'}

        self.assertEqual(
            inspect_merchant_identity(product, 'SOD-320', 'SOTO SOD-320 専用収納ケース 本体は含まれません'),
            {'status': 'failed', 'reason': 'merchant_accessory_only'},
        )

    def test_compatibility_type_does_not_turn_accessory_set_into_body_bundle(self):
        cases = (
            (
                {'name': 'スノーピーク ランドロック', 'brand': 'スノーピーク', 'categoryId': 'tent'},
                'TP-671R',
                'Snow Peak TP-671R テント用インナーマットセット',
            ),
            (
                {'name': 'SOTO アミカス', 'brand': 'SOTO', 'categoryId': 'burner'},
                'SOD-320',
                'SOTO SOD-320 バーナー用収納ケースセット',
            ),
        )

        for product, model, title in cases:
            with self.subTest(title=title):
                self.assertEqual(
                    inspect_merchant_identity(product, model, title),
                    {'status': 'failed', 'reason': 'merchant_accessory_only'},
                )

    def test_explicit_body_exclusion_overrides_body_bundle_words(self):
        product = {
            'name': 'TokyoCamp 焚火台 HAKOSUKA',
            'brand': 'TokyoCamp',
            'categoryId': 'firepit',
        }

        self.assertEqual(
            inspect_merchant_identity(
                product,
                'HAKOSUKA',
                'TokyoCamp HAKOSUKA 焚火台 本体なし 本体セット',
            ),
            {'status': 'failed', 'reason': 'merchant_accessory_only'},
        )

    def test_english_brand_substrings_are_not_brand_evidence(self):
        product = {'name': 'SOTO アミカス', 'brand': 'SOTO', 'categoryId': 'burner'}

        for title in (
            'NotSOTO アミカス SOD-320 シングルバーナー',
            'SOTOSOTODAYS アミカス SOD-320 シングルバーナー',
        ):
            with self.subTest(title=title):
                self.assertEqual(
                    inspect_merchant_identity(product, 'SOD-320', title),
                    {'status': 'unverified', 'reason': 'merchant_brand_evidence_missing'},
                )

    def test_compact_english_brand_alias_remains_allowed(self):
        product = {
            'name': 'スノーピーク 焚火台L',
            'brand': 'スノーピーク',
            'categoryId': 'firepit',
        }

        self.assertEqual(
            inspect_merchant_identity(product, 'ST-032RS', 'SnowPeak 焚き火台 L ST-032RS'),
            {'status': 'passed', 'reason': 'merchant_identity_confirmed'},
        )

    def test_missing_product_brand_is_unverified(self):
        product = {'name': 'アミカス', 'categoryId': 'burner'}

        self.assertEqual(
            inspect_merchant_identity(product, 'SOD-320', 'SOTO アミカス SOD-320 シングルバーナー'),
            {'status': 'unverified', 'reason': 'product_brand_missing'},
        )

    def test_conflicting_size_variant_is_unverified(self):
        product = {
            'name': 'スノーピーク 焚火台L',
            'brand': 'スノーピーク',
            'categoryId': 'firepit',
        }

        self.assertEqual(
            inspect_merchant_identity(
                product,
                'ST-032RS',
                'スノーピーク 焚火台 L ST-032RS 焚き火台 Sサイズ',
            ),
            {'status': 'unverified', 'reason': 'merchant_variant_evidence_conflicting'},
        )

    def test_model_substring_is_failed(self):
        product = {'name': 'SOTO レギュレーターストーブ', 'brand': 'SOTO', 'categoryId': 'burner'}

        self.assertEqual(
            inspect_merchant_identity(product, 'ST-310', 'SOTO ST-3100 レギュレーターストーブ'),
            {'status': 'failed', 'reason': 'merchant_model_mismatch'},
        )

    def test_named_alphabetic_model_absence_is_unverified(self):
        product = {'name': 'TokyoCamp 焚火台 HAKOSUKA', 'brand': 'TokyoCamp', 'categoryId': 'firepit'}

        self.assertEqual(
            inspect_merchant_identity(product, 'HAKOSUKA', 'Tokyo Camp 焚き火台 コンパクト'),
            {'status': 'unverified', 'reason': 'merchant_model_evidence_missing'},
        )

    def test_missing_product_type_is_unverified(self):
        product = {'name': 'SOTO アミカス', 'brand': 'SOTO'}

        self.assertEqual(
            inspect_merchant_identity(product, 'SOD-320', 'SOTO アミカス SOD-320'),
            {'status': 'unverified', 'reason': 'product_type_missing'},
        )

    def test_tent_family_without_type_word_requires_full_body_name(self):
        product = {
            'name': 'スノーピーク ランドロック',
            'brand': 'スノーピーク',
            'categoryId': 'tent',
        }

        self.assertEqual(
            inspect_merchant_identity(product, 'TP-671R', 'Snow Peak ランドロック TP-671R'),
            {'status': 'passed', 'reason': 'merchant_identity_confirmed'},
        )
        self.assertEqual(
            inspect_merchant_identity(product, 'TP-671R', 'Snow Peak TP-671R キャンプ用品'),
            {'status': 'unverified', 'reason': 'merchant_product_type_evidence_missing'},
        )

    def test_tent_known_name_does_not_admit_accessory_only_listing(self):
        product = {
            'name': 'スノーピーク ランドロック',
            'brand': 'スノーピーク',
            'categoryId': 'tent',
        }

        self.assertEqual(
            inspect_merchant_identity(
                product,
                'TP-671R',
                'Snow Peak ランドロック TP-671R インナーマット',
            ),
            {'status': 'failed', 'reason': 'merchant_accessory_only'},
        )


class ApparelMerchantIdentityTests(unittest.TestCase):
    CASES = (
        ('1101493', 'down', 'プラズマ1000 ダウンジャケット', 'プラズマ1000 ダウンジャケット', 'Down Jacket'),
        ('1107704', 'base-layer', 'ジオライン M.W. ラウンドネックシャツ', 'ジオライン M.W. ラウンドネックシャツ', 'Base Layer'),
        ('1114881', 'fleece', 'シャミース ジャケット', 'シャミース ジャケット', 'Fleece Jacket'),
    )

    def product(self, model, kind, name):
        return {'name': name, 'brand': 'モンベル', 'categoryId': 'wear',
                'specs': {'model': model, 'apparelClass': kind}}

    def test_real_wardrobe_classes_and_japanese_english_title_evidence(self):
        for model, kind, name, japanese, english in self.CASES:
            p = self.product(model, kind, name)
            for title in ('モンベル ' + model + ' ' + japanese, 'mont-bell ' + model + ' ' + english):
                with self.subTest(model=model, title=title):
                    self.assertEqual({'status': 'passed', 'reason': 'merchant_identity_confirmed'},
                                     inspect_merchant_identity(p, model, title))

    def test_explicit_categories_or_specific_names_work_without_broad_clothing_match(self):
        for category, name, title in (('down-jacket', 'Plasma', 'Down Jacket'),
                                      ('fleece', 'Chameece', 'Fleece Jacket'),
                                      ('base-layer', 'Zeoline', 'Base Layer')):
            p = {'brand': 'モンベル', 'name': name, 'categoryId': category}
            self.assertEqual('passed', inspect_merchant_identity(p, '1234567', 'Montbell 1234567 ' + title)['status'])
        p = {'brand': 'モンベル', 'name': '軽量ダウンジャケット'}
        self.assertEqual('passed', inspect_merchant_identity(p, '1234567', 'Montbell 1234567 Down Jacket')['status'])

    def test_unknown_or_conflicting_wear_remains_unverified(self):
        for p in ({'brand': 'モンベル', 'name': 'ダウンジャケット', 'categoryId': 'wear'},
                  {'brand': 'モンベル', 'name': '服', 'categoryId': 'wear', 'specs': {'apparelClass': 'unknown'}},
                  {'brand': 'モンベル', 'name': '服', 'categoryId': 'outerwear'},
                  {'brand': 'モンベル', 'name': '服', 'categoryId': 'fleece', 'specs': {'apparelClass': 'down'}}):
            self.assertEqual({'status': 'unverified', 'reason': 'product_type_missing'},
                inspect_merchant_identity(p, '1234567', 'Montbell 1234567 Down Jacket'))

    def test_wrong_kind_and_mixed_type_titles_never_pass(self):
        for model, kind, name, japanese, _ in self.CASES:
            p = self.product(model, kind, name)
            for other_model, other_kind, _, other_title, _ in self.CASES:
                if other_kind == kind:
                    continue
                for title in ('モンベル ' + model + ' ' + other_title,
                              'モンベル ' + model + ' ' + japanese + ' ' + other_title):
                    with self.subTest(model=model, title=title):
                        self.assertNotEqual('passed', inspect_merchant_identity(p, model, title)['status'])
            self.assertNotEqual('passed', inspect_merchant_identity(p, model, 'モンベル ' + model + ' ウェア 服 ジャケット')['status'])

    def test_wrong_model_brand_and_accessory_guards_remain_active(self):
        for model, kind, name, japanese, _ in self.CASES:
            p = self.product(model, kind, name)
            for title, reason in (
                ('モンベル ' + str(int(model) + 1) + ' ' + japanese, 'merchant_model_mismatch'),
                ('SOTO ' + model + ' ' + japanese, 'merchant_brand_mismatch'),
                ('モンベル ' + model + ' ' + japanese + ' 専用収納ケース', 'merchant_accessory_only'),
                ('モンベル ' + model + ' ' + japanese + ' 本体なし', 'merchant_accessory_only')):
                with self.subTest(title=title):
                    self.assertEqual({'status': 'failed', 'reason': reason}, inspect_merchant_identity(p, model, title))


if __name__ == '__main__':
    unittest.main()
