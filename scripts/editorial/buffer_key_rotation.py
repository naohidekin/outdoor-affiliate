"""Read-only Buffer key validation and one-shot atomic credential rotation."""
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from buffer_api import BufferAPI, POST_FIELDS


KEY_PATTERN = re.compile(r'[A-Za-z0-9_.:/+=-]{16,2048}')
X_POST = re.compile(r'https://(?:www\.)?x\.com/[^/]+/status/[1-9][0-9]*')
JST = timezone(timedelta(hours=9))
PREPARED_MAX_BYTES = 1024 * 1024


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def _target(config):
    repo = Path(config.get('repo', '')).resolve()
    configured = Path(config.get('bufferEnvFile', ''))
    _require(repo.is_absolute() and configured.is_absolute(), 'buffer_rotation_target_invalid')
    dest = configured.parent.resolve() / configured.name
    _require(dest == repo / '.env.buffer.local', 'buffer_rotation_target_invalid')
    try:
        info = dest.lstat()
    except OSError:
        raise ValueError('buffer_rotation_target_invalid') from None
    _require(stat.S_ISREG(info.st_mode) and not dest.is_symlink()
             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
             and info.st_uid == os.geteuid() and 0 < info.st_size <= 4096,
             'buffer_rotation_target_invalid')
    try:
        raw = dest.read_bytes()
    except OSError:
        raise ValueError('buffer_rotation_target_invalid') from None
    match = re.fullmatch(rb'BUFFER_API_KEY=([A-Za-z0-9_.:/+=-]{16,2048})\n', raw)
    _require(match is not None, 'buffer_rotation_target_invalid')
    return dest, match.group(1).decode('ascii')


def _assets(value):
    _require(isinstance(value, list), 'buffer_rotation_snapshot_invalid')
    result = []
    for item in value:
        _require(isinstance(item, dict) and isinstance(item.get('source'), str),
                 'buffer_rotation_snapshot_invalid')
        result.append({key: item.get(key) for key in
                       ('id', 'type', 'mimeType', 'source', 'thumbnail')})
    return result


def _normalize_post(value):
    _require(isinstance(value, dict) and isinstance(value.get('id'), str) and value['id'],
             'buffer_rotation_snapshot_invalid')
    thread = (value.get('metadata') or {}).get('thread')
    _require(thread is None or isinstance(thread, list) and len(thread) <= 20,
             'buffer_rotation_snapshot_invalid')
    normalized_thread = []
    for item in thread or []:
        _require(isinstance(item, dict) and isinstance(item.get('text'), str),
                 'buffer_rotation_snapshot_invalid')
        normalized_thread.append({'text': item['text'], 'assets': _assets(item.get('assets'))})
    status = value.get('status')
    _require(status in ('draft', 'scheduled', 'sending', 'sent')
             and isinstance(value.get('channelId'), str)
             and value.get('channelService') == 'twitter'
             and isinstance(value.get('text'), str), 'buffer_rotation_snapshot_invalid')
    due = value.get('dueAt')
    _require(due is None or isinstance(due, str), 'buffer_rotation_snapshot_invalid')
    sent, link = value.get('sentAt'), value.get('externalLink')
    _require(sent is None or isinstance(sent, str), 'buffer_rotation_snapshot_invalid')
    _require(link is None or isinstance(link, str), 'buffer_rotation_snapshot_invalid')
    return {'id': value['id'], 'channelId': value['channelId'],
            'channelService': value['channelService'], 'status': status,
            'text': value['text'], 'dueAt': due, 'sentAt': sent,
            'externalLink': link, 'assets': _assets(value.get('assets')),
            'threadCount': (value.get('metadata') or {}).get('threadCount'),
            'thread': normalized_thread, 'shareMode': value.get('shareMode'),
            'isCustomScheduled': value.get('isCustomScheduled')}


def _channel(channel, binding):
    _require(isinstance(channel, dict) and channel.get('id') == binding['channelId']
             and channel.get('organizationId') == binding['organizationId']
             and channel.get('service') == 'twitter'
             and channel.get('serviceId') == binding['xAccountId'],
             'buffer_rotation_binding_mismatch')
    _require(channel.get('isDisconnected') is False and channel.get('isLocked') is False
             and channel.get('isQueuePaused') is False
             and (channel.get('linkShortening') or {}).get('isEnabled') is False,
             'buffer_rotation_channel_unavailable')


