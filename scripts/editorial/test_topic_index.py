import json
import unittest
from topic_index import build_article_index, compact_article_summaries


class ArticleIndexTests(unittest.TestCase):
    def test_late_section_faq_and_conclusion_remain_available_locally(self):
        article = {'id': 'a', 'slug': 'winter', 'title': '冬の服装',
                   'content': '\n\n'.join('## 項目' + str(n) + '\n本文' for n in range(12))
                   + '\n\n## まとめ\n用途に合わせます。',
                   'faqs': [{'question': 'アクティブフリースと厚手の違いは？', 'answer': '局所の比較。'}]}
        row = build_article_index([article])[0]
        self.assertIn('項目11', row['headings'])
        self.assertIn('項目11', [section['heading'] for section in row['sections']])
        self.assertEqual('用途に合わせます。', row['conclusion'])
        self.assertEqual(['アクティブフリースと厚手の違いは？'], row['faqQuestions'])

    def test_model_projection_omits_full_body_faq_and_late_headings(self):
        row = build_article_index([{'id': 'a', 'title': '公開題', 'content': '## 先頭\nBODY_CANARY',
                                    'faqs': [{'question': 'FAQ_CANARY', 'answer': 'ANSWER_CANARY'}]}])
        projected = compact_article_summaries(row)
        encoded = json.dumps(projected)
        for value in ('BODY_CANARY', 'FAQ_CANARY', 'ANSWER_CANARY', 'sections', 'conclusion'):
            self.assertNotIn(value, encoded)
        self.assertEqual(['先頭'], projected[0]['headings'])

    def test_duplicate_or_overflow_cannot_claim_complete_coverage(self):
        with self.assertRaisesRegex(ValueError, 'identity_duplicate'):
            build_article_index([{'id': 'a'}, {'id': 'a'}])
        with self.assertRaisesRegex(ValueError, 'content_overflow'):
            build_article_index([{'id': 'a', 'content': 'x' * 200001}])
        self.assertEqual('summary_only', build_article_index([{'id': 'a'}])[0]['bodyCoverage'])

    def test_fenced_heading_is_not_an_article_section(self):
        row = build_article_index([{'id': 'a', 'content': '```md\n## 偽見出し\n```\n\n## 実見出し\n本文'}])[0]
        self.assertEqual(['実見出し'], row['headings'])


if __name__ == '__main__':
    unittest.main()
