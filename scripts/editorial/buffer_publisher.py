"""Exact-version Buffer draft/schedule adapter with fail-closed effect markers."""
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import json
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse
import warnings

from buffer_api import BufferAPI
from account_fence import AccountFence
from ledger import (fingerprint, valid_review, valid_social_images,
                    owned_article_social_image)
from social_policy_compat import require_approved_social_review
from social_publisher import SocialPublisher, _atomic, _require
from x_readback import exact_x_text


JST = timezone(timedelta(hours=9))
UTC = timezone.utc
X_UNVERIFIED_REASONS = frozenset({
    'x_media_fetch_failed', 'x_media_pixels_mismatch', 'x_media_readback_mismatch',
    'x_media_sha_mismatch', 'x_media_url_invalid', 'x_readback_mismatch',
    'x_reply_readback_mismatch',
})
GEARMAN_BINDING = {'organizationId': '6adf7fbb37d17051a678fba0',
                   'channelId': '6adfd45e2f1f5ed648e05a86',
                   'xAccountId': '1343879420470206464'}
GEARMAN_STATE_ROOT = Path('/Users/yuueikaiakabaneshounikakurinikku/Library/Application Support/CampGearLabCodex/editorial')


def _aware(value, code):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError):
        raise ValueError(code) from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed


def _iso(value):
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def deferred_result(state, now):
    """Return a known deferral while waiting; unknown effects never use this phase."""
    if state.get('phase') != 'deferred':
        return None
    result = state.get('result')
    _require(state.get('pending') is None and isinstance(result, dict)
             and result.get('status') == 'deferred' and result.get('verified') is False
             and result.get('fingerprint') == state.get('revision')
             and isinstance(result.get('reason'), str)
             and result.get('dueAt') is None, 'buffer_defer_marker_invalid')
    eligible = result.get('nextEligibleAt')
    if eligible is None or now < _aware(eligible, 'buffer_defer_marker_invalid'):
        return copy.deepcopy(result)
    return None


