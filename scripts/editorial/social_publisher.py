"""Exact approved social publication with a private, fail-closed effect journal."""
import base64
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from catalog import Catalog, _image_type
from ledger import fingerprint, valid_review
from x_readback import exact_x_text

JST = timezone(timedelta(hours=9))


def _require(ok, code):
    if not ok:
        raise ValueError(code)


def _atomic(path, data):
    tmp = path.with_name(path.name + '.' + secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp.exists():
            tmp.unlink()


class SocialPublisher:
    def __init__(self, config, env, client=None, fetcher=None):
        self.config, self.env = dict(config), dict(env)
        self.root = Path(config['stateRoot'])
        self.client = client or self._node
        self.fetcher = fetcher or Catalog(self.env)

    def _node(self, action, payload):
        child_env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR') if k in os.environ}
        child_env.update({k: self.env[k] for k in ('X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET') if k in self.env})
        child_env['TZ'] = 'Asia/Tokyo'
        try:
            remaining = min(300, getattr(self, '_deadline', time.monotonic() + 300) - time.monotonic())
            _require(remaining > 0, 'x_transport_unknown')
            result = subprocess.run([self.config.get('node', 'node'), str(Path(__file__).with_name('x-api.mjs'))],
                                    input=json.dumps({'action': action, 'payload': payload}), capture_output=True,
                                    text=True, env=child_env, timeout=remaining)
            _require(result.returncode == 0 and len(result.stdout) <= 16000, 'x_transport_unknown')
            value = json.loads(result.stdout)
            _require(isinstance(value, dict), 'x_response_invalid')
            return value
        except (OSError, subprocess.SubprocessError, ValueError):
            raise ValueError('x_transport_unknown') from None

    def preflight(self):
        """Read-only credential/account check; no job, journal or POST required."""
        result = self.client('preflight', {})
        user_id = result.get('userId') if isinstance(result, dict) else None
        expected = self.config.get('targetAccountId')
        _require(isinstance(expected, str) and re.fullmatch(r'\d+', expected), 'x_target_unconfigured')
        _require(user_id == expected, 'x_account_mismatch')
        return {'verified': True, 'userId': user_id}

    def _validate(self, job):
        _require(self.config.get('socialPostingEnabled') is True, 'social_posting_disabled')
        _require(isinstance(job, dict) and job.get('stage') == 'social_approved', 'social_approval_required')
        social, publication = job.get('social') or {}, job.get('publication') or {}
        proposal = social.get('proposal') or {}
        revision = social.get('revision')
        _require(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{64}', revision or '')
                 and fingerprint(proposal) == revision, 'social_revision_mismatch')
        valid_review(social.get('review'), revision)
        approval = social.get('approval') or {}
        _require(approval.get('action') == 'approved' and approval.get('revision') == revision
                 and approval.get('user_id') == self.config['slack']['user_id']
                 and isinstance(approval.get('request_id'), str) and approval['request_id'], 'social_owner_approval_required')
        _require(job.get('revision') == fingerprint(job.get('bundle'))
                 and publication.get('verified') is True and publication.get('revision') == job['revision']
                 and (publication.get('readback') or {}).get('verified') is True
                 and publication['readback'].get('fingerprint') == job['revision'], 'publication_unverified')
        _require(proposal.get('deliveryMode') == 'auto_x' and proposal.get('targetAccountId') == self.config.get('targetAccountId')
                 and proposal.get('platform') == 'x', 'social_target_mismatch')
        _require(isinstance(proposal.get('text'), str) and proposal['text'].strip()
                 and isinstance(proposal.get('replyText'), str)
                 and proposal['replyText'] == publication.get('url') == proposal.get('url'), 'social_text_url_mismatch')
        _require(not re.search(r'https?://', proposal['text']), 'main_text_contains_url')
        images = proposal.get('images')
        _require(isinstance(images, list) and 1 <= len(images) <= 4, 'social_images_required')
        approved = job['bundle'].get('images') or []
        _require(all(isinstance(i, dict) and i.get('verified') is True and i in approved
                     and isinstance(i.get('url'), str) and re.fullmatch(r'[0-9a-f]{64}', i.get('sha256', ''))
                     and isinstance(i.get('size'), int) and i['size'] > 0 for i in images), 'social_image_binding_invalid')
        _require(len({i['url'] for i in images}) == len(images), 'social_image_duplicate')
        return proposal, revision

    def _image_bytes(self, image):
        try:
            response = self.fetcher.request(image['url'], {'Accept': 'image/*', 'Cache-Control': 'no-cache'})
            body = response['body']
            mime = response['headers'].get('content-type', '').split(';')[0].lower()
            _require(response['url'] == image.get('finalUrl', image['url'])
                     and mime == image.get('contentType') == _image_type(body)
                     and len(body) == image['size'] and hashlib.sha256(body).hexdigest() == image['sha256']
                     and mime in ('image/jpeg', 'image/png', 'image/gif', 'image/webp'), 'social_image_changed')
            return body, mime
        except Exception:
            raise ValueError('social_image_fetch_failed') from None

    def _check_post(self, post, post_id, account, text, media_keys=None, parent=None):
        _require(isinstance(post, dict) and post.get('id') == post_id and post.get('authorId') == account
                 and exact_x_text(post, text),
                 'x_readback_mismatch')
        if media_keys is not None:
            _require(post.get('mediaKeys') == media_keys, 'x_media_readback_mismatch')
        if parent is not None:
            _require(post.get('replyTo') == parent, 'x_reply_parent_mismatch')

    def publish(self, job):
        self._deadline = time.monotonic() + 300
        proposal, revision = self._validate(job)
        account = self.preflight()['userId']  # An OAuth failure creates no journal and no POST.
        _require(self.root.is_dir() and self.root.stat().st_mode & 0o777 == 0o700,
                 'social_root_not_private')
        folder = self.root / 'social-publications'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require(folder.stat().st_mode & 0o777 == 0o700, 'social_journal_not_private')
        marker = folder / (revision + '.json')
        lock_path = folder / (revision + '.flock')
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if marker.exists():
                _require(not marker.is_symlink() and marker.stat().st_mode & 0o777 == 0o600, 'social_journal_invalid')
                state = json.loads(marker.read_text())
                _require(state.get('revision') == revision and state.get('account') == account
                         and state.get('proposalFingerprint') == fingerprint(proposal), 'social_journal_mismatch')
                if state.get('phase') == 'verified':
                    return self._result(state)
                if state.get('pending'):
                    return {'status': 'requires_reconciliation', 'phase': state['phase']}
            else:
                state = {'revision': revision, 'account': account, 'proposalFingerprint': fingerprint(proposal),
                         'phase': 'upload', 'uploads': [], 'pending': None}
                _atomic(marker, state)

            # A known post ID can be read back even if the source image later disappears.
            # Before any create, uploaded IDs remain bound to approved SHA256 values.
            _require(len(state['uploads']) <= len(proposal['images']) and all(
                upload.get('sha256') == image['sha256'] for upload, image in zip(state['uploads'], proposal['images'])),
                'social_upload_binding_invalid')
            images = [self._image_bytes(i) for i in proposal['images']] if len(state['uploads']) < len(proposal['images']) else []
            _require(not any(mime == 'image/gif' for _, mime in images) or len(proposal['images']) == 1,
                     'social_gif_must_be_single')
            for index in range(len(state['uploads']), len(proposal['images'])):
                state.update(phase='upload', pending={'index': index})
                _atomic(marker, state)
                body, mime = images[index]
                try:
                    result = self.client('upload', {'data': base64.b64encode(body).decode('ascii'), 'mime': mime})
                    _require(isinstance(result.get('mediaId'), str) and re.fullmatch(r'\d+', result['mediaId'])
                             and isinstance(result.get('mediaKey'), str) and result['mediaKey']
                             and isinstance(result.get('expiresAfterSecs'), int)
                             and 0 < result['expiresAfterSecs'] <= 86400, 'x_upload_unknown')
                except Exception:
                    return {'status': 'requires_reconciliation', 'phase': 'upload'}
                state['uploads'].append({'mediaId': result['mediaId'], 'mediaKey': result['mediaKey'],
                                         'sha256': proposal['images'][index]['sha256'],
                                         'size': len(body), 'contentType': mime,
                                         'expiresAt': (datetime.now(JST) + timedelta(seconds=result['expiresAfterSecs'])).isoformat()})
                state['pending'] = None
                _atomic(marker, state)
            media_ids = [u['mediaId'] for u in state['uploads']]
            media_keys = [u['mediaKey'] for u in state['uploads']]
            if not state.get('mainId'):
                _require(all(datetime.fromisoformat(u['expiresAt']) > datetime.now(JST) + timedelta(minutes=1)
                             for u in state['uploads']), 'social_media_expired')
                state.update(phase='maincreate', pending={'action': 'maincreate'})
                _atomic(marker, state)
                try:
                    result = self.client('maincreate', {'text': proposal['text'], 'mediaIds': media_ids})
                    _require(isinstance(result.get('id'), str) and re.fullmatch(r'\d+', result['id']), 'x_main_unknown')
                except Exception:
                    return {'status': 'requires_reconciliation', 'phase': 'maincreate'}
                state.update(mainId=result['id'], phase='mainread', pending=None)
                _atomic(marker, state)
            try:
                post = self.client('read', {'id': state['mainId']})
                self._check_post(post, state['mainId'], account, proposal['text'], media_keys)
                _require(post.get('replyTo') is None, 'x_main_parent_mismatch')
            except Exception:
                return {'status': 'requires_reconciliation', 'phase': 'mainread'}
            post = dict(post, rawText=post['text'], text=proposal['text'])
            state.update(phase='mainread', mainReadback=post)
            _atomic(marker, state)
            if not state.get('replyId'):
                state.update(phase='replycreate', pending={'action': 'replycreate'})
                _atomic(marker, state)
                try:
                    result = self.client('replycreate', {'text': proposal['replyText'], 'parentId': state['mainId']})
                    _require(isinstance(result.get('id'), str) and re.fullmatch(r'\d+', result['id']), 'x_reply_unknown')
                except Exception:
                    return {'status': 'requires_reconciliation', 'phase': 'replycreate'}
                state.update(replyId=result['id'], phase='replyread', pending=None)
                _atomic(marker, state)
            try:
                post = self.client('read', {'id': state['replyId']})
                self._check_post(post, state['replyId'], account, proposal['replyText'], [], state['mainId'])
            except Exception:
                return {'status': 'requires_reconciliation', 'phase': 'replyread'}
            post = dict(post, rawText=post['text'], text=proposal['replyText'])
            state.update(phase='verified', pending=None, replyReadback=post)
            _atomic(marker, state)
            return self._result(state)

    @staticmethod
    def _result(state):
        account, main_id, reply_id = state['account'], state['mainId'], state['replyId']
        main = dict(state['mainReadback'], verified=True, url=f'https://x.com/i/web/status/{main_id}')
        reply = dict(state['replyReadback'], verified=True, url=f'https://x.com/i/web/status/{reply_id}')
        main['text'] = main.pop('rawText')
        reply['text'] = reply.pop('rawText')
        return {'status': 'verified', 'verified': True, 'fingerprint': state['revision'],
                'accountId': account, 'mainId': main_id, 'replyId': reply_id,
                'readback': {'verified': True, 'fingerprint': state['revision'], 'accountId': account,
                             'main': main, 'reply': reply,
                             'media': {'verified': True,
                                       'items': [dict(item, verified=True) for item in state['uploads']]}}}
