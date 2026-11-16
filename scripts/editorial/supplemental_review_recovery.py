"""One owner-authorized Plasma correction; original stage histories stay intact.

Prepare is read only. Execution claims once, uses the normal quality pipeline and
unchanged budgets, and journals each new stage once under the fixed grant.
"""
import argparse
import copy
import fcntl
import plistlib
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3

from ledger import JST, fingerprint
from model_budget import _config as budget_config
from supplemental_topics import load_batch, resolve_batch


BATCH = 'apparel-2026-11-16'
JOB_ID = 'article-8a1de35ed5e57df9e6cacb5a'
AUTHORIZATION = 'call_62252aef8194402990abae5016c1bd19'
OWNER_ANSWER = '今回だけ追加修正・審査を許可'
CONFIG_SHA = 'de79f4c1537eb192df094f18d8deb7d6f8e6cf75877e4776e949456153107cbe'
SOURCE_DIR = '4558f792523df98e13826b674de8b859f8ef716266091acf93d4214d46b37566'
SOURCE_SHA = 'be6c83326f6139213d27d938c0783450ace9fd8b1355b57f3d17f3d76cb1219d'
CANDIDATE_SHA = 'a83363782b8aebea34e02729ec638900386c3a83a8564a2a716be99c376bfeb2'
FINAL_KEY = 'stage_journal:v1:0ab6221d113d2bedb030b03cdfe8062aff9de8dba2385ce580668c8fb291a8b8'
DIAGNOSTIC_DIR = 'manual-operations/20261117-apparel-slot1-final-review'
RECEIPT_KEY = 'supplemental_manual_recovery:v1:plasma-20261117'

MAX_BYTES = 2 * 1024 * 1024
PROTOCOL_FILES = ('supplemental_review_recovery.py', 'runtime.py', 'models.py', 'quality.py')
LOADED_FILES = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in PROTOCOL_FILES}
CRITIQUE = (
    'Remove unsupported windproofness and thin-shell comparisons.',
    'Remove mean-weight or size-variation assumptions.',
    'Remove ideal-packing, activity and room-suitability assumptions.',
    'Do not infer temperature ratings from absent source data.',
    'Remove unsupported scientific definitions; introduce no new facts.',
    'Include an exact sourced official-versus-Rakuten-versus-Amazon variant table; preserve fixed/selectable distinctions.',
    'State concisely once that this is a research article; do not repeat the disclosure.',
)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _read(path):
    path = Path(path)
    _require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents))
             and path.is_file() and path.stat().st_size <= MAX_BYTES, 'unsafe_evidence_file')
    raw = path.read_bytes()
    value = json.loads(raw)
    _require(isinstance(value, dict), 'evidence_object_required')
    return value, hashlib.sha256(raw).hexdigest()


def _fresh(value, now):
    try:
        checked = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (checked.utcoffset() is not None
                and timedelta(0) <= now - checked <= timedelta(hours=6))
    except (AttributeError, TypeError, ValueError):
        return False


def _cached(record):
    _require(record.get('status') == 'succeeded' and 'output' in record
             and record.get('outputHash') == fingerprint(record['output']), 'cached_output_integrity')
    return record['output']