class BufferPublisher:
    """Schedules one approved X thread and later verifies the actual X posts."""

    def __init__(self, config, env, *, client=None, fetcher=None, x_client=None, clock=None):
        self.config, self.env = dict(config), dict(env)
        self.settings = dict(config.get('buffer') or {})
        self.root = Path(config['stateRoot'])
        self.client = client or BufferAPI(self.env.get('BUFFER_API_KEY'))
        self.image_reader = SocialPublisher(config, env, client=lambda *_: None, fetcher=fetcher)
        self.x_client = x_client or self.image_reader._node
        self.clock = clock or (lambda: datetime.now(JST))

    def preflight(self):
        _require(self.config.get('bufferPostingEnabled') is True, 'buffer_posting_disabled')
        binding = self._binding()
        channel = self.client.preflight(binding['organizationId'], binding['channelId'])
        self._check_channel(channel, binding)
        return {'verified': True, **binding}

    @staticmethod
    def _check_channel(channel, binding):
        _require(isinstance(channel, dict) and channel.get('id') == binding['channelId']
                 and channel.get('organizationId') == binding['organizationId']
                 and channel.get('service') == 'twitter'
                 and channel.get('serviceId') == binding['xAccountId'], 'buffer_binding_mismatch')
        _require(channel.get('isDisconnected') is False and channel.get('isLocked') is False
                 and channel.get('isQueuePaused') is False, 'buffer_channel_unavailable')
        _require((channel.get('linkShortening') or {}).get('isEnabled') is False,
                 'buffer_link_shortening_must_be_disabled')

    def publish(self, job, now=None):
        return self.schedule_or_check(job, now=now)

    def schedule_or_check(self, job, now=None):
        limit = self.settings.get('dailyRootLimit')
        _require(limit is None or type(limit) is int and limit == 3, 'buffer_daily_root_limit_invalid')
        binding = self._binding()
        gearman = binding == GEARMAN_BINDING or self.root == GEARMAN_STATE_ROOT
        if gearman:
            _require(binding == GEARMAN_BINDING and limit == 3,
                     'gearman_daily_guard_configuration_required')
        if limit is None:
            return self._schedule_or_check(job, now)
        gap = self.settings.get('minimumRootGapMinutes', 120)
        _require(type(gap) is int and gap >= 120, 'buffer_minimum_root_gap_invalid')
        _require(re.fullmatch(r'[1-9][0-9]*', binding['xAccountId']) is not None,
                 'buffer_binding_mismatch')
        self._private_root()
        folder = self.root / 'buffer-publications'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require(folder.stat().st_mode & 0o777 == 0o700, 'buffer_journal_not_private')
        path = folder / ('account-' + binding['xAccountId'] + '.flock')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            _require(os.fstat(lock.fileno()).st_mode & 0o777 == 0o600, 'buffer_account_lock_invalid')
            lock_started = time.monotonic()
            fcntl.flock(lock, fcntl.LOCK_EX)
            if now is not None:
                now = _aware(now, 'buffer_now_invalid') + timedelta(seconds=time.monotonic() - lock_started)
            return self._schedule_or_check(job, now)

    def _schedule_or_check(self, job, now=None):
        _require(self.config.get('bufferPostingEnabled') is True, 'buffer_posting_disabled')
        guarded = self.settings.get('dailyRootLimit') == 3
        now = _aware(self.clock() if guarded else now or self.clock(), 'buffer_now_invalid')
        started = time.monotonic()
        def effective_now():
            elapsed = now + timedelta(seconds=time.monotonic() - started)
            return max(elapsed, _aware(self.clock(), 'buffer_now_invalid')) if guarded else elapsed
        proposal, revision = self._validate(job)
        binding = self._binding()
        self._private_root()
        folder = self.root / 'buffer-publications'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require(folder.stat().st_mode & 0o777 == 0o700, 'buffer_journal_not_private')
        marker = folder / (revision + '.json')
        lock_path = folder / (revision + '.flock')
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _require(job['stage'] == 'social_approved' or marker.exists(),
                     'buffer_schedule_marker_required')
            if not marker.exists():
                require_approved_social_review(job, self.config['slack']['user_id'], self.config.get('repo'))
            state, existed = self._state(marker, revision, proposal, binding)
            if job['stage'] == 'social_scheduled':
                _require(state.get('phase') in ('scheduled', 'unverified', 'verified')
                         and isinstance(state.get('postId'), str) and state['postId']
                         and isinstance(state.get('dueAt'), str) and state['dueAt']
                         and state.get('pending') is None, 'buffer_schedule_marker_invalid')
            if state.get('phase') == 'verified':
                return copy.deepcopy(state['result'])
            if state.get('phase') == 'unverified' and isinstance(state.get('result'), dict):
                return copy.deepcopy(state['result'])
            if state.get('pending'):
                return self._unverified(state, 'buffer_effect_result_unknown')
            waiting = deferred_result(state, now)
            if waiting:
                return waiting
            needs_schedule = not state.get('dueAt')
            try:
                fence = self._account_fence(binding) if guarded else None
            except (OSError, ValueError):
                return self._terminal_hold(marker, state, 'buffer_daily_capacity_unverified')
            # Normal scheduling costs at most eight calls; each due poll can
            # require one daily preflight plus one post read. X/media readback
            # makes no Buffer calls. Rollback's ten-call branch also fits.
            verification_calls = 2 * self._poll_policy()[0] if guarded else 0
            schedule_attempt = state.get('scheduleAttempt', 1)
            required = (max(10, 8 + verification_calls) if schedule_attempt == 1
                        else 6 + verification_calls)
            if guarded and needs_schedule and not self._request_room(state, required):
                return self._defer(marker, state, 'buffer_daily_guard_budget_hold')
            next_check = _aware(state['nextCheckAt'], 'buffer_poll_marker_invalid') if state.get('nextCheckAt') else None
            if next_check and now < next_check:
                return self._result('pending', state, verified=False)
            max_polls, _ = self._poll_policy()
            if state.get('dueAt') and state.get('polls', 0) >= max_polls:
                return self._unverified(state, 'buffer_due_poll_exhausted')
            due_for_poll = _aware(state['dueAt'], 'buffer_due_at_invalid') if state.get('dueAt') else None
            if due_for_poll and now >= due_for_poll:
                self._reserve_due_attempt(marker, state, now)
            channel = None
            if self._preflight_due(state, now) or guarded and needs_schedule:
                channel = self._buffer_call(marker, state, 'preflight', binding['organizationId'],
                                            binding['channelId'])
                self._check_channel(channel, binding)
                state['preflightAt'] = now.isoformat()
                _atomic(marker, state)
            if guarded and needs_schedule:
                try:
                    slots = self._guard_slots(channel, effective_now())
                except ValueError:
                    return self._defer(marker, state, 'buffer_posting_schedule_unverified')
                wait = self._slot_wait(slots, effective_now())
                if wait:
                    return self._defer(marker, state, 'buffer_due_guard_time', next_eligible=wait)
                try:
                    count, observed, occupied = self._day_roots(
                        marker, state, binding, now.astimezone(JST).date(),
                        effective_now(), exclude_id=state.get('postId'), fence=fence)
                except Exception:
                    return self._terminal_hold(marker, state, 'buffer_daily_capacity_unverified')
                if count >= 3:
                    return self._defer(marker, state, 'buffer_daily_root_limit', now)
                checked_now = effective_now()
                if checked_now.astimezone(JST).date() != now.astimezone(JST).date():
                    return self._defer(marker, state, 'buffer_capacity_day_changed',
                                       next_eligible=checked_now + timedelta(seconds=90))
                candidate = next((slot for slot in slots if slot >= checked_now and slot not in occupied), None)
                if candidate is None:
                    return self._defer(marker, state, 'buffer_posting_schedule_no_free_slot')
                if self._gap_conflict(candidate, observed):
                    return self._defer(marker, state, 'buffer_minimum_root_gap',
                                       next_eligible=candidate + timedelta(seconds=90))
            if not state.get('postId'):
                require_approved_social_review(job, self.config['slack']['user_id'], self.config.get('repo'))
                self._validate_images(proposal)
                lookback = self.settings.get('dedupLookbackDays', 30)
                _require(isinstance(lookback, int) and 1 <= lookback <= 90, 'buffer_dedup_policy_invalid')
                posts = self._buffer_call(marker, state, 'posts', binding['organizationId'],
                                          binding['channelId'], _iso(now - timedelta(days=lookback)),
                                          _iso(now + timedelta(days=1)))
                if any(self._duplicate(post, proposal) for post in posts):
                    return self._terminal_hold(marker, state, 'buffer_duplicate_post_hold')
                if not self._mutation_quota_ready():
                    return self._terminal_hold(marker, state, 'buffer_mutation_quota_hold')
                if guarded:
                    wait = self._slot_wait(slots, effective_now())
                    if effective_now().astimezone(JST).date() != now.astimezone(JST).date():
                        return self._defer(marker, state, 'buffer_capacity_day_changed',
                                           next_eligible=effective_now() + timedelta(seconds=90))
                    if wait:
                        return self._defer(marker, state, 'buffer_due_guard_time', next_eligible=wait)
                create_input = self._create_input(proposal, binding)
                create_operation = 'camp:create:' + revision
                if fence is not None:
                    fence.intent(self._fence_intent(create_operation, binding, create_input))
                state.update(phase='create_draft', pending={'action': 'createPost'})
                _atomic(marker, state)
                try:
                    post = self._buffer_call(marker, state, 'create_post',
                                             create_input, mutation=True)
                except Exception:
                    if state.get('phase') == 'unverified' and isinstance(state.get('result'), dict):
                        return copy.deepcopy(state['result'])
                    return self._unverified(state, 'buffer_create_result_unknown')
                state.update(postId=post['id'], phase='draft_readback', pending=None)
                _atomic(marker, state)
                _require(self._matches_content(post, proposal) and post.get('status') == 'draft',
                         'buffer_draft_readback_mismatch')
                if fence is not None:
                    fence.reject(create_operation, post['id'])
            post = self._buffer_call(marker, state, 'post', state['postId'])
            if post.get('status') == 'draft':
                if guarded and not needs_schedule:
                    return self._terminal_hold(marker, state, 'buffer_scheduled_post_became_draft')
                require_approved_social_review(job, self.config['slack']['user_id'], self.config.get('repo'))
                _require(self._matches_content(post, proposal), 'buffer_draft_readback_mismatch')
                if guarded and (not self._request_room(state, max(5, 3 + verification_calls))
                                or not self._guard_quota_ready(5)):
                    return self._defer(marker, state, 'buffer_daily_guard_quota_or_budget_hold')
                if guarded:
                    wait = self._slot_wait(slots, effective_now())
                    if effective_now().astimezone(JST).date() != now.astimezone(JST).date():
                        return self._defer(marker, state, 'buffer_capacity_day_changed',
                                           next_eligible=effective_now() + timedelta(seconds=90))
                    if wait:
                        return self._defer(marker, state, 'buffer_due_guard_time', next_eligible=wait)
                if not self._mutation_quota_ready():
                    return self._terminal_hold(marker, state, 'buffer_mutation_quota_hold')
                edit_input = self._edit_input(state['postId'])
                attempt = state.get('scheduleAttempt', 1)
                _require(type(attempt) is int and 1 <= attempt <= 100,
                         'buffer_schedule_attempt_invalid')
                schedule_operation = ('camp:schedule:' + revision if attempt == 1 else
                                      'camp:schedule:' + revision + ':attempt:' + str(attempt))
                if fence is not None:
                    fence.intent(self._fence_intent(schedule_operation, binding, edit_input))
                state.update(phase='schedule', pending={'action': 'editPost'},
                             scheduleOperation=schedule_operation, scheduleAttempt=attempt)
                _atomic(marker, state)
                try:
                    edited = self._buffer_call(marker, state, 'edit_post',
                                               edit_input, mutation=True)
                    _require(self._matches_scheduled(edited, proposal), 'buffer_schedule_readback_mismatch')
                    if guarded:
                        _require(edited.get('id') == state['postId'], 'buffer_schedule_identity_mismatch')
                    post = self._buffer_call(marker, state, 'post', state['postId'])
                    _require(self._matches_scheduled(post, proposal), 'buffer_schedule_readback_mismatch')
                    if guarded:
                        _require(post.get('id') == state['postId'] and post.get('dueAt') == edited.get('dueAt'),
                                 'buffer_schedule_readback_mismatch')
                        fence.accept(schedule_operation, post['id'], post['dueAt'])
                except Exception:
                    if state.get('phase') == 'unverified' and isinstance(state.get('result'), dict):
                        return copy.deepcopy(state['result'])
                    return self._unverified(state, 'buffer_schedule_result_unknown')
                due = _aware(post.get('dueAt'), 'buffer_due_at_invalid')
                if guarded:
                    state.update(phase='capacity_check', pending={'action': 'capacity_check'},
                                 rejectedDueAt=_iso(due))
                    _atomic(marker, state)
                    if due not in slots:
                        return self._rollback_to_draft(marker, state, proposal, post,
                                                       'buffer_due_schedule_mismatch', effective_now())
                    try:
                        count, actual_observed, _ = self._day_roots(
                            marker, state, binding, due.astimezone(JST).date(),
                            effective_now(), exclude_id=state['postId'], fence=fence,
                            known_post=post)
                        reason = ('buffer_daily_root_limit' if count >= 3 else
                                  'buffer_due_guard_time' if due - effective_now() < timedelta(seconds=90)
                                  else 'buffer_minimum_root_gap' if self._gap_conflict(
                                      due, observed + actual_observed)
                                  else None)
                    except Exception:
                        reason = 'buffer_daily_capacity_unverified'
                    if reason:
                        return self._rollback_to_draft(marker, state, proposal, post, reason,
                                                       effective_now())
                state.update(phase='scheduled', pending=None, dueAt=_iso(due), nextCheckAt=_iso(due),
                             scheduledReadback=post)
                _atomic(marker, state)
                return self._result('scheduled', state, verified=False)
            if (not self._matches_content(post, proposal)
                    or post.get('status') not in ('scheduled', 'sending', 'sent')):
                return self._terminal_hold(marker, state, 'buffer_post_readback_mismatch')
            due = _aware(state.get('dueAt'), 'buffer_due_at_invalid')
            if _aware(post.get('dueAt'), 'buffer_due_at_invalid') != due:
                return self._terminal_hold(marker, state, 'buffer_due_at_changed')
            if now < due:
                return self._result('pending', state, verified=False)
            return self._poll_sent(marker, state, post, proposal, due, binding, now, fence=fence)

    def _request_room(self, state, needed):
        maximum = self.settings.get('maxBufferRequestsPerPost', 18)
        _require(type(maximum) is int and 1 <= maximum <= 18, 'buffer_request_budget_invalid')
        return maximum - state.get('bufferRequests', 0) >= needed

    @staticmethod
    def _guard_slots(channel, now):
        _require(isinstance(channel, dict) and channel.get('timezone') == 'Asia/Tokyo',
                 'buffer_posting_timezone_invalid')
        rows = channel.get('postingSchedule')
        weekdays = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
        _require(isinstance(rows, list) and len(rows) == 7, 'buffer_posting_schedule_invalid')
        by_day = {}
        for row in rows:
            _require(isinstance(row, dict) and row.get('day') in weekdays
                     and row['day'] not in by_day and type(row.get('paused')) is bool
                     and isinstance(row.get('times'), list) and len(row['times']) <= 100
                     and all(isinstance(value, str) and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value)
                             for value in row['times']), 'buffer_posting_schedule_invalid')
            by_day[row['day']] = row
        midnight = datetime.combine(now.astimezone(JST).date(), datetime.min.time(), tzinfo=JST)
        slots = []
        for offset in range(-1, 8):
            day = midnight + timedelta(days=offset)
            row = by_day[weekdays[day.weekday()]]
            if not row['paused']:
                for value in row['times']:
                    hour, minute = map(int, value.split(':'))
                    slots.append(day.replace(hour=hour, minute=minute))
        _require(any(slot >= now for slot in slots), 'buffer_posting_schedule_empty')
        return sorted(set(slots))

    @staticmethod
    def _slot_wait(slots, now):
        nearby = [slot for slot in slots if now - timedelta(seconds=90) < slot <= now + timedelta(seconds=90)]
        return max(nearby) + timedelta(seconds=90) if nearby else None

    def _gap_conflict(self, candidate, observed):
        gap = timedelta(minutes=self.settings.get('minimumRootGapMinutes', 120))
        return any(abs(candidate - value) < gap for value in observed)

    def _guard_quota_ready(self, needed):
        return (self._mutation_quota_ready() and all(
            item['remaining'] >= self.settings.get('mutationRemainingFloor', 5) + needed
            for item in self.client.rate_limits))

    def _day_roots(self, marker, state, binding, day, now, *, exclude_id=None,
                   fence=None, known_post=None):
        today = now.astimezone(JST).date()
        _require(day >= today, 'buffer_capacity_day_past')
        start = datetime.combine(day, datetime.min.time(), tzinfo=JST)
        end = start + timedelta(days=1)
        roots, observed, occupied = [], [], set()
        if day == today:
            identity = self.x_client('preflight', {})
            _require(isinstance(identity, dict) and identity.get('userId') == binding['xAccountId'],
                     'buffer_native_binding_mismatch')
            # X end_time accepts whole-second UTC only. This snapshot is complete
            # through that exact exclusive cutoff, with subsecond freshness.
            cutoff = now.replace(microsecond=0)
            native_start = start - timedelta(days=1)
            query = {'accountId': binding['xAccountId'], 'start': _iso(native_start), 'end': _iso(cutoff)}
            native = self.x_client('dayroots', query)
            _require(isinstance(native, dict) and native.get('complete') is True
                     and all(native.get(key) == value for key, value in query.items()),
                     'buffer_native_day_incomplete')
            roots = native.get('roots')
            _require(isinstance(roots, list) and len(roots) <= 100, 'buffer_native_day_incomplete')
            ids = set()
            for item in roots:
                _require(isinstance(item, dict) and isinstance(item.get('id'), str)
                         and re.fullmatch(r'[1-9][0-9]*', item['id']) is not None
                         and item['id'] not in ids, 'buffer_native_day_invalid')
                created = _aware(item.get('createdAt'), 'buffer_native_day_invalid')
                _require(native_start <= created < cutoff, 'buffer_native_day_invalid')
                ids.add(item['id'])
                observed.append(created)
        posts = self._buffer_call(marker, state, 'pending_posts', binding['organizationId'], binding['channelId'])
        _require(isinstance(posts, list) and len(posts) <= 100, 'buffer_pending_posts_invalid')
        reservations, ids = 0, set()
        for post in posts:
            _require(isinstance(post, dict) and isinstance(post.get('id'), str) and post['id']
                     and post['id'] not in ids and post.get('channelId') == binding['channelId']
                     and post.get('channelService') == 'twitter'
                     and post.get('status') in ('draft', 'scheduled', 'sending'),
                     'buffer_pending_posts_invalid')
            ids.add(post['id'])
            if post['status'] == 'draft':
                continue
            due = _aware(post.get('dueAt'), 'buffer_pending_due_invalid')
            _require(post['status'] != 'sending' and due >= now, 'buffer_pending_sending_unknown')
            if post['id'] != exclude_id and start <= due < end:
                reservations += 1
            if post['id'] != exclude_id:
                observed.append(due)
                if post.get('isCustomScheduled') is False and post.get('shareMode') == 'addToQueue':
                    occupied.add(due)
        if fence is not None:
            by_id = {post['id']: post for post in posts}
            if isinstance(known_post, dict) and known_post.get('id') == exclude_id:
                by_id[exclude_id] = known_post
            for entry in fence.load()['entries']:
                if entry['phase'] in ('pending_intent', 'pending_rollback'):
                    raise ValueError('gearman_shared_outcome_unknown')
                if entry['phase'] == 'accepted':
                    matched = by_id.get(entry.get('bufferPostId'))
                    _require(matched is not None and matched.get('status') in ('scheduled', 'sending')
                             and matched.get('dueAt') == entry.get('dueAt'),
                             'gearman_shared_fence_readback_mismatch')
                if entry['phase'] == 'terminal_posted':
                    stamp = _aware(entry.get('actualAt'), 'gearman_shared_fence_readback_mismatch')
                    if day == today and native_start <= stamp < cutoff:
                        actual = next((root for root in roots
                                       if root['id'] == entry.get('publicPostId')), None)
                        _require(actual is not None, 'gearman_shared_fence_readback_mismatch')
                    elif day == today:
                        _require(stamp < native_start, 'gearman_shared_fence_readback_mismatch')
                    elif day > today:
                        _require(stamp <= now, 'gearman_shared_fence_readback_mismatch')
                        observed.append(stamp)
                if entry['phase'] == 'terminal_buffer_reported_sent':
                    stamp = _aware(entry.get('sentAt'), 'gearman_shared_fence_readback_mismatch')
                    if day == today and native_start <= stamp < cutoff:
                        _require(any(root['id'] == entry.get('reportedPostId') for root in roots),
                                 'gearman_shared_fence_readback_mismatch')
                    elif day == today:
                        _require(stamp < native_start, 'gearman_shared_fence_readback_mismatch')
                    else:
                        _require(stamp <= now, 'gearman_shared_fence_readback_mismatch')
                        observed.append(stamp)
        native_count = sum(start <= value < end for value in observed[:len(roots)])
        return native_count + reservations, observed, occupied

    def _account_fence(self, binding):
        fence = AccountFence(self.root / 'buffer-publications' /
                             ('account-' + binding['xAccountId'] + '.cross-route.json'), binding)
        value = fence.load()
        _require(not any(row['phase'] in ('pending_intent', 'pending_rollback')
                         for row in value['entries']),
                 'gearman_shared_outcome_unknown')
        return fence

    @staticmethod
    def _fence_intent(operation_id, binding, request):
        digest = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()
        return {'operationId': operation_id, 'route': 'camp', 'account': 'camp_gear_lab',
                'channelId': binding['channelId'], 'parentCount': 1, 'dueAt': None,
                'requestHash': digest}

    def _defer(self, marker, state, reason, now=None, *, next_eligible=None):
        eligible = next_eligible.isoformat() if next_eligible else None
        if now is not None:
            eligible = (datetime.combine(now.astimezone(JST).date(), datetime.min.time(), tzinfo=JST)
                        + timedelta(days=1)).isoformat()
        result = dict(self._result('deferred', state, False), reason=reason,
                      dueAt=None, bufferStatus='draft' if state.get('postId') else 'not_created',
                      nextEligibleAt=eligible)
        state.update(phase='deferred', pending=None, dueAt=None, nextCheckAt=None, result=result)
        _atomic(marker, state)
        return result

    def _rollback_to_draft(self, marker, state, proposal, post, reason, now):
        # Official EditPostInput.saveToDraft moves a scheduled post back to draft:
        # https://developers.buffer.com/types/EditPostInput.html
        _require(post['id'] == state['postId'] and self._matches_scheduled(post, proposal),
                 'buffer_rollback_target_invalid')
        fence = self._account_fence(state['binding'])
        operation = state.get('scheduleOperation')
        _require(isinstance(operation, str) and operation,
                 'gearman_shared_fence_intent_required')
        fence.begin_rollback(operation, post['id'])
        state.update(phase='rollback_draft', pending={'action': 'saveToDraft'})
        _atomic(marker, state)
        value = dict(self._edit_input(state['postId']), saveToDraft=True)
        try:
            edited = self._buffer_call(marker, state, 'edit_post', value, mutation=True)
            _require(edited.get('id') == state['postId'] and edited.get('status') == 'draft'
                     and self._matches_content(edited, proposal),
                     'buffer_rollback_readback_mismatch')
            actual = self._buffer_call(marker, state, 'post', state['postId'])
            _require(actual.get('id') == state['postId'] and actual.get('status') == 'draft'
                     and self._matches_content(actual, proposal), 'buffer_rollback_readback_mismatch')
        except Exception:
            # Retain pending intent even for an uncertain readback; never replay.
            return self._unverified(state, 'buffer_rollback_result_unknown')
        fence.rolled_back(operation, actual['id'])
        state['scheduleAttempt'] = state.get('scheduleAttempt', 1) + 1
        state['rollbackReadback'] = actual
        if reason in ('buffer_daily_capacity_unverified', 'buffer_due_schedule_mismatch'):
            return self._terminal_hold(marker, state, reason)
        if reason in ('buffer_due_guard_time', 'buffer_minimum_root_gap'):
            return self._defer(marker, state, reason,
                               next_eligible=_aware(post['dueAt'], 'buffer_due_at_invalid') + timedelta(seconds=90))
        return self._defer(marker, state, reason, now)

    def _binding(self):
        result = {key: self.settings.get(key) for key in ('organizationId', 'channelId', 'xAccountId')}
        _require(all(isinstance(value, str) and value for value in result.values()), 'buffer_binding_unconfigured')
        return result

    def _validate(self, job):
        _require(isinstance(job, dict) and job.get('stage') in ('social_approved', 'social_scheduled'),
                 'social_approval_required')
        social, publication = job.get('social') or {}, job.get('publication') or {}
        proposal, revision = social.get('proposal') or {}, social.get('revision')
        _require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{64}', revision or '')
                 and fingerprint(proposal) == revision, 'social_revision_mismatch')
        valid_review(social.get('review'), revision)
        approval = social.get('approval') or {}
        _require(approval.get('action') == 'approved' and approval.get('revision') == revision
                 and approval.get('user_id') == self.config['slack']['user_id']
                 and isinstance(approval.get('request_id'), str) and approval['request_id'],
                 'social_owner_approval_required')
        _require(job.get('revision') == fingerprint(job.get('bundle'))
                 and publication.get('verified') is True and publication.get('revision') == job['revision']
                 and (publication.get('readback') or {}).get('verified') is True
                 and publication['readback'].get('fingerprint') == job['revision'], 'publication_unverified')
        binding = self._binding()
        proposal_binding = proposal.get('buffer') or {}
        _require(proposal.get('deliveryMode') == 'buffer_x' and proposal.get('platform') == 'x'
                 and proposal.get('targetAccountIdX') == binding['xAccountId']
                 and proposal_binding == {'organizationId': binding['organizationId'],
                                          'channelId': binding['channelId'],
                                          'schedulingPolicy': 'next_available_slot'},
                 'buffer_proposal_binding_mismatch')
        _require(isinstance(proposal.get('text'), str) and proposal['text'].strip()
                 and isinstance(proposal.get('replyText'), str) and proposal['replyText']
                 and proposal['replyText'] == proposal.get('url') == publication.get('url'),
                 'social_text_url_mismatch')
        _require(not re.search(r'https?://', proposal['text']), 'main_text_contains_url')
        _require(isinstance(proposal.get('images'), list) and 1 <= len(proposal['images']) <= 4,
                 'social_images_required')
        valid_social_images(job, proposal)
        self._validate_immutable_social_card(job, proposal)
        _require('dueAt' not in proposal and 'scheduledAt' not in proposal, 'buffer_fixed_time_not_approved')
        return proposal, revision

    @staticmethod
    def _validate_immutable_social_card(job, proposal):
        if proposal.get('supplementalArticleImage') is not None:
            try:
                image, binding = owned_article_social_image(job)
                valid = (proposal.get('supplementalArticleImage') == binding
                         and proposal.get('images') == [image])
            except (KeyError, TypeError, ValueError):
                valid = False
            _require(valid, 'social_card_immutable_binding_invalid')
            return
        bundle = job.get('bundle') or {}
        article = bundle.get('article') or {}
        manifest = (article.get('generationMeta') or {}).get('socialCard')
        cards = [item for item in (bundle.get('images') or [])
                 if isinstance(item, dict) and item.get('role') == 'social-card']
        images = proposal.get('images') or []
        _require(isinstance(manifest, dict) and len(cards) == 1 and len(images) == 1,
                 'social_card_immutable_binding_invalid')
        card, approved = cards[0], images[0]
        fields = ('url', 'finalUrl', 'sha256', 'size', 'contentType')
        _require(card.get('verified') is True and approved.get('verified') is True
                 and card.get('role') == approved.get('role') == 'social-card'
                 and all(manifest.get(key) == card.get(key) == approved.get(key) for key in fields),
                 'social_card_immutable_binding_invalid')
        digest, url = manifest.get('sha256'), manifest.get('url')
        _require(isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest)
                 and manifest.get('finalUrl') == url and manifest.get('contentType') == 'image/png'
                 and type(manifest.get('size')) is int and 0 < manifest['size'] <= 8 * 1024 * 1024,
                 'social_card_immutable_binding_invalid')
        try:
            parsed = urlparse(url)
            immutable_path = re.fullmatch(
                r'/storage/v1/object/public/editorial-social-cards/([a-f0-9]{2})/([a-f0-9]{64})\.png',
                parsed.path or '')
            valid_url = (parsed.scheme == 'https' and bool(parsed.hostname) and parsed.port is None
                         and not parsed.username and not parsed.password
                         and not parsed.query and not parsed.fragment and immutable_path is not None
                         and immutable_path.group(1) == digest[:2]
                         and immutable_path.group(2) == digest)
        except ValueError:
            valid_url = False
        _require(valid_url, 'social_card_immutable_binding_invalid')

    def _private_root(self):
        _require(self.root.is_dir() and self.root.stat().st_mode & 0o777 == 0o700,
                 'social_root_not_private')

    def _state(self, marker, revision, proposal, binding):
        if marker.exists():
            _require(not marker.is_symlink() and marker.stat().st_mode & 0o777 == 0o600,
                     'buffer_journal_invalid')
            state = json.loads(marker.read_text())
            _require(state.get('revision') == revision and state.get('proposalFingerprint') == fingerprint(proposal)
                     and state.get('binding') == binding,
                     'buffer_journal_mismatch')
            return state, True
        state = {'revision': revision, 'proposalFingerprint': fingerprint(proposal), 'binding': binding,
                 'dueAt': None, 'imageBindings': [
                     {key: image.get(key) for key in ('url', 'finalUrl', 'contentType', 'size', 'sha256')}
                     for image in proposal['images']], 'phase': 'dedup', 'pending': None,
                 'polls': 0, 'lastPollAt': None}
        state['preflightAt'] = None
        state['nextCheckAt'] = None
        state['bufferRequests'] = 0
        state['sharedRateLimits'] = []
        _atomic(marker, state)
        return state, False

    def _mutation_quota_ready(self):
        floor = self.settings.get('mutationRemainingFloor', 5)
        limits = getattr(self.client, 'rate_limits', None)
        _require(isinstance(floor, int) and 1 <= floor <= 100, 'buffer_mutation_floor_invalid')
        return (isinstance(limits, list) and {item.get('window') for item in limits} ==
                {900, 86400, 2592000} and all(item.get('remaining', 0) > floor for item in limits))

    def _buffer_call(self, marker, state, method, *args, mutation=False):
        maximum = self.settings.get('maxBufferRequestsPerPost', 18)
        _require(isinstance(maximum, int) and 1 <= maximum <= 18, 'buffer_request_budget_invalid')
        _require(state.get('bufferRequests', 0) < maximum, 'buffer_request_budget_exhausted')
        if mutation:
            _require(self._mutation_quota_ready(), 'buffer_mutation_quota_hold')
        state['bufferRequests'] = state.get('bufferRequests', 0) + 1
        _atomic(marker, state)
        try:
            return getattr(self.client, method)(*args)
        except ValueError as error:
            if str(error) == 'buffer_rate_limited':
                result = self._unverified(state, 'buffer_rate_limited')
                state.update(phase='unverified', pending=None, result=result)
            raise
        finally:
            limits = getattr(self.client, 'rate_limits', None)
            if isinstance(limits, list):
                state['sharedRateLimits'] = copy.deepcopy(limits)
            retry = getattr(self.client, 'retry_after', None)
            state['retryAfter'] = retry if isinstance(retry, int) else None
            _atomic(marker, state)

    @staticmethod
    def _preflight_due(state, now):
        if not state.get('preflightAt'):
            return True
        return _aware(state['preflightAt'], 'buffer_preflight_marker_invalid').astimezone(JST).date() != now.astimezone(JST).date()

    def _validate_images(self, proposal):
        for image in proposal['images']:
            self.image_reader._image_bytes(image)

    @staticmethod
    def _assets(proposal):
        return [{'image': {'url': image['url'], 'thumbnailUrl': image['url'],
                           'metadata': {'altText': image.get('alt', '')}}} for image in proposal['images']]

    def _thread(self, proposal):
        return [{'text': proposal['text'], 'assets': self._assets(proposal)},
                {'text': proposal['replyText'], 'assets': []}]

    def _create_input(self, proposal, binding):
        return {'channelId': binding['channelId'], 'text': proposal['text'], 'assets': self._assets(proposal),
                'metadata': {'twitter': {'isAiGenerated': False, 'thread': self._thread(proposal)}},
                'mode': 'addToQueue', 'schedulingType': 'automatic',
                'needsApproval': False, 'saveToDraft': True, 'aiAssisted': True,
                'source': 'camp-editorial-slack'}

    @staticmethod
    def _edit_input(post_id):
        return {'id': post_id, 'mode': 'addToQueue', 'saveToDraft': False,
                'schedulingType': 'automatic', 'source': 'camp-editorial-slack'}

    @staticmethod
    def _asset_urls(items):
        if not isinstance(items, list):
            return None
        return [item.get('source') for item in items if isinstance(item, dict)]

    def _matches_content(self, post, proposal):
        if not isinstance(post, dict) or post.get('channelId') != self.settings.get('channelId'):
            return False
        if post.get('channelService') != 'twitter' or post.get('text') != proposal['text']:
            return False
        if self._asset_urls(post.get('assets')) != [item['url'] for item in proposal['images']]:
            return False
        metadata = post.get('metadata') or {}
        thread = metadata.get('thread')
        if not isinstance(thread, list) or len(thread) != 2:
            return False
        if [item.get('text') for item in thread] != [proposal['text'], proposal['replyText']]:
            return False
        if (self._asset_urls(thread[0].get('assets')) != [item['url'] for item in proposal['images']]
                or self._asset_urls(thread[1].get('assets')) != []):
            return False
        return True

    def _duplicate(self, post, proposal):
        if (not isinstance(post, dict) or post.get('channelId') != self.settings.get('channelId')
                or post.get('channelService') != 'twitter'):
            return False
        if post.get('status') not in ('draft', 'scheduled', 'sending', 'sent'):
            return False
        if self._matches_content(post, proposal):
            return True
        thread = (post.get('metadata') or {}).get('thread')
        texts = [post.get('text')]
        if isinstance(thread, list):
            texts.extend(item.get('text') for item in thread if isinstance(item, dict))
        return any(self._text_contains_exact_url(text, proposal['url']) for text in texts)

    @staticmethod
    def _text_contains_exact_url(text, expected):
        if not isinstance(text, str):
            return False
        trailing = '.,;:!?)]}>"\'、。！？）】」』'
        return any(token.rstrip(trailing) == expected
                   for token in re.findall(r'https?://[^\s<>]+', text))

    def _matches_scheduled(self, post, proposal):
        if not self._matches_content(post, proposal) or post.get('status') != 'scheduled':
            return False
        try:
            return _aware(post.get('dueAt'), 'buffer_due_at_invalid') is not None
        except ValueError:
            return False

    def _poll_policy(self):
        max_polls = self.settings.get('maxDuePolls', 3)
        interval = self.settings.get('duePollIntervalSeconds', 1800)
        _require(isinstance(max_polls, int) and 1 <= max_polls <= 10
                 and isinstance(interval, int) and 60 <= interval <= 86400, 'buffer_poll_policy_invalid')
        return max_polls, interval

    def _reserve_due_attempt(self, marker, state, now):
        _, interval = self._poll_policy()
        state['polls'] = state.get('polls', 0) + 1
        state['lastPollAt'] = now.isoformat()
        state['nextCheckAt'] = (now + timedelta(seconds=interval)).isoformat()
        _atomic(marker, state)

    def _poll_sent(self, marker, state, post, proposal, due, binding, now, fence=None):
        state['lastStatus'] = post.get('status')
        _atomic(marker, state)
        if post.get('status') in ('scheduled', 'sending'):
            return self._result('pending', state, verified=False)
        _require(post.get('status') == 'sent', 'buffer_post_failed')
        result = self._verify_x(post, proposal, binding)
        if result.get('verified') is not True:
            state.update(phase='unverified', result=result)
            _atomic(marker, state)
            return result
        if fence is not None:
            operation = state.get('scheduleOperation') or 'camp:schedule:' + state['revision']
            fence.posted(operation, post['id'], result['mainId'],
                         _iso(_aware(post.get('sentAt'), 'buffer_sent_at_invalid')))
        state.update(phase='verified', pending=None, result=result)
        _atomic(marker, state)
        return result

    def _verify_x(self, post, proposal, binding):
        link = post.get('externalLink')
        match = re.fullmatch(r'https://(?:www\.)?x\.com/[^/]+/status/([1-9][0-9]*)', link or '')
        if self.x_client is None or not match:
            return {'status': 'unverified', 'verified': False, 'reason': 'x_readback_unavailable',
                    'bufferPostId': post.get('id'), 'bufferStatus': post.get('status')}
        main, candidates, reply_ids = None, [], []
        try:
            readback = self.x_client('threadread', {'id': match.group(1)})
            main = readback['main']
            replies = readback.get('replies')
            if replies is None and isinstance(readback.get('reply'), dict):
                replies = [readback['reply']]
            reply_ids = [item['id'] for item in (replies or [])
                         if isinstance(item, dict) and isinstance(item.get('id'), str)]
            candidates = [item for item in (replies or []) if
                          item.get('authorId') == binding['xAccountId']
                          and item.get('replyTo') == main.get('id')
                          and item.get('mediaKeys') == []
                          and exact_x_text(item, proposal['replyText'])]
            _require(len(candidates) == 1, 'x_reply_readback_mismatch')
            reply = candidates[0]
            media = self._verify_x_media(readback.get('media'), proposal)
            ok = (main.get('id') == match.group(1) and main.get('authorId') == binding['xAccountId']
                  and exact_x_text(main, proposal['text'])
                  and isinstance(main.get('mediaKeys'), list)
                  and main['mediaKeys'] == [item['mediaKey'] for item in media])
            _require(ok, 'x_readback_mismatch')
        except Exception as error:
            reason = str(error) if str(error) in X_UNVERIFIED_REASONS else 'x_readback_unavailable'
            result = {'status': 'unverified', 'verified': False, 'reason': reason,
                      'bufferPostId': post.get('id'), 'bufferStatus': post.get('status')}
            if isinstance(main, dict) and isinstance(main.get('id'), str):
                result['mainId'] = main['id']
            result['replyCandidateIds'] = reply_ids
            return result
        return {'status': 'verified', 'verified': True, 'fingerprint': fingerprint(proposal),
                'accountId': binding['xAccountId'], 'bufferPostId': post['id'],
                'mainId': main['id'], 'replyId': reply['id'],
                'readback': {'verified': True, 'fingerprint': fingerprint(proposal),
                             'accountId': binding['xAccountId'], 'main': main, 'reply': reply,
                             'media': {'verified': True, 'items': media}}}

    def _verify_x_media(self, media, proposal):
        _require(isinstance(media, list) and len(media) == len(proposal['images']),
                 'x_media_readback_mismatch')
        verified = []
        for actual, approved in zip(media, proposal['images']):
            _require(isinstance(actual, dict) and isinstance(actual.get('mediaKey'), str)
                     and actual.get('type') == 'photo', 'x_media_readback_mismatch')
            parsed = urlparse(actual.get('url', ''))
            _require(parsed.scheme == 'https' and parsed.hostname == 'pbs.twimg.com'
                     and parsed.port is None and not parsed.username and not parsed.fragment,
                     'x_media_url_invalid')
            response = self.image_reader.fetcher.request(
                actual['url'], {'Accept': 'image/*', 'Cache-Control': 'no-cache'})
            body = response.get('body')
            final = urlparse(response.get('url', ''))
            _require(isinstance(body, bytes) and 0 < len(body) <= 8 * 1024 * 1024
                     and final.scheme == 'https' and final.hostname == 'pbs.twimg.com'
                     and final.port is None and not final.username, 'x_media_fetch_failed')
            source, _ = self.image_reader._image_bytes(approved)
            actual_sha = hashlib.sha256(body).hexdigest()
            if actual_sha == approved['sha256']:
                identity = {'kind': 'byte_sha256', 'approvedSha256': approved['sha256']}
            else:
                try:
                    expected_size, expected_pixels = self._decode_rgba(source)
                    actual_size, actual_pixels = self._decode_rgba(body)
                    _require(expected_size == actual_size and expected_pixels == actual_pixels,
                             'x_media_pixels_mismatch')
                    pixel_sha = hashlib.sha256(actual_pixels).hexdigest()
                except Exception:
                    try:
                        identity = self._jpeg_encoding_identity(source, body, approved['sha256'])
                    except Exception:
                        raise ValueError('x_media_pixels_mismatch') from None
                else:
                    identity = {'kind': 'decoded_rgba_sha256',
                                'approvedSha256': approved['sha256'],
                                'pixelSha256': pixel_sha, 'width': actual_size[0],
                                'height': actual_size[1]}
            verified.append({'mediaKey': actual['mediaKey'], 'url': actual['url'],
                             'actualSha256': actual_sha, 'identity': identity})
        return verified

    @staticmethod
    def _decode_rgba(body):
        try:
            from PIL import Image
        except ImportError:
            raise ValueError('x_media_decoder_unavailable') from None
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                _require(getattr(image, 'n_frames', 1) == 1
                         and not getattr(image, 'is_animated', False)
                         and 0 < image.width <= 8192 and 0 < image.height <= 8192
                         and image.width * image.height <= 16 * 1024 * 1024,
                         'x_media_dimensions_invalid')
                image.load()
                rgba = image.convert('RGBA')
                return rgba.size, rgba.tobytes()

    @staticmethod
    def _jpeg_encoding_identity(source, actual, approved_sha):
        try:
            from PIL import Image, JpegImagePlugin
        except ImportError:
            raise ValueError('x_media_decoder_unavailable') from None

        def bounded(image):
            _require(getattr(image, 'n_frames', 1) == 1
                     and not getattr(image, 'is_animated', False)
                     and 0 < image.width <= 8192 and 0 < image.height <= 8192
                     and image.width * image.height <= 16 * 1024 * 1024,
                     'x_media_dimensions_invalid')

        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(actual)) as native:
                bounded(native)
                _require(native.format == 'JPEG', 'x_media_jpeg_required')
                sampling = JpegImagePlugin.get_sampling(native)
                tables = native.quantization
                _require(type(sampling) is int and sampling in (0, 1, 2)
                         and isinstance(tables, dict) and 1 <= len(tables) <= 4,
                         'x_media_jpeg_parameters_invalid')
                normalized = []
                for key in sorted(tables):
                    table = tables[key]
                    _require(type(key) is int and 0 <= key <= 3
                             and isinstance(table, (list, tuple)) and len(table) == 64
                             and all(type(value) is int and 1 <= value <= 255 for value in table),
                             'x_media_jpeg_parameters_invalid')
                    normalized.append([key, list(table)])
                native.load()
                native_rgba = native.convert('RGBA')
                native_size, native_pixels = native_rgba.size, native_rgba.tobytes()

            with Image.open(BytesIO(source)) as approved:
                bounded(approved)
                approved.load()
                approved_rgba = approved.convert('RGBA')
                _require(approved_rgba.size == native_size
                         and approved_rgba.getchannel('A').getextrema() == (255, 255),
                         'x_media_jpeg_source_invalid')
                output = BytesIO()
                approved_rgba.convert('RGB').save(
                    output, format='JPEG', qtables=tables, subsampling=sampling)

            with Image.open(BytesIO(output.getvalue())) as reproduced:
                bounded(reproduced)
                _require(reproduced.format == 'JPEG' and reproduced.size == native_size,
                         'x_media_jpeg_reproduction_mismatch')
                reproduced.load()
                reproduced_pixels = reproduced.convert('RGBA').tobytes()
                _require(reproduced_pixels == native_pixels,
                         'x_media_jpeg_reproduction_mismatch')

        quantization_sha = hashlib.sha256(json.dumps(
            normalized, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
        return {'kind': 'jpeg_encoding_reproduced', 'approvedSha256': approved_sha,
                'pixelSha256': hashlib.sha256(native_pixels).hexdigest(),
                'width': native_size[0], 'height': native_size[1],
                'quantizationSha256': quantization_sha, 'subsampling': sampling}

    @staticmethod
    def _result(status, state, verified):
        return {'status': status, 'verified': verified, 'fingerprint': state['revision'],
                'bufferPostId': state.get('postId'), 'dueAt': state['dueAt'],
                'bufferStatus': state.get('lastStatus', 'scheduled')}

    @staticmethod
    def _unverified(state, reason):
        return {'status': 'unverified', 'verified': False, 'reason': reason,
                'fingerprint': state['revision'], 'bufferPostId': state.get('postId'),
                'dueAt': state['dueAt']}

    def _terminal_hold(self, marker, state, reason):
        result = self._unverified(state, reason)
        state.update(phase='unverified', pending=None, result=result)
        _atomic(marker, state)
        return result
