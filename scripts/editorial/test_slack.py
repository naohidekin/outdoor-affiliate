import copy
import html
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from slack import Slack, chunks


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
        for mode in ('text', 'double', 'value', 'url', 'mrkdwn'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                expected = copy.deepcopy(blocks)
                if mode == 'mrkdwn':
                    expected[0]['text']['type'] = 'mrkdwn'
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
                        elif mode in ('double', 'mrkdwn'):
                            encoded = html.escape(text, quote=False)
                            message['blocks'][0]['text']['text'] = html.escape(encoded, quote=False) if mode == 'double' else encoded
                        else:
                            button = message['blocks'][1]['elements'][0]
                            button[mode] = html.escape(button[mode], quote=False)
                    return result
                with self.assertRaisesRegex(ValueError, '^slack_blocks_mismatch$'):
                    Slack(dict(self.config, stateRoot=root), call=call).post(text, expected)
                self.assertEqual(len(posts), 1)
                receipt = Path(root) / 'slack-outbound/1793000000.123456.json'
                self.assertEqual(json.loads(receipt.read_text())['status'], 'sent_unverified')

    def test_unicode_chunks_respect_slack_units_without_splitting_characters(self):
        text = '🏕️あいう' * 1800
        values = chunks(text)
        self.assertEqual(text, ''.join(values))
        self.assertTrue(all(len(x.encode('utf-16-le')) // 2 <= 2600 for x in values))

    def test_secrets_are_rejected_before_transport(self):
        with self.assertRaises(ValueError):
            Slack(self.config, call=self.call).post('token xoxb-do-not-send')
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
