"""Credential setup never puts a key in argv/output or overwrites an old key."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import urlopen
from buffer_connection_setup import valid_key, save_remote, REMOTE_SAVE


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


if __name__ == '__main__':
    unittest.main()
