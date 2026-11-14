"""Per-audit bounded public GET concurrency; no cross-run cache or retries."""
from concurrent.futures import ThreadPoolExecutor
import time
import threading

MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class AuditRequests:
    def __init__(self, catalog, deadline, workers=4):
        if not 1 <= workers <= 4:
            raise ValueError('audit_worker_limit')
        self.catalog, self.deadline = catalog, deadline
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self.futures = {}
        self.lock, self.response_bytes = threading.Lock(), 0

    @staticmethod
    def _key(url, headers, allowed_domains, exact_domains):
        return (url, tuple(sorted((headers or {}).items())),
                tuple(allowed_domains or ()), bool(exact_domains))

    def _fetch(self, url, headers, allowed_domains, exact_domains):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('audit_budget_exhausted')
        response = self.catalog.request(url, headers=headers, allowed_domains=allowed_domains,
                                        exact_domains=exact_domains)
        size = len(response.get('body', b'')) if isinstance(response, dict) else 0
        with self.lock:
            self.response_bytes += size
            overflow = self.response_bytes > MAX_RESPONSE_BYTES
        if overflow:
            del response
            raise ValueError('audit_response_budget_exhausted')
        return response

    def prefetch(self, url, headers=None, allowed_domains=None, exact_domains=False):
        key = self._key(url, headers, allowed_domains, exact_domains)
        if key in self.futures or time.monotonic() >= self.deadline:
            return
        if len(self.futures) >= 128:
            raise ValueError('audit_request_limit')
        self.futures[key] = self.executor.submit(
            self._fetch, url, headers, allowed_domains, exact_domains)

    def request(self, url, headers=None, allowed_domains=None, exact_domains=False):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('audit_budget_exhausted')
        self.prefetch(url, headers, allowed_domains, exact_domains)
        return self.futures[self._key(url, headers, allowed_domains, exact_domains)].result(
            timeout=remaining)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
