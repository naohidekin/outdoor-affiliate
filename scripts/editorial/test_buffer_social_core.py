"""Offline contracts for the Buffer-bound social workflow."""
import copy
from datetime import datetime, timedelta
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import unittest

from dispatcher import DeterministicDispatcher
from ledger import fingerprint, valid_social_mode
from runtime import JST, Runtime, atomic
from slack import Slack
from buffer_publisher import BufferPublisher
from test_buffer_publisher import (ACCOUNT, ORG, BufferFake, Fetcher, XFake,
                                   approved_job)
from test_catalog import PNG
import test_runtime
from test_runtime import bundle


NOW = datetime(2026, 11, 20, 10, tzinfo=JST)
CHANNEL = '6adfd45e2f1f5ed648e05a86'


class BufferSocialCoreTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config.update(
            executionPolicy={'mode': 'deterministic', 'suspended': False,
                             'exceptions': {'autoAI': False}},
            socialGenerationEnabled=True,
            socialReviewEnabled=True,
            socialPostingEnabled=False,
            bufferPostingEnabled=False,
            bufferSocialStartPeriod='2026-11-20',
            buffer={'organizationId': 'org_verified', 'channelId': CHANNEL,
                    'xAccountId': '123', 'schedulingPolicy': 'next_available_slot',
                    'maxOutstanding': 3, 'duePollIntervalSeconds': 1800,
                    'maxDuePolls': 3})
        def draft(theme, context):
            value = bundle()
            value['images'][0].update(sha256='a' * 64, size=10)
            digest = hashlib.sha256(PNG).hexdigest()
            url = ('https://db.example/storage/v1/object/public/editorial-social-cards/'
                   + digest[:2] + '/' + digest + '.png')
            manifest = {'url': url, 'finalUrl': url, 'sha256': digest, 'size': len(PNG),
                        'contentType': 'image/png'}
            value['article'].setdefault('generationMeta', {})['socialCard'] = manifest
            value['images'].append({**manifest, 'role': 'social-card', 'verified': True})
            return value
        self.models.draft = draft

    def tearDown(self):
        test_runtime.RuntimeTests.tearDown(self)

    def published_job(self):
        return test_runtime.RuntimeTests.published_job(self)

    def approve(self, job, user='U'):
        return test_runtime.RuntimeTests.approve(self, job, user)

    def _save(self, job):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            db.execute('UPDATE jobs SET data=? WHERE id=?',
                       (json.dumps(job, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':')), job['id']))

    def _published_for_period(self, period='2026-11-20', *, audit=True):
        job = self.published_job()
        job['week'] = period
        manifest = job['bundle']['article']['generationMeta']['socialCard']
        job['publication']['readback']['socialCard'] = manifest
        self._save(job)
        job = self.runtime.ledger.get_job(job['id'])
        if audit:
            key = fingerprint({'id': job['id'], 'revision': job['revision'],
                               'publication': job['publication']})
            atomic(self.runtime.root / 'post-publication-audits' / (key + '.json'),
                   {'schemaVersion': 1, 'status': 'success', 'id': job['id'],
                    'revision': job['revision'], 'auditKey': key,
                    'publication': job['publication'], 'attempts': [],
                    'startedAt': NOW.isoformat(), 'completedAt': NOW.isoformat(),
                    'nextAttemptAt': None, 'action': None,
                    'result': {'passed': True, 'status': 'passed', 'issues': [],
                               'checks': [{'name': 'public_title', 'status': 'passed'},
                                          {'name': 'approved_body', 'status': 'passed'}]}})
        return job

    @staticmethod
    def _buffer_proposal():
        return {
            'deliveryMode': 'buffer_x', 'platform': 'x',
            'targetAccountIdX': '123',
            'buffer': {'organizationId': 'org_verified', 'channelId': CHANNEL,
                       'schedulingPolicy': 'next_available_slot'},
        }

    def test_buffer_mode_requires_exact_nested_binding_and_next_available_policy(self):
        valid_social_mode(self._buffer_proposal())
        mutations = [
            lambda p: p['buffer'].pop('channelId'),
            lambda p: p['buffer'].update(channelId=''),
            lambda p: p['buffer'].update(organizationId=''),
            lambda p: p['buffer'].update(schedulingPolicy='fixed_time'),
            lambda p: p.update(targetAccountIdX=''),
            lambda p: p.update(targetAccountId='123'),
            lambda p: p.update(targetAccountId=''),
            lambda p: p.update(dueAt=''),
            lambda p: p.update(scheduledAt=''),
        ]
        for mutation in mutations:
            proposal = copy.deepcopy(self._buffer_proposal())
            mutation(proposal)
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                valid_social_mode(proposal)

    def test_generation_binds_buffer_before_review_and_rejects_old_period_without_models(self):
        old = self._published_for_period('2026-11-13')
        with unittest.mock.patch.object(self.models, 'social') as social:
            with self.assertRaisesRegex(ValueError, 'buffer_social_period_ineligible'):
                self.runtime.make_social(old)
            social.assert_not_called()

        old['week'] = '2026-11-20'
        self._save(old)
        with unittest.mock.patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.make_social(self.runtime.ledger.get_job(old['id']))
        proposal = review.call_args.args[0]['proposal']
        self.assertEqual(self._buffer_proposal(), {key: proposal[key] for key in
            ('deliveryMode', 'platform', 'targetAccountIdX', 'buffer')})
        self.assertNotIn('dueAt', proposal)
        self.assertNotIn('scheduledAt', proposal)
        saved = self.runtime.ledger.get_job(old['id'])['social']
        self.assertEqual(fingerprint(proposal), saved['revision'])

    def test_missing_current_public_audit_blocks_before_social_models(self):
        job = self._published_for_period(audit=False)
        with unittest.mock.patch.object(self.models, 'social') as social:
            with self.assertRaisesRegex(ValueError, 'successful_public_audit'):
                self.runtime.make_social(job)
            social.assert_not_called()
        self.assertNotIn('make_social', {action['kind'] for action in
            DeterministicDispatcher(self.runtime).plan(NOW)['actions']})

    def test_partial_or_wrong_public_audit_never_authorizes_buffer_social(self):
        job = self._published_for_period()
        key = fingerprint({'id': job['id'], 'revision': job['revision'],
                           'publication': job['publication']})
        path = self.runtime.root / 'post-publication-audits' / (key + '.json')
        valid = json.loads(path.read_text())
        mutations = [
            lambda value: value.pop('schemaVersion'),
            lambda value: value.update(publication={'verified': True}),
            lambda value: value['result'].update(passed=False),
            lambda value: value['result'].update(issues=['mismatch']),
            lambda value: value['result'].pop('checks'),
            lambda value: value['result'].update(checks=[]),
            lambda value: value['result']['checks'][0].update(status='failed'),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(valid)
            mutation(changed)
            atomic(path, changed)
            with self.subTest(changed=changed), unittest.mock.patch.object(
                    self.models, 'social') as social:
                with self.assertRaisesRegex(ValueError, 'successful_public_audit'):
                    self.runtime.make_social(job)
                social.assert_not_called()

    def test_buffer_social_requires_content_addressed_current_social_card_before_models(self):
        job = self._published_for_period()
        mutations = [
            lambda value: value['bundle']['article']['generationMeta'].pop('socialCard'),
            lambda value: value['bundle']['images'][-1].update(url='https://maker.example/card.png'),
            lambda value: value['bundle']['images'][-1].update(sha256='c' * 64),
            lambda value: value['bundle']['images'][-1].update(size=999),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(job)
            mutation(changed)
            with self.subTest(changed=changed), unittest.mock.patch.object(
                    self.models, 'social') as social:
                with self.assertRaisesRegex(ValueError, 'buffer_social_card_binding_invalid'):
                    self.runtime.make_social(changed)
                social.assert_not_called()

    def test_buffer_journal_blocks_social_replacement_without_mutating_approval_or_reservation(self):
        job = self._published_for_period()
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        self.approve(job)
        self.runtime.consume()
        job = self.runtime.ledger.get_job(job['id'])
        revision = job['social']['revision']
        marker = self.runtime.root / 'buffer-publications' / (revision + '.json')
        atomic(marker, {'revision': revision, 'phase': 'unknown', 'pending': {'action': 'createPost'}})
        hold = self.runtime.ledger.reserve_buffer_requests('2026-11-20', 18, now=NOW)
        before_job = copy.deepcopy(job)
        before_budget = self.runtime.ledger.inspect_buffer_requests('2026-11-20')
        before_marker = marker.read_bytes()

        self.assertEqual(before_job, self.runtime.ledger.record_social(
            job['id'], job['social']['proposal'], job['social']['review']))
        proposal = copy.deepcopy(job['social']['proposal'])
        proposal['text'] += ' 修正版'
        review = copy.deepcopy(job['social']['review'])
        review['fingerprint'] = fingerprint(proposal)
        with self.assertRaisesRegex(ValueError, 'social effect requires explicit reconciliation'):
            self.runtime.ledger.record_social(job['id'], proposal, review)
        self.assertEqual(before_job, self.runtime.ledger.get_job(job['id']))
        self.assertEqual(before_budget, self.runtime.ledger.inspect_buffer_requests('2026-11-20'))
        self.assertEqual(before_marker, marker.read_bytes())
        self.assertIn(hold['id'], before_budget['reservations'])

    def test_dispatcher_caps_buffer_proposals_and_never_routes_buffer_to_direct_x(self):
        published = self._published_for_period()
        jobs = []
        for index, stage in enumerate(('social_review', 'social_approved', 'social_scheduled')):
            item = copy.deepcopy(published)
            item['id'] = 'buffer-pending-' + str(index)
            item['stage'] = stage
            proposal = self._buffer_proposal()
            item['social'] = {'proposal': proposal, 'revision': fingerprint(proposal),
                              'review': {}, 'approval': None}
            jobs.append(item)
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            for item in jobs:
                db.execute('INSERT INTO jobs VALUES (?,?)', (item['id'], json.dumps(item)))
        plan = DeterministicDispatcher(self.runtime).plan(NOW)
        self.assertNotIn('make_social', {item['kind'] for item in plan['actions']})
        self.assertNotIn('publish_social', {item['kind'] for item in plan['actions']})

    def test_consume_leaves_old_social_spool_untouched_but_accepts_current_buffer_request(self):
        old = self._published_for_period('2026-11-13')
        self.config.pop('bufferSocialStartPeriod')
        self.runtime.make_social(old)
        old_path = Path(self.config['spoolDir']) / 'old-social.json'
        old_req = self.slack.deliveries[-1][1]
        old_event = dict(old_req['payload'], **self.scope)
        old_event.update(user_id='U', event_id='old-event',
                         action_id='camp_review_approve', message_ts='1793000000.123456')
        atomic(old_path, old_event)
        self.config['bufferSocialStartPeriod'] = '2026-11-20'
        self.assertEqual(0, self.runtime.consume())
        self.assertTrue(old_path.exists())
        self.assertEqual('social_review', self.runtime.ledger.get_job(old['id'])['stage'])

        old['week'] = '2026-11-20'
        old['social'] = None
        old['stage'] = 'published'
        self._save(old)
        self.runtime.make_social(self.runtime.ledger.get_job(old['id']))
        current_req = self.slack.deliveries[-1][1]
        current_path = Path(self.config['spoolDir']) / 'buffer-social.json'
        event = dict(current_req['payload'], **self.scope)
        event.update(user_id='U', event_id='buffer-event',
                     action_id='camp_review_approve', message_ts='1793000000.123456')
        atomic(current_path, event)
        self.assertEqual(1, self.runtime.consume())
        self.assertFalse(current_path.exists())
        self.assertTrue(old_path.exists())
        self.assertEqual('social_approved', self.runtime.ledger.get_job(old['id'])['stage'])

    def test_rollout_never_redelivers_old_auto_x_or_preperiod_buffer_review(self):
        source = self._published_for_period()
        old_auto = copy.deepcopy(source)
        old_auto.update(id='old-auto-review', stage='social_review')
        old_auto['social'] = {'proposal': {'deliveryMode': 'auto_x'},
                              'revision': 'a' * 64, 'review': {}, 'approval': None}
        old_buffer = copy.deepcopy(source)
        old_buffer.update(id='old-buffer-review', week='2026-11-13', stage='social_review')
        old_buffer['social'] = {'proposal': self._buffer_proposal(),
                                'revision': 'b' * 64, 'review': {}, 'approval': None}
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            for item in (old_auto, old_buffer):
                db.execute('INSERT INTO jobs VALUES (?,?)',
                           (item['id'], json.dumps(item, ensure_ascii=False)))

        deliveries = len(self.slack.deliveries)
        plan = DeterministicDispatcher(self.runtime).plan(NOW)
        delivered_ids = {item['jobId'] for item in plan['actions']
                         if item['kind'] == 'deliver' and item.get('deliveryKind') == 'social'}
        self.assertFalse({'old-auto-review', 'old-buffer-review'} & delivered_ids)
        for job_id in ('old-auto-review', 'old-buffer-review'):
            with self.subTest(job_id=job_id), self.assertRaisesRegex(
                    ValueError, 'social_review_disabled'):
                self.runtime.deliver(job_id, 'social')
        self.assertEqual(deliveries, len(self.slack.deliveries))
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            self.assertEqual(0, db.execute(
                "SELECT count(*) FROM requests WHERE job_id IN (?,?)",
                ('old-auto-review', 'old-buffer-review')).fetchone()[0])

    def test_schedule_is_distinct_from_posted_and_due_check_is_bounded(self):
        job = self._published_for_period()
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        self.approve(job)
        self.runtime.consume()
        job = self.runtime.ledger.get_job(job['id'])
        due = NOW + timedelta(hours=2)

        class Adapter:
            def __init__(inner):
                inner.calls = 0
                inner.result = {'status': 'scheduled', 'verified': False,
                                'fingerprint': job['social']['revision'],
                                'bufferPostId': 'buffer-post-1', 'dueAt': due.isoformat()}

            def schedule_or_check(inner, current, now=None):
                inner.calls += 1
                atomic(self.runtime.root / 'buffer-publications' /
                       (current['social']['revision'] + '.json'), {
                    'revision': current['social']['revision'],
                    'phase': 'verified' if inner.result['status'] == 'verified' else 'scheduled',
                    'pending': None,
                    'bufferRequests': 3 + inner.calls,
                    'sharedRateLimits': [
                        {'name': str(seconds), 'quota': limit, 'window': seconds,
                         'remaining': remaining, 'resetAfter': 600}
                        for seconds, limit, remaining in
                        ((900, 150, 149), (86400, 600, 599), (2592000, 3000, 1147))
                    ],
                    'retryAfter': None,
                })
                return copy.deepcopy(inner.result)

        adapter = Adapter()
        self.runtime.buffer_publisher = adapter
        self.config['bufferPostingEnabled'] = True
        self.config['socialPostingEnabled'] = True
        with self.assertRaisesRegex(ValueError, 'direct_x_must_remain_disabled'):
            self.runtime.publish_buffer_social(job, now=NOW)
        self.config['socialPostingEnabled'] = False
        scheduled = self.runtime.publish_buffer_social(job, now=NOW)
        self.assertEqual('social_scheduled', scheduled['stage'])
        budget_period = self.runtime.ledger.production_schedule.period_key(NOW)
        self.assertEqual(4, self.runtime.ledger.inspect_buffer_requests(budget_period)['used'])
        self.assertIsNone(scheduled['social'].get('publication'))
        notice = self.runtime.root / 'buffer-scheduled-notices' / (
            scheduled['social']['revision'] + '.json')
        self.assertEqual('requires_reconciliation', json.loads(notice.read_text())['status'])
        self.assertTrue(any(text.startswith('【Buffer予約確認済み】') for text in self.slack.notices))
        with unittest.mock.patch.object(self.slack, 'notice') as resend:
            self.assertEqual('requires_reconciliation', self.runtime._notify_buffer_scheduled(scheduled))
            resend.assert_not_called()
        with unittest.mock.patch('runtime.datetime', wraps=datetime) as clock:
            clock.now.return_value = NOW
            health = self.runtime.tick()
        self.assertTrue(any(item.get('reason') == 'buffer_schedule_notice_requires_reconciliation'
                            for item in health['results']))
        self.assertEqual([], DeterministicDispatcher(self.runtime).plan(NOW + timedelta(minutes=30))['actions'])
        self.assertEqual([{'kind': 'publish_buffer_social', 'jobId': job['id']}],
                         DeterministicDispatcher(self.runtime).plan(due)['actions'])

        proposal = scheduled['social']['proposal']
        adapter.result = {
            'status': 'verified', 'verified': True,
            'fingerprint': scheduled['social']['revision'], 'bufferPostId': 'buffer-post-1',
            'accountId': proposal['targetAccountIdX'], 'mainId': '111', 'replyId': '222',
            'readback': {
                'verified': True, 'fingerprint': scheduled['social']['revision'],
                'accountId': proposal['targetAccountIdX'],
                'main': {'id': '111', 'authorId': proposal['targetAccountIdX'],
                         'text': proposal['text'], 'mediaKeys': ['media-1'], 'replyTo': None},
                'reply': {'id': '222', 'authorId': proposal['targetAccountIdX'],
                          'text': proposal['replyText'], 'mediaKeys': [], 'replyTo': '111'},
            },
        }
        with self.assertRaisesRegex(ValueError, 'Buffer X media identity'):
            self.runtime.publish_buffer_social(scheduled, now=due)
        self.assertEqual('social_scheduled', self.runtime.ledger.get_job(job['id'])['stage'])
        adapter.result['readback']['media'] = {
            'verified': True,
            'items': [{'mediaKey': 'media-1', 'url': 'https://pbs.twimg.com/media/known.png',
                       'actualSha256': proposal['images'][0]['sha256'],
                       'identity': {'kind': 'byte_sha256',
                                    'approvedSha256': proposal['images'][0]['sha256']}}],
        }
        with unittest.mock.patch.object(self.slack, 'notice', return_value={
                'verified': True, 'message_ts': '1793000002.123456'}):
            posted = self.runtime.publish_buffer_social(scheduled, now=due)
        self.assertEqual('social_posted', posted['stage'])
        self.assertEqual(6, self.runtime.ledger.inspect_buffer_requests(budget_period)['used'])
        self.assertEqual('buffer-post-1', posted['social']['publication']['bufferPostId'])

    def test_three_due_polls_terminally_require_reconciliation_without_adapter_call(self):
        job = self._published_for_period()
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        self.approve(job)
        self.runtime.consume()
        job = self.runtime.ledger.get_job(job['id'])
        revision = job['social']['revision']
        due = NOW + timedelta(hours=1)
        scheduled = {'status': 'scheduled', 'verified': False, 'fingerprint': revision,
                     'bufferPostId': 'buffer-post-terminal', 'dueAt': due.isoformat()}
        with self.assertRaisesRegex(ValueError, 'buffer due poll limit invalid'):
            self.runtime.ledger.record_buffer_social_schedule(
                job['id'], revision, scheduled, now=NOW, max_due_polls=3.0)
        self.runtime.ledger.record_buffer_social_schedule(job['id'], revision, scheduled, now=NOW)
        pending = dict(scheduled, status='pending')
        for offset in (0, 30, 60):
            terminal = self.runtime.ledger.record_buffer_social_schedule(
                job['id'], revision, pending, now=due + timedelta(minutes=offset))
        self.assertEqual(3, terminal['social']['bufferSchedule']['duePolls'])
        self.assertIsNone(terminal['social']['bufferSchedule']['nextCheckAt'])
        self.assertEqual('requires_reconciliation', terminal['social']['bufferSchedule']['status'])

        marker = self.runtime.root / 'buffer-publications' / (revision + '.json')
        atomic(marker, {'revision': revision, 'phase': 'scheduled', 'pending': None,
                        'bufferRequests': 3, 'sharedRateLimits': [], 'retryAfter': None})
        self.config['bufferPostingEnabled'] = True
        self.config['socialPostingEnabled'] = False
        plan = DeterministicDispatcher(self.runtime).plan(due + timedelta(hours=2))
        self.assertNotIn('publish_buffer_social', {item['kind'] for item in plan['actions']})
        self.assertIn({'jobId': job['id'],
                       'reason': 'buffer_publication_requires_reconciliation'}, plan['blocked'])

        adapter = unittest.mock.Mock()
        self.runtime.buffer_publisher = adapter
        before_budget = self.runtime.ledger.inspect_buffer_requests('2026-11-20')
        with self.assertRaisesRegex(ValueError, 'buffer_publication_requires_reconciliation'):
            self.runtime.publish_buffer_social(terminal, now=due + timedelta(hours=2))
        adapter.schedule_or_check.assert_not_called()
        self.assertEqual(before_budget, self.runtime.ledger.inspect_buffer_requests('2026-11-20'))

    def test_real_buffer_publisher_flows_through_runtime_and_ledger(self):
        source = approved_job()
        from PIL import Image
        image = Image.new('RGB', (16, 16))
        image.putdata([
            ((x * 17 + y * 3) % 256, (x * 7 + y * 19) % 256,
             (x * 13 + y * 11) % 256)
            for y in range(16) for x in range(16)])
        approved_file, native_file = BytesIO(), BytesIO()
        image.save(approved_file, format='PNG')
        image.save(native_file, format='JPEG', quality=83, subsampling=2)
        approved_bytes = approved_file.getvalue()
        approved_sha = hashlib.sha256(approved_bytes).hexdigest()
        approved_url = ('https://db.example/storage/v1/object/public/editorial-social-cards/'
                        + approved_sha[:2] + '/' + approved_sha + '.png')
        approved_image = {'url': approved_url, 'finalUrl': approved_url,
                          'contentType': 'image/png', 'sha256': approved_sha,
                          'size': len(approved_bytes), 'verified': True,
                          'role': 'social-card'}
        source['bundle']['images'] = [copy.deepcopy(approved_image)]
        source['bundle']['article']['generationMeta']['socialCard'] = {
            key: approved_image[key]
            for key in ('url', 'finalUrl', 'contentType', 'sha256', 'size')}
        source['social']['proposal']['images'] = [copy.deepcopy(approved_image)]
        source['revision'] = fingerprint(source['bundle'])
        source['publication']['revision'] = source['revision']
        source['publication']['readback']['fingerprint'] = source['revision']
        source['social']['revision'] = fingerprint(source['social']['proposal'])
        source['social']['review']['fingerprint'] = source['social']['revision']
        source['social']['approval']['revision'] = source['social']['revision']
        job = self._published_for_period(audit=False)
        job.update(stage='social_approved', bundle=copy.deepcopy(source['bundle']),
                   revision=source['revision'], publication=copy.deepcopy(source['publication']),
                   social=copy.deepcopy(source['social']))
        job['social']['approval']['user_id'] = self.config['slack']['user_id']
        self.config['buffer'].update(organizationId=ORG, channelId=CHANNEL,
                                     xAccountId=ACCOUNT, maxBufferRequestsPerPost=18,
                                     dedupLookbackDays=30, mutationRemainingFloor=5)
        self.config['bufferPostingEnabled'] = True
        self.config['socialPostingEnabled'] = False
        self._save(job)
        job = self.runtime.ledger.get_job(job['id'])
        key = fingerprint({'id': job['id'], 'revision': job['revision'],
                           'publication': job['publication']})
        atomic(self.runtime.root / 'post-publication-audits' / (key + '.json'), {
            'schemaVersion': 1, 'id': job['id'], 'revision': job['revision'],
            'publication': job['publication'], 'auditKey': key, 'status': 'success',
            'attempts': [], 'startedAt': NOW.isoformat(), 'completedAt': NOW.isoformat(),
            'nextAttemptAt': None, 'action': None,
            'result': {'passed': True, 'status': 'passed', 'issues': [],
                       'checks': [{'name': 'public_title', 'status': 'passed'},
                                  {'name': 'approved_body', 'status': 'passed'}]},
        })
        client = BufferFake(job)
        for limit in client.rate_limits:
            limit['resetAfter'] = 600
        fetcher = Fetcher()
        fetcher.body = approved_bytes
        self.runtime.buffer_publisher = BufferPublisher(
            self.config, {}, client=client, fetcher=fetcher, x_client=XFake())

        schedule_at = datetime(2026, 11, 20, 11, 0, tzinfo=JST)
        with unittest.mock.patch('test_buffer_publisher.DUE', '2026-11-20T03:00:00Z'):
            scheduled = self.runtime.publish_buffer_social(job, now=schedule_at)
            period = self.runtime.ledger.production_schedule.period_key(schedule_at)
            self.assertEqual(6, self.runtime.ledger.inspect_buffer_requests(period)['used'])
            client.status = 'sent'
            client.external = 'https://x.com/camp/status/111'
            fetcher.x_body = native_file.getvalue()
            with unittest.mock.patch.object(self.slack, 'notice', return_value={
                    'verified': True, 'message_ts': '1793000002.123456'}):
                posted = self.runtime.publish_buffer_social(
                    scheduled, now=datetime(2026, 11, 20, 12, 1, tzinfo=JST))
        self.assertEqual('social_posted', posted['stage'])
        self.assertEqual('111', posted['social']['publication']['mainId'])
        self.assertEqual('jpeg_encoding_reproduced',
                         posted['social']['publication']['readback']['media']['items'][0]
                         ['identity']['kind'])
        # Six schedule calls plus one due readback; X readback itself is not a Buffer request.
        self.assertEqual(7, self.runtime.ledger.inspect_buffer_requests(period)['used'])

    def test_buffer_slack_card_is_exact_version_consent_for_next_available_slot(self):
        proposal = dict(self._buffer_proposal(), text='広告 告知',
                        replyText='https://example.com/article',
                        url='https://example.com/article', images=[])
        job = {'id': 'article-buffer', 'bundle': {'article': {'title': '記事'}, 'images': []},
               'social': {'proposal': proposal, 'revision': fingerprint(proposal)}}
        request = {'kind': 'social', 'request_id': 'request', 'article_id': job['id'],
                   'manifest_hash': job['social']['revision'], 'nonce': 'nonce'}
        with unittest.mock.patch.object(Slack, 'post', return_value={
                'message_ts': '1793000000.123456'}) as post:
            Slack(self.config, call=lambda *_: None).deliver(job, request)
        card = post.call_args_list[-1].args[1]
        self.assertEqual('本文・画像を承認してBuffer予約',
                         card[1]['elements'][0]['text']['text'])
        self.assertIn('Bufferの次の空き枠', card[0]['text']['text'])
        self.assertNotIn('X接続の復旧待ち', card[0]['text']['text'])

    def test_missing_optional_buffer_env_does_not_block_article_production(self):
        config = dict(self.config, bufferEnvFile=str(self.runtime.root / 'missing-buffer.env'),
                      socialGenerationEnabled=False, socialReviewEnabled=False,
                      bufferPostingEnabled=False)
        runtime = Runtime(config, models=self.models, catalog=self.runtime.catalog,
                          slack=self.slack, renderer=self.runtime.renderer,
                          publisher=self.runtime.publisher)
        result = runtime.produce(limit=1)
        self.assertEqual(1, len(result['articles']))

    def test_ledger_buffer_request_budget_reserves_settles_and_holds_at_sixty(self):
        usage = {
            'requestCount': 4, 'observedAt': NOW.isoformat(),
            'rateLimitWindows': [
                {'windowSeconds': 900, 'limit': 100, 'remaining': 96, 'resetAt': NOW.isoformat()},
                {'windowSeconds': 86400, 'limit': 1000, 'remaining': 900, 'resetAt': NOW.isoformat()},
                {'windowSeconds': 2592000, 'limit': 3000, 'remaining': 1852, 'resetAt': NOW.isoformat()},
            ],
        }
        hold = self.runtime.ledger.reserve_buffer_requests('2026-11-20', 18, now=NOW)
        self.runtime.ledger.settle_buffer_requests(hold, usage, outcome='success', now=NOW)
        state = self.runtime.ledger.inspect_buffer_requests('2026-11-20')
        self.assertEqual((4, 56, {}), (state['used'], state['remaining'], state['reservations']))
        self.assertEqual(usage['rateLimitWindows'], state['rateLimitWindows'])
        for count in (18, 18, 18):
            hold = self.runtime.ledger.reserve_buffer_requests('2026-11-20', 18, now=NOW)
            value = copy.deepcopy(usage)
            value['requestCount'] = count
            self.runtime.ledger.settle_buffer_requests(hold, value, outcome='success', now=NOW)
        self.assertEqual(58, self.runtime.ledger.inspect_buffer_requests('2026-11-20')['used'])
        with self.assertRaisesRegex(ValueError, 'buffer_request_budget_hold'):
            self.runtime.ledger.reserve_buffer_requests('2026-11-20', 18, now=NOW)

    def test_ledger_buffer_429_is_retained_without_retry_or_fake_usage(self):
        hold = self.runtime.ledger.reserve_buffer_requests('2026-11-20', 18, now=NOW)
        usage = {
            'requestCount': 1, 'observedAt': NOW.isoformat(), 'statusCode': 429,
            'retryAfterSeconds': 900,
            'rateLimitWindows': [
                {'windowSeconds': seconds, 'limit': 100, 'remaining': 0,
                 'resetAt': (NOW + timedelta(minutes=15)).isoformat()}
                for seconds in (900, 86400, 2592000)
            ],
        }
        self.runtime.ledger.settle_buffer_requests(hold, usage, outcome='failed', now=NOW)
        state = self.runtime.ledger.inspect_buffer_requests('2026-11-20')
        self.assertEqual(1, state['used'])
        self.assertEqual(429, state['lastObservation']['statusCode'])
        self.assertEqual(900, state['lastObservation']['retryAfterSeconds'])
        self.assertEqual('buffer_rate_limit_429', state['holdReason'])


if __name__ == '__main__':
    unittest.main()
