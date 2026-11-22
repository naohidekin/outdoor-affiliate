"""Exact winter-depth slot replacement, preserving every historical job/usage row."""
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import quote

from ledger import canonical, fingerprint
from supplemental_topics import load_batch, resolve_batch, validate_batch

JST = timezone(timedelta(hours=9))
BATCH = 'winter-depth-2026-11-22'
SKIN = 'article-b1059cbd51d84cee93adbdc6'
KEY = 'supplemental_reselection:v1:' + BATCH
HOLD = Path('research/winter-depth-20261123-reselection/owner-skin-hold.json')


def require(ok, reason):
    if not ok:
        raise ValueError('supplemental_reselection_' + reason)


def read(path):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and not path.is_symlink(), 'file')
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def assert_not_held(root, db, id):
    """Read-only guard: deployment honors Main's existing hold even before apply."""
    if id == SKIN:
        path = Path(root) / HOLD
        require(not path.exists() and not path.is_symlink()
                and db.execute('SELECT 1 FROM meta WHERE key=?', (KEY,)).fetchone() is None,
                'owner_hold')


def receipt(db):
    row = db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
    if row is None:
        return None
    value = json.loads(row[0])
    require(isinstance(value, dict) and value.get('status') == 'applied'
            and fingerprint(value.get('plan')) == value.get('planSha256'), 'receipt')
    plan = value['plan']
    require(plan.get('batchId') == BATCH and plan.get('oldJobId') == SKIN and plan.get('slot') == 2
            and plan.get('budgetArticleId') == SKIN, 'receipt_scope')
    for manifest in (plan['oldManifest'], plan['newManifest']):
        validate_batch(manifest)
    require(all(plan['oldManifest'][k] == plan['newManifest'][k] for k in
                ('batchId', 'notBefore', 'maxArticles', 'batchCallCap', 'socialEligiblePeriod'))
            and plan['newManifest']['batchId'] == BATCH, 'receipt_bounds')
    return value


def active_jobs(db, jobs, batch_id):
    selected = [j for j in jobs if j.get('kind') == 'supplemental_article' and j.get('batchId') == batch_id]
    value = receipt(db) if batch_id == BATCH else None
    if value is not None:
        plan = value['plan']
        old = next((j for j in selected if j['id'] == SKIN), None)
        new = next((j for j in selected if j['id'] == value['newJobId']), None)
        require(old is not None and fingerprint(old) == plan['oldJobSha256']
                and old['stage'] == 'rejected' and old.get('approval') is None
                and old.get('publication') is None, 'old_history_changed')
        require(new is not None and new['id'] != SKIN and new.get('batchSlot') == 2
                and new.get('budgetArticleId') == SKIN and new.get('replacesJobId') == SKIN
                and new.get('sourceBinding') == plan['replacement']['sourceBinding']
                and new.get('theme') == plan['replacement']['theme']
                and new.get('batchCallCap') == 96 and new.get('week') == plan['periodKey'], 'replacement_binding')
        selected = [j for j in selected if j['id'] != SKIN]
    require(len(selected) <= 3 and len({j.get('batchSlot') for j in selected}) == len(selected)
            and all(j.get('batchSlot') in (1, 2, 3) for j in selected), 'current_slots')
    return selected


def effective_manifest(ledger, configured):
    with sqlite3.connect(ledger.db_path) as db:
        value = receipt(db) if configured['batchId'] == BATCH else None
        if value is None:
            return configured
        active_jobs(db, ledger.list_jobs(), BATCH)
        require(configured == value['plan']['oldManifest'], 'configured_manifest_changed')
        return copy.deepcopy(value['plan']['newManifest'])


def budget_article_id(ledger, job):
    if 'budgetArticleId' not in job and 'replacesJobId' not in job:
        return job['id']
    with sqlite3.connect(ledger.db_path) as db:
        value = receipt(db)
        require(value is not None and value['newJobId'] == job['id'], 'budget_alias')
        active_jobs(db, ledger.list_jobs(), BATCH)
    return SKIN


def report_aliases(root, article_ids):
    """Read-only aliases; actual call attribution is deliberately not rewritten."""
    path = Path(root) / 'ledger.sqlite3'
    if not path.is_file():
        return {}, None
    with sqlite3.connect('file:' + quote(str(path), safe='/') + '?mode=ro', uri=True) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone() is None:
            return {}, None
        value = receipt(db)
        if value is None:
            return {}, None
        jobs = [json.loads(v) for v, in db.execute('SELECT data FROM jobs')]
        active_jobs(db, jobs, BATCH)
        new_id = value['newJobId']
        aliases = {new_id: SKIN} if article_ids is None or new_id in article_ids else {}
        members = {j['id'] for j in jobs if j.get('kind') == 'supplemental_article' and j.get('batchId') == BATCH}
        budget_ids = sorted(members) if article_ids is not None and set(article_ids) & members else None
        return aliases, budget_ids


