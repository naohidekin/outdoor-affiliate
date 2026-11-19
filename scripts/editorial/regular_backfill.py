"""Consume a period's saved selection without researching or replacing a slot."""
import copy
import json
import secrets

from ledger import canonical, fingerprint


RECONCILE = 'weekly_research_requires_reconciliation'


def regular(job):
    return job.get('kind') not in ('article_revision', 'supplemental_article')


def pending(job):
    publication = job.get('publication')
    return (job.get('kind') != 'article_revision' and job.get('stage') != 'rejected'
            and not (isinstance(publication, dict) and publication.get('verified') is True))


def _themes(value):
    if (not isinstance(value, list) or len(value) != 3
            or any(not isinstance(theme, dict) or not isinstance(theme.get('slug'), str)
                   or not theme['slug'].strip() for theme in value)
            or len({theme['slug'] for theme in value}) != 3):
        raise ValueError(RECONCILE)
    return value


def load_selection(root, period):
    """Recover only completed research. Unknown/held attempts remain untouched."""
    path = root / 'production-attempts' / (period + '.json')
    if not path.exists():
        return None
    try:
        attempt = json.loads(path.read_text())
        if not isinstance(attempt, dict) or attempt.get('status') != 'generated':
            return None
        if attempt.get('period', period) != period:
            raise ValueError(RECONCILE)
        if 'themes' in attempt:
            return _themes(attempt['themes'])
        # Older mixed research saved proposals and a separate exact selection.
        # Rebind its saved public sources; never rerank or fetch new evidence.
        from topic_selection import bind_nonproduct_theme
        receipt = json.loads((root / 'period-receipts' / (period + '.json')).read_text())
        if (attempt.get('selection') != 'selected' or receipt.get('status') != 'selected'
                or receipt.get('period') != period):
            raise ValueError(RECONCILE)
        selected = [row['proposal'] for row in receipt['decisions'] if row['status'] == 'selected']
        _themes(selected)
        if ([theme['slug'] for theme in selected] != receipt['selectedSlugs']
                or any(theme not in attempt['proposals'] for theme in selected)):
            raise ValueError(RECONCILE)
        feed = (json.loads((root / 'public-sources' / (period + '.json')).read_text())
                if any(theme.get('productIds') == [] for theme in selected) else {})
        return [bind_nonproduct_theme(theme, feed) for theme in selected]
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError(RECONCILE) from None


def backfill(ledger, period, themes, now):
    """Pin the pool and create/consume slots in one authoritative transaction."""
    themes = copy.deepcopy(_themes(themes))
    if ledger.production_schedule.period_key(now) != period:
        raise ValueError('production not due')
    key = 'regular_selection:v1:' + period
    selection_sha = fingerprint(themes)
    created = []
    with ledger._tx() as db:
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        pool = (json.loads(row[0]) if row else
                {'period': period, 'themes': themes, 'selectionSha256': selection_sha, 'slots': {}})
        if (pool.get('period') != period or pool.get('themes') != themes
                or pool.get('selectionSha256') != selection_sha or not isinstance(pool.get('slots'), dict)):
            raise ValueError(RECONCILE)
        jobs = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs')]
        selected_slugs = {theme['slug'] for theme in themes}
        current = [job for job in jobs if regular(job) and job['week'] == period]
        if (len(current) > 3 or any(job['theme'].get('slug') not in selected_slugs for job in current)
                or set(pool['slots']) - selected_slugs):
            raise ValueError(RECONCILE)
        for theme in themes:
            slug = theme['slug']
            existing = [job for job in jobs if job['theme'].get('slug') == slug]
            if existing:
                if (len(existing) != 1 or not regular(existing[0]) or existing[0]['week'] != period
                        or pool['slots'].get(slug, existing[0]['id']) != existing[0]['id']):
                    raise ValueError(RECONCILE)
                pool['slots'][slug] = existing[0]['id']
            elif slug in pool['slots']:
                raise ValueError(RECONCILE)  # A consumed slot must never be recreated.
        uncertain = db.execute("SELECT 1 FROM effects WHERE status IN ('in_flight','unknown') LIMIT 1").fetchone()
        for index, theme in enumerate(themes, 1):
            if (uncertain or len(current) >= 3 or sum(pending(job) for job in jobs) >= 3):
                break
            if theme['slug'] in pool['slots']:
                continue
            job = dict(id='article-' + secrets.token_hex(12), theme=theme, week=period, stage='candidate',
                       regularSelection={'period': period, 'slot': index, 'selectionSha256': selection_sha},
                       bundle=None, revision=None, review=None, approval=None, publication=None,
                       social=None, error=None, created_at=now.isoformat())
            ledger._put(db, job, 'candidate')
            pool['slots'][theme['slug']] = job['id']
            jobs.append(job)
            current.append(job)
            created.append(job)
        db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, canonical(pool)))
    return created
