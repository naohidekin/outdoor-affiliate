"""Fixed Nov 20 owner grant: Zeoline and Chameece, normal pipeline, no publishing.

prepare reads only; execute consumes one durable claim per article. Historical
research and journals are evidence, never relabelled as freshly verified sources.

Completion API: prepare(..., phase='completion'), execute(..., owner_grant=...).
The fixed COMPLETION_AUTHORIZATION/ANSWER bind the latest completion instruction.
A proposal adds completionPlan={diagnosis:{scoringInconsistency,bodyQuality},
changes:[{target:body|purchase_links|structure|wording|facts,change:concrete text}]}.
The usual source proof adds historicalArtifacts={directory,source,candidate}
(SHA-256 values for the current failed generation's directory/source/candidate).
Each changed brief/plan gets a distinct claim and archive; each stage attempts
once. Known final-review quality failures can lead to a new specification under
the same standing grant. Same plans/briefs, historical candidate bodies, unknown
work and exhausted existing budgets stop. Owner approval/publication stay separate.

Optional correction_path pins the prior candidate article, exact replacement
paths/counts and corrected article. Default mode only deletes/retains complete
sentences. mode=upper_editor_candidate permits whole content/FAQ-field edits
bound by an Astra upperEditorReview to candidateArticleSha256, writingBriefSha256,
freshResearchSha256 and sourceProofSha256. Neither mode changes identity, products,
references, images or the original writer brief. Brief literal conflicts stop.
A local literal_correction journal records provenance without model usage;
Gemini, independent QA and Claude final remain real, budgeted and mandatory.
"""
import copy
from datetime import datetime
import fcntl
import hashlib
import json
import re
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
SOURCE_ONLY_AUTHORIZATION = 'call_b5fdac5902d24a3d8cdaa18f4e075de9'
SOURCE_ONLY_ANSWER = '2件の追加再構成・審査を許可'
# Fixed second-phase artifact pins; never accept caller-selected grants or jobs.
SOURCE_ONLY_JOBS = {
    'article-569175cfacbb87d25de6d09c': {
        'final': 'stage_journal:v1:bbe6844c25e5da3d37e8027c4401a359b82e22df8a15015109a18742cc161c90',
        'directory': '52c773c9359ab30f1c8e3b60ae6f7941bd1d8653653fd3b6cc9b40a9cd77f0f3',
        'source': '72308b738940d13d634909828c01f0162d36aa8d1a6233102611d944a07d6a2c',
        'candidate': '8db286ee5dc9a1f3c376a9c316cc9959619731448edf3641161bcd54624f3ec5'},
    'article-0f8f00185abe2a5ec39cdbea': {
        'final': 'stage_journal:v1:c861a651a1613247f8a183e66c9a5efc623f4b9c0688754e4144f81260a10e78',
        'directory': 'b02cd84a90a79f447069324991f6fdeceb96e72a92f076d24dd50c63a3592036',
        'source': 'd20a63bcf5f3f0b94645f3b1065bc15f21352244a52f67218b2f2878b9e8862e',
        'candidate': '5bf7fa272b0d151242491677031e5e0b55ff77ace856b27c8a0e07c4d556bc3e'},
}


COMPLETION_AUTHORIZATION = 'owner-20261120-pair-budgeted-completion'
COMPLETION_ANSWER = '原因を採点不整合/実本文品質に分け確認し本文購入リンク修正、予算上限内でSlack承認待ちまで進める'


