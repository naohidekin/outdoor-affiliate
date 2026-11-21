"""Offline SQLite editorial ledger. Callers must verify real evidence before recording it.

Delivery parts is a dict containing all SCOPE keys (or {'scope': {...}, ...}).
Decision events contain those keys, event_id, action_id, card_ts and button payload.
Nonces are private random capabilities; transport signature verification belongs to callers.
All validation failures raise ValueError. JSON hashes use sorted UTF-8, compact JSON.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import os
import re
from pathlib import Path
import secrets
import sqlite3
from x_readback import exact_x_text
from production_schedule import ProductionSchedule

JST = timezone(timedelta(hours=9))
SCOPE = ('team_id', 'app_id', 'user_id', 'channel_id', 'thread_ts')
FLAGS = ('facts', 'images', 'affiliate', 'medical', 'render')
REFRESH_NOTICE = '旧画像版は投稿済み。今回の承認で新画像版を新規投稿します。'


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    """Hash only canonical JSON; Catalog supplies verified public URLs/image SHA256.

    Path-like fields remain ordinary JSON strings and never trigger filesystem IO.
    """
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def timestamp(now=None):
    now = now if now is not None else datetime.now(JST)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace('Z', '+00:00'))
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware datetime required')
    return now.astimezone(JST)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_review(review, revision, bundle=None):
    if isinstance(bundle, dict) and 'articleReviewScoring' in bundle:
        from review_scoring import SUPPORTED_VERSIONS
        marker = bundle['articleReviewScoring']
        require(isinstance(marker, dict) and set(marker) == {'version'} and marker['version'] in SUPPORTED_VERSIONS
                and isinstance(review, dict) and review.get('scoringVersion') == marker['version'],
                'bound article scoring version required')
    if isinstance(review, dict) and any(key in review for key in
                                        ('scoringVersion', 'calculation', 'applicability', 'admissionMode', 'hardChecks', 'improvementFeedback')):
        from review_scoring import verify_review
        verify_review(review, bundle)
    from review_scoring import VERSION
    v2 = isinstance(review, dict) and review.get('scoringVersion') == VERSION
    if v2: require(isinstance(bundle, dict) and bundle.get('articleReviewScoring') == {'version': VERSION}, 'bound article v2 bundle required')
    score = review.get('score') if isinstance(review, dict) else None
    require(isinstance(score, (int, float)) and not isinstance(score, bool)
            and math.isfinite(score) and (0 <= score <= 10 if v2 else score >= 7.5) and review.get('passed') is True, 'review failed')
    evidence = review.get('evidence')
    require(isinstance(evidence, dict)
            and all(evidence.get(flag) is True for flag in FLAGS if flag != 'affiliate'),
            'evidence flags required')
    affiliate = evidence.get('affiliate')
    if affiliate is not True:
        from topic_selection import nonproduct_affiliate_review
        require(bundle is not None and affiliate == nonproduct_affiliate_review(bundle),
                'typed nonproduct affiliate applicability required')
    polish = review.get('polish', {})
    require(isinstance(polish, dict) and polish.get('model') == 'gemini-3.8-flash'
            and polish.get('validated') is True, 'validated Gemini polish required')
    require(review.get('fingerprint') == revision, 'review fingerprint mismatch')


def valid_astra_review(review, revision):
    require(isinstance(review, dict) and review.get('passed') is True
            and review.get('issues') == [] and review.get('reviewedBy') == 'Astra'
            and isinstance(review.get('evidence'), dict) and bool(review['evidence'])
            and review.get('fingerprint') == revision, 'matching Astra quality review required')


def valid_social_mode(proposal):
    mode = proposal.get('deliveryMode', 'manual')
    require(mode in ('manual', 'auto_x', 'buffer_x'), 'unknown social delivery mode')
    if mode == 'auto_x':
        require(isinstance(proposal.get('targetAccountId'), str) and
                re.fullmatch(r'[1-9][0-9]{0,19}', proposal['targetAccountId']) is not None,
                'fixed X account ID required')
        require(not proposal.get('targetAccountIdX') and not proposal.get('buffer'),
                'direct X target cannot use Buffer binding')
    elif mode == 'buffer_x':
        binding = proposal.get('buffer')
        require(isinstance(binding, dict) and set(binding) ==
                {'organizationId', 'channelId', 'schedulingPolicy'},
                'exact Buffer binding required')
        require(all(isinstance(binding.get(key), str) and
                    re.fullmatch(r'[A-Za-z0-9_-]{3,128}', binding[key])
                    for key in ('organizationId', 'channelId')),
                'fixed Buffer organization and channel required')
        require(binding['schedulingPolicy'] == 'next_available_slot',
                'next available Buffer slot required')
        require(isinstance(proposal.get('targetAccountIdX'), str) and
                re.fullmatch(r'[1-9][0-9]{0,19}', proposal['targetAccountIdX']) is not None,
                'fixed Buffer X account ID required')
        require(all(key not in proposal for key in ('targetAccountId', 'dueAt', 'scheduledAt')),
                'Buffer approval must not bind a fixed time')
    else:
        require(not proposal.get('targetAccountId') and not proposal.get('targetAccountIdX')
                and not proposal.get('buffer'), 'manual social target must be absent')


def valid_social_images(job, proposal):
    """SNS-only derivatives bind to the immutable published revision, never OG readback."""
    approved = job['bundle'].get('images') or []
    supplement = proposal.get('supplementalCard')
    if supplement is not None:
        publication = job.get('publication') or {}
        require(isinstance(supplement, dict) and supplement.get('articleId') == job.get('id')
                and supplement.get('articleRevision') == job.get('revision') == fingerprint(job['bundle'])
                and publication.get('revision') == job['revision'] and publication.get('verified') is True
                and (publication.get('readback') or {}).get('verified') is True
                and publication['readback'].get('fingerprint') == job['revision'], 'supplemental article binding invalid')
        manifest = supplement.get('manifest') or {}
        sources = manifest.get('sources')
        product_ids = job['bundle']['article'].get('productIds', [])[:2]
        products = {p.get('id'): p for p in job['bundle'].get('products', [])}
        require(isinstance(sources, list) and 1 <= len(sources) <= 2
                and [s.get('productId') for s in sources] == product_ids, 'supplemental source order invalid')
        for source in sources:
            matches = [i for i in approved if i.get('verified') is True
                       and i.get('productId') == source.get('productId')
                       and i.get('url') == products.get(source.get('productId'), {}).get('imageUrl')
                       and i.get('sha256') == source.get('sha256')]
            require(len(matches) == 1 and re.fullmatch(r'[a-f0-9]{64}', str(source.get('sha256', ''))),
                    'supplemental source hash invalid')
        require(manifest.get('contentType') == 'image/png' and manifest.get('width') == 1200
                and manifest.get('height') == 630 and manifest.get('templateVersion') in
                ('lake-sky-social-card-v1', 'lake-sky-social-card-v2')
                and isinstance(manifest.get('rendererEvidence'), dict) and manifest['rendererEvidence']
                and manifest.get('url') == manifest.get('finalUrl')
                and str(manifest.get('url', '')).startswith('https://')
                and type(manifest.get('size')) is int and 0 < manifest['size'] <= 2 * 1024 * 1024,
                'supplemental manifest invalid')
        renderer = manifest['rendererEvidence']
        shown = renderer.get('displayText') or {}
        title = job['bundle']['article']['title']
        parts = title.split('｜')
        heading = parts[1] if len(parts) == 2 and all(p.strip() for p in parts) else title
        crops = renderer.get('sourceCrops')
        require(shown.get('title') == title and shown.get('heading') == heading
                and shown.get('productNames') == [products[p].get('name') for p in product_ids]
                and isinstance(crops, list) and len(crops) == len(sources)
                and all(isinstance(c, dict) and c.get('productId') == s['productId']
                        and c.get('sha256') == s['sha256'] for c, s in zip(crops, sources))
                and re.fullmatch(r'[a-f0-9]{64}', str(renderer.get('contentHash', '')))
                and isinstance(renderer.get('layout'), dict) and renderer.get('renderEngine') and renderer.get('fontFamily'),
                'supplemental renderer binding invalid')
        card = dict(manifest, role='social-card', verified=True)
        require(proposal.get('images') == [card], 'supplemental card mismatch')
        approved = [card]
    images = proposal.get('images')
    require(isinstance(images, list) and 1 <= len(images) <= 4 and all(
        isinstance(i, dict) and i.get('verified') is True and i in approved
        and isinstance(i.get('url'), str) and re.fullmatch(r'[a-f0-9]{64}', str(i.get('sha256', '')))
        and type(i.get('size')) is int and i['size'] > 0 for i in images), 'social_image_binding_invalid')
    require(len({i['url'] for i in images}) == len(images), 'social_image_duplicate')


def valid_image_refresh(old, proposal, review):
    valid_review(old.get('review'), old['revision'], old.get('bundle'))
    require(fingerprint(old['proposal']) == old['revision'], 'old social changed')
    excluded = {'images', 'supplementalCard', 'approvalNotice', 'priorPostUrl', 'wisePolicy'}
    require({k: v for k, v in old['proposal'].items() if k not in excluded} ==
            {k: v for k, v in proposal.items() if k not in excluded}, 'image-only refresh changed text or delivery')
    if proposal.get('wisePolicy') != old['proposal'].get('wisePolicy'):
        from wise_contract import require_current_review
        require_current_review(proposal, review)
    binding = dict(kind='image_only', fromRevision=old['revision'], toRevision=fingerprint(proposal), modelRerun=True)
    require(review.get('imageRefresh') == binding and str(review.get('model', '')).startswith('claude-'),
            'independent current Claude image review required')
    reuse = review.get('polishReuse') or {}
    require(reuse == dict(kind='unchanged_text', fromRevision=old['revision'],
                         textHash=fingerprint(old['proposal']['text']), originalPolish=old['review']['polish'])
            and review.get('polish') == old['review']['polish'], 'unchanged Gemini provenance required')


def valid_codex_social_instruction(id, revision, text):
    """Exact directives only; the one owner instruction is pinned to its reviewed proposal."""
    explicit = text == f'post {id} {revision}'
    soto = (id == 'article-42db462e1ce17ce82afb36ed'
            and revision == '732c338b9c0cab5b9b5eaa6e591e26555f67b1b1846f6fd3918c5f21ef5fb24c'
            and text == 'SOTOのX投稿はもう行ってください。これはもう気にせずに。')
    require(explicit or soto, 'explicit social article/version instruction required')


def validate_display_suppression(previous, candidate):
    """Pure exact-diff check shared by offline preparation and atomic ledger save."""
    from catalog_corrections import validate_context
    from revisions import _aware
    require(isinstance(previous, dict) and isinstance(candidate, dict), 'bundle fields changed')
    comparison = candidate
    from review_scoring import VERSION, VERSION_V1
    if candidate.get('articleReviewScoring') == {'version': VERSION} and previous.get('articleReviewScoring') != {'version': VERSION}:
        from wise_contract import load_policy
        current_policy = load_policy()['id']
        require(('articleReviewScoring' not in previous or previous['articleReviewScoring'] == {'version': VERSION_V1})
                and previous.get('wisePolicy') in (None, '6eeecd05024a54cd4b6ec7c4e781470caad7b0fc597bfbc20af0de3cc951491b', current_policy)
                and candidate.get('wisePolicy') == current_policy, 'explicit fixed-body v2 metadata transition required')
        comparison = dict(candidate)
        for key in ('articleReviewScoring', 'wisePolicy'):
            if key in previous: comparison[key] = previous[key]
            else: comparison.pop(key, None)
    require(set(previous) == set(comparison), 'bundle fields changed')
    for key in previous:
        if key not in ('products', 'catalogCorrectionContext'):
            require(canonical(previous[key]) == canonical(comparison[key]), 'fixed bundle field changed: ' + key)
    old = validate_context(previous.get('catalogCorrectionContext'))
    new = validate_context(candidate.get('catalogCorrectionContext'))
    require(canonical(old['baseProducts']) == canonical(new['baseProducts']), 'original product baseline changed')
    require(canonical(previous['products']) == canonical(old['candidateProducts'])
            and canonical(candidate['products']) == canonical(new['candidateProducts']), 'candidate context mismatch')
    before, after = previous['products'], candidate['products']
    require(len(before) == len(after) and [p['id'] for p in before] == [p['id'] for p in after],
            'product identities changed')
    changed = False
    for a, b in zip(before, after):
        require(set(a) == set(b), 'product fields changed')
        delta = {k for k in a if canonical(a[k]) != canonical(b[k])}
        require(delta <= {'price', 'rating', 'updatedAt'}, 'only price/rating suppression allowed')
        if delta:
            require(bool(delta & {'price', 'rating'}) and 'updatedAt' in delta
                    and _aware(b['updatedAt']) > _aware(a['updatedAt']), 'suppression needs newer timestamp')
            for key in delta & {'price', 'rating'}:
                require(type(b[key]) in (int, float) and b[key] == 0,
                        'unverified display may only become numeric zero')
            changed = True
    require(changed, 'no display suppression requested')
    return json.loads(canonical(new))


class Ledger:
    BUFFER_REQUEST_LIMIT = 60

    def __init__(self, root, owner_id, production_schedule=None, *, target_account_id=None):
        self.production_schedule = ProductionSchedule(production_schedule)
        self.target_account_id = target_account_id
        raw = Path(root)
        require(raw.is_absolute(), 'root must be absolute')
        root = raw.resolve()
        require(root not in (Path('/'), Path.home().resolve()), 'unsafe root')
        require(not any((p / '.git').exists() or (p / '.git').is_symlink() for p in (root, *root.parents)), 'root inside git repository')
        require(bool(owner_id), 'owner required')
        # Never chmod existing directories, including existing parents.
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(root.is_dir() and root.stat().st_mode & 0o777 == 0o700, 'root must be private (0700)')
        self.root, self.owner_id = root, owner_id
        self.db_path = root / 'ledger.sqlite3'
        fd = os.open(self.db_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            require(os.fstat(fd).st_mode & 0o777 == 0o600, 'database must be private (0600)')
        finally:
            os.close(fd)
        with self._tx() as db:
            for sql in (
                'CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, data TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS effects (job_id TEXT, kind TEXT, status TEXT, data TEXT, PRIMARY KEY(job_id,kind))',
                'CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT NOT NULL, job_id TEXT, kind TEXT NOT NULL, data TEXT NOT NULL)',
                "CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable events'); END",
                "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable events'); END",
            ):
                db.execute(sql)
            db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('owner_id', owner_id))
            require(db.execute('SELECT value FROM meta WHERE key=?', ('owner_id',)).fetchone()[0] == owner_id, 'owner mismatch')

    @contextmanager
    def _tx(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _get(self, db, id):
        row = db.execute('SELECT data FROM jobs WHERE id=?', (id,)).fetchone()
        require(row is not None, 'unknown job')
        return json.loads(row[0])

    @classmethod
    def _buffer_budget_default(cls):
        return {'limit': cls.BUFFER_REQUEST_LIMIT, 'used': 0, 'reservations': {},
                'rateLimitWindows': [], 'lastObservation': None, 'holdReason': None,
                'retryAfterUntil': None}

    @staticmethod
    def _buffer_budget_key(period):
        require(isinstance(period, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', period),
                'buffer budget period required')
        try:
            date = datetime.fromisoformat(period).date()
        except ValueError:
            raise ValueError('buffer budget period required') from None
        require(date.isoformat() == period, 'buffer budget period required')
        return 'buffer_request_budget:' + period

    @staticmethod
    def _valid_buffer_usage(usage, now):
        require(isinstance(usage, dict) and set(usage) <= {
            'requestCount', 'observedAt', 'rateLimitWindows', 'statusCode',
            'retryAfterSeconds'}, 'buffer request usage invalid')
        require(type(usage.get('requestCount')) is int and usage['requestCount'] >= 0,
                'buffer request usage invalid')
        observed = timestamp(usage.get('observedAt'))
        require(observed <= now, 'buffer request usage invalid')
        windows = usage.get('rateLimitWindows')
        require(isinstance(windows, list) and len(windows) == 3,
                'buffer rate limit windows required')
        expected = {900, 86400, 2592000}
        normalized = []
        for item in windows:
            require(isinstance(item, dict) and set(item) == {
                'windowSeconds', 'limit', 'remaining', 'resetAt'},
                'buffer rate limit windows required')
            require(type(item.get('windowSeconds')) is int
                    and type(item.get('limit')) is int and item['limit'] > 0
                    and type(item.get('remaining')) is int
                    and 0 <= item['remaining'] <= item['limit'],
                    'buffer rate limit windows required')
            reset = timestamp(item.get('resetAt'))
            normalized.append({**item, 'resetAt': reset.isoformat()})
        require({item['windowSeconds'] for item in normalized} == expected,
                'buffer rate limit windows required')
        status = usage.get('statusCode')
        require(status is None or type(status) is int and 100 <= status <= 599,
                'buffer request usage invalid')
        retry = usage.get('retryAfterSeconds')
        require(retry is None or type(retry) is int and 0 <= retry <= 2592000,
                'buffer request usage invalid')
        require(status == 429 or retry is None, 'Retry-After requires Buffer 429')
        return {**usage, 'observedAt': observed.isoformat(),
                'rateLimitWindows': sorted(normalized, key=lambda item: item['windowSeconds'])}

    def reserve_buffer_requests(self, period, amount, *, now=None):
        """Reserve the adapter's bounded worst case before any shared Buffer request."""
        now = timestamp(now)
        key = self._buffer_budget_key(period)
        require(type(amount) is int and 1 <= amount <= 18, 'buffer request reservation invalid')
        with self._tx() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            state = self._buffer_budget_default() if row is None else json.loads(row[0])
            require(state.get('limit') == self.BUFFER_REQUEST_LIMIT
                    and type(state.get('used')) is int and state['used'] >= 0
                    and isinstance(state.get('reservations'), dict),
                    'buffer request budget requires reconciliation')
            reserved = sum(state['reservations'].values())
            require(all(type(value) is int and 1 <= value <= 18
                        for value in state['reservations'].values()),
                    'buffer request budget requires reconciliation')
            retry_until = state.get('retryAfterUntil')
            if retry_until is not None:
                require(now >= timestamp(retry_until), 'buffer_rate_limit_429')
            require(state['used'] + reserved + amount <= self.BUFFER_REQUEST_LIMIT,
                    'buffer_request_budget_hold')
            hold_id = secrets.token_hex(16)
            state['reservations'][hold_id] = amount
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, canonical(state)))
            self._event(db, 'buffer-budget:' + period, 'buffer_request_reserved',
                        {'period': period, 'holdId': hold_id, 'amount': amount,
                         'used': state['used']}, now)
        return {'id': hold_id, 'period': period, 'reserved': amount}

    def settle_buffer_requests(self, hold, usage, *, outcome, now=None):
        """Settle only measured requests and retain the provider's shared windows."""
        now = timestamp(now)
        require(isinstance(hold, dict) and set(hold) == {'id', 'period', 'reserved'}
                and isinstance(hold.get('id'), str) and hold['id'],
                'buffer request reservation invalid')
        require(outcome in ('success', 'failed', 'unknown'), 'buffer request outcome invalid')
        key = self._buffer_budget_key(hold.get('period'))
        measured = self._valid_buffer_usage(usage, now)
        with self._tx() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            require(row is not None, 'buffer request reservation missing')
            state = json.loads(row[0])
            reserved = (state.get('reservations') or {}).get(hold['id'])
            require(reserved == hold.get('reserved')
                    and measured['requestCount'] <= reserved,
                    'buffer request settlement conflict')
            state['reservations'].pop(hold['id'])
            state['used'] += measured['requestCount']
            require(state['used'] <= self.BUFFER_REQUEST_LIMIT,
                    'buffer request budget exceeded')
            state['rateLimitWindows'] = measured['rateLimitWindows']
            state['lastObservation'] = measured
            if measured.get('statusCode') == 429:
                state['holdReason'] = 'buffer_rate_limit_429'
                retry = measured.get('retryAfterSeconds')
                state['retryAfterUntil'] = ((now + timedelta(seconds=retry)).isoformat()
                                             if retry is not None else None)
            db.execute('UPDATE meta SET value=? WHERE key=?', (canonical(state), key))
            self._event(db, 'buffer-budget:' + hold['period'], 'buffer_request_settled',
                        {'period': hold['period'], 'holdId': hold['id'],
                         'outcome': outcome, 'usage': measured, 'used': state['used']}, now)
        return self.inspect_buffer_requests(hold['period'])

    def cancel_buffer_request_reservation(self, hold, *, now=None):
        """Release only a reservation proven to have made zero Buffer requests."""
        now = timestamp(now)
        require(isinstance(hold, dict) and set(hold) == {'id', 'period', 'reserved'},
                'buffer request reservation invalid')
        key = self._buffer_budget_key(hold.get('period'))
        with self._tx() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            require(row is not None, 'buffer request reservation missing')
            state = json.loads(row[0])
            require((state.get('reservations') or {}).get(hold.get('id')) == hold.get('reserved'),
                    'buffer request reservation missing')
            state['reservations'].pop(hold['id'])
            db.execute('UPDATE meta SET value=? WHERE key=?', (canonical(state), key))
            self._event(db, 'buffer-budget:' + hold['period'], 'buffer_request_cancelled',
                        {'period': hold['period'], 'holdId': hold['id'],
                         'reason': 'zero_requests_observed'}, now)
        return self.inspect_buffer_requests(hold['period'])

    def inspect_buffer_requests(self, period):
        key = self._buffer_budget_key(period)
        with sqlite3.connect(self.db_path) as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        state = self._buffer_budget_default() if row is None else json.loads(row[0])
        reserved = sum((state.get('reservations') or {}).values())
        return {**state, 'remaining': self.BUFFER_REQUEST_LIMIT - state.get('used', 0) - reserved}

    def _event(self, db, id, kind, data, now=None):
        db.execute('INSERT INTO events(at,job_id,kind,data) VALUES (?,?,?,?)',
                   (timestamp(now).isoformat(), id, kind, canonical(data)))

    def _put(self, db, job, kind):
        if job.get('kind') != 'article_revision' and not job['publication'] and job['stage'] != 'rejected':
            others = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs WHERE id!=?', (job['id'],))]
            require(sum(other.get('kind') != 'article_revision' and not other['publication'] and other['stage'] != 'rejected' for other in others) < 3, 'pending cap reached')
        job['updated_at'] = timestamp().isoformat()
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (job['id'], canonical(job)))
        self._event(db, job['id'], kind, job)
        return job

    def _invalidate(self, db, id, kind=None):
        rows = db.execute('SELECT id,data FROM requests WHERE job_id=?', (id,)).fetchall()
        for request_id, data in rows:
            request = json.loads(data)
            if kind is None or request['kind'] == kind:
                request['status'] = 'invalidated'
                db.execute('UPDATE requests SET data=? WHERE id=?', (canonical(request), request_id))

    def _current(self, job):
        require(job['bundle'] is not None and fingerprint(job['bundle']) == job['revision'], 'bundle fingerprint changed')
        if job.get('kind') == 'article_revision':
            from revisions import validate_revision_bundle
            validate_revision_bundle(job, job['bundle'])
        if 'catalogCorrectionContext' in job or 'catalogCorrectionContext' in job['bundle']:
            from catalog_corrections import validate_bundle
            validate_bundle(job, job['bundle'])

    def attach_catalog_correction(self, id, raw):
        """Trusted local operator only; attachment grants no publication authority."""
        from catalog_corrections import validated_context
        context = validated_context(raw)
        with self._tx() as db:
            job = self._get(db, id)
            require(job.get('kind') != 'article_revision' and job['stage'] in ('candidate', 'error')
                    and job.get('bundle') is None and job.get('revision') is None
                    and not job.get('approval') and not job.get('publication'),
                    'only unstaged new article can receive catalog correction')
            require(not db.execute('SELECT 1 FROM effects WHERE job_id=?', (id,)).fetchone(),
                    'catalog correction effects require reconciliation')
            ids = job['theme'].get('productIds') if isinstance(job['theme'], dict) else None
            require(ids == [p['id'] for p in context['candidateProducts']],
                    'catalog correction theme product IDs mismatch')
            job.update(catalogCorrectionContext=json.loads(canonical(context)), stage='candidate', error=None)
            self._invalidate(db, id)
            return self._put(db, job, 'catalog_correction_attached')

    def suppress_unverified_product_display(self, id, bundle, *, expected_revision):
        """Operator-only price/rating hiding; no model, publication or approval.

        Existing prose, imagery and links are immutable. A new exact review and
        independent Astra review plus new owner approval are required afterwards.
        """
        require(isinstance(expected_revision, str) and re.fullmatch(r'[a-f0-9]{64}', expected_revision),
                'expected exact revision required')
        with self._tx() as db:
            job = self._get(db, id)
            require(job.get('kind') != 'article_revision' and job.get('stage') in
                    ('draft', 'review', 'held', 'rejected', 'error') and not job.get('publication')
                    and not job.get('approval') and not job.get('social'),
                    'unapproved unpublished article required')
            self._current(job)
            require(job['revision'] == expected_revision, 'revision conflict')
            require(not db.execute('SELECT 1 FROM effects WHERE job_id=?', (id,)).fetchone(),
                    'existing effect requires reconciliation')
            for folder, name in (('catalog-corrections', expected_revision),
                                 ('social-publications', expected_revision),
                                 ('social-outbox', expected_revision), ('production-attempts', id)):
                marker = self.root / folder / (name + '.json')
                require(not marker.exists() and not marker.is_symlink(), 'inflight journal requires reconciliation')
            context = validate_display_suppression(job['bundle'], bundle)
            from catalog_corrections import validate_bundle
            candidate = dict(job, catalogCorrectionContext=context)
            validate_bundle(candidate, bundle)
            self._event(db, id, 'display_suppression_previous',
                        {'reason': 'hide_unverified_price_rating', 'job': job})
            candidate.update(bundle=json.loads(canonical(bundle)), revision=fingerprint(bundle),
                             review=None, astraReview=None, approval=None, publication=None,
                             social=None, error=None, stage='draft')
            self._invalidate(db, id)
            return self._put(db, candidate, 'unverified_display_suppressed')

    def create_candidate(self, theme, now=None):
        now = timestamp(now)
        slug = theme.get('slug') if isinstance(theme, dict) else theme
        require(isinstance(slug, str) and bool(slug.strip()), 'theme slug required')
        week = self.production_schedule.period_key(now)
        with self._tx() as db:
            jobs = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs')]
            jobs = [job for job in jobs if job.get('kind') not in
                    ('article_revision', 'supplemental_article')]
            for job in jobs:
                old_slug = job['theme'].get('slug') if isinstance(job['theme'], dict) else job['theme']
                if old_slug == slug:
                    return job
            require(week is not None, 'production not due')
            require(sum(job['week'] == week for job in jobs) < 3, 'weekly candidate cap reached')
            require(sum(not job['publication'] and job['stage'] != 'rejected' for job in jobs) < 3, 'pending cap reached')
            job = dict(id='article-' + secrets.token_hex(12), theme=theme, week=week, stage='candidate',
                       bundle=None, revision=None, review=None, approval=None, publication=None, social=None, error=None,
                       created_at=now.isoformat())
            return self._put(db, job, 'candidate')

    def create_supplemental_candidate(self, theme, batch_id, slot, source_binding, *,
                                      social_eligible_period, now=None):
        """Create one immutable slot in the bounded batch without consuming regular 3/week."""
        now = timestamp(now)
        require(isinstance(theme, dict) and all(isinstance(theme.get(key), str)
                and theme[key].strip() for key in
                ('slug', 'title', 'categoryId', 'query', 'selectionReason')),
                'complete supplemental theme required')
        ids = theme.get('productIds')
        require(isinstance(ids, list) and ids and len(ids) == len(set(ids))
                and all(isinstance(item, str) and item for item in ids),
                'supplemental apparel product IDs required')
        require(batch_id == 'apparel-2026-11-16' and type(slot) is int and 1 <= slot <= 3,
                'invalid supplemental batch slot')
        require(isinstance(source_binding, str)
                and re.fullmatch(r'[a-f0-9]{64}', source_binding), 'source binding required')
        require(social_eligible_period == '2026-11-20', 'invalid supplemental social period')
        with self._tx() as db:
            jobs = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs')]
            existing = [job for job in jobs if job.get('kind') == 'supplemental_article'
                        and job.get('batchId') == batch_id and job.get('batchSlot') == slot]
            if existing:
                require(len(existing) == 1 and existing[0].get('theme') == theme
                        and existing[0].get('sourceBinding') == source_binding,
                        'supplemental slot conflict')
                return existing[0]
            require(sum(job.get('kind') == 'supplemental_article'
                        and job.get('batchId') == batch_id for job in jobs) < 3,
                    'supplemental batch cap reached')
            require(sum(job.get('kind') != 'article_revision' and not job.get('publication')
                        and job.get('stage') != 'rejected' for job in jobs) < 3,
                    'pending cap reached')
            require(not any((job.get('theme') or {}).get('slug') == theme['slug'] for job in jobs),
                    'theme already exists')
            week = self.production_schedule.period_key(now)
            require(week is not None, 'supplemental production period unavailable')
            job = dict(id='article-' + secrets.token_hex(12), kind='supplemental_article',
                       batchId=batch_id, batchSlot=slot, sourceBinding=source_binding,
                       batchCallCap=96, socialEligiblePeriod=social_eligible_period,
                       theme=json.loads(canonical(theme)),
                       week=week, stage='candidate', bundle=None, revision=None, review=None,
                       approval=None, publication=None, social=None, error=None,
                       created_at=now.isoformat())
            return self._put(db, job, 'supplemental_candidate')

    def request_revision(self, specification, now=None):
        from revisions import validated_context, TARGETS, _aware
        context = validated_context(specification)
        base = context['baseArticle']
        now = timestamp(now)
        with self._tx() as db:
            previous = []
            for row in db.execute('SELECT data FROM jobs'):
                old = json.loads(row[0])
                if old.get('kind') == 'article_revision' and old['revisionContext']['baseArticle']['id'] == base['id']:
                    if old['revisionContext'] == context:
                        return old
                    approval, publication = old.get('approval') or {}, old.get('publication') or {}
                    readback = publication.get('readback') or {}
                    evidence = approval.get('evidence')
                    codex_approved = (approval.get('source') == 'codex' and approval.get('action') in (None, 'approved')
                        and isinstance(evidence, dict) and evidence.get('source') == 'codex'
                        and all(isinstance(evidence.get(k), str) and evidence[k].strip()
                                for k in ('thread_id', 'message_id', 'text'))
                        and approval.get('request_id') == 'codex-' + fingerprint(dict(
                            article_id=old['id'], revision=old.get('revision'), actor=self.owner_id, evidence=evidence)))
                    require(old['stage'] == 'published' and old.get('revision')
                            and (codex_approved if approval.get('source') == 'codex'
                                 else approval.get('action') == 'approved')
                            and approval.get('user_id') == self.owner_id
                            and approval.get('revision') == old['revision'] == publication.get('revision')
                            and publication.get('verified') is True and readback.get('verified') is True
                            and readback.get('fingerprint') == old['revision'],
                            'revision already requested; reconcile existing job')
                    require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')",
                                           (old['id'],)).fetchone(), 'revision publication requires reconciliation')
                    previous.append(old)
            if previous:
                stamps = [_aware(j['publication'].get('remoteUpdatedAt')) for j in previous]
                latest_at = max(stamps)
                require(stamps.count(latest_at) == 1, 'revision publication order ambiguous')
                latest = previous[stamps.index(latest_at)]
                require(latest_at == _aware(base.get('updatedAt'))
                        and latest['publication'].get('url') == 'https://camp-gear-lab.com/articles/' + base['slug'],
                        'revision next baseline must match verified publication')
            job = dict(id='revision-' + secrets.token_hex(12), kind='article_revision',
                       revisionContext=context, priority=list(TARGETS).index(base['id']),
                       theme=dict(slug=base['slug'], title=base['title'], categoryId=base['categoryId'],
                                  productIds=context['targetProductIds']),
                       week=(now.date() - timedelta(days=now.weekday())).isoformat(), stage='candidate',
                       bundle=None, revision=None, review=None, approval=None, publication=None, social=None,
                       error=None, created_at=now.isoformat())
            return self._put(db, job, 'revision_requested')

    def list_jobs(self):
        with self._tx() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs ORDER BY rowid')]

    def narrow_candidate_products(self, id, theme, raw):
        """Local operator only: atomically narrow an untouched job and bind corrections.

        No generation, source-check exemption, owner approval or publication follows.
        Existing gather and bundle/source/image validation remain mandatory.
        """
        from catalog_corrections import validated_context, validate_context
        context = validated_context(raw)
        require(isinstance(theme, dict), 'complete narrowed theme required')
        theme = json.loads(canonical(theme))
        editable = {'title', 'query', 'selectionReason', 'productIds'}
        require(all(isinstance(theme.get(k), str) and theme[k].strip()
                    for k in ('title', 'query', 'selectionReason')), 'narrowing reason and theme required')
        ids = theme.get('productIds')
        require(isinstance(ids, list) and ids and all(isinstance(x, str) and x for x in ids)
                and len(ids) == len(set(ids)), 'nonempty distinct subset required')
        require(ids == [p['id'] for p in context['candidateProducts']], 'narrowing context IDs mismatch')
        with self._tx() as db:
            job = self._get(db, id)
            require(job.get('kind') != 'article_revision' and job['stage'] in ('candidate', 'error')
                    and all(job.get(k) is None for k in
                            ('bundle', 'revision', 'review', 'astraReview', 'approval', 'publication', 'social')),
                    'only untouched new candidate can be narrowed')
            require(not db.execute('SELECT 1 FROM effects WHERE job_id=?', (id,)).fetchone()
                    and not db.execute('SELECT 1 FROM requests WHERE job_id=?', (id,)).fetchone(),
                    'candidate side effects require reconciliation')
            old = job['theme']
            old_ids = old.get('productIds') if isinstance(old, dict) else None
            require(isinstance(old_ids, list) and all(isinstance(x, str) and x for x in old_ids)
                    and len(set(old_ids)) == len(old_ids) and len(ids) < len(old_ids)
                    and ids == [x for x in old_ids if x in ids], 'ordered strict subset required')
            require(all(k in old and k in theme for k in ('slug', 'categoryId'))
                    and canonical({k:v for k,v in old.items() if k not in editable}) ==
                    canonical({k:v for k,v in theme.items() if k not in editable}),
                    'narrowing cannot change theme identity')
            require(all(p['categoryId'] == theme['categoryId'] for p in
                        context['baseProducts'] + context['candidateProducts']), 'narrowing category mismatch')
            if 'catalogCorrectionContext' in job:
                previous = validate_context(job['catalogCorrectionContext'])
                require(canonical(context['baseProducts']) == canonical(
                    [p for p in previous['baseProducts'] if p['id'] in ids]),
                    'narrowing baseline changed')
            job.update(theme=theme, catalogCorrectionContext=json.loads(canonical(context)),
                       stage='candidate', error=None)
            return self._put(db, job, 'candidate_products_narrowed')

    def correct_candidate_theme(self, id, theme):
        """Trusted operator supplies the complete theme; no owner approval is granted."""
        require(isinstance(theme, dict), 'complete corrected theme required')
        theme = json.loads(canonical(theme))
        editable = {'title', 'query', 'selectionReason'}
        require(all(isinstance(theme.get(k), str) and theme[k].strip() for k in editable),
                'corrected title query and selection reason required')
        with self._tx() as db:
            job = self._get(db, id)
            require(job.get('kind') != 'article_revision' and job['stage'] in ('candidate', 'error')
                    and job.get('bundle') is None and job.get('revision') is None
                    and not job.get('approval') and not job.get('publication'),
                    'only unstaged new article theme can be corrected')
            require(not db.execute('SELECT 1 FROM effects WHERE job_id=?', (id,)).fetchone(),
                    'candidate effects require reconciliation')
            old = job['theme']
            require(isinstance(old, dict) and all(k in old and k in theme
                    for k in ('slug', 'categoryId', 'productIds')), 'complete theme identity required')
            require(canonical({k: v for k, v in old.items() if k not in editable}) ==
                    canonical({k: v for k, v in theme.items() if k not in editable}),
                    'only title query and selection reason may change')
            job.update(theme=theme, stage='candidate', error=None)
            self._invalidate(db, id)
            return self._put(db, job, 'candidate_theme_corrected')

    def extend_nonproduct_sources(self, id, receipt):
        """Apply a verified, CAS-bound source handoff without starting production."""
        from source_enrichment import apply
        return apply(self, id, receipt)

    def revise_candidate(self, id, title, selection_reason):
        require(isinstance(title, str) and title.strip() and isinstance(selection_reason, str) and selection_reason.strip(),
                'candidate title and reason required')
        with self._tx() as db:
            job = self._get(db, id)
            require(job['stage'] in ('candidate', 'error', 'held') and not job.get('bundle')
                    and not job.get('approval') and not job.get('publication'), 'only unstaged candidate can be revised')
            job['theme'] = dict(job['theme'], title=title, selectionReason=selection_reason)
            return self._put(db, job, 'candidate_revised')

    def get_job(self, id):
        with self._tx() as db:
            return self._get(db, id)

    def save_bundle(self, id, bundle, expected_revision=None):
        require(isinstance(bundle, dict) and all(k in bundle for k in ('article', 'products', 'images', 'brief', 'references')), 'complete bundle required')
        revision = fingerprint(bundle)
        with self._tx() as db:
            job = self._get(db, id)
            require(not (job['publication'] and job['publication'].get('verified') is True),
                    'published bundle is immutable; use a separate revision workflow')
            if job.get('kind') == 'article_revision':
                from revisions import validate_revision_bundle
                validate_revision_bundle(job, bundle)
                require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status!='failed'", (id,)).fetchone(),
                        'revision effect requires reconciliation')
            if 'catalogCorrectionContext' in job or 'catalogCorrectionContext' in bundle:
                from catalog_corrections import validate_bundle
                validate_bundle(job, bundle)
                require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status!='failed'", (id,)).fetchone(),
                        'catalog correction effect requires reconciliation')
            require(expected_revision is None or job['revision'] == expected_revision, 'revision conflict')
            if revision != job['revision']:
                job.update(bundle=json.loads(canonical(bundle)), revision=revision, review=None, approval=None,
                           publication=None, social=None, error=None, stage='draft')
                if job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job:
                    job['astraReview'] = None
                self._invalidate(db, id)
                return self._put(db, job, 'bundle')
            return job

    def set_stage(self, id, stage, detail=None):
        require(stage in ('candidate', 'draft', 'review', 'held', 'rejected', 'error'), 'protected or unknown stage')
        with self._tx() as db:
            job = self._get(db, id)
            require(not (job['publication'] and job['publication'].get('verified') is True),
                    'published state is protected')
            job['stage'] = stage
            job['error'] = detail if stage == 'error' else None
            if stage in ('held', 'rejected', 'error', 'draft'):
                job['approval'] = None
                self._invalidate(db, id)
            return self._put(db, job, 'stage')

    def record_review(self, id, revision, review):
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            require(revision == job['revision'], 'revision mismatch')
            valid_review(review, revision, job.get('bundle'))
            job.update(review=json.loads(canonical(review)), approval=None, stage='review')
            self._invalidate(db, id, 'article')
            return self._put(db, job, 'review')

    def record_astra_review(self, id, revision, review):
        """Explicit operator-recorded Astra QA, separate from owner publication approval."""
        with self._tx() as db:
            job = self._get(db, id)
            require((job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job) and job['stage'] == 'review'
                    and not job.get('approval') and not job.get('publication'),
                    'only unapproved revision or catalog correction in review can receive Astra QA')
            self._current(job)
            require(revision == job['revision'], 'revision mismatch')
            valid_review(job['review'], revision, job.get('bundle'))
            valid_astra_review(review, revision)
            job['astraReview'] = dict(json.loads(canonical(review)), recordedAt=timestamp().isoformat())
            return self._put(db, job, 'astra_review')

    def create_request(self, id, kind='article', now=None):
        now = timestamp(now)
        require(kind in ('article', 'social'), 'unknown request kind')
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            if kind == 'article':
                revision = job['revision']
                valid_review(job['review'], revision, job.get('bundle'))
                if job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job:
                    valid_astra_review(job.get('astraReview'), revision)
            else:
                require(job['publication'] and job['publication'].get('verified') is True and job['social'], 'verified publication and social required')
                require(not job['social'].get('publication'), 'posted social is immutable')
                revision = fingerprint(job['social']['proposal'])
                require(revision == job['social']['revision'], 'social changed')
                valid_review(job['social']['review'], revision, job['social'].get('proposal'))
            request_id, nonce = 'camp-' + secrets.token_hex(12), secrets.token_hex(16)
            payload = dict(request_id=request_id, article_id=id, manifest_hash=revision, nonce=nonce)
            request = dict(payload, kind=kind, payload=payload, status='created', expires_at=(now + timedelta(days=7)).isoformat())
            self._invalidate(db, id, kind)
            db.execute('INSERT INTO requests VALUES (?,?,?,?)', (request_id, id, kind, canonical(request)))
            self._event(db, id, 'request', request, now)
            return request

    def mark_delivered(self, request_id, parts, card_ts):
        require(isinstance(parts, dict), 'delivery parts must include scope')
        scope = parts.get('scope', parts)
        require(isinstance(scope, dict) and all(scope.get(k) for k in SCOPE) and bool(card_ts), 'delivery scope/card required')
        require(scope['user_id'] == self.owner_id, 'owner mismatch')
        with self._tx() as db:
            row = db.execute('SELECT data FROM requests WHERE id=?', (request_id,)).fetchone()
            require(row is not None, 'unknown request')
            request = json.loads(row[0])
            if request['status'] == 'delivered':
                require(request['card_ts'] == card_ts and request['parts'] == parts, 'delivery conflict')
                return request
            require(request['status'] == 'created', 'request inactive')
            request.update(status='delivered', scope={k: scope[k] for k in SCOPE}, card_ts=card_ts, parts=parts)
            db.execute('UPDATE requests SET data=? WHERE id=?', (canonical(request), request_id))
            self._event(db, request['article_id'], 'delivered', request)
            return request

    def decide(self, event, scope, now=None):
        now = timestamp(now)
        require(all(scope.get(k) and event.get(k) == scope[k] for k in SCOPE), 'scope mismatch')
        require(event['user_id'] == self.owner_id, 'owner mismatch')
        require(bool(event.get('event_id')), 'event id required')
        with self._tx() as db:
            prior = db.execute('SELECT data FROM decisions WHERE id=?', (event['event_id'],)).fetchone()
            if prior:
                saved = json.loads(prior[0])
                require(saved['event'] == event, 'event id collision')
                return saved['result']
            row = db.execute('SELECT data FROM requests WHERE id=?', (event.get('request_id'),)).fetchone()
            require(row is not None, 'unknown request')
            req = json.loads(row[0])
            require(req['status'] == 'delivered' and req['card_ts'] == event.get('card_ts'), 'undelivered or stale request')
            require(all(req['scope'][k] == scope[k] for k in SCOPE), 'delivery scope mismatch')
            require(now < timestamp(req['expires_at']), 'request expired')
            require(all(isinstance(event.get(k), str) and hmac.compare_digest(event[k].encode('utf-8'), req[k].encode('utf-8'))
                        for k in ('nonce', 'manifest_hash', 'article_id')), 'request payload mismatch')
            stages = {'camp_review_approve': 'approved', 'camp_review_reject': 'rejected', 'camp_review_hold': 'held'}
            require(event.get('action_id') in stages, 'unknown action')
            job = self._get(db, req['article_id'])
            self._current(job)
            target = job if req['kind'] == 'article' else job['social']
            require(target and target['revision'] == req['manifest_hash'], 'stale manifest')
            if req['kind'] == 'social':
                require(fingerprint(target['proposal']) == target['revision'] and job['publication']
                        and job['publication'].get('verified') is True, 'social changed or unpublished')
            valid_review(target['review'], target['revision'], target.get('bundle') or target.get('proposal'))
            stage = stages[event['action_id']]
            target['approval'] = dict(request_id=req['request_id'], revision=req['manifest_hash'], user_id=self.owner_id,
                                      action=stage, at=now.isoformat()) if stage == 'approved' else None
            job['stage'] = ('social_' if req['kind'] == 'social' else '') + stage
            req['status'] = 'decided'
            db.execute('UPDATE requests SET data=? WHERE id=?', (canonical(req), req['request_id']))
            result = self._put(db, job, 'decision')
            db.execute('INSERT INTO decisions VALUES (?,?)', (event['event_id'], canonical(dict(event=event, result=result))))
            return result

    def _validate_codex_batch(self, db, id, revision, actor, evidence):
        """Operator-resolved finite Slack batch, with actual owner text preserved.

        External operator must verify the authenticated message and its referent.
        This is NOT a Slack button event and never invents a button nonce/event.
        """
        require(re.fullmatch(r'(?:<@[A-Z0-9]+>\s*)?(?:記事は)?全て公開[。.]?', evidence['text'].strip()),
                'explicit batch publication instruction required')
        scope = evidence.get('slack_scope') or {}
        require(set(scope) == set(SCOPE) and all(isinstance(scope[k], str) and scope[k] for k in SCOPE)
                and scope['user_id'] == actor and scope['thread_ts'] == evidence['thread_id'], 'batch scope required')
        message_ts, context_ts = evidence['message_id'], evidence.get('context_message_id', '')
        require(all(isinstance(t, str) and re.fullmatch(r'[0-9]+\.[0-9]+', t)
                    for t in (message_ts, context_ts)), 'Slack timestamps required')
        require(float(context_ts) < float(message_ts), 'batch context must precede approval')
        items = evidence.get('batch')
        require(isinstance(items, list) and 1 <= len(items) <= 20, 'finite batch required')
        require(all(isinstance(i, dict) and set(i) == {'article_id', 'revision', 'card_ts'}
                    and all(isinstance(v, str) and v for v in i.values()) for i in items), 'batch binding required')
        require(len({i['article_id'] for i in items}) == len(items), 'duplicate batch article')
        require(any(i['article_id'] == id and i['revision'] == revision for i in items), 'article outside approved batch')
        for item in items:
            job = self._get(db, item['article_id'])
            require(job['revision'] == item['revision'], 'batch revision changed')
            require(re.fullmatch(r'[0-9]+\.[0-9]+', item['card_ts'])
                    and float(item['card_ts']) <= float(context_ts), 'card must precede context')
            requests = [json.loads(row[0]) for row in db.execute(
                "SELECT data FROM requests WHERE job_id=? AND kind='article'", (item['article_id'],))]
            matched = [r for r in requests if r.get('manifest_hash') == item['revision']
                       and r.get('card_ts') == item['card_ts'] and r.get('scope') == scope]
            require(bool(matched), 'exact batch card delivery required')
            events = [json.loads(row[0]) for row in db.execute(
                "SELECT data FROM events WHERE job_id=? AND kind='delivered'", (item['article_id'],))]
            require(any(all(e.get(k) == r.get(k) for k in
                            ('request_id', 'manifest_hash', 'article_id', 'scope', 'parts', 'card_ts'))
                        and e.get('status') == 'delivered' for r in matched for e in events),
                    'verified batch delivery event required')
            require(any(timestamp(r['expires_at']).timestamp() >= float(message_ts) for r in matched),
                    'batch approval after card expiry')

    def approve_from_codex(self, id, revision, actor, evidence):
        """Trusted local operator API; explicit Runtime CLI command only, never tick.

        Actor strings/evidence are not authentication. The invoking operator/tool
        must verify the owner's actual message and allowed user approval scope.
        Codex models cannot self-approve or fabricate evidence. This records article
        authority only; publication and social retain their separate gates.
        Text must be exactly '記事 <id> 版 <revision> を公開してください' or
        'publish <id> <revision>' (optional final punctuation). A finite Slack
        batch may instead retain the actual '全て公開' text and bind each delivered
        card/revision in evidence; _validate_codex_batch checks these bindings.
        """
        require(actor == self.owner_id, 'owner mismatch')
        require(isinstance(evidence, dict) and evidence.get('source') == 'codex', 'Codex evidence required')
        require(all(isinstance(evidence.get(k), str) and evidence[k].strip()
                    for k in ('thread_id', 'message_id', 'text')), 'message evidence required')
        require(isinstance(id, str) and isinstance(revision, str), 'article and revision required')
        directive = (rf'(?:記事\s+{re.escape(id)}\s+版\s+{re.escape(revision)}\s+を公開してください[。.]?'
                     rf'|publish\s+{re.escape(id)}\s+{re.escape(revision)}[.]?)')
        is_batch = 'batch' in evidence
        if not is_batch:
            require(re.fullmatch(directive, evidence['text'].strip()) is not None, 'explicit article/version publication instruction required')
        # Snapshot caller-owned JSON before the transactional approval record.
        evidence = json.loads(canonical(evidence))
        with self._tx() as db:
            if is_batch:
                self._validate_codex_batch(db, id, revision, actor, evidence)
            job = self._get(db, id)
            self._current(job)
            require(revision == job['revision'], 'revision mismatch')
            valid_review(job['review'], revision, job.get('bundle'))
            require(not job['publication'] and not job['approval'], 'already published or approved')
            require(job['stage'] not in ('approved', 'published', 'publishing', 'scheduled',
                                         'schedule_pending', 'publication_pending'), 'publication/schedule pending')
            effects = db.execute('SELECT kind,status FROM effects WHERE job_id=?', (id,)).fetchall()
            require(not any(kind != 'social' and status != 'failed' for kind, status in effects), 'publication/schedule effect already claimed')
            request_id = 'codex-' + fingerprint(dict(article_id=id, revision=revision, actor=actor, evidence=evidence))
            job.update(approval=dict(user_id=actor, request_id=request_id, revision=revision,
                                     at=timestamp().isoformat(), source='codex', evidence=evidence), stage='approved')
            self._invalidate(db, id, 'article')
            return self._put(db, job, 'codex_approval')

    def approve_social_from_codex(self, id, revision, actor, evidence):
        """Trusted local operator API, explicit CLI only; never authenticate or post here.

        The operator verifies the real owner's message and posting scope externally.
        No Slack decision or message ID is invented. The retained source is limited
        to the actual text, Codex thread and operator-observed timestamp.
        """
        require(actor == self.owner_id, 'owner mismatch')
        require(isinstance(id, str) and isinstance(revision, str)
                and re.fullmatch(r'[a-f0-9]{64}', revision), 'article and social revision required')
        require(isinstance(evidence, dict) and set(evidence) ==
                {'source', 'thread_id', 'observed_at', 'text', 'directive'}
                and evidence.get('source') == 'codex', 'Codex social evidence required')
        require(all(isinstance(evidence.get(k), str) and evidence[k].strip()
                    for k in ('thread_id', 'observed_at', 'text')), 'message evidence required')
        timestamp(evidence['observed_at'])
        valid_codex_social_instruction(id, revision, evidence['text'])
        evidence = json.loads(canonical(evidence))
        request_id = 'codex-social-' + fingerprint(dict(article_id=id, revision=revision, actor=actor, evidence=evidence))
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            publication = job.get('publication') or {}
            readback = publication.get('readback') or {}
            require(publication.get('verified') is True and publication.get('revision') == job['revision']
                    and isinstance(publication.get('url'), str) and publication['url'].startswith('https://')
                    and readback.get('verified') is True and readback.get('fingerprint') == job['revision'],
                    'current verified article publication required')
            social = job.get('social') or {}
            proposal = social.get('proposal') or {}
            require(social.get('revision') == revision and fingerprint(proposal) == revision, 'social revision mismatch')
            valid_review(social.get('review'), revision, social.get('proposal'))
            valid_social_mode(proposal)
            valid_social_images(job, proposal)
            require(proposal.get('platform') == 'x' and proposal.get('deliveryMode') == 'auto_x'
                    and self.target_account_id and proposal.get('targetAccountId') == self.target_account_id,
                    'configured X account required')
            require(proposal.get('url') == publication['url'] and proposal.get('replyText') == publication['url'],
                    'published article social URL required')
            binding = dict(article_id=id, revision=revision, targetAccountId=proposal['targetAccountId'],
                           textHash=fingerprint(proposal['text']),
                           imageSha256s=[image['sha256'] for image in proposal['images']],
                           replyText=proposal['replyText'])
            require(evidence['directive'] == binding, 'social directive binding mismatch')
            require(not social.get('publication'), 'social already published')
            require(not db.execute('SELECT 1 FROM effects WHERE job_id=? AND kind=?', (id, 'social')).fetchone(),
                    'social effect requires reconciliation')
            for folder in ('social-publications', 'social-outbox'):
                marker = self.root / folder / (revision + '.json')
                require(not marker.exists() and not marker.is_symlink(), 'social journal/outbox requires reconciliation')
            approval = social.get('approval')
            if approval:
                require(job['stage'] == 'social_approved' and approval.get('request_id') == request_id
                        and approval.get('evidence') == evidence and approval.get('source') == 'codex'
                        and approval.get('action') == 'approved' and approval.get('user_id') == actor
                        and approval.get('revision') == revision, 'social already approved or replay conflict')
                return job
            require(job['stage'] in ('social_held', 'social_review'), 'social approval stage unavailable')
            requests = [json.loads(row[0]) for row in db.execute(
                'SELECT data FROM requests WHERE job_id=? AND kind=?', (id, 'social'))]
            deliveries = [json.loads(row[0]) for row in db.execute(
                'SELECT data FROM events WHERE job_id=? AND kind=?', (id, 'delivered'))]
            delivered = False
            for req in requests:
                scope, parts = req.get('scope') or {}, req.get('parts') or {}
                part_scope = parts.get('scope', parts) if isinstance(parts, dict) else None
                if (req.get('manifest_hash') != revision or not isinstance(req.get('card_ts'), str)
                        or not req['card_ts'] or not isinstance(scope, dict) or not isinstance(part_scope, dict)
                        or not all(scope.get(k) for k in SCOPE) or scope.get('user_id') != actor
                        or any(part_scope.get(k) != scope[k] for k in SCOPE)):
                    continue
                if any(all(event.get(k) == req.get(k) for k in
                           ('request_id', 'manifest_hash', 'article_id', 'scope', 'parts', 'card_ts'))
                       and event.get('status') == 'delivered' for event in deliveries):
                    delivered = True
                    break
            require(delivered, 'exact social revision delivery evidence required')
            social['approval'] = dict(action='approved', user_id=actor, request_id=request_id, revision=revision,
                source='codex', evidence=evidence, at=timestamp().isoformat(),
                evidenceLimitations='Operator-observed Codex thread, actual text and timestamp; no message ID or Slack decision.')
            job['stage'] = 'social_approved'
            self._invalidate(db, id, 'social')
            return self._put(db, job, 'codex_social_approval')

    def claim_effect(self, id, kind):
        require(kind in ('publish', 'publication', 'social'), 'unknown effect')
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            target = job['social'] if kind == 'social' else job
            if kind == 'social':
                require(job['publication'] and job['publication'].get('verified') is True and target
                        and fingerprint(target['proposal']) == target['revision'], 'current social publication/proposal required')
            require(target and target.get('approval') and target['approval']['revision'] == target['revision'], 'current approval required')
            row = db.execute('SELECT status FROM effects WHERE job_id=? AND kind=?', (id, kind)).fetchone()
            if row and row[0] != 'failed':
                return False
            db.execute('INSERT OR REPLACE INTO effects VALUES (?,?,?,?)', (id, kind, 'in_flight', '{}'))
            self._event(db, id, 'effect_claim', {'kind': kind, 'revision': target['revision']})
            return True

    def finish_effect(self, id, kind, result):
        require(isinstance(result, dict) and result.get('status') in ('success', 'unknown', 'failed'), 'invalid effect result')
        with self._tx() as db:
            job = self._get(db, id)
            row = db.execute('SELECT status FROM effects WHERE job_id=? AND kind=?', (id, kind)).fetchone()
            require(row and row[0] == 'in_flight', 'effect not in flight')
            db.execute('UPDATE effects SET status=?,data=? WHERE job_id=? AND kind=?', (result['status'], canonical(result), id, kind))
            job['error'] = result if result['status'] != 'success' else None
            self._event(db, id, 'effect_result', {'kind': kind, 'result': result})
            return self._put(db, job, 'effect_finished')

    def record_publication(self, id, revision, evidence):
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            require(revision == job['revision'] and job['approval'] and job['approval']['revision'] == revision, 'current approval required')
            readback = evidence.get('readback', {})
            require(evidence.get('verified') is True and isinstance(evidence.get('url'), str)
                    and evidence['url'].startswith('https://') and isinstance(readback, dict)
                    and readback.get('verified') is True and readback.get('fingerprint') == revision, 'verified URL readback required')
            context = ((job.get('bundle') or {}).get('article') or {}).get('generationMeta', {}).get('editorialContext')
            if context is not None:
                from topic_selection import validate_nonproduct_bundle
                validate_nonproduct_bundle(job['bundle'])
                expected_route = {'status': 'not_applicable', 'measured': False,
                                  'sponsoredCtaCount': 0,
                                  'reason': 'verified_nonproduct_article',
                                  'verifiedBy': 'deterministic_contract_v1'}
                proof_ids = context['imageProofIds']
                expected_images = [{key: image.get(key) for key in
                    ('id', 'url', 'sha256', 'size', 'contentType')}
                    for image in job['bundle']['images'] if image.get('id') in proof_ids]
                require(readback.get('productIds') == []
                        and readback.get('editorialContext') == context
                        and readback.get('commercialRoute') == expected_route
                        and readback.get('imageProofs') == expected_images
                        and [item['id'] for item in expected_images] == proof_ids,
                        'nonproduct public metadata readback required')
            job.update(publication=dict(evidence, revision=revision, at=timestamp().isoformat()), stage='published')
            return self._put(db, job, 'publication')

    def record_social(self, id, proposal, review):
        require(isinstance(proposal, dict), 'social proposal required')
        valid_social_mode(proposal)
        revision = fingerprint(proposal)
        valid_review(review, revision)
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            require(job.get('kind') != 'article_revision', 'revision has no automatic social workflow')
            require(job['publication'] and job['publication'].get('verified') is True, 'verified publication required')
            require(not (job.get('social') or {}).get('publication'), 'posted social is immutable')
            if job['social'] and job['social']['revision'] == revision:
                return job
            if job.get('social'):
                require('supplementalCard' not in job['social']['proposal'],
                        'supplemental card requires explicit image refresh')
                old_revision = job['social']['revision']
                require(not (self.root / 'social-publications' / (old_revision + '.json')).exists()
                        and not (self.root / 'social-outbox' / (old_revision + '.json')).exists()
                        and not (self.root / 'buffer-publications' / (old_revision + '.json')).exists()
                        and not db.execute('SELECT 1 FROM effects WHERE job_id=? AND kind=?', (id, 'social')).fetchone(),
                        'social effect requires explicit reconciliation')
            require('supplementalCard' not in proposal, 'supplemental card requires explicit image refresh')
            self._invalidate(db, id, 'social')
            job.update(social=dict(proposal=json.loads(canonical(proposal)), revision=revision,
                                   review=json.loads(canonical(review)), approval=None), stage='social_review')
            return self._put(db, job, 'social')

    def hold_social_refresh(self, id, *, expected_social_revision):
        """Invalidate old buttons without discarding the original approval/effect evidence."""
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            social = job.get('social') or {}
            require(social.get('revision') == expected_social_revision
                    and fingerprint(social.get('proposal')) == expected_social_revision, 'social revision conflict')
            require(job.get('publication') and job['publication'].get('verified') is True
                    and not social.get('publication') and job['stage'] in
                    ('social_review', 'social_approved', 'social_held', 'social_rejected'), 'social refresh hold unavailable')
            self._invalidate(db, id, 'social')
            job['stage'] = 'social_held'
            return self._put(db, job, 'social_refresh_hold')

    def refresh_social_images(self, id, proposal, review, *, expected_social_revision, prior_main_readback=None):
        """Explicit operator transition. Retain original journals and partial effects verbatim."""
        revision = fingerprint(proposal)
        valid_review(review, revision)
        valid_social_mode(proposal)
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            old = job.get('social')
            require(old and old['revision'] == expected_social_revision, 'social revision conflict')
            require(not old.get('publication'), 'posted social is immutable')
            require(revision != old['revision'] and proposal.get('supplementalCard'), 'new supplemental card required')
            valid_social_images(job, proposal)
            valid_image_refresh(old, proposal, review)
            require(not db.execute('SELECT 1 FROM effects WHERE job_id=? AND kind=?', (id, 'social')).fetchone()
                    and not (self.root / 'social-outbox' / (old['revision'] + '.json')).exists()
                    and not (self.root / 'buffer-publications' / (old['revision'] + '.json')).exists(),
                    'legacy social effect requires reconciliation')
            marker = self.root / 'social-publications' / (old['revision'] + '.json')
            journal = None
            if marker.exists():
                require(job['stage'] == 'social_held', 'partial social must be held before refresh')
                require(not marker.is_symlink() and marker.stat().st_mode & 0o777 == 0o600,
                        'social journal invalid')
                journal = json.loads(marker.read_text())
                main = prior_main_readback or {}
                uploads = journal.get('uploads') or []
                require(journal.get('revision') == journal.get('proposalFingerprint') == old['revision']
                        and journal.get('account') == old['proposal'].get('targetAccountId')
                        and journal.get('phase') == 'mainread' and journal.get('pending') is None
                        and not journal.get('replyId') and journal.get('mainId')
                        and main.get('id') == journal['mainId'] and main.get('authorId') == journal['account']
                        and exact_x_text(main, old['proposal']['text']) and main.get('replyTo') is None
                        and len(uploads) == len(old['proposal']['images'])
                        and all(u.get('sha256') == i.get('sha256') for u, i in zip(uploads, old['proposal']['images']))
                        and main.get('mediaKeys') == [u.get('mediaKey') for u in uploads],
                        'verified existing main readback required')
                require(proposal.get('approvalNotice') == REFRESH_NOTICE
                        and proposal.get('priorPostUrl') == 'https://x.com/i/web/status/' + journal['mainId'],
                        'new publication notice required')
            else:
                require(prior_main_readback is None and not proposal.get('approvalNotice')
                        and not proposal.get('priorPostUrl'), 'unexpected prior post evidence')
            history = dict(social=old, journal=journal, mainReadback=prior_main_readback,
                           kind='superseded_image_proposal', at=timestamp().isoformat())
            job.setdefault('socialHistory', []).append(history)
            self._invalidate(db, id, 'social')
            job.update(social=dict(proposal=json.loads(canonical(proposal)), revision=revision,
                                   review=json.loads(canonical(review)), approval=None), stage='social_review')
            return self._put(db, job, 'social_image_refresh')

    def enable_social_autopost(self, id, target_id):
        """Explicit mode-only migration; carries real content review, never a new LLM review."""
        require(isinstance(target_id, str) and re.fullmatch(r'[1-9][0-9]{0,19}', target_id), 'fixed X account ID required')
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            social = job.get('social')
            require(job.get('publication') and job['publication'].get('verified') is True and social,
                    'verified article and reviewed social required')
            require(job['stage'] in ('social_review', 'social_approved', 'social_held', 'social_rejected'),
                    'social mode cannot change in this stage')
            require(not social.get('publication'), 'posted social is immutable')
            require(not db.execute('SELECT 1 FROM effects WHERE job_id=? AND kind=?', (id, 'social')).fetchone(),
                    'social effect requires reconciliation')
            require(not (self.root / 'social-outbox' / (social['revision'] + '.json')).exists(),
                    'legacy social handoff requires reconciliation')
            require(not (self.root / 'social-publications' / (social['revision'] + '.json')).exists(),
                    'social publisher journal requires reconciliation')
            old = social['proposal']
            require(old.get('deliveryMode', 'manual') == 'manual' and not old.get('targetAccountId'),
                    'only manual social can be migrated')
            require(fingerprint(old) == social['revision'], 'social changed')
            valid_review(social['review'], social['revision'], social.get('proposal'))
            proposal = dict(old, deliveryMode='auto_x', targetAccountId=target_id)
            valid_social_mode(proposal)
            revision = fingerprint(proposal)
            transition = dict(kind='delivery_mode_only', fromRevision=social['revision'], toRevision=revision,
                              targetAccountId=target_id, at=timestamp().isoformat(),
                              modelRerun=False, originalProposal=old, originalContentReview=social['review'])
            review = dict(social['review'], fingerprint=revision,
                          modeBinding=dict(fromRevision=social['revision'], transition='delivery_mode_only', modelRerun=False))
            self._invalidate(db, id, 'social')
            job.update(social=dict(proposal=proposal, revision=revision, review=review, approval=None,
                                   modeTransition=transition), stage='social_review')
            return self._put(db, job, 'social_mode_migrated')

    def record_buffer_social_schedule(self, id, revision, evidence, *, now=None,
                                      poll_interval_seconds=1800, max_due_polls=3):
        """Persist an exact Buffer schedule without treating it as an X publication."""
        require(isinstance(evidence, dict) and evidence.get('status') in ('scheduled', 'pending')
                and evidence.get('verified') is False and evidence.get('fingerprint') == revision,
                'verified Buffer schedule required')
        require(isinstance(evidence.get('bufferPostId'), str) and evidence['bufferPostId'].strip(),
                'Buffer post identity required')
        due = timestamp(evidence.get('dueAt'))
        now = timestamp(now)
        require(type(poll_interval_seconds) is int and 60 <= poll_interval_seconds <= 86400,
                'buffer poll interval invalid')
        require(type(max_due_polls) is int and max_due_polls == 3,
                'buffer due poll limit invalid')
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            social = job.get('social') or {}
            require(social.get('revision') == revision
                    and fingerprint(social.get('proposal')) == revision, 'social revision mismatch')
            proposal = social['proposal']
            valid_social_mode(proposal)
            valid_review(social.get('review'), revision)
            valid_social_images(job, proposal)
            publication = job.get('publication') or {}
            readback = publication.get('readback') or {}
            require(publication.get('verified') is True
                    and publication.get('revision') == job.get('revision')
                    and readback.get('verified') is True
                    and readback.get('fingerprint') == job.get('revision'),
                    'verified article publication required')
            approval = social.get('approval') or {}
            require(proposal.get('deliveryMode') == 'buffer_x'
                    and approval.get('action') == 'approved'
                    and approval.get('revision') == revision
                    and approval.get('user_id') == self.owner_id,
                    'current Buffer owner approval required')
            require(job['stage'] in ('social_approved', 'social_scheduled'),
                    'Buffer schedule stage unavailable')
            saved = social.get('bufferSchedule')
            immutable = {'fingerprint': revision, 'bufferPostId': evidence['bufferPostId'],
                         'dueAt': due.isoformat()}
            if saved:
                require(all(saved.get(key) == value for key, value in immutable.items()),
                        'Buffer schedule conflict')
            polls = (saved or {}).get('duePolls', 0)
            require(type(polls) is int and 0 <= polls <= max_due_polls,
                    'Buffer schedule requires reconciliation')
            if now >= due and evidence['status'] == 'pending' and polls < max_due_polls:
                polls += 1
            terminal = polls >= max_due_polls and evidence['status'] == 'pending'
            schedule = dict(immutable,
                            status='requires_reconciliation' if terminal else evidence['status'],
                            verified=False, duePolls=polls,
                            nextCheckAt=None if terminal else
                            (due if now < due else
                             now + timedelta(seconds=poll_interval_seconds)).isoformat())
            social['bufferSchedule'] = schedule
            job['stage'] = 'social_scheduled'
            return self._put(db, job, 'buffer_social_scheduled')

    def record_buffer_social_publication(self, id, revision, evidence):
        """Accept only a Buffer-bound, exact X thread readback for the approved proposal."""
        require(isinstance(evidence, dict) and evidence.get('status') == 'verified'
                and evidence.get('verified') is True and evidence.get('fingerprint') == revision,
                'verified Buffer publication required')
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            social = job.get('social') or {}
            require(social.get('revision') == revision
                    and fingerprint(social.get('proposal')) == revision, 'social revision mismatch')
            proposal = social['proposal']
            valid_social_mode(proposal)
            valid_social_images(job, proposal)
            approval = social.get('approval') or {}
            require(proposal.get('deliveryMode') == 'buffer_x'
                    and approval.get('action') == 'approved'
                    and approval.get('revision') == revision
                    and approval.get('user_id') == self.owner_id,
                    'current Buffer owner approval required')
            schedule = social.get('bufferSchedule') or {}
            require(job['stage'] == 'social_scheduled'
                    and evidence.get('bufferPostId') == schedule.get('bufferPostId'),
                    'bound Buffer schedule required')
            account = proposal['targetAccountIdX']
            readback = evidence.get('readback') or {}
            main, reply, media = readback.get('main'), readback.get('reply'), readback.get('media')
            require(readback.get('verified') is True and readback.get('fingerprint') == revision
                    and readback.get('accountId') == account and evidence.get('accountId') == account
                    and isinstance(main, dict) and isinstance(reply, dict),
                    'bound Buffer X readback required')
            require(isinstance(media, dict) and media.get('verified') is True
                    and isinstance(media.get('items'), list),
                    'Buffer X media identity required')
            require(main.get('id') == evidence.get('mainId')
                    and reply.get('id') == evidence.get('replyId')
                    and re.fullmatch(r'[1-9][0-9]*', str(main.get('id', '')))
                    and re.fullmatch(r'[1-9][0-9]*', str(reply.get('id', '')))
                    and main.get('authorId') == account and reply.get('authorId') == account
                    and exact_x_text(main, proposal['text'])
                    and exact_x_text(reply, proposal['replyText'])
                    and main.get('replyTo') is None and reply.get('replyTo') == main.get('id')
                    and isinstance(main.get('mediaKeys'), list)
                    and len(main['mediaKeys']) == len(proposal['images'])
                    and reply.get('mediaKeys') == [], 'approved Buffer X thread mismatch')
            media_keys = []
            require(len(media['items']) == len(proposal['images']),
                    'Buffer X media identity required')
            for image, actual in zip(proposal['images'], media['items']):
                require(isinstance(actual, dict)
                        and isinstance(actual.get('mediaKey'), str) and actual['mediaKey']
                        and isinstance(actual.get('url'), str)
                        and re.fullmatch(r'https://pbs\.twimg\.com/[^?#]+', actual['url'])
                        and re.fullmatch(r'[a-f0-9]{64}', str(actual.get('actualSha256', ''))),
                        'Buffer X media identity required')
                identity = actual.get('identity')
                require(isinstance(identity, dict)
                        and identity.get('approvedSha256') == image.get('sha256'),
                        'Buffer X media identity required')
                if identity.get('kind') == 'byte_sha256':
                    require(set(identity) == {'kind', 'approvedSha256'}
                            and actual['actualSha256'] == image['sha256'],
                            'Buffer X media identity required')
                elif identity.get('kind') == 'decoded_rgba_sha256':
                    width, height = identity.get('width'), identity.get('height')
                    require(set(identity) == {'kind', 'approvedSha256', 'pixelSha256',
                                              'width', 'height'}
                            and re.fullmatch(r'[a-f0-9]{64}', str(identity.get('pixelSha256', '')))
                            and type(width) is int and type(height) is int
                            and 0 < width <= 8192 and 0 < height <= 8192
                            and width * height <= 16 * 1024 * 1024,
                            'Buffer X media identity required')
                elif identity.get('kind') == 'jpeg_encoding_reproduced':
                    width, height = identity.get('width'), identity.get('height')
                    require(set(identity) == {'kind', 'approvedSha256', 'pixelSha256',
                                              'width', 'height', 'quantizationSha256',
                                              'subsampling'}
                            and re.fullmatch(r'[a-f0-9]{64}',
                                             str(identity.get('pixelSha256', '')))
                            and re.fullmatch(r'[a-f0-9]{64}',
                                             str(identity.get('quantizationSha256', '')))
                            and type(identity.get('subsampling')) is int
                            and identity['subsampling'] in (0, 1, 2)
                            and type(width) is int and type(height) is int
                            and 0 < width <= 8192 and 0 < height <= 8192
                            and width * height <= 16 * 1024 * 1024,
                            'Buffer X media identity required')
                else:
                    raise ValueError('Buffer X media identity required')
                media_keys.append(actual['mediaKey'])
            require(len(set(media_keys)) == len(media_keys)
                    and main['mediaKeys'] == media_keys,
                    'Buffer X media identity required')
            publication = json.loads(canonical(evidence))
            publication.update(at=timestamp().isoformat(),
                               mainUrl='https://x.com/i/web/status/' + main['id'],
                               replyUrl='https://x.com/i/web/status/' + reply['id'])
            social['publication'] = publication
            job['stage'] = 'social_posted'
            self._invalidate(db, id, 'social')
            return self._put(db, job, 'buffer_social_publication')

    def record_social_publication(self, id, revision, evidence):
        """Accept only bound main/reply/media readbacks from the real publisher."""
        require(isinstance(evidence, dict), 'social publication evidence required')
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            social = job.get('social')
            require(social and social['revision'] == revision and fingerprint(social['proposal']) == revision,
                    'social revision mismatch')
            proposal = social['proposal']
            valid_social_mode(proposal)
            valid_social_images(job, proposal)
            require(proposal.get('deliveryMode') == 'auto_x', 'manual approval cannot authorize X posting')
            approval = social.get('approval') or {}
            require(approval.get('revision') == revision and approval.get('user_id') == self.owner_id
                    and approval.get('action') == 'approved', 'current social owner approval required')
            valid_review(social['review'], revision)
            require(job.get('publication') and job['publication'].get('verified') is True
                    and (job['publication'].get('readback') or {}).get('fingerprint') == job['revision']
                    and (job['publication'].get('readback') or {}).get('verified') is True,
                    'verified article publication required')
            require(proposal.get('platform') == 'x' and proposal.get('url') == job['publication'].get('url')
                    and proposal.get('replyText') == proposal.get('url'), 'approved public reply URL required')
            rb = evidence.get('readback') or {}
            require(evidence.get('verified') is True and evidence.get('fingerprint') == revision
                    and evidence.get('accountId') == proposal['targetAccountId']
                    and isinstance(rb, dict),
                    'bound verified X readback required')
            main, reply, media = rb.get('main'), rb.get('reply'), rb.get('media')
            require(isinstance(main, dict) and isinstance(reply, dict) and isinstance(media, dict)
                    and media.get('verified') is True and isinstance(media.get('items'), list),
                    'main reply media readback required')
            for post, key in ((main, 'mainId'), (reply, 'replyId')):
                require(isinstance(post.get('id'), str) and re.fullmatch(r'[1-9][0-9]{0,19}', post['id'])
                        and post.get('verified') is True and post.get('authorId') == proposal['targetAccountId']
                        and post['id'] == evidence.get(key), 'X post identity required')
            require(main['id'] != reply['id'] and exact_x_text(main, proposal.get('text'))
                    and exact_x_text(reply, proposal.get('replyText')) and reply.get('replyTo') == main['id']
                    and main.get('replyTo') is None,
                    'approved X text reply binding mismatch')
            images = proposal.get('images')
            require(isinstance(images, list) and 1 <= len(images) <= 4 and len(images) == len(media['items']),
                    'approved X media count mismatch')
            media_ids, media_keys = [], []
            for image, actual in zip(images, media['items']):
                require(isinstance(image, dict) and image.get('verified') is True
                        and re.fullmatch(r'[a-f0-9]{64}', image.get('sha256', ''))
                        and isinstance(actual, dict) and isinstance(actual.get('mediaKey'), str) and actual['mediaKey']
                        and actual.get('sha256') == image['sha256']
                        and isinstance(actual.get('mediaId'), str) and re.fullmatch(r'[1-9][0-9]{0,19}', actual['mediaId']),
                        'approved X media identity mismatch')
                media_ids.append(actual['mediaId'])
                media_keys.append(actual['mediaKey'])
            require(len(set(media_ids)) == len(media_ids) and len(set(media_keys)) == len(media_keys)
                    and main.get('mediaKeys') == media_keys and reply.get('mediaKeys') == [],
                    'X attachment order mismatch')
            if social.get('publication'):
                prior = {k: v for k, v in social['publication'].items() if k not in ('at', 'mainUrl', 'replyUrl')}
                require(prior == evidence, 'social publication conflict')
                return job
            require(job['stage'] == 'social_approved', 'social not awaiting publication')
            social['publication'] = dict(json.loads(canonical(evidence)), at=timestamp().isoformat(),
                                         mainUrl='https://x.com/i/web/status/' + main['id'],
                                         replyUrl='https://x.com/i/web/status/' + reply['id'])
            job['stage'] = 'social_posted'
            self._invalidate(db, id, 'social')
            return self._put(db, job, 'social_publication')
