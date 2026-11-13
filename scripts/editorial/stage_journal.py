"""Bounded, crash-safe stage memoization in the authoritative editorial ledger.

Only canonical JSON hashes of inputs are persisted.  Successful outputs remain in
the ledger's private ``meta`` table; status views never expose their contents.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3


JST = timezone(timedelta(hours=9))
PREFIX = 'stage_journal:v1:'
SCHEMA = 1
_NORMALIZABLE_PATHS = {
    ('checkedAt',),
    ('article', 'createdAt'),
    ('article', 'updatedAt'),
    ('preview', 'path'),
}
_USAGE_RECORD_KEYS = {
    'responseId', 'model', 'requestedModel', 'actualModel', 'input', 'output',
    'usage', 'actualUSD', 'actualInvoiceUsd',
}
_USAGE_TOKEN_KEYS = {
    'input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens',
    'cached_input_tokens', 'cache_read_input_tokens', 'cache_write_input_tokens',
    'reasoning_tokens', 'reasoning_output_tokens', 'total_tokens',
    'cache_creation_input_tokens',
}
_CACHE_CREATION_KEYS = {'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'}


class StageBlocked(RuntimeError):
    """The stage has a known failure and requires an explicit bounded retry."""

    def __init__(self, message, *, stage_key=None, status='failed'):
        super().__init__(message)
        self.stage_key = stage_key
        self.status = status


class StageUnknown(RuntimeError):
    """A prior reservation may have produced an unknown external outcome."""

    def __init__(self, message, *, stage_key=None, status='in_flight'):
        super().__init__(message)
        self.stage_key = stage_key
        self.status = status


@dataclass(frozen=True)
class OperationResult:
    """Optional operation wrapper for attaching a measured-usage reference."""

    output: object
    usage_reference: object = None


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('stage journal values must be canonical JSON') from exc


def _json_copy(value):
    return json.loads(_canonical(value))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _now():
    return datetime.now(JST).isoformat()


def _usage_copy(records):
    raw_records = _json_copy(records)
    if not isinstance(raw_records, list):
        raise ValueError('usage records must be a JSON list')
    clean = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise ValueError('usage record must be an object')
        record = {key: copy.deepcopy(raw[key]) for key in _USAGE_RECORD_KEYS if key in raw}
        for name in ('responseId', 'model', 'requestedModel', 'actualModel'):
            if name in record and record[name] is not None and not isinstance(record[name], str):
                raise ValueError('usage identity must be a string or null')
        for name in ('input', 'output'):
            if name in record and (type(record[name]) is not int or record[name] < 0):
                raise ValueError('usage count must be a non-negative integer')
        for name in ('actualUSD', 'actualInvoiceUsd'):
            if name in record and record[name] is not None and (
                    isinstance(record[name], bool) or not isinstance(record[name], (int, float))
                    or record[name] < 0):
                raise ValueError('usage cost must be a non-negative number or null')
        usage = raw.get('usage')
        if usage is not None:
            if not isinstance(usage, dict):
                raise ValueError('usage metadata must be an object')
            projected = {key: usage[key] for key in _USAGE_TOKEN_KEYS if key in usage}
            cache_creation = usage.get('cache_creation')
            if isinstance(cache_creation, dict):
                projected['cache_creation'] = {
                    key: cache_creation[key] for key in _CACHE_CREATION_KEYS
                    if key in cache_creation
                }
            flat = [value for key, value in projected.items() if key != 'cache_creation']
            nested = list(projected.get('cache_creation', {}).values())
            if any(type(value) is not int or value < 0 for value in flat + nested):
                raise ValueError('usage metadata must contain non-negative integers')
            record['usage'] = projected
        clean.append(record)
    return clean


def normalize_dependencies(dependencies, *, omit_paths=()):
    """Return a JSON copy with only explicitly opted-in observational paths removed.

    Paths are tuples (or dotted strings) from a deliberately small allow-list.
    Nothing is stripped by default, and matching names nested elsewhere remain.
    """
    value = _json_copy(dependencies)
    normalized = []
    for raw in omit_paths:
        path = tuple(raw.split('.')) if isinstance(raw, str) else tuple(raw)
        if path not in _NORMALIZABLE_PATHS:
            raise ValueError('unsafe dependency normalization path')
        normalized.append(path)
    for path in normalized:
        parent = value
        for part in path[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                parent = None
                break
            parent = parent[part]
        if isinstance(parent, dict):
            parent.pop(path[-1], None)
    return value


def _parts(inputs):
    value = _json_copy(inputs)
    if not isinstance(value, dict):
        raise ValueError('stage inputs must be a JSON object')
    if 'dependencies' not in value or 'schemaVersion' not in value:
        raise ValueError('dependencies and schemaVersion are required')
    dependencies = value.pop('dependencies')
    schema_version = value.pop('schemaVersion')
    return value, dependencies, schema_version


def _identity(job_id, stage, inputs):
    if not isinstance(job_id, str) or not job_id or not isinstance(stage, str) or not stage:
        raise ValueError('non-empty job_id and stage required')
    payload, dependencies, schema_version = _parts(inputs)
    hashes = {
        'inputHash': _hash(payload),
        'dependencyHash': _hash(dependencies),
        'schemaHash': _hash(schema_version),
    }
    digest = _hash({'jobId': job_id, 'stage': stage, **hashes})
    return PREFIX + digest, hashes


def _public(record):
    return {key: copy.deepcopy(record.get(key)) for key in (
        'stageKey', 'jobId', 'stage', 'status', 'attempts', 'maxAttempts',
        'inputHash', 'dependencyHash', 'schemaHash', 'createdAt', 'updatedAt',
        'failureType', 'usageReferencePresent', 'responseReceiptCount',
        'missingUsageAttemptCount', 'missingUsage', 'cacheHits') if key in record}


def read_status(db_path, *, job_id=None, stage=None):
    """Read content-free journal status directly without constructing Runtime."""
    path = Path(db_path).resolve()
    uri = 'file:' + str(path).replace('?', '%3f').replace('#', '%23') + '?mode=ro'
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        rows = db.execute('SELECT value FROM meta WHERE key LIKE ?', (PREFIX + '%',)).fetchall()
    records = []
    corrupt = 0
    for (raw,) in rows:
        try:
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            corrupt += 1
            continue
        if job_id is not None and record.get('jobId') != job_id:
            continue
        if stage is not None and record.get('stage') != stage:
            continue
        records.append(_public(record))
    records.sort(key=lambda item: (item.get('jobId', ''), item.get('stage', ''),
                                   item.get('createdAt', ''), item.get('stageKey', '')))
    counts = {}
    for record in records:
        name = record.get('status', 'corrupt')
        counts[name] = counts.get(name, 0) + 1
    if corrupt:
        counts['corrupt'] = corrupt
    by_stage = {}
    for record in records:
        item = by_stage.setdefault(record.get('stage', ''), {
            'stageAttempts': 0, 'responseReceipts': 0, 'missingUsageAttempts': 0,
            'hits': 0, 'records': 0,
        })
        item['stageAttempts'] += record.get('attempts', 0)
        item['responseReceipts'] += record.get('responseReceiptCount', 0)
        item['missingUsageAttempts'] += record.get('missingUsageAttemptCount', 0)
        item['hits'] += record.get('cacheHits', 0)
        item['records'] += 1
    return {'schemaVersion': SCHEMA, 'counts': counts, 'byStage': by_stage, 'records': records}


class StageJournal:
    """Persist stage reservations/results using a Ledger's transaction and tables."""

    def __init__(self, ledger):
        if not hasattr(ledger, '_tx') or not hasattr(ledger, '_event') or not hasattr(ledger, 'db_path'):
            raise TypeError('authoritative ledger required')
        self.ledger = ledger

    @staticmethod
    def key(job_id, stage, inputs):
        return _identity(job_id, stage, inputs)[0]

    def status(self, *, job_id=None, stage=None):
        return read_status(self.ledger.db_path, job_id=job_id, stage=stage)

    def run(self, job_id, stage, inputs, operation, *, max_attempts=2):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise ValueError('max_attempts must be 1 or 2')
        key, hashes = _identity(job_id, stage, inputs)
        with self.ledger._tx() as db:
            self._block_other_in_flight(db, job_id, stage, key)
            record = self._load(db, key)
            if record is not None:
                result = self._existing(record, key)
                record['cacheHits'] = record.get('cacheHits', 0) + 1
                record['updatedAt'] = _now()
                self._save(db, key, record)
                self.ledger._event(db, job_id, 'stage_cache_hit', _public(record))
                return result
            now = _now()
            record = dict(schemaVersion=SCHEMA, stageKey=key, jobId=job_id, stage=stage,
                          status='in_flight', attempts=1, maxAttempts=max_attempts,
                          createdAt=now, updatedAt=now, responseReceiptCount=0,
                          missingUsageAttemptCount=0, missingUsage=False, cacheHits=0, **hashes)
            self._save(db, key, record)
            self.ledger._event(db, job_id, 'stage_reserved', _public(record))
        return self._operate(key, record, operation)

    def record_usage(self, job_id, stage, input_key, records, *, reason='initial'):
        """Attach an exact measured usage slice, including failed-attempt responses.

        No model identity or token value is inferred or normalized.  Empty slices
        are valid and retained as evidence that the caller observed no new records.
        """
        if reason not in ('initial', 'explicit_retry'):
            raise ValueError('usage reason must be initial or explicit_retry')
        clean = _usage_copy(records)
        usage_missing = not clean or any(record.get('usage') is None for record in clean)
        with self.ledger._tx() as db:
            record = self._load(db, input_key)
            if record is None or record.get('jobId') != job_id or record.get('stage') != stage:
                raise StageUnknown('exact stage usage target not found', stage_key=input_key,
                                   status='missing')
            batches = record.setdefault('usageBatches', [])
            batches.append({'reason': reason, 'recordedAt': _now(), 'records': clean,
                            'usageMissing': usage_missing})
            record['responseReceiptCount'] = record.get('responseReceiptCount', 0) + len(clean)
            if usage_missing:
                record['missingUsageAttemptCount'] = record.get('missingUsageAttemptCount', 0) + 1
                record['missingUsage'] = True
            record['updatedAt'] = _now()
            self._save(db, input_key, record)
            event = _public(record)
            event.update(reason=reason, responseReceiptCount=len(clean), usageMissing=usage_missing)
            self.ledger._event(db, job_id, 'stage_usage_recorded', event)

    def retry_failed(self, job_id, stage, inputs, operation):
        """Explicitly retry the same known-failed key, without resetting its counter."""
        key, hashes = _identity(job_id, stage, inputs)
        with self.ledger._tx() as db:
            self._block_other_in_flight(db, job_id, stage, key)
            record = self._load(db, key)
            if record is None or any(record.get(name) != value for name, value in hashes.items()):
                raise StageBlocked('no known failure for exact stage input', stage_key=key, status='missing')
            if record.get('status') == 'in_flight':
                raise StageUnknown('stage outcome requires reconciliation', stage_key=key)
            if record.get('status') != 'failed':
                raise StageBlocked('only known failures may be retried', stage_key=key,
                                   status=record.get('status'))
            if record.get('attempts', 0) >= min(2, record.get('maxAttempts', 0)):
                raise StageBlocked('stage retry limit reached', stage_key=key, status='exhausted')
            record['attempts'] += 1
            record['status'] = 'in_flight'
            record['updatedAt'] = _now()
            record.pop('failureType', None)
            self._save(db, key, record)
            self.ledger._event(db, job_id, 'stage_retry_reserved', _public(record))
        return self._operate(key, record, operation)

    def reconcile_in_flight(self, job_id, stage, inputs, *, outcome,
                            output=None, usage_reference=None):
        """Explicitly resolve an unknown reservation as succeeded or failed."""
        if outcome not in ('succeeded', 'failed'):
            raise ValueError('reconciliation outcome must be succeeded or failed')
        key, hashes = _identity(job_id, stage, inputs)
        with self.ledger._tx() as db:
            record = self._load(db, key)
            if record is None or any(record.get(name) != value for name, value in hashes.items()):
                raise StageUnknown('exact in-flight stage reservation not found', stage_key=key,
                                   status='missing')
            if record.get('status') != 'in_flight':
                raise StageBlocked('only in-flight stages may be reconciled', stage_key=key,
                                   status=record.get('status'))
            if outcome == 'succeeded':
                clean = _json_copy(output)
                record.update(status='succeeded', output=clean, outputHash=_hash(clean),
                              usageReferencePresent=usage_reference is not None)
                if usage_reference is not None:
                    record['usageReference'] = _json_copy(usage_reference)
            else:
                record.update(status='failed', failureType='reconciled_failure',
                              usageReferencePresent=usage_reference is not None)
                if usage_reference is not None:
                    record['usageReference'] = _json_copy(usage_reference)
            record['updatedAt'] = _now()
            self._save(db, key, record)
            self.ledger._event(db, job_id, 'stage_reconciled', _public(record))
        return _json_copy(output) if outcome == 'succeeded' else None

    def _operate(self, key, reserved, operation):
        try:
            raw = operation()
            if isinstance(raw, OperationResult):
                output, usage_reference = raw.output, raw.usage_reference
            else:
                output, usage_reference = raw, None
            clean = _json_copy(output)
            usage = _json_copy(usage_reference) if usage_reference is not None else None
        except StageUnknown:
            # The operation may have crossed an external side-effect boundary.
            # Preserve its reservation until an operator explicitly reconciles it.
            raise
        except Exception as exc:
            if getattr(exc, 'outcome_unknown', False) is True:
                raise StageUnknown('stage operation outcome requires reconciliation',
                                   stage_key=key) from None
            with self.ledger._tx() as db:
                record = self._load(db, key)
                if record is not None and record.get('status') == 'in_flight':
                    record.update(status='failed', failureType=type(exc).__name__, updatedAt=_now(),
                                  usageReferencePresent=False)
                    self._save(db, key, record)
                    self.ledger._event(db, record['jobId'], 'stage_failed', _public(record))
            raise
        # BaseException deliberately bypasses this handler, preserving in_flight.
        with self.ledger._tx() as db:
            record = self._load(db, key)
            if record is None or record.get('status') != 'in_flight':
                raise StageUnknown('stage reservation changed during operation', stage_key=key)
            record.update(status='succeeded', output=clean, outputHash=_hash(clean),
                          updatedAt=_now(), usageReferencePresent=usage is not None)
            if usage is not None:
                record['usageReference'] = usage
            self._save(db, key, record)
            self.ledger._event(db, record['jobId'], 'stage_succeeded', _public(record))
        return _json_copy(clean)

    def _existing(self, record, key):
        status = record.get('status')
        if status == 'succeeded':
            if 'output' not in record or record.get('outputHash') != _hash(record['output']):
                raise StageUnknown('cached stage output integrity failure', stage_key=key,
                                   status='corrupt')
            return _json_copy(record['output'])
        if status == 'in_flight':
            raise StageUnknown('stage outcome requires reconciliation', stage_key=key)
        if status == 'failed':
            raise StageBlocked('stage has a known failure; explicit retry required', stage_key=key)
        raise StageUnknown('unknown stage journal status', stage_key=key, status='corrupt')

    def _block_other_in_flight(self, db, job_id, stage, key):
        for meta_key, raw in db.execute('SELECT key,value FROM meta WHERE key LIKE ?', (PREFIX + '%',)):
            if meta_key == key:
                continue
            try:
                record = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                raise StageUnknown('corrupt stage journal record', stage_key=meta_key,
                                   status='corrupt') from None
            if not isinstance(record, dict) or record.get('status') not in (
                    'in_flight', 'failed', 'succeeded'):
                raise StageUnknown('unknown stage journal status', stage_key=meta_key,
                                   status='corrupt')
            if (isinstance(record, dict) and record.get('jobId') == job_id
                    and record.get('stage') == stage and record.get('status') == 'in_flight'):
                raise StageUnknown('previous stage input requires reconciliation',
                                   stage_key=record.get('stageKey'))

    @staticmethod
    def _load(db, key):
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[0])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StageUnknown('corrupt stage journal record', stage_key=key, status='corrupt') from exc
        if not isinstance(value, dict) or value.get('stageKey') != key:
            raise StageUnknown('corrupt stage journal record', stage_key=key, status='corrupt')
        return value

    @staticmethod
    def _save(db, key, record):
        db.execute('INSERT INTO meta(key,value) VALUES (?,?) '
                   'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (key, _canonical(record)))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read content-free stage journal status')
    parser.add_argument('database')
    parser.add_argument('--job-id')
    parser.add_argument('--stage')
    args = parser.parse_args(argv)
    print(_canonical(read_status(args.database, job_id=args.job_id, stage=args.stage)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
