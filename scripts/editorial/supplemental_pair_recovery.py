"""Fixed Nov 20 owner grant: Zeoline and Chameece, normal pipeline, no publishing.

prepare reads only; execute consumes one durable claim per article. Historical
research and journals are evidence, never relabelled as freshly verified sources.
"""
import copy
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3

from ledger import JST, fingerprint
from model_budget import _config as budget_config
from models import Models
from runtime import Runtime, atomic, reason, stamp
from stage_journal import _usage_copy
from supplemental_review_recovery import _read, _require, _fresh, _cached, _VerifiedCatalog
from supplemental_topics import load_batch, resolve_batch

BATCH = 'apparel-2026-11-16'
CONFIG_SHA = 'de79f4c1537eb192df094f18d8deb7d6f8e6cf75877e4776e949456153107cbe'
OWNER_DATE = '2026-11-20'
AUTHORIZATION = 'owner-20261120-zeoline-chameece-repair'
OWNER_ANSWER = 'ジオラインとシャミースの追加修正・再審査を許可します。品質基準と予算上限は維持してSlack承認待ちまで進めてください。11月20日の通常制作への影響も確認し、公開・SNS予約はそれぞれ私の承認後にお願いします。'
JOBS = {
    'article-569175cfacbb87d25de6d09c': {
        'slot': 2, 'product': 'apparel-montbell-1107704', 'slug': 'zeoline-mw-1107704-guide',
        'final': 'stage_journal:v1:f5aef98fe14b54dda1dd005e70e3915ce0c52937ad070bea02fcd55027dbc674',
        'directory': '9b2c2d6457e32f85d4631772e3a26bab8de8e0382d632b1862014e12b8fb7d2a',
        'source': 'a9cc83c7f3f394a4a9936133eb35c255cd642967c26e23dddfc41ed9559e60a6',
        'candidate': '0bbb52706f59bebb4b21a926c09835fc1edc56b5cd64918d324085b1de0bc035'},
    'article-0f8f00185abe2a5ec39cdbea': {
        'slot': 3, 'product': 'apparel-montbell-1114881', 'slug': 'chameece-1114881-layering-guide',
        'final': 'stage_journal:v1:bcd9d8614f3f961b64c95defa85cd20da4807732d11092282abb24edda01799c',
        'directory': 'a637eb511239ffb9e38e1aeee25bc320ed3a6da1ed605fc41eea93c669eeb702',
        'source': '559a95070e7a211c05b5926fa4eeeb21452c2ab57bee670d4f6e1c003c754b58',
        'candidate': 'de66d0d115de8c0b3abb943c948bc590d657b4d4c0022eb1a6f38a9c2e3efa01'},
}
PROTOCOL_FILES = ('supplemental_pair_recovery.py', 'supplemental_review_recovery.py',
                  'runtime.py', 'models.py', 'quality.py', 'model_budget.py')
LOADED_FILES = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                for n in PROTOCOL_FILES}


def _protocol():
    files = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
             for n in PROTOCOL_FILES}
    _require(files == LOADED_FILES, 'loaded_protocol_changed_restart_required')
    return files


def receipt_key(job_id):
    _require(job_id in JOBS, 'fixed_pair_job_required')
    return 'supplemental_manual_recovery:v1:' + AUTHORIZATION + ':' + job_id


def _slot(job, snapshot, batch, jobs, now):
    result = resolve_batch(batch, snapshot,
        [j['theme'] for j in jobs if j.get('kind') != 'supplemental_article'], now)
    slot = next((s for s in result['slots'] if s['slot'] == JOBS[job['id']]['slot']), {})
    _require(slot.get('status') == 'ready' and slot.get('theme') == job['theme']
             and slot.get('sourceBinding') == job['sourceBinding'], 'current_source_binding_or_theme_changed')


