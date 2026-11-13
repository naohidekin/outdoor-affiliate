"""Bounded, content-free inspection of editorial records. Never mutates state."""
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote


MAX_ROWS = 1000
MAX_FILES = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
FOLDERS = ('social-publications', 'social-posted-notices', 'production-attempts',
           'revision-production-attempts', 'post-publication-audits', 'index-tracking')
UNRESOLVED = {'unknown', 'in_flight'}
MANAGER_UNRESOLVED = {'evaluating', 'executing', 'requires_reconciliation'}
COMPLETE = {'verified', 'delivered', 'completed', 'generated', 'success', 'posted', 'indexed'}


def _root(value):
    root = Path(value)
    if not root.is_absolute() or root.resolve() in (Path('/'), Path.home().resolve()):
        raise ValueError('safe absolute state root required')
    return root.resolve()


def _safe(value, limit=160):
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _json_file(path):
    if path.is_symlink():
        raise ValueError('symlink')
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise OverflowError('oversized')
    with path.open('r', encoding='utf-8') as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError('object_required')
    return value


def _verified_parts(request):
    parts = request.get('parts')
    if isinstance(parts, dict):
        parts = parts.get('parts')
    return bool(isinstance(parts, list) and parts and
                all(isinstance(part, dict) and part.get('verified') is True for part in parts))


def _folder_summary(root, name, diagnostics, budget, revision_jobs):
    folder = root / name
    if not folder.is_dir() or folder.is_symlink():
        diagnostics.append({'scope': name, 'code': 'folder_missing_or_invalid'})
        return {'kind': name, 'count': None, 'incompleteCount': None,
                'unknownBindingCount': None, 'records': [], 'truncated': False}
    files, scanned = [], 0
    for path in folder.iterdir():
        scanned += 1
        if path.suffix == '.json':
            files.append(path)
        if len(files) > MAX_FILES or scanned > MAX_FILES * 4:
            break
    truncated = len(files) > MAX_FILES or scanned > MAX_FILES * 4 or budget[0] + min(len(files), MAX_FILES) > MAX_FILES * len(FOLDERS)
    records, incomplete, unknown = [], 0, 0
    for path in files[:MAX_FILES]:
        budget[0] += 1
        try:
            value = _json_file(path)
            raw_status = value.get('status') or value.get('phase')
            if name == 'index-tracking' and raw_status is None:
                checks = value.get('checks')
                latest = checks[-1] if isinstance(checks, list) and checks else {}
                if (isinstance(latest, dict) and latest.get('sitemap') == 'current'
                        and latest.get('index') == 'indexed'):
                    raw_status = 'indexed'
            status = raw_status if raw_status in COMPLETE | UNRESOLVED | {
                'requires_reconciliation', 'pending', 'blocked', 'failed', 'unverified', 'mainread'} else 'unknown'
            article_id = next((_safe(value.get(key)) for key in ('articleId', 'jobId', 'id')
                               if _safe(value.get(key))), None)
            if article_id is None:
                article_id = revision_jobs.get(value.get('revision'))
            is_incomplete = status not in COMPLETE
            incomplete += int(is_incomplete)
            unknown += int(article_id is None)
            if is_incomplete and len(records) < 100:
                records.append({'articleId': article_id, 'status': status,
                                'safeReasonCode': name.replace('-', '_') + '_unfinished'})
        except (OSError, ValueError, OverflowError, UnicodeError, RecursionError):
            incomplete += 1
            unknown += 1
            diagnostics.append({'scope': name, 'code': 'receipt_corrupt_or_oversized'})
            if len(records) < 100:
                records.append({'articleId': None, 'status': 'unknown',
                                'safeReasonCode': name.replace('-', '_') + '_unreadable'})
    return {'kind': name, 'count': len(files), 'incompleteCount': incomplete,
            'unknownBindingCount': unknown, 'records': records, 'truncated': truncated}


