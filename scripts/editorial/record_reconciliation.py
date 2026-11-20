"""Additive reconciliation receipts for bounded historical records.

The original SQLite rows and JSON receipts are evidence and are never changed here.
"""
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
from urllib.parse import quote


JST = timezone(timedelta(hours=9))
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_RECEIPTS = 500
RECEIPT_FOLDER = 'record-reconciliations'
RECORD_TYPES = {
    'manager_work_order': 'managerWorkOrders',
    'revision_production_attempt': 'revisionProductionAttempts',
    'post_publication_audit': 'postPublicationAudits',
    'index_tracking': 'indexTracking',
}
JSON_FOLDERS = {
    'revision-production-attempts', 'post-publication-audits', 'index-tracking',
    'reconciliations', 'operator-reconciliations', 'repair', 'repairs', 'reports',
    'deployments',
}


def _root(value):
    root = Path(value)
    if not root.is_absolute() or root.resolve() in (Path('/'), Path.home().resolve()):
        raise ValueError('safe absolute state root required')
    return root.resolve()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return _digest(_canonical(value).encode('utf-8'))


def _identifier(value, name):
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError(name + ' required')
    return value


def _sha256(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in '0123456789abcdef' for character in value)):
        raise ValueError('sha256 required')
    return value


def _relative_json_path(value):
    if not isinstance(value, str):
        raise ValueError('safe JSON path required')
    relative = PurePosixPath(value)
    if (relative.is_absolute() or len(relative.parts) < 2 or '..' in relative.parts
            or relative.parts[0] not in JSON_FOLDERS or relative.suffix != '.json'):
        raise ValueError('safe JSON path required')
    return relative


def _json_bytes(root, relative):
    path = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('safe JSON path required')
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError('bounded JSON record required')
    if root not in resolved.parents:
        raise ValueError('safe JSON path required')
    if not resolved.is_file() or resolved.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('bounded JSON record required')
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError('valid JSON record required')
    return raw, value


def _sqlite_value(root, table, column, identifier):
    path = root / 'ledger.sqlite3'
    if path.is_symlink() or not path.is_file():
        raise ValueError('ledger required')
    uri = 'file:' + quote(str(path), safe='/') + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True, timeout=.2) as db:
            db.execute('PRAGMA query_only=ON')
            row = db.execute('SELECT data FROM jobs WHERE id=?' if table == 'jobs'
                             else 'SELECT value FROM meta WHERE key=?', (identifier,)).fetchone()
    except sqlite3.Error:
        raise ValueError('ledger record unavailable')
    if row is None or not isinstance(row[0], str) or len(row[0].encode('utf-8')) > MAX_FILE_BYTES:
        raise ValueError('ledger record unavailable')
    raw = row[0].encode('utf-8')
    try:
        value = json.loads(row[0])
    except (ValueError, TypeError, RecursionError):
        raise ValueError('valid ledger record required')
    if not isinstance(value, dict):
        raise ValueError('ledger object required')
    return raw, value