def _normalized(value):
    if isinstance(value, str):
        return ' '.join(value.split())
    if isinstance(value, list):
        return [_normalized(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalized(v) for k, v in value.items()}
    return value


def _completion_plan(proposed):
    plan = proposed.get('completionPlan', {})
    diagnosis = plan.get('diagnosis', {})
    _require(isinstance(diagnosis, dict) and all(isinstance(diagnosis.get(k), str)
             and diagnosis[k].strip() for k in ('scoringInconsistency', 'bodyQuality')),
             'completion_diagnosis_required')
    changes = plan.get('changes')
    _require(isinstance(changes, list) and changes and all(isinstance(c, dict)
             and c.get('target') in ('body', 'purchase_links', 'structure', 'wording', 'facts')
             and isinstance(c.get('change'), str) and len(c['change'].strip()) >= 10 for c in changes),
             'concrete_completion_changes_required')
    # Exclude labels/timestamps/diagnosis prose: they cannot mint a new attempt.
    brief = proposed.get('approvedWritingBrief')
    return fingerprint(_normalized({'brief': brief, 'changes': sorted(
        [{'target': c['target'], 'change': c['change']} for c in changes],
        key=lambda c: (c['target'], c['change']))})), fingerprint(_normalized(brief))


def _literal_candidate(plan, job, article, brief, candidate_sha, *, upper_binding=None):
    """Apply pinned deletions or an explicitly source-bound upper-editor candidate."""
    upper = plan.get('mode') == 'upper_editor_candidate'
    extra = {'mode', 'upperEditorReview'} if upper else set()
    _require(set(plan) - extra == {'jobId', 'sourceBinding', 'candidateArtifactSha256', 'articleSha256', 'replacements'}
             and plan.get('jobId') == job['id'] and plan.get('sourceBinding') == job['sourceBinding']
             and plan.get('candidateArtifactSha256') == candidate_sha
             and plan.get('articleSha256') == fingerprint(article), 'literal_candidate_binding_required')
    replacements = plan.get('replacements')
    _require(isinstance(replacements, list) and 0 < len(replacements) <= 64, 'literal_replacements_required')
    changed = copy.deepcopy(article)
    for item in replacements:
        _require(isinstance(item, dict) and set(item) == {'path', 'old', 'new', 'count'}
                 and isinstance(item.get('path'), str)
                 and re.fullmatch(r'article\.(?:content|faqs\.[0-4]\.(?:question|answer))', item['path'])
                 and isinstance(item.get('old'), str) and item['old']
                 and isinstance(item.get('new'), str) and item['new'] != item['old']
                 and type(item.get('count')) is int and 0 < item['count'] <= 100,
                 'bounded_literal_replacement_required')
        old, new = item['old'], item['new']
        start = old.find(new) if new else 0
        _require(upper or not new or (start >= 0 and (start == 0 or old[start - 1] in '\n。！？')
                 and (start + len(new) == len(old) or new[-1] in '\n。！？')),
                 'literal_new_claim_or_partial_sentence_forbidden')
        if item['path'] == 'article.content':
            target, key = changed, 'content'
        else:
            index, key = item['path'].split('.')[2:]
            _require(int(index) < len(changed.get('faqs', [])), 'literal_faq_index_required')
            target = changed['faqs'][int(index)]
        _require(isinstance(target.get(key), str) and target[key].count(old) == item['count'],
                 'literal_occurrence_count_mismatch')
        _require(not upper or (item['count'] == 1 and target[key] == old),
                 'upper_editor_whole_field_replacement_required')
        target[key] = target[key].replace(old, new)
    _require(article != changed, 'literal_candidate_must_change')
    before = '\n'.join([article['content']] + [f[k] for f in article.get('faqs', []) for k in ('question', 'answer')])
    after = '\n'.join([changed['content']] + [f[k] for f in changed.get('faqs', []) for k in ('question', 'answer')])
    if upper:
        _require(isinstance(upper_binding, dict) and plan.get('upperEditorReview') == dict(upper_binding,
                 reviewedBy='Astra', candidateArticleSha256=fingerprint(changed)),
                 'upper_editor_source_review_binding_required')
    for field in ('protected', 'requiredExpressions', 'facts', 'numbers'):
        _require(all(not isinstance(value, str) or value not in before or value in after
                     for value in brief.get(field, [])), 'literal_original_brief_conflict_requires_review')
    return changed


def _completion_baseline(root, job, records, receipts, proposed, proof, old_failed_key, literal_plan=None):
    job_id = job['id']
    plan_sha, brief_sha = _completion_plan(proposed)
    if literal_plan is not None:
        plan_sha = fingerprint({'completionPlan': plan_sha, 'literalPlan': literal_plan})
    _require(not any(r.get('jobId') == job_id and r.get('status') in ('in_flight', 'unknown')
                     for r in records.values()), 'completion_unknown_stage_requires_reconciliation')
    prefix = receipt_key(job_id, 'completion') + ':'
    previous_key = (job.get('error') or {}).get('ownerRecoveryReceipt')
    _require(previous_key == receipt_key(job_id, 'source_only')
             or isinstance(previous_key, str) and previous_key.startswith(prefix),
             'completion_previous_receipt_required')
    previous = receipts.get(previous_key, {})
    previous_phase = 'completion' if previous_key.startswith(prefix) else 'source_only'
    reference, answer, _ = _profile(previous_phase)
    _require(previous.get('jobId') == job_id and previous.get('attempts') == previous.get('maxAttempts') == 1
             and previous.get('status') == ('failed_known' if previous_phase == 'completion' else 'requires_reconciliation')
             and previous.get('failureType') == 'ValueError'
             and previous.get('ownerGrant') == {'reference': reference, 'answer': answer,
                 'jobId': job_id, 'manifestSha256': previous.get('manifestSha256')},
             'completion_known_previous_failure_required')
    for key, value in receipts.items():
        if key.startswith(prefix):
            _require(value.get('status') == 'failed_known', 'completion_unknown_claim_requires_reconciliation')
            _require(value.get('planSha256') != plan_sha
                     and (literal_plan is not None or value.get('briefSha256') != brief_sha),
                     'completion_same_plan_or_brief_forbidden')
    archive = root / 'manual-operations'
    if previous_phase == 'completion':
        previous_plan = previous.get('planSha256', '')
        _require(re.fullmatch(r'[0-9a-f]{64}', previous_plan) is not None
                 and previous_key == prefix + previous_plan, 'completion_previous_plan_binding')
        archive = archive / '20261120-pair-completion' / job_id / previous_plan
        namespace = 'owner_oneoff:' + reference + ':' + previous_plan + ':'
    else:
        archive = archive / '20261120-pair-source-only-recovery' / job_id
        namespace = 'owner_oneoff:' + reference + ':'
    prior_manifest, _ = _read(archive / 'manifest.json')
    _require(fingerprint(prior_manifest) == previous['manifestSha256']
             and prior_manifest.get('jobId') == job_id, 'previous_manifest_binding_required')
    prior_proposal, prior_sha = _read(prior_manifest['paths']['proposed'])
    _require(prior_sha == prior_manifest['sha256']['proposedCandidate'], 'previous_proposal_binding_required')
    _require(literal_plan is not None or fingerprint(_normalized(prior_proposal.get('approvedWritingBrief'))) != brief_sha,
             'completion_same_plan_or_brief_forbidden')
    pins = proof.get('historicalArtifacts', {})
    _require(isinstance(pins, dict) and set(pins) == {'directory', 'source', 'candidate'}
             and all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in pins.values()),
             'completion_historical_pins_required')
    final = records.get(old_failed_key, {})
    _require(final.get('stage') == namespace + 'final_review' and final.get('status') == 'failed'
             and final.get('attempts') == final.get('maxAttempts') == 1,
             'completion_current_failed_review_required')
    return dict(pins, final=old_failed_key), previous, namespace, plan_sha, brief_sha


