import json
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

    def test_unicode_chunks_respect_slack_units_without_splitting_characters(self):
        text = '🏕️あいう' * 1800
        values = chunks(text)
        self.assertEqual(text, ''.join(values))
        self.assertTrue(all(len(x.encode('utf-16-le')) // 2 <= 2600 for x in values))

    def test_secrets_are_rejected_before_transport(self):
        with self.assertRaises(ValueError):
            Slack(self.config, call=self.call).post('token xoxb-do-not-send')
        self.assertIsNone(self.sent)

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
