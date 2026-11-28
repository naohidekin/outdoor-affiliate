"""One prepared-source continuation for the exact amended burner revision."""
import copy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from ledger import canonical, fingerprint, timestamp
from revisions import validate_context
from revision_catalog_amendment import ALIASES, BUDGET_CAPS
from stage_journal import StageUnknown


JOB = 'revision-81d57bccd5f033c369187f4d'
SPEC = '60a38e7aaa9642373f102dbdda84669c62c6bd28f17ab079d594c07d15990a3a'
FAILED_SOURCE_SHA256 = '0224c73bdeed2aeae99b196323108b8a2fd8ce2ef7e2287a040284e078684880'
TARGET = 'rakuten-brave-6-4953571093208'
OWNER_GRANT = '7971cd7bfcbb89a599920c58d56b40ae99c57d595e6e7984e462bf26a581325e'
OWNER_RECEIPT = '6caee83229eba9ae01f7ebebadff2d3b8fd0d4331a29fe9bae7974198454b602'
PERIOD = '2026-11-27'
SOURCE_REASON = 'source_product_image_or_affiliate_verification_incomplete'
ACTION = 'resume_exact_revision_with_prepared_source_once'
TTL = timedelta(hours=6)
GATHERED_FIELDS = ('theme', 'productIds', 'checks', 'evidence', 'catalog', 'products',
                   'references', 'images', 'existingArticles', 'categories',
                   'merchantClicks', 'blocked')
_TOKEN = object()


def _require(value, reason):
    if not value:
        raise ValueError('revision_prepared_source_resume_' + reason)


def _read(path, reason):
    path = Path(path)
    try:
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_mode & 0o777 == 0o600, reason)
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError('revision_prepared_source_resume_' + reason) from None
    _require(isinstance(value, dict), reason)
    return value, raw


def _write_once(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(not path.parent.is_symlink()
             and path.parent.stat().st_mode & 0o777 == 0o700, 'receipt_directory')
    raw = (canonical(value) + '\n').encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
    except OSError as error:
        raise ValueError('revision_prepared_source_resume_already_claimed') from error
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _archive(path, raw):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(not path.parent.is_symlink()
             and path.parent.stat().st_mode & 0o777 == 0o700, 'archive_directory')
    if path.exists() or path.is_symlink():
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_mode & 0o777 == 0o600
                 and path.read_bytes() == raw, 'archive_conflict')
        return
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
    except OSError as error:
        raise ValueError('revision_prepared_source_resume_archive_conflict') from error
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _checked(value, now, reason):
    try:
        checked = timestamp(value)
    except (TypeError, ValueError):
        raise ValueError('revision_prepared_source_resume_' + reason) from None
    _require(checked <= now < checked + TTL, reason)
    return checked


def _exact_rows(db, job_id, budget_id):
    cursor = db.execute(
        'SELECT * FROM model_budget_reservations WHERE article_id IN (?,?) '
        'ORDER BY reservation_id', (job_id, budget_id))
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, values)) for values in cursor.fetchall()]
    _require(not any(row['article_id'] == job_id for row in rows), 'job_model_usage')
    aliases = [row for row in rows if row['article_id'] == budget_id]
    actual = [{'reservationId': row['reservation_id'], 'dataHash': fingerprint(row)}
              for row in aliases]
    _require(actual == ALIASES and {row['stage'] for row in aliases}
             == {'draft', 'polish', 'final_review'}
             and all(row['status'] == 'imported' for row in aliases), 'budget_aliases')


