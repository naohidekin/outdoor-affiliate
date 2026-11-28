"""One bounded repair for a fully received, settled, all-invalid research response.

The first response is archived verbatim and never reused as proposal input.  A
repair right is consumed transactionally before the normal producer gathers a
fresh context and performs its one additional API request.
"""
from collections import Counter
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3

from ledger import JST, Ledger, fingerprint
from model_budget import _config, _usage
from models import Models, _strict_json
from production_schedule import ProductionSchedule
from regular_backfill import pending, regular
from runtime import atomic
from topic_selection import TopicSelectionError, validate_proposals


VERSION = 1
OWNER_AUTHORIZATION = 'owner-20261128-bounded-recurring-mixed-research-repair'
FILES = ('research_response_recovery.py', 'runtime.py', 'models.py', 'topic_selection.py',
         'model_budget.py', 'production_schedule.py', 'regular_backfill.py')
LOADED = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
          for name in FILES}
_FEEDBACK_CODES = {'proposal_contract', 'proposal_contract_type', 'proposal_fields',
    'proposal_product_route', 'overlap_id_not_in_supplied_articles', 'new_has_overlap',
    'update_has_no_target', 'query_over_500', 'readerQuestion_over_500',
    'overlapRationale_over_500', 'selectionReason_over_500'}


def require(value, code):
    if not value:
        raise ValueError(code)


def key(period):
    require(isinstance(period, str) and period, 'research_response_repair_period_required')
    return 'research_response_recovery:v1:' + period


def _read(path):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and path.stat().st_size <= 2 * 1024 * 1024
            and not any(item.is_symlink() for item in (path, *path.parents)),
            'research_response_repair_unsafe_file')
    raw = path.read_bytes()
    value = _strict_json(raw.decode('utf-8'))
    require(isinstance(value, dict), 'research_response_repair_object_required')
    return value, raw, hashlib.sha256(raw).hexdigest()


def _protocol():
    files = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
             for name in FILES}
    require(files == LOADED, 'research_response_repair_protocol_changed_restart_required')
    return {'files': files, 'authorization': OWNER_AUTHORIZATION}


def _paths(root, period, response_id):
    return {
        'marker': root / 'production-attempts' / (period + '.json'),
        'artifact': root / 'model-artifacts' /
            (hashlib.sha256(response_id.encode('utf-8')).hexdigest() + '.json'),
        'context': root / 'research-contexts' / (period + '.json'),
    }


def _feedback(marker):
    counts = Counter()
    for rejection in marker.get('contractRejections', []):
        if not isinstance(rejection, dict):
            continue
        codes = rejection.get('details') or [rejection.get('reason')]
        for code in codes:
            if code in _FEEDBACK_CODES:
                counts[code] += 1
    if not counts:
        counts['proposal_contract'] = marker['rawProposalCount']
    value = {'kind': 'all_invalid_contract_repair', 'invalidCount': marker['rawProposalCount'],
             'codes': [code + ':' + str(counts[code]) for code in sorted(counts)]}
    require(len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))) <= 300,
            'research_response_repair_feedback_too_large')
    return value


def _all_invalid(artifact, context, marker):
    Models({})._safe_public(artifact)
    raw = _strict_json(artifact.get('content', ''))
    proposals = raw.get('proposals') if set(raw) == {'proposals'} else None
    require(isinstance(proposals, list) and len(proposals) == marker.get('rawProposalCount')
            and proposals, 'research_response_repair_artifact_mismatch')
    catalog_ids = {row['id'] for row in context.get('catalog', [])
                   if isinstance(row, dict) and isinstance(row.get('id'), str) and row['id']}
    existing_ids = {row['id'] for row in context.get('existingArticles', [])
                    if isinstance(row, dict) and isinstance(row.get('id'), str) and row['id']}
    category_ids = {row['id'] for row in context.get('categories', [])
                    if isinstance(row, dict) and isinstance(row.get('id'), str) and row['id']}
    invalid = 0
    for proposal in proposals:
        try:
            validate_proposals([proposal], catalog_ids=catalog_ids, existing_ids=existing_ids,
                               category_ids=category_ids)
        except (TopicSelectionError, TypeError):
            invalid += 1
    require(invalid == len(proposals), 'research_response_repair_valid_proposal_present')


