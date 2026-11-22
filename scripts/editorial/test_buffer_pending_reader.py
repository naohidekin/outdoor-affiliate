"""Offline contracts for complete, channel-bound Buffer reservation reads."""
import copy
import unittest

from buffer_api import BufferAPI
from test_buffer_api import Transport


class PendingReaderTests(unittest.TestCase):
    def post(self):
        return dict(id='p1', channelId='channel', channelService='twitter',
                    status='scheduled', dueAt='2026-11-16T00:00:00Z')

    def read(self, posts=None, *, edges=None, page_info=None):
        if edges is None:
            edges = [{'node': post} for post in (posts or [])]
        response = {'data': {'posts': {'edges': edges, 'pageInfo': (
            {'hasNextPage': False} if page_info is None else page_info)}}}
        transport = Transport(response)
        return BufferAPI('offline', transport=transport).pending_posts('org', 'channel'), transport

    def test_reads_old_created_custom_reservations_without_creation_filter(self):
        posts = [self.post(), dict(self.post(), id='p2', status='sending',
                 dueAt='2026-11-16T09:00:00+09:00'),
                 dict(self.post(), id='p3', status='draft', dueAt=None)]
        posts[0].update(createdAt='2025-01-01T00:00:00Z', isCustomScheduled=True)
        result, transport = self.read(posts)
        self.assertEqual(posts, result)
        value = transport.calls[0][2]['variables']['input']
        self.assertEqual({'organizationId': 'org', 'filter': {'channelIds': ['channel'],
                         'status': ['draft', 'scheduled', 'sending']}}, value)
        self.assertEqual(1, len(transport.calls))

    def test_rejects_wrong_binding_status_missing_and_duplicate_ids(self):
        for changes in ({'id': ''}, {'id': 1}, {'channelId': 'other'},
                        {'channelService': 'facebook'}, {'status': 'sent'}, {'status': []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.read([dict(self.post(), **changes)])
        for field in ('id', 'channelId', 'channelService', 'status', 'dueAt'):
            post = self.post()
            del post[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.read([post])
        with self.assertRaises(ValueError):
            self.read([self.post(), copy.deepcopy(self.post())])

    def test_scheduled_and_sending_require_real_timezone_aware_iso_due_at(self):
        for status in ('scheduled', 'sending'):
            for at in (None, '', 0, '2026-11-16', '2026-11-16T09:00:00',
                       '2026-02-30T09:00:00Z', '2026-11-16 09:00:00Z',
                       '2026-11-16T09:00:00+25:00', '2026-11-16T09:00:00+09:60',
                       '2026-11-16T09:00:00-00:00'):
                with self.subTest(status=status, at=at), self.assertRaises(ValueError):
                    self.read([dict(self.post(), status=status, dueAt=at)])
            for at in ('2026-11-15T15:00:00Z', '2026-11-16T00:00:00+09:00',
                       '2026-11-16T00:00:00.123+09:00'):
                post = dict(self.post(), status=status, dueAt=at)
                self.assertEqual([post], self.read([post])[0])

    def test_malformed_or_incomplete_pages_fail_closed(self):
        self.assertEqual([], self.read()[0])
        for page_info in ({}, {'hasNextPage': True}, {'hasNextPage': 0}, [], 'bad'):
            with self.subTest(page_info=page_info), self.assertRaises(ValueError):
                self.read(page_info=page_info)
        for edges in ([{}], [{'node': None}], [{'node': {}}], [None],
                      [{'node': self.post()}] * 101):
            with self.subTest(edges=edges[:1]), self.assertRaises(ValueError):
                self.read(edges=edges)

    def test_missing_connection_and_partial_graphql_responses_fail_closed(self):
        for response in ({'data': {}}, {'data': {'posts': None}},
                         {'data': {'posts': {'edges': None, 'pageInfo': {'hasNextPage': False}}}},
                         {'data': {'posts': {'edges': [], 'pageInfo': {'hasNextPage': False}}},
                          'errors': [{'message': 'partial result'}]}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                BufferAPI('offline', transport=Transport(response)).pending_posts('org', 'channel')

    def test_invalid_input_binding_is_rejected_without_api_call(self):
        for org, channel in ((None, 'channel'), ('org', None), ('', 'channel'), ('org', ' ')):
            transport = Transport({'data': {}})
            with self.subTest(org=org, channel=channel), self.assertRaisesRegex(
                    ValueError, 'buffer_binding_mismatch'):
                BufferAPI('offline', transport=transport).pending_posts(org, channel)
            self.assertEqual([], transport.calls)

    def test_preflight_requests_timezone_and_schedule_in_same_call(self):
        schedule = [{'day': day, 'paused': False, 'times': ['09:00']}
                    for day in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')]
        channel = {'id': 'channel', 'organizationId': 'org', 'service': 'twitter',
                   'timezone': 'Asia/Tokyo', 'postingSchedule': schedule}
        transport = Transport({'data': {'account': {'organizations': [{'id': 'org'}]},
                                      'channel': channel}})
        self.assertEqual(channel, BufferAPI('offline', transport=transport).preflight('org', 'channel'))
        query = ' '.join(transport.calls[0][2]['query'].split())
        self.assertIn('timezone', query)
        self.assertIn('postingSchedule { day paused times }', query)
        self.assertEqual(1, len(transport.calls))


if __name__ == '__main__':
    unittest.main()