def _delivery_summary(root, requests, jobs, diagnostics):
    folder = root / 'deliveries'
    missing_folder = not folder.is_dir() or folder.is_symlink()
    if missing_folder:
        diagnostics.append({'scope': 'deliveries', 'code': 'folder_missing_or_invalid'})
    unresolved, historical, unknown = [], 0, 0
    for job_id, kind, raw in requests:
        try:
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            unknown += 1
            continue
        job = jobs.get(job_id) or {}
        current_revision = ((job.get('social') or {}).get('revision') if kind == 'social'
                            else job.get('revision'))
        request_revision = request.get('manifest_hash')
        status = request.get('status')
        old = status in ('invalidated', 'decided') or bool(
            current_revision and request_revision and current_revision != request_revision)
        if old:
            historical += 1
            continue
        marker_status = None
        request_id = request.get('request_id')
        if not missing_folder and isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id):
            marker = folder / (request_id + '.json')
            if marker.is_file():
                try:
                    marker_status = _json_file(marker).get('status')
                except (OSError, ValueError, OverflowError, UnicodeError, RecursionError):
                    marker_status = 'unknown'
        reason = None
        if status == 'delivered':
            if _verified_parts(request) and marker_status != 'delivered':
                reason = 'ledger_delivered_journal_unfinished'
            elif not _verified_parts(request):
                reason = 'legacy_delivery_state_unknown'
        elif status == 'created':
            reason = 'current_delivery_unconfirmed'
        elif status not in ('delivered',):
            reason = 'legacy_delivery_state_unknown'
        if reason:
            unresolved.append({'jobId': _safe(job_id), 'kind': _safe(kind),
                               'status': 'unconfirmed', 'safeReasonCode': reason})
    return {'unresolved': unresolved[:MAX_ROWS], 'historicalNonblockingCount': historical,
            'unknownLegacyCount': unknown, 'truncated': len(unresolved) > MAX_ROWS}


