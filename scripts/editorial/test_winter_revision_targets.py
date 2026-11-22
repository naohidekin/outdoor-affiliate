"""Exact revision targets, using synthetic snapshots only."""
import copy
import unittest

from revisions import TARGETS, validated_context, validate_context


EXISTING = [('article-024', 'firepit-beginner-guide'),
            ('article-005', 'single-burner-ranking'),
            ('article-002', 'landlock-vs-landnest-shelter')]
ADDITIONS = [
    ('3082b43c-a612-4ae0-926e-8bd86c6ab84e', 'autumn-camp-classic-fleece-comparison'),
    ('winter-camp-heating-comparison-p1', 'winter-camp-heating-comparison'),
    ('camp-kerosene-stove-8xzl2p', 'camp-kerosene-stove-comparison'),
    ('article-010', 'rainwear-ranking'),
    ('article-043', 'autumn-camp-clothing-layering-guide'),
]


def fixture(id, slug):
    stamp = '2026-11-01T00:00:00+09:00'
    product = dict(id='fixture-product', updatedAt=stamp)
    return dict(baseArticle=dict(id=id, slug=slug, status='published', content='Fixture source',
                                 productIds=[product['id']], createdAt=stamp,
                                 updatedAt=stamp, publishedAt=stamp),
                changeSummary='Fixture correction', editorialCorrectionInstructions='Fixture only',
                verifiedAuthorFacts=[], targetProductIds=[product['id']], productRemovalReasons={},
                baseProducts=[product], candidateProducts=[copy.deepcopy(product)])


class WinterRevisionTargetsTests(unittest.TestCase):
    def test_exact_allowlist_and_priority(self):
        self.assertEqual(EXISTING + ADDITIONS, list(TARGETS.items()))
        for id, slug in EXISTING + ADDITIONS:
            with self.subTest(id=id):
                context = validated_context(fixture(id, slug))
                self.assertEqual(context, validate_context(context))

    def test_swapped_slugs_and_unlisted_targets_rejected(self):
        pairs = EXISTING + ADDITIONS
        for id, slug in pairs:
            for other_id, other_slug in pairs:
                if other_id == id:
                    continue
                with self.subTest(id=id, slug=other_slug), self.assertRaisesRegex(ValueError, 'target invalid'):
                    validated_context(fixture(id, other_slug))
            for bad_id, bad_slug in [('unlisted', slug), (id, slug + '-unlisted'), ('unlisted', 'unlisted')]:
                with self.subTest(id=bad_id, slug=bad_slug), self.assertRaisesRegex(ValueError, 'target invalid'):
                    validated_context(fixture(bad_id, bad_slug))

    def test_new_targets_keep_product_subset_and_baseline_binding(self):
        for id, slug in ADDITIONS:
            with self.subTest(id=id):
                value = fixture(id, slug)
                value['targetProductIds'].append('new-product')
                with self.assertRaisesRegex(ValueError, 'target product set invalid'):
                    validated_context(value)
                context = validated_context(fixture(id, slug))
                context['baseArticle']['content'] += ' drift'
                with self.assertRaisesRegex(ValueError, 'baseline binding changed'):
                    validate_context(context)


if __name__ == '__main__':
    unittest.main()
