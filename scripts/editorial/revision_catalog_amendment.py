"""One finite pre-model catalog amendment for the held burner revision."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from ledger import canonical, fingerprint, timestamp
from revisions import validated_context, validate_context
from stage_journal import StageUnknown


JOB = 'revision-81d57bccd5f033c369187f4d'
S001, S008, S006 = 'burner-s-001', 'burner-s-008', 'burner-s-006'
S001_AMAZON = 'https://www.amazon.co.jp/dp/B007VLFI6W/?tag=camp78-22'
S006_RAKUTEN = ('https://hb.afl.rakuten.co.jp/ichiba/'
    '52ca7731.3a4caf9e.52ca7732.67f9ad23/'
    '?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Ftsuribitokan-masuda%2F'
    '1000003108849%2F&link_type=text')
S001_CHECKED_AT = '2026-11-28T23:11:38.780591+09:00'
S006_CHECKED_AT = '2026-11-28T23:14:26.685353+09:00'
OWNER_GRANT_FINGERPRINT = '7971cd7bfcbb89a599920c58d56b40ae99c57d595e6e7984e462bf26a581325e'
OWNER_GRANT_RECEIPT_SHA256 = '6caee83229eba9ae01f7ebebadff2d3b8fd0d4331a29fe9bae7974198454b602'
BUDGET_CAPS = {
    'article': {'calls': 32, 'inputTokens': 2_000_000, 'outputTokens': 262_144},
    'period': {'calls': 128, 'inputTokens': 8_000_000, 'outputTokens': 1_048_576},
}
KNOWN_PREWRITE_FAILURES = {
    'source_product_image_or_affiliate_verification_incomplete',
    'prewrite_display_correction_required',
    'purchase evidence required',
}
SUMMARY = (
    'burner-s-008の検証済み楽天購入先訂正を保持し、burner-s-001のGST-120R'
    '確認済みAmazon購入先とburner-s-006の1824393-CARB確認済み楽天購入先を追加する。'
    '共有商品変更として3商品の影響を対象版承認で表示する。')
INSTRUCTIONS = (
    '公開済みarticle-005、全11商品の順序・仕様・画像、既存burner-s-008訂正を保持する。'
    'burner-s-001には確認済みGST-120RのAmazon購入先だけ、burner-s-006には確認済み'
    'JETBOIL Flash 1824393-CARBの楽天購入先だけを追加し、各updatedAtを検証時刻へ更新する。'
    '制作前に全11商品を通常のCatalog.gather_revisionでfresh検証し、facts/images/affiliate'
    'またはpurchase prewrite gateが不合格ならモデルを呼ばず保留する。旧source claim、'
    'model利用量、予算alias、本文、FAQ、承認、公開、SNS状態を初期化しない。独立Astra QAと'
    '本人の対象版Slack承認前に公開せず、記事承認をSNS承認へ転用しない。')

ALIASES = [
    {'reservationId': 'import-36c431b98d286279052f76fff1e3c6d796f20d4614239b074a88292fa0b0947d',
     'dataHash': '0fa769c0a5245a7c30f33eff8b81fcb0c2f51ac6ee1167c7a840ab9b82867290'},
    {'reservationId': 'import-5af2f52c9fd56fdda9c40f893382a55b40ee2cb507578b418eef5ac7411534ed',
     'dataHash': '6404226d86e28baa371be4e88cf98f9bc096f640fd0ff0cbea8f1fd1003c54aa'},
    {'reservationId': 'import-e24d655021388dc3584b462a33d4bccf067cea37ca1f061a4baf8ee39ece374e',
     'dataHash': '0aa402f2e30be51382e8cf102e170e3c20a548f429d77b5c87f5a9fa76b4d529'},
]
AUTHORIZED = {
    JOB: {
        'oldJobHash': '1f29607285cea48442fbd7cdb0f0f18cf560e20060e87d911340b19c8c0a6f20',
        'oldSpecHash': '04f89ebac8194b33a8ea3c05ee430027b76279fbe5b1f14823e6968b98372ae0',
        'researchSha256': '74e176b774537f0d9769686e45ae703785793dd29370f8ca916f9a1643ec810c',
        'sourceRecoveryAttemptSha256': '69c3633f8f15eb70c6a62b38a505b80164a8ae76ade9320a0f9e4941ea66093e',
        'sourceRecoveryResultSha256': 'fc229ff7b87f237659b58b0a3601b7f5ba19dc1ce4490e2b781b00fc2373daa0',
        'productionMarkerSha256': '72f52a27f2985b2d9d15d5e58db9acd8ec60262ae5cc7ad88c0e524bdd3ac570',
        'budgetArticleId': 'article:ac96288bae37671f53d326f7c1b5f037540aa502a8e3fb3f7a5757df10a31201',
        'productionPeriod': '2026-11-27',
        'existingImportedBudgetReceipts': ALIASES,
        'ownerGrantFingerprint': OWNER_GRANT_FINGERPRINT,
        'ownerGrantReceiptSha256': OWNER_GRANT_RECEIPT_SHA256,
    },
}


def _require(value, reason):
    if not value:
        raise ValueError('revision_catalog_amendment_' + reason)


def _secure_read(path, reason):
    path = Path(path)
    try:
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_mode & 0o777 == 0o600, reason)
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError('revision_catalog_amendment_' + reason) from None
    _require(isinstance(value, dict), reason)
    return value, raw


def _write_once(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require(not path.parent.is_symlink()
             and path.parent.stat().st_mode & 0o777 == 0o700,
             'receipt_directory_invalid')
    raw = (canonical(value) + '\n').encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
    except OSError as error:
        raise ValueError('revision_catalog_amendment_already_claimed') from error
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
             'archive_directory_invalid')
    if path.exists() or path.is_symlink():
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_mode & 0o777 == 0o600
                 and path.read_bytes() == raw, 'archive_conflict')
        return
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
    except OSError as error:
        raise ValueError('revision_catalog_amendment_archive_conflict') from error
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _raw_context(context):
    return {key: copy.deepcopy(value) for key, value in context.items()
            if key not in ('kind', 'baseHash', 'productPatches')}


def _amended_context(old):
    raw = _raw_context(old)
    products = raw['candidateProducts']
    by_id = {product['id']: product for product in products}
    _require(list(by_id) == old['targetProductIds'], 'product_order')
    _require(by_id[S001].get('amazonUrl') in ('', None)
             and by_id[S006].get('affiliateUrl') in ('', None),
             'missing_routes_changed')
    by_id[S001]['amazonUrl'] = S001_AMAZON
    by_id[S001]['updatedAt'] = S001_CHECKED_AT
    by_id[S006]['affiliateUrl'] = S006_RAKUTEN
    by_id[S006]['updatedAt'] = S006_CHECKED_AT
    raw['changeSummary'] = SUMMARY
    raw['editorialCorrectionInstructions'] = INSTRUCTIONS
    amended = validated_context(raw)
    prior_s008 = [item for item in old.get('productPatches', [])
                  if item.get('id') == S008]
    next_s008 = [item for item in amended['productPatches']
                 if item.get('id') == S008]
    _require(len(prior_s008) == len(next_s008) == 1
             and prior_s008 == next_s008,
             'existing_s008_patch_changed')
    _require([item['id'] for item in amended['productPatches']]
             == [S001, S008, S006], 'patch_scope')
    return amended


def _product_changes(old, new):
    changes = []
    for before, after in zip(old['candidateProducts'], new['candidateProducts']):
        delta = {key: copy.deepcopy(after[key]) for key in after
                 if canonical(after[key]) != canonical(before[key])}
        if delta:
            changes.append({'productId': before['id'],
                            'previous': {key: copy.deepcopy(before[key])
                                         for key in delta},
                            'fields': delta})
    return changes


def _source_scope(source, context):
    products = source.get('products')
    evidence = (source.get('evidence') or {}).get('products')
    _require(source.get('productIds') == context['targetProductIds']
             and products == context['candidateProducts']
             and source.get('catalog') == products
             and source.get('checks')
                == {'facts': True, 'images': True, 'affiliate': True}
             and source.get('blocked') is False
             and 'purchaseEvidence' not in source
             and isinstance(evidence, list)
             and [item.get('productId') for item in evidence]
                == context['targetProductIds'], 'research_scope')
    by_product = {product['id']: product for product in products}
    missing = {(product['id'], channel) for product in products
               for channel, field in (('amazon', 'amazonUrl'),
                                      ('rakuten', 'affiliateUrl'))
               if product.get(field) in ('', None)}
    _require(missing == {(S001, 'amazon'), (S006, 'rakuten')},
             'research_missing_routes')
    details = {item['productId']: item for item in evidence}
    for product_id, alternative, field in ((S001, 'rakuten', 'affiliateUrl'),
                                            (S006, 'amazon', 'amazonUrl')):
        detail = details[product_id]
        _require(all(detail.get(key) is True
                     for key in ('facts', 'images', 'affiliate'))
                 and detail.get('issues') == []
                 and any(destination.get('channel') == alternative
                         and destination.get('verified') is True
                         and destination.get('url')
                            == by_product[product_id][field]
                         for destination in detail.get('destinations', [])),
                 'verified_alternative')


def _budget_rows(db, article_id):
    cursor = db.execute(
        'SELECT * FROM model_budget_reservations WHERE article_id=? '
        'ORDER BY reservation_id', (article_id,))
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, values)) for values in cursor.fetchall()]


def _eligibility(runtime, id, owner_grant, expected_current_period, now):
    runtime._require_running()
    authorization = AUTHORIZED.get(id)
    _require(isinstance(authorization, dict), 'scope')
    grant = runtime.ledger.validate_existing_improvement_owner_grant(owner_grant)
    _require(fingerprint(grant) == authorization['ownerGrantFingerprint']
             and grant.get('instructionReceiptSha256')
                == authorization['ownerGrantReceiptSha256'],
             'owner_grant')
    limits = runtime.model_budget.config
    _require(all(limits.get(scope, {}).get(field) == value
                 for scope, values in BUDGET_CAPS.items()
                 for field, value in values.items()), 'budget_caps')
    job = runtime.ledger.get_job(id)
    _require(fingerprint(job) == authorization['oldJobHash'], 'job_hash')
    with sqlite3.connect(runtime.ledger.db_path) as db:
        row = db.execute('SELECT data FROM jobs WHERE id=?', (id,)).fetchone()
    _require(row is not None and json.loads(row[0]) == job, 'job_archive_source')
    job_raw = row[0].encode('utf-8')
    raw_context = copy.deepcopy(job.get('revisionContext'))
    context_raw = canonical(raw_context).encode('utf-8')
    context = validate_context(job.get('revisionContext'))
    _require(fingerprint(context) == authorization['oldSpecHash'], 'spec_hash')
    _require(job.get('kind') == 'article_revision' and job.get('stage') == 'error'
             and (job.get('error') or {}).get('reason') == 'purchase evidence required'
             and (job.get('error') or {}).get('sourceHoldRecovery') == 'blocked'
             and all(job.get(key) is None for key in (
                 'bundle', 'revision', 'review', 'astraReview', 'approval',
                 'publication', 'social')), 'job_state')
    _require(runtime._budget_article_id(id) == authorization['budgetArticleId']
             and runtime.model_budget._period_key(timestamp(now))
                == expected_current_period
             and expected_current_period == authorization['productionPeriod'],
             'budget_period')

    root = runtime.root
    source_path = root / 'research' / (id + '.json')
    source, source_raw = _secure_read(source_path, 'research_missing')
    _require(hashlib.sha256(source_raw).hexdigest()
             == authorization['researchSha256'], 'research_hash')
    _source_scope(source, context)
    paths = {
        'sourceRecoveryAttempt': root / 'revision-source-hold-recovery-attempts' /
            (id + '.json'),
        'sourceRecoveryResult': root / 'revision-source-hold-recovery-results' /
            (id + '.json'),
        'productionMarker': root / 'revision-production-attempts' / (id + '.json'),
    }
    prior = {}
    for key, path in paths.items():
        value, raw = _secure_read(path, key + '_missing')
        expected = authorization[key + 'Sha256']
        _require(hashlib.sha256(raw).hexdigest() == expected, key + '_hash')
        prior[key] = value
    attempt, result = prior['sourceRecoveryAttempt'], prior['sourceRecoveryResult']
    _require(attempt.get('status') == 'claimed'
             and attempt.get('jobId') == id
             and attempt.get('specHash') == authorization['oldSpecHash']
             and attempt.get('budgetArticleId') == authorization['budgetArticleId']
             and attempt.get('productionPeriod') == authorization['productionPeriod']
             and attempt.get('existingImportedBudgetReceipts')
                == authorization['existingImportedBudgetReceipts'],
             'source_recovery_attempt')
    _require(result.get('status') == 'blocked' and result.get('jobId') == id
             and result.get('reason') == 'purchase evidence required'
             and result.get('attemptReceiptSha256')
                == authorization['sourceRecoveryAttemptSha256'],
             'source_recovery_result')
    _require(prior['productionMarker'].get('status') == 'blocked'
             and prior['productionMarker'].get('reason')
                == 'source_product_image_or_affiliate_verification_incomplete',
             'production_marker')

    records = runtime.stage_journal.status(job_id=id)['records']
    _require(records == [], 'model_stage_started')
    with sqlite3.connect(runtime.ledger.db_path) as db:
        _require(not db.execute('SELECT 1 FROM requests WHERE job_id=?',
                                (id,)).fetchone()
                 and not db.execute('SELECT 1 FROM effects WHERE job_id=?',
                                    (id,)).fetchone(), 'side_effects')
        _require(not db.execute(
            'SELECT 1 FROM model_budget_reservations WHERE article_id=?',
            (id,)).fetchone(), 'current_job_model_usage')
        rows = _budget_rows(db, authorization['budgetArticleId'])
    imported = [{'reservationId': row['reservation_id'],
                 'dataHash': fingerprint(row)} for row in rows]
    _require(imported == authorization['existingImportedBudgetReceipts']
             and {row['stage'] for row in rows}
                == {'draft', 'polish', 'final_review'}
             and all(row['status'] == 'imported' for row in rows),
             'budget_aliases')

    attempt_path = root / 'revision-catalog-amendment-attempts' / (id + '.json')
    result_path = root / 'revision-catalog-amendment-results' / (id + '.json')
    _require(not attempt_path.exists() and not attempt_path.is_symlink()
             and not result_path.exists() and not result_path.is_symlink(),
             'already_claimed')
    amended = _amended_context(context)
    changes = _product_changes(context, amended)
    claim = {
        'kind': 'revision_catalog_amendment_v1', 'jobId': id,
        'oldJobHash': authorization['oldJobHash'],
        'oldSpecHash': authorization['oldSpecHash'],
        'newSpecHash': fingerprint(amended),
        'sourceSha256': authorization['researchSha256'],
        'sourceRecoveryAttemptSha256': authorization['sourceRecoveryAttemptSha256'],
        'sourceRecoveryResultSha256': authorization['sourceRecoveryResultSha256'],
        'ownerGrantSha256': fingerprint(grant),
        'budgetArticleId': authorization['budgetArticleId'],
        'existingImportedBudgetReceipts': copy.deepcopy(
            authorization['existingImportedBudgetReceipts']),
        'productChanges': changes,
    }
    archive_path = root / 'revision-catalog-amendment-sources' / id / (
        authorization['researchSha256'] + '.json')
    job_archive_path = root / 'revision-catalog-amendment-history' / id / (
        authorization['oldJobHash'] + '.job.json')
    context_archive_path = root / 'revision-catalog-amendment-history' / id / (
        authorization['oldSpecHash'] + '.context.json')
    return (job, context, amended, claim, source_raw, archive_path,
            attempt_path, result_path, grant, job_raw, job_archive_path,
            context_raw, context_archive_path)


def prepare(runtime, id, owner_grant, *, expected_current_period, now=None):
    """Read-only exact preflight. It performs no Catalog gather or mutation."""
    _, _, amended, claim, _, _, _, _, _, _, _, _, _ = _eligibility(
        runtime, id, owner_grant, expected_current_period, now)
    return {
        'status': 'ready', 'action': 'amend_verified_purchase_routes_once',
        'jobId': id, 'oldSpecHash': claim['oldSpecHash'],
        'newSpecHash': claim['newSpecHash'],
        'productPatchIds': [item['id'] for item in amended['productPatches']],
        'budgetArticleId': claim['budgetArticleId'],
        'productionPeriod': expected_current_period,
        'sourceSha256': claim['sourceSha256'],
    }


def _failure_outcome(runtime, id, error):
    """Only a proven pre-model, side-effect-free gate failure is retry-blocked."""
    from runtime import reason
    if isinstance(error, StageUnknown) or reason(error) not in KNOWN_PREWRITE_FAILURES:
        return 'requires_reconciliation'
    if runtime.stage_journal.status(job_id=id)['records']:
        return 'requires_reconciliation'
    with sqlite3.connect(runtime.ledger.db_path) as db:
        side_effect = (db.execute('SELECT 1 FROM requests WHERE job_id=?',
                                  (id,)).fetchone()
                       or db.execute('SELECT 1 FROM effects WHERE job_id=?',
                                     (id,)).fetchone()
                       or db.execute(
                           'SELECT 1 FROM model_budget_reservations WHERE article_id=?',
                           (id,)).fetchone())
    return 'requires_reconciliation' if side_effect else 'blocked'


def execute(runtime, id, owner_grant, *, expected_current_period, now=None):
    """Claim once, atomically amend the job, then call the normal pipeline once."""
    (job, old_context, amended_context, claim, source_raw, archive_path,
     attempt_path, result_path, grant, job_raw, job_archive_path,
     context_raw, context_archive_path) = _eligibility(
        runtime, id, owner_grant, expected_current_period, now)
    _archive_exact(archive_path, source_raw)
    _archive_exact(job_archive_path, job_raw)
    _archive_exact(context_archive_path, context_raw)
    attempt = {
        **copy.deepcopy(claim), 'status': 'claimed',
        'action': 'amend_verified_purchase_routes_once',
        'sourceArchive': str(archive_path.relative_to(runtime.root)),
        'oldJobArchive': str(job_archive_path.relative_to(runtime.root)),
        'oldJobArchiveSha256': hashlib.sha256(job_raw).hexdigest(),
        'oldContextArchive': str(context_archive_path.relative_to(runtime.root)),
        'oldContextArchiveSha256': hashlib.sha256(context_raw).hexdigest(),
        'ownerGrant': copy.deepcopy(grant), 'claimedAt': timestamp(now).isoformat(),
    }
    attempt_sha = _write_once(attempt_path, attempt)
    amended_job = None
    try:
        amended_job = runtime.ledger.amend_unstarted_revision_catalog(
            id, claim['oldJobHash'], claim['oldSpecHash'],
            _raw_context(amended_context), claim)
        delivery = runtime._make_article(amended_job, runtime._context())
        if (not isinstance(delivery, dict)
                or delivery.get('status') not in (
                    'awaiting_astra_review', 'delivered', 'already_delivered')):
            raise ValueError('delivery_requires_reconciliation')
        current = runtime.ledger.get_job(id)
        _require(current.get('approval') is None
                 and current.get('publication') is None
                 and current.get('social') is None,
                 'authority_changed')
        result = {
            'kind': 'revision_catalog_amendment_result_v1',
            'status': 'completed', 'jobId': id,
            'attemptReceiptSha256': attempt_sha,
            'oldSpecHash': fingerprint(old_context),
            'newSpecHash': fingerprint(amended_context),
            'stage': current.get('stage'),
            'deliveryStatus': (delivery.get('status')
                               if isinstance(delivery, dict) else None),
            'completedAt': timestamp().isoformat(),
        }
        _write_once(result_path, result)
        return {'status': 'completed', 'id': id,
                'stage': current.get('stage'),
                'deliveryStatus': result['deliveryStatus']}
    except Exception as error:
        from runtime import reason
        outcome = _failure_outcome(runtime, id, error)
        if amended_job is not None:
            runtime.ledger.set_stage(id, 'error', {
                'reason': reason(error),
                'originalFailure': copy.deepcopy(job.get('error')),
                'catalogAmendmentRecovery': 'catalog_amendment_' + outcome,
                'at': timestamp().isoformat(),
            })
        _write_once(result_path, {
            'kind': 'revision_catalog_amendment_result_v1',
            'status': outcome, 'jobId': id,
            'attemptReceiptSha256': attempt_sha,
            'reason': reason(error), 'completedAt': timestamp().isoformat(),
        })
        return {'status': 'attention', 'id': id,
                'reason': reason(error), 'outcome': outcome}
    finally:
        runtime._save_usage()
