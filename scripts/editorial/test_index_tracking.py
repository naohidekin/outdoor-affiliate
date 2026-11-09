import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from index_tracking import instant, track_publications


class IndexTrackingTests(unittest.TestCase):
    def test_verified_revision_is_inspected_at_publication_then_days_one_and_seven(self):
        at = '2026-11-10T09:00:00+09:00'
        url = 'https://camp-gear-lab.com/articles/example'
        publication = dict(at=at, url=url, revision='revision', verified=True,
                           remoteUpdatedAt='2026-11-10T00:00:00Z',
                           readback=dict(verified=True, fingerprint='revision'))
        job = dict(id='article', revision='revision', publication=publication)
        draft = dict(id='draft', revision='revision', publication=None)
        config = dict(indexTrackingEnabled=True, indexTrackingSince=at)
        started = instant(at)

        def save(path, value):
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(value))

        with (tempfile.TemporaryDirectory() as directory,
              patch('index_tracking.read_sitemap', return_value={url: at}),
              patch('index_tracking.inspect_url', side_effect=[
                  {'verdict': 'NEUTRAL'}, {'verdict': 'NEUTRAL'},
                  {'verdict': 'PASS', 'googleCanonical': url}]) as inspect):
            root = Path(directory)
            for day, calls in [(0, 1), (0, 1), (1, 2), (6, 2), (7, 3), (8, 3)]:
                result = track_publications([draft, job], root, {}, config,
                                            started + timedelta(days=day), save)
                self.assertEqual(len(result), 1)
                self.assertEqual(inspect.call_count, calls)
            self.assertEqual(result[0]['latest']['sitemap'], 'current')
            self.assertEqual(result[0]['latest']['index'], 'indexed')
            self.assertIsNone(result[0]['nextAt'])
