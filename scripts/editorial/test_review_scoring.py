"""Exact arithmetic, applicability and persisted article-review contract regressions."""
import copy
import unittest

from review_scoring import (CRITERIA_FIELDS, VERSION_V1 as VERSION, VERSION as CURRENT_VERSION, article_applicability,
                            calculate as current_calculate, verify_review)
from nonproduct_contract_fixture import fixture
from test_models import bundle


def calculate(criteria, bundle):
    return current_calculate(criteria, bundle, version=VERSION)


class ReviewScoringTests(unittest.TestCase):
    def test_commercial_guide_cannot_avoid_comparison_by_format_change(self):
        b = bundle()
        for format_name in ('guide', 'how-to', 'review', 'ranking', 'comparison'):
            b['brief']['format'] = format_name
            result = calculate(dict.fromkeys(CRITERIA_FIELDS, 8), b)
            self.assertEqual(8, result['score'])
            self.assertEqual(0, result['calculation']['naCount'])
            self.assertEqual({'applicability': 'applicable', 'evaluationRequired': True},
                             result['applicability']['comparison_table'])
            active = {k: 8 for k in CRITERIA_FIELDS if k != 'comparison_table'}
            with self.assertRaises(ValueError): calculate(active, b)

    def test_strict_nonproduct_has_two_na_but_invalid_bundle_cannot_claim_na(self):
        b = fixture()['bundle']; b['brief'] = {'format': 'guide'}
        active = {k: 7.5 for k in CRITERIA_FIELDS
                  if k not in ('affiliate_links', 'comparison_table')}
        self.assertEqual(2, calculate(active, b)['calculation']['naCount'])
        result = calculate(active, b)
        self.assertEqual({'applicability': 'not_applicable', 'measured': False,
                          'neutralScore': 7.5, 'reason': 'validated_nonproduct_no_product_comparison'},
                         result['applicability']['comparison_table'])
        for score in (0, 5, 7.5, 10):
            with self.assertRaises(ValueError): calculate(dict(active, comparison_table=score), b)
        for earned, expected in ((7.4, False), (7.5, True), (7.6, True)):
            scored = calculate(dict.fromkeys(active, earned), b)
            self.assertEqual(expected, scored['calculation']['thresholdMet'])
            self.assertEqual(expected, earned >= 7.5)
            self.assertEqual(str(earned), str(float(scored['calculation']['activeMean']['numerator'] /
                                                   scored['calculation']['activeMean']['denominator'])))
        b['article']['content'] += '\n{{product:forged}}'
        with self.assertRaises(ValueError):
            calculate(active, b)

    def test_ranking_and_comparison_still_require_comparison_score(self):
        for format_name in ('ranking', 'comparison'):
            b = bundle(); b['brief']['format'] = format_name
            result = calculate(dict.fromkeys(CRITERIA_FIELDS, 8), b)
            self.assertEqual(0, result['calculation']['naCount'])
            self.assertTrue(result['applicability']['comparison_table']['evaluationRequired'])

    def test_exact_threshold_no_rounding_and_neutral_na_equivalence(self):
        b = bundle()
        active = dict.fromkeys(CRITERIA_FIELDS, 7.5)
        for last, expected in ((7.499999999999999, False), (7.5, True), (7.500000000000001, True)):
            active['faq'] = last
            result = calculate(active, b)
            self.assertEqual(expected, result['calculation']['thresholdMet'])
            if last < 7.5:
                self.assertEqual(7.5, result['score'])  # display rounds; exact gate still fails
        active = dict.fromkeys(active, 7.4)
        self.assertEqual({'numerator': 37, 'denominator': 5},
                         calculate(active, b)['calculation']['normalized11Mean'])

    def test_bad_numbers_missing_extra_fields_and_unknown_format_rejected(self):
        b = bundle(); active = dict.fromkeys(CRITERIA_FIELDS, 8)
        for bad in (True, False, float('nan'), float('inf'), -1, 11, '8', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                calculate(dict(active, faq=bad), b)
        for bad in ({}, dict(active, extra=8)):
            with self.assertRaises(ValueError): calculate(bad, b)
        b['brief']['format'] = 'unknown'
        with self.assertRaises(ValueError): calculate(active, b)

    def test_new_record_recomputes_and_rejects_tampering(self):
        b = bundle(); criteria = dict.fromkeys(CRITERIA_FIELDS, 8)
        value = dict(calculate(criteria, b), criteria=criteria, passed=True,
                     wiseScores=dict(w=2, i=2, s=2, e=2, ai=3, sense=2), issues=[],
                     facts=True, images=True, affiliate=True, medical=True, render=True)
        verify_review(value, b)
        for change in ({'score': 10}, {'passed': False}, {'scoringVersion': 'unknown'},
                       {'calculation': {}}, {'applicability': {}}, {'issues': ['blocker']},
                       {'facts': False}, {'wiseScores': dict(value['wiseScores'], ai=2)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_review(dict(value, **change), b)
        self.assertEqual(VERSION, value['scoringVersion'])


class LedgerArticleScoringTests(unittest.TestCase):
    def recorded_review(self, b):
        from models import Models
        from test_models import ENV, Fake, response, article_review_value, FLAGS
        from ledger import fingerprint
        b['articleReviewScoring']={'version':CURRENT_VERSION}
        value = Models(ENV, Fake(response(article_review_value(b)))).review(
            b, dict(editorialRules='rubric', evidence=FLAGS, structural={'passed':True}))
        value.update(evidence=dict(FLAGS), fingerprint=fingerprint(b),
                     polish={'model': 'gemini-3.8-flash', 'validated': True})
        return value

    def test_ledger_recomputes_new_review_and_all_partial_version_strips_fail(self):
        from ledger import valid_review, fingerprint
        b = bundle(); value = self.recorded_review(b)
        before = copy.deepcopy(value)
        valid_review(value, fingerprint(b), b)
        for field in ('scoringVersion', 'calculation', 'applicability'):
            changed = copy.deepcopy(value); changed.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                valid_review(changed, fingerprint(b), b)
        for change in ({'score': 10}, {'criteria': dict(value['criteria'], faq=0)},
                       {'wiseScores': dict(value['wiseScores'], ai=2)},
                       {'issues': ['blocker']}, {'render': False}, {'scoringVersion': 'v999'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                valid_review(dict(value, **change), fingerprint(b), b)
        self.assertEqual(before, value)

    def test_bundle_marker_prevents_complete_new_field_strip_into_legacy(self):
        from ledger import valid_review, fingerprint
        b = bundle(); b['articleReviewScoring'] = {'version': VERSION}
        value = self.recorded_review(b)
        valid_review(value, fingerprint(b), b)
        for key in ('scoringVersion', 'calculation', 'applicability'):
            value.pop(key)
        with self.assertRaisesRegex(ValueError, 'bound article scoring version required'):
            valid_review(value, fingerprint(b), b)
        for marker in (None, {}, {'version': 'future'}):
            b['articleReviewScoring'] = marker
            with self.assertRaises(ValueError): valid_review(value, fingerprint(b), b)

    def test_ledger_near_threshold_display_pass_is_still_rejected(self):
        from ledger import valid_review, fingerprint
        b = bundle(); value = self.recorded_review(b)
        b['articleReviewScoring']={'version':VERSION}
        value['criteria'] = dict.fromkeys(CRITERIA_FIELDS, 7.5)
        value['criteria']['faq'] = 7.499999999999999
        value.update(calculate(value['criteria'], b))
        self.assertEqual(7.5, value['score'])
        self.assertFalse(value['calculation']['thresholdMet'])
        with self.assertRaises(ValueError): valid_review(value, fingerprint(b), b)

    def test_legacy_review_stays_unchanged_without_new_markers(self):
        from ledger import valid_review
        value = dict(score=8, passed=True, fingerprint='old',
                     evidence=dict.fromkeys(('facts', 'images', 'affiliate', 'medical', 'render'), True),
                     polish={'model': 'gemini-3.8-flash', 'validated': True})
        before = copy.deepcopy(value)
        valid_review(value, 'old')
        self.assertEqual(before, value)
        with self.assertRaises(ValueError): valid_review(dict(value, passed=False), 'old')

    def test_ledger_new_nonproduct_review_requires_same_typed_na_binding(self):
        from ledger import valid_review, fingerprint
        from models import Models
        from test_models import ENV, Fake, response, article_review_value, FLAGS
        b = fixture()['bundle']; b['brief'] = {'format': 'guide'}; b['article']['content']+='\n\n'+'根拠のある説明。'*400; b['articleReviewScoring']={'version':CURRENT_VERSION}
        from topic_selection import nonproduct_affiliate_review
        evidence = dict(FLAGS, affiliate=nonproduct_affiliate_review(b))
        value = Models(ENV, Fake(response(article_review_value(b)))).review(
            b, dict(editorialRules='rubric', evidence=evidence, structural={'passed':True}))
        value.update(evidence=evidence, fingerprint=fingerprint(b),
                     polish={'model': 'gemini-3.8-flash', 'validated': True})
        valid_review(value, fingerprint(b), b)
        bad = copy.deepcopy(b); bad['article']['content'] += '{{product:forged}}'
        with self.assertRaises(ValueError): valid_review(value, fingerprint(bad), bad)


if __name__ == '__main__':
    unittest.main()
