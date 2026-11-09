"""Track discovery and Google's observed index status for published revisions."""
import json
import os
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from ledger import fingerprint

SITE = 'https://camp-gear-lab.com'
OFFSETS = (0, 1, 7)


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('timestamp_requires_timezone')
    return parsed


def read_sitemap():
    with urllib.request.urlopen(SITE + '/sitemap.xml', timeout=10) as response:
        if response.geturl() != SITE + '/sitemap.xml':
            raise ValueError('unexpected_sitemap_url')
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError('sitemap_too_large')
    root = ET.fromstring(body)
    namespace = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    if root.tag != namespace + 'urlset':
        raise ValueError('invalid_sitemap')
    return {entry.findtext(namespace + 'loc'): entry.findtext(namespace + 'lastmod')
            for entry in root.findall(namespace + 'url')}


def inspect_url(url, env):
    credentials = env.get('INDEXING_CREDENTIALS')
    if not credentials:
        return {'error': 'credentials_unavailable'}
    try:
        result = subprocess.run(
            ['node', str(Path(__file__).with_name('index_inspection.mjs')), url],
            env={**os.environ, 'INDEXING_CREDENTIALS': credentials},
            capture_output=True, text=True, timeout=15, check=True,
        )
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'error': 'inspection_unavailable'}


def track_publications(jobs, root, env, config, now, save):
    if config.get('indexTrackingEnabled') is not True:
        return []
    since = instant(config['indexTrackingSince'])
    backfill = config.get('indexTrackingBackfillIds', [])
    summaries = []
    sitemap_loaded = False
    sitemap = None
    attempted = 0
    for job in jobs:
        publication = job.get('publication') or {}
        readback = publication.get('readback') or {}
        revision = job.get('revision')
        url = publication.get('url') or ''
        if (publication.get('verified') is not True or publication.get('revision') != revision
                or readback.get('verified') is not True or readback.get('fingerprint') != revision
                or not re.fullmatch(re.escape(SITE) + r'/articles/[a-z0-9-]+', url)):
            continue
        published_at = instant(publication['at'])
        historical = published_at < since
        if historical and job['id'] not in backfill:
            continue
        key = fingerprint([job['id'], revision, publication['at']])
        path = root / 'index-tracking' / (key + '.json')
        state = json.loads(path.read_text()) if path.exists() else {
            'id': job['id'], 'revision': revision, 'url': url,
            'startedAt': (now if historical else published_at).isoformat(), 'checks': [],
        }
        checks = state['checks']
        latest = checks[-1] if checks else {}
        complete = latest.get('sitemap') == 'current' and latest.get('index') == 'indexed'
        started = instant(state['startedAt'])
        next_at = None
        if not complete and len(checks) < len(OFFSETS):
            offset = OFFSETS[len(checks)]
            next_at = started + timedelta(days=offset)
            if attempted < 3 and now >= next_at:
                attempted += 1
                if not sitemap_loaded:
                    try:
                        sitemap = read_sitemap()
                    except (OSError, ValueError, ET.ParseError):
                        pass
                    sitemap_loaded = True
                lastmod = sitemap.get(url) if sitemap is not None else None
                expected = publication.get('remoteUpdatedAt')
                sitemap_status = 'unavailable' if sitemap is None else 'missing'
                if sitemap is not None and url in sitemap:
                    try:
                        sitemap_status = ('current' if instant(lastmod) == instant(expected)
                                          else 'outdated')
                    except (ValueError, AttributeError):
                        sitemap_status = 'date_unverified'
                proof = inspect_url(url, env)
                index = 'unverified'
                if proof.get('verdict') == 'PASS':
                    index = ('indexed' if proof.get('googleCanonical') == url
                             else 'canonical_unverified')
                elif proof.get('verdict') in ('NEUTRAL', 'FAIL'):
                    index = 'not_indexed'
                latest = dict(at=now.isoformat(), day=offset, sitemap=sitemap_status,
                              lastmod=lastmod, expectedLastmod=expected, index=index, inspection=proof)
                checks.append(latest)
                save(path, state)
                complete = sitemap_status == 'current' and index == 'indexed'
                next_at = (started + timedelta(days=OFFSETS[len(checks)])
                           if not complete and len(checks) < len(OFFSETS) else None)
        summaries.append(dict(id=job['id'], revision=revision, url=url, latest=latest,
                              nextAt=next_at.isoformat() if next_at else None))
    return summaries