def _pending_posts(client, binding):
    if hasattr(client, 'pending_posts'):
        values = client.pending_posts(binding['organizationId'], binding['channelId'])
    else:
        data = client.execute("""query BufferRotationQueue($input: PostsInput!) {
          posts(input: $input, first: 100) {
            edges { node { %s } }
            pageInfo { hasNextPage }
          }
        }""" % POST_FIELDS, {'input': {'organizationId': binding['organizationId'],
            'filter': {'channelIds': [binding['channelId']],
                       'status': ['draft', 'scheduled', 'sending']}}})
        result = data.get('posts') if isinstance(data, dict) else None
        _require(isinstance(result, dict)
                 and (result.get('pageInfo') or {}).get('hasNextPage') is False,
                 'buffer_rotation_queue_unbounded')
        edges = result.get('edges')
        _require(isinstance(edges, list), 'buffer_rotation_snapshot_invalid')
        values = [edge.get('node') for edge in edges if isinstance(edge, dict)]
        _require(len(values) == len(edges), 'buffer_rotation_snapshot_invalid')
    _require(isinstance(values, list) and len(values) <= 100,
             'buffer_rotation_queue_unbounded')
    return values


def _snapshot(client, binding, tracked_ids=()):
    channel = client.preflight(binding['organizationId'], binding['channelId'])
    _channel(channel, binding)
    pending = {}
    for value in _pending_posts(client, binding):
        normalized = _normalize_post(value)
        _require(normalized['channelId'] == binding['channelId'],
                 'buffer_rotation_snapshot_invalid')
        _require(normalized['status'] in ('draft', 'scheduled', 'sending'),
                 'buffer_rotation_snapshot_invalid')
        _require(normalized['id'] not in pending, 'buffer_rotation_snapshot_invalid')
        pending[normalized['id']] = normalized
    ids = set(pending) | set(tracked_ids)
    _require(all(isinstance(value, str) and value for value in ids),
             'buffer_rotation_snapshot_invalid')
    result = []
    for post_id in sorted(ids):
        readback = _normalize_post(client.post(post_id))
        if post_id in pending:
            _require(readback == pending[post_id], 'buffer_rotation_snapshot_invalid')
        result.append(readback)
    return result


def _compare(before, after, sent_progress_verifier=None):
    _require([item['id'] for item in before] == [item['id'] for item in after],
             'buffer_rotation_queue_mismatch')
    immutable = ('id', 'channelId', 'channelService', 'text', 'dueAt', 'assets', 'thread')
    immutable += ('threadCount', 'shareMode', 'isCustomScheduled')
    progress = {('scheduled', 'sending'), ('scheduled', 'sent'), ('sending', 'sent')}
    for old, new in zip(before, after):
        _require(all(old[key] == new[key] for key in immutable),
                 'buffer_rotation_queue_mismatch')
        if old['status'] == new['status']:
            _require(old['sentAt'] == new['sentAt'] and old['externalLink'] == new['externalLink'],
                     'buffer_rotation_queue_mismatch')
        else:
            _require((old['status'], new['status']) in progress,
                     'buffer_rotation_queue_mismatch')
            if new['status'] == 'sent':
                _require(isinstance(new['sentAt'], str) and new['sentAt']
                         and isinstance(new['externalLink'], str)
                         and X_POST.fullmatch(new['externalLink']) is not None,
                         'buffer_rotation_queue_mismatch')
                _require(sent_progress_verifier is not None
                         and sent_progress_verifier(old, new) is True,
                         'buffer_rotation_sent_reconciliation_required')
            else:
                raise ValueError('buffer_rotation_sent_reconciliation_required')