def corrected_link_retry_receipt(db, jobs, job):
    if (job.get('kind') != 'supplemental_article' or job.get('batchId') != BATCH
            or (job.get('error') or {}).get('reason') != 'Unknown or self internal article link'):
        return None
    value = receipt(db)
    if value is None or value['newJobId'] != job['id']:
        return None
    active_jobs(db, jobs, BATCH)
    records = [json.loads(raw) for raw, in db.execute("SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
    require(not any(r.get('jobId') == job['id'] and r.get('stage') != 'draft' for r in records), 'retry_stage_scope')
    require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status!='failed'", (job['id'],)).fetchone()
            and not db.execute('SELECT 1 FROM requests WHERE job_id=?', (job['id'],)).fetchone()
            and not db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id=? "
                               "AND status IN ('reserved','in_flight','unknown')", (SKIN,)).fetchone(), 'retry_unresolved')
    targets = {s['slug'] for s in value['plan']['newManifest']['slots']}
    managers = [json.loads(raw) for raw, in db.execute("SELECT value FROM meta WHERE key LIKE 'editorial_manager:%'")]
    require(not any(_manager_blocks(db, r, targets) for r in managers), 'manager')
    return value


def _manager_blocks(db, record, target_slugs):
    if not isinstance(record, dict) or not isinstance(record.get('status'), str):
        return True
    if record['status'] in ('evaluating', 'executing'):
        return True
    if record['status'] in ('completed', 'blocked', 'stale', 'input_limit',
                            'budget_exhausted', 'provider_failed', 'invalid_decision'):
        return False
    if record['status'] != 'requires_reconciliation':
        return True
    action = record.get('action')
    if not isinstance(action, dict):
        return True
    ids = [action[k] for k in ('job_id', 'jobId') if k in action]
    if not ids or any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != 1:
        return True
    if ids[0] in {SKIN, BATCH, *target_slugs}:
        return True
    row = db.execute('SELECT data FROM jobs WHERE id=?', (ids[0],)).fetchone()
    if row is None:
        return True
    job = json.loads(row[0])
    if job.get('batchId') == BATCH:
        return True
    if job.get('kind') == 'article_revision':
        from revisions import validate_context
        try:
            slug = validate_context(job.get('revisionContext'))['baseArticle']['slug']
        except (ValueError, TypeError, KeyError):
            return True
    else:
        slug = (job.get('theme') or {}).get('slug')
    return not isinstance(slug, str) or not slug.strip() or slug in target_slugs