def _source_rows(source, context, now):
    ids = context['targetProductIds']
    details = (source.get('evidence') or {}).get('products')
    _require(source.get('productIds') == ids
             and source.get('products') == context['candidateProducts']
             and source.get('catalog') == context['candidateProducts']
             and isinstance(details, list)
             and [row.get('productId') for row in details if isinstance(row, dict)] == ids,
             'failed_source_binding')
    _require(source.get('checks') == {'facts': True, 'images': False, 'affiliate': True}
             and source.get('blocked') is True, 'failed_source_scope')
    expires = []
    for row in details:
        if row['productId'] == TARGET:
            try:
                checked = timestamp(row.get('checkedAt'))
            except (TypeError, ValueError):
                raise ValueError('revision_prepared_source_resume_target_old_timestamp') from None
            _require(checked <= now, 'target_old_timestamp')
        else:
            checked = _checked(row.get('checkedAt'), now, 'reused_source_stale')
            expires.append(checked + TTL)
        _require(all(claim.get('verified') is True
                     and claim.get('checkedAt') == row.get('checkedAt')
                     for claim in row.get('claims', []))
                 and all(destination.get('verified') is True
                     and destination.get('checkedAt') == row.get('checkedAt')
                     for destination in row.get('destinations', [])),
                 'source_nested_proof')
        if row['productId'] == TARGET:
            _require(row.get('facts') is True and row.get('affiliate') is True
                     and row.get('images') is not True, 'target_old_failure')
        else:
            _require(all(row.get(key) is True for key in ('facts', 'images', 'affiliate')),
                     'reused_source_incomplete')
    _require(sum(row.get('images') is not True for row in details) == 1,
             'failed_source_scope')
    by_id = {row['productId']: row for row in details}
    references = source.get('references')
    images = source.get('images')
    _require(isinstance(references, list) and isinstance(images, list), 'source_proof_shape')
    for product_id in ids:
        refs = [row for row in references if isinstance(row, dict)
                and row.get('productId') == product_id]
        pics = [row for row in images if isinstance(row, dict)
                and row.get('productId') == product_id]
        _require(refs and all(row.get('checkedAt') == by_id[product_id]['checkedAt']
                             for row in refs), 'source_reference_proof')
        if product_id != TARGET:
            _require(pics and all(row.get('verified') is True
                                  and row.get('checkedAt') == by_id[product_id]['checkedAt']
                                  for row in pics), 'source_image_proof')
    return details, min(expires)


def _target_source(source, product, failed_target, now):
    details = (source.get('evidence') or {}).get('products')
    detail = details[0] if isinstance(details, list) and len(details) == 1 else {}
    claims = detail.get('claims')
    destinations = detail.get('destinations')
    required_destinations = {
        channel: product[field] for channel, field in (
            ('rakuten', 'affiliateUrl'), ('amazon', 'amazonUrl'), ('yahoo', 'yahooUrl'))
        if product.get(field)
    }
    _require(source.get('productIds') == [TARGET]
             and source.get('products') == source.get('catalog') == [product]
             and source.get('checks') == {'facts': True, 'images': True, 'affiliate': True}
             and source.get('blocked') is False
             and isinstance(details, list) and len(details) == 1
             and detail.get('productId') == TARGET
             and all(detail.get(key) is True for key in ('facts', 'images', 'affiliate'))
             and isinstance(claims, list) and bool(claims)
             and all(claim.get('verified') is True
                     and claim.get('checkedAt') == detail.get('checkedAt')
                     for claim in claims)
             and isinstance(destinations, list) and bool(destinations)
             and all(destination.get('verified') is True
                     and destination.get('checkedAt') == detail.get('checkedAt')
                     for destination in destinations)
             and {destination.get('channel'): destination.get('url')
                  for destination in destinations} == required_destinations,
             'target_not_strictly_verified')
    checked = _checked(detail.get('checkedAt'), now, 'target_source_stale')
    _require(checked > timestamp(failed_target.get('checkedAt')), 'target_not_fresh_retry')
    for key in ('references', 'images'):
        rows = source.get(key)
        _require(isinstance(rows, list) and rows
                 and all(isinstance(row, dict) and row.get('productId') == TARGET
                         and row.get('checkedAt') == detail['checkedAt'] for row in rows),
                 'target_' + key)
    _require(any(image.get('verified') is True for image in source['images']),
             'target_image_not_positive')
    return detail, checked + TTL


def _replace(rows, target_rows):
    first = next((index for index, row in enumerate(rows)
                  if isinstance(row, dict) and row.get('productId') == TARGET), len(rows))
    kept = [copy.deepcopy(row) for row in rows
            if not isinstance(row, dict) or row.get('productId') != TARGET]
    first = min(first, len(kept))
    return kept[:first] + copy.deepcopy(target_rows) + kept[first:]


class _PreparedSource:
    def __init__(self, token, manifest, source):
        _require(token is _TOKEN, 'capability')
        self.manifest = copy.deepcopy(manifest)
        self.source = copy.deepcopy(source)
        self.used = False


def _scope(runtime, context, binding):
    return {
        'baseArticle': copy.deepcopy(binding['baseArticle']),
        'baseProducts': copy.deepcopy(binding['baseProducts']),
        'candidateProducts': copy.deepcopy(binding['candidateProducts']),
        'wisePolicy': copy.deepcopy(context.get('wisePolicy')),
        'editorialRules': copy.deepcopy(context.get('editorialRules')),
        'modelRoutes': runtime._model_routes(),
    }


