import unittest
from attention_presentation import attention_text, thread_url, REASONS, research_summary

class AttentionPresentationTests(unittest.TestCase):
    def test_known_reasons_have_action_without_raw_codes(self):
        for reason in REASONS:
            text = attention_text([{'id': 'internal-id', 'title': 'ランタン', 'error': {'reason': reason}}], {})
            self.assertIn('理由：', text)
            self.assertIn('依頼できること：', text)
            self.assertNotIn(reason, text)
            self.assertNotIn('internal-id', text)
            self.assertIn('公開の承認依頼ではありません', text)
    def test_internal_quality_failures_need_no_owner_reply(self):
        from attention_presentation import INTERNAL_REASONS
        for reason in INTERNAL_REASONS:
            text = attention_text([{'title': '記事', 'error': {'reason': reason}}], {})
            self.assertIn('本人の操作は不要', text)
            self.assertNotIn('「原因を調べて」', text)
            self.assertNotIn('具体的な原因はまだ', text)

    def test_unknown_reason_not_leaked_or_guessed(self):
        text = attention_text([{'id': 'secret-id', 'title': 'secret-id', 'error': {'reason':'private_error'}}], {})
        self.assertIn('具体的な原因はまだ確認できていません', text)
        self.assertNotIn('private_error', text)
        self.assertNotIn('secret-id', text)
    def test_entrypoint_uses_exact_configured_thread(self):
        scope = {'channel_id':'C0C7LG1TQUC','thread_ts':'1791436109.446899'}
        self.assertEqual('https://app.slack.com/archives/C0C7LG1TQUC/p1791436109446899',thread_url(scope))
        self.assertIn('相談スレッドを開く', attention_text([],scope))
        self.assertEqual('',thread_url({'channel_id':'C0|bad','thread_ts':'1791436109.446899'}))
    def test_research_details_keep_product_and_translate_issues(self):
        text = research_summary('ランタン: 仕様: 重量; 購入先未確認: rakuten・amazon; manufacturer page unavailable')
        self.assertIn('ランタン', text)
        self.assertIn('楽天・Amazon', text)
        self.assertIn('メーカー公式ページの取得', text)
        self.assertNotIn('manufacturer page unavailable', text)

    def test_two_blank_lines_between_numbered_items(self):
        text = attention_text([{'title': '一つ目', 'error': {}}, {'title': '二つ目', 'error': {}}], {})
        self.assertIn('\n\n\n2. 二つ目', text)
        self.assertNotIn('\n\n\n\n2.', text)

    def test_only_social_result_is_not_reported_as_article_stop(self):
        social = {'title': '公開済原稿', 'error': {'reason': 'buffer_publication_requires_reconciliation'}}
        text = attention_text([social], {})
        self.assertIn('【X投稿の確認】', text)
        self.assertNotIn('記事制作が止まっています', text)
        self.assertIn('記事は公開済み', text)
        self.assertIn('本人の操作は不要', text)

    def test_social_and_article_failures_have_separate_sections(self):
        social = {'title': '公開済原稿', 'error': {'reason': 'buffer_publication_requires_reconciliation'}}
        article = {'title': '未公開原稿', 'error': {'reason': 'weekly_research_requires_reconciliation'}}
        text = attention_text([social, article], {})
        self.assertLess(text.index('未公開原稿'), text.index('【X投稿の確認】'))
        self.assertLess(text.index('【X投稿の確認】'), text.index('公開済原稿', text.index('【X投稿の確認】')))
        self.assertNotIn('具体的な原因はまだ', text)

    def test_no_active_title_markup(self):
        text=attention_text([{'title':'<!channel>\nhello','error':{}}],{})
        self.assertNotIn('<!channel>',text)

if __name__ == '__main__':
    unittest.main()
