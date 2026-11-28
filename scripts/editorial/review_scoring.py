"""Versioned article-only scoring. Applicability and verdicts belong to the program.

Owner WISE-AS 1–4 floors remain independent of the Supervisor's 0–10 scores.
No policy pins, historical reviews, model counters or provider artifacts are changed.
"""
from fractions import Fraction
import math
import json
import re

from wise_contract import passes, valid_scores

VERSION_V1 = 'article-review-scoring-v1'
VERSION = 'article-review-scoring-v2'
SUPPORTED_VERSIONS = (VERSION_V1, VERSION)
ARTICLE_LENGTHS = {'ranking':(5000,8000), 'comparison':(5000,8000), 'guide':(3000,5000),
                   'how-to':(3000,5000), 'review':(2000,3500)}
CRITERIA_FIELDS = ('wise_w', 'wise_i', 'wise_s', 'wise_e', 'wise_ai', 'wise_sense',
                   'affiliate_links', 'comparison_table', 'internal_links', 'faq', 'word_count')
FLAGS = ('facts', 'images', 'affiliate', 'medical', 'render')
THRESHOLD = Fraction(15, 2)


def article_applicability(bundle, version=VERSION):
    if version not in SUPPORTED_VERSIONS: raise ValueError('Unknown article scoring version')
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
    result = {key: ({'applicability': 'not_applicable', 'measured': False,
                   'neutralScore': 7.5, 'reason': na[key]} if key in na else
                  {'applicability': 'applicable', 'evaluationRequired': True})
            for key in CRITERIA_FIELDS}
    if version == VERSION:
        result['word_count'] = {'applicability':'applicable', 'evaluationRequired':False, 'determinedBy':'program'}
    return result


def _number(value):
    if type(value) not in (int, float) or not 0 <= value <= 10 or not math.isfinite(value):
        raise ValueError('Finite numeric article criterion 0–10 required')
    return Fraction(str(value))


def _ratio(value):
    return {'numerator': value.numerator, 'denominator': value.denominator}


def word_count_score(bundle):
    content = bundle['article'].get('content')
    if not isinstance(content, str): raise ValueError('Actual article content required')
    format_name = bundle['brief']['format']; lower, upper = ARTICLE_LENGTHS[format_name]
    if not lower <= len(content) <= upper: raise ValueError('Article length outside existing SKILL limits')
    return {'score':10, 'contentCharacters':len(content), 'format':format_name,
            'minimumCharacters':lower, 'maximumCharacters':upper,
            'method':'python_len_decoded_article_content'}


def _quote_locations(quote, bundle):
    paragraphs = re.split(r'(?:\r?\n[ \t]*){2,}', bundle['article']['content'])
    targets = [('paragraph', paragraphs), ('faq_answer', [q['answer'] for q in bundle['article'].get('faqs', [])])]
    return [{'kind':kind, 'index':index} for kind, items in targets for index, text in enumerate(items)
            for _ in range(text.count(quote))]


def resolve_feedback(feedback, bundle):
    if not isinstance(feedback, list) or len(feedback) > 6:
        raise ValueError('At most six improvements required')
    result = []
    for item in feedback:
        if (not isinstance(item, dict) or set(item) != {'criterion','quote','anchor','nextAction'}
                or not isinstance(item['quote'], str) or not item['quote'].strip() or len(item['quote']) > 240):
            raise ValueError('Feedback wire has no model-selected location')
        locations = _quote_locations(item['quote'], bundle)
        if len(locations) != 1: raise ValueError('Feedback quote must occur exactly once in article or FAQ answers')
        result.append(dict(item, location=locations[0]))
    validate_feedback(result, bundle)
    return result


def validate_feedback(feedback, bundle, criteria=None):
    if not isinstance(feedback, list) or len(feedback) > 6:
        raise ValueError('At most six evidence-bound improvements required')
    if criteria is not None and not isinstance(criteria, dict): raise ValueError('Criterion object required')
    paragraphs = re.split(r'(?:\r?\n[ \t]*){2,}', bundle['article']['content'])
    allowed = {key for key, value in article_applicability(bundle).items()
               if value['applicability'] == 'applicable' and key != 'word_count'}
    for item in feedback:
        if (not isinstance(item, dict) or set(item) != {'criterion','location','quote','anchor','nextAction'}
                or item['criterion'] not in allowed):
            raise ValueError('Invalid improvement criterion or schema')
        location = item['location']
        if (not isinstance(location, dict) or set(location) != {'kind','index'}
                or type(location['index']) is not int or location['index'] < 0
                or location['kind'] not in ('paragraph','faq_answer')):
            raise ValueError('Valid improvement location required')
        targets = paragraphs if location['kind'] == 'paragraph' else [q['answer'] for q in bundle['article'].get('faqs', [])]
        if location['index'] >= len(targets): raise ValueError('Improvement location outside article')
        for key, limit in (('quote',240),('anchor',160),('nextAction',400)):
            if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > limit:
                raise ValueError('Bounded improvement text required')
        if item['quote'] not in targets[location['index']] or _quote_locations(item['quote'], bundle) != [location]:
            raise ValueError('Improvement quote must occur at the exact article location')
    return feedback


