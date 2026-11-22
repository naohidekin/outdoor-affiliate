"""Offline opt-in account/day guard contracts; no live provider access."""
import copy
from datetime import datetime, timedelta
from unittest.mock import patch
import fcntl
import json
import unittest

from buffer_api import BufferAPI
from account_fence import AccountFence
from buffer_publisher import BufferPublisher, JST
from test_buffer_api import Transport
import test_buffer_publisher as fixtures
from test_buffer_publisher import ACCOUNT, CHANNEL


class DailyGuardTests(unittest.TestCase):
    marker = fixtures.BufferPublisherTests.marker
    tearDown = fixtures.BufferPublisherTests.tearDown
    # Reuse fixtures without collecting the parent's legacy tests a second time.
    def setUp(self):
        fixtures.BufferPublisherTests.setUp(self)
        self.publisher.settings['dailyRootLimit'] = 3
        self.fence_path = (self.root / 'buffer-publications' /
                           ('account-' + ACCOUNT + '.cross-route.json'))
        self.fence_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.fence_path.write_text(json.dumps({'version': 1, 'binding': {
            'organizationId': fixtures.ORG, 'channelId': CHANNEL,
            'xAccountId': ACCOUNT}, 'entries': []}) + '\n')
        self.fence_path.chmod(0o600)
        self.native_calls = []
        self.roots = []
        self.pending = []
        self.publisher.x_client = self.native
        original_preflight = self.buffer.preflight
        def preflight(*args):
            value = original_preflight(*args)
            value.update(timezone='Asia/Tokyo', postingSchedule=[
                {'day': day, 'paused': False, 'times': ['08:07', '12:17', '19:17']}
                for day in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')])
            return value
        self.buffer.preflight = preflight
        self.buffer.pending_posts = self.pending_posts
        original_post = self.buffer._post
        def scheduled_post(status=None):
            value = original_post(status)
            if value['status'] != 'draft':
                value['dueAt'] = '2026-11-16T03:17:00Z'
            return value
        self.buffer._post = scheduled_post
        original_edit = self.buffer.edit_post
        def edit(value):
            post = original_edit(value)
            if value.get('saveToDraft'):
                self.buffer.status = 'draft'
                return self.buffer._post()
            return post
        self.buffer.edit_post = edit

    def at(self, job, now):
        self.publisher.clock = lambda: now
        return self.publisher.schedule_or_check(job, now=now)

    def schedule(self):
        return self.at(self.job, datetime(2026, 11, 16, 11, tzinfo=JST))

    def native(self, action, payload):
        self.native_calls.append((action, payload))
        if action == 'preflight':
            return {'userId': ACCOUNT}
        self.assertEqual('dayroots', action)
        return {'accountId': ACCOUNT, 'start': payload['start'], 'end': payload['end'],
                'complete': True, 'roots': copy.deepcopy(self.roots)}

    def pending_posts(self, *_):
        self.buffer.calls.append(('pending_posts', None))
        return copy.deepcopy(self.pending)

    def native_root(self, id, at='2026-11-16T00:00:00Z'):
        return {'id': str(id), 'createdAt': at}

    def reservation(self, id, status='scheduled', due='2026-11-16T10:00:00Z'):
        return {'id': id, 'channelId': CHANNEL, 'channelService': 'twitter',
                'status': status, 'dueAt': due, 'isCustomScheduled': True,
                'metadata': {'threadCount': 2}}

    def test_today_three_defers_without_create_and_keeps_approval(self):
        self.roots = [self.native_root(i) for i in (1, 2, 3)]
        before = copy.deepcopy(self.job)
        result = self.schedule()
        self.assertEqual('deferred', result['status'])
        self.assertEqual('buffer_daily_root_limit', result['reason'])
        self.assertEqual('2026-11-17T00:00:00+09:00', result['nextEligibleAt'])
        self.assertEqual(before, self.job)
        self.assertFalse({'create_post', 'edit_post'} & {x[0] for x in self.buffer.calls})
        state = json.loads(self.marker().read_text())
        self.assertEqual(0, state['polls'])
        self.assertEqual('deferred', state['phase'])
        self.assertIsNone(state['pending'])
        calls = (len(self.buffer.calls), len(self.native_calls), state['bufferRequests'])
        self.assertEqual(result, self.schedule())
        self.assertEqual(calls, (len(self.buffer.calls), len(self.native_calls),
                                json.loads(self.marker().read_text())['bufferRequests']))

    def test_real_gear_target_cannot_disable_the_guard_by_omitting_limit(self):
        self.publisher.settings.update(organizationId='6adf7fbb37d17051a678fba0')
        self.publisher.settings.pop('dailyRootLimit')
        with self.assertRaisesRegex(ValueError, 'gearman_daily_guard_configuration_required'):
            self.publisher.schedule_or_check(self.job, datetime(2026, 11, 16, 11, tzinfo=JST))
        self.assertEqual([], self.buffer.calls)

    def test_mixed_native_manual_custom_thread_roots_and_jst(self):
        self.roots = [self.native_root(1, '2026-11-15T15:00:00Z')]
        self.pending = [self.reservation('manual'), self.reservation('custom'),
                        self.reservation('tomorrow', due='2026-11-16T15:00:00Z'),
                        self.reservation('draft', status='draft', due=None)]
        self.assertEqual('buffer_daily_root_limit', self.schedule()['reason'])
        request = self.native_calls[-1][1]
        self.assertEqual('2026-11-14T15:00:00Z', request['start'])
        self.assertTrue(request['end'].startswith('2026-11-16T02:00:00'))

    def test_free_capacity_schedules_exact_approval(self):
        before = copy.deepcopy(self.job)
        result = self.schedule()
        self.assertEqual('scheduled', result['status'])
        self.assertEqual(before, self.job)
        self.assertEqual(8, json.loads(self.marker().read_text())['bufferRequests'])

    def test_due_outside_verified_slots_rolls_back_and_requires_reconciliation(self):
        original = self.buffer._post
        def post(status=None):
            value = original(status)
            if value['status'] != 'draft':
                value['dueAt'] = '2026-11-16T09:44:00Z'
            return value
        self.buffer._post = post
        before = copy.deepcopy(self.job)
        result = self.schedule()
        self.assertEqual('unverified', result['status'])
        self.assertEqual('buffer_due_schedule_mismatch', result['reason'])
        self.assertEqual('draft', self.buffer.status)
        self.assertEqual(before, self.job)
        state = json.loads(self.marker().read_text())
        self.assertEqual('unverified', state['phase'])
        self.assertEqual('draft', state['rollbackReadback']['status'])
        self.assertIsNone(state['pending'])
        self.assertIsNone(state['dueAt'])
        calls = copy.deepcopy(self.buffer.calls)
        self.assertEqual(result, self.schedule())
        self.assertEqual(calls, self.buffer.calls)

    def test_three_approved_jobs_reserve_free_regular_slots_in_one_day(self):
        times = ['2026-11-15T23:07:00Z', '2026-11-16T03:17:00Z', '2026-11-16T10:17:00Z']
        current = [0]
        original = self.buffer._post
        def post(status=None):
            value = original(status)
            value.update(id='queued-' + str(current[0]), isCustomScheduled=False, shareMode='addToQueue')
            if value['status'] != 'draft':
                value['dueAt'] = times[current[0]]
            return value
        self.buffer._post = post
        base = copy.deepcopy(self.job)
        for index, due in enumerate(times):
            current[0] = index
            job = copy.deepcopy(base)
            proposal = job['social']['proposal']
            proposal['text'] += str(index)
            url = fixtures.URL + str(index)
            proposal.update(url=url, replyText=url)
            job['publication']['url'] = url
            revision = fixtures.fingerprint(proposal)
            job['social']['revision'] = revision
            job['social']['review']['fingerprint'] = revision
            job['social']['approval']['revision'] = revision
            self.buffer.job = job
            before = copy.deepcopy(job)
            result = self.at(job, datetime(2026, 11, 16, 0, 1, tzinfo=JST))
            self.assertEqual('scheduled', result['status'])
            self.assertEqual(due, result['dueAt'])
            self.assertEqual(before, job)
            marker = self.root / 'buffer-publications' / (revision + '.json')
            self.assertEqual(8, json.loads(marker.read_text())['bufferRequests'])
            self.pending.append(post())
        self.assertEqual(3, sum(name == 'create_post' for name, _ in self.buffer.calls))
        self.assertEqual(3, sum(name == 'edit_post' for name, _ in self.buffer.calls))

    def test_custom_post_at_regular_slot_remains_spacing_conflict(self):
        value = self.reservation('custom', due='2026-11-15T23:07:00Z')
        value['shareMode'] = 'customScheduled'
        self.pending = [value]
        result = self.at(self.job, datetime(2026, 11, 16, 0, 1, tzinfo=JST))
        self.assertEqual('buffer_minimum_root_gap', result['reason'])
        self.assertEqual('2026-11-16T08:08:30+09:00', result['nextEligibleAt'])
        self.assertFalse({'create_post', 'edit_post'} & {name for name, _ in self.buffer.calls})

    def test_stale_tick_cannot_bypass_execution_time_guard(self):
        self.publisher.clock = lambda: datetime(2026, 11, 16, 12, 16, tzinfo=JST)
        result = self.publisher.schedule_or_check(self.job, datetime(2026, 11, 16, 11, tzinfo=JST))
        self.assertEqual('buffer_due_guard_time', result['reason'])
        self.assertFalse({'create_post', 'edit_post'} & {name for name, _ in self.buffer.calls})

    def test_previous_day_native_roots_affect_gap_but_not_today_count(self):
        preflight = self.buffer.preflight
        def early(*args):
            channel = preflight(*args)
            for row in channel['postingSchedule']:
                row['times'] = ['00:20', '12:17', '19:17']
            return channel
        self.buffer.preflight = early
        self.roots = [self.native_root(i, '2026-11-15T14:50:00Z') for i in (1, 2, 3)]
        now = datetime(2026, 11, 16, 0, 1, tzinfo=JST)
        self.publisher.clock = lambda: now
        result = self.at(self.job, now)
        self.assertEqual('buffer_minimum_root_gap', result['reason'])
        self.assertEqual('2026-11-14T15:00:00Z', self.native_calls[-1][1]['start'])

    def test_insufficient_verification_allowance_holds_before_effects(self):
        self.publisher.settings['maxBufferRequestsPerPost'] = 11
        result = self.schedule()
        self.assertEqual('buffer_daily_guard_budget_hold', result['reason'])
        self.assertEqual([], self.buffer.calls)

    def test_native_cutoff_is_whole_second_utc_with_exact_echo(self):
        original = self.publisher.x_client
        def native(action, payload):
            if action == 'dayroots':
                self.assertEqual('2026-11-14T15:00:00Z', payload['start'])
                self.assertEqual('2026-11-16T02:00:00Z', payload['end'])
            return original(action, payload)
        self.publisher.x_client = native
        self.roots = [self.native_root(i) for i in (1, 2, 3)]
        with patch('buffer_publisher.time.monotonic', return_value=0):
            result = self.at(
                self.job, datetime(2026, 11, 16, 11, 0, 0, 987654, tzinfo=JST))
        self.assertEqual('buffer_daily_root_limit', result['reason'])

    def test_native_root_at_exclusive_whole_second_cutoff_is_rejected(self):
        self.roots = [self.native_root(1, '2026-11-16T02:00:00Z')]
        with patch('buffer_publisher.time.monotonic', return_value=0):
            result = self.at(
                self.job, datetime(2026, 11, 16, 11, 0, 0, 987654, tzinfo=JST))
        self.assertEqual('buffer_daily_capacity_unverified', result['reason'])
        self.assertFalse({'create_post', 'edit_post'} & {name for name, _ in self.buffer.calls})

    def test_due_day_full_rolls_back_verified_draft_and_defers(self):
        original = self.buffer.pending_posts
        def pending(*args):
            result = original(*args)
            if self.buffer.status == 'scheduled':
                result += [self.reservation(str(i)) for i in range(3)]
            return result
        self.buffer.pending_posts = pending
        result = self.schedule()
        self.assertEqual('deferred', result['status'])
        self.assertEqual('draft', result['bufferStatus'])
        self.assertEqual('buffer_daily_root_limit', result['reason'])
        self.assertIsNone(result['dueAt'])
        self.assertEqual('draft', self.buffer.status)
        state = json.loads(self.marker().read_text())
        self.assertEqual(10, state['bufferRequests'])
        self.assertEqual('2026-11-16T03:17:00Z', state['rejectedDueAt'])
        self.assertEqual(0, state['polls'])
        self.assertIsNone(state['pending'])
        self.assertEqual(2, state['scheduleAttempt'])
        fence = json.loads(self.fence_path.read_text())
        schedule = next(row for row in fence['entries'] if row['operationId'].startswith('camp:schedule:'))
        self.assertEqual('terminal_rolled_back', schedule['phase'])

    def test_future_day_accepts_only_past_terminal_history_without_native_query(self):
        proposal, revision = self.publisher._validate(self.job)
        binding = self.publisher._binding()
        folder = self.root / 'buffer-publications'; folder.mkdir(mode=0o700, exist_ok=True)
        marker = folder / (revision + '.json')
        state, _ = self.publisher._state(marker, revision, proposal, binding)
        fence = self.publisher._account_fence(binding)
        intent = {'operationId': 'camp:past', 'route': 'camp', 'account': 'camp_gear_lab',
                  'channelId': CHANNEL, 'parentCount': 1, 'dueAt': None,
                  'requestHash': 'a' * 64}
        fence.intent(intent); fence.accept('camp:past', 'past-buffer', '2026-11-16T00:00:00Z')
        fence.posted('camp:past', 'past-buffer', '123', '2026-11-16T00:00:00Z')
        count, observed, _ = self.publisher._day_roots(
            marker, state, binding, datetime(2026, 11, 17, tzinfo=JST).date(),
            datetime(2026, 11, 16, 11, tzinfo=JST), fence=fence)
        self.assertEqual(0, count)
        self.assertIn(datetime(2026, 11, 16, 9, tzinfo=JST), observed)
        self.assertEqual([], self.native_calls)

    def test_today_skips_old_buffer_terminal_and_uses_native_time_for_current_id(self):
        proposal, revision = self.publisher._validate(self.job); binding = self.publisher._binding()
        folder = self.root / 'buffer-publications'; folder.mkdir(mode=0o700, exist_ok=True)
        marker = folder / (revision + '.json'); state, _ = self.publisher._state(marker, revision, proposal, binding)
        base = {'operationId': 'normal:old', 'route': 'normal', 'account': 'camp_gear_lab',
                'channelId': CHANNEL, 'parentCount': 1, 'requestHash': 'a' * 64,
                'phase': 'terminal_buffer_reported_sent', 'bufferPostId': 'old-buffer',
                'dueAt': '2026-11-14T00:00:00Z', 'reportedPostId': '900',
                'sentAt': '2026-11-14T00:00:00Z',
                'publicUrl': 'https://x.com/camp_gear_lab/status/900'}
        current = dict(base, operationId='normal:current', bufferPostId='current-buffer',
                       reportedPostId='901', dueAt='2026-11-16T00:00:00Z',
                       sentAt='2026-11-16T00:00:00Z',
                       publicUrl='https://x.com/camp_gear_lab/status/901')
        self.fence_path.write_text(json.dumps({'version': 1, 'binding': binding,
                                               'entries': [base, current]}) + '\n')
        self.fence_path.chmod(0o600); self.roots = [self.native_root('901', '2026-11-16T00:00:07Z')]
        count, observed, _ = self.publisher._day_roots(
            marker, state, binding, datetime(2026, 11, 16, tzinfo=JST).date(),
            datetime(2026, 11, 16, 11, tzinfo=JST), fence=self.publisher._account_fence(binding))
        self.assertEqual(1, count)
        self.assertIn(datetime(2026, 11, 16, 9, 0, 7, tzinfo=JST), observed)
        self.assertNotIn(datetime(2026, 11, 16, 9, 0, tzinfo=JST), observed)

    def test_short_guard_time_rolls_back_and_unknown_is_never_replayed(self):
        original = self.buffer._post
        def post(status=None):
            value = original(status)
            if value['status'] != 'draft':
                value['dueAt'] = '2026-11-16T02:01:00Z'
            return value
        self.buffer._post = post
        edit = self.buffer.edit_post
        def unknown(value):
            if value.get('saveToDraft'):
                self.buffer.calls.append(('edit_post', copy.deepcopy(value)))
                raise TimeoutError('unknown rollback')
            return edit(value)
        self.buffer.edit_post = unknown
        self.assertEqual('buffer_rollback_result_unknown', self.schedule()['reason'])
        schedule = next(row for row in json.loads(self.fence_path.read_text())['entries']
                        if row['operationId'].startswith('camp:schedule:'))
        self.assertEqual('pending_rollback', schedule['phase'])
        calls = copy.deepcopy(self.buffer.calls)
        self.assertEqual('buffer_effect_result_unknown', self.schedule()['reason'])
        self.assertEqual(calls, self.buffer.calls)

    def test_verified_rollback_attempt_two_schedules_and_posts_its_own_operation(self):
        self.publisher.settings['maxDuePolls'] = 1
        original_pending = self.buffer.pending_posts
        def full(*args):
            result = original_pending(*args)
            if self.buffer.status == 'scheduled':
                result += [self.reservation(str(i)) for i in range(3)]
            return result
        self.buffer.pending_posts = full
        self.assertEqual('deferred', self.schedule()['status'])
        self.buffer.pending_posts = original_pending
        original_post = self.buffer._post
        def next_day(status=None):
            value = original_post(status)
            if value['status'] != 'draft': value['dueAt'] = '2026-11-17T03:17:00Z'
            if value['status'] == 'sent': value['sentAt'] = '2026-11-17T03:17:03Z'
            return value
        self.buffer._post = next_day
        self.assertEqual('scheduled', self.at(self.job, datetime(2026, 11, 17, 11, tzinfo=JST))['status'])
        self.buffer.status = 'sent'; self.buffer.external = 'https://x.com/camp/status/111'
        native = self.publisher.x_client; xread = fixtures.XFake()
        self.publisher.x_client = lambda action, payload: (xread(action, payload)
                                                            if action == 'threadread'
                                                            else native(action, payload))
        self.assertEqual('verified', self.at(self.job, datetime(2026, 11, 17, 12, 18, tzinfo=JST))['status'])
        rows = json.loads(self.fence_path.read_text())['entries']
        self.assertEqual('terminal_rolled_back', next(r for r in rows if ':attempt:' not in r['operationId'] and r['operationId'].startswith('camp:schedule:'))['phase'])
        second = next(r for r in rows if r['operationId'].endswith(':attempt:2'))
        self.assertEqual(('terminal_posted', '111'), (second['phase'], second['publicPostId']))

    def test_due_day_tomorrow_uses_reservations_and_not_future_native(self):
        original = self.buffer._post
        def post(status=None):
            value = original(status)
            if value['status'] != 'draft':
                value['dueAt'] = '2026-11-17T03:17:00Z'
            return value
        self.buffer._post = post
        self.pending = [self.reservation(str(i), due='2026-11-17T01:00:00Z') for i in range(3)]
        self.assertEqual('deferred', self.schedule()['status'])
        self.assertEqual(1, sum(action == 'dayroots' for action, _ in self.native_calls))

    def test_ui_slot_within_90_seconds_defers_before_any_write(self):
        result = self.at(self.job, datetime(2026, 11, 16, 12, 16, tzinfo=JST))
        self.assertEqual('buffer_due_guard_time', result['reason'])
        self.assertEqual('2026-11-16T12:18:30+09:00', result['nextEligibleAt'])
        self.assertEqual(['preflight'], [name for name, _ in self.buffer.calls])
        self.assertEqual([], self.native_calls)

    def test_native_morning_root_defers_nearby_ui_slot(self):
        self.roots = [self.native_root(1, '2026-11-15T23:00:00Z')]
        result = self.at(self.job, datetime(2026, 11, 16, 8, 2, tzinfo=JST))
        self.assertEqual('buffer_minimum_root_gap', result['reason'])
        self.assertEqual('2026-11-16T08:08:30+09:00', result['nextEligibleAt'])
        self.assertFalse({'create_post', 'edit_post'} & {name for name, _ in self.buffer.calls})

    def test_manual_noon_reservation_defers_lunch_candidate(self):
        self.pending = [self.reservation('manual', due='2026-11-16T03:00:00Z')]
        result = self.schedule()
        self.assertEqual('buffer_minimum_root_gap', result['reason'])
        self.assertEqual('2026-11-16T12:18:30+09:00', result['nextEligibleAt'])
        self.assertFalse({'create_post', 'edit_post'} & {name for name, _ in self.buffer.calls})

    def test_actual_due_gap_conflict_rolls_back_exact_draft(self):
        # The free lunch candidate is clear; the actual evening slot conflicts
        # with a custom reservation. Both times belong to the verified UI slots.
        self.pending = [self.reservation('custom', due='2026-11-16T08:30:00Z')]
        original = self.buffer._post
        def post(status=None):
            value = original(status)
            if value['status'] != 'draft':
                value['dueAt'] = '2026-11-16T10:17:00Z'
            return value
        self.buffer._post = post
        result = self.schedule()
        self.assertEqual('buffer_minimum_root_gap', result['reason'])
        self.assertEqual('draft', result['bufferStatus'])
        self.assertEqual('draft', self.buffer.status)

    def test_missing_schedule_is_explicit_hold_without_create(self):
        self.buffer.preflight = lambda *_: {
            'id': CHANNEL, 'organizationId': fixtures.ORG, 'service': 'twitter',
            'serviceId': ACCOUNT, 'isDisconnected': False, 'isLocked': False,
            'isQueuePaused': False, 'linkShortening': {'isEnabled': False}}
        result = self.schedule()
        self.assertEqual('buffer_posting_schedule_unverified', result['reason'])
        self.assertIsNone(result['nextEligibleAt'])
        self.assertFalse({'create_post', 'edit_post'} & {name for name, _ in self.buffer.calls})

    def test_crossing_midnight_during_capacity_read_does_not_create(self):
        self.roots = []
        clock = [0]
        original = self.buffer.pending_posts
        def pending(*args):
            values = original(*args)
            clock[0] = 2
            return values
        self.buffer.pending_posts = pending
        with patch('buffer_publisher.time.monotonic', side_effect=lambda: clock[0]):
            result = self.at(
                self.job, datetime(2026, 11, 16, 23, 59, 59, tzinfo=JST))
        self.assertEqual('buffer_capacity_day_changed', result['reason'])
        self.assertFalse({'create_post', 'edit_post'} & {name for name, _ in self.buffer.calls})

    def test_incomplete_native_never_creates(self):
        self.publisher.x_client = lambda action, payload: (
            {'userId': ACCOUNT} if action == 'preflight' else {'complete': False})
        self.assertEqual('unverified', self.schedule()['status'])
        self.assertFalse({'create_post', 'edit_post'} & {x[0] for x in self.buffer.calls})

    def test_unknown_sending_never_creates(self):
        self.pending = [self.reservation('unknown', status='sending', due=None)]
        self.assertEqual('unverified', self.schedule()['status'])
        self.assertFalse({'create_post', 'edit_post'} & {x[0] for x in self.buffer.calls})

    def test_duplicate_pending_ids_never_create(self):
        self.pending = [self.reservation('same'), self.reservation('same')]
        self.assertEqual('unverified', self.schedule()['status'])
        self.assertFalse({'create_post', 'edit_post'} & {x[0] for x in self.buffer.calls})

    def test_budget_and_quota_hold_without_reads_or_mutations(self):
        self.publisher.settings['maxBufferRequestsPerPost'] = 1
        result = self.schedule()
        self.assertEqual('deferred', result['status'])
        self.assertEqual('buffer_daily_guard_budget_hold', result['reason'])
        self.assertEqual([], self.native_calls)
        self.assertEqual([], self.buffer.calls)

    def test_quota_headroom_preserves_draft_without_enqueue(self):
        for item in self.buffer.rate_limits:
            item['remaining'] = 6
        result = self.schedule()
        self.assertEqual('buffer_daily_guard_quota_or_budget_hold', result['reason'])
        self.assertEqual('draft', result['bufferStatus'])
        self.assertFalse(any(name == 'edit_post' for name, _ in self.buffer.calls))
        self.assertLessEqual(json.loads(self.marker().read_text())['bufferRequests'], 18)

    def test_known_timed_deferral_resumes_without_resetting_counters(self):
        self.roots = [self.native_root(i) for i in (1, 2, 3)]
        first = self.schedule()
        requests = json.loads(self.marker().read_text())['bufferRequests']
        self.roots = []
        original = self.buffer._post
        def post(status=None):
            value = original(status)
            if value['status'] != 'draft':
                value['dueAt'] = '2026-11-17T03:17:00Z'
            return value
        self.buffer._post = post
        before = copy.deepcopy(self.job)
        result = self.at(self.job, datetime(2026, 11, 17, 11, tzinfo=JST))
        self.assertEqual('scheduled', result['status'])
        self.assertEqual(before, self.job)
        self.assertEqual(requests + 8, json.loads(self.marker().read_text())['bufferRequests'])
        self.assertEqual(0, json.loads(self.marker().read_text())['polls'])

    def test_account_lock_is_held_during_capacity_read(self):
        original = self.buffer.pending_posts
        def checked(*args):
            path = self.root / 'buffer-publications' / ('account-' + ACCOUNT + '.flock')
            with path.open('r') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original(*args)
        self.buffer.pending_posts = checked
        self.schedule()

    def test_invalid_limit_rejected_before_provider_calls(self):
        self.publisher.settings['dailyRootLimit'] = 4
        with self.assertRaisesRegex(ValueError, 'buffer_daily_root_limit_invalid'):
            self.schedule()
        self.assertEqual([], self.buffer.calls)

    def test_missing_shared_fence_blocks_before_provider_or_mutation(self):
        self.fence_path.unlink()
        result = self.schedule()
        self.assertEqual('buffer_daily_capacity_unverified', result['reason'])
        self.assertFalse({'create_post', 'edit_post'} & {x[0] for x in self.buffer.calls})

    def test_cross_route_pending_intent_blocks_new_camp_mutation(self):
        AccountFence(self.fence_path, {'organizationId': fixtures.ORG,
                     'channelId': CHANNEL, 'xAccountId': ACCOUNT}).intent({
            'operationId': 'normal:x-approval:' + 'a' * 64, 'route': 'normal',
            'account': 'camp_gear_lab', 'channelId': CHANNEL, 'parentCount': 1,
            'dueAt': '2026-11-16T03:15:00Z', 'requestHash': 'b' * 64})
        result = self.schedule()
        self.assertEqual('buffer_daily_capacity_unverified', result['reason'])
        self.assertFalse({'create_post', 'edit_post'} & {x[0] for x in self.buffer.calls})


class PendingReaderTests(unittest.TestCase):
    def test_no_creation_window_and_complete_page_required(self):
        for page in ({'hasNextPage': False}, {'hasNextPage': True}, {}):
            transport = Transport({'data': {'posts': {'edges': [], 'pageInfo': page}}})
            api = BufferAPI('offline', transport=transport)
            if page.get('hasNextPage') is False:
                self.assertEqual([], api.pending_posts('org', CHANNEL))
            else:
                with self.assertRaises(ValueError):
                    api.pending_posts('org', CHANNEL)
            variables = transport.calls[0][2]['variables']['input']['filter']
            self.assertNotIn('createdAt', variables)
            self.assertEqual(['draft', 'scheduled', 'sending'], variables['status'])
