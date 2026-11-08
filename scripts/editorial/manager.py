"""Agenda-only Astra manager. SQLite is authoritative; no approval/publish tools.

Call evaluate_locked from Runtime.tick's existing runtime.flock critical section
before legacy production; disable that branch when managed. No CLI discovery here.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import sqlite3
import subprocess
import time

from analytics import _context, _ga4
from ledger import canonical, fingerprint, valid_review, valid_astra_review
from reporting import read_snapshot

JST = timezone(timedelta(hours=9))
ACTIONS = ('wait', 'start_period', 'produce_existing', 'improve_existing', 'investigate_sources',
           'deliver_reviewed', 'reconcile_unknown')
MODEL = 'gpt-6-astra'
RECEIPT_PREFIX = 'editorial_manager:'

# This schema is the fixed schema for the separately configured managed CLI.
ACTION_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'required': ['action', 'jobId', 'revision', 'expectations', 'targetUrl'],
    'properties': {'action': {'type': 'string', 'enum': list(ACTIONS)},
                   'jobId': {'type': ['string', 'null']},
                   'targetUrl': {'type': ['string', 'null']},
                   'revision': {'type': ['string', 'null']},
                   'expectations': {'type': 'object', 'additionalProperties': False,
                                    'properties': {}}}}
# Expectations are a small, explicit optimistic concurrency binding, not capabilities.
EXPECTATION_FIELDS = ('stage', 'revision', 'socialRevision', 'approvalCurrent', 'published', 'socialPosted')
ACTION_SCHEMA['properties']['expectations'] = {
    'type': 'object', 'additionalProperties': False,
    'required': list(EXPECTATION_FIELDS), 'properties': {
        'stage': {'type': ['string', 'null']}, 'revision': {'type': ['string', 'null']},
        'socialRevision': {'type': ['string', 'null']},
        **{k: {'type': 'boolean'} for k in ('approvalCurrent', 'published', 'socialPosted')}}}
DECISION_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'required': ['stateFingerprint', 'summary', 'actions'], 'properties': {
        'stateFingerprint': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
        'summary': {'type': 'string', 'maxLength': 1000},
        'actions': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': ACTION_SCHEMA}}}


@dataclass(frozen=True)
class Budget:
    timeout_seconds: float
    max_input_bytes: int
    max_output_bytes: int
    max_output_tokens: int
    max_calls_per_period: int
    max_cost_usd: object = None

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == 'max_cost_usd' and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError('invalid_manager_budget')
        for name in ('max_input_bytes', 'max_output_bytes', 'max_output_tokens', 'max_calls_per_period'):
            if type(getattr(self, name)) is not int:
                raise ValueError('invalid_manager_budget')


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('nonfinite_json')
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    canonical(value)  # also rejects overflowing exponents
    if not isinstance(value, dict):
        raise ValueError('json_object_required')
    return value


class CommandProvider:
    """Configured module caller, not a guessed Astra command. No shell/fallback.

    argv must address Main's trusted adapter, which enforces route/model/time limits
    and strips CLI chatter into the envelope below. Supply minimal child env/cwd.
    Both output streams share a hard byte limit; no stderr is recorded.
    """
    def __init__(self, argv, budget, *, cwd=None, env=None):
        if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(a, str) or not a or '\x00' in a for a in argv):
            raise ValueError('configured_argv_required')
        if not isinstance(budget, Budget):
            raise ValueError('configured_budget_required')
        self.argv, self.budget, self.cwd = tuple(argv), budget, cwd
        self.env = dict(env) if env is not None else {}  # never inherit API env

    def __call__(self, request):
        data = canonical(request).encode()
        if len(data) > self.budget.max_input_bytes:
            raise ValueError('manager_input_limit')
        process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=self.cwd, env=self.env, start_new_session=True)
        selector = selectors.DefaultSelector()
        output = bytearray()
        total = 0
        offset = 0
        deadline = time.monotonic() + self.budget.timeout_seconds
        try:
            for stream, event in ((process.stdin, selectors.EVENT_WRITE),
                                  (process.stdout, selectors.EVENT_READ), (process.stderr, selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('manager_provider_timeout')
                for key, event in selector.select(min(remaining, .05)):
                    stream = key.fileobj
                    if event == selectors.EVENT_WRITE:
                        try:
                            offset += os.write(stream.fileno(), data[offset:offset + 65536])
                        except BrokenPipeError:
                            offset = len(data)
                        if offset == len(data):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stream)
                            continue
                        total += len(chunk)
                        if total > self.budget.max_output_bytes:
                            raise ValueError('manager_output_limit')
                        if stream is process.stdout:
                            output.extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('manager_provider_timeout')
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise TimeoutError('manager_provider_timeout') from None
            if code:
                raise ValueError('manager_provider_exit')
            return strict_json(output)
        finally:
            # Kill the entire session, including orphan children retaining pipes.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            selector.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()


def _now(now):
    now = now if now is not None else datetime.now(JST)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware_manager_time_required')
    return now.astimezone(JST)


def _code(value):
    # No arbitrary error text, title, summary, owner instruction or document body.
    return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,160}', value) else None


def _review_ok(job, social=False):
    target = (job.get('social') or {}) if social else job
    try:
        valid_review(target.get('review'), target.get('revision'))
        if not social and (job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job):
            valid_astra_review(job.get('astraReview'), job.get('revision'))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _job(job):
    social = job.get('social') or {}
    approval = job.get('approval') or {}
    publication = job.get('publication') or {}
    posted = social.get('publication') or {}
    review = job.get('review') or {}
    return dict(id=_code(job['id']), kind=_code(job.get('kind')),
        catalogCorrection='catalogCorrectionContext' in job,
        period=_code(job.get('week')), stage=_code(job.get('stage')), revision=_code(job.get('revision')),
        bundleCurrent=bool(job.get('bundle') and fingerprint(job['bundle']) == job.get('revision')),
        reviewPassed=_review_ok(job), reviewFingerprint=_code(review.get('fingerprint')),
        approvalRevision=_code(approval.get('revision')),
        approvalCurrent=bool(approval.get('action') == 'approved' and job.get('revision')
                             and approval.get('revision') == job.get('revision')),
        published=publication.get('verified') is True,
        publicationRevision=_code(publication.get('revision')),
        socialRevision=_code(social.get('revision')), socialReviewPassed=_review_ok(job, True),
        socialApprovalCurrent=bool(social.get('revision') and (social.get('approval') or {}).get('action') == 'approved'
            and (social.get('approval') or {}).get('revision') == social.get('revision')),
        socialPosted=posted.get('verified') is True,
        mainId=_code(posted.get('mainId')), replyId=_code(posted.get('replyId')),
        errorCode=_code((job.get('error') or {}).get('reason')))


def expectations(job=None):
    return {key: job[key] if job else (False if key in ('approvalCurrent', 'published', 'socialPosted') else None)
            for key in EXPECTATION_FIELDS}


def _metrics(runtime, now):
    raw = read_snapshot(Path(runtime.config['seoStateRoot']) / 'metrics/latest.json') if runtime.config.get('seoStateRoot') else None
    context = _context(raw, now)
    evidence = context['evidence']
    previous_ga4 = _ga4((raw or {}).get('previousGa4'), now, []) if context['status'] == 'ok' else None
    def aggregate(source, ga4=False):
        if not source:
            return None
        keys = ('startDate', 'endDate', 'dateBasis', 'status') + (
            ('sessions', 'coverageVerified') if ga4 else ('settledThrough', 'summary', 'country', 'searchType'))
        return {k: source.get(k) for k in keys}
    out = dict(gscCurrent=aggregate(evidence.get('current')), gscPrevious=aggregate(evidence.get('previous')),
               ga4=aggregate(evidence.get('ga4'), True), ga4Previous=aggregate(previous_ga4, True))
    out['missing'] = [k for k, value in out.items() if value is None]
    out['opportunities'] = []
    for opportunity in context.get('opportunities', [])[:3]:
        url = opportunity.get('url')
        if isinstance(url, str) and re.fullmatch(r'https://camp-gear-lab\.com/articles/[a-z0-9][a-z0-9_-]*', url):
            out['opportunities'].append(dict(opportunity,
                gscPeriod={k: (evidence.get('current') or {}).get(k) for k in ('startDate', 'endDate', 'dateBasis')},
                ga4Period={k: (evidence.get('ga4') or {}).get(k) for k in ('startDate', 'endDate', 'dateBasis')}
                    if opportunity.get('ga4') else None))
    out['uncertainty'] = context.get('uncertainty', [])[:12]
    out['sales'] = 'not_connected'
    # Source freshness is validated by Analytics; raw collectedAt is never a trigger.
    out['sourceStatus'] = context['status']
    return out


def _target_date(config):
    value = config.get('initialTargetPublishBy')
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _external_queue(config):
    # Main supplies current verifier output; neither old handoffs nor connectivity
    # alone prove queue coverage. No raw queue/owner/provider capability is copied.
    raw = (config.get('editorialManager') or {}).get('externalQueue') or {}
    if not isinstance(raw, dict):
        raw = {}
    connected = raw.get('connected') if type(raw.get('connected')) is bool else None
    evidence = raw.get('evidenceFingerprint')
    valid_evidence = isinstance(evidence, str) and re.fullmatch(r'[a-f0-9]{64}', evidence)
    verified = connected is True and raw.get('status') == 'verified' and bool(valid_evidence)
    return dict(provider='Buffer', connected=connected, status='verified' if verified else 'unknown',
                evidenceFingerprint=evidence if verified else None)


def build_snapshot(runtime, *, now=None):
    """Read one SQLite transaction, never health.json or raw event/request payloads.

    Receipts are status projections only. External journals are allowlisted markers;
    their contents/names (which can be capabilities) never cross the model boundary.
    """
    now = _now(now)
    with sqlite3.connect('file:' + str(runtime.ledger.db_path) + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        raw_jobs = [strict_json(r[0]) for r in db.execute('SELECT data FROM jobs ORDER BY rowid')]
        jobs = [_job(j) for j in raw_jobs]
        candidates = [j for j in jobs if j['kind'] != 'article_revision' and j['stage'] == 'candidate']
        effects = [dict(jobId=_code(j), kind=_code(k), status=_code(s)) for j, k, s in db.execute(
            'SELECT job_id,kind,status FROM effects ORDER BY job_id,kind')]
        # Latest semantic event kinds, not monotonically increasing IDs/timestamps.
        events = sorted({(_code(j), _code(k)) for j, k in db.execute(
            "SELECT job_id,kind FROM events WHERE kind NOT LIKE 'manager_%'")}, key=lambda x: (x[0] or '', x[1] or ''))
        requests = []
        delivery_bindings = {}
        jobs_by_id = {j['id']: j for j in jobs}
        for job_id, kind, data in db.execute('SELECT job_id,kind,data FROM requests ORDER BY job_id,kind'):
            row = strict_json(data)
            expired = False
            try:
                expired = datetime.fromisoformat(row['expires_at']).astimezone(JST) <= now
            except (KeyError, ValueError, TypeError):
                expired = True
            job = jobs_by_id.get(job_id, {})
            current_revision = job.get('socialRevision') if kind == 'social' else job.get('revision')
            request_revision = _code(row.get('manifest_hash'))
            current = bool(current_revision and request_revision == current_revision)
            superseded = bool(current_revision and request_revision and request_revision != current_revision)
            request_status = _code(row.get('status'))
            historical = superseded or request_status in ('invalidated', 'decided')
            delivery_bindings[str(row.get('request_id'))] = dict(jobId=_code(job_id), revision=request_revision,
                requestStatus=request_status, currentRevision=current, historicalNonblocking=historical)
            requests.append(dict(jobId=_code(job_id), kind=_code(kind), status=_code(row.get('status')),
                                 revision=request_revision, expired=expired, currentRevision=current, historicalNonblocking=historical))
    markers = []
    for folder in ('production-attempts', 'revision-production-attempts', 'social-attempts',
                   'social-publications', 'social-outbox', 'deliveries'):
        path = runtime.root / folder
        files = sorted(path.glob('*.json')) if path.is_dir() else []
        states = []
        for file in files:
            raw = read_snapshot(file) if not file.is_symlink() else None
            raw = raw or {}
            binding = delivery_bindings.get(file.stem, {}) if folder == 'deliveries' else {'target': _code(file.stem)}
            states.append(dict(binding, status=_code(raw.get('status')),
                phase=_code(raw.get('phase')), pending=raw.get('pending') is not None,
                mainPresent=bool(raw.get('mainId')), replyPresent=bool(raw.get('replyId'))))
        markers.append(dict(kind=folder, count=len(files), states=sorted(states, key=canonical)))
    schedule = runtime.ledger.production_schedule
    config = runtime.config
    return dict(schemaVersion=1, brand='Camp Gear Lab', jobs=jobs, effects=effects,
        events=[dict(jobId=j, kind=k) for j, k in events],
        requests=sorted(requests, key=canonical), stateReceipts=markers,
        metrics=_metrics(runtime, now), externalQueue=_external_queue(config),
        production=dict(period=schedule.period_key(now), due=schedule.is_due(now),
                        schedule={k: config['productionSchedule'].get(k) for k in
                            ('weekday', 'hour', 'effectiveFrom', 'initialProductionAt')}
                            if isinstance(config.get('productionSchedule'), dict) else None,
                        initialTargetPublishBy=_target_date(config),
                        nextCandidateId=candidates[0]['id'] if candidates else None,
                        periodCandidateCount=sum(j['kind'] != 'article_revision' and j['period'] == schedule.period_key(now) for j in jobs),
                        pending=sum(j.get('kind') != 'article_revision' and not j.get('publication')
                                    and j.get('stage') != 'rejected' for j in raw_jobs), retentionCap=3),
        gates={k: config.get(k) is True for k in ('generationEnabled', 'publicationEnabled', 'socialPostingEnabled')})


def semantic_key(snapshot):
    return fingerprint(snapshot)


@contextmanager
def _lease(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Plan:
    action: str
    job_id: object
    target_url: object
    revision: object
    state_fingerprint: str
    expectations: dict


def validate_decision(response, snapshot, key, expected_model):
    required = {'decision', 'requestedModel', 'actualModel', 'usage', 'actualInvoiceUsd'}
    if not isinstance(response, dict) or not required <= set(response) or set(response) - required - {'warnings'}:
        raise ValueError('manager_envelope_schema')
    if 'warnings' in response and _safe_warnings(response['warnings']) is None:
        raise ValueError('manager_warning_schema')
    if response['requestedModel'] != MODEL or expected_model != MODEL:
        raise ValueError('astra_route_required')
    actual = response['actualModel']
    if actual is not None and actual != expected_model:
        raise ValueError('unexpected_actual_model')
    decision = response['decision']
    if not isinstance(decision, dict) or set(decision) != {'stateFingerprint', 'summary', 'actions'}:
        raise ValueError('manager_decision_schema')
    if decision['stateFingerprint'] != key or not isinstance(decision['summary'], str) or len(decision['summary']) > 1000:
        raise ValueError('manager_state_binding')
    actions = decision['actions']
    if not isinstance(actions, list) or len(actions) != 1:
        raise ValueError('one_manager_action_required')
    action = actions[0]
    if not isinstance(action, dict) or set(action) != {'action', 'jobId', 'revision', 'expectations', 'targetUrl'} or action['action'] not in ACTIONS:
        raise ValueError('manager_action_schema')
    job = next((j for j in snapshot['jobs'] if j['id'] == action['jobId']), None)
    if action['jobId'] is not None and job is None:
        raise ValueError('manager_unknown_job')
    if action['revision'] != (job['revision'] if job else None) or action['expectations'] != expectations(job):
        raise ValueError('manager_expectation_conflict')
    if type(action['expectations']) is not dict or any(type(action['expectations'][k]) is not bool for k in ('approvalCurrent', 'published', 'socialPosted')):
        raise ValueError('manager_expectation_types')
    target_url = action['targetUrl']
    if target_url is not None and (action['action'] != 'improve_existing' or job is not None
            or target_url not in [o['url'] for o in snapshot['metrics']['opportunities']]):
        raise ValueError('verified_opportunity_url_required')
    if action['action'] == 'improve_existing' and job is None and target_url is None:
        raise ValueError('exact_improvement_target_required')
    if action['action'] not in ('wait', 'start_period', 'improve_existing') and job is None:
        raise ValueError('exact_job_required')
    if action['action'] == 'start_period' and job is not None:
        raise ValueError('start_period_requires_null_job')
    usage = response['usage']
    allowed = {'input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'reasoning_tokens'}
    if usage is not None and (not isinstance(usage, dict) or set(usage) - allowed or
            any(type(v) is not int or v < 0 for v in usage.values())):
        raise ValueError('manager_usage_schema')
    cost = response['actualInvoiceUsd']
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0):
        raise ValueError('manager_cost_schema')
    return Plan(action['action'], action['jobId'], target_url, action['revision'], key, action['expectations'])


def _safe_warnings(value):
    if (not isinstance(value, dict) or set(value) != {'preTurnErrorCount', 'code', 'toolsStartupVerified'}
            or type(value['preTurnErrorCount']) is not int or not 1 <= value['preTurnErrorCount'] <= 16
            or value['code'] != 'unknown' or value['toolsStartupVerified'] is not False):
        return None
    return dict(preTurnErrorCount=value['preTurnErrorCount'], code='unknown', toolsStartupVerified=False)


def _returned_evidence(response):
    """Retain available bounded accounting even when the action is rejected."""
    response = response if isinstance(response, dict) else {}
    usage = response.get('usage')
    allowed = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'reasoning_tokens')
    safe_usage = {k: usage[k] for k in allowed if type(usage.get(k)) is int and usage[k] >= 0} if isinstance(usage, dict) else None
    cost = response.get('actualInvoiceUsd')
    if isinstance(cost, bool) or not isinstance(cost, (float, int)) or not math.isfinite(cost) or cost < 0:
        cost = None
    evidence = dict(requestedModel=MODEL, actualModel=_code(response.get('actualModel')),
                    usage=safe_usage, actualInvoiceUsd=cost, costMissing=cost is None, usdCapEnforced=False)
    warning = _safe_warnings(response.get('warnings'))
    if warning is not None:
        evidence['warnings'] = warning
    return evidence


class Manager:
    def __init__(self, root, *, budget=None, expected_model=MODEL):
        self.root, self.budget, self.expected_model = Path(root), budget, expected_model

    def _save(self, runtime, key, receipt):
        # meta/events live in the existing authoritative ledger, never another DB.
        receipt = dict(receipt, stateFingerprint=key)
        with runtime.ledger._tx() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (RECEIPT_PREFIX + key, canonical(receipt)))
            runtime.ledger._event(db, None, 'manager_receipt', receipt)
        return receipt

    def evaluate_locked(self, runtime, provider, *, now=None, handlers=None):
        """Caller MUST hold runtime.flock from before tick through this return.

        handlers are narrow trusted APIs: improve_existing queues a proposal/private
        correction attachment; investigate_sources is read-only; reconcile_unknown is
        read-only. They receive Plan + sanitized snapshot, never an owner capability.
        They must enforce their normal gates and return {'status':'completed'} or
        {'status':'blocked'}; anything else is an unknown outcome, never retried.
        """
        if self.root.resolve() != runtime.root.resolve():
            raise ValueError('manager_root_mismatch')
        try:
            with _lease(self.root / 'manager.flock'):
                return self._evaluate(runtime, provider, now=_now(now), handlers=handlers or {})
        except BlockingIOError:
            return {'status': 'busy'}

    def _evaluate(self, runtime, provider, *, now, handlers):
        snapshot = build_snapshot(runtime, now=now)
        key = semantic_key(snapshot)
        with sqlite3.connect(runtime.ledger.db_path) as db:
            previous = db.execute('SELECT value FROM meta WHERE key=?', (RECEIPT_PREFIX + key,)).fetchone()
            unresolved = db.execute('SELECT value FROM meta WHERE key LIKE ?', (RECEIPT_PREFIX + '%',)).fetchall()
        if previous:
            return dict(status='unchanged', stateFingerprint=key, receiptStatus=strict_json(previous[0])['status'])
        if not isinstance(self.budget, Budget) or self.expected_model != MODEL or provider is None:
            return dict(status='unconfigured', stateFingerprint=key)
        # A crash/unknown execution is global until the owning integration reconciles
        # it in SQLite. A changed job or different provider does not authorize replay.
        if any(strict_json(row[0])['status'] in ('evaluating', 'executing', 'requires_reconciliation') for row in unresolved):
            return dict(status='requires_reconciliation', stateFingerprint=key)
        prompt = (Path(__file__).resolve().parents[2] / 'skills/camp-editorial-manager/references/prompt.md').read_text()
        request = dict(schemaVersion=1, stateFingerprint=key, snapshot=snapshot, prompt=prompt,
                       requestedModel=MODEL, budget=asdict(self.budget), decisionSchema=DECISION_SCHEMA)
        if len(canonical(request).encode()) > self.budget.max_input_bytes:
            return self._save(runtime, key, dict(status='input_limit'))
        # Reserve one call atomically in the authoritative SQLite before dispatch.
        # Failed/invalid/unknown responses still consume the period allowance.
        period = snapshot['production']['period'] or 'inactive'
        counter_key = 'editorial_manager_calls:' + period
        with runtime.ledger._tx() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (counter_key,)).fetchone()
            calls = int(row[0]) if row else 0
            if calls >= self.budget.max_calls_per_period:
                exhausted = True
            else:
                exhausted = False
                db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (counter_key, str(calls + 1)))
                receipt = dict(status='evaluating', requestedModel=MODEL)
                db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (RECEIPT_PREFIX + key, canonical(receipt)))
                runtime.ledger._event(db, None, 'manager_receipt', dict(stateFingerprint=key, **receipt))
        if exhausted:
            return self._save(runtime, key, dict(status='budget_exhausted'))
        started = time.monotonic()
        try:
            response = provider(request)
            if time.monotonic() - started > self.budget.timeout_seconds:
                raise TimeoutError('provider_deadline')
            if len(canonical(response).encode()) > self.budget.max_output_bytes:
                raise ValueError('output_limit')
        except Exception as error:
            return self._save(runtime, key, dict(status='provider_failed', errorCode='timeout' if isinstance(error, TimeoutError) else 'provider_error', requestedModel=MODEL,
                actualModel=None, usage=None, actualInvoiceUsd=None, costMissing=True))
        try:
            plan = validate_decision(response, snapshot, key, self.expected_model)
            if self.budget.max_cost_usd is not None and response['actualInvoiceUsd'] is not None and response['actualInvoiceUsd'] > self.budget.max_cost_usd:
                raise ValueError('cost_exceeded')
            if (response['usage'] or {}).get('output_tokens', 0) > self.budget.max_output_tokens:
                raise ValueError('tokens_exceeded')
        except (ValueError, TypeError, KeyError):
            return self._save(runtime, key, dict(status='invalid_decision', **_returned_evidence(response)))
        receipt = dict(_returned_evidence(response),
                       routeAssurance='configured_astra_no_fallback' if response['actualModel'] is None else 'returned_model_matches',
                       summary=response['decision']['summary'], action=asdict(plan))
        # Re-read before executing: injected provider must not bypass state binding.
        if semantic_key(build_snapshot(runtime, now=now)) != key:
            return self._save(runtime, key, dict(receipt, status='stale'))
        if plan.action == 'wait':
            return self._save(runtime, key, dict(receipt, status='completed'))
        job = next((j for j in snapshot['jobs'] if j['id'] == plan.job_id), None)
        blocked = self._blocked(plan.action, job, snapshot)
        if blocked:
            return self._save(runtime, key, dict(receipt, status='blocked', reason=blocked))
        if plan.action in ('improve_existing', 'investigate_sources', 'reconcile_unknown') and plan.action not in handlers:
            return self._save(runtime, key, dict(receipt, status='blocked', reason='handler_unconfigured'))
        self._save(runtime, key, dict(receipt, status='executing'))
        try:
            if plan.action in ('produce_existing', 'start_period'):
                result = runtime.produce(limit=1)  # ONLY existing normal producer, no retry/reset
                status = 'completed' if result.get('status') in ('completed', 'idle', 'disabled') else 'requires_reconciliation'
            elif plan.action == 'deliver_reviewed':
                result = runtime.deliver(plan.job_id)
                status = 'completed' if result.get('status') in ('delivered', 'already_delivered') else 'blocked'
            else:
                result = handlers[plan.action](plan, snapshot)
                status = result.get('status') if isinstance(result, dict) else None
                if status not in ('completed', 'blocked'):
                    status = 'requires_reconciliation'
        except Exception:
            status = 'requires_reconciliation'
        # Do not persist handler bodies, attachments or transport request IDs.
        return self._save(runtime, key, dict(receipt, status=status))

    @staticmethod
    def _blocked(action, job, snapshot):
        if action == 'start_period':
            production = snapshot['production']
            if not snapshot['gates']['generationEnabled'] or not production['due'] or production['period'] is None:
                return 'production_not_enabled_or_due'
            if production['periodCandidateCount'] != 0 or production['nextCandidateId'] is not None:
                return 'existing_period_or_candidate'
            if production['pending'] >= production['retentionCap']:
                return 'retention_cap_reached'
            if any(e['status'] in ('in_flight', 'unknown') for e in snapshot['effects']):
                return 'unknown_effect'
            if any(st.get('target') == production['period'] or st.get('status') not in ('generated', 'completed', 'blocked')
                   for m in snapshot['stateReceipts'] if m['kind'] == 'production-attempts' for st in m['states']):
                return 'production_marker_requires_reconciliation'
            return None
        if action in ('reconcile_unknown', 'investigate_sources'):
            return None
        if action == 'improve_existing':
            # Proposal-only for a bound job (including published/posted) or a
            # verified opportunity URL. Never mutate/repost that version.
            return None
        if job['socialPosted'] or job['stage'] == 'social_posted':
            return 'posted_immutable'
        if any(e['jobId'] == job['id'] and e['status'] in ('in_flight', 'unknown') for e in snapshot['effects']):
            return 'unknown_effect'
        if job['stage'] in ('held', 'social_held', 'rejected', 'social_rejected', 'error'):
            return 'held_or_error_requires_proposal_or_reconciliation'
        if action == 'produce_existing':
            if job['kind'] == 'article_revision' or snapshot['production']['nextCandidateId'] != job['id']:
                return 'normal_producer_target_conflict'
            if job['stage'] != 'candidate' or job['published'] or job['approvalCurrent']:
                return 'existing_candidate_required'
            if not snapshot['gates']['generationEnabled'] or not snapshot['production']['due']:
                return 'production_not_enabled_or_due'
            if any(st.get('target') in (job['id'], snapshot['production']['period']) and st.get('status') not in ('generated', 'completed')
                   for m in snapshot['stateReceipts'] if m['kind'] in ('production-attempts', 'revision-production-attempts') for st in m['states']):
                return 'production_marker_requires_reconciliation'
        if action == 'deliver_reviewed':
            if job['stage'] != 'review' or not job['bundleCurrent'] or not job['reviewPassed'] or job['approvalCurrent']:
                return 'current_review_required'
            if any(st.get('jobId') == job['id'] and not st.get('historicalNonblocking') and st.get('status') != 'delivered'
                   for m in snapshot['stateReceipts'] if m['kind'] == 'deliveries' for st in m['states']):
                return 'delivery_marker_requires_reconciliation'
            if any(r['jobId'] == job['id'] and r['kind'] == 'article' and r['currentRevision'] and not r['historicalNonblocking'] and r['status'] in ('created', 'delivered') for r in snapshot['requests']):
                return 'existing_delivery_no_duplicate'
        return None


