"""One known Nov 20 mixed-research intent-contract repair; no generation here.

prepare reads only, arm archives/pins the known failure and marks retry_ready.
Runtime consumes the durable repair before any fresh research. No refund/rearm,
proposal normalization, selection bypass, new article/budget ID, or publication.
All six intent violations are confirmed; they are not proven to be the only
errors. Old category/product/existing-article memberships remain unverified.
Fresh research must pass full validation against its newly gathered context.
"""
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from ledger import JST, fingerprint
from model_budget import _config, _usage
from models import Models, MIXED_RESEARCH_SCHEMA, _strict_json
from production_schedule import ProductionSchedule
from regular_backfill import pending, regular
from runtime import atomic
from topic_selection import INTENTS, TOPIC_TYPES, UNVERIFIED_FIRSTHAND, _clean_text

PERIOD = '2026-11-20'
RESPONSE_ID = 'msg_011ChDCY4QQ8rXD7wat9ERrk'
ARTIFACT_SHA = '50bda36415e62900671936b0f21b99f6b9a5eaa76c7485814806669a5812f91c'
CONFIG_SHA = 'de79f4c1537eb192df094f18d8deb7d6f8e6cf75877e4776e949456153107cbe'
AUTHORIZATION = 'owner-20261120-regular-vacancy-contract-repair'
OWNER_ANSWER = '通常制作空枠補充整備'
KEY = 'research_contract_recovery:v1:' + PERIOD
FILES = ('research_contract_recovery.py', 'runtime.py', 'models.py', 'topic_selection.py',
         'model_budget.py', 'production_schedule.py', 'regular_backfill.py')
LOADED = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in FILES}


def require(value, code):
    if not value:
        raise ValueError(code)


def read(path):
    path = Path(path)
    require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents))
            and path.is_file() and path.stat().st_size <= 2 * 1024 * 1024, 'research_repair_unsafe_file')
    raw = path.read_bytes()
    value = _strict_json(raw.decode('utf-8'))
    require(isinstance(value, dict), 'research_repair_object_required')
    return value, hashlib.sha256(raw).hexdigest()


def protocol():
    files = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in FILES}
    require(files == LOADED, 'research_repair_protocol_changed_restart_required')
    require(set(MIXED_RESEARCH_SCHEMA['properties']['proposals']['items']['properties']['intent']['enum']) == INTENTS,
            'research_repair_strict_intent_schema_required')
    return {'files': files, 'schemaSha256': fingerprint(MIXED_RESEARCH_SCHEMA)}


def _intent_failure(artifact):
    Models({})._safe_public(artifact)  # JSON/secret boundary only; no transport.
    raw = _strict_json(artifact.get('content', ''))
    require(isinstance(raw, dict) and set(raw) == {'proposals'}
            and isinstance(raw['proposals'], list) and len(raw['proposals']) == 6,
            'research_repair_exact_six_proposals_required')
    properties = MIXED_RESEARCH_SCHEMA['properties']['proposals']['items']['properties']
    for p in raw['proposals']:
        require(isinstance(p, dict) and set(p) == set(properties), 'research_repair_other_contract_failure')
        for key, schema in properties.items():
            value = p[key]
            require((schema['type'] == 'string' and isinstance(value, str))
                    or (schema['type'] == 'array' and isinstance(value, list)
                        and all(isinstance(v, str) for v in value))
                    or (schema['type'] == 'integer' and type(value) is int), 'research_repair_other_contract_failure')
            if key != 'intent' and 'enum' in schema:
                require(value in schema['enum'], 'research_repair_other_contract_failure')
        require(_clean_text(p['intent']) and p['intent'] not in INTENTS, 'research_repair_all_six_intents_required')
        require(1 <= p['priority'] <= 100 and re.fullmatch(r'[a-z0-9][a-z0-9-]{2,79}', p['slug'])
                and _clean_text(p['title'], 80) and not UNVERIFIED_FIRSTHAND.search(p['title'])
                and all(_clean_text(p[k]) for k in ('categoryId', 'query', 'readerQuestion', 'overlapRationale', 'selectionReason'))
                and 3 <= len(p['outline']) <= 5 and all(_clean_text(v, 40) for v in p['outline'])
                and p['sourceIds'] and len(set(p['sourceIds'])) == len(p['sourceIds'])
                and all(_clean_text(v) for k in ('sourceIds', 'productIds', 'overlapArticleIds') for v in p[k])
                and len(set(p['productIds'])) == len(p['productIds'])
                and len(set(p['overlapArticleIds'])) == len(p['overlapArticleIds'])
                and (p['topicType'] != 'product' or p['productIds'])
                and (p['proposedAction'] != 'new' or not p['overlapArticleIds'])
                and (p['proposedAction'] != 'existing_update' or p['overlapArticleIds'])
                and (p['needsStatus'] in ('measured_change', 'seasonal_hypothesis')
                     if p['topicType'] == 'seasonal_problem' else p['needsStatus'] == 'not_applicable'),
                'research_repair_other_contract_failure')
    # No old proposal, source ID, product ID or replacement intent is returned.
    return ['proposals.' + str(i) + '.intent' for i in range(6)]


