"""Versioned article-only scoring. Applicability and verdicts belong to the program.

Owner WISE-AS 1–4 floors remain independent of the Supervisor's 0–10 scores.
No policy pins, historical reviews, model counters or provider artifacts are changed.
"""
from fractions import Fraction
import math
import json

from wise_contract import passes, valid_scores

VERSION = 'article-review-scoring-v1'
CRITERIA_FIELDS = ('wise_w', 'wise_i', 'wise_s', 'wise_e', 'wise_ai', 'wise_sense',
                   'affiliate_links', 'comparison_table', 'internal_links', 'faq', 'word_count')
FLAGS = ('facts', 'images', 'affiliate', 'medical', 'render')
THRESHOLD = Fraction(15, 2)


def article_applicability(bundle):
    if not isinstance(bundle, dict):
        raise ValueError('Article bundle required for scoring')
    if not isinstance(bundle.get('brief'), dict) or not isinstance(bundle.get('article'), dict):
        raise ValueError('Article and brief objects required for scoring')
    format_name = bundle['brief'].get('format')
    if format_name not in ('ranking', 'comparison', 'guide', 'how-to', 'review'):
        raise ValueError('Known article format required for scoring')
    ids = (bundle.get('article') or {}).get('productIds')
    if not isinstance(ids, list):
        raise ValueError('Article productIds required for scoring')
    na = {}
    if ids == []:
        from topic_selection import nonproduct_affiliate_review
        # Empty IDs or a caller's N/A assertion are insufficient: validate the
        # full Python-owned source/image/commerce applicability contract.
        nonproduct_affiliate_review(bundle)
        na['affiliate_links'] = 'validated_nonproduct_no_commerce'
        na['comparison_table'] = 'validated_nonproduct_no_product_comparison'
    return {key: ({'applicability': 'not_applicable', 'measured': False,
                   'neutralScore': 7.5, 'reason': na[key]} if key in na else
                  {'applicability': 'applicable', 'evaluationRequired': True})
            for key in CRITERIA_FIELDS}


def _number(value):
    if type(value) not in (int, float) or not 0 <= value <= 10 or not math.isfinite(value):
        raise ValueError('Finite numeric article criterion 0–10 required')
    return Fraction(str(value))


def _ratio(value):
    return {'numerator': value.numerator, 'denominator': value.denominator}


def calculate(criteria, bundle):
    applicability = article_applicability(bundle)
    active = [key for key in CRITERIA_FIELDS
              if applicability[key]['applicability'] == 'applicable']
    if not isinstance(criteria, dict) or set(criteria) != set(active):
        raise ValueError('Exactly applicable article criteria required; NA is unmeasured')
    total = sum((_number(criteria[key]) for key in active), Fraction())
    active_mean = total / len(active)
    na_count = len(CRITERIA_FIELDS) - len(active)
    total += na_count * THRESHOLD
    mean = total / len(CRITERIA_FIELDS)
    return {'scoringVersion': VERSION, 'applicability': applicability,
            'score': float(mean),
            'calculation': {'method': 'neutral-na-mean-11', 'sum': _ratio(total),
                            'activeMean': _ratio(active_mean),
                            'normalized11Mean': _ratio(mean),
                            'scoreMeaning': 'normalized11Mean_not_cross_applicability_comparable',
                            'threshold': _ratio(THRESHOLD),
                            'activeCount': len(active), 'naCount': na_count,
                            'thresholdMet': mean >= THRESHOLD}}


def verdict(review, calculation):
    if (not valid_scores(review.get('wiseScores'))
            or any(type(review.get(flag)) is not bool for flag in FLAGS)
            or not isinstance(review.get('issues'), list)
            or any(not isinstance(issue, str) for issue in review['issues'])):
        raise ValueError('Complete article flags, issues and owner WISE-AS scores required')
    return (calculation['thresholdMet'] and passes(review['wiseScores'])
            and not review['issues'] and all(review[flag] for flag in FLAGS))


def verify_review(review, bundle):
    """Recompute new persisted reviews; never upgrade a legacy review."""
    if review.get('scoringVersion') != VERSION:
        raise ValueError('Unknown article scoring version')
    expected = calculate(review.get('criteria'), bundle)
    # Strict JSON equality also rejects bool-as-number mutations in calculations.
    for field in ('scoringVersion', 'applicability', 'calculation', 'score'):
        if json.dumps(review.get(field), sort_keys=True, allow_nan=False) != json.dumps(
                expected[field], sort_keys=True, allow_nan=False):
            raise ValueError('Article scoring calculation or applicability mismatch')
    if type(review.get('passed')) is not bool or review['passed'] != verdict(review, expected['calculation']):
        raise ValueError('Article scoring verdict mismatch')
    return expected
