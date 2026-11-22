"""One explicit metadata-only continuation; never rerun paid writing stages."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sqlite3

from ledger import fingerprint
from purchase_evidence import validate_purchase_evidence
from quality import inspect_bundle, inspect_polish
from revisions import validate_context, validate_revision_bundle
from stage_journal import _hash

JST = timezone(timedelta(hours=9))
JOB = 'revision-752f932fa6927ba5852ada4e'
SOURCE = '13b878b88e3694851e4e5998ba209dd29c8ea2b4185c1c1c8b0183709ce28f9d'
DRAFT = 'stage_journal:v1:752fa2ec1cdd38778e9b35bede8dcd08ad2b45b19d2f11c0974d27edc77e0a7c'
DRAFT_SHA = '9530a44f21bac85e391af29a67a4ade19f4d42a8b58d794abdf11e9621f99335'
POLISH = 'stage_journal:v1:6f7d266dd831ce1d096cccbeb31db4b05b4816eca7127fc8c03fb0d2cbe34953'
POLISH_SHA = '8202f81cf1f2efa5ca4ee2cc7178bf0a4b2b30a3aed02ce2a4fe80ece49e740b'
ERROR = 'article_structure_or_affiliate_failed'
FAILURE = 'purchase: fp-003: missing amazon; remove product or provide explicit NA evidence'


def require(ok, reason):
    if not ok:
        raise ValueError('revision_purchase_na_' + reason)


def read(path):
    require(not path.is_symlink() and path.is_file(), 'artifact_missing_or_symlink')
    return json.loads(path.read_text())


def resume(runtime, id, evidence, operator_reference):
    """Caller holds runtime.flock. Any claimed continuation is single-use."""
    runtime._require_running()
    require(id == JOB and isinstance(operator_reference, str) and bool(operator_reference.strip()), 'scope')
    job = runtime.ledger.get_job(id)
    require(job.get('kind') == 'article_revision' and job.get('stage') == 'error'
            and (job.get('error') or {}).get('reason') == ERROR
            and all(job.get(k) is None for k in ('bundle', 'review', 'approval', 'publication')), 'job_state')
    binding = validate_context(job.get('revisionContext'))
    require(job['theme']['slug'] == binding['baseArticle']['slug']
            and job['theme']['productIds'] == binding['targetProductIds'], 'theme')
    receipt_path = runtime.root / 'revision-purchase-na-resumes' / (id + '.json')
    require(receipt_path.parent.resolve() == runtime.root.resolve() / 'revision-purchase-na-resumes', 'receipt_path')
    require(not receipt_path.exists() and not receipt_path.is_symlink(), 'already_claimed')
    with sqlite3.connect(runtime.ledger.db_path) as db:
        records = [json.loads(row[0]) for row in db.execute(
            "SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
        records = [r for r in records if r.get('jobId') == id]
        managers = db.execute("SELECT value FROM meta WHERE key LIKE 'editorial_manager:%'").fetchall()
        require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')", (id,)).fetchone()
                and not db.execute('SELECT 1 FROM requests WHERE job_id=?', (id,)).fetchone()
                and not db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id IN (?,?) "
                                   "AND status IN ('reserved','in_flight','unknown')",
                                   (id, runtime._budget_article_id(id))).fetchone(), 'unresolved')
    require(not any(runtime._revision_manager_blocks(row[0], job) for row in managers), 'manager')
    require(len(records) == 3 and not any(r.get('stage') == 'final_review'
            or r.get('status') in ('in_flight', 'unknown') for r in records), 'stage_scope')
    draft = next((r for r in records if r.get('stageKey') == DRAFT), {})
    polish = next((r for r in records if r.get('stageKey') == POLISH), {})
    parent = next((r for r in records if r.get('stageKey') == draft.get('predecessorKey')), {})
    require(parent.get('stage') == 'draft' and parent.get('status') == 'failed'
            and parent.get('attempts') == 1 and parent.get('maxAttempts') == 2
            and parent.get('successorKey') == DRAFT and not parent.get('predecessorKey'), 'lineage')
    for record, stage, attempts, sha in ((draft, 'draft', 2, DRAFT_SHA), (polish, 'polish', 1, POLISH_SHA)):
        require(record.get('stage') == stage and record.get('status') == 'succeeded'
                and record.get('attempts') == attempts and record.get('maxAttempts') == 2
                and not record.get('successorKey') and record.get('outputHash') == sha
                and _hash(record.get('output')) == sha, 'cached_output')
    require(draft.get('inheritedAttempts') == 1 and not polish.get('predecessorKey'), 'cached_lineage')
    production_marker = runtime.root / 'revision-production-attempts' / (id + '.json')
    retry_marker = (runtime.root / 'revision-stage-retries' / id /
                    (hashlib.sha256(parent['stageKey'].encode()).hexdigest() + '.json'))
    production, retry = read(production_marker), read(retry_marker)
    require(production.get('status') == 'blocked'
            and production.get('reason') == 'Article length outside existing SKILL limits'
            and retry.get('status') == 'blocked' and retry.get('reason') == ERROR
            and retry.get('stage') == 'draft' and retry.get('inputKey') == parent['stageKey'], 'failure_markers')
    artifacts = runtime.root / 'research' / 'artifacts' / id / SOURCE
    require(artifacts.resolve() == runtime.root.resolve() / 'research' / 'artifacts' / id / SOURCE, 'artifact_path')
    source = read(artifacts / 'source.json')['bundle']
    polished = read(artifacts / 'candidate.json')['candidate']
    require(fingerprint(source) == SOURCE and polished == polish['output']['polished']
            and source.get('revisionContext') == binding
            and source['article']['content'] == draft['output']['article']['content'], 'source_binding')
    require(inspect_polish(source['article']['content'], polished['content']) == polish['output']['preservation'],
            'preservation_binding')
    require(polish['output']['preservation'].get('passed') is True, 'preservation')
    bundle = copy.deepcopy(source)
    bundle['article']['content'] = polished['content']
    require(inspect_bundle({k: v for k, v in bundle.items() if k != 'revisionContext'})['failures'] == [FAILURE],
            'sole_known_failure')
    context = runtime._wise_context(runtime._context())
    base = binding['baseArticle']
    live = next((a for a in context.get('revisionArticles', context.get('articles', [])) if a.get('id') == base['id']), None)
    require(fingerprint(live) == binding['baseHash'], 'article_baseline')
    products = {p['id']: p for p in context['products']}
    require(all(products.get(p['id']) == p for p in binding['baseProducts']), 'product_baseline')
    fresh = runtime.catalog.gather_revision(job['theme'], context, binding)
    require(all(fresh.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate'))
            and not fresh.get('blocked'), 'fresh_source')
    for field in ('products', 'images', 'references'):
        require(runtime._source_dependencies({field: fresh.get(field)})
                == runtime._source_dependencies({field: source.get(field)}), 'fresh_' + field)
    detail = next((p for p in fresh.get('evidence', {}).get('products', []) if p.get('productId') == 'fp-003'), {})
    product = next((p for p in fresh['products'] if p['id'] == 'fp-003'), {})
    require(product.get('amazonUrl') in (None, '') and any(d.get('channel') == 'rakuten'
            and d.get('verified') is True and d.get('url') == product.get('affiliateUrl')
            for d in detail.get('destinations', [])), 'verified_alternative')
    now = datetime.now(JST)
    bundle = validate_purchase_evidence(bundle, evidence, now)
    require([(e['productId'], e['channel']) for e in evidence] == [('fp-003', 'amazon')], 'na_scope')
    validate_revision_bundle(job, bundle, require_presentation=False)
    require(inspect_bundle({k: v for k, v in bundle.items() if k != 'revisionContext'})['passed'], 'structure')
    receipt = dict(kind='metadata_only_revalidation', status='in_flight', jobId=id,
                   operatorReference=operator_reference, sourceHash=SOURCE,
                   successfulStages=[dict(stage=r['stage'], stageKey=r['stageKey'], outputHash=r['outputHash'],
                                          attempts=r['attempts'], maxAttempts=r['maxAttempts']) for r in (draft, polish)],
                   oldFailure=copy.deepcopy(job['error']), freshProofSha256=fingerprint(fresh),
                   validatedBundleSha256=fingerprint(bundle),
                   freshProof=copy.deepcopy(fresh),
                   originalMarkersSha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in (production_marker, retry_marker)},
                   purchaseEvidence=copy.deepcopy(evidence), checkedAt=now.isoformat())
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(receipt, stream, ensure_ascii=False)
    from runtime import atomic
    try:
        result = runtime._finish_article_review(job, context, fresh, bundle, source,
            polish['output']['preservation'], polished, runtime._source_dependencies(fresh))
    except Exception:
        atomic(receipt_path, dict(receipt, status='requires_reconciliation'))
        raise
    finally:
        runtime._save_usage()
    atomic(receipt_path, dict(receipt, status='completed'))
    return result
