"""Bounded post-publication observations derived from sanitized report evidence.

This module never calls a provider, schedules work, changes approval state, or treats
co-occurring editorial features as causes. Receipts are immutable and additive.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

JST = timezone(timedelta(hours=9))
MAX_FILE_BYTES = 128 * 1024
MAX_OBSERVATIONS = 5
MAX_PROJECTED = 3
HASH = re.compile(r'^[a-f0-9]{64}$')
HYPOTHESIS = ('Measured page response co-occurs with these public editorial features; '
              'their contribution is unverified and they are not source facts.')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _receipt_content(value):
    return {key: item for key, item in value.items()
            if key not in ('generatedAt', 'receiptContentSha256')}


def _now(value=None):
    value = value or datetime.now(JST)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('learning_aware_time_required')
    return value.astimezone(JST)


def _text(value, limit):
    if not isinstance(value, str):
        return None
    value = re.sub(r'[\x00-\x1f\x7f]+', ' ', value).strip()
    return value[:limit] if value else None


def _article_url(job):
    publication = job.get('publication') if isinstance(job, dict) else None
    bundle = job.get('bundle') if isinstance(job, dict) else None
    article = bundle.get('article') if isinstance(bundle, dict) else None
    if not isinstance(publication, dict) or not isinstance(bundle, dict) or not isinstance(article, dict):
        return None
    readback = publication.get('readback') if isinstance(publication, dict) else None
    revision = job.get('revision') if isinstance(job, dict) else None
    url = publication.get('url') if isinstance(publication, dict) else None
    slug = article.get('slug') if isinstance(article, dict) else None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (publication.get('verified') is not True or publication.get('revision') != revision
            or not isinstance(readback, dict) or readback.get('verified') is not True
            or readback.get('fingerprint') != revision or not isinstance(revision, str)
            or not HASH.fullmatch(revision) or not isinstance(slug, str) or not slug
            or parsed.scheme != 'https' or parsed.hostname != 'camp-gear-lab.com'
            or parsed.username or parsed.password or port not in (None, 443)
            or parsed.query or parsed.fragment or '%' in parsed.path
            or parsed.path != '/articles/' + slug):
        return None
    return url


def _publication_at(job):
    if not isinstance(job, dict) or not isinstance(job.get('publication'), dict):
        return None
    try:
        value = datetime.fromisoformat(job['publication']['at'].replace('Z', '+00:00'))
        return value if value.tzinfo is not None else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _period(source):
    if not isinstance(source, dict) or source.get('status') != 'ok':
        return None
    try:
        start = datetime.fromisoformat(source['startDate']).date()
        end = datetime.fromisoformat(source['endDate']).date()
        zone = ZoneInfo(source['dateBasis'])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return None
    return (start, end, zone) if start <= end else None


def _window(publication_at, source):
    period = _period(source)
    if not publication_at or not period:
        return None
    start, end, zone = period
    published = publication_at.astimezone(zone).date()
    if published > end:
        return None
    return ('current_revision_full_window' if published <= start
            else 'overlap_unattributed')


def _source_receipt(job):
    article = ((job.get('bundle') or {}).get('article') or {})
    context = (article.get('generationMeta') or {}).get('editorialContext') or {}
    value = context.get('sourceReceiptSha256')
    return value if HASH.fullmatch(str(value or '')) else None


def _features(article):
    content = article.get('content') if isinstance(article, dict) else ''
    content = content if isinstance(content, str) else ''
    headings = [_text(value, 120) for value in
                re.findall(r'(?m)^#{2,4}\s+(.+?)\s*$', content)]
    headings = [value for value in headings if value][:5]
    features = []
    if headings:
        features.append('section_headings')
    if isinstance(article.get('faqs'), list) and article['faqs']:
        features.append('faq')
    if re.search(r'(?m)^\s*[-*]\s+\S', content):
        features.append('bullet_list')
    if re.search(r'(?m)^\s*\d+[.)]\s+\S', content):
        features.append('numbered_steps')
    if len(re.findall(r'(?m)^\s*\|.*\|\s*$', content)) >= 2:
        features.append('table')
    return headings, features[:5]


def _quality_binding(job):
    review = job.get('review') if isinstance(job, dict) else None
    marker = (job.get('bundle') or {}).get('articleReviewScoring') if isinstance(job, dict) else None
    return {
        'reviewPassed': isinstance(review, dict) and review.get('passed') is True,
        'scoringVersion': (marker or {}).get('version') if isinstance(marker, dict) else None,
        'aggregateScoreUse': 'advisory_only',
    }


def _page_map(source, key, field):
    rows = source.get(key) if isinstance(source, dict) else None
    if not isinstance(rows, list):
        return {}
    result = {}
    for row in rows[:1000]:
        if isinstance(row, dict) and isinstance(row.get(field), str):
            result[row[field]] = row
    return result


def build_receipt(kind, period, evidence, jobs, now=None):
    """Build one bounded receipt from analytics._context/build_report evidence."""
    if kind not in ('weekly', 'monthly') or not isinstance(period, str):
        raise ValueError('learning_report_scope_invalid')
    now = _now(now)
    evidence = evidence if isinstance(evidence, dict) else {}
    current, ga4 = evidence.get('current'), evidence.get('ga4')
    gsc_rows = _page_map(current, 'pages', 'url')
    ga4_rows = _page_map(ga4, 'landingPages', 'path')
    metric_source = {'kind': kind, 'period': period, 'current': current, 'ga4': ga4}
    source_hash = _hash(metric_source)
    candidates = []
    for job in (jobs if isinstance(jobs, list) else [])[:1000]:
        url = _article_url(job)
        published = _publication_at(job)
        if not url or not published:
            continue
        article = ((job.get('bundle') or {}).get('article') or {})
        gsc = gsc_rows.get(url)
        path = urlsplit(url).path
        ga = ga4_rows.get(path)
        gsc_window = _window(published, current) if gsc else None
        ga4_window = _window(published, ga4) if ga else None
        # A missing page row is absence of a measurement, never a measured zero.
        if not (gsc and gsc_window) and not (ga and ga4_window):
            continue
        headings, features = _features(article)
        source_receipt = _source_receipt(job)
        observation = {
            'article': {
                'id': _text(job.get('id'), 160), 'title': _text(article.get('title'), 160),
                'url': url, 'revision': job['revision'], 'headings': headings,
                'publicFeatures': features, 'sourceReceiptSha256': source_receipt,
            },
            'qualityGate': _quality_binding(job),
            'measurement': {
                'gsc': ({key: gsc.get(key) for key in ('clicks', 'impressions', 'ctr', 'position')}
                        | {'metricScope': 'page', 'versionWindow': gsc_window,
                           'period': {key: current.get(key) for key in
                                      ('startDate', 'endDate', 'dateBasis', 'settledThrough')}})
                       if gsc and gsc_window else None,
                'ga4': ({key: ga.get(key) for key in ('sessions', 'engagedSessions', 'keyEvents')}
                        | {'coverageVerified': ga4.get('coverageVerified') is True,
                           'versionWindow': ga4_window,
                           'period': {key: ga4.get(key) for key in
                                      ('startDate', 'endDate', 'dateBasis')}})
                       if ga and ga4_window else None,
                'comparability': ('same_dates_different_timezones_partial'
                                  if gsc and ga and current.get('startDate') == ga4.get('startDate')
                                  and current.get('endDate') == ga4.get('endDate')
                                  and current.get('dateBasis') != ga4.get('dateBasis')
                                  else 'different_periods_partial'
                                  if gsc and ga and (current.get('startDate'), current.get('endDate')) !=
                                     (ga4.get('startDate'), ga4.get('endDate'))
                                  else 'separate_metrics_not_combined'),
                'effect': 'not_causally_attributed',
            },
            'editorialHypothesis': {
                'status': 'unverified',
                'statement': HYPOTHESIS,
            },
        }
        observation['samePeriodPeerRank'] = None
        candidates.append(observation)
    peers = [observation for observation in candidates
             if observation['measurement']['gsc'] is not None
             and observation['measurement']['gsc']['versionWindow'] == 'current_revision_full_window'
             and _metric_number(observation['measurement']['gsc'].get('impressions')) is not None]
    peers.sort(key=lambda observation: (
        -observation['measurement']['gsc']['impressions'], observation['article']['url']))
    for index, observation in enumerate(peers, 1):
        observation['samePeriodPeerRank'] = {
            'rank': index, 'ofMeasuredPublishedPages': len(peers),
            'basis': 'gsc_page_impressions_same_period_full_revision',
            'meaning': 'same_window_ranking_only_not_causality',
        }
    def selection_key(observation):
        gsc, ga = observation['measurement']['gsc'], observation['measurement']['ga4']
        impressions = _metric_number((gsc or {}).get('impressions'))
        sessions = _metric_number((ga or {}).get('sessions'))
        return (0 if observation['samePeriodPeerRank'] else 1 if gsc else 2,
                -(impressions if impressions is not None else -1),
                -(sessions if sessions is not None else -1), observation['article']['url'])
    candidates.sort(key=selection_key)
    observations = candidates[:MAX_OBSERVATIONS]
    receipt = {
        'schemaVersion': 1, 'kind': kind, 'period': period, 'generatedAt': now.isoformat(),
        'metricSourceSha256': source_hash,
        'status': 'measured_observations' if observations else 'no_measured_observations',
        'observations': observations,
        'limitations': [
            'Missing page rows are not zero.',
            'GSC and GA4 remain separate when periods or timezones differ.',
            'A window overlapping publication is not an edition-effect estimate.',
            'Public editorial features are hypotheses, never verified source facts or causal findings.',
        ],
    }
    receipt['receiptContentSha256'] = _hash(_receipt_content(receipt))
    return receipt


def store_receipt(root, receipt):
    root = Path(root).resolve()
    source_hash = receipt.get('metricSourceSha256') if isinstance(receipt, dict) else None
    content_hash = receipt.get('receiptContentSha256') if isinstance(receipt, dict) else None
    kind, period = receipt.get('kind'), receipt.get('period')
    if (kind not in ('weekly', 'monthly') or not isinstance(period, str)
            or not re.fullmatch(r'\d{4}-(?:\d{2}|\d{2}-\d{2})', period)
            or not HASH.fullmatch(str(source_hash or ''))
            or not HASH.fullmatch(str(content_hash or ''))
            or content_hash != _hash(_receipt_content(receipt))):
        raise ValueError('learning_receipt_invalid')
    path = root / 'postpublication-learning' / kind / period / (content_hash + '.json')
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    parents = (root / 'postpublication-learning', root / 'postpublication-learning' / kind,
               root / 'postpublication-learning' / kind / period)
    if any(parent.is_symlink() for parent in parents) or path.parent.resolve() != parents[-1]:
        raise ValueError('learning_receipt_path_invalid')
    payload = (_canonical(receipt) + '\n').encode()
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError('learning_receipt_too_large')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink():
            return {'status': 'conflict', 'path': str(path.relative_to(root))}
        try:
            existing = json.loads(path.read_bytes())
            unchanged = (isinstance(existing, dict)
                         and existing.get('receiptContentSha256') == content_hash
                         and _receipt_content(existing) == _receipt_content(receipt))
            return {'status': 'unchanged' if unchanged else 'conflict',
                    'path': str(path.relative_to(root))}
        except (OSError, ValueError, TypeError):
            return {'status': 'conflict', 'path': str(path.relative_to(root))}
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {'status': 'created', 'path': str(path.relative_to(root))}


def _read(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        value = json.loads(path.read_bytes())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _metric_number(value):
    return value if (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value) and value >= 0) else None


def _safe_period(value, gsc=False):
    if not isinstance(value, dict):
        return None
    keys = ('startDate', 'endDate', 'dateBasis') + (('settledThrough',) if gsc else ())
    if any(not isinstance(value.get(key), str) or len(value[key]) > 64 for key in keys):
        return None
    try:
        start = datetime.fromisoformat(value['startDate']).date()
        end = datetime.fromisoformat(value['endDate']).date()
        ZoneInfo(value['dateBasis'])
        settled = datetime.fromisoformat(value['settledThrough']).date() if gsc else end
        if start > end or settled < end:
            return None
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return None
    return {key: value[key] for key in keys}


def _safe_public_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (parsed.scheme != 'https' or parsed.hostname != 'camp-gear-lab.com'
            or parsed.username or parsed.password or port not in (None, 443)
            or parsed.query or parsed.fragment or '%' in parsed.path
            or not re.fullmatch(r'/articles/[a-z0-9][a-z0-9_-]*', parsed.path)):
        return None
    return value


def _safe_measurement(value):
    if not isinstance(value, dict) or value.get('effect') != 'not_causally_attributed':
        return None
    allowed_comparability = {'same_dates_different_timezones_partial',
                             'different_periods_partial', 'separate_metrics_not_combined'}
    if value.get('comparability') not in allowed_comparability:
        return None
    result = {'gsc': None, 'ga4': None, 'comparability': value['comparability'],
              'effect': 'not_causally_attributed'}
    gsc = value.get('gsc')
    if isinstance(gsc, dict) and gsc.get('metricScope') == 'page' \
            and gsc.get('versionWindow') in ('current_revision_full_window', 'overlap_unattributed'):
        period = _safe_period(gsc.get('period'), True)
        numbers = {key: _metric_number(gsc.get(key)) for key in
                   ('clicks', 'impressions', 'ctr', 'position')}
        if period and any(number is not None for number in numbers.values()):
            result['gsc'] = {**numbers, 'metricScope': 'page',
                             'versionWindow': gsc['versionWindow'], 'period': period}
    ga4 = value.get('ga4')
    if isinstance(ga4, dict) and type(ga4.get('coverageVerified')) is bool \
            and ga4.get('versionWindow') in ('current_revision_full_window', 'overlap_unattributed'):
        period = _safe_period(ga4.get('period'))
        numbers = {key: _metric_number(ga4.get(key)) for key in
                   ('sessions', 'engagedSessions', 'keyEvents')}
        if period and any(number is not None for number in numbers.values()):
            result['ga4'] = {**numbers, 'coverageVerified': ga4['coverageVerified'],
                             'versionWindow': ga4['versionWindow'], 'period': period}
    return result if result['gsc'] or result['ga4'] else None


def _safe_observation(value):
    if not isinstance(value, dict):
        return None
    article, quality = value.get('article'), value.get('qualityGate')
    hypothesis, rank = value.get('editorialHypothesis'), value.get('samePeriodPeerRank')
    if (not isinstance(article, dict) or not isinstance(quality, dict)
            or quality.get('reviewPassed') is not True or not isinstance(hypothesis, dict)
            or quality.get('aggregateScoreUse') != 'advisory_only'
            or hypothesis.get('status') != 'unverified' or hypothesis.get('statement') != HYPOTHESIS):
        return None
    url, revision = _safe_public_url(article.get('url')), article.get('revision')
    source_receipt = article.get('sourceReceiptSha256')
    measurement = _safe_measurement(value.get('measurement'))
    if (not url or not HASH.fullmatch(str(revision or ''))
            or not HASH.fullmatch(str(source_receipt or '')) or not measurement):
        return None
    if rank is not None and (not isinstance(rank, dict) or type(rank.get('rank')) is not int
            or type(rank.get('ofMeasuredPublishedPages')) is not int
            or not 1 <= rank['rank'] <= rank['ofMeasuredPublishedPages']
            or rank.get('basis') != 'gsc_page_impressions_same_period_full_revision'
            or rank.get('meaning') != 'same_window_ranking_only_not_causality'
            or measurement['gsc'] is None
            or measurement['gsc']['versionWindow'] != 'current_revision_full_window'
            or measurement['gsc']['impressions'] is None):
        return None
    headings = [_text(item, 120) for item in article.get('headings', [])[:5]] \
        if isinstance(article.get('headings'), list) else []
    allowed_features = {'section_headings', 'faq', 'bullet_list', 'numbered_steps', 'table'}
    features = [item for item in article.get('publicFeatures', [])[:5]
                if isinstance(item, str) and item in allowed_features] \
        if isinstance(article.get('publicFeatures'), list) else []
    scoring_version = _text(quality.get('scoringVersion'), 80)
    return {
        'article': {'id': _text(article.get('id'), 160), 'title': _text(article.get('title'), 160),
                    'url': url, 'revision': revision,
                    'headings': [item for item in headings if item],
                    'publicFeatures': features, 'sourceReceiptSha256': source_receipt},
        'measurement': measurement,
        'qualityGate': {'reviewPassed': True, 'scoringVersion': scoring_version,
                        'aggregateScoreUse': 'advisory_only'},
        'samePeriodPeerRank': ({key: rank[key] for key in
                                ('rank', 'ofMeasuredPublishedPages', 'basis', 'meaning')}
                               if rank is not None else None),
        'editorialHypothesis': {'status': 'unverified', 'statement': HYPOTHESIS},
    }


def load_editorial_learnings(root, limit=MAX_PROJECTED):
    """Project recent immutable observations into a bounded, non-factual model input."""
    if type(limit) is not int or not 0 <= limit <= MAX_PROJECTED:
        raise ValueError('learning_projection_limit_invalid')
    folder = Path(root).resolve() / 'postpublication-learning'
    if folder.is_symlink():
        return []
    try:
        paths = sorted((path for path in folder.glob('*/*/*.json') if not path.is_symlink()),
                       key=lambda path: path.stat().st_mtime_ns, reverse=True)[:40]
    except OSError:
        return []
    selected = []
    seen = set()
    for path in paths:
        try:
            if (path.parent.is_symlink() or path.parent.parent.is_symlink()
                    or folder not in path.resolve().parents):
                continue
        except OSError:
            continue
        receipt = _read(path)
        if (not receipt or receipt.get('schemaVersion') != 1
                or receipt.get('status') != 'measured_observations'
                or not HASH.fullmatch(str(receipt.get('metricSourceSha256') or ''))
                or not HASH.fullmatch(str(receipt.get('receiptContentSha256') or ''))
                or path.stem != receipt['receiptContentSha256']
                or receipt['receiptContentSha256'] != _hash(_receipt_content(receipt))):
            continue
        for observation in receipt.get('observations', [])[:MAX_OBSERVATIONS]:
            safe = _safe_observation(observation)
            if not safe:
                continue
            article = safe['article']
            key = (article.get('url'), article.get('revision'))
            if key in seen:
                continue
            selected.append({
                'article': article, 'measurement': safe['measurement'],
                'qualityGate': safe['qualityGate'],
                'samePeriodPeerRank': safe['samePeriodPeerRank'],
                'editorialHypothesis': safe['editorialHypothesis'],
                'metricSourceSha256': receipt['metricSourceSha256'],
                'reportScope': {'kind': receipt.get('kind'), 'period': receipt.get('period')},
                'use': ('Unverified editorial context only. Never convert metrics or hypotheses into '
                        'source facts, author evidence, approval, or causal claims.'),
            })
            seen.add(key)
            if len(selected) >= limit:
                return selected
    return selected