def atomic_replace_env(dest, key, *, replace=os.replace):
    """Fsync one 0600 same-directory candidate inode, then atomically rename it."""
    _require(isinstance(key, str) and KEY_PATTERN.fullmatch(key) is not None,
             'buffer_rotation_key_invalid')
    dest = Path(dest)
    stage = dest.parent / ('.buffer-key-rotation-' + secrets.token_hex(16))
    fd = None
    try:
        fd = os.open(str(stage), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        payload = ('BUFFER_API_KEY=' + key + '\n').encode('ascii')
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError('short write')
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = None
        replace(str(stage), str(dest))
        directory = os.open(str(dest.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        info = dest.lstat()
        _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                 and info.st_nlink == 1 and info.st_uid == os.geteuid(),
                 'buffer_rotation_replace_unknown')
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            stage.unlink()
        except FileNotFoundError:
            pass
        raise ValueError('buffer_rotation_replace_unknown') from None


def _write_marker(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(path.parent.is_dir() and not path.parent.is_symlink()
             and stat.S_IMODE(path.parent.stat().st_mode) == 0o700,
             'buffer_rotation_marker_invalid')
    stage = path.parent / ('.rotation-marker-' + secrets.token_hex(12))
    fd = None
    try:
        fd = os.open(str(stage), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        body = (_canonical(value) + '\n').encode('utf-8')
        offset = 0
        while offset < len(body):
            written = os.write(fd, body[offset:])
            if written <= 0:
                raise OSError('short marker write')
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(str(stage), str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            stage.unlink()
        except FileNotFoundError:
            pass
        raise ValueError('buffer_rotation_marker_unknown') from None


def _normalized_baseline(value):
    _require(isinstance(value, list) and len(value) <= 100,
             'buffer_rotation_prepared_invalid')
    result = []
    for item in value:
        _require(isinstance(item, dict), 'buffer_rotation_prepared_invalid')
        rebuilt = _normalize_post({
            'id': item.get('id'), 'channelId': item.get('channelId'),
            'channelService': item.get('channelService'), 'status': item.get('status'),
            'text': item.get('text'), 'dueAt': item.get('dueAt'),
            'sentAt': item.get('sentAt'), 'externalLink': item.get('externalLink'),
            'assets': item.get('assets'), 'shareMode': item.get('shareMode'),
            'isCustomScheduled': item.get('isCustomScheduled'),
            'metadata': {'threadCount': item.get('threadCount'),
                         'thread': item.get('thread')},
        })
        _require(rebuilt == item, 'buffer_rotation_prepared_invalid')
        result.append(rebuilt)
    _require([item['id'] for item in result] == sorted({item['id'] for item in result}),
             'buffer_rotation_prepared_invalid')
    return result


def _read_prepared(path):
    if not path.exists():
        return None
    try:
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode) and not path.is_symlink()
                 and stat.S_IMODE(info.st_mode) == 0o600
                 and info.st_uid == os.geteuid()
                 and 0 < info.st_size <= PREPARED_MAX_BYTES,
                 'buffer_rotation_prepared_invalid')
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        raise ValueError('buffer_rotation_prepared_invalid') from None
    required = {'schemaVersion', 'phase', 'target', 'binding', 'originalIdentity',
                'oldKeySha256', 'baselineDigest', 'baseline', 'priorMarkerDigest',
                'preparedAt'}
    _require(isinstance(value, dict) and set(value) == required
             and value.get('schemaVersion') == 1 and value.get('phase') == 'prepared'
             and isinstance(value.get('target'), str)
             and isinstance(value.get('binding'), dict)
             and isinstance(value.get('originalIdentity'), dict)
             and re.fullmatch(r'[a-f0-9]{64}', str(value.get('oldKeySha256'))) is not None
             and re.fullmatch(r'[a-f0-9]{64}', str(value.get('baselineDigest'))) is not None
             and (value.get('priorMarkerDigest') is None
                  or re.fullmatch(r'[a-f0-9]{64}', str(value['priorMarkerDigest'])) is not None)
             and isinstance(value.get('preparedAt'), str),
             'buffer_rotation_prepared_invalid')
    value['baseline'] = _normalized_baseline(value['baseline'])
    _require(hashlib.sha256(_canonical(value['baseline']).encode()).hexdigest()
             == value['baselineDigest'], 'buffer_rotation_prepared_invalid')
    return value


def _file_identity(path):
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            raw = b''
            while len(raw) <= 4096:
                chunk = os.read(fd, 4097 - len(raw))
                if not chunk:
                    break
                raw += chunk
            after = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError:
        raise ValueError('buffer_rotation_cas_mismatch') from None
    _require(before.st_dev == after.st_dev and before.st_ino == after.st_ino
             and stat.S_ISREG(after.st_mode) and stat.S_IMODE(after.st_mode) == 0o600
             and after.st_nlink == 1 and after.st_uid == os.geteuid() and len(raw) <= 4096,
             'buffer_rotation_cas_mismatch')
    return {'device': after.st_dev, 'inode': after.st_ino,
            'contentSha256': hashlib.sha256(raw).hexdigest()}


class RotationSession:
    """Hold runtime.flock from old-key snapshot through one candidate decision."""

    def __init__(self, config_path, *, client_factory=BufferAPI, now=None,
                 atomic_replace=atomic_replace_env, sent_progress_verifier=None):
        self.consumed = False
        self.lock = None
        self.atomic_replace = atomic_replace
        self.sent_progress_verifier = sent_progress_verifier
        try:
            config_path = Path(config_path)
            config = json.loads(config_path.read_text())
            root = Path(config.get('stateRoot', ''))
            _require(root.is_absolute() and root.is_dir() and not root.is_symlink()
                     and stat.S_IMODE(root.stat().st_mode) == 0o700,
                     'buffer_rotation_state_invalid')
            self.root = root
            lock_fd = os.open(str(root / 'runtime.flock'),
                              os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self.lock = os.fdopen(lock_fd, 'a+')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.rotation_marker = root / 'buffer-key-rotations' / 'latest.json'
            prior = None
            if self.rotation_marker.exists():
                info = self.rotation_marker.lstat()
                _require(stat.S_ISREG(info.st_mode) and not self.rotation_marker.is_symlink()
                         and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 65536,
                         'buffer_rotation_marker_invalid')
                prior = json.loads(self.rotation_marker.read_text())
                _require(isinstance(prior, dict), 'buffer_rotation_marker_invalid')
                _require(prior.get('phase') not in ('inflight', 'unknown', 'validation_unknown'),
                         'buffer_rotation_reconciliation_required')
            prior_digest = (hashlib.sha256(_canonical(prior).encode()).hexdigest()
                            if prior is not None else None)
            self.prepared_receipt = root / 'buffer-key-rotations' / 'prepared.json'
            self.dest, old_key = _target(config)
            journals = root / 'buffer-publications'
            if journals.exists():
                _require(journals.is_dir() and not journals.is_symlink(),
                         'buffer_rotation_journal_invalid')
                for marker in journals.glob('*.json'):
                    _require(not marker.is_symlink() and marker.stat().st_size <= 1024 * 1024,
                             'buffer_rotation_journal_invalid')
                    state = json.loads(marker.read_text())
                    _require(isinstance(state, dict) and not state.get('pending'),
                             'buffer_rotation_unknown_hold')
            settings = config.get('buffer') or {}
            self.binding = {key: settings.get(key) for key in
                            ('organizationId', 'channelId', 'xAccountId')}
            _require(all(isinstance(value, str) and value for value in self.binding.values()),
                     'buffer_rotation_binding_mismatch')
            self.now = now or datetime.now(JST)
            _require(isinstance(self.now, datetime) and self.now.tzinfo is not None
                     and self.now.utcoffset() is not None, 'buffer_rotation_time_invalid')
            self.client_factory = client_factory
            self.original_identity = _file_identity(self.dest)
            old_key_sha256 = hashlib.sha256(old_key.encode('ascii')).hexdigest()
            _require(self.original_identity['contentSha256'] == hashlib.sha256(
                ('BUFFER_API_KEY=' + old_key + '\n').encode('ascii')).hexdigest(),
                'buffer_rotation_cas_mismatch')
            prepared = _read_prepared(self.prepared_receipt)
            if prepared is not None and prepared['priorMarkerDigest'] == prior_digest:
                _require(prepared['target'] == str(self.dest)
                         and prepared['binding'] == self.binding
                         and prepared['originalIdentity'] == self.original_identity
                         and prepared['oldKeySha256'] == old_key_sha256,
                         'buffer_rotation_prepared_mismatch')
                self.baseline = prepared['baseline']
                self.baseline_digest = prepared['baselineDigest']
            else:
                self.baseline = _snapshot(client_factory(old_key), self.binding)
                self.baseline_digest = hashlib.sha256(
                    _canonical(self.baseline).encode()).hexdigest()
                prepared = {'schemaVersion': 1, 'phase': 'prepared',
                    'target': str(self.dest), 'binding': self.binding,
                    'originalIdentity': self.original_identity,
                    'oldKeySha256': old_key_sha256,
                    'baselineDigest': self.baseline_digest, 'baseline': self.baseline,
                    'priorMarkerDigest': prior_digest,
                    'preparedAt': self.now.astimezone(JST).isoformat()}
                _require(len((_canonical(prepared) + '\n').encode('utf-8'))
                         <= PREPARED_MAX_BYTES, 'buffer_rotation_prepared_too_large')
                _write_marker(self.prepared_receipt, prepared)
            self.old_key_digest = bytes.fromhex(old_key_sha256)
        except (BlockingIOError, OSError):
            self.close()
            raise ValueError('buffer_rotation_lock_unavailable') from None
        except ValueError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ValueError('buffer_rotation_prepare_unknown') from None

    def commit(self, candidate, *, posts_write_confirmed=False):
        _require(not self.consumed, 'buffer_rotation_already_consumed')
        self.consumed = True
        _require(isinstance(candidate, str) and KEY_PATTERN.fullmatch(candidate) is not None,
                 'buffer_rotation_key_invalid')
        _require(not secrets.compare_digest(hashlib.sha256(candidate.encode('ascii')).digest(),
                                            self.old_key_digest),
                 'buffer_rotation_key_unchanged')
        _require(posts_write_confirmed is True, 'buffer_rotation_posts_write_unconfirmed')
        candidate_digest = hashlib.sha256(candidate.encode('ascii')).hexdigest()
        try:
            observed = _snapshot(self.client_factory(candidate), self.binding,
                                 [item['id'] for item in self.baseline])
            _compare(self.baseline, observed, self.sent_progress_verifier)
        except ValueError as error:
            if str(error) in ('buffer_rotation_binding_mismatch', 'buffer_rotation_channel_unavailable',
                              'buffer_rotation_queue_mismatch', 'buffer_rotation_snapshot_invalid',
                              'buffer_rotation_queue_unbounded',
                              'buffer_rotation_sent_reconciliation_required'):
                raise
            _write_marker(self.rotation_marker, {'schemaVersion': 1,
                'phase': 'validation_unknown', 'intentId': secrets.token_hex(16),
                'target': str(self.dest), 'baselineDigest': self.baseline_digest,
                'candidateSha256': candidate_digest,
                'postsWriteProof': 'ui_attestation_unverified',
                'coordinationRequired': ['other_consumers_of_regenerated_key_unknown'],
                'createdAt': self.now.astimezone(JST).isoformat()})
            raise ValueError('buffer_rotation_validation_unknown') from None
        except Exception:
            _write_marker(self.rotation_marker, {'schemaVersion': 1,
                'phase': 'validation_unknown', 'intentId': secrets.token_hex(16),
                'target': str(self.dest), 'baselineDigest': self.baseline_digest,
                'candidateSha256': candidate_digest,
                'postsWriteProof': 'ui_attestation_unverified',
                'coordinationRequired': ['other_consumers_of_regenerated_key_unknown'],
                'createdAt': self.now.astimezone(JST).isoformat()})
            raise ValueError('buffer_rotation_validation_unknown') from None
        _require(_file_identity(self.dest) == self.original_identity,
                 'buffer_rotation_cas_mismatch')
        marker = {'schemaVersion': 1, 'phase': 'inflight',
                  'intentId': secrets.token_hex(16), 'target': str(self.dest),
                  'baselineDigest': self.baseline_digest,
                  'originalContentSha256': self.original_identity['contentSha256'],
                  'candidateSha256': candidate_digest,
                  'postsWriteProof': 'ui_attestation_unverified',
                  'coordinationRequired': ['other_consumers_of_regenerated_key_unknown'],
                  'createdAt': self.now.astimezone(JST).isoformat()}
        _write_marker(self.rotation_marker, marker)
        try:
            self.atomic_replace(self.dest, candidate)
            installed = _file_identity(self.dest)
            _require(installed['contentSha256'] == hashlib.sha256(
                ('BUFFER_API_KEY=' + candidate + '\n').encode('ascii')).hexdigest(),
                'buffer_rotation_replace_unknown')
        except Exception:
            marker.update(phase='unknown')
            try:
                _write_marker(self.rotation_marker, marker)
            except ValueError:
                pass
            raise ValueError('buffer_rotation_replace_unknown') from None
        marker.update(phase='verified', verifiedAt=datetime.now(JST).isoformat())
        _write_marker(self.rotation_marker, marker)
        return {'saved': True, 'snapshotDigest': self.baseline_digest,
                'postCount': len(observed),
                'proved': ['account_read', 'posts_read', 'pending_queue_unchanged'],
                'notProved': ['posts_write'], 'postsWriteUiConfirmed': True,
                'coordinationRequired': ['other_consumers_of_regenerated_key_unknown']}

    def close(self):
        if self.lock is not None:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_UN)
            finally:
                self.lock.close()
                self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
