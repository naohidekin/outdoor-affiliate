"""One Nov 23 00:24 JST owner grant, exact skin job, paid insertions only.

Read-only diagnose/prepare, then explicit execute under runtime.flock. No writer
request, no resetting old stages, no public publication or social operation.
An unknown/failed attempt consumes this grant; a different plan cannot rearm it.
"""
import copy
from datetime import datetime
from difflib import SequenceMatcher
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3

from ledger import JST, fingerprint
from models import Models, ModelError, ARTICLE_FIELDS, ARTICLE_LENGTHS, _strict_json
from model_budget import _config as budget_config
from quality import _protected, inspect_polish
from runtime import Runtime, atomic, reason, stamp
from stage_journal import _usage_copy
from supplemental_review_recovery import _read, _require, _fresh, _VerifiedCatalog
from supplemental_topics import load_batch, resolve_batch

JOB_ID = 'article-b1059cbd51d84cee93adbdc6'
BATCH = 'winter-depth-2026-11-22'
OLD_KEY = 'stage_journal:v1:aa5d8885296281a0a41b548269e72fe7d44a44e47797cdd5c20bc505d80d6710'
ARTIFACT_NAMES = ('6836c7029ea13ae38d52a246935d7b0baaaf07a6237b43a9686945daa0aad8d2',
                  'b825b7e86729a91a96727775571bab10f415a46fe61113de08a4bbf646ae616b')
AUTHORIZATION = 'owner-20261123T0024JST-skin-insertion-recovery'
ACTION = 'skin_insertions_to_article_approval_once'  # Program enum, not an owner quote.
AUTHORIZATION_PATH = 'research/winter-depth-20261122/owner-limited-recovery-authorization-20261123.json'
RECEIPT = 'skin_insertion_recovery:v1:' + JOB_ID
FILES = ('skin_insertion_recovery.py', 'models.py', 'runtime.py', 'quality.py',
         'model_budget.py', 'supplemental_review_recovery.py', 'supplemental_topics.py',
         'catalog.py', 'apparel_identity.py')
LOADED = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in FILES}


def protocol():
    files = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in FILES}
    _require(files == LOADED, 'skin_protocol_changed_restart_required')
    return files