def prepare(config_path, job_id, old_failed_key, proposed_path, proof_path, snapshot_path, *, now=None):
    """Pin a caller-supplied correction proposal and fresh source snapshot.

    All inputs are read only. A supplied candidate is a proposal, never accepted
    Claude output. Even a blocker-free plan requires explicit owner permission,
    a new source-bound Claude correction, Gemini, live QA and final review.
    """
    now = now or datetime.now(JST)
    _require(now.utcoffset() is not None, 'aware_now_required')
    config, config_sha = _read(config_path)
    root = Path(config['stateRoot'])
    _require(root.is_absolute() and root.resolve() not in (Path('/'), Path.home()), 'unsafe_state_root')
    database = root / 'ledger.sqlite3'
    _require(database.is_file() and not any(p.is_symlink() for p in (database, *database.parents)),
             'unsafe_ledger')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        jobs = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs')]
        records = {key: json.loads(raw) for key, raw in db.execute(
            'SELECT key,value FROM meta WHERE key LIKE ?', ('stage_journal:v1:%',))}
    job = next((j for j in jobs if j['id'] == job_id), None)
    _require(job_id == JOB_ID and old_failed_key == FINAL_KEY and config_sha == CONFIG_SHA,
             'exact_owner_authorized_plasma_required')
    diagnostic, diagnostic_sha = _read(root / DIAGNOSTIC_DIR / 'provider-diagnostic.json')
    operation_path = root / DIAGNOSTIC_DIR / 'operation.plist'
    _require(not operation_path.is_symlink(), 'unsafe_operation_proof')
    operation_raw = operation_path.read_bytes()
    operation = plistlib.loads(operation_raw)
    args = operation['ProgramArguments']
    _require(args[args.index('--job-id') + 1] == JOB_ID
             and args[args.index('--input-key') + 1] == FINAL_KEY
             and args[args.index('--stage') + 1] == 'final_review'
             and args[args.index('--state-root') + 1] == str(root)
             and diagnostic.get('httpStatus') == 400
             and diagnostic.get('providerCategory') == 'invalid_request_error'
             and diagnostic.get('reasonClass') == 'schema'
             and diagnostic.get('requestedModel') == 'claude-sonnet-4-6', 'schema_diagnostic_binding')
    _require(job is not None and job.get('kind') == 'supplemental_article'
             and job.get('batchId') == BATCH and job.get('batchSlot') == 1
             and job['theme'].get('productIds') == ['apparel-montbell-1101493']
             and job['theme'].get('slug') == 'plasma1000-1101493-layering-guide'
             and job.get('batchCallCap') == 96 and job.get('stage') == 'error'
             and all(job.get(k) is None for k in ('bundle', 'review', 'approval', 'publication'))
             and (job.get('error') or {}).get('reason') == 'ModelError',
             'existing_supplemental_schema_failure_required')
    _require(Path(job_id).name == job_id and job_id not in ('.', '..'), 'unsafe_job_id')
    final = records.get(old_failed_key, {})
    _require(final.get('stageKey') == old_failed_key and final.get('jobId') == job_id
             and final.get('stage') == 'final_review' and final.get('status') == 'failed'
             and final.get('attempts') == 2 and final.get('maxAttempts') == 2
             and not final.get('successorKey'), 'exact_exhausted_review_required')
    successes = {}
    for stage in ('draft', 'polish'):
        found = [r for r in records.values() if r.get('jobId') == job_id
                 and r.get('stage') == stage and r.get('status') == 'succeeded']
        _require(len(found) == 1, 'unique_successful_writer_polish_required')
        successes[stage] = found[0]
    draft, polish = (_cached(successes[s]) for s in ('draft', 'polish'))
    parent = records.get(successes['draft'].get('predecessorKey'), {})
    _require(parent.get('jobId') == job_id and parent.get('stage') == 'draft'
             and parent.get('status') == 'failed' and parent.get('attempts') == 1
             and parent.get('successorKey') == successes['draft']['stageKey'], 'original_failed_lineage_required')
    successes['original_failed_draft'] = parent
    source_path = root / 'research' / 'artifacts' / job_id / SOURCE_DIR / 'source.json'
    source, source_sha = _read(source_path)
    candidate, candidate_sha = _read(source_path.with_name('candidate.json'))
    gathered, gathered_sha = _read(root / 'research' / (job_id + '.json'))
    _require(source_sha == SOURCE_SHA and candidate_sha == CANDIDATE_SHA, 'pinned_original_artifacts_required')
    _require(source.get('kind') == 'source' and isinstance(source.get('bundle'), dict)
             and source_path.parent.name == fingerprint(source['bundle'])
             and source['bundle'].get('article', {}).get('content') == draft.get('article', {}).get('content'),
             'source_artifact_mismatch')
    _require(candidate.get('kind') == 'candidate' and candidate.get('candidate') == polish.get('polished')
             and polish.get('polished', {}).get('model') == 'gemini-3.8-flash'
             and polish.get('preservation', {}).get('passed') is True, 'polish_artifact_mismatch')
    proposed, proposed_sha = _read(proposed_path)
    proof, proof_sha = _read(proof_path)
    _require(proof.get('jobId') == job_id and proof.get('sourceBinding') == job['sourceBinding']
             and proof.get('proposedCandidateSha256') == proposed_sha
             and isinstance(proof.get('corrections'), list) and proof['corrections']
             and all(isinstance(item, dict) for item in proof['corrections']), 'proposal_proof_binding')
    _require(proposed.get('kind') in ('candidate', 'correction-plan'), 'correction_proposal_required')
    if 'approvedWritingBrief' in proposed:
        _require(isinstance(proposed['approvedWritingBrief'], dict) and proposed['approvedWritingBrief'],
                 'approved_writing_brief_must_be_nonempty_object')
    body = (proposed.get('candidate') or {}).get('content')
    _require(proposed['kind'] == 'correction-plan' or isinstance(body, str) and body.strip(),
             'proposed_body_required')
    snapshot, snapshot_sha = _read(snapshot_path)
    batch = load_batch(config.get('supplementalApparelBatchManifest'))
    resolved = resolve_batch(batch, snapshot,
        [j['theme'] for j in jobs if j.get('kind') != 'supplemental_article'], now)
    slot = next((s for s in resolved['slots'] if s['slot'] == job['batchSlot']), {})
    blockers = []
    if body == polish['polished']['content']:
        blockers.append('unsupported_claim_corrections_required')
    if (slot.get('status') != 'ready' or slot.get('sourceBinding') != job['sourceBinding']
            or slot.get('theme') != job['theme']):
        blockers.append('current_source_binding_or_theme_changed')
    products = [p for p in snapshot.get('products', []) if p.get('id') in job['theme']['productIds']]
    if not (products == gathered.get('products') == gathered.get('catalog') == source['bundle'].get('products')):
        blockers.append('canonical_products_changed')
    evidence = (gathered.get('evidence') or {}).get('products') or []
    if (not _fresh(snapshot.get('checkedAt'), now)
            or [p.get('productId') for p in evidence] != job['theme']['productIds']
            or any(not _fresh(p.get('checkedAt'), now) for p in evidence)):
        blockers.append('source_evidence_stale_or_future')
    if not all(gathered.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate')):
        blockers.append('independent_source_checks_incomplete')
    limits = budget_config(config.get('modelBudget'))
    _require(limits['article']['calls'] <= 32 and limits['period']['calls'] <= 128,
             'unchanged_budget_bounds_required')
    return {
        'schemaVersion': 1, 'status': 'held_for_owner_decision', 'executed': False,
        'jobId': job_id, 'batchId': BATCH, 'batchSlot': job['batchSlot'],
        'paths': {'config': str(config_path), 'proposed': str(proposed_path),
                  'proof': str(proof_path), 'snapshot': str(snapshot_path)},
        'jobSha256': fingerprint(job), 'originalError': job['error'],
        'sourceBinding': job['sourceBinding'], 'oldFailedKey': old_failed_key,
        'oldStages': {s: {'key': r['stageKey'], 'status': r['status'], 'attempts': r['attempts'],
                         'maxAttempts': r['maxAttempts'], 'recordSha256': fingerprint(r),
                         'inputHash': r['inputHash'], 'dependencyHash': r['dependencyHash']}
                      for s, r in dict(successes, final_review=final).items()},
        'sha256': {'sourceArtifact': source_sha, 'candidateArtifact': candidate_sha,
                   'sourceBundle': fingerprint(source['bundle']), 'gathered': gathered_sha,
                   'proposedCandidate': proposed_sha, 'sourceProof': proof_sha,
                   'currentSourceSnapshot': snapshot_sha, 'config': config_sha,
                   'newProtocol': fingerprint(_protocol()), 'caps': fingerprint({'modelBudget': limits, 'batchCalls': 96}),
                   'diagnostic': diagnostic_sha, 'operation': hashlib.sha256(operation_raw).hexdigest(),
                   'batchManifest': fingerprint(batch)},
        'caps': {'articleCalls': limits['article']['calls'], 'periodCalls': limits['period']['calls'],
                 'batchCalls': 96},
        'bodyChanged': body != polish['polished']['content'] if body is not None else None,
        'proposedCorrections': proof['corrections'], 'correctionConstraints': list(CRITIQUE),
        'required': {'ownerGrant': True, 'ClaudeVerifiedSourceCorrection': True, 'newGemini': True,
                     'independentSourceReview': True, 'historicalDependencyVerification': True,
                     'liveGatherAndImages': True, 'fullQualityAndRender': True, 'ClaudeFinalReview': True},
        'maximumProposedRuns': {'correction': 1, 'Gemini': 1, 'finalReview': 1},
        'blockers': blockers,
    }


def _protocol():
    import models
    files = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
             for name in PROTOCOL_FILES}
    _require(files == LOADED_FILES, 'loaded_protocol_changed_restart_required')
    return {'files': files,
            'writerSchema': fingerprint(models.WRITER_SCHEMA),
            'reviewSchema': fingerprint(models.REVIEW_SCHEMA)}