def _inspect(config, config_sha256, root, *, period, response_id, marker_sha256,
             artifact_sha256, context_sha256, now, source_paths=None):
    require(isinstance(response_id, str) and response_id and len(response_id) <= 160,
            'research_response_repair_response_required')
    schedule = ProductionSchedule(config.get('productionSchedule'))
    require(schedule.period_key(now) == period, 'research_response_repair_current_period_required')
    limits = _config(config.get('modelBudget'))
    require(limits['article']['calls'] == 32 and limits['period']['calls'] == 128,
            'research_response_repair_existing_budget_required')
    root = Path(root)
    database = root / 'ledger.sqlite3'
    require(root.is_absolute() and root.resolve() not in (Path('/'), Path.home())
            and database.is_file() and not any(item.is_symlink() for item in (database, *database.parents)),
            'research_response_repair_unsafe_ledger')
    paths = source_paths or _paths(root, period, response_id)
    marker, _, marker_digest = _read(paths['marker'])
    artifact, _, artifact_digest = _read(paths['artifact'])
    context, _, context_digest = _read(paths['context'])
    require(marker_digest == marker_sha256 and artifact_digest == artifact_sha256
            and context_digest == context_sha256, 'research_response_repair_input_drift')
    rejections = marker.get('contractRejections')
    require(marker.get('status') == 'research_contract_rejected'
            and marker.get('period') == period and marker.get('responseId') == response_id
            and marker.get('requestOccurred') is True and marker.get('retryable') is False
            and isinstance(marker.get('rawProposalCount'), int) and marker['rawProposalCount'] > 0
            and isinstance(rejections, list) and len(rejections) == marker['rawProposalCount']
            and {item.get('index') for item in rejections if isinstance(item, dict)}
                == set(range(marker['rawProposalCount']))
            and marker.get('researchContextSha256') == fingerprint(context),
            'research_response_repair_known_all_invalid_marker_required')
    usage = _usage(artifact.get('usage'))
    require(artifact.get('responseId') == response_id and isinstance(artifact.get('model'), str)
            and artifact['model'] and usage is not None,
            'research_response_repair_exact_response_required')
    _all_invalid(artifact, context, marker)
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(
            'SELECT * FROM model_budget_reservations WHERE article_id=? AND period_key=?',
            ('research:' + period, period))]
        require(len(rows) == 1, 'research_response_repair_single_settled_research_required')
        row = rows[0]
        require(row['response_id'] == response_id and row['stage'] == 'research'
                and row['model'] == artifact['model'] and row['status'] == 'settled'
                and row['outcome'] == 'success'
                and (row['actual_input_tokens'], row['actual_output_tokens']) == usage,
                'research_response_repair_budget_response_binding')
        jobs = [json.loads(item[0]) for item in db.execute('SELECT data FROM jobs')]
        require(not any(regular(job) and job.get('week') == period for job in jobs)
                and sum(pending(job) for job in jobs) < 3,
                'research_response_repair_pending_or_period_cap')
        require(db.execute('SELECT 1 FROM meta WHERE key=?',
                           ('regular_selection:v1:' + period,)).fetchone() is None
                and not (root / 'period-receipts' / (period + '.json')).exists()
                and not (root / 'existing-update-proposals' / (period + '.json')).exists(),
                'research_response_repair_selection_already_exists')
    return {'schemaVersion': VERSION, 'period': period, 'stateRoot': str(root),
            'configSha256': config_sha256, 'runtimeConfigSha256': fingerprint(config),
            'protocol': _protocol(),
            'capsSha256': fingerprint(limits), 'maxRepairs': 1,
            'firstFailure': {'code': 'all_proposals_contract_invalid', 'responseId': response_id,
                'markerSha256': marker_sha256, 'artifactSha256': artifact_sha256,
                'contextSha256': context_sha256, 'budgetReservationSha256': fingerprint(row)},
            'feedback': _feedback(marker), 'oldProposalUse': 'none',
            'freshContextRequired': True}


