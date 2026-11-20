"""Narrow, offline regressions for observed unsupported Mont-bell wear claims."""
import copy
import unittest

from quality import inspect_bundle, montbell_wear_claim_issues
from test_quality import bundle


def product(model='1107704'):
    kind = 'base-layer' if model == '1107704' else 'fleece'
    return {'id': 'selected-wear', 'brand': 'mont-bell', 'categoryId': kind,
            'specs': {'model': model, 'apparelClass': kind, 'weight': '159g'}}


BAD = {
    'average_origin': ('159g。これはサイズによる個体差を均した平均値です。',
                       '平均重量159gはサイズ差をならした値です。'),
    'weight_inference': ('159gが中間の厚みを示します。',
                         '159gが端境期に効いてくる重さです。',
                         '159gなので暖かく着られます。',
                         '159gという重さから対応気温が分かります。'),
    'all_combinations': ('理屈の上では4色×4サイズの組み合わせが存在します。',
                         '全16通りから選べます。', '全色・全サイズが揃っています。'),
    'purchase_guarantee': ('これだけ守れば失敗しません。', '購入で絶対に失敗しません。'),
    'internal_option_token': ('販売先はselectableです。', 'optionStateはfixedです。'),
}


class MontbellWearClaimTests(unittest.TestCase):
    def test_observed_claims_are_rejected_in_body_and_faq_for_both_models(self):
        for model in ('1107704', '1114881'):
            for code, samples in BAD.items():
                for text in samples:
                    for field in ('content', 'faq'):
                        article = {'content': text if field == 'content' else '公式仕様を確認します。',
                                   'faqs': [{'answer': text if field == 'faq' else '公式仕様を確認します。'}]}
                        with self.subTest(model=model, text=text, field=field):
                            issues = montbell_wear_claim_issues(article, [product(model)])
                            self.assertTrue(any(code in issue for issue in issues), issues)
                            self.assertTrue(any(('content' if field == 'content' else 'faqs[0].answer') in issue
                                                for issue in issues), issues)

    def test_source_facts_and_explicit_denials_are_allowed(self):
        safe = (
            'メーカー公表の平均重量は159gです。平均値の算出方法は確認できません。',
            '平均重量159g。薄手の素材を採用し、メーカーは保温性と通気性を説明しています。',
            '平均重量159gで、素材は薄手のポリエステルです。',
            '重量159gから厚みや保温力は判断できません。',
            '159gが中間の厚みを示すとは言えません。',
            '159gだから暖かいとは断定できません。',
            '159gなので暖かいということではありません。',
            '159gは中間着の重量です。',
            '159gから生地の厚みや対応気温を計算することもできません。',
            'サイズ差を均した平均値という説明は公式にありません。',
            '「サイズ差を均した平均値」とは確認できません。',
            'サイズ差を均した値ではありません。',
            '4色、4サイズを展開しています。全色が全サイズで購入できるとは限りません。',
            '公式にある4色・4サイズの展開すべてを、この2リンクで選べるわけではありません。',
            '公式に4色と4サイズの記載があっても、その組み合わせすべてを今注文できると推定はしません。',
            '公式の4色・4サイズすべてを紹介します。',
            '4色×4サイズの組み合わせが存在するとは限りません。',
            '全16通りから選べるという説明は確認できません。',
            '4色×4サイズの組み合わせが存在することを保証していません。',
            '「これだけ守れば失敗しません」とは言えません。',
            '購入の失敗を防げると保証するものではありません。',
            '袖口の縫い目を斜めにし、伸縮性を妨げない構造とメーカーは説明しています。',
        )
        for text in safe:
            with self.subTest(text=text):
                self.assertEqual([], montbell_wear_claim_issues({'content': text}, [product()]))

    def test_scope_requires_selected_known_montbell_wear_not_model_text(self):
        text = '1107704：これだけ守れば失敗しません。'
        for products in ([], [product('1101493')], [dict(product(), brand='other')],
                         [dict(product(), categoryId='stove', specs={'model': '1107704'})]):
            self.assertEqual([], montbell_wear_claim_issues({'content': text}, products))
        self.assertEqual([], montbell_wear_claim_issues(
            {'productIds': ['other'], 'content': text}, [product()]))

    def test_reference_brief_question_and_metadata_are_not_scanned(self):
        data = bundle()
        data['products'][0].update(product(), id='tent-a')
        data['references'][0]['text'] = '159gなので暖かく着られます。'
        data['brief']['facts'] = ['selectable']
        data['article']['faqs'][0]['question'] = 'これだけ守れば失敗しませんか？'
        data['article']['excerpt'] = 'selectable'
        self.assertFalse(any('montbell_wear_claim' in failure for failure in inspect_bundle(data)['failures']))

    def test_inspect_bundle_uses_same_issues_and_never_rewrites_inputs(self):
        for field in ('content', 'faq'):
            data = bundle()
            data['products'][0].update(product(), id='tent-a')
            if field == 'content':
                data['article']['content'] += '\n159gなので暖かく着られます。'
            else:
                data['article']['faqs'][1]['answer'] = 'これだけ守れば失敗しません。'
            before = copy.deepcopy(data)
            expected = montbell_wear_claim_issues(data['article'], data['products'])
            result = inspect_bundle(data)
            self.assertTrue(expected)
            self.assertTrue(all(issue in result['failures'] for issue in expected))
            self.assertFalse(result['passed'])
            self.assertEqual(before, data)

    def test_separate_negative_sentence_does_not_hide_an_asserted_claim(self):
        text = '159gなので暖かく着られます。在庫の保証はありません。'
        self.assertTrue(montbell_wear_claim_issues({'content': text}, [product()]))

    def test_early_writer_gate_rejects_before_paid_length_repair_and_keeps_first_receipt(self):
        import test_models as fixture
        from models import Models, ModelError
        for model in ('1107704', '1114881'):
            for field in ('content', 'faq'):
                candidate, context = fixture.bundle(), fixture.context()
                context['catalog'][0].update(product(model), id='tent-a')
                # Deliberately short: without this early rejection draft() would
                # make its additional, paid length-repair transport call.
                candidate['article']['content'] = '広告\n## Choice\n{{product:tent-a}}\n[設営](/articles/setup) [撤収](/articles/pack)'
                if field == 'content':
                    candidate['article']['content'] += '\n159gなので暖かく着られます。'
                else:
                    candidate['article']['faqs'] = copy.deepcopy(candidate['article']['faqs'])
                    candidate['article']['faqs'][0] = {'question': '選び方は？', 'answer': 'これだけ守れば失敗しません。'}
                transport = fixture.Fake(fixture.writer_response(candidate), fixture.writer_response(fixture.bundle()))
                artifacts, budget = [], fixture.Budget()
                models = Models(fixture.ENV, transport, budget=budget, artifact_sink=artifacts.append)
                with self.subTest(model=model, field=field), self.assertRaisesRegex(ModelError, 'Unsupported Mont-bell apparel claim'):
                    models.draft({'productIds': ['tent-a']}, context)
                self.assertEqual(1, len(transport.calls))
                self.assertEqual(1, len(budget.holds))
                self.assertEqual(1, len(budget.settlements))
                self.assertEqual(1, len(artifacts))
                self.assertEqual(1, len(models.usage))

    def test_early_writer_accepts_explicit_denials_with_one_transport(self):
        import test_models as fixture
        from models import Models
        candidate, context = fixture.bundle(), fixture.context()
        context['catalog'][0].update(product(), id='tent-a')
        candidate['article']['content'] += '\n159gから生地の厚みや対応気温を計算することもできません。'
        candidate['article']['faqs'] = [{'question': '選択条件は？', 'answer':
            '公式にある4色・4サイズの展開すべてを、この2リンクで選べるわけではありません。'} for _ in range(3)]
        transport = fixture.Fake(fixture.writer_response(candidate))
        result = Models(fixture.ENV, transport).draft({'productIds': ['tent-a']}, context)
        self.assertEqual(candidate['article']['content'], result['article']['content'])
        self.assertEqual(1, len(transport.calls))


if __name__ == '__main__':
    unittest.main()
