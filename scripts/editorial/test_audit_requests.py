import threading
import time
import unittest
from unittest.mock import patch
from audit_requests import AuditRequests


class AuditRequestTests(unittest.TestCase):
    def test_total_retained_bytes_are_bounded(self):
        class Catalog:
            def request(self, *a, **k):
                return {'body': b'x' * 60}
        with patch('audit_requests.MAX_RESPONSE_BYTES', 100):
            pool = AuditRequests(Catalog(), time.monotonic() + 2, workers=1)
            try:
                self.assertEqual(len(pool.request('a')['body']), 60)
                with self.assertRaisesRegex(ValueError, 'audit_response_budget_exhausted'):
                    pool.request('b')
            finally:
                pool.close()

    def test_bounded_parallel_requests_are_reused_without_retry(self):
        class Catalog:
            def __init__(self):
                self.active = self.peak = self.calls = 0
                self.lock = threading.Lock()
            def request(self, url, **kwargs):
                with self.lock:
                    self.active += 1
                    self.calls += 1
                    self.peak = max(self.peak, self.active)
                time.sleep(.01)
                with self.lock:
                    self.active -= 1
                if url == 'bad':
                    raise ValueError('private error')
                return url
        source = Catalog()
        pool = AuditRequests(source, time.monotonic() + 2, workers=2)
        try:
            for url in ('a', 'b', 'c', 'bad'):
                pool.prefetch(url, headers={'Accept': 'x'}, allowed_domains=('example.com',))
            self.assertEqual('a', pool.request('a', {'Accept': 'x'}, allowed_domains=('example.com',)))
            for _ in range(2):
                with self.assertRaises(ValueError):
                    pool.request('bad', {'Accept': 'x'}, allowed_domains=('example.com',))
            self.assertLessEqual(source.peak, 2)
            self.assertEqual(source.calls, 4)
        finally:
            pool.close()

    def test_expired_budget_never_starts_request(self):
        class Catalog:
            def request(self, *a, **k):
                raise AssertionError('network after deadline')
        pool = AuditRequests(Catalog(), time.monotonic() - 1)
        try:
            with self.assertRaises(TimeoutError):
                pool.request('a')
        finally:
            pool.close()
