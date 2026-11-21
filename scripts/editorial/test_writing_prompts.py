"""Offline prompt contracts; these tests do not measure model writing quality."""
from pathlib import Path
import unittest

from writing_prompts import (
    DRAFT_SPECIFICITY_PROMPT,
    FACTUAL_SPECIFICITY_PROMPT,
    POLISH_STYLE_PROMPT,
    get_draft_specificity_prompt,
    get_polish_style_prompt,
)


ROOT = Path(__file__).resolve().parents[2]


class WritingPromptTests(unittest.TestCase):
    def test_getters_return_stable_nonempty_stage_specific_instructions(self):
        self.assertEqual(DRAFT_SPECIFICITY_PROMPT + "\n" + FACTUAL_SPECIFICITY_PROMPT, get_draft_specificity_prompt())
        self.assertEqual(POLISH_STYLE_PROMPT, get_polish_style_prompt())
        self.assertNotEqual(get_draft_specificity_prompt(), get_polish_style_prompt())
        for getter in (get_draft_specificity_prompt, get_polish_style_prompt):
            self.assertIsInstance(getter(), str)
            self.assertTrue(getter().strip())
            self.assertEqual(getter(), getter())

    def test_draft_requires_source_bound_distinct_decisions_in_existing_brief(self):
        prompt = get_draft_specificity_prompt()
        for term in ('Opus', 'H2', '読者の場面', '出典ID', '対象', '表示・入力', '条件',
                     '具体行動', '判断の違い', '例外・未確認', 'brief.headings', 'brief.facts',
                     '独自論点', '同じ型', '仮想'):
            self.assertIn(term, prompt)
        for constraint in ('数値根拠が必要', '数字や体験を強要しない', '反復', '免責',
                           '安全保証', '逆命題', 'protected', '文体NG', '不足'):
            self.assertIn(constraint, prompt)

    def test_factual_specificity_preserves_conditions_fields_and_reader_links(self):
        prompt = get_draft_specificity_prompt()
        for term in ('「表示がない」と「表示が読めない」は別', '明記した項目だけ',
                     '本体JAN', '全製品での見やすさ', '型番の数字から容量・数量・寸法を推定せず',
                     '該当公式URLの完全一致リンクを本文にも', 'brief.linksやreferences',
                     '未提供URLの生成はしない'):
            self.assertIn(term, prompt)
        self.assertNotIn(FACTUAL_SPECIFICITY_PROMPT, get_polish_style_prompt())

    def test_polish_cannot_take_over_editorial_decisions_or_change_sources(self):
        prompt = get_polish_style_prompt()
        for term in ('Gemini', '上位確定仕様', '意味を変えない', '構成・結論',
                     '情報・例・条件', 'URL・CTA', '禁止', 'protected', '公式引用',
                     '文体NG', '重複', 'eligible', '{edits:[{index,text}]}'):
            self.assertIn(term, prompt)

    def test_no_unsupported_hold_output_or_new_writer_schema(self):
        draft = get_draft_specificity_prompt()
        self.assertIn('{article,brief}', draft)
        self.assertIn('返却キーを増やさない', draft)
        for prompt in (draft, get_polish_style_prompt()):
            self.assertNotIn('source_hold', prompt)
            self.assertNotIn('"status"', prompt)
        self.assertIn('字数・品質閾値・予算・承認', draft)

    def test_documentation_contains_exact_runtime_prompt_text(self):
        document = (ROOT / 'docs/editorial-writing-specificity.md').read_text()
        for prompt in (DRAFT_SPECIFICITY_PROMPT, POLISH_STYLE_PROMPT):
            self.assertIn('```text\n' + prompt + '\n```', document)

    def test_documentation_distinguishes_examples_and_hold_design_from_execution(self):
        document = (ROOT / 'docs/editorial-writing-specificity.md').read_text()
        for term in ('仮想ケース', 'API実測ではない', '137字', 'source_hold',
                     '文字数・資料数', 'preflightは未実装', 'SKILL.md', '逆命題'):
            self.assertIn(term, document)

    def test_instructions_reach_existing_provider_calls_without_extra_call(self):
        from models import Models
        from test_models import ENV, Fake, bundle, context, response, writer_response
        draft = Fake(writer_response(bundle()))
        Models(ENV, draft).draft({'slug': 'new', 'title': 'Guide'}, context())
        self.assertEqual(1, len(draft.calls))
        self.assertIn(get_draft_specificity_prompt(), draft.calls[0][2]['messages'][0]['content'])
        polish = Fake(response({'edits': []}, gemini=True))
        value = bundle()
        Models(ENV, polish).polish(value['article']['content'], value['brief'])
        self.assertEqual(1, len(polish.calls))
        self.assertIn(get_polish_style_prompt(), polish.calls[0][2]['messages'][0]['content'])


if __name__ == '__main__':
    unittest.main()
