"""Explicit owner scope, bounded budget and duplicate protection; offline only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import unittest
from supplemental_topics import load_batch, resolve_batch, validate_batch
from test_supplemental_20261122 import product


class WinterDepthBatchTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_batch(Path(__file__).with_name('supplemental-winter-depth-20261122.json'))
        self.now = datetime(2026, 11, 24, tzinfo=timezone(timedelta(hours=9)))

    def test_no_products_are_created_or_treated_as_verified_by_manifest(self):
        result = resolve_batch(self.manifest, {'products': [], 'articles': []}, [], self.now)
        self.assertEqual('source_hold', result['status'])
        self.assertEqual(0, result['readyCount'])
        self.assertTrue(all(s['reason'] == 'catalog_product_not_verified' for s in result['slots']))
        for field, value in (('batchCallCap', 97), ('maxArticles', 4),
                             ('socialEligiblePeriod', '2026-11-27')):
            bad = copy.deepcopy(self.manifest)
            bad[field] = value
            with self.assertRaises(ValueError):
                validate_batch(bad)

    def test_preexisting_r1_theme_is_not_recreated_in_a_new_namespace(self):
        products = [product(pid) for slot in self.manifest['slots'] for pid in slot['productIds']]
        prior = {'slug': self.manifest['slots'][0]['slug']}
        result = resolve_batch(self.manifest, {'products': products, 'articles': [prior]}, [], self.now)
        self.assertEqual('duplicate_theme', result['slots'][0]['reason'])
        self.assertEqual(2, result['readyCount'])


if __name__ == '__main__':
    unittest.main()