def insertion_candidates(source, repaired):
    """Only diff opcodes with zero source deletion are offered for upper review."""
    _require(isinstance(source, str) and source and isinstance(repaired, str), 'skin_body_required')
    offered, rejected = [], []
    for tag, i, end, j, stop in SequenceMatcher(None, source, repaired, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        if tag != 'insert':
            rejected.append({'kind': tag, 'sourceStart': i, 'sourceEnd': end,
                             'original': source[i:end], 'replacement': repaired[j:stop]})
            continue
        text = repaired[j:stop]
        # Equivalent insertions can be aligned before a shared sentence suffix
        # (e.g. 'す。...で' + original 'す。'). Rotate that shared prefix right
        # so upper review sees the complete added sentence, with identical bytes.
        while i < len(source) and text and source[i] == text[0]:
            text = text[1:] + source[i]
            i += 1
        item = {'offset': i, 'text': text,
                'before': source[max(0, i - 80):i], 'after': source[i:i + 80]}
        item['id'] = fingerprint(item)
        offered.append(item)
    return {'sourceSha256': fingerprint(source), 'repairSha256': fingerprint(repaired),
            'insertions': offered, 'rejectedChanges': rejected}


def apply_selected(source, diagnosis, selected):
    _require(diagnosis.get('sourceSha256') == fingerprint(source)
             and isinstance(selected, list) and selected and len(selected) == len(set(selected)),
             'skin_insertion_selection_invalid')
    by_id = {i['id']: i for i in diagnosis['insertions']}
    _require(all(s in by_id for s in selected), 'skin_unoffered_insertion')
    result = source
    for item in sorted((by_id[s] for s in selected), key=lambda i: i['offset'], reverse=True):
        at = item['offset']
        _require(item['before'] == source[max(0, at - 80):at]
                 and item['after'] == source[at:at + 80], 'skin_insertion_anchor_changed')
        result = result[:at] + item['text'] + result[at:]
    _require(inspect_polish(source, result)['passed'] is True, 'skin_protected_content_changed')
    return result


def diagnose(root):
    """Read only: expose the exact two pinned paid outputs and insertion choices."""
    root = Path(root)
    values, hashes, responses, models = [], [], [], []
    for name in ARTIFACT_NAMES:
        artifact, digest = _read(root / 'model-artifacts' / (name + '.json'))
        _require(isinstance(artifact.get('responseId'), str)
                 and hashlib.sha256(artifact['responseId'].encode()).hexdigest() == name,
                 'skin_response_file_binding')
        values.append(_strict_json(artifact.get('content', '')))
        hashes.append(digest)
        responses.append(artifact['responseId'])
        models.append(artifact.get('model'))
    _require(isinstance(models[0], str) and models[0].startswith('claude-') and models[0] == models[1],
             'skin_same_paid_writer_required')
    original, repair = values
    _require(set(original) == set(repair) == {'article', 'brief'}
             and isinstance(original['article'], dict) and isinstance(repair['article'], dict)
             and original['brief'] == repair['brief']
             and {k: v for k, v in original['article'].items() if k != 'content'} ==
                 {k: v for k, v in repair['article'].items() if k != 'content'},
             'skin_metadata_or_brief_changed')
    body, other = original['article']['content'], repair['article']['content']
    _require(len(body) == 4994 and len(other) == 5148 and original['brief'].get('format') == 'comparison'
             and 'この2つは素材の考え方が根本的に違います' in body
             and 'その1パターンを買う形' in body, 'skin_exact_failure_artifacts_required')
    from collections import Counter
    removed = Counter(_protected(body)) - Counter(_protected(other))
    added = Counter(_protected(other)) - Counter(_protected(body))
    _require(removed == Counter({('number', '2'): 1, ('number', '1'): 1}) and not added,
             'skin_other_protected_change')
    return {'artifacts': hashes, 'responseIds': responses, 'original': original,
            'diagnosis': insertion_candidates(body, other)}


def _slot(job, snapshot, batch, jobs, now):
    result = resolve_batch(batch, snapshot,
        [j['theme'] for j in jobs if j.get('kind') != 'supplemental_article'], now)
    slot = next((s for s in result['slots'] if s['slot'] == job['batchSlot']), {})
    _require(slot.get('status') == 'ready' and slot.get('theme') == job['theme']
             and slot.get('sourceBinding') == job['sourceBinding'], 'skin_live_source_or_theme_changed')


def manager_blocks(record):
    action = record.get('action') if isinstance(record.get('action'), dict) else {}
    targets = [record.get('jobId'), record.get('job_id'), action.get('jobId'), action.get('job_id')]
    return (record.get('status') in ('evaluating', 'executing')
            or record.get('status') == 'requires_reconciliation' and JOB_ID in targets)


def selected_products(snapshot, ids):
    result = []
    for pid in ids:
        rows = [p for p in snapshot.get('products', []) if isinstance(p, dict) and p.get('id') == pid]
        _require(len(rows) == 1, 'skin_unique_selected_products_required')
        result.append(rows[0])
    return result


def prepare(config_path, review_path, snapshot_path, fresh_research_path, *, now=None):
    """Read only. Astra selects offered insertions and reviews their meaning/style."""
    now = now or datetime.now(JST)
    _require(now.utcoffset() is not None, 'skin_aware_now_required')
    config, config_sha = _read(config_path)
    root = Path(config['stateRoot'])
    authorization, authorization_sha = _read(root / AUTHORIZATION_PATH)
    _require(bool(authorization), 'skin_owner_authorization_evidence_required')
    database = root / 'ledger.sqlite3'
    _require(database.is_absolute() and database.is_file()
             and not any(p.is_symlink() for p in (database, *database.parents)), 'skin_unsafe_state')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        jobs = [json.loads(v[0]) for v in db.execute('SELECT data FROM jobs')]
        records = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM meta WHERE key LIKE ?',
                                                        ('stage_journal:v1:%',))}
        _require(db.execute('SELECT 1 FROM meta WHERE key=?', (RECEIPT,)).fetchone() is None,
                 'skin_grant_already_claimed')
        _require(db.execute("SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')", (JOB_ID,)).fetchone() is None,
                 'skin_unknown_effect')
        _require(db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id=? AND status IN ('reserved','in_flight','unknown')", (JOB_ID,)).fetchone() is None,
                 'skin_unknown_budget')
        managers = [json.loads(v[0]) for v in db.execute(
            "SELECT value FROM meta WHERE key LIKE 'editorial_manager:%'")]
        _require(not any(manager_blocks(v) for v in managers), 'skin_manager_requires_reconciliation')
        _require(db.execute('SELECT 1 FROM requests WHERE job_id=?', (JOB_ID,)).fetchone() is None,
                 'skin_existing_owner_request')
    job = next((j for j in jobs if j['id'] == JOB_ID), {})
    _require(job.get('kind') == 'supplemental_article' and job.get('batchId') == BATCH
             and job.get('batchSlot') == 2
             and job.get('theme', {}).get('productIds') == ['apparel-millet-miv01248', 'apparel-finetrack-fum0422']
             and job.get('theme', {}).get('slug') == 'drynamic-mesh-drylayer-basic-outdoor-comparison'
             and job.get('batchCallCap') == 96 and job.get('stage') == 'error'
             and all(job.get(k) is None for k in ('bundle', 'review', 'approval', 'publication')),
             'skin_exact_unapproved_error_job_required')
    mine = {k: r for k, r in records.items() if r.get('jobId') == JOB_ID}
    _require(not any(r.get('status') in ('in_flight', 'unknown') for r in mine.values()), 'skin_unknown_stage')
    parent = mine.get(OLD_KEY, {})
    child = mine.get(parent.get('successorKey'), {})
    _require(len(mine) == 2 and parent.get('stage') == child.get('stage') == 'draft'
             and parent.get('status') == child.get('status') == 'failed'
             and parent.get('attempts') == 1 and parent.get('maxAttempts') == 2
             and child.get('attempts') == child.get('maxAttempts') == 2
             and child.get('predecessorKey') == OLD_KEY and not child.get('successorKey'),
             'skin_exact_exhausted_lineage_required')
    paid = diagnose(root)
    receipts = {r.get('responseId') for b in child.get('usageBatches', []) for r in b.get('records', [])}
    _require(set(paid['responseIds']) <= receipts, 'skin_paid_responses_not_in_failed_lineage')
    review, review_sha = _read(review_path)
    _require(review.get('kind') == 'skin_length_insertion_review_v1' and review.get('jobId') == JOB_ID
             and review.get('artifactSha256') == paid['artifacts'] and review.get('reviewedBy') == 'Astra'
             and isinstance(review.get('reviewReference'), str) and bool(review['reviewReference'].strip())
             and all(review.get(k) is True for k in ('factsPreserved', 'meaningPreserved', 'styleReviewed', 'noNewFacts')),
             'skin_exact_upper_review_required')
    corrected = copy.deepcopy(paid['original'])
    corrected['article']['content'] = apply_selected(corrected['article']['content'], paid['diagnosis'], review.get('selectedInsertionIds'))
    _require(review.get('candidateSha256') == fingerprint(corrected), 'skin_upper_candidate_hash_changed')
    bounds = ARTICLE_LENGTHS['comparison']
    _require(bounds[0] <= len(corrected['article']['content']) <= bounds[1], 'skin_corrected_length_outside_bounds')
    snapshot, snapshot_sha = _read(snapshot_path)
    fresh, fresh_sha = _read(fresh_research_path)
    batch = load_batch(config.get('supplementalApparelBatchManifest'))
    _slot(job, snapshot, batch, jobs, now)
    ids = job['theme']['productIds']
    products = selected_products(snapshot, ids)
    _require(products == fresh.get('products') == fresh.get('catalog')
             and [p['id'] for p in products] == ids
             and all(fresh.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate')),
             'skin_fresh_verified_products_required')
    evidence = (fresh.get('evidence') or {}).get('products') or []
    _require([e.get('productId') for e in evidence] == ids
             and all(_fresh(e.get('checkedAt'), now) for e in evidence), 'skin_stale_or_future_evidence')
    validated = Models({})._validate_draft(copy.deepcopy(corrected), job['theme'], fresh)
    _require(all(validated['article'][k] == corrected['article'][k] for k in ARTICLE_FIELDS)
             and validated['brief'] == corrected['brief'], 'skin_validation_changed_candidate')
    limits = budget_config(config.get('modelBudget'))
    _require(limits['article']['calls'] <= 32 and limits['period']['calls'] <= 128, 'skin_unchanged_budget_required')
    return {'schemaVersion': 1, 'status': 'ready_for_owner_grant', 'jobId': JOB_ID, 'batchId': BATCH,
            'paths': {'config': str(config_path), 'review': str(review_path), 'snapshot': str(snapshot_path),
                      'freshResearch': str(fresh_research_path)}, 'jobSha256': fingerprint(job),
            'originalError': job['error'], 'oldStages': {k: fingerprint(v) for k, v in mine.items()},
            'sha256': {'config': config_sha, 'artifacts': paid['artifacts'], 'upperReview': review_sha,
                       'snapshot': snapshot_sha, 'freshResearch': fresh_sha, 'protocol': fingerprint(protocol()),
                       'authorization': authorization_sha},
            'authorizationEvidence': {'reference': AUTHORIZATION_PATH, 'sha256': authorization_sha},
            'corrected': corrected, 'correctedSha256': fingerprint(corrected),
            'caps': {'articleCalls': limits['article']['calls'], 'periodCalls': limits['period']['calls'], 'batchCalls': 96},
            'maximumRuns': {'literalDraft': 1, 'polish': 1, 'final_review': 1}, 'executed': False}


class _OneRequestBudget:
    """No provider fallback/retry can spend a second request in a granted stage."""
    def __init__(self, budget):
        self.budget, self.stage, self.spent = budget, None, set()

    def reserve(self, *args, **kwargs):
        _require(self.stage in ('polish', 'final_review') and self.stage not in self.spent,
                 'skin_one_request_per_stage')
        self.spent.add(self.stage)
        return self.budget.reserve(*args, **kwargs)

    def settle(self, *args, **kwargs):
        return self.budget.settle(*args, **kwargs)


class _SkinRuntime(Runtime):
    def __init__(self, rt, plan):
        self.__dict__ = rt.__dict__.copy()
        self._plan = copy.deepcopy(plan)
        self._executed_stages = set()
        self._explicit_stage_retry = None
        self.models = copy.copy(rt.models)
        self.models.usage, self.models.review_diagnostics = [], []
        self.models.budget = _OneRequestBudget(rt.model_budget)
        self._usage_response_ids, self._saved_usage_response_ids = set(), set()
        self._publisher, self.publisher = rt.publisher, self._stage_only
        snapshot, _ = _read(plan['paths']['snapshot'])
        job = rt.ledger.get_job(JOB_ID)
        selected = selected_products(snapshot, job['theme']['productIds'])
        self.catalog = _VerifiedCatalog(rt.catalog, job, selected)

    def _require_running(self):
        Runtime._require_running(self)
        _, digest = _read(self._plan['paths']['config'])
        _require(digest == self._plan['sha256']['config']
                 and fingerprint(protocol()) == self._plan['sha256']['protocol'], 'skin_config_or_protocol_changed')

    def _run_model_stage(self, job, stage, inputs, operation, requested_model, **kwargs):
        self._require_running()
        order = ('draft', 'polish', 'final_review')
        _require(job['id'] == JOB_ID and stage in order and not kwargs
                 and self._executed_stages == set(order[:order.index(stage)]), 'skin_stage_or_order_forbidden')
        if stage == 'final_review':
            _require(all(inputs['dependencies']['qualityFlags'].values())
                     and inputs['dependencies']['structural'].get('passed') is True, 'skin_quality_gates_failed')
        self._executed_stages.add(stage)
        namespace = 'owner_oneoff:' + AUTHORIZATION + ':' + ('literal_draft' if stage == 'draft' else stage)
        bound = dict(inputs, ownerGrantManifestSha256=fingerprint(self._plan))
        key = self.stage_journal.key(JOB_ID, namespace, bound)
        if stage == 'draft':
            def literal():
                fresh, digest = _read(self.root / 'research' / (JOB_ID + '.json'))
                _require(fresh.get('products') == inputs['dependencies']['source']['products'], 'skin_live_products_changed')
                value = copy.deepcopy(self._plan['corrected'])
                _require(fingerprint(value) == self._plan['correctedSha256'], 'skin_candidate_changed')
                return self.models._validate_draft(value, job['theme'], fresh)
            return self.stage_journal.run(JOB_ID, namespace, bound, literal, max_attempts=1)
        start = len(self.models.usage)
        self.models.budget.stage = stage
        def measured():
            with self.model_budget.scope(JOB_ID, stage):
                result = operation()
            usage = self.models.usage[start:]
            _require(len(usage) == 1 and usage[0].get('responseId') and usage[0].get('usage')
                     and usage[0]['model'] == ('gemini-3.8-flash' if stage == 'polish' else 'claude-sonnet-4-6'),
                     'skin_exact_model_receipt_required')
            return result
        try:
            return self.stage_journal.run(JOB_ID, namespace, bound, measured, max_attempts=1)
        finally:
            self.models.budget.stage = None
            usage = self._usage_slice(start, article_id=JOB_ID, stage=namespace, reason='initial', requested_model=requested_model)
            if usage:
                self.stage_journal.record_usage(JOB_ID, namespace, key, _usage_copy(usage))

    def _stage_only(self, action, job):
        _require(action == 'stage' and job['id'] == JOB_ID and job['stage'] == 'review'
                 and job.get('approval') is None and job.get('publication') is None, 'skin_publication_forbidden')
        return self._publisher(action, job)

    def deliver(self, id, kind='article'):
        _require(id == JOB_ID and kind == 'article', 'skin_delivery_forbidden')
        return Runtime.deliver(self, id, kind)

    def _forbidden(self, *args, **kwargs):
        raise ValueError('skin_entrypoint_forbidden')

    tick = consume = produce = produce_supplemental = retry = retry_stage = _forbidden
    retry_corrected_stage = publish_social = publish_buffer_social = make_social = _publish = _forbidden
    request_revisions = approve_from_codex = enable_social_autopost = _forbidden
    prepare_social_handoff = refresh_social_images = _forbidden


def execute(runtime, plan, *, owner_grant):
    """Main invokes only after reviewing the exact prepared plan; no CLI autorun."""
    _require(owner_grant == {'reference': AUTHORIZATION_PATH, 'action': ACTION, 'jobId': JOB_ID,
                            'authorizationSha256': plan['sha256']['authorization'],
                            'manifestSha256': fingerprint(plan)} and plan.get('jobId') == JOB_ID,
             'skin_exact_owner_grant_required')
    runtime._require_running()
    config, digest = _read(plan['paths']['config'])
    _require(config == runtime.config and digest == plan['sha256']['config']
             and Path(config['stateRoot']).resolve() == runtime.root.resolve(), 'skin_runtime_config_changed')
    with (runtime.root / 'runtime.flock').open('a') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy', 'executed': False}
        p = plan['paths']
        current = prepare(p['config'], p['review'], p['snapshot'], p['freshResearch'])
        _require(current == plan, 'skin_pinned_plan_changed')
        _require(isinstance(runtime.models, Models) and runtime.models.budget is runtime.model_budget
                 and runtime.model_budget.config == budget_config(config.get('modelBudget')), 'skin_real_unchanged_budget_required')
        routes = runtime._model_routes()
        _require(routes['polish']['requested'] == 'gemini-3.8-flash'
                 and routes['final_review']['requested'] == 'claude-sonnet-4-6', 'skin_model_routes_changed')
        with runtime.ledger._tx() as db:
            _require(db.execute('SELECT 1 FROM meta WHERE key=?', (RECEIPT,)).fetchone() is None, 'skin_grant_already_claimed')
            receipt = {'status': 'in_flight', 'attempts': 1, 'maxAttempts': 1, 'jobId': JOB_ID,
                       'manifestSha256': fingerprint(plan), 'ownerGrant': owner_grant, 'at': stamp(),
                       'originalError': plan['originalError'], 'oldStages': plan['oldStages']}
            db.execute('INSERT INTO meta VALUES (?,?)', (RECEIPT, json.dumps(receipt)))
            runtime.ledger._event(db, JOB_ID, 'skin_owner_recovery_claimed', receipt)
        view = None
        try:
            archive = runtime.root / 'manual-operations' / AUTHORIZATION
            _require(not archive.exists(), 'skin_archive_exists')
            historical, _ = _read(runtime.root / 'research' / (JOB_ID + '.json'))
            atomic(archive / 'original-research.json', historical)
            atomic(archive / 'manifest.json', plan)
            atomic(archive / 'original-job.json', runtime.ledger.get_job(JOB_ID))
            view = _SkinRuntime(runtime, plan)
            context = view._context()
            _slot(view.ledger.get_job(JOB_ID), context, view._supplemental_manifest(), view.ledger.list_jobs(), datetime.now(JST))
            result = view._make_article(view.ledger.get_job(JOB_ID), context)
            _require(view._executed_stages == {'draft', 'polish', 'final_review'}, 'skin_incomplete_pipeline')
            status = 'completed'
            return result
        except BaseException as error:
            status = 'requires_reconciliation'
            if isinstance(error, Exception):
                current_job = runtime.ledger.get_job(JOB_ID)
                if current_job.get('approval') is None and current_job.get('publication') is None:
                    runtime.ledger.set_stage(JOB_ID, 'error', {'reason': reason(error), 'at': stamp(),
                        'originalFailure': copy.deepcopy(plan['originalError']), 'ownerRecoveryReceipt': RECEIPT})
            raise
        finally:
            with runtime.ledger._tx() as db:
                saved = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (RECEIPT,)).fetchone()[0])
                saved.update(status=status, completedAt=stamp())
                db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(saved), RECEIPT))
                runtime.ledger._event(db, JOB_ID, 'skin_owner_recovery_result', saved)
            if view is not None:
                view._save_usage()
