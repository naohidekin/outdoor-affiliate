"""Offline cross-route account fence contract tests."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from account_fence import AccountFence


BINDING = {'organizationId': '6adf7fbb37d17051a678fba0',
           'channelId': '6adfd45e2f1f5ed648e05a86',
           'xAccountId': '1343879420470206464'}


class AccountFenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / ('account-' + BINDING['xAccountId'] + '.cross-route.json')
        self.path.write_text(json.dumps({'version': 1, 'binding': BINDING, 'entries': []}) + '\n')
        self.path.chmod(0o600)
        self.fence = AccountFence(self.path, BINDING)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_or_changed_binding_never_bootstraps_empty_authority(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, 'gearman_shared_fence_missing'):
            self.fence.load()
        self.assertFalse(self.path.exists())

    def test_pending_intent_is_private_durable_and_conflicts_fail_closed(self):
        intent = {'operationId': 'camp:' + 'a' * 64, 'route': 'camp',
                  'account': 'camp_gear_lab', 'channelId': BINDING['channelId'],
                  'parentCount': 1, 'dueAt': None, 'requestHash': 'b' * 64}
        self.fence.intent(intent)
        value = self.fence.load()
        self.assertEqual('pending_intent', value['entries'][0]['phase'])
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)
        with self.assertRaisesRegex(ValueError, 'gearman_shared_fence_conflict'):
            self.fence.intent(dict(intent, requestHash='c' * 64))

    def test_accept_requires_original_intent_and_exact_buffer_identity(self):
        intent = {'operationId': 'camp:' + 'a' * 64, 'route': 'camp',
                  'account': 'camp_gear_lab', 'channelId': BINDING['channelId'],
                  'parentCount': 1, 'dueAt': None, 'requestHash': 'b' * 64}
        self.fence.intent(intent)
        self.fence.accept(intent['operationId'], 'buffer-1', '2026-11-23T03:17:00Z')
        entry = self.fence.load()['entries'][0]
        self.assertEqual(('accepted', 'buffer-1', '2026-11-23T03:17:00Z'),
                         (entry['phase'], entry['bufferPostId'], entry['dueAt']))
        with self.assertRaisesRegex(ValueError, 'gearman_shared_fence_conflict'):
            self.fence.accept(intent['operationId'], 'buffer-2', entry['dueAt'])

    def test_verified_public_identity_moves_accepted_occupancy_to_actual_root(self):
        intent = {'operationId': 'camp:' + 'a' * 64, 'route': 'camp',
                  'account': 'camp_gear_lab', 'channelId': BINDING['channelId'],
                  'parentCount': 1, 'dueAt': None, 'requestHash': 'b' * 64}
        self.fence.intent(intent)
        self.fence.accept(intent['operationId'], 'buffer-1', '2026-11-23T03:17:00Z')
        self.fence.posted(intent['operationId'], 'buffer-1', '12345',
                          '2026-11-23T03:17:03Z')
        entry = self.fence.load()['entries'][0]
        self.assertEqual(('terminal_posted', '12345', '2026-11-23T03:17:03Z'),
                         (entry['phase'], entry['publicPostId'], entry['actualAt']))

    def test_exact_draft_rollback_releases_only_the_accepted_attempt(self):
        intent = {'operationId': 'camp:schedule:' + 'a' * 64, 'route': 'camp',
                  'account': 'camp_gear_lab', 'channelId': BINDING['channelId'],
                  'parentCount': 1, 'dueAt': None, 'requestHash': 'b' * 64}
        self.fence.intent(intent)
        self.fence.accept(intent['operationId'], 'buffer-1', '2026-11-23T03:17:00Z')
        self.fence.begin_rollback(intent['operationId'], 'buffer-1')
        self.fence.rolled_back(intent['operationId'], 'buffer-1')
        self.assertEqual('terminal_rolled_back', self.fence.load()['entries'][0]['phase'])
        next_intent = dict(intent, operationId=intent['operationId'] + ':attempt:2',
                           requestHash='c' * 64)
        self.fence.intent(next_intent)
        self.fence.accept(next_intent['operationId'], 'buffer-1', '2026-11-24T03:17:00Z')
        self.assertEqual('accepted', self.fence.load()['entries'][1]['phase'])

    def test_node_buffer_reported_terminal_schema_is_readable_without_native_claim(self):
        entry = {'operationId': 'normal:x-approval:' + 'a' * 64, 'route': 'normal',
                 'account': 'camp_gear_lab', 'channelId': BINDING['channelId'],
                 'parentCount': 1, 'requestHash': 'b' * 64,
                 'phase': 'terminal_buffer_reported_sent', 'bufferPostId': 'buffer-1',
                 'dueAt': '2026-11-23T03:17:00Z', 'reportedPostId': '12345',
                 'sentAt': '2026-11-23T03:17:03Z',
                 'publicUrl': 'https://x.com/camp_gear_lab/status/12345'}
        self.path.write_text(json.dumps({'version': 1, 'binding': BINDING,
                                         'entries': [entry]}) + '\n')
        self.path.chmod(0o600)
        self.assertEqual(entry, self.fence.load()['entries'][0])


if __name__ == '__main__':
    unittest.main()