def _validate_live(context, binding):
    article = next((row for row in context.get('revisionArticles', context.get('articles', []))
                    if row.get('id') == binding['baseArticle']['id']), None)
    products = {row['id']: row for row in context.get('products', [])}
    _require(article is not None and fingerprint(article) == binding['baseHash']
             and all(products.get(row['id']) == row for row in binding['baseProducts']),
             'live_binding')


def _base_eligibility(runtime, owner_grant, now):
    runtime._require_running()
    now = timestamp(now)
    grant = runtime.ledger.validate_existing_improvement_owner_grant(owner_grant)
    _require(fingerprint(grant) == OWNER_GRANT
             and grant.get('instructionReceiptSha256') == OWNER_RECEIPT, 'owner_grant')
    job = runtime.ledger.get_job(JOB)
    context = validate_context(job.get('revisionContext'))
    _require(fingerprint(context) == SPEC and len(context['targetProductIds']) == 11
             and TARGET in context['targetProductIds'], 'spec')
    error = job.get('error') or {}
    _require(job.get('kind') == 'article_revision' and job.get('stage') == 'error'
             and error.get('reason') == SOURCE_REASON
             and error.get('catalogAmendmentRecovery') == 'catalog_amendment_blocked'
             and all(job.get(key) is None for key in ('bundle', 'revision', 'review',
                 'astraReview', 'approval', 'publication', 'social')), 'job_state')
    _require(runtime.model_budget._period_key(now) == PERIOD, 'period')
    limits = runtime.model_budget.config
    _require(all(limits.get(scope, {}).get(field) == value
                 for scope, values in BUDGET_CAPS.items() for field, value in values.items()),
             'budget_caps')
    budget_id = runtime._budget_article_id(JOB)
    _require(job.get('budgetArticleId', budget_id) == budget_id, 'budget_binding')
    _require(runtime.stage_journal.status(job_id=JOB)['records'] == [], 'stage_started')
    with sqlite3.connect(runtime.ledger.db_path) as db:
        _require(not db.execute('SELECT 1 FROM requests WHERE job_id=?', (JOB,)).fetchone()
                 and not db.execute('SELECT 1 FROM effects WHERE job_id=?', (JOB,)).fetchone(),
                 'side_effect')
        _exact_rows(db, JOB, budget_id)

    root = runtime.root
    source, source_raw = _read(root / 'research' / (JOB + '.json'), 'failed_source')
    _require(hashlib.sha256(source_raw).hexdigest() == FAILED_SOURCE_SHA256,
             'failed_source_sha')
    details, expiry = _source_rows(source, context, now)
    failed_target = next(row for row in details if row['productId'] == TARGET)
    product = context['candidateProducts'][context['targetProductIds'].index(TARGET)]

    amendment, amendment_raw = _read(
        root / 'revision-catalog-amendment-attempts' / (JOB + '.json'), 'amendment_claim')
    result, result_raw = _read(
        root / 'revision-catalog-amendment-results' / (JOB + '.json'), 'amendment_result')
    amendment_sha = hashlib.sha256(amendment_raw).hexdigest()
    _require(amendment.get('kind') == 'revision_catalog_amendment_v1'
             and amendment.get('jobId') == JOB and amendment.get('newSpecHash') == SPEC
             and amendment.get('ownerGrantSha256') == OWNER_GRANT, 'amendment_claim')
    _require(result.get('kind') == 'revision_catalog_amendment_result_v1'
             and result.get('status') == 'blocked' and result.get('jobId') == JOB
             and result.get('reason') == SOURCE_REASON
             and result.get('attemptReceiptSha256') == amendment_sha, 'amendment_result')

    paths = (root / 'revision-prepared-source-attempts' / (JOB + '.json'),
             root / 'revision-prepared-source-results' / (JOB + '.json'))
    _require(all(not path.exists() and not path.is_symlink() for path in paths), 'already_claimed')
    return (job, context, grant, source, source_raw, details, failed_target,
            product, expiry, paths, amendment_raw, result_raw)