def _profile(phase):
    _require(phase in ('original', 'source_only', 'completion'), 'fixed_grant_phase_required')
    if phase == 'completion':
        return COMPLETION_AUTHORIZATION, COMPLETION_ANSWER, JOBS
    if phase == 'source_only':
        _require(set(SOURCE_ONLY_JOBS) == set(JOBS), 'source_only_pins_required')
        return SOURCE_ONLY_AUTHORIZATION, SOURCE_ONLY_ANSWER, SOURCE_ONLY_JOBS
    return AUTHORIZATION, OWNER_ANSWER, JOBS


PROTOCOL_FILES = ('supplemental_pair_recovery.py', 'supplemental_review_recovery.py',
                  'runtime.py', 'models.py', 'quality.py', 'model_budget.py',
                  'catalog.py', 'apparel_identity.py')
LOADED_FILES = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                for n in PROTOCOL_FILES}


def _protocol():
    files = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
             for n in PROTOCOL_FILES}
    _require(files == LOADED_FILES, 'loaded_protocol_changed_restart_required')
    return files


def receipt_key(job_id, phase='original', *, plan_sha=None):
    reference, _, _ = _profile(phase)
    _require(job_id in JOBS, 'fixed_pair_job_required')
    key = 'supplemental_manual_recovery:v1:' + reference + ':' + job_id
    if plan_sha is not None:
        _require(phase == 'completion' and isinstance(plan_sha, str)
                 and re.fullmatch(r'[0-9a-f]{64}', plan_sha) is not None, 'completion_plan_digest_required')
        key += ':' + plan_sha
    return key