def _inspect(config_path, marker_sha256, artifact_sha256, *, now=None, archived_marker=None):
    now = now or datetime.now(JST)
    config, config_sha = read(config_path)
    require(config_sha == CONFIG_SHA, 'research_repair_exact_config_required')
    schedule = ProductionSchedule(config.get('productionSchedule'))
    require(schedule.period_key(now) == PERIOD, 'research_repair_current_period_required')
    limits = _config(config.get('modelBudget'))
    require(limits['article']['calls'] <= 32 and limits['period']['calls'] <= 128,
            'research_repair_existing_budget_required')
    root = Path(config['stateRoot'])
    database = root / 'ledger.sqlite3'
    require(root.is_absolute() and root.resolve() not in (Path('/'), Path.home())
            and database.is_file() and not any(p.is_symlink() for p in (database, *database.parents)),
            'research_repair_unsafe_ledger')
    marker = root / 'production-attempts' / (PERIOD + '.json')
    old, digest = read(archived_marker or marker)
    require(digest == marker_sha256 and old.get('status') == 'in_flight'
            and set(old) <= {'status', 'at'}, 'research_repair_exact_old_marker_required')
    try:
        at = datetime.fromisoformat(old['at'].replace('Z', '+00:00'))
        valid = schedule.period_key(at) == PERIOD and at <= now
    except (ValueError, TypeError, KeyError):
        valid = False
    require(valid, 'research_repair_marker_period_required')
    artifact_path = root / 'model-artifacts' / (hashlib.sha256(RESPONSE_ID.encode()).hexdigest() + '.json')
    artifact, digest = read(artifact_path)
    require(digest == artifact_sha256 == ARTIFACT_SHA and artifact.get('responseId') == RESPONSE_ID
            and artifact.get('model') == 'claude-sonnet-4-6' and _usage(artifact.get('usage')) == (128983, 3807),
            'research_repair_exact_known_response_required')
    invalid = _intent_failure(artifact)
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM model_budget_reservations WHERE article_id=?', ('research:' + PERIOD,))]
        require(len(rows) == 1, 'research_repair_single_settled_research_required')
        row = rows[0]
        require(row['response_id'] == RESPONSE_ID and row['period_key'] == PERIOD and row['stage'] == 'research'
                and row['model'] == artifact['model'] and row['status'] == 'settled' and row['outcome'] == 'success'
                and row['actual_input_tokens'] == 128983 and row['actual_output_tokens'] == 3807,
                'research_repair_budget_response_binding')
        jobs = [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs')]
        require(not any(regular(j) and j.get('week') == PERIOD for j in jobs)
                and sum(pending(j) for j in jobs) < 3, 'research_repair_no_jobs_and_free_slot_required')
        require(db.execute('SELECT 1 FROM meta WHERE key=?', ('regular_selection:v1:' + PERIOD,)).fetchone() is None
                and not (root / 'period-receipts' / (PERIOD + '.json')).exists()
                and not (root / 'existing-update-proposals' / (PERIOD + '.json')).exists(),
                'research_repair_no_selection_required')
    return {'schemaVersion': 1, 'period': PERIOD, 'configPath': str(config_path), 'stateRoot': str(root),
            'configSha256': config_sha, 'protocol': protocol(), 'capsSha256': fingerprint(limits),
            'firstFailure': {'code': 'proposal_contract', 'invalidFields': invalid, 'responseId': RESPONSE_ID,
                'diagnosis': {'intentEnumViolations': 'confirmed_all_six', 'onlyErrorProven': False,
                    'oldCategoryMembership': 'unverified', 'oldProductMembership': 'unverified',
                    'oldExistingArticleMembership': 'unverified',
                    'newResearch': 'fresh_context_full_validation_required'},
                'markerSha256': marker_sha256, 'artifactSha256': artifact_sha256,
                'budgetReservationSha256': fingerprint(row)},
            'maxRepairs': 1, 'scope': 'fresh_schema_research_only',
            'oldProposalUse': 'none; referential memberships not reconstructed'}


def prepare(config_path, marker_sha256, artifact_sha256, *, now=None):
    """Read-only pinning; no raw proposal text is returned."""
    return _inspect(config_path, marker_sha256, artifact_sha256, now=now)


def _archive(root):
    path = root / 'research-contract-recovery' / PERIOD
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'research_repair_unsafe_archive')
    return path