def inspect_records(state_root):
    """Return a JSON-safe operational snapshot from SQLite mode=ro and receipt JSON."""
    root = _root(state_root)
    db_path = root / 'ledger.sqlite3'
    diagnostics = []
    result = {'schemaVersion': 1, 'status': 'diagnostic_error', 'readOnly': True,
              'limits': {'rows': MAX_ROWS, 'filesPerFolder': MAX_FILES,
                         'fileBytes': MAX_FILE_BYTES}, 'truncated': False, 'diagnostics': diagnostics}
    if not db_path.is_file() or db_path.is_symlink():
        diagnostics.append({'scope': 'ledger', 'code': 'ledger_missing_or_invalid'})
        return result
    db = None
    try:
        uri = 'file:' + quote(str(db_path), safe='/') + '?mode=ro'
        db = sqlite3.connect(uri, uri=True, timeout=.2)
        db.execute('PRAGMA query_only=ON')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted({'jobs', 'requests', 'effects', 'meta'} - tables)
        if missing:
            diagnostics.append({'scope': 'ledger', 'code': 'required_tables_missing', 'tables': missing})
            return result
        db.execute('BEGIN')
        job_rows = db.execute('SELECT data FROM jobs WHERE length(CAST(data AS BLOB))<=? ORDER BY rowid LIMIT ?',
                              (MAX_FILE_BYTES, MAX_ROWS + 1)).fetchall()
        request_rows = db.execute('SELECT job_id,kind,data FROM requests WHERE length(CAST(data AS BLOB))<=? '
                                  'ORDER BY rowid LIMIT ?', (MAX_FILE_BYTES, MAX_ROWS + 1)).fetchall()
        effect_rows = db.execute("SELECT substr(job_id,1,161),substr(kind,1,161),status FROM effects WHERE status IN ('unknown','in_flight') "
                                 'ORDER BY job_id,kind LIMIT ?', (MAX_ROWS + 1,)).fetchall()
        meta_rows = db.execute("SELECT substr(key,1,220),value FROM meta WHERE length(CAST(value AS BLOB))<=? AND "
                               "(key LIKE 'editorial_manager:%' OR key LIKE 'editorial_manager_work:%') ORDER BY key LIMIT ?",
                               (MAX_FILE_BYTES, MAX_ROWS + 1)).fetchall()
        oversized = sum(db.execute('SELECT count(*) FROM ' + table +
            ' WHERE length(CAST(' + column + ' AS BLOB))>?', (MAX_FILE_BYTES,)).fetchone()[0]
            for table, column in (('jobs', 'data'), ('requests', 'data'), ('meta', 'value')))
        if oversized:
            diagnostics.append({'scope': 'ledger', 'code': 'record_oversized', 'count': oversized})
        result['truncated'] = any(len(rows) > MAX_ROWS for rows in
                                  (job_rows, request_rows, effect_rows, meta_rows))
        jobs, summaries = {}, []
        for (raw,) in job_rows[:MAX_ROWS]:
            job = json.loads(raw)
            jobs[job.get('id')] = job
            article = ((job.get('bundle') or {}).get('article') or {})
            approval = job.get('approval') or {}
            summaries.append({'id': _safe(job.get('id')), 'title': _safe(article.get('title')) or
                              _safe((job.get('theme') or {}).get('title')), 'stage': _safe(job.get('stage')),
                              'currentRevision': _safe(job.get('revision')),
                              'socialRevision': _safe((job.get('social') or {}).get('revision')),
                              'publicationVerified': (job.get('publication') or {}).get('verified') is True,
                              'approvalCurrent': bool(job.get('revision') and approval.get('revision') == job.get('revision'))})
        result['jobs'] = summaries
        result['unresolvedEffects'] = [{'jobId': _safe(j), 'kind': _safe(k), 'status': s,
            'safeReasonCode': 'effect_outcome_unconfirmed'} for j, k, s in effect_rows[:MAX_ROWS]]
        result['deliveries'] = _delivery_summary(root, request_rows[:MAX_ROWS], jobs, diagnostics)
        executions = {key: 0 for key in MANAGER_UNRESOLVED}
        work = {}
        unknown_manager = 0
        for key, raw in meta_rows[:MAX_ROWS]:
            try:
                value = json.loads(raw)
            except (ValueError, TypeError, RecursionError):
                unknown_manager += 1
                continue
            if key.startswith('editorial_manager_work:'):
                if value.get('status') == 'human_needed':
                    group = (_safe(value.get('action')), _safe(value.get('jobId')),
                             _safe(value.get('revision')))
                    work[group] = work.get(group, 0) + 1
            elif value.get('status') in executions:
                executions[value['status']] += 1
        result['managerExecutions'] = {'counts': executions, 'unknownLegacyCount': unknown_manager}
        result['managerWorkOrders'] = {'status': 'human_needed', 'total': sum(work.values()),
            'groups': [{'action': key[0], 'jobId': key[1], 'revision': key[2], 'count': count}
                       for key, count in sorted(work.items(), key=lambda item: str(item[0]))]}
        budget = [0]
        revision_jobs = {revision: _safe(job_id) for job_id, job in jobs.items() for revision in
                         (job.get('revision'), (job.get('social') or {}).get('revision')) if revision}
        result['receiptFolders'] = [_folder_summary(root, name, diagnostics, budget, revision_jobs)
                                    for name in FOLDERS]
        result['truncated'] |= result['deliveries']['truncated'] or any(
            folder['truncated'] for folder in result['receiptFolders'])
        result['status'] = 'diagnostic_error' if diagnostics else 'read_only'
        return result
    except (OSError, sqlite3.Error, ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        diagnostics.append({'scope': 'ledger', 'code': 'ledger_corrupt_or_unreadable'})
        return result
    finally:
        if db is not None:
            db.close()