def _read_ref(root, reference):
    if not isinstance(reference, dict):
        raise ValueError('record reference required')
    kind = reference.get('kind')
    expected = _sha256(reference.get('sha256'))
    if kind == 'json':
        allowed = ({'kind', 'path', 'sha256'}, {'kind', 'path', 'sha256', 'selector'})
        if set(reference) not in allowed:
            raise ValueError('invalid JSON reference')
        relative = _relative_json_path(reference.get('path'))
        raw, value = _json_bytes(root, relative)
        identity = {'kind': kind, 'path': relative.as_posix()}
        if 'selector' in reference:
            selector = reference.get('selector')
            if (not isinstance(selector, dict) or set(selector) != {'index'}
                    or not isinstance(selector.get('index'), int)
                    or isinstance(selector.get('index'), bool)
                    or selector['index'] < 0 or selector['index'] >= 100
                    or not isinstance(value, list) or selector['index'] >= len(value)):
                raise ValueError('bounded JSON selector required')
            value = value[selector['index']]
            identity['selector'] = {'index': selector['index']}
    elif kind == 'sqlite_publication':
        if set(reference) != {'kind', 'path', 'id', 'sha256'} or reference.get('path') != 'ledger.sqlite3':
            raise ValueError('invalid publication reference')
        identifier = _identifier(reference.get('id'), 'job id')
        unused, job = _sqlite_value(root, 'jobs', 'data', identifier)
        if job.get('id') != identifier:
            raise ValueError('publication job mismatch')
        value = {'id': job.get('id'), 'revision': job.get('revision'),
                 'publication': job.get('publication')}
        raw = _canonical(value).encode('utf-8')
        identity = {'kind': kind, 'path': 'ledger.sqlite3', 'id': identifier}
    elif kind == 'sqlite_meta':
        if set(reference) != {'kind', 'path', 'key', 'sha256'} or reference.get('path') != 'ledger.sqlite3':
            raise ValueError('invalid meta reference')
        key = _identifier(reference.get('key'), 'meta key')
        if not key.startswith('editorial_manager_work:'):
            raise ValueError('manager work reference required')
        raw, value = _sqlite_value(root, 'meta', 'value', key)
        identity = {'kind': kind, 'path': 'ledger.sqlite3', 'key': key}
    else:
        raise ValueError('unsupported reference kind')
    if _digest(raw) != expected:
        raise ValueError('record hash mismatch')
    if not isinstance(value, dict):
        raise ValueError('selected JSON object required')
    return value, identity


def _published(job, job_id, revision):
    publication = job.get('publication') or {}
    readback = publication.get('readback') or {}
    if (job.get('id') != job_id or job.get('revision') != revision
            or publication.get('verified') is not True
            or publication.get('revision') != revision
            or not isinstance(readback, dict) or readback.get('verified') is not True
            or readback.get('fingerprint') != revision):
        raise ValueError('published version proof required')
    return publication


def _publication_proof(root, reference, job_id=None, revision=None):
    job, identity = _read_ref(root, reference)
    if identity.get('kind') != 'sqlite_publication':
        raise ValueError('sqlite publication proof required')
    expected_id = job_id if job_id is not None else job.get('id')
    expected_revision = revision if revision is not None else job.get('revision')
    return job, _published(job, expected_id, expected_revision), identity


def _standard_audit(value, identity, job_id, revision, publication, *, passed):
    key = _hash({'id': job_id, 'revision': revision, 'publication': publication})
    result = value.get('result') or {}
    if (identity != {'kind': 'json', 'path': 'post-publication-audits/' + key + '.json'}
            or value.get('auditKey') != key or value.get('id') != job_id
            or value.get('revision') != revision or value.get('publication') != publication):
        raise ValueError('standard audit binding required')
    checks = result.get('checks') if isinstance(result, dict) else None
    every_check_passed = bool(isinstance(checks, list) and checks
                              and all(isinstance(check, dict)
                                      and check.get('status') == 'passed' for check in checks))
    if passed and (value.get('status') != 'success' or not isinstance(result, dict)
                   or result.get('status') != 'passed' or result.get('passed') is not True
                   or not every_check_passed):
        raise ValueError('passing standard audit required')
    return key


def _base_id(job):
    context = job.get('revisionContext') or {}
    base = context.get('baseArticle') if isinstance(context, dict) else None
    value = base.get('id') if isinstance(base, dict) else None
    return value if isinstance(value, str) and value else None


def _job_state(root, job_id):
    unused, job = _sqlite_value(root, 'jobs', 'data', job_id)
    if job.get('id') != job_id:
        raise ValueError('publication job mismatch')
    return job


def _latest_published(root, base_id, url):
    path = root / 'ledger.sqlite3'
    uri = 'file:' + quote(str(path), safe='/') + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True, timeout=.2) as db:
            db.execute('PRAGMA query_only=ON')
            rows = db.execute('SELECT data FROM jobs ORDER BY rowid LIMIT ?',
                              (MAX_RECEIPTS * 2 + 1,)).fetchall()
    except sqlite3.Error:
        raise ValueError('latest published version unavailable')
    if len(rows) > MAX_RECEIPTS * 2:
        raise ValueError('latest published version scan truncated')
    matches = []
    for (raw,) in rows:
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_FILE_BYTES:
            continue
        try:
            job = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            continue
        publication = job.get('publication') or {}
        readback = publication.get('readback') or {}
        if (_base_id(job) == base_id and publication.get('url') == url
                and publication.get('verified') is True and isinstance(readback, dict)
                and readback.get('verified') is True
                and publication.get('revision') == job.get('revision')
                and readback.get('fingerprint') == job.get('revision')):
            stamp = _aware_timestamp(publication.get('remoteUpdatedAt'))
            matches.append((stamp, job))
    if not matches:
        raise ValueError('latest published version unavailable')
    latest_stamp = max(stamp for stamp, unused in matches)
    latest = [job for stamp, job in matches if stamp == latest_stamp]
    if len(latest) != 1:
        raise ValueError('latest published version ambiguous')
    return latest[0]