def prepare(config_path, *, period, response_id, config_sha256, marker_sha256,
            artifact_sha256, context_sha256, owner_reference, now=None):
    """Read-only preparation for an already existing known response."""
    config, _, digest = _read(config_path)
    require(digest == config_sha256, 'research_response_repair_config_drift')
    require(isinstance(owner_reference, str) and owner_reference and len(owner_reference) <= 160,
            'research_response_repair_owner_reference_required')
    manifest = _inspect(config, digest, Path(config['stateRoot']), period=period,
        response_id=response_id, marker_sha256=marker_sha256, artifact_sha256=artifact_sha256,
        context_sha256=context_sha256, now=now or datetime.now(JST))
    manifest.update(configPath=str(Path(config_path)), ownerReference=owner_reference)
    return manifest


def owner_grant(manifest):
    first = manifest['firstFailure']
    return {'authorization': OWNER_AUTHORIZATION, 'reference': manifest['ownerReference'],
            'configSha256': manifest['configSha256'], 'markerSha256': first['markerSha256'],
            'artifactSha256': first['artifactSha256'], 'contextSha256': first['contextSha256'],
            'manifestSha256': fingerprint(manifest)}


def _archive(root, period):
    path = root / 'research-response-recovery' / period
    require(not any(item.is_symlink() for item in (path, *path.parents)),
            'research_response_repair_unsafe_archive')
    return path


def _write_archive(root, manifest, paths):
    archive = _archive(root, manifest['period'])
    require(not archive.exists(), 'research_response_repair_already_armed_requires_reconciliation')
    archive.mkdir(parents=True)
    for target, source in (('first-marker.json', paths['marker']),
                           ('first-artifact.json', paths['artifact']),
                           ('first-context.json', paths['context'])):
        with (archive / target).open('xb') as output:
            output.write(Path(source).read_bytes())
    return archive


def _ready(manifest):
    return {'status': 'retry_ready', 'period': manifest['period'],
            'researchResponseRecoveryKey': key(manifest['period']),
            'manifestSha256': fingerprint(manifest)}


def _store_ready(runtime, manifest, paths):
    period, root = manifest['period'], runtime.root
    expected_marker = manifest['firstFailure']['markerSha256']
    current = Path(paths['marker']).read_bytes()
    require(hashlib.sha256(current).hexdigest() == expected_marker,
            'research_response_repair_marker_cas_failed')
    archive = _write_archive(root, manifest, paths)
    ready = _ready(manifest)
    receipt = {'status': 'retry_ready', 'manifest': manifest, 'feedback': manifest['feedback'],
               'repairsUsed': 0, 'maxRepairs': 1, 'readyMarker': ready}
    with runtime.ledger._tx() as db:
        require(db.execute('SELECT 1 FROM meta WHERE key=?', (key(period),)).fetchone() is None,
                'research_response_repair_already_claimed')
        db.execute('INSERT INTO meta VALUES (?,?)', (key(period), json.dumps(receipt)))
    atomic(archive / 'receipt.json', receipt)
    current = Path(paths['marker']).read_bytes()
    require(hashlib.sha256(current).hexdigest() == expected_marker,
            'research_response_repair_marker_cas_failed')
    atomic(paths['marker'], ready)
    return {'status': 'retry_ready', 'armed': True, 'period': period}


def arm_runtime(runtime, period, marker, *, now=None):
    """Arm a newly observed all-invalid response from the normal producer."""
    response_id = marker.get('responseId')
    paths = _paths(runtime.root, period, response_id)
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    config_sha = fingerprint(runtime.config)
    manifest = _inspect(runtime.config, config_sha, runtime.root, period=period,
        response_id=response_id, marker_sha256=digests['marker'], artifact_sha256=digests['artifact'],
        context_sha256=digests['context'], now=now or datetime.now(JST))
    manifest.update(configPath=None, ownerReference=OWNER_AUTHORIZATION)
    return _store_ready(runtime, manifest, paths)


