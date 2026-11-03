import copy
import html
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from slack import Slack, chunks, mrkdwn_chunks
from presentation import article_body


class SlackTests(unittest.TestCase):
    def setUp(self):
        self.config = {'slack': {'team_id': 'T', 'bot_user_id': 'B', 'channel_id': 'C', 'thread_ts': '1793000000.000001'}}
        self.sent = None

    def call(self, method, data):
        if method == 'chat.postMessage':
            self.sent = data
            return {'ok': True, 'channel': 'C', 'ts': '1793000000.123456'}
        return {'ok': True, 'messages': [{'ts': '1793000000.123456', 'thread_ts': self.config['slack']['thread_ts'],
                                        'text': self.sent['text'].replace('\n', ' '), 'blocks': self.sent.get('blocks')}]}

    def test_verified_delivery_checks_visible_text_and_buttons(self):
        s = Slack(self.config, call=self.call)
        text = '本文\n二行目'
        blocks = [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}}]
        self.assertTrue(s.post(text, blocks)['verified'])
        self.assertFalse(self.sent['unfurl_links'])
        self.assertEqual('none', self.sent['parse'])

    def test_readback_missing_or_changed_is_not_delivered(self):
        for observed in ([], [{'ts': '1793000000.123456', 'thread_ts': self.config['slack']['thread_ts'], 'text': '別の本文'}]):
            def call(method, data):
                return self.call(method, data) if method == 'chat.postMessage' else {'messages': observed}
            with self.assertRaises(ValueError):
                Slack(self.config, call=call).post('本文')

    def test_image_server_metadata_only_is_ignored(self):
        blocks = [{'type': 'image', 'image_url': 'https://example.com/image.jpg', 'alt_text': '画像 & 説明'}]
        metadata = {'image_bytes': 303678, 'image_height': 3088, 'fallback': 'server fallback',
                    'is_animated': False, 'image_width': 2056, 'block_id': 'server-id'}
        for mode in ('metadata', 'image_url', 'alt_text', 'type', 'unknown'):
            with self.subTest(mode=mode):
                def call(method, data):
                    result = self.call(method, data)
                    if method == 'conversations.replies':
                        image = copy.deepcopy(blocks[0])
                        image.update(metadata)
                        if mode in ('image_url', 'alt_text', 'type'):
                            image[mode] = {'image_url': 'https://example.com/changed.jpg',
                                           'alt_text': '変更された説明', 'type': 'section'}[mode]
                        if mode == 'unknown':
                            image['unexpected'] = True
                        result['messages'][0]['blocks'] = [image]
                    return result
                slack = Slack(self.config, call=call)
                if mode == 'metadata':
                    self.assertTrue(slack.post('画像', blocks)['verified'])
                else:
                    with self.assertRaisesRegex(ValueError, '^slack_blocks_mismatch$'):
                        slack.post('画像', blocks)

    def test_image_metadata_names_are_not_ignored_on_other_objects(self):
        blocks = [{'type': 'actions', 'elements': [{'type': 'button',
                   'text': {'type': 'plain_text', 'text': '承認'}, 'action_id': 'approve',
                   'value': '{"nonce":"exact"}'}]}]
        def call(method, data):
            result = self.call(method, data)
            if method == 'conversations.replies':
                result['messages'][0]['blocks'] = copy.deepcopy(blocks)
                result['messages'][0]['blocks'][0]['elements'][0]['fallback'] = 'unexpected'
            return result
        with self.assertRaisesRegex(ValueError, '^slack_blocks_mismatch$'):
            Slack(self.config, call=call).post('承認', blocks)

    def test_plain_text_block_entities_decode_once_without_changing_expected(self):
        text = 'HOME&CAMP\n> 引用 &lt;literal&gt;'
        blocks = [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}},
                  {'type': 'actions', 'elements': [{'type': 'button',
                   'text': {'type': 'plain_text', 'text': '承認 & 確認'},
                   'action_id': 'approve', 'value': '{"nonce":"a&b"}',
                   'url': 'https://example.com/?a=1&b=2'}]}]
        original = copy.deepcopy(blocks)
        posts = []
        def call(method, data):
            result = self.call(method, data)
            if method == 'chat.postMessage':
                posts.append(data)
            else:
                message = result['messages'][0]
                message['text'] = html.escape(text, quote=False)
                message['blocks'] = copy.deepcopy(blocks)
                message['blocks'][0]['block_id'] = 'server-generated'
                message['blocks'][0]['text'].update(text=html.escape(text, quote=False), emoji=True)
                message['blocks'][1]['elements'][0]['text']['text'] = '承認 &amp; 確認'
            return result
        self.assertTrue(Slack(self.config, call=call).post(text, blocks)['verified'])
        self.assertEqual(blocks, original)
        self.assertEqual(len(posts), 1)

    def test_block_normalization_rejects_changed_text_values_urls_and_mrkdwn(self):
        text = 'HOME&CAMP > 引用'
        blocks = [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}},
                  {'type': 'actions', 'elements': [{'type': 'button',
                   'text': {'type': 'plain_text', 'text': '承認 & 確認'},
                   'action_id': 'approve', 'value': '{"nonce":"a&b"}',
                   'url': 'https://example.com/?a=1&b=2'}]}]
        for mode in ('text', 'double', 'value', 'url'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                expected = copy.deepcopy(blocks)
                posts = []
                def call(method, data):
                    result = self.call(method, data)
                    if method == 'chat.postMessage':
                        posts.append(data)
                    else:
                        message = result['messages'][0]
                        message['blocks'] = copy.deepcopy(expected)
                        if mode == 'text':
                            message['blocks'][0]['text']['text'] = '変更された本文'
                        elif mode == 'double':
                            encoded = html.escape(text, quote=False)
                            message['blocks'][0]['text']['text'] = html.escape(encoded, quote=False)
                        else:
                            button = message['blocks'][1]['elements'][0]
                            button[mode] = html.escape(button[mode], quote=False)
                    return result
                with self.assertRaisesRegex(ValueError, '^slack_blocks_mismatch$'):
                    Slack(dict(self.config, stateRoot=root), call=call).post(text, expected)
                self.assertEqual(len(posts), 1)
                receipt = Path(root) / 'slack-outbound/1793000000.123456.json'
                self.assertEqual(json.loads(receipt.read_text())['status'], 'sent_unverified')

    def test_mrkdwn_readback_decodes_one_server_encoding_only(self):
        rendered = '*選び方*\n<https://example.com/?a=1&amp;b=2|公式 &amp; 詳細>'
        blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': rendered, 'verbatim': True}}]
        for mode in ('retained', 'amp_encoded', 'decoded_amp', 'encoded_angles', 'changed_url', 'changed_label'):
            with self.subTest(mode=mode):
                def call(method, data):
                    result = self.call(method, data)
                    if method == 'conversations.replies':
                        result['messages'][0]['blocks'] = copy.deepcopy(blocks)
                        observed = {'retained': rendered, 'amp_encoded': rendered.replace('&amp;', '&amp;amp;'),
                                    'decoded_amp': rendered.replace('&amp;', '&'),
                                    'encoded_angles': html.escape(rendered, quote=False),
                                    'changed_url': rendered.replace('b=2', 'b=3'),
                                    'changed_label': rendered.replace('公式', '改変'),
                                    }[mode]
                        result['messages'][0]['blocks'][0]['text']['text'] = observed
                    return result
                slack = Slack(self.config, call=call)
                if mode in ('encoded_angles', 'changed_url', 'changed_label'):
                    with self.assertRaisesRegex(ValueError, '^slack_blocks_mismatch$'):
                        slack.post('記事本文', blocks)
                else:
                    self.assertTrue(slack.post('記事本文', blocks)['verified'])

    def test_escaped_literal_cannot_become_active_slack_token(self):
        text = '引用：&lt;!channel&gt; と &lt;https://example.com|リンク&gt;'
        blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': text, 'verbatim': True}}]
        for replacement in ('<!channel>', '<https://example.com|リンク>'):
            with self.subTest(replacement=replacement):
                def call(method, data):
                    result = self.call(method, data)
                    if method == 'conversations.replies':
                        result['messages'][0]['blocks'] = copy.deepcopy(blocks)
                        result['messages'][0]['blocks'][0]['text']['text'] = text.replace(
                            '&lt;!channel&gt;' if replacement.startswith('<!') else '&lt;https://example.com|リンク&gt;', replacement)
                    return result
                with self.assertRaisesRegex(ValueError, '^slack_blocks_mismatch$'):
                    Slack(self.config, call=call).post('記事本文', blocks)
        active = '<https://example.com/?a=1&amp;b=2|購入先>'
        block = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': active, 'verbatim': True}}]
        def encoded_call(method, data):
            result = self.call(method, data)
            if method == 'conversations.replies':
                result['messages'][0]['blocks'] = copy.deepcopy(block)
                result['messages'][0]['blocks'][0]['text']['text'] = html.escape(active, quote=False)
            return result
        with self.assertRaisesRegex(ValueError, '^slack_blocks_mismatch$'):
            Slack(self.config, call=encoded_call).post('記事本文', block)

    def test_unicode_chunks_respect_slack_units_without_splitting_characters(self):
        text = '🏕️あいう' * 1800
        values = chunks(text)
        self.assertEqual(text, ''.join(values))
        self.assertTrue(all(len(x.encode('utf-16-le')) // 2 <= 2600 for x in values))

    def test_mrkdwn_chunks_keep_links_whole_and_bound_utf16(self):
        link = '<https://example.com/item?a=1&amp;b=2|購入先>'
        value = 'あ' * 2590 + '\n' + link + '\n' + '🏕️' * 1400
        parts = mrkdwn_chunks(value)
        self.assertEqual(value, ''.join(parts))
        self.assertTrue(any(link in part for part in parts))
        self.assertTrue(all(len(part.encode('utf-16-le')) // 2 <= 2600 for part in parts))

    def test_secrets_are_rejected_before_transport(self):
        with self.assertRaises(ValueError):
            Slack(self.config, call=self.call).post('token xoxb-do-not-send')
        with self.assertRaises(ValueError):
            Slack(self.config, call=self.call).post('記事本文', [{'type': 'section', 'text': {'type': 'mrkdwn',
                'text': 'token xoxb-do-not-send'}}])
        self.assertIsNone(self.sent)

    def test_slack_html_entity_encoding_is_decoded_once(self):
        def call(method, data):
            result = self.call(method, data)
            if method == 'conversations.replies':
                result['messages'][0]['text'] = 'HOME&amp;CAMP &amp;lt;literal&amp;gt;'
            return result
        self.assertTrue(Slack(self.config, call=call).post('HOME&CAMP &lt;literal&gt;')['verified'])

    def test_unknown_readback_preserves_sent_receipt_without_resending(self):
        with tempfile.TemporaryDirectory() as root:
            def call(method, data):
                if method == 'chat.postMessage':
                    return self.call(method, data)
                raise TimeoutError('readback unavailable')
            with self.assertRaises(TimeoutError):
                Slack(dict(self.config, stateRoot=root), call=call).post('HOME&CAMP')
            receipt = Path(root) / 'slack-outbound/1793000000.123456.json'
            self.assertEqual('sent_unverified', json.loads(receipt.read_text())['status'])
            self.assertEqual(0o600, receipt.stat().st_mode & 0o777)

    def test_article_presentation_shows_content_links_cards_and_faq_once(self):
        article = {'title': 'バーナー比較', 'content': '## 選び方\n- 火力と[公式](https://example.com/?a=1&b=2)\n{{comparison:p1,p2}}\n{{product:p1}}\n## FAQ\nQ. 燃料は？\nA. CB缶です。',
                   'faqs': [{'question': '燃料は？', 'answer': 'CB缶です。'}, {'question': '重量は？', 'answer': '350gです。'}]}
        products = [{'id': 'p1', 'name': '製品A', 'affiliateUrl': 'https://example.com/a'},
                    {'id': 'p2', 'name': '製品B', 'amazonUrl': 'https://example.com/b'}]
        bundle = {'article': article, 'products': products, 'images': [{'productId': 'p1', 'url': 'https://example.com/a.jpg'}]}
        body = article_body(bundle)
        self.assertIn('*選び方*', body)
        self.assertIn('<https://example.com/?a=1&amp;b=2|公式>', body)
        self.assertIn('<https://example.com/a|楽天>', body)
        self.assertIn('<https://example.com/b|Amazon>', body)
        self.assertNotIn('{{', body)
        self.assertEqual(body.count('燃料は？'), 1)
        self.assertEqual(body.count('350gです。'), 1)
        job = {'id': 'article-hidden', 'revision': 'revision-hidden', 'bundle': bundle,
               'review': {'score': 9.2}, 'theme': {'selectionReason': '内部理由'}}
        req = {'request_id': 'req', 'article_id': job['id'], 'manifest_hash': 'hash-hidden', 'nonce': 'nonce-hidden'}
        sent = []
        s = Slack(self.config, call=self.call)
        with patch.object(s, 'post', side_effect=lambda text, blocks=None: sent.append((text, blocks)) or {'message_ts': '1793000000.123456'}):
            s.deliver(job, req)
        visible = '\n'.join(text + '\n' + str(blocks[0].get('text', {}).get('text', '')) for text, blocks in sent)
        for hidden in ('article-hidden', 'revision-hidden', 'hash-hidden', '内部理由', '9.2', '{{'):
            self.assertNotIn(hidden, visible)
        self.assertEqual(sent[0][1][0]['text']['type'], 'mrkdwn')
        self.assertEqual(sent[1][1][0]['alt_text'], '画像：製品A')
        actions = sent[-1][1][1]['elements']
        self.assertEqual([a['text']['text'] for a in actions], ['公開する', '修正を依頼', '保留'])
        self.assertEqual(json.loads(actions[0]['value']), req)

    def test_product_comparison_and_ranking_preserve_page_visible_product_facts(self):
        product = {'id': 'p1', 'name': '製品A', 'brand': 'メーカーA', 'categoryId': 'burner',
                   'description': '公式寸法を確認した製品。', 'price': 2500,
                   'specs': {'weight': '900g', '重量': '850g', 'サイズ': '20×10cm', '素材': '鉄',
                             '発熱量': '3.3kW', 'unknown_api': 'hidden'},
                   'affiliateUrl': 'https://example.com/item?a=1&b=2'}
        for tag, expected, excluded in (
                ('product', ('メーカーA', '公式寸法を確認した製品。', '重量：850g', 'サイズ：20×10cm', '素材：鉄', '参考価格：¥2,500'), ('発熱量：3.3kW',)),
                ('comparison', ('メーカーA', '重量：850g', 'サイズ：20×10cm', '素材：鉄', '発熱量：3.3kW', '参考価格：¥2,500'), ('公式寸法を確認した製品。',)),
                ('ranking', ('1位', 'メーカーA', '公式寸法を確認した製品。', '参考価格：¥2,500'), ('重量：850g',))):
            with self.subTest(tag=tag):
                bundle = {'article': {'content': '{{' + tag + ':p1}}', 'faqs': []}, 'products': [product]}
                body = article_body(bundle)
                for value in expected:
                    self.assertIn(value, body)
                for value in excluded:
                    self.assertNotIn(value, body)
                self.assertNotIn('unknown_api', body)
                self.assertNotIn('900g', body)
                self.assertIn('<https://example.com/item?a=1&amp;b=2|楽天>', body)

    def test_presentation_preserves_parenthesized_links_and_resolves_other_page_tags(self):
        article = {'title': '動画', 'content': '## 詳細\n[公式](https://example.com/a_(b))\n価格 {{price:p1}}\n{{youtube:AbCdEf12345|設営動画|2026-01-01}}', 'faqs': []}
        bundle = {'article': article, 'products': [{'id': 'p1', 'name': '製品A', 'price': 1234}]}
        body = article_body(bundle)
        self.assertIn('<https://example.com/a_(b)|公式>', body)
        self.assertIn('価格 1,234円', body)
        self.assertIn('<https://www.youtube.com/watch?v=AbCdEf12345|設営動画>', body)
        self.assertNotIn('{{', body)
        article['content'] += '\n{{unknown:p1}}'
        with self.assertRaisesRegex(ValueError, 'presentation_shortcode_unhandled'):
            article_body(bundle)

    def test_presentation_table_keeps_every_header_and_cell(self):
        bundle = {'article': {'content': '## 比較\n| 項目 | A | B |\n| --- | --- | --- |\n| 重量 | 100g | 200g |\n| 燃料 | CB | OD |', 'faqs': []}, 'products': []}
        body = article_body(bundle)
        self.assertIn('• *項目*: 重量 ・ *A*: 100g ・ *B*: 200g', body)
        self.assertIn('• *項目*: 燃料 ・ *A*: CB ・ *B*: OD', body)
        self.assertNotIn('| --- |', body)

    def test_social_delivery_shows_only_proposed_images_in_order(self):
        s = Slack(self.config, call=self.call)
        images = [{'url': 'https://example.com/a.png'}, {'url': 'https://example.com/b.png'}]
        job = {'id': 'article-test', 'revision': 'revision', 'bundle': {'article': {'title': '記事'}, 'images': images},
               'social': {'proposal': {'text': '告知', 'replyText': 'URL', 'images': [images[1]]}}}
        req = {'kind': 'social', 'request_id': 'req', 'article_id': job['id'], 'manifest_hash': 'hash', 'nonce': 'nonce'}
        with patch.object(s, 'post', return_value={'message_ts': '1793000000.123456'}) as post:
            s.deliver(job, req)
        urls = [call.args[1][0]['image_url'] for call in post.call_args_list if call.args[1][0]['type'] == 'image']
        self.assertEqual(['https://example.com/b.png'], urls)
        card = post.call_args_list[-1].args[1]
        self.assertEqual(card[1]['elements'][0]['text']['text'], 'この告知案を承認')
        self.assertIn('Xへの投稿は手動', post.call_args_list[-1].args[0])
        self.assertEqual(json.loads(card[1]['elements'][0]['value'])['nonce'], 'nonce')

    def test_auto_x_card_explicit_consent_preserves_full_text_images_and_hidden_binding(self):
        s = Slack(self.config, call=self.call)
        images = [{'url': 'https://example.com/a.png'}, {'url': 'https://example.com/b.png'}]
        proposal = {'text': '広告 PR 公表仕様に基づく告知。', 'replyText': 'https://camp-gear-lab.com/articles/stove',
                    'images': images, 'deliveryMode': 'auto_x', 'targetAccountId': '123456789'}
        job = {'id': 'article-hidden', 'revision': 'article-revision-hidden',
               'bundle': {'article': {'title': '記事'}, 'images': []},
               'social': {'proposal': proposal, 'revision': 'social-revision-hidden'}}
        req = {'kind': 'social', 'request_id': 'request-hidden', 'article_id': job['id'],
               'manifest_hash': job['social']['revision'], 'nonce': 'nonce-hidden'}
        with patch.object(s, 'post', return_value={'message_ts': '1793000000.123456'}) as post:
            s.deliver(job, req)
        calls = post.call_args_list
        body = calls[0].args[1][0]['text']['text']
        self.assertIn(proposal['text'], body)
        self.assertIn(proposal['replyText'], body)
        self.assertEqual([c.args[1][0]['image_url'] for c in calls if c.args[1][0]['type'] == 'image'],
                         [image['url'] for image in images])
        card = calls[-1].args[1]
        self.assertEqual(card[1]['elements'][0]['text']['text'], 'Xに投稿する')
        explanation = card[0]['text']['text']
        self.assertIn('承認した本文・画像', explanation)
        self.assertIn('記事リンク', explanation)
        self.assertIn('自動投稿', explanation)
        self.assertNotIn('手動', explanation)
        expected = {key: req[key] for key in ('request_id', 'article_id', 'manifest_hash', 'nonce')}
        for button in card[1]['elements']:
            self.assertEqual(json.loads(button['value']), expected)
        visible = '\n'.join(c.args[0] + str(c.args[1][0]) for c in calls)
        for private in ('article-hidden', 'revision-hidden', 'request-hidden', 'nonce-hidden', '123456789', 'auto_x'):
            self.assertNotIn(private, visible)

    def test_explicit_manual_mode_retains_legacy_manual_card(self):
        job = {'id': 'article-test', 'bundle': {'article': {'title': '記事'}},
               'social': {'proposal': {'text': '広告 告知', 'replyText': 'https://example.com/article',
                                      'images': [], 'deliveryMode': 'manual'}}}
        req = {'kind': 'social', 'request_id': 'req', 'article_id': job['id'],
               'manifest_hash': 'hash', 'nonce': 'nonce'}
        with patch.object(Slack, 'post', return_value={'message_ts': '1793000000.123456'}) as post:
            Slack(self.config, call=self.call).deliver(job, req)
        card = post.call_args_list[-1].args[1]
        self.assertEqual(card[1]['elements'][0]['text']['text'], 'この告知案を承認')
        self.assertIn('Xへの投稿は手動です。', card[0]['text']['text'])
        self.assertNotIn('接続の復旧待ち', card[0]['text']['text'])

    def test_auto_x_disabled_connection_saves_intent_without_immediate_post_promise(self):
        job = {'id': 'article-test', 'bundle': {'article': {'title': '記事'}},
               'social': {'proposal': {'text': '広告 告知', 'replyText': 'https://example.com/article',
                    'images': [], 'deliveryMode': 'auto_x', 'targetAccountId': '1343879420470206464'}}}
        req = {'kind': 'social', 'request_id': 'req', 'article_id': job['id'],
               'manifest_hash': 'hash', 'nonce': 'nonce'}
        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.object(Slack, 'post', return_value={'message_ts': '1793000000.123456'}) as post:
                Slack(dict(self.config, socialPostingEnabled=enabled), call=self.call).deliver(job, req)
            card = post.call_args_list[-1].args[1]
            text = card[0]['text']['text']
            self.assertEqual(card[1]['elements'][0]['text']['text'], 'Xに投稿する')
            if not enabled:
                self.assertIn('X接続の復旧待ちです。承認した内容は保存し、接続確認後に投稿します。', text)
            else:
                self.assertNotIn('復旧待ち', text)

    def test_social_unknown_mode_or_unbound_auto_target_fails_before_any_slack_send(self):
        for changes in ({'deliveryMode': 'auto_x'}, {'deliveryMode': 'auto_x', 'targetAccountId': ''},
                        {'deliveryMode': 'auto_x', 'targetAccountId': None},
                        {'deliveryMode': 'auto_x', 'targetAccountId': 123},
                        {'deliveryMode': 'unexpected', 'targetAccountId': '123'}):
            proposal = dict(text='広告 告知', replyText='https://example.com/article', images=[], **changes)
            job = {'bundle': {'article': {'title': '記事'}}, 'social': {'proposal': proposal}}
            with self.subTest(changes=changes), patch.object(Slack, 'post') as post:
                with self.assertRaisesRegex(ValueError, 'social_delivery_mode_invalid'):
                    Slack(self.config, call=self.call).deliver(job, {'kind': 'social'})
                post.assert_not_called()

    def test_posts_are_spaced_even_after_unknown_send(self):
        s = Slack(self.config, call=self.call)
        clock = [10.0]
        starts = []
        def sleep(seconds):
            clock[0] += seconds
        def call(method, data):
            if method == 'chat.postMessage':
                starts.append(clock[0])
            return self.call(method, data)
        s._call = call
        with patch('slack.time.monotonic', side_effect=lambda: clock[0]), patch('slack.time.sleep', side_effect=sleep):
            s.post('first')
            s.post('second')
        self.assertGreaterEqual(starts[1] - starts[0], 1.1 - 1e-8)


if __name__ == '__main__':
    unittest.main()
