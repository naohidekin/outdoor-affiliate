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

JST = timezone(timedelta(hours=9))
SCOPE = ('team_id', 'app_id', 'user_id', 'channel_id', 'thread_ts')
FLAGS = ('facts', 'images', 'affiliate', 'medical', 'render')


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


def valid_review(review, revision):
    score = review.get('score') if isinstance(review, dict) else None
    require(isinstance(score, (int, float)) and not isinstance(score, bool)
            and math.isfinite(score) and score >= 7.5 and review.get('passed') is True, 'review failed')
    require(isinstance(review.get('evidence'), dict)
            and all(review['evidence'].get(flag) is True for flag in FLAGS), 'evidence flags required')
    polish = review.get('polish', {})
    require(isinstance(polish, dict) and polish.get('model') == 'gemini-3.8-flash'
            and polish.get('validated') is True, 'validated Gemini polish required')
    require(review.get('fingerprint') == revision, 'review fingerprint mismatch')


class Ledger:
    def __init__(self, root, owner_id):
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

    def _event(self, db, id, kind, data, now=None):
        db.execute('INSERT INTO events(at,job_id,kind,data) VALUES (?,?,?,?)',
                   (timestamp(now).isoformat(), id, kind, canonical(data)))

    def _put(self, db, job, kind):
        if not job['publication'] and job['stage'] != 'rejected':
            others = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs WHERE id!=?', (job['id'],))]
            require(sum(not other['publication'] and other['stage'] != 'rejected' for other in others) < 3, 'pending cap reached')
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

    def create_candidate(self, theme, now=None):
        now = timestamp(now)
        slug = theme.get('slug') if isinstance(theme, dict) else theme
        require(isinstance(slug, str) and bool(slug.strip()), 'theme slug required')
        week = (now.date() - timedelta(days=now.weekday())).isoformat()
        with self._tx() as db:
            jobs = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs')]
            for job in jobs:
                old_slug = job['theme'].get('slug') if isinstance(job['theme'], dict) else job['theme']
                if old_slug == slug:
                    return job
            require(sum(job['week'] == week for job in jobs) < 3, 'weekly candidate cap reached')
            require(sum(not job['publication'] and job['stage'] != 'rejected' for job in jobs) < 3, 'pending cap reached')
            job = dict(id='article-' + secrets.token_hex(12), theme=theme, week=week, stage='candidate',
                       bundle=None, revision=None, review=None, approval=None, publication=None, social=None, error=None,
                       created_at=now.isoformat())
            return self._put(db, job, 'candidate')

    def list_jobs(self):
        with self._tx() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs ORDER BY rowid')]

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
            require(expected_revision is None or job['revision'] == expected_revision, 'revision conflict')
            if revision != job['revision']:
                job.update(bundle=json.loads(canonical(bundle)), revision=revision, review=None, approval=None,
                           publication=None, social=None, error=None, stage='draft')
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
            valid_review(review, revision)
            job.update(review=json.loads(canonical(review)), approval=None, stage='review')
            self._invalidate(db, id, 'article')
            return self._put(db, job, 'review')

    def create_request(self, id, kind='article', now=None):
        now = timestamp(now)
        require(kind in ('article', 'social'), 'unknown request kind')
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            if kind == 'article':
                revision = job['revision']
                valid_review(job['review'], revision)
            else:
                require(job['publication'] and job['publication'].get('verified') is True and job['social'], 'verified publication and social required')
                revision = fingerprint(job['social']['proposal'])
                require(revision == job['social']['revision'], 'social changed')
                valid_review(job['social']['review'], revision)
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
            valid_review(target['review'], target['revision'])
            stage = stages[event['action_id']]
            target['approval'] = dict(request_id=req['request_id'], revision=req['manifest_hash'], user_id=self.owner_id,
                                      action=stage, at=now.isoformat()) if stage == 'approved' else None
            job['stage'] = ('social_' if req['kind'] == 'social' else '') + stage
            req['status'] = 'decided'
            db.execute('UPDATE requests SET data=? WHERE id=?', (canonical(req), req['request_id']))
            result = self._put(db, job, 'decision')
            db.execute('INSERT INTO decisions VALUES (?,?)', (event['event_id'], canonical(dict(event=event, result=result))))
            return result

    def approve_from_codex(self, id, revision, actor, evidence):
        """Trusted local operator API; explicit Runtime CLI command only, never tick.

        Actor strings/evidence are not authentication. The invoking operator/tool
        must verify the owner's actual message and allowed user approval scope.
        Codex models cannot self-approve or fabricate evidence. This records article
        authority only; publication and social retain their separate gates.
        Text must be exactly '記事 <id> 版 <revision> を公開してください' or
        'publish <id> <revision>' (optional final punctuation).
        """
        require(actor == self.owner_id, 'owner mismatch')
        require(isinstance(evidence, dict) and evidence.get('source') == 'codex', 'Codex evidence required')
        require(all(isinstance(evidence.get(k), str) and evidence[k].strip()
                    for k in ('thread_id', 'message_id', 'text')), 'message evidence required')
        require(isinstance(id, str) and isinstance(revision, str), 'article and revision required')
        directive = (rf'(?:記事\s+{re.escape(id)}\s+版\s+{re.escape(revision)}\s+を公開してください[。.]?'
                     rf'|publish\s+{re.escape(id)}\s+{re.escape(revision)}[.]?)')
        require(re.fullmatch(directive, evidence['text'].strip()) is not None, 'explicit article/version publication instruction required')
        # Snapshot caller-owned JSON before the transactional approval record.
        evidence = json.loads(canonical(evidence))
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            require(revision == job['revision'], 'revision mismatch')
            valid_review(job['review'], revision)
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
            job.update(publication=dict(evidence, revision=revision, at=timestamp().isoformat()), stage='published')
            return self._put(db, job, 'publication')

    def record_social(self, id, proposal, review):
        revision = fingerprint(proposal)
        valid_review(review, revision)
        with self._tx() as db:
            job = self._get(db, id)
            self._current(job)
            require(job['publication'] and job['publication'].get('verified') is True, 'verified publication required')
            if job['social'] and job['social']['revision'] == revision:
                return job
            self._invalidate(db, id, 'social')
            job.update(social=dict(proposal=proposal, revision=revision, review=review, approval=None), stage='social_review')
            return self._put(db, job, 'social')