def _claim(rt, manifest, grant):
    with rt.ledger._tx() as db:
        _require(db.execute('SELECT 1 FROM meta WHERE key=?', (RECEIPT_KEY,)).fetchone() is None,
                 'owner_oneoff_already_claimed_requires_reconciliation')
        receipt = {'jobId': JOB_ID, 'status': 'in_flight', 'maxAttempts': 1, 'attempts': 1,
                   'manifestSha256': fingerprint(manifest), 'ownerGrant': grant,
                   'at': datetime.now(JST).isoformat()}
        db.execute('INSERT INTO meta VALUES (?,?)', (RECEIPT_KEY, json.dumps(receipt)))
        rt.ledger._event(db, JOB_ID, 'supplemental_owner_oneoff_claimed', receipt)


def _receipt(rt, **fields):
    with rt.ledger._tx() as db:
        raw = db.execute('SELECT value FROM meta WHERE key=?', (RECEIPT_KEY,)).fetchone()
        _require(raw is not None, 'owner_oneoff_claim_missing')
        value = json.loads(raw[0])
        value.update(fields)
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(value), RECEIPT_KEY))
        rt.ledger._event(db, JOB_ID, 'supplemental_owner_oneoff_result', fields)


def _validate_live(job, context, batch, jobs):
    result = resolve_batch(batch, context,
        [j['theme'] for j in jobs if j.get('kind') != 'supplemental_article'], datetime.now(JST))
    slot = next((s for s in result['slots'] if s['slot'] == 1), {})
    _require(slot.get('status') == 'ready' and slot.get('theme') == job['theme']
             and slot.get('sourceBinding') == job['sourceBinding'], 'live_source_or_theme_changed')