def arm(config_path, manifest, *, owner_grant, now=None):
    require(owner_grant == {'reference': AUTHORIZATION, 'answer': OWNER_ANSWER,
            'manifestSha256': fingerprint(manifest)}, 'research_repair_owner_instruction_required')
    config, digest = read(config_path)
    root = Path(manifest['stateRoot'])
    require(digest == CONFIG_SHA and root == Path(config['stateRoot'])
            and not (root / 'runtime.flock').is_symlink(), 'research_repair_runtime_config_changed')
    with (root / 'runtime.flock').open('a') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy', 'armed': False}
        first = manifest['firstFailure']
        require(prepare(config_path, first['markerSha256'], first['artifactSha256'], now=now) == manifest,
                'research_repair_manifest_changed')
        archive = _archive(root)
        require(not archive.exists(), 'research_repair_already_armed_requires_reconciliation')
        with sqlite3.connect(root / 'ledger.sqlite3', isolation_level=None) as db:
            db.execute('BEGIN IMMEDIATE')
            require(db.execute('SELECT 1 FROM meta WHERE key=?', (KEY,)).fetchone() is None,
                    'research_repair_already_claimed')
            archive.mkdir(parents=True)
            marker = root / 'production-attempts' / (PERIOD + '.json')
            raw = marker.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == first['markerSha256'], 'research_repair_marker_changed')
            with (archive / 'first-marker.json').open('xb') as out:
                out.write(raw)
            ready = {'status': 'retry_ready', 'period': PERIOD, 'recoveryKey': KEY,
                     'manifestSha256': fingerprint(manifest)}
            receipt = {'status': 'retry_ready', 'manifest': manifest, 'ownerGrant': owner_grant,
                       'repairsUsed': 0, 'maxRepairs': 1, 'readyMarker': ready}
            atomic(archive / 'receipt.json', receipt)
            db.execute('INSERT INTO meta VALUES (?,?)', (KEY, json.dumps(receipt)))
            db.commit()
            atomic(marker, ready)
    return {'status': 'retry_ready', 'armed': True, 'period': PERIOD}


def consume(runtime, period, marker):
    """Called only by the normal producer; transaction spends repair before IO/API."""
    require(period == PERIOD and marker.get('recoveryKey') == KEY, 'research_repair_wrong_period')
    root = runtime.root
    with runtime.ledger._tx() as db:
        raw = db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        require(raw is not None, 'research_repair_receipt_missing')
        receipt = json.loads(raw[0])
        require(receipt['status'] == 'retry_ready' and receipt['repairsUsed'] == 0
                and receipt['maxRepairs'] == 1 and marker == receipt['readyMarker'], 'research_repair_already_consumed')
        manifest = receipt['manifest']
        first = manifest['firstFailure']
        require(runtime.config == read(manifest['configPath'])[0], 'research_repair_runtime_config_changed')
        # Read-only evidence inspection uses a separate connection while the
        # authoritative transaction prevents two producers from claiming it.
        require(_inspect(manifest['configPath'], first['markerSha256'], first['artifactSha256'],
                         archived_marker=_archive(root) / 'first-marker.json') == manifest,
                'research_repair_manifest_changed')
        receipt.update(status='consumed', repairsUsed=1)
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(receipt), KEY))
        runtime.ledger._event(db, 'research:' + PERIOD, 'research_contract_repair_consumed',
                              {'responseId': RESPONSE_ID, 'repairsUsed': 1})
    atomic(_archive(root) / 'receipt.json', receipt)
    return KEY


def finish(runtime, marker):
    """Terminal status only; never restore a consumed right, even on failure."""
    with runtime.ledger._tx() as db:
        row = db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        require(row is not None, 'research_repair_receipt_missing')
        receipt = json.loads(row[0])
        require(receipt['status'] == 'consumed' and receipt['repairsUsed'] == 1, 'research_repair_not_consumed')
        receipt.update(status='completed' if marker.get('status') == 'generated' else 'held',
                       resultStatus=marker.get('status', 'unknown'))
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(receipt), KEY))
    atomic(_archive(runtime.root) / 'receipt.json', receipt)