def _aware_timestamp(value):
    if not isinstance(value, str):
        raise ValueError('aware evidence timestamp required')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('aware evidence timestamp required')
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('aware evidence timestamp required')
    return parsed


def _validate_source(root, entry):
    record_type = entry['recordType']
    value, identity = _read_ref(root, entry['source'])
    job_id, revision = entry['jobId'], entry['revision']
    if record_type == 'manager_work_order':
        if (identity.get('kind') != 'sqlite_meta' or value.get('status') != 'human_needed'
                or value.get('jobId') != job_id
                or value.get('revision') not in (None, revision)):
            raise ValueError('manager work source mismatch')
    elif record_type == 'revision_production_attempt':
        expected = 'revision-production-attempts/' + job_id + '.json'
        if (identity != {'kind': 'json', 'path': expected}
                or value.get('status') != 'blocked'):
            raise ValueError('blocked revision attempt required')
    elif record_type == 'post_publication_audit':
        publication = value.get('publication') or {}
        try:
            _standard_audit(value, identity, job_id, revision, publication, passed=False)
        except ValueError:
            raise ValueError('failed historical audit required')
        if (publication.get('revision') != revision
                or value.get('status') not in ('failed', 'unverified', 'requires_reconciliation')):
            raise ValueError('failed historical audit required')
    elif record_type == 'index_tracking':
        if (identity.get('kind') != 'json'
                or not identity['path'].startswith('index-tracking/')
                or value.get('id') != job_id or value.get('revision') != revision):
            raise ValueError('historical index record required')
    return identity


def _manual_audit(root, entry, evidence, identity, publication):
    """Fixed-path operator proof; never advances or rewrites the audit runner."""
    job_id, revision = entry['jobId'], entry['revision']
    path = 'operator-reconciliations/' + job_id + '-' + revision + '-audit.json'
    if (entry['recordType'] != 'post_publication_audit'
            or len(PurePosixPath(path).parts) != 2
            or identity != {'kind': 'json', 'path': path}):
        raise ValueError('fixed manual audit proof required')
    key = _hash({'id': job_id, 'revision': revision, 'publication': publication})
    source, source_identity = _read_ref(root, entry['source'])
    _standard_audit(source, source_identity, job_id, revision, publication, passed=False)
    if (evidence.get('id') != job_id or evidence.get('revision') != revision
            or evidence.get('publication') != publication or evidence.get('auditKey') != key
            or evidence.get('sourceAuditSHA256') != entry['source']['sha256']
            or evidence.get('readOnly') is not True):
        raise ValueError('manual audit binding required')
    result = evidence.get('result')
    checks = result.get('checks') if isinstance(result, dict) else None
    if (not isinstance(result, dict) or result.get('status') != 'passed' or result.get('passed') is not True
            or result.get('issues') != [] or not isinstance(checks, list) or not checks
            or any(not isinstance(check, dict) or check.get('status') != 'passed'
                   or not isinstance(check.get('name'), str) or not check['name'] for check in checks)):
        raise ValueError('complete passing manual audit required')
    names = [check['name'] for check in checks]
    job = _job_state(root, job_id)
    bundle = job.get('bundle') or {}
    products, images = bundle.get('products'), bundle.get('images')
    if (not isinstance(products, list) or not 1 <= len(products) <= 20
            or any(not isinstance(product, dict) for product in products)
            or not isinstance(images, list) or not 1 <= len(images) <= 41):
        raise ValueError('manual audit bundle required')
    required = {'public_title', 'approved_body', 'desktop', 'mobile',
                'desktop.binding', 'mobile.binding', 'desktop.prose', 'mobile.prose'}
    required.update('image.' + str(index) for index in range(len(images)))
    for index in range(len(products)):
        required.add('product_image_binding.' + str(index))
        for channel in ('rakuten', 'amazon'):
            required.add(f'destination.{index}.{channel}')
            for viewport in ('desktop', 'mobile'):
                required.add(f'{viewport}.click.{index}.{channel}')
        for viewport in ('desktop', 'mobile'):
            required.add(f'{viewport}.product_image.{index}')
    if ((bundle.get('article') or {}).get('generationMeta') or {}).get('socialCard'):
        required.update(('social_manifest', 'social_metadata'))
    # A fresh proof must cover every named original check, including failures;
    # omitting a prior non-core failure must never make reconciliation pass.
    required.update(check['name'] for check in (source.get('result') or {}).get('checks', [])
                    if isinstance(check, dict) and isinstance(check.get('name'), str)
                    and check['name'])
    if len(names) != len(set(names)) or not required.issubset(names):
        raise ValueError('manual audit core checks required')
    observed = _aware_timestamp(evidence.get('completedAt') or evidence.get('checkedAt') or evidence.get('at'))
    for before in (publication.get('at'), source.get('completedAt')):
        if before is not None and observed < _aware_timestamp(before):
            raise ValueError('manual audit must follow original observation')