def collect_target(runtime, owner_grant, *, now=None):
    """Fetch only SOD-320 through the ordinary Catalog verifier and save once."""
    now = timestamp(now)
    (job, context, _, _, _, _, failed_target, product, _, _, _, _) = (
        _base_eligibility(runtime, owner_grant, now))
    path = runtime.root / 'revision-prepared-source-targets' / (JOB + '.json')
    _require(not path.exists() and not path.is_symlink(), 'target_already_collected')
    live = runtime._wise_context(runtime._context())
    _validate_live(live, context)
    theme = copy.deepcopy(job['theme'])
    theme['productIds'] = [TARGET]
    target_source = runtime.catalog.gather(
        theme, dict(live, products=copy.deepcopy(context['candidateProducts'])))
    finished = timestamp(runtime.clock() if callable(getattr(runtime, 'clock', None)) else None)
    _target_source(target_source, product, failed_target, finished)
    wrapper = {
        'schemaVersion': 1, 'kind': 'prepared_revision_target_source_v1',
        'jobId': JOB, 'specHash': SPEC, 'targetProductId': TARGET,
        'contextScopeFingerprint': fingerprint(_scope(runtime, live, context)),
        'sourceFingerprint': fingerprint(target_source), 'collectedAt': finished.isoformat(),
        'source': copy.deepcopy(target_source),
    }
    digest = _write_once(path, wrapper)
    return {'status': 'verified', 'jobId': JOB, 'targetProductId': TARGET,
            'targetArtifactSha256': digest,
            'sourceFingerprint': wrapper['sourceFingerprint']}


def _eligibility(runtime, owner_grant, now):
    now = timestamp(now)
    (job, context, grant, source, source_raw, details, failed_target, product,
     expiry, paths, amendment_raw, result_raw) = _base_eligibility(
        runtime, owner_grant, now)
    target_wrapper, target_raw = _read(
        runtime.root / 'revision-prepared-source-targets' / (JOB + '.json'),
        'target_artifact')
    target_source = target_wrapper.get('source')
    _require(target_wrapper.get('kind') == 'prepared_revision_target_source_v1'
             and target_wrapper.get('jobId') == JOB
             and target_wrapper.get('specHash') == SPEC
             and target_wrapper.get('targetProductId') == TARGET
             and target_wrapper.get('sourceFingerprint') == fingerprint(target_source),
             'target_artifact')
    live = runtime._wise_context(runtime._context())
    _validate_live(live, context)
    _require(target_wrapper.get('contextScopeFingerprint')
             == fingerprint(_scope(runtime, live, context)), 'context_scope_drift')
    target_detail, target_expiry = _target_source(
        target_source, product, failed_target, now)
    expiry = min(expiry, target_expiry)
    amendment_sha = hashlib.sha256(amendment_raw).hexdigest()

    _require(all(key in source for key in GATHERED_FIELDS), 'failed_source_schema')
    merged = {key: copy.deepcopy(source[key]) for key in GATHERED_FIELDS}
    merged['evidence']['products'] = [copy.deepcopy(target_detail) if row['productId'] == TARGET
                                      else copy.deepcopy(row) for row in details]
    merged['references'] = _replace(source.get('references', []), target_source['references'])
    merged['images'] = _replace(source.get('images', []), target_source['images'])
    merged['checks'] = {key: all(row.get(key) is True
        for row in merged['evidence']['products']) for key in ('facts', 'images', 'affiliate')}
    merged['blocked'] = not all(merged['checks'].values())
    _require(merged['checks'] == {'facts': True, 'images': True, 'affiliate': True}
             and merged['blocked'] is False, 'merged_source_incomplete')
    merged = runtime.catalog._public(merged)
    _require(isinstance(merged, dict) and set(merged) == set(GATHERED_FIELDS),
             'merged_public_schema')
    target_hash = fingerprint(target_source)
    manifest = {
        'schemaVersion': 1, 'kind': 'prepared_revision_source_v1', 'action': ACTION,
        'jobId': JOB, 'specHash': SPEC, 'contextHash': fingerprint(context),
        'failedSourceSha256': hashlib.sha256(source_raw).hexdigest(),
        'amendmentClaimSha256': amendment_sha,
        'amendmentResultSha256': hashlib.sha256(result_raw).hexdigest(),
        'ownerGrantSha256': OWNER_GRANT, 'targetProductId': TARGET,
        'targetArtifactSha256': hashlib.sha256(target_raw).hexdigest(),
        'targetSourceFingerprint': target_hash, 'mergedSourceFingerprint': fingerprint(merged),
        'preparedSourceTtl': expiry.isoformat(), 'assembledAt': now.isoformat(),
        'reusedProductIds': [pid for pid in context['targetProductIds'] if pid != TARGET],
    }
    return job, context, grant, manifest, merged, paths, (
        source_raw, amendment_raw, result_raw, target_raw), live


def prepare(runtime, owner_grant, *, now=None):
    """Read-only validation of the exact positive one-product handoff."""
    _, _, _, manifest, _, _, _, _ = _eligibility(runtime, owner_grant, now)
    return {'status': 'ready', **copy.deepcopy(manifest)}


