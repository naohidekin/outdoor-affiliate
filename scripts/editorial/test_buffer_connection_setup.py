"""Credential setup never puts a key in argv/output or overwrites an old key."""
import json
import fcntl
import io
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from buffer_connection_setup import (valid_key, save_remote, serve, start_remote_rotation,
                                     REMOTE_SAVE, REMOTE_ROTATE)
from buffer_key_rotation import RotationSession, atomic_replace_env


class ConnectionSetupTests(unittest.TestCase):
    def test_early_eof_rejects_even_a_valid_key_prefix(self):
        child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('buffer_connection_setup.py'))],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            url = urlsplit(json.loads(child.stdout.readline())['setupUrl'])
            with urlopen(url.geturl(), timeout=3) as response:
                self.assertEqual('same-origin', response.headers['Referrer-Policy'])
            with socket.create_connection((url.hostname, url.port), timeout=8) as connection:
                request = ('POST ' + url.path + ' HTTP/1.1\r\nHost: ' + url.netloc +
                           '\r\nOrigin: http://' + url.netloc +
                           '\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: 100\r\n\r\nkey=buffer-key-123456789')
                connection.sendall(request.encode())
                connection.shutdown(socket.SHUT_WR)
                self.assertIn(b'400', connection.recv(4096))
        finally:
            child.terminate()
            child.communicate(timeout=5)

    def test_incomplete_http_body_times_out_without_saving(self):
        child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('buffer_connection_setup.py'))],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            url = urlsplit(json.loads(child.stdout.readline())['setupUrl'])
            with socket.create_connection((url.hostname, url.port), timeout=8) as connection:
                authority = url.netloc
                request = ('POST ' + url.path + ' HTTP/1.1\r\nHost: ' + authority +
                           '\r\nOrigin: http://' + authority +
                           '\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: 100\r\n\r\nx')
                connection.sendall(request.encode())
                self.assertIn(b'400', connection.recv(4096))
        finally:
            child.terminate()
            child.communicate(timeout=5)

    def test_key_goes_only_to_encrypted_stdin_not_command_arguments(self):
        secret = 'buffer-test-only-key-123456789'
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout=json.dumps({'saved': True}))
        self.assertTrue(save_remote(secret, runner=run))
        self.assertNotIn(secret, str(calls[0][0]))
        self.assertEqual(secret, calls[0][1]['input'])
        self.assertTrue(calls[0][1]['capture_output'])
        self.assertIn('os.O_EXCL', REMOTE_SAVE)
        self.assertIn('os.O_NOFOLLOW', REMOTE_SAVE)

    def test_invalid_or_multiline_secret_and_shell_host_never_spawn(self):
        def run(*args, **kwargs):
            raise AssertionError('must not spawn')
        for value in ('short', 'buffer-key-123456789\nX=secret', 'a' * 2049):
            self.assertFalse(valid_key(value))
            self.assertFalse(save_remote(value, runner=run))
        self.assertFalse(save_remote('buffer-key-123456789', host='macpro;echo', runner=run))

    def test_existing_file_or_bad_response_does_not_claim_saved(self):
        self.assertFalse(save_remote('buffer-key-123456789', runner=lambda *a, **k: SimpleNamespace(returncode=1, stdout='')))
        self.assertFalse(save_remote('buffer-key-123456789', runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout='{}')))


def post(post_id='post-1', *, status='scheduled', text='approved', due='2026-11-20T03:00:00Z'):
    image = 'https://db.example/social-card.png'
    return {'id': post_id, 'channelId': 'channel-1', 'channelService': 'twitter',
            'status': status, 'text': text, 'dueAt': due, 'sentAt': None,
            'externalLink': None,
            'assets': [{'source': image}], 'metadata': {'threadCount': 2, 'thread': [
                {'text': text, 'assets': [{'source': image}]},
                {'text': 'https://camp.example/article', 'assets': []}]}}