def arm(config_path, manifest, *, owner_grant, now=None):
    require(owner_grant == globals()['owner_grant'](manifest),
            'research_response_repair_owner_instruction_required')
    config, _, digest = _read(config_path)
    require(digest == manifest['configSha256'] and manifest.get('configPath') == str(Path(config_path)),
            'research_response_repair_config_drift')
    root = Path(config['stateRoot'])
    first = manifest['firstFailure']
    current = prepare(config_path, period=manifest['period'], response_id=first['responseId'],
        config_sha256=digest, marker_sha256=first['markerSha256'],
        artifact_sha256=first['artifactSha256'], context_sha256=first['contextSha256'],
        owner_reference=manifest['ownerReference'], now=now)
    require(current == manifest, 'research_response_repair_manifest_changed')
    with (root / 'runtime.flock').open('a') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy', 'armed': False}
        view = type('RuntimeView', (), {})()
        view.root = root
        view.ledger = Ledger(root, config['slack']['user_id'],
                             production_schedule=config.get('productionSchedule'),
                             target_account_id=config.get('targetAccountId'))
        return _store_ready(view, manifest, _paths(root, manifest['period'], first['responseId']))


def _archived_paths(root, period):
    archive = _archive(root, period)
    return {'marker': archive / 'first-marker.json', 'artifact': archive / 'first-artifact.json',
            'context': archive / 'first-context.json'}


def consume(runtime, period, marker):
    """Consume the right before any fresh external request."""
    recovery_key = key(period)
    require(marker.get('researchResponseRecoveryKey') == recovery_key,
            'research_response_repair_wrong_marker')
    with runtime.ledger._tx() as db:
        row = db.execute('SELECT value FROM meta WHERE key=?', (recovery_key,)).fetchone()
        require(row is not None, 'research_response_repair_receipt_missing')
        receipt = json.loads(row[0])
        require(receipt['status'] == 'retry_ready' and receipt['repairsUsed'] == 0
                and marker == receipt['readyMarker'], 'research_response_repair_already_consumed')
        manifest = receipt['manifest']
        require(manifest['protocol'] == _protocol()
                and fingerprint(runtime.config) == manifest['runtimeConfigSha256'],
                'research_response_repair_runtime_config_changed')
        first = manifest['firstFailure']
        checked = _inspect(runtime.config, manifest['configSha256'], runtime.root, period=period,
            response_id=first['responseId'], marker_sha256=first['markerSha256'],
            artifact_sha256=first['artifactSha256'], context_sha256=first['contextSha256'],
            now=datetime.now(JST), source_paths=_archived_paths(runtime.root, period))
        for field in ('schemaVersion', 'period', 'stateRoot', 'configSha256', 'runtimeConfigSha256',
                      'protocol', 'capsSha256',
                      'maxRepairs', 'firstFailure', 'feedback', 'oldProposalUse', 'freshContextRequired'):
            require(checked[field] == manifest[field], 'research_response_repair_manifest_changed')
        receipt.update(status='consumed', repairsUsed=1)
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(receipt), recovery_key))
        runtime.ledger._event(db, 'research:' + period, 'research_response_repair_consumed',
                              {'responseId': first['responseId'], 'repairsUsed': 1})
    atomic(_archive(runtime.root, period) / 'receipt.json', receipt)
    return {'key': recovery_key, 'feedback': receipt['feedback']}


def finish(runtime, marker, period):
    recovery_key = key(period)
    with runtime.ledger._tx() as db:
        row = db.execute('SELECT value FROM meta WHERE key=?', (recovery_key,)).fetchone()
        require(row is not None, 'research_response_repair_receipt_missing')
        receipt = json.loads(row[0])
        require(receipt['status'] == 'consumed' and receipt['repairsUsed'] == 1,
                'research_response_repair_not_consumed')
        receipt.update(status='completed' if marker.get('status') == 'generated' else 'held',
                       resultStatus=marker.get('status', 'unknown'))
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(receipt), recovery_key))
    atomic(_archive(runtime.root, period) / 'receipt.json', receipt)
