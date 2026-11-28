"""Project private page/query rows into bounded controlled intent signals.

Raw query text and hashes of raw query text never leave this module.  The
projection is an observed sample for one owned page, not a diagnosis, market
demand estimate, dominant query, CTR cause, or SERP observation.
"""
import hashlib
import json
import copy
import re

from search_demand import ALIASES, FACET_KEYS, MAX_QUERY_LENGTH, classify_topic

MAX_ROWS = 10000
MAX_TARGETS = 30
MAX_SIGNALS = 5


def _hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def project_page_intent(rows, period, target_urls, *, input_truncated=False):
    """Return one privacy-safe observation per requested canonical target URL."""
    rows = rows if isinstance(rows, list) else []
    targets = list(dict.fromkeys(
        url for url in target_urls[:MAX_TARGETS]
        if isinstance(url, str) and url.startswith('https://')))
    groups = {url: {} for url in targets}
    observed = {url: 0 for url in targets}
    classified = {url: 0 for url in targets}
    for row in rows[:MAX_ROWS]:
        if not isinstance(row, dict) or row.get('url') not in groups:
            continue
        query = row.get('query')
        if (not isinstance(query, str) or not 1 <= len(query) <= MAX_QUERY_LENGTH
                or not query.strip()):
            continue
        url = row['url']
        observed[url] += 1
        facets = classify_topic(query)
        if not any(facets.values()):
            continue
        classified[url] += 1
        controlled = {key: facets[key] for key in FACET_KEYS}
        facet_id = _hash(controlled)
        group = groups[url].setdefault(
            facet_id, {'id': 'page-intent:' + facet_id,
                       'facets': controlled, 'observedRowCount': 0})
        group['observedRowCount'] += 1
    result = {}
    for url in targets:
        signals = sorted(groups[url].values(),
                         key=lambda item: (-item['observedRowCount'], item['id']))[:MAX_SIGNALS]
        evidence = {
            'schemaVersion': 1,
            'status': 'observed_sample' if signals else 'unavailable',
            'targetUrl': url,
            'period': dict(period),
            'signals': signals,
            'coverage': {
                'observedRowCount': observed[url],
                'classifiedRowCount': classified[url],
                'signalsTruncated': len(groups[url]) > MAX_SIGNALS,
                'inputTruncated': input_truncated or len(rows) > MAX_ROWS,
            },
            'rawQueriesExposed': False,
            'diagnosis': False,
            'marketDemand': False,
            'dominantQuery': False,
            'causalGuarantee': False,
            'serpEvidence': {
                'status': 'unconnected',
                'reason': 'serp_collection_not_implemented',
            },
        }
        evidence['projectionHash'] = _hash(evidence)
        result[url] = evidence
    return result


def validate_page_intent(value, *, target_url, period):
    """Validate the complete public-safe observed-sample contract."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    keys = {'schemaVersion', 'status', 'targetUrl', 'period', 'signals',
            'coverage', 'rawQueriesExposed', 'diagnosis', 'marketDemand',
            'dominantQuery', 'causalGuarantee', 'serpEvidence',
            'projectionHash'}
    require(isinstance(value, dict) and set(value) == keys,
            'page intent evidence fields invalid')
    require(value['schemaVersion'] == 1 and value['status'] == 'observed_sample'
            and value['targetUrl'] == target_url and value['period'] == period,
            'page intent target or period invalid')
    signals = value['signals']
    require(isinstance(signals, list) and 1 <= len(signals) <= MAX_SIGNALS,
            'page intent signals invalid')
    ids = []
    for signal in signals:
        require(isinstance(signal, dict)
                and set(signal) == {'id', 'facets', 'observedRowCount'},
                'page intent signal fields invalid')
        facets = signal['facets']
        require(isinstance(facets, dict) and set(facets) == set(FACET_KEYS),
                'page intent facets invalid')
        for key in FACET_KEYS:
            values = facets[key]
            require(isinstance(values, list) and values == sorted(set(values))
                    and all(isinstance(item, str) and item in ALIASES[key]
                            for item in values),
                    'page intent controlled facet invalid')
        facet_id = _hash(facets)
        require(signal['id'] == 'page-intent:' + facet_id
                and type(signal['observedRowCount']) is int
                and signal['observedRowCount'] > 0,
                'page intent signal proof invalid')
        ids.append(signal['id'])
    require(len(ids) == len(set(ids)), 'page intent duplicate signal invalid')
    coverage = value['coverage']
    require(isinstance(coverage, dict) and set(coverage) == {
                'observedRowCount', 'classifiedRowCount', 'signalsTruncated',
                'inputTruncated'}
            and type(coverage['observedRowCount']) is int
            and type(coverage['classifiedRowCount']) is int
            and 0 <= coverage['classifiedRowCount'] <= coverage['observedRowCount'] <= MAX_ROWS
            and type(coverage['signalsTruncated']) is bool
            and type(coverage['inputTruncated']) is bool
            and sum(item['observedRowCount'] for item in signals)
                <= coverage['classifiedRowCount'],
            'page intent coverage invalid')
    require(value['rawQueriesExposed'] is False
            and value['diagnosis'] is False
            and value['marketDemand'] is False
            and value['dominantQuery'] is False
            and value['causalGuarantee'] is False
            and value['serpEvidence'] == {
                'status': 'unconnected',
                'reason': 'serp_collection_not_implemented'},
            'page intent interpretation boundary changed')
    require(isinstance(value['projectionHash'], str)
            and re.fullmatch(r'[a-f0-9]{64}', value['projectionHash']),
            'page intent projection hash invalid')
    projection = {key: copy.deepcopy(item) for key, item in value.items()
                  if key != 'projectionHash'}
    require(value['projectionHash'] == _hash(projection),
            'page intent projection changed')
    return copy.deepcopy(value)