def _validate_proof(root, entry, proof):
    if not isinstance(proof, dict):
        raise ValueError('proof required')
    kind = proof.get('kind')
    job_id, revision = entry['jobId'], entry['revision']
    if kind == 'published_same_version':
        if set(proof) != {'kind', 'record'}:
            raise ValueError('invalid publication proof')
        _publication_proof(root, proof['record'], job_id, revision)
    elif kind == 'superseded_by_published_version':
        if set(proof) != {'kind', 'sourceJob', 'latestJob'}:
            raise ValueError('invalid supersession proof')
        old, old_publication, unused = _publication_proof(
            root, proof['sourceJob'], job_id, revision)
        latest, latest_publication, unused = _publication_proof(root, proof['latestJob'])
        old_state = _job_state(root, job_id)
        latest_state = _job_state(root, latest.get('id'))
        base_id = _base_id(old_state)
        selected = _latest_published(root, base_id, old_publication.get('url'))
        if (not base_id or _base_id(latest_state) != base_id
                or selected.get('id') != latest.get('id')
                or selected.get('revision') != latest.get('revision')
                or latest.get('id') == job_id or latest.get('revision') == revision
                or not old_publication.get('url')
                or old_publication.get('url') != latest_publication.get('url')):
            raise ValueError('superseding published version required')
    elif kind == 'superseded_by_successful_published_version':
        if set(proof) != {'kind', 'sourceJob', 'latestJob', 'latestAudit'}:
            raise ValueError('invalid successful supersession proof')
        old, old_publication, unused = _publication_proof(
            root, proof['sourceJob'], job_id, revision)
        latest, latest_publication, unused = _publication_proof(root, proof['latestJob'])
        evidence, audit_identity = _read_ref(root, proof['latestAudit'])
        old_state = _job_state(root, job_id)
        latest_state = _job_state(root, latest.get('id'))
        base_id = _base_id(old_state)
        selected = _latest_published(root, base_id, old_publication.get('url'))
        if (not base_id or _base_id(latest_state) != base_id
                or selected.get('id') != latest.get('id')
                or selected.get('revision') != latest.get('revision')
                or old_publication.get('url') != latest_publication.get('url')
                or evidence.get('id') != latest.get('id')
                or evidence.get('revision') != latest.get('revision')):
            raise ValueError('successful superseding version required')
        _standard_audit(evidence, audit_identity, latest.get('id'), latest.get('revision'),
                        latest_publication, passed=True)
        _aware_timestamp(evidence.get('completedAt') or evidence.get('checkedAt') or evidence.get('at'))
    elif kind == 'same_version_audit_passed':
        if set(proof) != {'kind', 'record', 'job'}:
            raise ValueError('invalid audit proof')
        evidence, identity = _read_ref(root, proof['record'])
        result = evidence.get('result') or {}
        unused, publication, unused_identity = _publication_proof(
            root, proof['job'], job_id, revision)
        standard = False
        try:
            _standard_audit(evidence, identity, job_id, revision, publication, passed=True)
            standard = True
        except ValueError:
            standard = False
        readonly_path = ('deployments/20261114-readiness/' + job_id
                         + '-deployed-audit.json')
        checks = result.get('checks') if isinstance(result, dict) else None
        readonly = (identity.get('path') == readonly_path
                    and evidence.get('readOnly') is True and isinstance(result, dict)
                    and result.get('status') == 'passed' and result.get('passed') is True
                    and isinstance(checks, list) and bool(checks)
                    and all(isinstance(check, dict) and check.get('status') == 'passed'
                            for check in checks))
        manual = False
        if identity.get('path') == 'operator-reconciliations/' + job_id + '-' + revision + '-audit.json':
            _manual_audit(root, entry, evidence, identity, publication)
            manual = True
        if (evidence.get('id') != job_id or evidence.get('revision') != revision
                or not (standard or readonly or manual)):
            raise ValueError('same version passing audit required')
        _aware_timestamp(evidence.get('completedAt') or evidence.get('checkedAt') or evidence.get('at'))
    elif kind == 'same_version_indexed':
        if set(proof) != {'kind', 'record', 'job'}:
            raise ValueError('invalid index proof')
        evidence, identity = _read_ref(root, proof['record'])
        job, publication, unused = _publication_proof(root, proof['job'], job_id, revision)
        evidence_proof = evidence.get('proof') or {}
        if (identity.get('path') != 'deployments/20261114-readiness/index-readonly.json'
                or 'selector' not in identity
                or evidence.get('id') != job_id or evidence.get('sitemapCurrent') is not True
                or not isinstance(evidence_proof, dict)
                or evidence_proof.get('verdict') != 'PASS'
                or evidence_proof.get('coverageState') != 'Submitted and indexed'
                or evidence_proof.get('googleCanonical') != publication.get('url')):
            raise ValueError('same version indexed proof required')
        _aware_timestamp(evidence_proof.get('lastCrawlTime'))
    else:
        raise ValueError('unsupported proof kind')