from runtime import Runtime
from stage_journal import StageJournal, _usage_copy


class _VerifiedCatalog:
    def __init__(self, catalog, job, products):
        self._catalog, self._job, self._products = catalog, job, products

    def __getattr__(self, name):
        return getattr(self._catalog, name)

    def gather(self, theme, context):
        _require(theme == self._job['theme'], 'unrelated_theme_forbidden')
        value = self._catalog.gather(theme, context)
        _require(value.get('products') == value.get('catalog') == self._products
                 and value.get('productIds') == self._job['theme']['productIds']
                 and all(value.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate')),
                 'fresh_independent_source_checks_required')
        evidence = (value.get('evidence') or {}).get('products') or []
        _require([e.get('productId') for e in evidence] == self._job['theme']['productIds']
                 and all(_fresh(e.get('checkedAt'), datetime.now(JST)) for e in evidence),
                 'fresh_source_evidence_required')
        return value


class _GrantedRuntime(Runtime):
    """A view of the existing runner, limited to this one approved job."""
    def __init__(self, rt, manifest, old_candidate):
        self.__dict__ = rt.__dict__.copy()
        self._manifest = copy.deepcopy(manifest)
        self._original = old_candidate
        self.models = copy.copy(rt.models)
        self.models.usage = []
        self._usage_response_ids, self._saved_usage_response_ids = set(), set()
        self._explicit_stage_retry = None
        self._publisher = rt.publisher
        self.publisher = self._stage_only
        snapshot, _ = _read(manifest['paths']['snapshot'])
        selected = [p for p in snapshot['products'] if p['id'] == 'apparel-montbell-1101493']
        self.catalog = _VerifiedCatalog(rt.catalog, rt.ledger.get_job(JOB_ID), selected)
        self._executed_stages = set()

    def _require_running(self):
        Runtime._require_running(self)
        _, digest = _read(self._manifest['paths']['config'])
        _require(digest == CONFIG_SHA and fingerprint(_protocol()) == self._manifest['sha256']['newProtocol'],
                 'owner_oneoff_config_or_protocol_changed')

    def _run_model_stage(self, job, stage, inputs, operation, requested_model, **kwargs):
        self._require_running()
        _require(job['id'] == JOB_ID and stage in ('draft', 'polish', 'final_review')
                 and stage not in self._executed_stages and not kwargs.get('explicit_retry'),
                 'owner_oneoff_stage_forbidden')
        _require((stage == 'draft' and not self._executed_stages)
                 or (stage == 'polish' and self._executed_stages == {'draft'})
                 or (stage == 'final_review' and self._executed_stages == {'draft', 'polish'}),
                 'owner_oneoff_stage_order')
        if stage == 'final_review':
            _require(all(inputs['dependencies']['qualityFlags'].values())
                     and inputs['dependencies']['structural'].get('passed') is True,
                     'independent_quality_gates_failed')
        self._executed_stages.add(stage)
        namespace = 'owner_oneoff:' + AUTHORIZATION + ':' + stage
        bound = dict(inputs, ownerGrantManifestSha256=fingerprint(self._manifest))
        key = self.stage_journal.key(JOB_ID, namespace, bound)
        start = len(self.models.usage)
        called = False
        def measured():
            nonlocal called
            called = True
            with self.model_budget.scope(JOB_ID, stage):
                result = operation()
            if stage == 'draft':
                _require(result['brief']['format'] == 'guide'
                         and all(result['article'].get(k) == job['theme'][k]
                                 for k in ('productIds', 'slug', 'categoryId')), 'corrected_article_identity_or_format_changed')
                _require(result['article']['content'] != self._original['content'],
                         'unsupported_original_body_not_corrected')
            measured_usage = self.models.usage[start:]
            _require(measured_usage and all(record.get('responseId') and record.get('usage')
                     and isinstance(record.get('model'), str)
                     and record['model'].startswith('gemini-' if stage == 'polish' else 'claude-')
                     for record in measured_usage), 'real_model_usage_receipt_required')
            return result
        try:
            return self.stage_journal.run(JOB_ID, namespace, bound, measured, max_attempts=1)
        finally:
            if called:
                records = self._usage_slice(start, article_id=JOB_ID, stage=namespace,
                    reason='initial', requested_model=requested_model)
                self.stage_journal.record_usage(JOB_ID, namespace, key, _usage_copy(records))

    def _stage_only(self, action, job):
        self._require_running()
        _require(action == 'stage' and job['id'] == JOB_ID and job['stage'] == 'review'
                 and job.get('approval') is None and job.get('publication') is None,
                 'owner_oneoff_publish_forbidden')
        return self._publisher(action, job)

    def deliver(self, id, kind='article'):
        _require(id == JOB_ID and kind == 'article', 'owner_oneoff_delivery_forbidden')
        return Runtime.deliver(self, id, kind)

    def _forbidden(self, *args, **kwargs):
        raise ValueError('owner_oneoff_entrypoint_forbidden')

    tick = consume = produce = produce_supplemental = retry = retry_stage = _forbidden
    retry_corrected_stage = publish_social = make_social = _publish = _forbidden
    request_revisions = approve_from_codex = _forbidden


def execute(runtime, manifest, *, owner_grant):
    """Main supplies the actual owner answer and this exact plan's digest.

    This API acquires runtime.flock itself. A crash, failed validation/model call,
    unknown outcome or delivery failure consumes the one-off claim; no retry path.
    It never changes old stage counters, config flags, budgets or owner approval.
    """
    expected = {'reference': AUTHORIZATION, 'answer': OWNER_ANSWER, 'jobId': JOB_ID,
                'manifestSha256': fingerprint(manifest)}
    _require(owner_grant == expected and manifest.get('jobId') == JOB_ID
             and manifest.get('oldFailedKey') == FINAL_KEY, 'exact_owner_grant_required')
    runtime._require_running()
    config, digest = _read(manifest['paths']['config'])
    _require(digest == CONFIG_SHA and config == runtime.config
             and Path(config['stateRoot']).resolve() == runtime.root.resolve(), 'runtime_config_binding')
    with (runtime.root / 'runtime.flock').open('a') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy', 'executed': False}
        paths = manifest['paths']
        current = prepare(paths['config'], JOB_ID, FINAL_KEY, paths['proposed'], paths['proof'], paths['snapshot'])
        _require(current == manifest and not current['blockers'], 'pinned_manifest_changed_or_blocked')
        from models import Models
        _require(runtime.model_budget.config == budget_config(config.get('modelBudget')), 'budget_config_changed')
        routes = runtime._model_routes()
        _require(routes['draft']['requested'].startswith('claude-')
                 and routes['final_review']['requested'] == 'claude-sonnet-4-6'
                 and routes['polish']['requested'] == 'gemini-3.8-flash', 'authorized_model_routes_required')
        _require(isinstance(runtime.models, Models) and runtime.models.budget is runtime.model_budget,
                 'real_budgeted_models_required')
        _claim(runtime, manifest, owner_grant)
        view = None
        try:
            # Preserve the original research file before _make_article regathers it.
            from runtime import atomic
            archive = runtime.root / 'manual-operations' / '20261117-plasma-owner-approved-repair'
            _require(not archive.exists(), 'recovery_artifact_directory_already_exists')
            gathered, _ = _read(runtime.root / 'research' / (JOB_ID + '.json'))
            atomic(archive / 'original-research.json', gathered)
            atomic(archive / 'manifest.json', manifest)
            old, _ = _read(runtime.root / 'research' / 'artifacts' / JOB_ID / SOURCE_DIR / 'candidate.json')
            view = _GrantedRuntime(runtime, manifest, old['candidate'])
            context = view._context()
            job = view.ledger.get_job(JOB_ID)
            _validate_live(job, context, view._supplemental_manifest(), view.ledger.list_jobs())
            # Critique is an upper-editor constraint, never an asserted factual source.
            context['editorialRules'] += '\nOwner-approved correction constraints:\n' + '\n'.join(CRITIQUE)
            original, _ = _read(runtime.root / 'research' / 'artifacts' / JOB_ID / SOURCE_DIR / 'source.json')
            context['editorialRules'] += ('\nCorrect the existing article below; every legacy claim is unverified. '
                'Remove the listed unsupported inferences from title/body/FAQ/metadata. '
                'Use ONLY the newly gathered primary evidence; add no facts from legacy prose.\n'
                + json.dumps(original['bundle']['article'], ensure_ascii=False))
            proposed, proposed_sha = _read(paths['proposed'])
            _require(proposed_sha == manifest['sha256']['proposedCandidate'], 'pinned_proposal_changed')
            if 'approvedWritingBrief' in proposed:
                context['editorialRules'] += ('\nMain upper-editor approvedWritingBrief (not a new factual source); '
                    'all facts must match freshly gathered primary references. Preserve guide format, '
                    'selected products, slug and category.\n'
                    + json.dumps(proposed['approvedWritingBrief'], ensure_ascii=False))
            result = view._make_article(job, context)
            _require(view._executed_stages == {'draft', 'polish', 'final_review'}, 'incomplete_owner_pipeline')
            _receipt(runtime, status='completed', result=result)
            return result
        except BaseException as error:
            # Unknown/interrupted work is never reconciled as a safe failed retry.
            _receipt(runtime, status='requires_reconciliation', failureType=type(error).__name__)
            if isinstance(error, Exception):
                from runtime import reason, stamp
                current_job = runtime.ledger.get_job(JOB_ID)
                if current_job.get('approval') is None and current_job.get('publication') is None:
                    runtime.ledger.set_stage(JOB_ID, 'error', {
                        'reason': reason(error), 'at': stamp(),
                        'originalFailure': copy.deepcopy(manifest['originalError']),
                        'ownerRecoveryReceipt': RECEIPT_KEY})
            raise
        finally:
            if view is not None:
                view._save_usage()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepare or execute the one authorized Plasma correction')
    for name in ('config', 'job-id', 'old-failed-key', 'proposed', 'source-proof', 'current-source',
                 'manifest', 'owner-grant'):
        parser.add_argument('--' + name)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    if args.execute:
        _require(args.manifest and args.owner_grant, 'pinned_manifest_and_owner_grant_required')
        manifest, _ = _read(args.manifest)
        grant, _ = _read(args.owner_grant)
        _require(grant == {'reference': AUTHORIZATION, 'answer': OWNER_ANSWER, 'jobId': JOB_ID,
                          'manifestSha256': fingerprint(manifest)}, 'exact_owner_grant_required')
        config, digest = _read(manifest['paths']['config'])
        _require(digest == CONFIG_SHA, 'exact_config_required')
        result = execute(Runtime(config), manifest, owner_grant=grant)
    else:
        _require(all((args.config, args.job_id, args.old_failed_key, args.proposed,
                      args.source_proof, args.current_source)), 'prepare_inputs_required')
        result = prepare(args.config, args.job_id, args.old_failed_key, args.proposed,
                         args.source_proof, args.current_source)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
