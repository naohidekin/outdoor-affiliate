"""Offline tests for the bounded Buffer GraphQL transport."""
import json
import unittest

from buffer_api import BufferAPI


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        return self.response.pop(0) if isinstance(self.response, list) else self.response


class BufferAPITests(unittest.TestCase):
    def test_fixed_endpoint_bearer_and_variables(self):
        transport = Transport({'data': {'post': {'id': 'post-1'}}})
        api = BufferAPI('memory-secret', transport=transport)
        self.assertEqual(api.post('post-1'), {'id': 'post-1'})
        url, headers, body, timeout = transport.calls[0]
        self.assertEqual(url, 'https://api.buffer.com')
        self.assertEqual(headers['Authorization'], 'Bearer memory-secret')
        self.assertEqual(body['variables'], {'input': {'id': 'post-1'}})
        self.assertNotIn('memory-secret', json.dumps(body))
        self.assertEqual(timeout, 20)

    def test_rejects_non_buffer_endpoint_and_missing_key(self):
        for endpoint in ('http://api.buffer.com', 'https://api.buffer.com.evil.test',
                         'https://api.buffer.com/graphql', 'https://api.buffer.com:443'):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, 'buffer_endpoint_invalid'):
                BufferAPI('key', endpoint=endpoint)
        with self.assertRaisesRegex(ValueError, 'buffer_api_key_missing'):
            BufferAPI('')

    def test_graphql_and_typed_errors_fail_closed(self):
        for response in ({'errors': [{'message': 'no'}]}, {'data': {'createPost': {
                '__typename': 'InvalidInputError', 'message': 'bad'}}}):
            with self.subTest(response=response):
                api = BufferAPI('key', transport=Transport(response))
                with self.assertRaises(ValueError):
                    api.create_post({'channelId': 'channel'})

    def test_preflight_requires_exact_org_and_channel(self):
        good = {'data': {'account': {'organizations': [{'id': 'org'}]},
                         'channel': {'id': 'channel', 'organizationId': 'org', 'service': 'twitter'}}}
        api = BufferAPI('key', transport=Transport(good))
        self.assertEqual(api.preflight('org', 'channel')['id'], 'channel')
        bad = {'data': {'account': {'organizations': [{'id': 'other'}]}, 'channel': None}}
        with self.assertRaisesRegex(ValueError, 'buffer_binding_mismatch'):
            BufferAPI('key', transport=Transport(bad)).preflight('org', 'channel')

    def test_posts_rejects_unbounded_second_page(self):
        response = {'data': {'posts': {'edges': [], 'pageInfo': {'hasNextPage': True}}}}
        with self.assertRaisesRegex(ValueError, 'buffer_posts_unbounded'):
            BufferAPI('key', transport=Transport(response)).posts('org', 'channel', 'a', 'b')

    def test_bounded_channel_discovery_returns_exact_binding(self):
        transport = Transport([
            {'data': {'account': {'organizations': [{'id': 'org'}]}}},
            {'data': {'channels': [{'id': 'channel', 'organizationId': 'org', 'service': 'twitter',
                                    'serviceId': '123', 'linkShortening': {'isEnabled': False}}]}}])
        result = BufferAPI('key', transport=transport).discover_channel('channel', '123')
        self.assertEqual({key: result[key] for key in ('organizationId', 'channelId', 'xAccountId')},
                         {'organizationId': 'org', 'channelId': 'channel', 'xAccountId': '123'})

    def test_channel_discovery_has_hard_organization_bound(self):
        response = {'data': {'account': {'organizations': [{'id': str(i)} for i in range(4)]}}}
        with self.assertRaisesRegex(ValueError, 'buffer_organization_discovery_unbounded'):
            BufferAPI('key', transport=Transport(response)).discover_channel('channel', '123')

    def test_retains_only_rate_limit_headers_and_bounds_body(self):
        response = (b'{"data":{"post":{"id":"p"}}}', [
            ('RateLimit', '"150-in-15min";r=98;t=897'),
            ('RateLimit', '"600-in-1day";r=598;t=86397'),
            ('RateLimit', '"3000-in-30days";r=2969;t=696980'),
            ('RateLimit-Policy', '"150-in-15min";q=150;w=900'),
            ('RateLimit-Policy', '"600-in-1day";q=600;w=86400'),
            ('RateLimit-Policy', '"3000-in-30days";q=3000;w=2592000'),
            ('X-Secret', 'no')])
        api = BufferAPI('key', transport=Transport(response))
        api.post('p')
        self.assertEqual(len(api.rate_limit_headers['ratelimit']), 3)
        self.assertEqual({item['window'] for item in api.rate_limits}, {900, 86400, 2592000})
        self.assertEqual(next(item['remaining'] for item in api.rate_limits
                              if item['window'] == 2592000), 2969)
        too_large = b'{' + b' ' * (4 * 1024 * 1024) + b'}'
        with self.assertRaisesRegex(ValueError, 'buffer_transport_unknown'):
            BufferAPI('key', transport=Transport(too_large)).post('p')

    def test_429_retains_all_windows_and_retry_after_without_retry(self):
        body = {'errors': [{'message': 'limited',
                            'extensions': {'code': 'RATE_LIMIT_EXCEEDED', 'window': '15m'}}]}
        headers = [('RateLimit', '"150-in-15min";r=0;t=753'),
                   ('RateLimit-Policy', '"150-in-15min";q=150;w=900'),
                   ('Retry-After', '753')]
        transport = Transport((429, json.dumps(body).encode(), headers))
        api = BufferAPI('key', transport=transport)
        with self.assertRaisesRegex(ValueError, 'buffer_rate_limited'):
            api.post('p')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(api.retry_after, 753)
        self.assertEqual(api.rate_limits[0]['remaining'], 0)


if __name__ == '__main__':
    unittest.main()