def _proof_projection(root, proof):
    kind = proof['kind']
    if kind == 'same_version_audit_passed':
        evidence, identity = _read_ref(root, proof['record'])
        return {'kind': kind, 'proofStatus': 'passed',
                'observedAt': evidence.get('completedAt') or evidence.get('checkedAt')
                or evidence.get('at'), 'readOnly': evidence.get('readOnly') is True,
                'evidenceIdentity': identity}
    if kind == 'same_version_indexed':
        evidence, identity = _read_ref(root, proof['record'])
        detail = evidence.get('proof') or {}
        return {'kind': kind, 'proofStatus': 'indexed',
                'observedAt': detail.get('lastCrawlTime'), 'readOnly': True,
                'evidenceIdentity': identity}
    if kind == 'superseded_by_successful_published_version':
        evidence, identity = _read_ref(root, proof['latestAudit'])
        return {'kind': kind, 'proofStatus': 'superseded_success',
                'observedAt': evidence.get('completedAt') or evidence.get('checkedAt')
                or evidence.get('at'), 'readOnly': evidence.get('readOnly') is True,
                'evidenceIdentity': identity}
    reference = proof.get('latestJob') or proof.get('record')
    evidence, identity = _read_ref(root, reference)
    publication = evidence.get('publication') or {}
    return {'kind': kind,
            'proofStatus': ('superseded_published'
                            if kind == 'superseded_by_published_version' else 'published'),
            'observedAt': publication.get('remoteUpdatedAt'), 'readOnly': True,
            'evidenceIdentity': identity}