def prepare(config_path, job_id, old_failed_key, proposed_path, proof_path, snapshot_path,
            fresh_research_path, *, now=None):
    """Read-only manifest; fresh evidence is separate from immutable old research."""
    now = now or datetime.now(JST)
    _require(now.utcoffset() is not None and now.astimezone(JST).date().isoformat() == OWNER_DATE,
             'owner_grant_date_required')
    _require(job_id in JOBS, 'fixed_pair_job_required')
    pins = JOBS[job_id]
    _require(old_failed_key == pins['final'], 'exact_failed_review_required')
    config, digest = _read(config_path)
    _require(digest == CONFIG_SHA, 'exact_config_required')
    root = Path(config['stateRoot'])
    database = root / 'ledger.sqlite3'
    _require(root.is_absolute() and root.resolve() not in (Path('/'), Path.home())
             and database.is_file() and not any(p.is_symlink() for p in (database, *database.parents)),
             'unsafe_ledger')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        jobs = [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs')]
        records = {k: json.loads(v) for k, v in db.execute(
            "SELECT key,value FROM meta WHERE key LIKE 'stage_journal:v1:%'")}
    job = next((j for j in jobs if j['id'] == job_id), {})
    _require(job.get('kind') == 'supplemental_article' and job.get('batchId') == BATCH
             and job.get('batchSlot') == pins['slot'] and job.get('batchCallCap') == 96
             and job.get('week') == '2026-11-13' and job.get('stage') == 'error'
             and job.get('theme', {}).get('productIds') == [pins['product']]
             and job['theme'].get('slug') == pins['slug'] and job['theme'].get('categoryId') == 'wear'
             and all(job.get(k) is None for k in ('bundle', 'review', 'approval', 'publication'))
             and (job.get('error') or {}).get('reason') == 'final_review_failed', 'exact_failed_pair_job_required')
    final = records.get(old_failed_key, {})
    _require(final.get('stageKey') == old_failed_key and final.get('jobId') == job_id
             and final.get('stage') == 'final_review' and final.get('status') == 'failed'
             and final.get('attempts') == 1 and final.get('maxAttempts') == 2
             and not final.get('successorKey'), 'exact_failed_review_required')
    old = {}
    for stage in ('draft', 'polish'):
        found = [r for r in records.values() if r.get('jobId') == job_id
                 and r.get('stage') == stage and r.get('status') == 'succeeded']
        _require(len(found) == 1, 'unique_successful_writer_polish_required')
        old[stage] = found[0]
    draft, polish = (_cached(old[s]) for s in ('draft', 'polish'))
    artifact = root / 'research' / 'artifacts' / job_id / pins['directory']
    source, source_sha = _read(artifact / 'source.json')
    candidate, candidate_sha = _read(artifact / 'candidate.json')
    historical, historical_sha = _read(root / 'research' / (job_id + '.json'))
    _require(source_sha == pins['source'] and candidate_sha == pins['candidate']
             and source.get('kind') == 'source' and artifact.name == fingerprint(source['bundle'])
             and source['bundle']['article']['content'] == draft['article']['content']
             and candidate.get('kind') == 'candidate' and candidate.get('candidate') == polish.get('polished')
             and polish['polished'].get('model') == 'gemini-3.8-flash'
             and polish.get('preservation', {}).get('passed') is True, 'pinned_historical_artifacts_required')
    proposed, proposed_sha = _read(proposed_path)
    proof, proof_sha = _read(proof_path)
    _require(proposed.get('kind') == 'correction-plan'
             and isinstance(proposed.get('approvedWritingBrief'), dict) and proposed['approvedWritingBrief'],
             'approved_writing_brief_required')
    _require(proof.get('jobId') == job_id and proof.get('sourceBinding') == job['sourceBinding']
             and proof.get('proposedCandidateSha256') == proposed_sha
             and isinstance(proof.get('corrections'), list) and proof['corrections']
             and all(isinstance(c, dict) and c for c in proof['corrections']), 'proposal_proof_binding')
    snapshot, snapshot_sha = _read(snapshot_path)
    fresh, fresh_sha = _read(fresh_research_path)
    batch = load_batch(config.get('supplementalApparelBatchManifest'))
    _slot(job, snapshot, batch, jobs, now)
    products = [p for p in snapshot.get('products', []) if p.get('id') == pins['product']]
    _require(len(products) == 1 and products == fresh.get('products') == fresh.get('catalog')
             == historical.get('products') == source['bundle'].get('products'), 'canonical_products_changed')
    evidence = (fresh.get('evidence') or {}).get('products') or []
    _require(_fresh(snapshot.get('checkedAt'), now) and fresh.get('productIds') == [pins['product']]
             and [p.get('productId') for p in evidence] == [pins['product']]
             and all(_fresh(p.get('checkedAt'), now) for p in evidence)
             and all(fresh.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate')),
             'fresh_independent_source_checks_required')
    limits = budget_config(config.get('modelBudget'))
    _require(limits['article']['calls'] <= 32 and limits['period']['calls'] <= 128,
             'unchanged_budget_bounds_required')
    return {'schemaVersion': 1, 'status': 'held_for_owner_decision', 'executed': False,
        'jobId': job_id, 'oldFailedKey': old_failed_key, 'originalError': job['error'],
        'jobSha256': fingerprint(job), 'sourceBinding': job['sourceBinding'],
        'paths': {k: str(v) for k, v in dict(config=config_path, proposed=proposed_path,
            proof=proof_path, snapshot=snapshot_path, freshResearch=fresh_research_path).items()},
        'sha256': dict(config=digest, sourceArtifact=source_sha, candidateArtifact=candidate_sha,
            gathered=historical_sha, proposedCandidate=proposed_sha, sourceProof=proof_sha,
            currentSourceSnapshot=snapshot_sha, freshResearch=fresh_sha,
            batchManifest=fingerprint(batch), newProtocol=fingerprint(_protocol())),
        'oldStages': {s: fingerprint(r) for s, r in dict(old, final_review=final).items()},
        'caps': limits, 'batchCalls': 96, 'blockers': []}


class _PairRuntime(Runtime):
    def __init__(self, rt, manifest, original):
        self.__dict__ = rt.__dict__.copy()
        self._manifest = copy.deepcopy(manifest)
        self._job_id = manifest['jobId']
        self._original = original
        self.models = copy.copy(rt.models)
        self.models.usage = []
        self._usage_response_ids, self._saved_usage_response_ids = set(), set()
        self._explicit_stage_retry = None
        self._executed_stages = set()
        self._publisher = rt.publisher
        self.publisher = self._stage_only
        snapshot, _ = _read(manifest['paths']['snapshot'])
        products = [p for p in snapshot['products'] if p['id'] == JOBS[self._job_id]['product']]
        self.catalog = _VerifiedCatalog(rt.catalog, rt.ledger.get_job(self._job_id), products)

    def _require_running(self):
        Runtime._require_running(self)
        config, digest = _read(self._manifest['paths']['config'])
        _require(digest == CONFIG_SHA and config == self.config
                 and fingerprint(_protocol()) == self._manifest['sha256']['newProtocol'],
                 'owner_pair_config_or_protocol_changed')

    def _run_model_stage(self, job, stage, inputs, operation, requested_model, **kwargs):
        self._require_running()
        order = ('draft', 'polish', 'final_review')
        _require(job['id'] == self._job_id and stage in order
                 and self._executed_stages == set(order[:order.index(stage)])
                 and not kwargs, 'owner_pair_stage_forbidden')
        if stage == 'final_review':
            _require(all(inputs['dependencies']['qualityFlags'].values())
                     and inputs['dependencies']['structural'].get('passed') is True,
                     'independent_quality_gates_failed')
        self._executed_stages.add(stage)
        namespace = 'owner_oneoff:' + AUTHORIZATION + ':' + stage
        bound = dict(inputs, ownerGrantManifestSha256=fingerprint(self._manifest))
        key = self.stage_journal.key(self._job_id, namespace, bound)
        start = len(self.models.usage)
        called = False
        def measured():
            nonlocal called
            called = True
            with self.model_budget.scope(self._job_id, stage):
                result = operation()
            if stage == 'draft':
                _require(result['brief']['format'] == 'guide'
                         and all(result['article'].get(k) == job['theme'][k]
                                 for k in ('productIds', 'slug', 'categoryId'))
                         and result['article']['content'] != self._original['content'],
                         'corrected_article_identity_or_body_required')
            usage = self.models.usage[start:]
            _require(usage and all(r.get('responseId') and r.get('usage')
                     and isinstance(r.get('model'), str)
                     and r['model'].startswith('gemini-' if stage == 'polish' else 'claude-')
                     for r in usage), 'real_model_usage_receipt_required')
            return result
        try:
            return self.stage_journal.run(self._job_id, namespace, bound, measured, max_attempts=1)
        finally:
            if called:
                usage = self._usage_slice(start, article_id=self._job_id, stage=namespace,
                    reason='initial', requested_model=requested_model)
                self.stage_journal.record_usage(self._job_id, namespace, key, _usage_copy(usage))

    def _stage_only(self, action, job):
        self._require_running()
        _require(action == 'stage' and job['id'] == self._job_id and job['stage'] == 'review'
                 and job.get('approval') is None and job.get('publication') is None,
                 'owner_pair_publish_forbidden')
        return self._publisher(action, job)

    def deliver(self, id, kind='article'):
        _require(id == self._job_id and kind == 'article', 'owner_pair_delivery_forbidden')
        return Runtime.deliver(self, id, kind)

    def _forbidden(self, *args, **kwargs):
        raise ValueError('owner_pair_entrypoint_forbidden')

    tick = consume = produce = produce_supplemental = retry = retry_stage = _forbidden
    retry_corrected_stage = publish_social = publish_buffer_social = make_social = _publish = _forbidden
    request_revisions = approve_from_codex = enable_social_autopost = _forbidden
    prepare_social_handoff = refresh_social_images = _forbidden


def _receipt(rt, job_id, **fields):
    with rt.ledger._tx() as db:
        key = receipt_key(job_id)
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        _require(row is not None, 'owner_pair_claim_missing')
        value = json.loads(row[0])
        value.update(fields)
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(value), key))
        rt.ledger._event(db, job_id, 'supplemental_owner_pair_result', fields)