def _slot(job, snapshot, batch, jobs, now):
    result = resolve_batch(batch, snapshot,
        [j['theme'] for j in jobs if j.get('kind') != 'supplemental_article'], now)
    slot = next((s for s in result['slots'] if s['slot'] == JOBS[job['id']]['slot']), {})
    _require(slot.get('status') == 'ready' and slot.get('theme') == job['theme']
             and slot.get('sourceBinding') == job['sourceBinding'], 'current_source_binding_or_theme_changed')


def prepare(config_path, job_id, old_failed_key, proposed_path, proof_path, snapshot_path,
            fresh_research_path, *, now=None, phase='original', correction_path=None):
    """Read-only manifest; fresh evidence is separate from immutable old research."""
    _require(correction_path is None or phase == 'completion', 'literal_completion_only')
    now = now or datetime.now(JST)
    _require(now.utcoffset() is not None and now.astimezone(JST).date().isoformat() == OWNER_DATE,
             'owner_grant_date_required')
    _require(job_id in JOBS, 'fixed_pair_job_required')
    reference, _, phase_jobs = _profile(phase)
    pins = dict(JOBS[job_id], **phase_jobs[job_id])
    if phase != 'completion':
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
        prior_row = db.execute('SELECT value FROM meta WHERE key=?', (receipt_key(job_id),)).fetchone()
        receipts = {k: json.loads(v) for k, v in db.execute(
            "SELECT key,value FROM meta WHERE key LIKE 'supplemental_manual_recovery:v1:%'")}
        if phase == 'completion':
            pending = db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id=? AND status IN ('reserved','unknown')",
                                 (job_id,)).fetchone()
            _require(pending is None, 'completion_unknown_budget_requires_reconciliation')
    prior = json.loads(prior_row[0]) if prior_row else None
    if phase == 'source_only':
        _require(isinstance(prior, dict) and prior.get('status') == 'requires_reconciliation'
                 and prior.get('jobId') == job_id and prior.get('attempts') == prior.get('maxAttempts') == 1
                 and prior.get('failureType') == 'ValueError'
                 and prior.get('ownerGrant') == {'reference': AUTHORIZATION, 'answer': OWNER_ANSWER,
                     'jobId': job_id, 'manifestSha256': prior.get('manifestSha256')},
                 'previous_grant_failed_quality_required')
        prior_manifest, _ = _read(root / 'manual-operations' / '20261120-pair-recovery' / job_id / 'manifest.json')
        _require(fingerprint(prior_manifest) == prior['manifestSha256']
                 and prior_manifest.get('jobId') == job_id, 'previous_manifest_binding_required')
    job = next((j for j in jobs if j['id'] == job_id), {})
    completion_namespace = None
    if phase == 'completion':
        proposed, _ = _read(proposed_path)
        proof, _ = _read(proof_path)
        _require(job.get('id') == job_id, 'exact_failed_pair_job_required')
        literal_plan = _read(correction_path)[0] if correction_path is not None else None
        dynamic, prior, completion_namespace, plan_sha, brief_sha = _completion_baseline(
            root, job, records, receipts, proposed, proof, old_failed_key, literal_plan)
        pins = dict(JOBS[job_id], **dynamic)
    _require(job.get('kind') == 'supplemental_article' and job.get('batchId') == BATCH
             and job.get('batchSlot') == pins['slot'] and job.get('batchCallCap') == 96
             and job.get('week') == '2026-11-13' and job.get('stage') == 'error'
             and job.get('theme', {}).get('productIds') == [pins['product']]
             and job['theme'].get('slug') == pins['slug'] and job['theme'].get('categoryId') == 'wear'
             and all(job.get(k) is None for k in ('bundle', 'review', 'approval', 'publication'))
             and (job.get('error') or {}).get('reason') == 'final_review_failed', 'exact_failed_pair_job_required')
    if phase == 'source_only':
        _require(job['error'].get('ownerRecoveryReceipt') == receipt_key(job_id), 'previous_error_receipt_required')
    old_namespace = completion_namespace or ('owner_oneoff:' + AUTHORIZATION + ':' if phase == 'source_only' else '')
    final = records.get(old_failed_key, {})
    _require(final.get('stageKey') == old_failed_key and final.get('jobId') == job_id
             and final.get('stage') == old_namespace + 'final_review' and final.get('status') == 'failed'
             and final.get('attempts') == 1 and final.get('maxAttempts') == (2 if phase == 'original' else 1)
             and not final.get('successorKey'), 'exact_failed_review_required')
    old = {}
    for stage in ('draft', 'polish'):
        historical_stage = old_namespace + stage
        if stage == 'draft' and phase == 'completion':
            local = [r for r in records.values() if r.get('jobId') == job_id
                     and r.get('stage') == old_namespace + 'literal_correction']
            if local:
                historical_stage = old_namespace + 'literal_correction'
        found = [r for r in records.values() if r.get('jobId') == job_id
                 and r.get('stage') == historical_stage and r.get('status') == 'succeeded'
                 and (phase == 'original' or r.get('attempts') == r.get('maxAttempts') == 1)]
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
    result = {'schemaVersion': 1, 'status': 'held_for_owner_decision', 'executed': False,
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
    if phase == 'source_only':
        result.update(phase=phase, previousReceiptSha256=fingerprint(prior))
    if phase == 'completion':
        candidate_hashes, article_hashes = [], []
        for record in records.values():
            if (record.get('jobId') == job_id and record.get('status') == 'succeeded'
                    and (record.get('stage') == 'polish' or record.get('stage', '').endswith(':polish'))):
                output = _cached(record)
                candidate_hashes.append(fingerprint(_normalized(output['polished']['content'])))
                prefix = record['stage'][:-len('polish')]
                writers = [r for r in records.values() if r.get('jobId') == job_id
                           and r.get('status') == 'succeeded'
                           and r.get('stage') in (prefix + 'draft', prefix + 'literal_correction')]
                _require(len(writers) == 1, 'historical_candidate_writer_required')
                prior_article = _cached(writers[0])['article']
                article_hashes.append(fingerprint(_normalized({'content': output['polished']['content'],
                                                               'faqs': prior_article['faqs']})))
        result.update(status='ready_for_budgeted_completion', phase=phase, previousReceiptSha256=fingerprint(prior),
                      planSha256=plan_sha, briefSha256=brief_sha, historicalArtifacts=pins,
                      historicalCandidateBodyHashes=sorted(set(candidate_hashes)),
                      historicalCandidateArticleHashes=sorted(set(article_hashes)))
    if correction_path is not None:
        correction, correction_sha = _read(correction_path)
        # Preserve the original model writer/brief across successive local repairs.
        writer = old['draft']
        if writer['stage'].endswith(':literal_correction'):
            # Provenance is pinned in the prior manifest, not fabricated as model usage.
            previous_plan = prior['planSha256']
            previous_manifest, _ = _read(root / 'manual-operations' / '20261120-pair-completion'
                                          / job_id / previous_plan / 'manifest.json')
            provenance = previous_manifest['writerProvenance']
            writer = records.get(provenance['stageKey'], {})
            _require(fingerprint(writer) == provenance['recordSha256'], 'literal_writer_provenance_changed')
        _require(writer.get('jobId') == job_id and writer.get('status') == 'succeeded' and (writer.get('stage') == 'draft'
                 or writer.get('stage', '').endswith(':draft')), 'literal_original_writer_required')
        original_writer = _cached(writer)
        article = copy.deepcopy(source['bundle']['article'])
        article['content'] = candidate['candidate']['content']
        upper_binding = None
        if correction.get('mode') == 'upper_editor_candidate':
            upper_binding = {'writingBriefSha256': fingerprint(proposed['approvedWritingBrief']),
                             'freshResearchSha256': fresh_sha, 'sourceProofSha256': proof_sha}
            result['upperEditorBinding'] = upper_binding
        corrected = _literal_candidate(correction, job, article, original_writer['brief'], candidate_sha,
                                       upper_binding=upper_binding)
        result['paths']['correction'] = str(correction_path)
        result['sha256']['correction'] = correction_sha
        result['literalCorrection'] = {'articleSha256': fingerprint(corrected)}
        result['writerProvenance'] = {'stageKey': writer['stageKey'], 'recordSha256': fingerprint(writer),
                                      'briefSha256': fingerprint(original_writer['brief'])}
    return result


class _PairRuntime(Runtime):
    def __init__(self, rt, manifest, original):
        self.__dict__ = rt.__dict__.copy()
        self._manifest = copy.deepcopy(manifest)
        self._job_id = manifest['jobId']
        self._original = original
        self.models = copy.copy(rt.models)
        self.models.usage = []
        self.models.review_diagnostics = []
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
        if stage == 'draft' and self._manifest.get('literalCorrection'):
            return self._literal_draft(job, inputs)
        if stage == 'final_review':
            _require(all(inputs['dependencies']['qualityFlags'].values())
                     and inputs['dependencies']['structural'].get('passed') is True,
                     'independent_quality_gates_failed')
        if stage == 'final_review' and self._manifest.get('phase') == 'completion':
            article = inputs['bundle']['article']
            if self._manifest.get('literalCorrection'):
                _require(fingerprint(_normalized({'content': article['content'], 'faqs': article['faqs']}))
                         not in self._manifest['historicalCandidateArticleHashes'],
                         'completion_same_body_grader_reroll_forbidden')
            else:
                _require(fingerprint(_normalized(article['content']))
                         not in self._manifest['historicalCandidateBodyHashes'],
                         'completion_same_body_grader_reroll_forbidden')
        self._executed_stages.add(stage)
        reference, _, _ = _profile(self._manifest.get('phase', 'original'))
        namespace = 'owner_oneoff:' + reference + ':'
        if self._manifest.get('phase') == 'completion':
            namespace += self._manifest['planSha256'] + ':'
        namespace += stage
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

    def _literal_draft(self, job, inputs):
        manifest = self._manifest
        provenance = manifest['writerProvenance']
        with self.ledger._tx() as db:
            writer = json.loads(db.execute('SELECT value FROM meta WHERE key=?',
                                (provenance['stageKey'],)).fetchone()[0])
        _require(fingerprint(writer) == provenance['recordSha256'], 'literal_writer_provenance_changed')
        pins = manifest['historicalArtifacts']
        artifact = self.root / 'research' / 'artifacts' / self._job_id / pins['directory']
        source, source_sha = _read(artifact / 'source.json')
        candidate, candidate_sha = _read(artifact / 'candidate.json')
        correction, correction_sha = _read(manifest['paths']['correction'])
        _require(source_sha == pins['source'] and candidate_sha == pins['candidate']
                 and correction_sha == manifest['sha256']['correction'], 'literal_pinned_files_changed')
        original = _cached(writer)
        article = copy.deepcopy(source['bundle']['article'])
        article['content'] = candidate['candidate']['content']
        corrected = _literal_candidate(correction, job, article, original['brief'], candidate_sha,
                                       upper_binding=manifest.get('upperEditorBinding'))
        _require(fingerprint(corrected) == manifest['literalCorrection']['articleSha256'], 'literal_result_changed')
        gathered, _ = _read(self.root / 'research' / (self._job_id + '.json'))
        live = self._source_dependencies(gathered)
        expected = inputs['dependencies']['source']
        _require(all(live.get(k) == expected.get(k) for k in
                     ('products', 'catalog', 'references', 'images', 'checks', 'evidence')),
                 'literal_fresh_source_binding_changed')
        # Validate without a model invocation. Runtime attaches fresh verified
        # records normally, so stale source evidence never becomes new evidence.
        result = {'article': {k: copy.deepcopy(corrected[k]) for k in original['article']},
                  'brief': copy.deepcopy(original['brief'])}
        def operation():
            validated = self.models._validate_draft(result, job['theme'], gathered)
            _require(validated['article']['content'] == corrected['content']
                     and validated['article']['faqs'] == corrected['faqs']
                     and validated['brief'] == original['brief'], 'literal_validation_must_not_rewrite')
            _require(all(validated['article'].get(k) == job['theme'][k]
                         for k in ('productIds', 'slug', 'categoryId')), 'literal_identity_changed')
            return validated
        namespace = 'owner_oneoff:' + COMPLETION_AUTHORIZATION + ':' + manifest['planSha256'] + ':literal_correction'
        bound = {'writerProvenance': provenance, 'correctionSha256': correction_sha,
                 'sourceArtifactSha256': source_sha, 'candidateArtifactSha256': candidate_sha,
                 'correctedArticleSha256': fingerprint(corrected), 'freshInputs': inputs,
                 'ownerGrantManifestSha256': fingerprint(manifest),
                 'dependencies': inputs['dependencies'],
                 'schemaVersion': {'stage': 1, 'input': 'pinned-literal-plan', 'output': 'corrected-writer-candidate'}}
        self._executed_stages.add('draft')
        return self.stage_journal.run(self._job_id, namespace, bound, operation, max_attempts=1)


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


def _receipt(rt, job_id, *, phase='original', plan_sha=None, **fields):
    with rt.ledger._tx() as db:
        key = receipt_key(job_id, phase, plan_sha=plan_sha)
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        _require(row is not None, 'owner_pair_claim_missing')
        value = json.loads(row[0])
        value.update(fields)
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(value), key))
        rt.ledger._event(db, job_id, 'supplemental_owner_pair_result', fields)


