"""Length expansion must never paraphrase or delete the original source."""
import copy
import unittest

import models
from models import Models, ModelError
from quality import inspect_polish
from test_models import ENV, Fake, bundle, context, response, writer_response


class LengthInsertionRepairTests(unittest.TestCase):
    def test_unknown_outcome_keeps_classification_flag(self):
        self.assertIs(getattr(models.ModelOutcomeUnknown('x'), 'outcome_unknown'), True)

    def apply(self, source, insertions):
        self.assertTrue(callable(getattr(models, 'apply_length_insertions', None)),
                        'deterministic insertion application is missing')
        return models.apply_length_insertions(source, {'insertions': insertions})

    def test_original_numeric_phrases_are_immutable(self):
        source = 'この2つは素材の考え方が根本的に違います。\n\nその1パターンを買う形です。'
        result = self.apply(source, [{'after': 'その1パターンを買う形です。',
                                     'text': '\n\n記載された選択肢を照らし合わせて考えます。'}])
        self.assertTrue(result.startswith(source))
        self.assertTrue(inspect_polish(source, result)['passed'])

    def test_missing_repeated_midword_and_duplicate_anchors_are_rejected(self):
        for source, changes in [
            ('同じ文。\n\n同じ文。', [{'after': '同じ文。', 'text': '補足'}]),
            ('文章の途中です。', [{'after': '文章', 'text': '補足'}]),
            ('本文。', [{'after': '不在', 'text': '補足'}]),
            ('本文。', [{'after': '本文。', 'text': '補足'}, {'after': '本文。', 'text': '追加'}])]:
            with self.subTest(source=source), self.assertRaises(ModelError):
                self.apply(source, changes)

    def test_protected_additions_and_token_boundary_changes_are_rejected(self):
        for text in ('追加は2つ。', '一方では。', '\n## 見出し', '\nhttps://bad.example',
                     '\n{{product:other}}', '\n| 新しい表 |', '\n広告'):
            with self.subTest(text=text), self.assertRaises(ModelError):
                self.apply('本文。', [{'after': '本文。', 'text': text}])
        with self.assertRaises(ModelError):
            self.apply('数量2', [{'after': '数量2', 'text': 'kg'}])

    def test_underlength_requests_one_insertion_response_and_preserves_paid_source(self):
        first = bundle()
        first['article']['content'] = first['article']['content'][:2200]
        text = '\n\n' + '根拠に書かれた条件を照らし合わせて選びます。' * 55
        patch = {'insertions': [{'after': first['article']['content'], 'text': text}]}
        fake = Fake(writer_response(first), response(patch))
        model = Models(ENV, fake)
        result = model.draft({}, context())
        self.assertEqual(first['article']['content'] + text, result['article']['content'])
        self.assertEqual(first['brief'], result['brief'])
        self.assertEqual(2, len(fake.calls))
        self.assertEqual(models.LENGTH_INSERTION_SCHEMA,
                         fake.calls[1][2]['output_config']['format']['schema'])
        self.assertTrue(inspect_polish(first['article']['content'], result['article']['content'])['passed'])

    def test_failed_insertions_never_trigger_a_third_model_call(self):
        first = bundle()
        first['article']['content'] = first['article']['content'][:2200]
        fake = Fake(writer_response(first), response({'insertions': [{'after': 'missing', 'text': '補足'}]}),
                    writer_response(bundle()))
        with self.assertRaises(ModelError):
            Models(ENV, fake).draft({}, context())
        self.assertEqual(2, len(fake.calls))

    def test_legacy_full_response_cannot_paraphrase_non_numeric_source_either(self):
        first = bundle()
        first['article']['content'] = first['article']['content'][:2200]
        other = bundle()
        other['article']['content'] = other['article']['content'].replace('検証済みの説明です。', '根拠を確かめる説明です。', 1)
        fake = Fake(writer_response(first), writer_response(other))
        with self.assertRaises(ModelError):
            Models(ENV, fake).draft({}, context())