def execute(runtime, manifest, *, owner_grant):
    job_id = manifest.get('jobId')
    _require(job_id in JOBS and owner_grant == {'reference': AUTHORIZATION, 'answer': OWNER_ANSWER,
             'jobId': job_id, 'manifestSha256': fingerprint(manifest)}, 'exact_owner_grant_required')
    runtime._require_running()
    config, digest = _read(manifest['paths']['config'])
    _require(digest == CONFIG_SHA and config == runtime.config
             and Path(config['stateRoot']).resolve() == runtime.root.resolve(), 'runtime_config_binding')
    with (runtime.root / 'runtime.flock').open('a') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy', 'executed': False}
        # Check claim before prepare: a completed run has legitimately changed the job.
        with runtime.ledger._tx() as db:
            _require(db.execute('SELECT 1 FROM meta WHERE key=?', (receipt_key(job_id),)).fetchone() is None,
                     'owner_pair_already_claimed_requires_reconciliation')
        p = manifest['paths']
        current = prepare(p['config'], job_id, manifest['oldFailedKey'], p['proposed'], p['proof'],
                          p['snapshot'], p['freshResearch'])
        _require(current == manifest and not current['blockers'], 'pinned_manifest_changed_or_blocked')
        _require(runtime.model_budget.config == budget_config(config.get('modelBudget'))
                 and isinstance(runtime.models, Models) and runtime.models.budget is runtime.model_budget,
                 'real_unchanged_budgeted_models_required')
        routes = runtime._model_routes()
        _require(routes['draft']['requested'].startswith('claude-')
                 and routes['final_review']['requested'] == 'claude-sonnet-4-6'
                 and routes['polish']['requested'] == 'gemini-3.8-flash', 'authorized_model_routes_required')
        with runtime.ledger._tx() as db:
            _require(db.execute('SELECT 1 FROM meta WHERE key=?', (receipt_key(job_id),)).fetchone() is None,
                     'owner_pair_already_claimed_requires_reconciliation')
            receipt = {'status': 'in_flight', 'jobId': job_id, 'attempts': 1, 'maxAttempts': 1,
                       'manifestSha256': fingerprint(manifest), 'ownerGrant': owner_grant, 'at': stamp()}
            db.execute('INSERT INTO meta VALUES (?,?)', (receipt_key(job_id), json.dumps(receipt)))
            runtime.ledger._event(db, job_id, 'supplemental_owner_pair_claimed', receipt)
        view = None
        try:
            archive = runtime.root / 'manual-operations' / '20261120-pair-recovery' / job_id
            _require(not archive.exists(), 'recovery_archive_already_exists')
            historical, _ = _read(runtime.root / 'research' / (job_id + '.json'))
            atomic(archive / 'original-research.json', historical)
            atomic(archive / 'manifest.json', manifest)
            artifact = runtime.root / 'research' / 'artifacts' / job_id / JOBS[job_id]['directory']
            candidate, _ = _read(artifact / 'candidate.json')
            source, _ = _read(artifact / 'source.json')
            view = _PairRuntime(runtime, manifest, candidate['candidate'])
            context = view._context()
            job = view.ledger.get_job(job_id)
            _slot(job, context, view._supplemental_manifest(), view.ledger.list_jobs(), datetime.now(JST))
            proposed, _ = _read(p['proposed'])
            context['editorialRules'] += ('\nOwner-approved body correction. Legacy claims are unverified; '
                'use ONLY freshly gathered primary evidence, remove unsupported inferences everywhere. '
                'Preserve guide format, products, slug and category. Legacy article:\n'
                + json.dumps(source['bundle']['article'], ensure_ascii=False)
                + '\nMain upper-editor approvedWritingBrief (not a new factual source):\n'
                + json.dumps(proposed['approvedWritingBrief'], ensure_ascii=False))
            result = view._make_article(job, context)
            _require(view._executed_stages == {'draft', 'polish', 'final_review'}, 'incomplete_owner_pipeline')
            _receipt(runtime, job_id, status='completed', result=result)
            return result
        except BaseException as error:
            _receipt(runtime, job_id, status='requires_reconciliation', failureType=type(error).__name__)
            if isinstance(error, Exception):
                job = runtime.ledger.get_job(job_id)
                if job.get('approval') is None and job.get('publication') is None:
                    runtime.ledger.set_stage(job_id, 'error', {'reason': reason(error), 'at': stamp(),
                        'originalFailure': copy.deepcopy(manifest['originalError']),
                        'ownerRecoveryReceipt': receipt_key(job_id)})
            raise
        finally:
            if view is not None:
                view._save_usage()