def _normalize_entry(root, entry):
    if not isinstance(entry, dict) or set(entry) != {
            'recordType', 'jobId', 'revision', 'source', 'proofs'}:
        raise ValueError('exact reconciliation entry required')
    record_type = entry.get('recordType')
    if record_type not in RECORD_TYPES:
        raise ValueError('unsupported record type')
    normalized = {
        'recordType': record_type,
        'jobId': _identifier(entry.get('jobId'), 'job id'),
        'revision': _identifier(entry.get('revision'), 'revision'),
        'source': entry.get('source'),
        'proofs': entry.get('proofs'),
    }
    source_identity = _validate_source(root, normalized)
    proofs = normalized['proofs']
    if not isinstance(proofs, list):
        raise ValueError('proof list required')
    proof_kinds = [proof.get('kind') if isinstance(proof, dict) else None for proof in proofs]
    required = {
        'manager_work_order': ['published_same_version'],
        'revision_production_attempt': [
            'published_same_version', 'superseded_by_published_version'],
        'index_tracking': ['same_version_indexed'],
    }.get(record_type)
    if required is not None and sorted(proof_kinds) != sorted(required):
        raise ValueError('exact proof set required')
    if (record_type == 'post_publication_audit'
            and proof_kinds not in (['same_version_audit_passed'],
                                    ['superseded_by_successful_published_version'])):
        raise ValueError('exact audit proof required')
    for proof in proofs:
        _validate_proof(root, normalized, proof)
    normalized['sourceRecordHash'] = normalized['source']['sha256']
    normalized['evidenceHash'] = _hash(proofs)
    normalized['sourceIdentity'] = source_identity
    return normalized


def _validate_normalized(root, entries):
    if not isinstance(entries, list) or not entries or len(entries) > MAX_RECEIPTS:
        raise ValueError('bounded reconciliation entries required')
    normalized, identities = [], set()
    for saved in entries:
        if not isinstance(saved, dict):
            raise ValueError('reconciliation entry required')
        base = {key: saved.get(key) for key in
                ('recordType', 'jobId', 'revision', 'source', 'proofs')}
        current = _normalize_entry(root, base)
        if saved.get('sourceRecordHash') != current['sourceRecordHash']:
            raise ValueError('source record hash mismatch')
        if saved.get('evidenceHash') != current['evidenceHash']:
            raise ValueError('evidence hash mismatch')
        if saved.get('sourceIdentity') != current['sourceIdentity']:
            raise ValueError('source identity mismatch')
        identity_key = _canonical(current['sourceIdentity'])
        if identity_key in identities:
            raise ValueError('duplicate source record')
        identities.add(identity_key)
        normalized.append(current)
    return normalized


def prepare_reconciliation(state_root, entries):
    """Validate an explicit allowlist and return a read-only, hash-bound plan."""
    root = _root(state_root)
    if not isinstance(entries, list) or not entries or len(entries) > MAX_RECEIPTS:
        raise ValueError('bounded reconciliation entries required')
    normalized, identities = [], set()
    for entry in entries:
        value = _normalize_entry(root, entry)
        identity_key = _canonical(value['sourceIdentity'])
        if identity_key in identities:
            raise ValueError('duplicate source record')
        identities.add(identity_key)
        normalized.append(value)
    body = {'schemaVersion': 1, 'entries': normalized}
    return dict(body, status='planned', planHash=_hash(body), recordCount=len(normalized))


def check_reconciliation_plan(state_root, plan):
    """Re-read every source and proof without writing, returning a checked plan."""
    root = _root(state_root)
    if not isinstance(plan, dict) or plan.get('status') not in ('planned', 'checked'):
        raise ValueError('prepared reconciliation plan required')
    entries = _validate_normalized(root, plan.get('entries'))
    body = {'schemaVersion': 1, 'entries': entries}
    plan_hash = _hash(body)
    if plan.get('schemaVersion') != 1 or plan.get('planHash') != plan_hash:
        raise ValueError('reconciliation plan hash mismatch')
    return dict(body, status='checked', planHash=plan_hash, recordCount=len(entries))


def _receipt_body(plan, created_at):
    return {'schemaVersion': 1, 'status': 'verified_historical_reconciliation',
            'planHash': plan['planHash'], 'createdAt': created_at,
            'entries': plan['entries']}


def _existing_receipt(path, plan_hash):
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise ValueError('existing reconciliation receipt invalid')
    if (not isinstance(value, dict) or value.get('schemaVersion') != 1
            or value.get('status') != 'verified_historical_reconciliation'
            or value.get('planHash') != plan_hash or set(value) != {
                'schemaVersion', 'status', 'planHash', 'createdAt', 'entries'}):
        raise ValueError('existing reconciliation receipt invalid')
    return value


