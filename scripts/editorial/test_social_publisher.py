"""Offline approval, exact media, and durable unknown-result tests."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ledger import Ledger, fingerprint
from runtime import Runtime
from social_publisher import SocialPublisher
from test_catalog import PNG
from x_readback import exact_x_text


URL = 'https://camp-gear-lab.com/articles/test'
IMAGE_URL = 'https://images.example.com/known.png'


def approved_job():
    image = dict(url=IMAGE_URL, finalUrl=IMAGE_URL, contentType='image/png',
                 sha256=hashlib.sha256(PNG).hexdigest(), size=len(PNG), verified=True)
    bundle = {'article': {'title': 'Approved'}, 'products': [], 'images': [image],
              'brief': {}, 'references': []}
    proposal = dict(text='新しい記事を公開しました。', replyText=URL, url=URL, images=[image],
                    platform='x', deliveryMode='auto_x', targetAccountId='123')
    revision = fingerprint(proposal)
    review = dict(passed=True, score=8.5, fingerprint=revision,
                  evidence={key: True for key in ('facts', 'images', 'affiliate', 'medical', 'render')},
                  polish={'model': 'gemini-3.8-flash', 'validated': True})
    return dict(stage='social_approved', bundle=bundle, revision=fingerprint(bundle),
                publication={'verified': True, 'revision': fingerprint(bundle), 'url': URL,
                             'readback': {'verified': True, 'fingerprint': fingerprint(bundle)}},
                social={'proposal': proposal, 'revision': revision, 'review': review,
                        'approval': {'action': 'approved', 'revision': revision,
                                     'user_id': 'owner', 'request_id': 'req'}})


class Fetcher:
    def __init__(self):
        self.body = PNG

    def request(self, url, headers):
        return {'url': url, 'headers': {'content-type': 'image/png'}, 'body': self.body}


class XFake:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.main = '111'
        self.user = '123'
        self.photo = False

    def __call__(self, action, payload):
        self.calls.append((action, payload))
        if action == self.fail:
            raise TimeoutError('secret must not appear in journal')
        if action == 'preflight':
            return {'userId': self.user}
        if action == 'upload':
            return {'mediaId': '333', 'mediaKey': '3_333', 'expiresAfterSecs': 3600}
        if action == 'maincreate':
            return {'id': self.main}
        if action == 'replycreate':
            return {'id': '222'}
        if payload['id'] == '111':
            if self.photo:
                base, token = '新しい記事を公開しました。', 'https://t.co/photo'
                start = len((base + ' ').encode('utf-16-le')) // 2
                return {'id': '111', 'authorId': '123', 'text': base + ' ' + token,
                        'urls': [{'start': start, 'end': start + len(token), 'url': token,
                                  'expanded_url': 'https://x.com/gear/status/111/photo/1',
                                  'media_key': '3_333'}], 'mediaKeys': ['3_333'], 'replyTo': None}
            return {'id': '111', 'authorId': '123', 'text': '新しい記事を公開しました。',
                    'urls': [], 'mediaKeys': ['3_333'], 'replyTo': None}
        return {'id': '222', 'authorId': '123', 'text': 'https://t.co/short',
                'urls': [{'start': 0, 'end': len('https://t.co/short'),
                          'url': 'https://t.co/short', 'expanded_url': URL}],
                'mediaKeys': [], 'replyTo': '111'}


class SocialPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'private'
        self.root.mkdir(mode=0o700)
        self.config = dict(stateRoot=str(self.root), socialPostingEnabled=True,
                           targetAccountId='123', slack={'user_id': 'owner'})
        self.x = XFake()
        self.fetcher = Fetcher()
        self.publisher = SocialPublisher(self.config, {}, client=self.x, fetcher=self.fetcher)
        self.job = approved_job()

    def tearDown(self):
        self.tmp.cleanup()

    def marker(self):
        return self.root / 'social-publications' / (self.job['social']['revision'] + '.json')

    def test_exact_approved_text_image_reply_and_readback_once(self):
        result = self.publisher.publish(self.job)
        self.assertEqual((result['status'], result['mainId'], result['replyId']), ('verified', '111', '222'))
        self.assertEqual(result['fingerprint'], self.job['social']['revision'])
        self.assertEqual(result['accountId'], '123')
        self.assertEqual(result['readback']['media']['items'][0]['sha256'], hashlib.sha256(PNG).hexdigest())
        self.assertEqual([a for a, _ in self.x.calls],
                         ['preflight', 'upload', 'maincreate', 'read', 'replycreate', 'read'])
        self.assertEqual(self.x.calls[2][1], {'text': self.job['social']['proposal']['text'], 'mediaIds': ['333']})
        self.assertEqual(self.x.calls[4][1], {'text': URL, 'parentId': '111'})
        self.assertEqual(self.marker().stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.marker().read_text())['phase'], 'verified')
        self.assertEqual(self.publisher.publish(self.job)['status'], 'verified')
        self.assertEqual([a for a, _ in self.x.calls].count('maincreate'), 1)

    def test_platform_terminal_photo_suffix_is_verified_without_changing_approved_text(self):
        self.x.photo = True
        result = self.publisher.publish(self.job)
        self.assertEqual(result['status'], 'verified')
        main = result['readback']['main']
        self.assertEqual(main['text'], '新しい記事を公開しました。 https://t.co/photo')
        self.assertEqual(self.x.calls[2][1]['text'], '新しい記事を公開しました。')
        self.assertEqual(main['mediaKeys'], ['3_333'])

    def test_photo_suffix_requires_exact_post_attachment_terminal_offsets_and_no_extra_text(self):
        expected, token = '💡説明', 'https://t.co/photo'
        start = len((expected + ' ').encode('utf-16-le')) // 2
        post = {'id': '111', 'text': expected + ' ' + token, 'mediaKeys': ['3_333'],
                'urls': [{'start': start, 'end': start + len(token), 'url': token,
                          'expanded_url': 'https://x.com/gear/status/111/photo/1',
                          'media_key': '3_333'}]}
        self.assertTrue(exact_x_text(post, expected))
        codepoint = copy.deepcopy(post)
        codepoint['urls'][0]['start'] = len(expected + ' ')
        codepoint['urls'][0]['end'] = len(codepoint['text'])
        self.assertTrue(exact_x_text(codepoint, expected))
        for change in (
            lambda p: p['urls'][0].update(expanded_url='https://x.com/gear/status/999/photo/1'),
            lambda p: p['urls'][0].update(media_key='3_other'),
            lambda p: p.update(mediaKeys=['3_other']),
            lambda p: p['urls'][0].update(start=start + 1),
            lambda p: p.update(text=expected + ' ' + token + ' 追加'),
            lambda p: p.update(text='途中 ' + token + ' ' + expected),
            lambda p: p['urls'][0].update(expanded_url='https://x.com/gear/status/111/photo/2'),
            lambda p: p['urls'][0].update(expanded_url='https://evil.example/gear/status/111/photo/1'),
            lambda p: p['urls'][0].update(url='https://evil.example/photo'),
        ):
            candidate = copy.deepcopy(post)
            change(candidate)
            with self.subTest(candidate=candidate):
                self.assertFalse(exact_x_text(candidate, expected))

    def test_photo_index_binds_media_order_and_legacy_twitter_host(self):
        expected, token = '画像2枚', 'https://t.co/photo'
        start = len((expected + ' ').encode('utf-16-le')) // 2
        post = {'id': '111', 'text': expected + ' ' + token, 'mediaKeys': ['3_first', '3_second'],
                'urls': [{'start': start, 'end': start + len(token), 'url': token,
                          'expanded_url': 'https://twitter.com/gear/status/111/photo/2',
                          'media_key': '3_second'}]}
        self.assertTrue(exact_x_text(post, expected))
        wrong = copy.deepcopy(post)
        wrong['urls'][0]['media_key'] = '3_first'
        self.assertFalse(exact_x_text(wrong, expected))

    def test_preflight_is_read_only_and_account_failure_blocks_without_journal(self):
        self.assertEqual(self.publisher.preflight(), {'verified': True, 'userId': '123'})
        self.assertFalse((self.root / 'social-publications').exists())
        self.x.user = '999'
        with self.assertRaisesRegex(ValueError, 'x_account_mismatch'):
            self.publisher.publish(self.job)
        self.assertFalse((self.root / 'social-publications').exists())

    def test_disabled_or_changed_image_never_posts_text_only(self):
        cfg = dict(self.config, socialPostingEnabled=False)
        with self.assertRaisesRegex(ValueError, 'social_posting_disabled'):
            SocialPublisher(cfg, {}, client=self.x).publish(self.job)
        self.fetcher.body = PNG + b'x'
        with self.assertRaisesRegex(ValueError, 'social_image_fetch_failed'):
            self.publisher.publish(self.job)
        self.assertFalse(any(action.endswith('create') for action, _ in self.x.calls))

    def test_wrong_revision_owner_target_or_review_blocks(self):
        for path, value in [('revision', '0' * 64), ('targetAccountId', '999')]:
            job = copy.deepcopy(self.job)
            if path == 'revision':
                job['social']['revision'] = value
            else:
                job['social']['proposal'][path] = value
            with self.assertRaises(ValueError):
                self.publisher.publish(job)
        job = copy.deepcopy(self.job)
        job['social']['approval']['user_id'] = 'other'
        with self.assertRaises(ValueError):
            self.publisher.publish(job)
        job = copy.deepcopy(self.job)
        job['social']['review']['passed'] = False
        with self.assertRaises(ValueError):
            self.publisher.publish(job)
        self.assertEqual(self.x.calls, [])

    def test_unknown_main_create_never_blind_retries(self):
        self.x.fail = 'maincreate'
        self.assertEqual(self.publisher.publish(self.job), {'status': 'requires_reconciliation', 'phase': 'maincreate'})
        self.x.fail = None
        self.assertEqual(self.publisher.publish(self.job), {'status': 'requires_reconciliation', 'phase': 'maincreate'})
        self.assertEqual([a for a, _ in self.x.calls].count('maincreate'), 1)
        self.assertNotIn('secret', self.marker().read_text())

    def test_unknown_reply_create_keeps_known_main_and_never_replies_twice(self):
        self.x.fail = 'replycreate'
        self.assertEqual(self.publisher.publish(self.job), {'status': 'requires_reconciliation', 'phase': 'replycreate'})
        self.x.fail = None
        self.assertEqual(self.publisher.publish(self.job), {'status': 'requires_reconciliation', 'phase': 'replycreate'})
        self.assertEqual([a for a, _ in self.x.calls].count('replycreate'), 1)
        self.assertEqual(json.loads(self.marker().read_text())['mainId'], '111')

    def test_known_main_id_readback_retry_never_reposts(self):
        self.x.fail = 'read'
        self.assertEqual(self.publisher.publish(self.job)['phase'], 'mainread')
        self.x.fail = None
        self.fetcher.body = b'origin unavailable after known post id'
        self.assertEqual(self.publisher.publish(self.job)['status'], 'verified')
        self.assertEqual([a for a, _ in self.x.calls].count('maincreate'), 1)

    def test_expired_uploaded_media_stops_before_main_post(self):
        self.x.fail = 'maincreate'
        self.publisher.publish(self.job)
        saved = json.loads(self.marker().read_text())
        saved['pending'] = None  # Simulate an operator having reconciled the unknown create as absent.
        saved.pop('mainId', None)
        saved['uploads'][0]['expiresAt'] = '2026-01-01T00:00:00+09:00'
        self.marker().write_text(json.dumps(saved))
        self.x.fail = None
        with self.assertRaisesRegex(ValueError, 'social_media_expired'):
            self.publisher.publish(self.job)
        self.assertEqual([a for a, _ in self.x.calls].count('maincreate'), 1)

    def test_readback_mismatch_blocks_reply_and_keeps_known_main_id(self):
        self.x.main = '555'
        self.assertEqual(self.publisher.publish(self.job)['phase'], 'mainread')
        self.assertFalse(any(a == 'replycreate' for a, _ in self.x.calls))
        self.assertEqual(json.loads(self.marker().read_text())['mainId'], '555')

    def test_real_runtime_and_ledger_accept_only_publisher_readback(self):
        self.x.photo = True
        ledger = Ledger(self.root, 'owner')
        scope = dict(team_id='T', app_id='A', user_id='owner', channel_id='C', thread_ts='1.0')
        now = datetime.now(timezone(timedelta(hours=9)))

        def approve(job, kind):
            request = ledger.create_request(job['id'], kind, now)
            ledger.mark_delivered(request['request_id'], scope, '2.0')
            event = dict(request['payload'], **scope, event_id='event-' + request['request_id'],
                         action_id='camp_review_approve', card_ts='2.0')
            return ledger.decide(event, scope, now)

        candidate = ledger.create_candidate({'slug': 'approved-social', 'title': 'Approved'}, now)
        draft = ledger.save_bundle(candidate['id'], self.job['bundle'])
        article_review = copy.deepcopy(self.job['social']['review'])
        article_review['fingerprint'] = draft['revision']
        ledger.record_review(draft['id'], draft['revision'], article_review)
        approved_article = approve(ledger.get_job(draft['id']), 'article')
        ledger.record_publication(draft['id'], draft['revision'],
                                  {'verified': True, 'url': URL,
                                   'readback': {'verified': True, 'fingerprint': draft['revision']}})
        proposal = self.job['social']['proposal']
        ledger.record_social(draft['id'], proposal, self.job['social']['review'])
        approved_social = approve(ledger.get_job(draft['id']), 'social')
        self.assertEqual(approved_social['stage'], 'social_approved')
        runtime = Runtime.__new__(Runtime)
        runtime.config = self.config
        runtime.root = self.root
        runtime.ledger = ledger
        runtime.social_publisher = self.publisher

        class SlackNotice:
            def notice(self, text):
                return {'verified': True, 'message_ts': '1.23'}

        runtime.slack = SlackNotice()
        posted = runtime.publish_social(approved_social)
        self.assertEqual(posted['stage'], 'social_posted')
        self.assertTrue(posted['social']['publication']['verified'])
        self.assertEqual(posted['social']['publication']['readback']['media']['items'][0]['mediaId'], '333')
        self.assertEqual(posted['social']['publication']['readback']['reply']['text'], 'https://t.co/short')
        self.assertIn('https://t.co/photo', posted['social']['publication']['readback']['main']['text'])
        self.assertEqual(posted['social']['publication']['replyUrl'], 'https://x.com/i/web/status/222')
        self.assertEqual([a for a, _ in self.x.calls].count('maincreate'), 1)


if __name__ == '__main__':
    unittest.main()