def select_feedback(feedback, bundle, criteria):
    """Quarantine unbound advisory quotes; malformed wire remains fatal."""
    if not isinstance(feedback, list) or len(feedback) > 6:
        raise ValueError('At most six improvements required')
    allowed = {key for key, value in article_applicability(bundle).items()
               if value['applicability'] == 'applicable' and key != 'word_count'}
    selected, rejected, accepted = [], [], []
    for index, item in enumerate(feedback):
        if (not isinstance(item, dict) or set(item) != {'criterion','quote','anchor','nextAction'}
                or not isinstance(item['criterion'], str) or item['criterion'] not in allowed):
            raise ValueError('Invalid improvement wire schema or criterion')
        for key, limit in (('quote',240),('nextAction',400)):
            if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > limit:
                raise ValueError('Bounded improvement text required')
        if not isinstance(item['anchor'], str) or not item['anchor'].strip():
            raise ValueError('Bounded improvement text required')
        locations = _quote_locations(item['quote'], bundle)
        if len(locations) != 1:
            rejected.append({'index':index, 'criterion':item['criterion'],
                             'reason':'quote_missing' if not locations else 'quote_ambiguous'})
            continue
        if len(item['anchor']) > 160:
            rejected.append({'index':index, 'criterion':item['criterion'],
                             'reason':'anchor_over_limit',
                             'actualCharacters':len(item['anchor']), 'maxCharacters':160})
            continue
        selected.append(dict(item, location=locations[0])); accepted.append(index)
    validate_feedback(selected, bundle)
    low = {key for key, value in criteria.items() if _number(value) < THRESHOLD}
    return selected, {'status':('partial' if selected else 'rejected') if rejected else 'valid',
                      'rawItems':feedback, 'acceptedIndices':accepted, 'rejected':rejected,
                      'missingLowCriteria':sorted(low - {item['criterion'] for item in selected})}


def calculate(criteria, bundle, version=VERSION):
    applicability = article_applicability(bundle, version)
    active = [key for key in CRITERIA_FIELDS
              if applicability[key]['applicability'] == 'applicable']
    ai_fields = set(active) - ({'word_count'} if version == VERSION else set())
    if not isinstance(criteria, dict) or set(criteria) != ai_fields:
        raise ValueError('Exactly applicable article criteria required; NA is unmeasured')
    word_count = word_count_score(bundle) if version == VERSION else None
    total = sum((_number(criteria[key]) for key in ai_fields), Fraction())
    if word_count is not None: total += word_count['score']
    active_mean = total / len(active)
    na_count = len(CRITERIA_FIELDS) - len(active)
    total += na_count * THRESHOLD
    mean = total / len(CRITERIA_FIELDS)
    result = {'scoringVersion': version, 'applicability': applicability,
            'score': float(mean),
            'calculation': {'method': 'neutral-na-mean-11', 'sum': _ratio(total),
                            'activeMean': _ratio(active_mean),
                            'normalized11Mean': _ratio(mean),
                            'scoreMeaning': 'normalized11Mean_not_cross_applicability_comparable',
                            'threshold': _ratio(THRESHOLD),
                            'activeCount': len(active), 'naCount': na_count,
                            'thresholdMet': mean >= THRESHOLD}}
    if version == VERSION:
        result['admissionMode'] = 'hard_checks_and_owner_floors'
        result['calculation'].update(aggregateRole='advisory', admission='hard_checks_and_owner_floors', wordCount=word_count)
    return result


def verdict(review, calculation):
    if (not valid_scores(review.get('wiseScores'))
            or any(type(review.get(flag)) is not bool for flag in FLAGS)
            or not isinstance(review.get('issues'), list)
            or any(not isinstance(issue, str) for issue in review['issues'])):
        raise ValueError('Complete article flags, issues and owner WISE-AS scores required')
    advisory = calculation.get('aggregateRole') == 'advisory'
    hard = review.get('hardChecks')
    if advisory and (not isinstance(hard, dict) or set(hard) != {'structure'} or hard['structure'] is not True): return False
    return ((advisory or calculation['thresholdMet']) and passes(review['wiseScores'])
            and not review['issues'] and all(review[flag] for flag in FLAGS))


def verify_review(review, bundle):
    """Recompute new persisted reviews; never upgrade a legacy review."""
    version = review.get('scoringVersion')
    if version not in SUPPORTED_VERSIONS:
        raise ValueError('Unknown article scoring version')
    expected = calculate(review.get('criteria'), bundle, version)
    if version == VERSION:
        validate_feedback(review.get('improvementFeedback'), bundle, review.get('criteria'))
        metadata = review.get('feedbackValidation')
        if not isinstance(metadata, dict): raise ValueError('Feedback selection metadata required')
        selected, expected_metadata = select_feedback(metadata.get('rawItems'), bundle, review['criteria'])
        if (json.dumps(metadata, sort_keys=True, allow_nan=False) != json.dumps(expected_metadata, sort_keys=True, allow_nan=False)
                or selected != review['improvementFeedback']):
            raise ValueError('Feedback selection mismatch')
        if not isinstance(review.get('hardChecks'), dict) or set(review['hardChecks']) != {'structure'} or type(review['hardChecks']['structure']) is not bool:
            raise ValueError('Program structural evidence required')
    # Strict JSON equality also rejects bool-as-number mutations in calculations.
    for field in ('scoringVersion', 'applicability', 'calculation', 'score') + (('admissionMode',) if version == VERSION else ()):
        if json.dumps(review.get(field), sort_keys=True, allow_nan=False) != json.dumps(
                expected[field], sort_keys=True, allow_nan=False):
            raise ValueError('Article scoring calculation or applicability mismatch')
    if type(review.get('passed')) is not bool or review['passed'] != verdict(review, expected['calculation']):
        raise ValueError('Article scoring verdict mismatch')
    return expected