class BufferReadFake:
    def __init__(self, channel=None, posts=None, fail=None):
        self.channel = channel or {'id': 'channel-1', 'organizationId': 'org-1',
            'service': 'twitter', 'serviceId': 'account-1', 'isDisconnected': False,
            'isLocked': False, 'isQueuePaused': False, 'linkShortening': {'isEnabled': False}}
        self.values = list(posts if posts is not None else [post()])
        self.fail = fail
        self.calls = []

    def preflight(self, organization_id, channel_id):
        self.calls.append(('preflight', organization_id, channel_id))
        if self.fail == 'preflight':
            raise TimeoutError('unknown')
        return json.loads(json.dumps(self.channel))

    def posts(self, organization_id, channel_id, start, end):
        self.calls.append(('posts', organization_id, channel_id, start, end))
        if self.fail == 'posts':
            raise TimeoutError('unknown')
        return json.loads(json.dumps(self.values))

    def pending_posts(self, organization_id, channel_id):
        self.calls.append(('pending_posts', organization_id, channel_id))
        if self.fail == 'posts':
            raise TimeoutError('unknown')
        return json.loads(json.dumps([
            item for item in self.values if item['status'] in ('draft', 'scheduled', 'sending')]))

    def post(self, post_id):
        self.calls.append(('post', post_id))
        return next((json.loads(json.dumps(item)) for item in self.values if item['id'] == post_id), None)


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        self.root = Path(self.tmp.name) / 'state'
        self.repo.mkdir(mode=0o700)
        self.root.mkdir(mode=0o700)
        self.dest = self.repo / '.env.buffer.local'
        self.old = 'buffer-old-key-123456789'
        self.new = 'buffer-new-key-123456789'
        self.dest.write_text('BUFFER_API_KEY=' + self.old + '\n')
        self.dest.chmod(0o600)
        self.config = Path(self.tmp.name) / 'config.json'
        self.config.write_text(json.dumps({'repo': str(self.repo), 'stateRoot': str(self.root),
            'bufferEnvFile': str(self.dest), 'buffer': {'organizationId': 'org-1',
                'channelId': 'channel-1', 'xAccountId': 'account-1'}}))
        self.old_client, self.new_client = BufferReadFake(), BufferReadFake()

    def tearDown(self):
        self.tmp.cleanup()

    def factory(self, key):
        return {self.old: self.old_client, self.new: self.new_client}[key]

    def test_rotation_replaces_only_after_exact_readback_and_does_not_claim_write_scope(self):
        with RotationSession(self.config, client_factory=self.factory) as session:
            proof = session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.new + '\n')
        self.assertEqual(self.dest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(proof['proved'], ['account_read', 'posts_read', 'pending_queue_unchanged'])
        self.assertEqual(proof['notProved'], ['posts_write'])
        self.assertEqual(proof['postsWriteUiConfirmed'], True)
        self.assertEqual(proof['coordinationRequired'],
                         ['other_consumers_of_regenerated_key_unknown'])
        self.assertNotIn(self.old, json.dumps(proof))
        self.assertNotIn(self.new, json.dumps(proof))

    def test_prepared_baseline_survives_restart_without_old_key_api(self):
        receipt = self.root / 'buffer-key-rotations' / 'prepared.json'
        with RotationSession(self.config, client_factory=self.factory) as session:
            baseline_digest = session.baseline_digest
        prepared = json.loads(receipt.read_text())
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(prepared['phase'], 'prepared')
        self.assertEqual(prepared['baselineDigest'], baseline_digest)
        self.assertEqual(prepared['baseline'][0]['id'], 'post-1')
        self.assertEqual(prepared['baseline'][0]['text'], 'approved')
        self.assertEqual(prepared['baseline'][0]['dueAt'], '2026-11-20T03:00:00Z')
        self.assertEqual(prepared['binding'], {'organizationId': 'org-1',
                                               'channelId': 'channel-1',
                                               'xAccountId': 'account-1'})
        self.assertTrue(prepared['preparedAt'].endswith('+09:00'))
        self.assertNotIn(self.old, receipt.read_text())
        self.assertNotIn(self.new, receipt.read_text())
        old_calls = list(self.old_client.calls)

        def after_regeneration(key):
            if key == self.old:
                raise AssertionError('invalidated old key must not be called after restart')
            return self.new_client

        with RotationSession(self.config, client_factory=after_regeneration) as session:
            proof = session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(proof['snapshotDigest'], baseline_digest)
        self.assertEqual(self.old_client.calls, old_calls)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.new + '\n')

    def test_wrong_account_and_queue_mismatch_never_replace(self):
        self.new_client.channel['serviceId'] = 'wrong-account'
        with RotationSession(self.config, client_factory=self.factory) as session:
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_binding_mismatch'):
                session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.old + '\n')

        self.new_client = BufferReadFake(posts=[post(text='changed')])
        with RotationSession(self.config, client_factory=self.factory) as session:
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_queue_mismatch'):
                session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.old + '\n')

    def test_unknown_validation_is_consumed_without_retry_or_replacement(self):
        self.new_client.fail = 'posts'
        with RotationSession(self.config, client_factory=self.factory) as session:
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_validation_unknown'):
                session.commit(self.new, posts_write_confirmed=True)
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_already_consumed'):
                session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.old + '\n')
        marker = self.root / 'buffer-key-rotations' / 'latest.json'
        self.assertEqual(json.loads(marker.read_text())['phase'], 'validation_unknown')
        with self.assertRaisesRegex(ValueError, 'buffer_rotation_reconciliation_required'):
            RotationSession(self.config, client_factory=self.factory)

    def test_sent_progress_without_native_x_proof_holds_for_manual_reconciliation(self):
        sent = post(status='sent')
        sent.update(sentAt='2026-11-20T03:01:00Z',
                    externalLink='https://x.com/camp/status/123')
        self.new_client = BufferReadFake(posts=[sent])
        with RotationSession(self.config, client_factory=self.factory) as session:
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_sent_reconciliation_required'):
                session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.old + '\n')

    def test_sent_progress_with_injected_native_x_proof_can_preserve_same_post(self):
        sent = post(status='sent')
        sent.update(sentAt='2026-11-20T03:01:00Z',
                    externalLink='https://x.com/camp/status/123')
        self.new_client = BufferReadFake(posts=[sent])
        checked = []
        def verify(old, new):
            checked.append((old['id'], new['id'], new['externalLink']))
            return True
        with RotationSession(self.config, client_factory=self.factory,
                             sent_progress_verifier=verify) as session:
            session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(checked, [('post-1', 'post-1', 'https://x.com/camp/status/123')])
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.new + '\n')

    def test_old_single_nonthread_pending_post_is_included_without_created_at_window(self):
        single = post(post_id='old-pending')
        single['metadata'] = None
        single['assets'] = []
        self.old_client = BufferReadFake(posts=[single])
        self.new_client = BufferReadFake(posts=[single])
        with RotationSession(self.config, client_factory=self.factory) as session:
            proof = session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(proof['postCount'], 1)
        self.assertTrue(any(call[0] == 'pending_posts' for call in self.old_client.calls))
        self.assertFalse(any(call[0] == 'posts' for call in self.old_client.calls))

    def test_production_pending_query_has_no_created_at_gap_and_is_bounded(self):
        value = post()
        calls = []
        class Client:
            def preflight(inner, *_):
                return self.old_client.channel
            def execute(inner, query, variables):
                calls.append((query, variables))
                filter_value = variables['input']['filter']
                self.assertNotIn('createdAt', filter_value)
                self.assertEqual(filter_value['status'], ['draft', 'scheduled', 'sending'])
                return {'posts': {'edges': [{'node': value}],
                                  'pageInfo': {'hasNextPage': False}}}
            def post(inner, post_id):
                return value
        with RotationSession(self.config, client_factory=lambda key: Client()) as session:
            session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(len(calls), 2)

    def test_existing_target_must_be_regular_nonsymlink_0600(self):
        self.dest.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'buffer_rotation_target_invalid'):
            RotationSession(self.config, client_factory=self.factory)

    def test_runtime_lock_and_unbounded_pending_queue_fail_before_candidate(self):
        lease = (self.root / 'runtime.flock').open('a+')
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_lock_unavailable'):
                RotationSession(self.config, client_factory=self.factory)
        finally:
            fcntl.flock(lease, fcntl.LOCK_UN)
            lease.close()

        class Unbounded:
            def preflight(inner, *_):
                return self.old_client.channel
            def execute(inner, *_):
                return {'posts': {'edges': [], 'pageInfo': {'hasNextPage': True}}}
        with self.assertRaisesRegex(ValueError, 'buffer_rotation_queue_unbounded'):
            RotationSession(self.config, client_factory=lambda key: Unbounded())

    def test_same_key_is_not_a_rotation_and_never_replaces(self):
        with RotationSession(self.config, client_factory=self.factory) as session:
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_key_unchanged'):
                session.commit(self.old, posts_write_confirmed=True)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.old + '\n')
        self.dest.unlink()
        target = self.repo / 'other'
        target.write_text('BUFFER_API_KEY=' + self.old + '\n')
        target.chmod(0o600)
        self.dest.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'buffer_rotation_target_invalid'):
            RotationSession(self.config, client_factory=self.factory)

    def test_atomic_partial_save_preserves_old_and_removes_staging(self):
        def fail_replace(source, destination):
            raise OSError('simulated replace failure')
        with self.assertRaisesRegex(ValueError, 'buffer_rotation_replace_unknown'):
            atomic_replace_env(self.dest, self.new, replace=fail_replace)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=' + self.old + '\n')
        self.assertEqual([item.name for item in self.repo.iterdir()], ['.env.buffer.local'])

    def test_rotation_cas_rechecks_original_inode_and_content_before_effect(self):
        with RotationSession(self.config, client_factory=self.factory) as session:
            self.dest.write_text('BUFFER_API_KEY=buffer-changed-key-123456789\n')
            self.dest.chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_cas_mismatch'):
                session.commit(self.new, posts_write_confirmed=True)
        self.assertEqual(self.dest.read_text(), 'BUFFER_API_KEY=buffer-changed-key-123456789\n')
        self.assertFalse((self.root / 'buffer-key-rotations' / 'latest.json').exists())

    def test_durable_intent_is_inflight_before_replace_and_verified_without_secrets(self):
        observed = []
        marker = self.root / 'buffer-key-rotations' / 'latest.json'
        def replace(dest, key):
            state = json.loads(marker.read_text())
            observed.append(state['phase'])
            atomic_replace_env(dest, key)
        with RotationSession(self.config, client_factory=self.factory,
                             atomic_replace=replace) as session:
            session.commit(self.new, posts_write_confirmed=True)
        state = json.loads(marker.read_text())
        self.assertEqual(observed, ['inflight'])
        self.assertEqual(state['phase'], 'verified')
        self.assertTrue(state['createdAt'].endswith('+09:00'))
        self.assertTrue(state['verifiedAt'].endswith('+09:00'))
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.old, marker.read_text())
        self.assertNotIn(self.new, marker.read_text())

    def test_unknown_effect_marker_blocks_future_rotation_prepare(self):
        def uncertain(dest, key):
            dest.write_text('corrupt\n')
            dest.chmod(0o600)
            raise ValueError('buffer_rotation_replace_unknown')
        with RotationSession(self.config, client_factory=self.factory,
                             atomic_replace=uncertain) as session:
            with self.assertRaisesRegex(ValueError, 'buffer_rotation_replace_unknown'):
                session.commit(self.new, posts_write_confirmed=True)
        marker = self.root / 'buffer-key-rotations' / 'latest.json'
        self.assertEqual(json.loads(marker.read_text())['phase'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'buffer_rotation_reconciliation_required'):
            RotationSession(self.config, client_factory=self.factory)

    def test_pending_snapshot_rejects_duplicate_wrong_channel_and_sent_rows(self):
        for values in ([post(), post()],
                       [dict(post(), channelId='other-channel')],
                       [post(status='sent')]):
            self.old_client = BufferReadFake(posts=values)
            self.old_client.pending_posts = lambda *args, values=values: json.loads(json.dumps(values))
            with self.subTest(values=values), self.assertRaisesRegex(
                    ValueError, 'buffer_rotation_snapshot_invalid'):
                RotationSession(self.config, client_factory=self.factory)

    def test_rotation_form_requires_signed_nonce_origin_exact_form_and_is_one_use(self):
        class Session:
            def __init__(inner):
                inner.calls = []
            def commit(inner, key, posts_write_confirmed=False):
                inner.calls.append((key, posts_write_confirmed))
                return {'saved': True}
            def close(inner):
                pass
        session = Session()
        announced = queue.Queue()
        thread = threading.Thread(target=serve, kwargs={'host': 'macpro', 'rotate': True,
            'rotation_factory': lambda host: session, 'announce': announced.put, 'timeout': 15}, daemon=True)
        thread.start()
        url = announced.get(timeout=3)['setupUrl']
        html = urlopen(url, timeout=3).read().decode()
        nonce = re.search(r'name="nonce" value="([^"]+)"', html).group(1)
        signature = re.search(r'name="signature" value="([^"]+)"', html).group(1)
        fields = {'key': self.new, 'nonce': nonce, 'signature': signature,
                  'posts_write_confirmed': '1'}
        with self.assertRaises(HTTPError) as wrong_origin:
            urlopen(Request(url, data=urlencode(fields).encode(), headers={
                'Origin': 'http://attacker.invalid', 'Content-Type': 'application/x-www-form-urlencoded'}), timeout=3)
        self.assertEqual(wrong_origin.exception.code, 403)
        with self.assertRaises(HTTPError) as wrong_form:
            bad = dict(fields, extra='x')
            urlopen(Request(url, data=urlencode(bad).encode(), headers={
                'Origin': 'http://' + urlsplit(url).netloc,
                'Content-Type': 'application/x-www-form-urlencoded'}), timeout=3)
        self.assertEqual(wrong_form.exception.code, 400)
        response = urlopen(Request(url, data=urlencode(fields).encode(), headers={
            'Origin': 'http://' + urlsplit(url).netloc,
            'Content-Type': 'application/x-www-form-urlencoded'}), timeout=3)
        body = response.read().decode()
        self.assertNotIn(self.new, body)
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(session.calls, [(self.new, True)])

    def test_candidate_secret_uses_only_remote_stdin_not_ssh_arguments_or_output(self):
        digest = 'a' * 64
        proof = {'saved': True, 'snapshotDigest': digest, 'postCount': 0}
        output = io.StringIO()
        class Input(io.StringIO):
            def close(inner):
                inner.closed_by_client = True
        class Process:
            def __init__(inner):
                inner.stdin, inner.stdout, inner.stderr = Input(), output, io.StringIO()
            def wait(inner, timeout=None):
                return 0
            def poll(inner):
                return 0
        calls = []
        def popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return Process()
        replies = [json.dumps({'ready': True, 'snapshotDigest': digest, 'postCount': 0}),
                   json.dumps({'saved': True, 'proof': proof})]
        with mock.patch('buffer_connection_setup._readline', side_effect=replies):
            rotation = start_remote_rotation(popen=popen)
            self.assertEqual(rotation.commit(self.new, posts_write_confirmed=True), proof)
        self.assertNotIn(self.new, str(calls[0][0]))
        self.assertNotIn(self.new, output.getvalue())
        self.assertIn(self.new, rotation.process.stdin.getvalue())
        self.assertIn('RotationSession', REMOTE_ROTATE)
        self.assertNotIn('BUFFER_API_KEY=', REMOTE_ROTATE)


if __name__ == '__main__':
    unittest.main()
