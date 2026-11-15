import copy
import unittest

from publication_selection import latest_published_jobs


class PublicationSelectionTests(unittest.TestCase):
    def job(self, name, at):
        return {'id': name, 'revision': name, 'publication': {'url': 'https://camp-gear-lab.com/articles/example',
                'revision': name, 'verified': True, 'at': at,
                'readback': {'verified': True, 'fingerprint': name}}}

    def test_latest_public_version_wins_without_changing_old_receipts(self):
        old = self.job('old', '2026-11-09T09:00:00+09:00')
        new = self.job('new', '2026-11-15T00:37:00Z')
        before = copy.deepcopy([new, old])
        self.assertEqual([new], latest_published_jobs([new, old]))
        self.assertEqual(before, [new, old])

    def test_ambiguous_or_missing_version_time_is_not_silently_suppressed(self):
        first = self.job('a', '2026-11-15T09:00:00+09:00')
        second = self.job('b', '2026-11-15T00:00:00Z')
        with self.assertRaises(ValueError):
            latest_published_jobs([first, second])
        second['publication']['at'] = None
        with self.assertRaises(ValueError):
            latest_published_jobs([first, second])

    def test_unverified_readback_cannot_supersede_valid_version(self):
        old = self.job('old', '2026-11-09T09:00:00+09:00')
        bad = self.job('bad', '2026-11-15T09:00:00+09:00')
        bad['publication']['readback']['fingerprint'] = 'different'
        self.assertEqual([old], latest_published_jobs([old, bad]))

    def test_bad_url_group_reports_fault_without_starving_other_articles(self):
        bad = self.job('bad', None)
        good = self.job('good', '2026-11-15T09:00:00+09:00')
        good['publication']['url'] = 'https://camp-gear-lab.com/articles/other'
        faults = []
        self.assertEqual([good], latest_published_jobs([bad, good],
            on_invalid=lambda error, versions: faults.extend(j['id'] for j in versions)))
        self.assertEqual(['bad'], faults)