def execute(runtime, manifest, *, owner_grant):
    job_id = manifest.get('jobId')
    phase = manifest.get('phase', 'original')
    reference, answer, phase_jobs = _profile(phase)
    _require(job_id in JOBS and owner_grant == {'reference': reference, 'answer': answer,
             'jobId': job_id, 'manifestSha256': fingerprint(manifest)}, 'exact_owner_grant_required')
    plan_sha = manifest.get('planSha256') if phase == 'completion' else None
    claim_key = receipt_key(job_id, phase, plan_sha=plan_sha)
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
            _require(db.execute('SELECT 1 FROM meta WHERE key=?', (claim_key,)).fetchone() is None,
                     'owner_pair_already_claimed_requires_reconciliation')
        p = manifest['paths']
        current = prepare(p['config'], job_id, manifest['oldFailedKey'], p['proposed'], p['proof'],
                          p['snapshot'], p['freshResearch'], phase=phase, correction_path=p.get('correction'))
        _require(current == manifest and not current['blockers'], 'pinned_manifest_changed_or_blocked')
        _require(runtime.model_budget.config == budget_config(config.get('modelBudget'))
                 and isinstance(runtime.models, Models) and runtime.models.budget is runtime.model_budget,
                 'real_unchanged_budgeted_models_required')
        routes = runtime._model_routes()
        _require(routes['draft']['requested'].startswith('claude-')
                 and routes['final_review']['requested'] == 'claude-sonnet-4-6'
                 and routes['polish']['requested'] == 'gemini-3.8-flash', 'authorized_model_routes_required')
        with runtime.ledger._tx() as db:
            _require(db.execute('SELECT 1 FROM meta WHERE key=?', (claim_key,)).fetchone() is None,
                     'owner_pair_already_claimed_requires_reconciliation')
            receipt = {'status': 'in_flight', 'jobId': job_id, 'attempts': 1, 'maxAttempts': 1,
                       'manifestSha256': fingerprint(manifest), 'ownerGrant': owner_grant, 'at': stamp()}
            if phase == 'completion':
                receipt.update(planSha256=plan_sha, briefSha256=manifest['briefSha256'])
            db.execute('INSERT INTO meta VALUES (?,?)', (claim_key, json.dumps(receipt)))
            runtime.ledger._event(db, job_id, 'supplemental_owner_pair_claimed', receipt)
        view = None
        try:
            archive = runtime.root / 'manual-operations' / ('20261120-pair-source-only-recovery' if phase == 'source_only' else '20261120-pair-recovery') / job_id
            if phase == 'completion':
                archive = runtime.root / 'manual-operations' / '20261120-pair-completion' / job_id / plan_sha
            _require(not archive.exists(), 'recovery_archive_already_exists')
            historical, _ = _read(runtime.root / 'research' / (job_id + '.json'))
            atomic(archive / 'original-research.json', historical)
            atomic(archive / 'manifest.json', manifest)
            if p.get('correction'):
                correction, digest = _read(p['correction'])
                _require(digest == manifest['sha256']['correction'], 'literal_pinned_files_changed')
                atomic(archive / 'correction-input.json', {'inputSha256': digest, 'plan': correction})
            artifact_pins = manifest['historicalArtifacts'] if phase == 'completion' else phase_jobs[job_id]
            artifact = runtime.root / 'research' / 'artifacts' / job_id / artifact_pins['directory']
            candidate, _ = _read(artifact / 'candidate.json')
            source, _ = _read(artifact / 'source.json')
            view = _PairRuntime(runtime, manifest, candidate['candidate'])
            context = view._context()
            job = view.ledger.get_job(job_id)
            _slot(job, context, view._supplemental_manifest(), view.ledger.list_jobs(), datetime.now(JST))
            proposed, _ = _read(p['proposed'])
            if phase in ('source_only', 'completion'):
                context['editorialRules'] += (
                    '\nOwner-approved source-only reconstruction. Write a new guide of 3000-5000 characters '
                    'using ONLY freshly gathered primary references and the upper-editor writing brief. '
                    'Preserve selected products, slug and category. Do not reconstruct legacy claims. '
                    'Main upper-editor approvedWritingBrief (not a new factual source):\n'
                    + json.dumps(proposed['approvedWritingBrief'], ensure_ascii=False))
                if phase == 'completion':
                    context['editorialRules'] += (
                        '\nPinned diagnosis and required corrections (editor instructions, not article text):\n'
                        + json.dumps(proposed['completionPlan'], ensure_ascii=False))
            else:
                context['editorialRules'] += ('\nOwner-approved body correction. Legacy claims are unverified; '
                    'use ONLY freshly gathered primary evidence, remove unsupported inferences everywhere. '
                    'Preserve guide format, products, slug and category. Legacy article:\n'
                    + json.dumps(source['bundle']['article'], ensure_ascii=False)
                    + '\nMain upper-editor approvedWritingBrief (not a new factual source):\n'
                    + json.dumps(proposed['approvedWritingBrief'], ensure_ascii=False))
            result = view._make_article(job, context)
            _require(view._executed_stages == {'draft', 'polish', 'final_review'}, 'incomplete_owner_pipeline')
            _receipt(runtime, job_id, phase=phase, plan_sha=plan_sha, status='completed', result=result)
            return result
        except BaseException as error:
            status = 'requires_reconciliation'
            if phase == 'completion' and isinstance(error, ValueError) and str(error) == 'final_review_failed' and view is not None:
                namespace = 'owner_oneoff:' + reference + ':' + plan_sha + ':final_review'
                records = view.stage_journal.status(job_id=job_id, stage=namespace)['records']
                if len(records) == 1 and records[0].get('status') == 'failed':
                    status = 'failed_known'
            _receipt(runtime, job_id, phase=phase, plan_sha=plan_sha, status=status, failureType=type(error).__name__)
            if isinstance(error, Exception):
                job = runtime.ledger.get_job(job_id)
                if job.get('approval') is None and job.get('publication') is None:
                    runtime.ledger.set_stage(job_id, 'error', {'reason': reason(error), 'at': stamp(),
                        'originalFailure': copy.deepcopy(manifest['originalError']),
                        'ownerRecoveryReceipt': claim_key})
            raise
        finally:
            if view is not None:
                view._save_usage()