def consume_prepared_source(capability, runtime, job, context, binding):
    """Runtime-only capability boundary; arbitrary dictionaries are rejected."""
    _require(isinstance(capability, _PreparedSource) and not capability.used, 'capability')
    manifest = capability.manifest
    _require(job.get('id') == JOB and job.get('kind') == 'article_revision'
             and fingerprint(binding) == manifest.get('specHash') == SPEC
             and fingerprint(capability.source) == manifest.get('mergedSourceFingerprint'),
             'capability_binding')
    artifacts = {
        'failedSourceSha256': runtime.root / 'research' / (JOB + '.json'),
        'amendmentClaimSha256': runtime.root / 'revision-catalog-amendment-attempts' /
            (JOB + '.json'),
        'amendmentResultSha256': runtime.root / 'revision-catalog-amendment-results' /
            (JOB + '.json'),
        'targetArtifactSha256': runtime.root / 'revision-prepared-source-targets' /
            (JOB + '.json'),
    }
    target_record = None
    for field, path in artifacts.items():
        value, raw = _read(path, 'capability_artifact')
        _require(hashlib.sha256(raw).hexdigest() == manifest.get(field),
                 'capability_artifact')
        if field == 'targetArtifactSha256':
            target_record = value
    live = next((article for article in context.get('revisionArticles', context.get('articles', []))
                 if article.get('id') == binding['baseArticle']['id']), None)
    products = {product['id']: product for product in context.get('products', [])}
    _require(live is not None and fingerprint(live) == binding['baseHash']
             and all(products.get(product['id']) == product
                     for product in binding['baseProducts']), 'live_binding')
    _require(fingerprint(_scope(runtime, context, binding))
             == target_record.get('contextScopeFingerprint'), 'context_scope_drift')
    clock = getattr(runtime, 'clock', None)
    current = timestamp(clock() if callable(clock) else None)
    _require(current < timestamp(manifest['preparedSourceTtl']), 'source_expired')
    from models import Models
    checker = getattr(runtime, 'models', None)
    if not callable(getattr(checker, '_safe_public', None)):
        checker = Models(getattr(runtime, 'env', {}))
    checker._safe_public(capability.source)
    capability.used = True
    return copy.deepcopy(capability.source)


def execute(runtime, owner_grant, *, now=None):
    """Archive and claim once, then enter the unchanged normal pipeline."""
    job, _, grant, manifest, merged, paths, raws, live = _eligibility(
        runtime, owner_grant, now)
    attempt_path, result_path = paths
    archive_root = runtime.root / 'revision-prepared-source-archives' / JOB
    names = ('failed-source', 'amendment-claim', 'amendment-result', 'target-source')
    archives = {}
    for name, raw in zip(names, raws):
        digest = hashlib.sha256(raw).hexdigest()
        path = archive_root / (name + '-' + digest + '.json')
        _archive(path, raw)
        archives[name] = {'path': str(path.relative_to(runtime.root)), 'sha256': digest}
    attempt = {**manifest, 'status': 'claimed', 'ownerGrant': copy.deepcopy(grant),
               'sourceArchives': archives, 'claimedAt': timestamp(now).isoformat()}
    attempt_sha = _write_once(attempt_path, attempt)
    capability = _PreparedSource(_TOKEN, manifest, merged)
    try:
        delivery = runtime._make_article(job, live,
                                         prepared_revision_source=capability)
        current = runtime.ledger.get_job(JOB)
        result = {'schemaVersion': 1, 'kind': 'prepared_revision_source_result_v1',
                  'status': 'completed', 'jobId': JOB,
                  'attemptReceiptSha256': attempt_sha, 'stage': current.get('stage'),
                  'revision': current.get('revision'), 'completedAt': timestamp().isoformat()}
        _write_once(result_path, result)
        return {'status': 'completed', 'id': JOB, 'stage': current.get('stage'),
                'deliveryStatus': delivery.get('status') if isinstance(delivery, dict) else None}
    except Exception as error:
        from runtime import reason
        records = runtime.stage_journal.status(job_id=JOB)['records']
        outcome = 'requires_reconciliation' if isinstance(error, StageUnknown) or records else 'blocked'
        runtime.ledger.set_stage(JOB, 'error', {
            'reason': reason(error), 'originalFailure': copy.deepcopy(job.get('error')),
            'preparedSourceRecovery': outcome, 'at': timestamp().isoformat()})
        _write_once(result_path, {'schemaVersion': 1,
            'kind': 'prepared_revision_source_result_v1', 'status': outcome,
            'jobId': JOB, 'attemptReceiptSha256': attempt_sha,
            'reason': reason(error), 'completedAt': timestamp().isoformat()})
        return {'status': 'attention', 'id': JOB, 'reason': reason(error),
                'outcome': outcome}
    finally:
        runtime._save_usage()
