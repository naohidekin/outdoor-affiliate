"""Shared Gear account mutation fence. Caller must hold the account flock."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
import uuid


def _require(value, code):
    if not value:
        raise ValueError(code)


def _time(value):
    try:
        return (isinstance(value, str) and
                datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() is not None)
    except (TypeError, ValueError):
        return False


class AccountFence:
    def __init__(self, path, binding):
        self.path, self.binding = Path(path), dict(binding)
        _require(set(self.binding) == {'organizationId', 'channelId', 'xAccountId'}
                 and all(isinstance(v, str) and v for v in self.binding.values())
                 and re.fullmatch(r'[1-9][0-9]*', self.binding['xAccountId']),
                 'gearman_shared_fence_configuration_invalid')

    @staticmethod
    def _entry(value):
        valid = (isinstance(value, dict) and isinstance(value.get('operationId'), str)
                 and value['operationId'] and value.get('route') in ('normal', 'camp')
                 and value.get('account') == 'camp_gear_lab'
                 and isinstance(value.get('channelId'), str)
                 and value.get('parentCount') == 1
                 and isinstance(value.get('requestHash'), str)
                 and re.fullmatch(r'[a-f0-9]{64}', value['requestHash'])
                 and value.get('phase') in ('pending_intent', 'pending_rollback', 'accepted',
                                             'terminal_rejected', 'terminal_rolled_back',
                                             'terminal_buffer_reported_sent',
                                             'terminal_posted')
                 and (value.get('dueAt') is None or _time(value['dueAt'])))
        if value.get('phase') in ('accepted', 'pending_rollback'):
            valid = valid and isinstance(value.get('bufferPostId'), str) and bool(value['bufferPostId']) and _time(value.get('dueAt'))
        if value.get('phase') == 'terminal_posted':
            valid = valid and isinstance(value.get('publicPostId'), str) and value['publicPostId'].isdigit() and _time(value.get('actualAt'))
        if value.get('phase') == 'terminal_buffer_reported_sent':
            valid = (valid and isinstance(value.get('bufferPostId'), str) and bool(value['bufferPostId'])
                     and isinstance(value.get('reportedPostId'), str) and value['reportedPostId'].isdigit()
                     and _time(value.get('sentAt')) and isinstance(value.get('publicUrl'), str))
        return bool(valid)

    def load(self):
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            raise ValueError('gearman_shared_fence_missing') from None
        _require(stat.S_ISREG(info.st_mode) and not self.path.is_symlink()
                 and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                 and info.st_nlink == 1 and info.st_size <= 1024 * 1024,
                 'gearman_shared_fence_invalid')
        try:
            value = json.loads(self.path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError('gearman_shared_fence_invalid') from None
        _require(value.get('version') == 1 and value.get('binding') == self.binding
                 and isinstance(value.get('entries'), list) and len(value['entries']) <= 1000
                 and all(self._entry(row) and row['channelId'] == self.binding['channelId']
                         for row in value['entries']),
                 'gearman_shared_fence_invalid')
        operations, buffer_ids = set(), set()
        for row in value['entries']:
            _require(row['operationId'] not in operations, 'gearman_shared_fence_invalid')
            operations.add(row['operationId'])
            if row.get('bufferPostId') and row['phase'] not in ('terminal_rejected', 'terminal_rolled_back'):
                _require(row['bufferPostId'] not in buffer_ids, 'gearman_shared_fence_invalid')
                buffer_ids.add(row['bufferPostId'])
        return value

    def _write(self, value):
        temp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (json.dumps(value, separators=(',', ':')) + '\n').encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, self.path)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def intent(self, intent):
        state, entry = self.load(), dict(intent, phase='pending_intent')
        _require(self._entry(entry) and entry['channelId'] == self.binding['channelId'],
                 'gearman_shared_fence_intent_invalid')
        old = next((row for row in state['entries'] if row['operationId'] == entry['operationId']), None)
        if old is not None:
            _require(old == entry, 'gearman_shared_fence_conflict')
            return old
        _require(len(state['entries']) < 1000, 'gearman_shared_fence_full')
        state['entries'].append(entry)
        self._write(state)
        return entry

    def accept(self, operation_id, buffer_post_id, due_at):
        state = self.load()
        index = next((i for i, row in enumerate(state['entries'])
                      if row['operationId'] == operation_id), None)
        _require(index is not None, 'gearman_shared_fence_intent_required')
        old = state['entries'][index]
        if old['phase'] == 'accepted':
            _require(old.get('bufferPostId') == buffer_post_id and old.get('dueAt') == due_at,
                     'gearman_shared_fence_conflict')
            return old
        _require(old['phase'] == 'pending_intent' and isinstance(buffer_post_id, str)
                 and buffer_post_id and _time(due_at)
                 and (old.get('dueAt') is None or old['dueAt'] == due_at)
                 and not any(i != index and row.get('bufferPostId') == buffer_post_id
                             and row.get('phase') not in ('terminal_rejected', 'terminal_rolled_back')
                             for i, row in enumerate(state['entries'])),
                 'gearman_shared_fence_conflict')
        entry = dict(old, phase='accepted', bufferPostId=buffer_post_id, dueAt=due_at)
        state['entries'][index] = entry
        self._write(state)
        return entry

    def reject(self, operation_id, buffer_post_id):
        state = self.load()
        index = next((i for i, row in enumerate(state['entries'])
                      if row['operationId'] == operation_id), None)
        _require(index is not None, 'gearman_shared_fence_intent_required')
        old = state['entries'][index]
        if old['phase'] == 'terminal_rejected':
            _require(old.get('bufferPostId') == buffer_post_id,
                     'gearman_shared_fence_conflict')
            return old
        _require(old['phase'] == 'pending_intent' and isinstance(buffer_post_id, str)
                 and buffer_post_id, 'gearman_shared_fence_conflict')
        entry = dict(old, phase='terminal_rejected', bufferPostId=buffer_post_id)
        state['entries'][index] = entry
        self._write(state)
        return entry

    def rolled_back(self, operation_id, buffer_post_id):
        state = self.load()
        index = next((i for i, row in enumerate(state['entries'])
                      if row['operationId'] == operation_id), None)
        _require(index is not None, 'gearman_shared_fence_intent_required')
        old = state['entries'][index]
        if old['phase'] == 'terminal_rolled_back':
            _require(old.get('bufferPostId') == buffer_post_id,
                     'gearman_shared_fence_conflict')
            return old
        _require(old['phase'] == 'pending_rollback' and old.get('bufferPostId') == buffer_post_id,
                 'gearman_shared_fence_conflict')
        entry = dict(old, phase='terminal_rolled_back')
        state['entries'][index] = entry
        self._write(state)
        return entry

    def begin_rollback(self, operation_id, buffer_post_id):
        state = self.load()
        index = next((i for i, row in enumerate(state['entries'])
                      if row['operationId'] == operation_id), None)
        _require(index is not None, 'gearman_shared_fence_intent_required')
        old = state['entries'][index]
        if old['phase'] == 'pending_rollback':
            _require(old.get('bufferPostId') == buffer_post_id,
                     'gearman_shared_fence_conflict')
            return old
        _require(old['phase'] == 'accepted' and old.get('bufferPostId') == buffer_post_id,
                 'gearman_shared_fence_conflict')
        entry = dict(old, phase='pending_rollback')
        state['entries'][index] = entry
        self._write(state)
        return entry

    def posted(self, operation_id, buffer_post_id, public_post_id, actual_at):
        state = self.load()
        index = next((i for i, row in enumerate(state['entries'])
                      if row['operationId'] == operation_id), None)
        _require(index is not None, 'gearman_shared_fence_intent_required')
        old = state['entries'][index]
        if old['phase'] == 'terminal_posted':
            _require(old.get('bufferPostId') == buffer_post_id
                     and old.get('publicPostId') == public_post_id
                     and old.get('actualAt') == actual_at,
                     'gearman_shared_fence_conflict')
            return old
        _require(old['phase'] == 'accepted' and old.get('bufferPostId') == buffer_post_id
                 and isinstance(public_post_id, str) and public_post_id.isdigit()
                 and _time(actual_at), 'gearman_shared_fence_conflict')
        entry = dict(old, phase='terminal_posted', publicPostId=public_post_id,
                     actualAt=actual_at)
        state['entries'][index] = entry
        self._write(state)
        return entry
