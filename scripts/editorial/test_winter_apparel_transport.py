"""Exact public-page UA compatibility; synthetic transport, no real HTTP."""
import unittest
from catalog import Catalog


class WinterApparelTransportTests(unittest.TestCase):
    def test_ordinary_headers_only_on_verified_exact_pages(self):
        for url in (
            'https://arcteryx.jp/products/beta-jacket-m',
            'https://arcteryx.jp/products/beta-sl-jacket-m',
        ):
            calls = []
            def fetch(target, headers, timeout):
                calls.append((target, headers))
                return {'status': 200, 'headers': {'content-type': 'text/html'}, 'body': b'<html></html>'}
            Catalog({}, fetch).request(url)
            self.assertEqual('Mozilla/5.0', calls[0][1]['User-Agent'])
            self.assertEqual('text/html', calls[0][1]['Accept'])

    def test_millet_ordinary_browser_headers_need_no_retry_or_identity_bypass(self):
        for path in ('/products/miv01248', '/collections/activities/products/miv01248'):
            calls = []
            def fetch(target, headers, timeout):
                calls.append(headers)
                valid = ('Chrome/' in headers.get('User-Agent', '')
                         and headers.get('Accept-Language') == 'ja-JP,ja;q=0.9'
                         and 'application/xhtml+xml' in headers.get('Accept', ''))
                return {'status': 200 if valid else 403, 'headers': {}, 'body': b'<html></html>'}
            Catalog({}, fetch).request('https://www.millet.jp' + path)
            self.assertEqual(1, len(calls))

    def test_other_pages_and_lookalike_hosts_are_not_rewritten(self):
        for url in ('https://arcteryx.jp/products/unverified',
                    'https://arcteryx.jp.example/products/beta-jacket-m',
                    'https://www.millet.jp/collections/activities/products/miv012480'):
            calls = []
            def fetch(target, headers, timeout):
                calls.append(headers)
                return {'status': 200, 'headers': {}, 'body': b'<html></html>'}
            Catalog({}, fetch).request(url)
            self.assertNotIn('User-Agent', calls[0])

    def test_redirect_clears_compatibility_headers(self):
        calls = []
        def fetch(target, headers, timeout):
            calls.append(headers)
            if len(calls) == 1:
                return {'status': 302, 'headers': {'location': 'https://arcteryx.jp/products/unverified'}, 'body': b''}
            return {'status': 200, 'headers': {}, 'body': b'<html></html>'}
        Catalog({}, fetch).request('https://arcteryx.jp/products/beta-jacket-m')
        self.assertNotIn('User-Agent', calls[1])


if __name__ == '__main__':
    unittest.main()