def _snapshots(db, id, new_manifest):
    requests = db.execute('SELECT id,kind,data FROM requests WHERE job_id=? ORDER BY id', (id,)).fetchall()
    require(requests and all(json.loads(row[2]).get('status') == 'decided' for row in requests), 'decisions')
    require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status!='failed'", (id,)).fetchone(), 'effects')
    journals = [json.loads(v) for v, in db.execute("SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
    require(not any(r.get('jobId') == id and r.get('status') in ('in_flight', 'unknown') for r in journals), 'stages')
    usage = db.execute('SELECT * FROM model_budget_reservations WHERE article_id=? ORDER BY reservation_id', (id,)).fetchall()
    require(not any(row for row in db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id=? "
                                             "AND status IN ('reserved','in_flight','unknown')", (id,))), 'usage')
    managers = [json.loads(v) for v, in db.execute("SELECT value FROM meta WHERE key LIKE 'editorial_manager:%'")]
    old = json.loads(db.execute('SELECT data FROM jobs WHERE id=?', (id,)).fetchone()[0])
    target_slugs = {old['theme']['slug'], *(s['slug'] for s in new_manifest['slots'])}
    require(not any(_manager_blocks(db, v, target_slugs) for v in managers), 'manager')
    return fingerprint(requests), fingerprint(usage)


def prepare(runtime, new_manifest_path, actor, evidence):
    """Read-only plan; operator verifies the real owner's instruction externally."""
    require(actor == runtime.ledger.owner_id and isinstance(evidence, dict)
            and evidence.get('source') == 'codex'
            and all(isinstance(evidence.get(k), str) and evidence[k].strip()
                    for k in ('thread_id', 'message_id', 'text')), 'owner_instruction')
    old_path = Path(runtime.config['supplementalApparelBatchManifest'])
    old, old_sha = read(old_path)
    new, new_sha = read(new_manifest_path)
    validate_batch(old); validate_batch(new)
    require(old['batchId'] == BATCH and all(old[k] == new[k] for k in
            ('batchId', 'notBefore', 'maxArticles', 'batchCallCap', 'socialEligiblePeriod')), 'bounds')
    hold, hold_sha = read(runtime.root / HOLD)
    jobs = runtime.ledger.list_jobs()
    job = runtime.ledger.get_job(SKIN)
    require(job.get('kind') == 'supplemental_article' and job.get('batchId') == BATCH
            and job.get('batchSlot') == 2 and job.get('batchCallCap') == 96
            and job.get('stage') == 'rejected' and job.get('approval') is None
            and job.get('publication') is None and job.get('social') is None, 'old_state')
    require(hold.get('kind') == 'owner_requested_hold_and_reselection' and hold.get('articleId') == SKIN
            and hold.get('revision') == job.get('revision') and hold.get('observedStage') == 'rejected'
            and hold.get('ownerPublicationApproval') is False and hold.get('ownerSNSApproval') is False
            and isinstance(hold.get('ownerInstruction'), str) and bool(hold['ownerInstruction'].strip()), 'hold_binding')
    require([j['id'] for j in jobs if j.get('kind') == 'supplemental_article' and j.get('batchId') == BATCH] == [SKIN],
            'only_uncreated_other_slots')
    with sqlite3.connect(runtime.ledger.db_path) as db:
        require(receipt(db) is None, 'already_applied')
        request_sha, usage_sha = _snapshots(db, SKIN, new)
    now = datetime.now(JST)
    period = runtime.ledger.production_schedule.period_key(now)
    require(period == job['week'], 'period_changed')
    context = runtime._context()
    resolved = resolve_batch(new, context, [j['theme'] for j in jobs
        if not (j.get('kind') == 'supplemental_article' and j.get('batchId') == BATCH)], now)
    require(all(all(isinstance(slot.get(k), str) and slot[k].strip()
                    for k in ('slug', 'title', 'categoryId', 'query', 'selectionReason')) for slot in new['slots'])
            and len(resolved.get('slots', [])) == 3 and resolved['slots'][1]['status'] == 'ready'
            and all(s.get('reason') in (None, 'catalog_product_not_verified',
                    'missing_required_destination', 'apparel_identity_invalid') for s in resolved['slots'])
            and new['slots'][1]['slug'] != job['theme']['slug'], 'three_chosen_replacement_ready')
    return dict(schemaVersion=1, batchId=BATCH, slot=2, oldJobId=SKIN, budgetArticleId=SKIN,
                oldJobSha256=fingerprint(job), requestsSha256=request_sha, usageSha256=usage_sha,
                holdSha256=hold_sha, ownerHold=hold, actor=actor, ownerInstruction=copy.deepcopy(evidence),
                oldManifestPath=str(old_path), oldManifestSha256=old_sha, oldManifest=old,
                newManifestPath=str(Path(new_manifest_path)), newManifestSha256=new_sha, newManifest=new,
                replacement=resolved['slots'][1], periodKey=period)


def apply(runtime, plan):
    """One exact operator apply, under the same runner lease; never model/publish."""
    runtime._require_running()
    require(runtime.config.get('supplementalApparelEnabled') is True, 'disabled')
    with (runtime.root / 'runtime.flock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(prepare(runtime, plan['newManifestPath'], plan['actor'], plan['ownerInstruction']) == plan, 'plan_changed')
        with runtime.ledger._tx() as db:
            require(receipt(db) is None, 'already_applied')
            require(read(runtime.root / HOLD)[1] == plan['holdSha256']
                    and read(plan['oldManifestPath'])[1] == plan['oldManifestSha256']
                    and read(plan['newManifestPath'])[1] == plan['newManifestSha256'], 'files_changed')
            old = runtime.ledger._get(db, SKIN)
            require(fingerprint(old) == plan['oldJobSha256'], 'old_changed')
            request_sha, usage_sha = _snapshots(db, SKIN, plan['newManifest'])
            require((request_sha, usage_sha) == (plan['requestsSha256'], plan['usageSha256']), 'history_changed')
            new_id = 'article-' + secrets.token_hex(12)
            job = dict(id=new_id, kind='supplemental_article', batchId=BATCH, batchSlot=2,
                       sourceBinding=plan['replacement']['sourceBinding'], batchCallCap=96,
                       budgetArticleId=SKIN, replacesJobId=SKIN,
                       socialEligiblePeriod=plan['newManifest']['socialEligiblePeriod'],
                       theme=copy.deepcopy(plan['replacement']['theme']), week=plan['periodKey'],
                       stage='candidate', bundle=None, revision=None, review=None, approval=None,
                       publication=None, social=None, error=None, created_at=datetime.now(JST).isoformat())
            job = runtime.ledger._put(db, job, 'supplemental_reselection_candidate')
            value = dict(status='applied', plan=copy.deepcopy(plan), planSha256=fingerprint(plan), newJobId=new_id)
            db.execute('INSERT INTO meta VALUES (?,?)', (KEY, canonical(value)))
            runtime.ledger._event(db, SKIN, 'owner_hold_and_slot_reselection', value)
            return value