def apply_reconciliation(state_root, plan, *, now=None):
    """Explicitly add one immutable receipt while holding the existing root lock."""
    root = _root(state_root)
    if not isinstance(plan, dict) or plan.get('status') not in ('planned', 'checked'):
        raise ValueError('prepared reconciliation plan required')
    timestamp = now or datetime.now(JST)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('aware timestamp required')
    created_at = timestamp.astimezone(JST).isoformat()
    lock_path = root / 'runtime.flock'
    with lock_path.open('a') as lease:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('runtime lock busy')
        checked = check_reconciliation_plan(root, plan)
        entries = checked['entries']
        plan_hash = checked['planHash']
        folder = root / RECEIPT_FOLDER
        if folder.exists() and (folder.is_symlink() or not folder.is_dir()):
            raise ValueError('safe reconciliation folder required')
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
        target = folder / (plan_hash + '.json')
        if target.exists():
            existing = _existing_receipt(target, plan_hash)
            try:
                existing_entries = _validate_normalized(root, existing.get('entries'))
                if (_hash({'schemaVersion': 1, 'entries': existing_entries}) != plan_hash
                        or existing_entries != entries):
                    raise ValueError('invalid')
                _aware_timestamp(existing.get('createdAt'))
            except ValueError:
                raise ValueError('existing reconciliation receipt invalid')
            return {'status': 'already_applied', 'receiptId': plan_hash,
                    'recordCount': len(entries)}
        receipt = _receipt_body(checked, created_at)
        raw = (_canonical(receipt) + '\n').encode('utf-8')
        temporary = folder / ('.' + plan_hash + '.' + str(os.getpid()) + '.tmp')
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(str(temporary), str(target))
            except FileExistsError:
                _existing_receipt(target, plan_hash)
                return {'status': 'already_applied', 'receiptId': plan_hash,
                        'recordCount': len(entries)}
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        directory = os.open(str(folder), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return {'status': 'applied', 'receiptId': plan_hash, 'recordCount': len(entries)}


def project_reconciliations(state_root):
    """Pure read projection; invalid or stale receipts never suppress old records."""
    root = _root(state_root)
    counts = {name: 0 for name in RECORD_TYPES.values()}
    result = {'schemaVersion': 1, 'status': 'read_only', 'readOnly': True,
              'historicalReconciledCounts': counts, 'reconciledSources': [],
              'receiptCount': 0, 'invalidReceiptCount': 0, 'truncated': False}
    folder = root / RECEIPT_FOLDER
    if not folder.exists():
        return result
    if folder.is_symlink() or not folder.is_dir():
        return dict(result, status='diagnostic_error', invalidReceiptCount=1)
    files = sorted(folder.glob('*.json'))
    if len(files) > MAX_RECEIPTS:
        files = files[:MAX_RECEIPTS]
        result['truncated'] = True
    seen = set()
    for path in files:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError('invalid receipt')
            receipt = json.loads(path.read_bytes())
            if (not isinstance(receipt, dict) or receipt.get('schemaVersion') != 1
                    or receipt.get('status') != 'verified_historical_reconciliation'
                    or path.stem != receipt.get('planHash')):
                raise ValueError('invalid receipt')
            _aware_timestamp(receipt.get('createdAt'))
            entries = _validate_normalized(root, receipt.get('entries'))
            proof_values = [[_proof_projection(root, proof)
                             for proof in entry['proofs']] for entry in entries]
            expected = _hash({'schemaVersion': 1, 'entries': entries})
            if receipt.get('planHash') != expected:
                raise ValueError('invalid receipt hash')
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            result['invalidReceiptCount'] += 1
            continue
        result['receiptCount'] += 1
        for entry, proofs in zip(entries, proof_values):
            identity_key = _canonical(entry['sourceIdentity'])
            if identity_key in seen:
                continue
            seen.add(identity_key)
            counts[RECORD_TYPES[entry['recordType']]] += 1
            result['reconciledSources'].append({
                'recordType': entry['recordType'], 'jobId': entry['jobId'],
                'revision': entry['revision'], 'sourceIdentity': entry['sourceIdentity'],
                'resolution': 'historical_reconciled', 'proofs': proofs,
            })
    if result['invalidReceiptCount']:
        result['status'] = 'diagnostic_error'
    return result
