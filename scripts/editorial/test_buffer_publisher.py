"""Offline exact-version and unknown-result tests for Buffer scheduling."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from buffer_publisher import BufferPublisher
from ledger import canonical, fingerprint, Ledger
from test_catalog import PNG


JST = timezone(timedelta(hours=9))
URL = 'https://camp-gear-lab.com/articles/test'
IMAGE_SHA = hashlib.sha256(PNG).hexdigest()
IMAGE_URL = ('https://db.example/storage/v1/object/public/editorial-social-cards/'
             + IMAGE_SHA[:2] + '/' + IMAGE_SHA + '.png')
ORG = 'org-1'
CHANNEL = '6adfd45e2f1f5ed648e05a86'
ACCOUNT = '1343879420470206464'
DUE = '2026-11-16T03:00:00Z'


def approved_job():
    image = dict(url=IMAGE_URL, finalUrl=IMAGE_URL, contentType='image/png',
                 sha256=IMAGE_SHA, size=len(PNG), verified=True, role='social-card')
    manifest = {key: image[key] for key in ('url', 'finalUrl', 'contentType', 'sha256', 'size')}
    bundle = {'article': {'title': 'Approved', 'generationMeta': {'socialCard': manifest}},
              'products': [], 'images': [image],
              'brief': {}, 'references': []}
    proposal = dict(text='新しい記事を公開しました。', replyText=URL, url=URL, images=[image],
                    platform='x', deliveryMode='buffer_x', targetAccountIdX=ACCOUNT,
                    buffer={'organizationId': ORG, 'channelId': CHANNEL,
                            'schedulingPolicy': 'next_available_slot'})
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
        self.x_body = PNG

    def request(self, url, headers):
        body = self.x_body if url.startswith('https://pbs.twimg.com/') else self.body
        return {'url': url, 'headers': {'content-type': 'image/png'}, 'body': body}


class BufferFake:
    def __init__(self, job):
        self.job = job
        self.calls = []
        self.fail = None
        self.posts_result = []
        self.status = 'draft'
        self.external = None
        self.rate_limits = [
            {'window': 900, 'remaining': 149, 'quota': 150},
            {'window': 86400, 'remaining': 599, 'quota': 600},
            {'window': 2592000, 'remaining': 2999, 'quota': 3000}]
        self.retry_after = None

    def preflight(self, organization_id, channel_id):
        self.calls.append(('preflight', (organization_id, channel_id)))
        return {'id': CHANNEL, 'organizationId': ORG, 'service': 'twitter', 'serviceId': ACCOUNT,
                'isDisconnected': False, 'isLocked': False, 'isQueuePaused': False,
                'linkShortening': {'isEnabled': False}}

    def posts(self, organization_id, channel_id, start, end):
        self.calls.append(('posts', (organization_id, channel_id, start, end)))
        return copy.deepcopy(self.posts_result)

    def _post(self, status=None):
        proposal = self.job['social']['proposal']
        assets = [{'id': 'asset', 'type': 'image', 'mimeType': 'image/png',
                   'source': image['url'], 'thumbnail': image['url']} for image in proposal['images']]
        return {'id': 'buffer-1', 'channelId': CHANNEL, 'channelService': 'twitter',
                'text': proposal['text'], 'status': status or self.status,
                'dueAt': None if (status or self.status) == 'draft' else DUE,
                'externalLink': self.external, 'assets': assets,
                'metadata': {'threadCount': 2, 'thread': [
                    {'text': proposal['text'], 'assets': assets},
                    {'text': proposal['replyText'], 'assets': []}]}}

    def create_post(self, value):
        self.calls.append(('create_post', copy.deepcopy(value)))
        if self.fail == 'create_post':
            raise TimeoutError('unknown')
        self.status = 'draft'
        return self._post()

    def post(self, post_id):
        self.calls.append(('post', post_id))
        if self.fail == 'post':
            raise TimeoutError('read failed')
        return self._post()

    def edit_post(self, value):
        self.calls.append(('edit_post', copy.deepcopy(value)))
        if self.fail == 'edit_post':
            raise TimeoutError('unknown')
        self.status = 'scheduled'
        return self._post()


class XFake:
    def __call__(self, action, payload):
        if action != 'threadread':
            raise ValueError('read only')
        token = 'https://t.co/article'
        return {'main': {'id': '111', 'authorId': ACCOUNT, 'text': '新しい記事を公開しました。',
                         'urls': [], 'mediaKeys': ['3_333'], 'replyTo': None},
                'replies': [{'id': '222', 'authorId': ACCOUNT, 'text': token,
                          'urls': [{'start': 0, 'end': len(token), 'url': token, 'expanded_url': URL}],
                          'mediaKeys': [], 'replyTo': '111'}],
                'media': [{'mediaKey': '3_333', 'type': 'photo',
                           'url': 'https://pbs.twimg.com/media/known.png'}]}


class BufferPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'private'
        self.root.mkdir(mode=0o700)
        self.config = {'stateRoot': str(self.root), 'socialPostingEnabled': False,
                       'bufferPostingEnabled': True,
                       'slack': {'user_id': 'owner'}, 'buffer': {
                           'organizationId': ORG, 'channelId': CHANNEL,
                           'xAccountId': ACCOUNT, 'maxDuePolls': 2,
                           'duePollIntervalSeconds': 60, 'dedupLookbackDays': 30,
                           'maxBufferRequestsPerPost': 18, 'mutationRemainingFloor': 5}}
        self.job = approved_job()
        self.buffer = BufferFake(self.job)
        self.fetcher = Fetcher()
        self.publisher = BufferPublisher(self.config, {}, client=self.buffer,
                                         fetcher=self.fetcher, x_client=XFake())

    def tearDown(self):
        self.tmp.cleanup()

    def marker(self):
        return self.root / 'buffer-publications' / (self.job['social']['revision'] + '.json')

    def schedule(self):
        return self.publisher.schedule_or_check(self.job, datetime(2026, 11, 16, 11, 0, tzinfo=JST))

    def test_draft_exact_readback_then_minimal_add_to_queue(self):
        result = self.schedule()
        self.assertEqual(result['status'], 'scheduled')
        self.assertEqual(result['dueAt'], DUE)
        actions = [action for action, _ in self.buffer.calls]
        self.assertEqual(actions, ['preflight', 'posts', 'create_post', 'post', 'edit_post', 'post'])
        created = next(value for action, value in self.buffer.calls if action == 'create_post')
        self.assertTrue(created['saveToDraft'])
        self.assertTrue(created['aiAssisted'])
        self.assertFalse(created['metadata']['twitter']['isAiGenerated'])
        self.assertEqual(created['mode'], 'addToQueue')
        self.assertEqual(created['metadata']['twitter']['thread'][1]['text'], URL)
        edited = next(value for action, value in self.buffer.calls if action == 'edit_post')
        self.assertEqual(edited, {'id': 'buffer-1', 'mode': 'addToQueue', 'saveToDraft': False,
                                  'schedulingType': 'automatic', 'source': 'camp-editorial-slack'})
        self.assertFalse({'text', 'assets', 'metadata', 'dueAt'} & set(edited))
        state = json.loads(self.marker().read_text())
        self.assertEqual(state['phase'], 'scheduled')
        self.assertEqual(state['imageBindings'][0]['sha256'], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(self.marker().stat().st_mode & 0o777, 0o600)

    def test_unknown_create_is_never_retried(self):
        self.buffer.fail = 'create_post'
        self.assertEqual(self.schedule()['reason'], 'buffer_create_result_unknown')
        first = [action for action, _ in self.buffer.calls].count('create_post')
        self.assertEqual(self.schedule()['reason'], 'buffer_effect_result_unknown')
        self.assertEqual([action for action, _ in self.buffer.calls].count('create_post'), first)

    def test_unknown_schedule_is_never_retried(self):
        self.buffer.fail = 'edit_post'
        self.assertEqual(self.schedule()['reason'], 'buffer_schedule_result_unknown')
        first = [action for action, _ in self.buffer.calls].count('edit_post')
        self.assertEqual(self.schedule()['reason'], 'buffer_effect_result_unknown')
        self.assertEqual([action for action, _ in self.buffer.calls].count('edit_post'), first)

    def test_changed_image_blocks_before_create(self):
        self.fetcher.body = PNG + b'changed'
        with self.assertRaisesRegex(ValueError, 'social_image_fetch_failed'):
            self.schedule()
        self.assertNotIn('create_post', [action for action, _ in self.buffer.calls])

    def test_mutable_social_card_url_blocks_before_any_buffer_call(self):
        mutable = 'https://maker.example.com/latest/card.png'
        manifest = self.job['bundle']['article']['generationMeta']['socialCard']
        for item in (self.job['social']['proposal']['images'][0],
                     self.job['bundle']['images'][0], manifest):
            item['url'] = mutable
            item['finalUrl'] = mutable
        self.job['revision'] = fingerprint(self.job['bundle'])
        self.job['publication']['revision'] = self.job['revision']
        self.job['publication']['readback']['fingerprint'] = self.job['revision']
        self.job['social']['revision'] = fingerprint(self.job['social']['proposal'])
        self.job['social']['review']['fingerprint'] = self.job['social']['revision']
        self.job['social']['approval']['revision'] = self.job['social']['revision']
        with self.assertRaisesRegex(ValueError, 'social_card_immutable_binding_invalid'):
            self.schedule()
        self.assertEqual(self.buffer.calls, [])

    def test_draft_readback_mismatch_blocks_schedule(self):
        original = self.buffer._post
        self.buffer._post = lambda status=None: dict(original(status), text='changed')
        with self.assertRaisesRegex(ValueError, 'buffer_draft_readback_mismatch'):
            self.schedule()
        self.assertNotIn('edit_post', [action for action, _ in self.buffer.calls])

    def test_existing_exact_draft_is_held_and_never_adopted(self):
        self.buffer.posts_result = [self.buffer._post('draft')]
        self.assertEqual(self.schedule()['reason'], 'buffer_duplicate_post_hold')
        calls = len(self.buffer.calls)
        self.assertEqual(self.schedule()['reason'], 'buffer_duplicate_post_hold')
        self.assertEqual(len(self.buffer.calls), calls)
        self.assertNotIn('create_post', [action for action, _ in self.buffer.calls])
        self.assertNotIn('edit_post', [action for action, _ in self.buffer.calls])

    def test_article_url_match_from_other_automation_is_held(self):
        other = self.buffer._post('scheduled')
        other['text'] = 'different text'
        other['metadata']['thread'][0]['text'] = 'different text'
        self.buffer.posts_result = [other]
        self.assertEqual(self.schedule()['reason'], 'buffer_duplicate_post_hold')

    def test_article_url_in_other_automation_main_text_is_held(self):
        other = self.buffer._post('scheduled')
        other['text'] = '別の自動化による公開です: ' + URL + '。'
        other['metadata']['thread'] = [{'text': '別内容', 'assets': []}]
        self.buffer.posts_result = [other]
        self.assertEqual(self.schedule()['reason'], 'buffer_duplicate_post_hold')
        self.assertNotIn('create_post', [action for action, _ in self.buffer.calls])

    def test_social_scheduled_stage_can_poll_own_marker(self):
        self.schedule()
        self.job['stage'] = 'social_scheduled'
        result = self.publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 11, 30, tzinfo=JST))
        self.assertEqual(result['status'], 'pending')

    def test_before_due_returns_pending_without_x_read(self):
        self.schedule()
        result = self.publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 11, 30, tzinfo=JST))
        self.assertEqual(result['status'], 'pending')
        self.assertFalse(result['verified'])

    def test_sent_requires_x_readback_for_verified(self):
        self.schedule()
        self.buffer.status = 'sent'
        self.buffer.external = 'https://x.com/camp/status/111'
        result = self.publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 12, 1, tzinfo=JST))
        self.assertEqual((result['status'], result['verified']), ('verified', True))
        self.assertEqual((result['mainId'], result['replyId']), ('111', '222'))

    def test_actual_buffer_publisher_evidence_records_in_real_ledger(self):
        scheduled = self.schedule()
        self.buffer.status = 'sent'
        self.buffer.external = 'https://x.com/camp/status/111'
        self.fetcher.x_body = PNG + b'non-pixel-metadata'
        evidence = self.publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 12, 1, tzinfo=JST))
        self.assertTrue(evidence['verified'])
        self.assertEqual(evidence['readback']['media']['items'][0]['identity']['kind'],
                         'decoded_rgba_sha256')

        stored = copy.deepcopy(self.job)
        stored['id'] = 'buffer-e2e'
        stored['stage'] = 'social_scheduled'
        stored['social']['bufferSchedule'] = {
            'fingerprint': stored['social']['revision'],
            'bufferPostId': scheduled['bufferPostId'], 'dueAt': scheduled['dueAt'],
            'status': 'scheduled', 'verified': False, 'duePolls': 0,
            'nextCheckAt': scheduled['dueAt']}
        ledger = Ledger(self.root, 'owner')
        with sqlite3.connect(ledger.db_path) as db:
            db.execute('INSERT INTO jobs VALUES (?,?)', (stored['id'], canonical(stored)))

        tampered = copy.deepcopy(evidence)
        tampered['readback']['media']['items'][0]['identity'] = {
            'kind': 'decoded_rgba_sha256',
            'approvedSha256': stored['social']['proposal']['images'][0]['sha256'],
            'pixelSha256': 'not-a-digest', 'width': 1, 'height': 1}
        with self.assertRaisesRegex(ValueError, 'Buffer X media identity'):
            ledger.record_buffer_social_publication(
                stored['id'], stored['social']['revision'], tampered)

        posted = ledger.record_buffer_social_publication(
            stored['id'], stored['social']['revision'], evidence)
        self.assertEqual(posted['stage'], 'social_posted')
        self.assertEqual(posted['social']['publication'], evidence | {
            'at': posted['social']['publication']['at'],
            'mainUrl': 'https://x.com/i/web/status/111',
            'replyUrl': 'https://x.com/i/web/status/222'})

    def test_buffer_sent_without_x_reader_is_explicitly_unverified(self):
        self.schedule()
        self.buffer.status = 'sent'
        self.buffer.external = 'https://x.com/camp/status/111'
        publisher = BufferPublisher(self.config, {}, client=self.buffer, fetcher=self.fetcher)
        result = publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 12, 1, tzinfo=JST))
        self.assertEqual((result['status'], result['verified'], result['reason']),
                         ('unverified', False, 'x_readback_unavailable'))

    def test_x_reencoded_identical_pixels_are_verified_but_changed_pixels_are_not(self):
        self.schedule()
        self.buffer.status = 'sent'
        self.buffer.external = 'https://x.com/camp/status/111'
        self.fetcher.x_body = PNG + b'non-pixel-metadata'
        same = self.publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 12, 1, tzinfo=JST))
        self.assertTrue(same['verified'])
        self.assertEqual(same['readback']['media']['items'][0]['identity']['kind'],
                         'decoded_rgba_sha256')

        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'private'
        self.root.mkdir(mode=0o700)
        self.config['stateRoot'] = str(self.root)
        self.buffer = BufferFake(self.job)
        self.publisher = BufferPublisher(self.config, {}, client=self.buffer,
                                         fetcher=self.fetcher, x_client=XFake())
        self.schedule()
        self.buffer.status = 'sent'
        self.buffer.external = 'https://x.com/camp/status/111'
        self.fetcher.x_body = b'not-an-image'
        changed = self.publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 12, 1, tzinfo=JST))
        self.assertFalse(changed['verified'])
        self.assertEqual(changed['reason'], 'x_media_pixels_mismatch')
        self.assertEqual(changed['mainId'], '111')
        self.assertEqual(changed['replyCandidateIds'], ['222'])

    def test_x_jpeg_encoding_reproduction_is_exact_and_rejects_wrong_image(self):
        from PIL import Image

        source_image = Image.new('RGB', (16, 16))
        source_image.putdata([
            ((x * 17 + y * 3) % 256, (x * 7 + y * 19) % 256, (x * 13 + y * 11) % 256)
            for y in range(16) for x in range(16)])
        source_file, native_file = BytesIO(), BytesIO()
        source_image.save(source_file, format='PNG')
        source_image.save(native_file, format='JPEG', quality=83, subsampling=2)
        source, native = source_file.getvalue(), native_file.getvalue()
        approved = {'url': IMAGE_URL, 'finalUrl': IMAGE_URL, 'contentType': 'image/png',
                    'sha256': hashlib.sha256(source).hexdigest(), 'size': len(source),
                    'verified': True, 'role': 'social-card'}
        self.fetcher.body, self.fetcher.x_body = source, native
        items = self.publisher._verify_x_media([
            {'mediaKey': '3_333', 'type': 'photo',
             'url': 'https://pbs.twimg.com/media/native.jpg'}], {'images': [approved]})
        identity = items[0]['identity']
        self.assertEqual(identity['kind'], 'jpeg_encoding_reproduced')
        self.assertEqual(identity['subsampling'], 2)
        self.assertRegex(identity['quantizationSha256'], r'^[a-f0-9]{64}$')

        wrong = Image.new('RGB', (16, 16), (255, 0, 0))
        wrong_file = BytesIO()
        wrong.save(wrong_file, format='JPEG', quality=83, subsampling=2)
        self.fetcher.x_body = wrong_file.getvalue()
        with self.assertRaisesRegex(ValueError, 'x_media_pixels_mismatch'):
            self.publisher._verify_x_media([
                {'mediaKey': '3_333', 'type': 'photo',
                 'url': 'https://pbs.twimg.com/media/wrong.jpg'}], {'images': [approved]})

    def test_per_post_buffer_request_budget_stops_before_next_call(self):
        self.publisher.settings['maxBufferRequestsPerPost'] = 6
        self.schedule()
        self.job['stage'] = 'social_scheduled'
        calls = len(self.buffer.calls)
        with self.assertRaisesRegex(ValueError, 'buffer_request_budget_exhausted'):
            self.publisher.schedule_or_check(
                self.job, datetime(2026, 11, 16, 12, 1, tzinfo=JST))
        self.assertEqual(len(self.buffer.calls), calls)

    def test_disabled_and_binding_mismatch_fail_before_mutation(self):
        disabled = copy.deepcopy(self.config)
        disabled['bufferPostingEnabled'] = False
        with self.assertRaisesRegex(ValueError, 'buffer_posting_disabled'):
            BufferPublisher(disabled, {}, client=self.buffer, fetcher=self.fetcher).publish(self.job)
        changed = copy.deepcopy(self.job)
        changed['social']['proposal']['buffer']['channelId'] = 'other'
        changed['social']['revision'] = fingerprint(changed['social']['proposal'])
        changed['social']['review']['fingerprint'] = changed['social']['revision']
        changed['social']['approval']['revision'] = changed['social']['revision']
        with self.assertRaisesRegex(ValueError, 'buffer_proposal_binding_mismatch'):
            self.publisher.publish(changed)
        self.assertNotIn('create_post', [action for action, _ in self.buffer.calls])

    def test_social_scheduled_without_owned_marker_never_calls_buffer(self):
        self.job['stage'] = 'social_scheduled'
        with self.assertRaisesRegex(ValueError, 'buffer_schedule_marker_required'):
            self.publisher.schedule_or_check(
                self.job, datetime(2026, 11, 16, 12, 1, tzinfo=JST))
        self.assertEqual(self.buffer.calls, [])

    def test_due_read_failures_consume_bounded_attempts_before_api(self):
        self.schedule()
        self.job['stage'] = 'social_scheduled'
        self.buffer.fail = 'post'
        for minute in (1, 2):
            with self.assertRaises(TimeoutError):
                self.publisher.schedule_or_check(
                    self.job, datetime(2026, 11, 16, 12, minute, tzinfo=JST))
        calls = [action for action, _ in self.buffer.calls].count('post')
        result = self.publisher.schedule_or_check(
            self.job, datetime(2026, 11, 16, 12, 3, tzinfo=JST))
        self.assertEqual(result['reason'], 'buffer_due_poll_exhausted')
        self.assertEqual([action for action, _ in self.buffer.calls].count('post'), calls)

    def test_link_shortening_blocks_before_dedup_or_create(self):
        original = self.buffer.preflight
        self.buffer.preflight = lambda organization_id, channel_id: dict(
            original(organization_id, channel_id), linkShortening={'isEnabled': True})
        with self.assertRaisesRegex(ValueError, 'buffer_link_shortening_must_be_disabled'):
            self.schedule()
        self.assertNotIn('posts', [action for action, _ in self.buffer.calls])
        self.assertNotIn('create_post', [action for action, _ in self.buffer.calls])

    def test_low_shared_quota_is_terminal_before_mutation(self):
        self.buffer.rate_limits[-1]['remaining'] = 5
        result = self.schedule()
        self.assertEqual(result['reason'], 'buffer_mutation_quota_hold')
        calls = len(self.buffer.calls)
        self.assertNotIn('create_post', [action for action, _ in self.buffer.calls])
        self.assertEqual(self.schedule()['reason'], 'buffer_mutation_quota_hold')
        self.assertEqual(len(self.buffer.calls), calls)


if __name__ == '__main__':
    unittest.main()
