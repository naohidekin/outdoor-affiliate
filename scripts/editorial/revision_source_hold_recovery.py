"""One owner-granted retry of a revision stopped before every model stage."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from ledger import canonical, fingerprint, timestamp
from model_budget import _config
from revisions import validate_context
from stage_journal import StageUnknown


SOURCE_REASON = 'source_product_image_or_affiliate_verification_incomplete'
SCHEMA = 1
ACTION = 'retry_full_fresh_revision_source_once'
AUTHORIZED = {
    'revision-81d57bccd5f033c369187f4d': {
        'action': ACTION,
        'specHash': '04f89ebac8194b33a8ea3c05ee430027b76279fbe5b1f14823e6968b98372ae0',
        'ownerGrantHash': '7971cd7bfcbb89a599920c58d56b40ae99c57d595e6e7984e462bf26a581325e',
        'instructionReceiptSha256': '6caee83229eba9ae01f7ebebadff2d3b8fd0d4331a29fe9bae7974198454b602',
        'productionPeriod': '2026-11-27',
    },
}


def _require(value, reason):
    if not value:
        raise ValueError('revision_source_hold_recovery_' + reason)


def _read_secure(path, reason):
    path = Path(path)
    try:
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_mode & 0o777 == 0o600, reason)
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError('revision_source_hold_recovery_' + reason) from None
    _require(isinstance(value, dict), reason)
    return value, raw


def _write_once(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(not path.parent.is_symlink()
             and path.parent.stat().st_mode & 0o777 == 0o700,
             'receipt_directory_invalid')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise ValueError('revision_source_hold_recovery_already_claimed') from error
    raw = (canonical(value) + '\n').encode('utf-8')
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _archive_exact(path, raw):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(not path.parent.is_symlink()
             and path.parent.stat().st_mode & 0o777 == 0o700,
             'source_archive_directory_invalid')
    if path.exists() or path.is_symlink():
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_mode & 0o777 == 0o600
                 and path.read_bytes() == raw,
                 'source_archive_conflict')
        return
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise ValueError('revision_source_hold_recovery_source_archive_conflict') from error
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _failed_source(value, product_ids):
    checks = value.get('checks')
    evidence = (value.get('evidence') or {}).get('products')
    _require(checks == {'facts': True, 'images': False, 'affiliate': True},
             'failure_scope_changed')
    _require(value.get('productIds') == product_ids
             and isinstance(evidence, list) and len(evidence) == len(product_ids)
             and len(product_ids) >= 1,
             'failure_products_changed')
    rows = {row.get('productId'): row for row in evidence if isinstance(row, dict)}
    _require(set(rows) == set(product_ids)
             and all(rows[pid].get('facts') is True
                     and rows[pid].get('affiliate') is True for pid in product_ids)
             and sum(rows[pid].get('images') is not True for pid in product_ids) == 1,
             'failure_scope_changed')
    return [{'productId': pid, 'images': rows[pid].get('images') is True}
            for pid in product_ids]


def _eligibility(runtime, id, expected_spec_hash, owner_grant,
                 expected_current_period, now):
    runtime._require_running()
    now = timestamp(now)
    authorized = AUTHORIZED.get(id)
    _require(isinstance(authorized, dict) and authorized.get('action') == ACTION,
             'scope_not_authorized')
    grant = runtime.ledger.validate_existing_improvement_owner_grant(owner_grant)
    _require(fingerprint(grant) == authorized.get('ownerGrantHash')
             and grant.get('instructionReceiptSha256')
                 == authorized.get('instructionReceiptSha256'),
             'owner_grant_not_authorized')
    job = runtime.ledger.get_job(id)
    _require(job.get('kind') == 'article_revision' and job.get('stage') == 'error'
             and (job.get('error') or {}).get('reason') == SOURCE_REASON
             and all(job.get(key) is None for key in
                     ('bundle', 'revision', 'review', 'astraReview', 'approval',
                      'publication', 'social')),
             'job_state_changed')
    binding = validate_context(job.get('revisionContext'))
    spec_hash = fingerprint(binding)
    _require(expected_spec_hash == spec_hash == authorized.get('specHash')
             and job.get('theme') == {
                 'slug': binding['baseArticle']['slug'],
                 'title': binding['baseArticle']['title'],
                 'categoryId': binding['baseArticle']['categoryId'],
                 'productIds': binding['targetProductIds']},
             'spec_changed')
    budget_period = runtime.model_budget._period_key(now)
    _require(expected_current_period == authorized.get('productionPeriod')
             and budget_period == expected_current_period,
             'period_changed')
    limits = _config(runtime.config.get('modelBudget'))
    _require(limits['article']['calls'] == 32 and limits['period']['calls'] == 128,
             'budget_caps_changed')
    budget_id = runtime._budget_article_id(id)
    _require(job.get('budgetArticleId', budget_id) == budget_id,
             'budget_binding_changed')
    marker_path = runtime.root / 'revision-production-attempts' / (id + '.json')
    marker, marker_raw = _read_secure(marker_path, 'production_marker_invalid')
    _require(marker.get('status') == 'blocked' and marker.get('reason') == SOURCE_REASON,
             'production_marker_changed')
    source_path = runtime.root / 'research' / (id + '.json')
    source, source_raw = _read_secure(source_path, 'failed_source_missing')
    failed_images = _failed_source(source, list(binding['targetProductIds']))
    records = runtime.stage_journal.status(job_id=id)['records']
    _require(records == [], 'model_stage_already_started')
    with sqlite3.connect(runtime.ledger.db_path) as db:
        _require(not db.execute('SELECT 1 FROM requests WHERE job_id=?', (id,)).fetchone()
                 and not db.execute('SELECT 1 FROM effects WHERE job_id=?', (id,)).fetchone()
                 and not db.execute(
                     'SELECT 1 FROM model_budget_reservations WHERE article_id IN (?,?)',
                     (id, budget_id)).fetchone(),
                 'side_effect_or_model_attempt_exists')
    attempt_path = runtime.root / 'revision-source-hold-recovery-attempts' / (id + '.json')
    result_path = runtime.root / 'revision-source-hold-recovery-results' / (id + '.json')
    _require(not attempt_path.exists() and not attempt_path.is_symlink()
             and not result_path.exists() and not result_path.is_symlink(),
             'already_claimed')
    source_sha = hashlib.sha256(source_raw).hexdigest()
    archive_path = (runtime.root / 'revision-source-hold-recovery-sources' / id /
                    (source_sha + '.json'))
    attempt = {
        'schemaVersion': SCHEMA, 'kind': 'revision_source_hold_recovery',
        'action': ACTION, 'status': 'claimed', 'jobId': id,
        'legacyJobWeek': job['week'], 'productionPeriod': budget_period,
        'specHash': spec_hash, 'budgetArticleId': budget_id,
        'budgetCaps': {'articleCalls': 32, 'periodCalls': 128},
        'ownerGrant': grant,
        'productionMarkerSha256': hashlib.sha256(marker_raw).hexdigest(),
        'failedSourceSha256': source_sha,
        'failedSourceArchive': str(archive_path.relative_to(runtime.root)),
        'failedImageProof': failed_images, 'claimedAt': now.isoformat(),
    }
    return job, attempt_path, result_path, archive_path, source_raw, attempt


def execute(runtime, id, expected_spec_hash, owner_grant, *,
            expected_current_period, now=None):
    """Caller holds runtime.flock; claim once, then use the unchanged pipeline."""
    job, attempt_path, result_path, archive_path, source_raw, attempt = _eligibility(
        runtime, id, expected_spec_hash, owner_grant,
        expected_current_period, now)
    _archive_exact(archive_path, source_raw)
    attempt_hash = _write_once(attempt_path, attempt)
    try:
        delivery = runtime._make_article(job, runtime._context())
        current = runtime.ledger.get_job(id)
        result = {
            'schemaVersion': SCHEMA, 'kind': 'revision_source_hold_recovery_result',
            'action': ACTION, 'status': 'completed', 'jobId': id,
            'attemptReceiptSha256': attempt_hash,
            'revision': current.get('revision'), 'stage': current.get('stage'),
            'completedAt': timestamp().isoformat(),
        }
        _write_once(result_path, result)
        return {'status': 'completed', 'id': id,
                'deliveryStatus': delivery.get('status') if isinstance(delivery, dict) else None,
                'revision': current.get('revision')}
    except Exception as error:
        from runtime import reason
        status = 'unknown' if isinstance(error, StageUnknown) else 'blocked'
        detail = {'reason': reason(error), 'at': timestamp().isoformat(),
                  'originalFailure': copy.deepcopy(job['error']),
                  'sourceHoldRecovery': status}
        runtime.ledger.set_stage(id, 'error', detail)
        _write_once(result_path, {
            'schemaVersion': SCHEMA, 'kind': 'revision_source_hold_recovery_result',
            'action': ACTION, 'status': status, 'jobId': id,
            'attemptReceiptSha256': attempt_hash,
            'reason': reason(error), 'completedAt': timestamp().isoformat(),
        })
        return {'status': 'attention', 'id': id, 'reason': reason(error),
                'outcome': status}
    finally:
        runtime._save_usage()
