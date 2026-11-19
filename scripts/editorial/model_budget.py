"""Durable, transport-attempt model budgets stored beside the editorial ledger."""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid
from urllib.parse import quote


JST = timezone(timedelta(hours=9))
DEFAULTS = {
    'article': {'calls': 32, 'inputTokens': 2_000_000, 'outputTokens': 262_144},
    'period': {'calls': 128, 'inputTokens': 8_000_000, 'outputTokens': 1_048_576},
    'requestInputBytes': 1_048_576,
    'warningRatio': .75,
}
DIMENSIONS = ('calls', 'inputTokens', 'outputTokens')
OUTCOMES = ('success', 'failed', 'unknown')
UNATTRIBUTED_ARTICLE = 'maintenance:legacy-unattributed'


class BudgetHold(RuntimeError):
    """Safe, content-free signal raised before an outbound model attempt."""
    def __init__(self, *, reason_code, budget_scope, dimension, cap, projected,
                 article_id, stage, period_key, event_id):
        super().__init__('model_budget_hold')
        self.reason_code = reason_code
        self.budget_scope = budget_scope
        self.dimension = dimension
        self.cap = cap
        self.projected = projected
        self.article_id = article_id
        self.stage = stage
        self.period_key = period_key
        self.event_id = event_id

    def __str__(self):
        return 'model_budget_hold'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _safe_root(value):
    root = Path(value)
    if not root.is_absolute() or root.resolve() in (Path('/'), Path.home().resolve()):
        raise ValueError('safe absolute state root required')
    root = root.resolve()
    ledger = root / 'ledger.sqlite3'
    if not ledger.is_file() or ledger.is_symlink():
        raise ValueError('editorial ledger required')
    return root, ledger


def _safe_text(value, name):
    if (not isinstance(value, str) or not value or len(value) > 160
            or any(ord(character) < 32 for character in value)):
        raise ValueError('invalid ' + name)
    return value


def _aware(value, name='timestamp'):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('aware ' + name + ' required')
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('aware ' + name + ' required')
    return value.astimezone(JST)


def _positive_int(value):
    return type(value) is int and value > 0


def _nonnegative_int(value):
    return type(value) is int and value >= 0


def _config(value):
    if value is None:
        return copy.deepcopy(DEFAULTS)
    try:
        if not isinstance(value, dict) or set(value) - set(DEFAULTS):
            raise ValueError()
        result = copy.deepcopy(DEFAULTS)
        for scope in ('article', 'period'):
            if scope not in value:
                continue
            supplied = value[scope]
            if not isinstance(supplied, dict) or set(supplied) - set(DIMENSIONS):
                raise ValueError()
            result[scope].update(supplied)
        if 'requestInputBytes' in value:
            result['requestInputBytes'] = value['requestInputBytes']
        if 'warningRatio' in value:
            result['warningRatio'] = value['warningRatio']
        if any(not _positive_int(result[scope][dimension])
               for scope in ('article', 'period') for dimension in DIMENSIONS):
            raise ValueError()
        if not _positive_int(result['requestInputBytes']):
            raise ValueError()
        ratio = result['warningRatio']
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 < ratio < 1:
            raise ValueError()
        result['warningRatio'] = float(ratio)
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError('invalid model budget config') from None


def _usage(value):
    if not isinstance(value, dict):
        return None
    pairs = [('input_tokens', 'output_tokens'), ('input', 'output'),
             ('prompt_tokens', 'completion_tokens')]
    present = [(input_key, output_key) for input_key, output_key in pairs
               if input_key in value or output_key in value]
    if len(present) != 1:
        return None
    input_key, output_key = present[0]
    input_tokens, output_tokens = value.get(input_key), value.get(output_key)
    if not _nonnegative_int(input_tokens) or not _nonnegative_int(output_tokens):
        return None
    if input_key == 'prompt_tokens':
        return input_tokens, output_tokens
    caches = []
    for key in ('cache_creation_input_tokens', 'cache_read_input_tokens'):
        cached = value.get(key, 0)
        if not _nonnegative_int(cached):
            return None
        caches.append(cached)
    return input_tokens + sum(caches), output_tokens


class ModelBudget:
    def __init__(self, root, production_schedule, config=None):
        self.root, self.db_path = _safe_root(root)
        if not callable(getattr(production_schedule, 'period_key', None)):
            raise ValueError('production schedule required')
        self.production_schedule = production_schedule
        self.config = _config(config)
        self._active = ContextVar('model_budget_scope_' + uuid.uuid4().hex, default=None)
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=10, isolation_level=None)

    def _read(self):
        uri = 'file:' + quote(str(self.db_path), safe='/') + '?mode=ro'
        db = sqlite3.connect(uri, uri=True, timeout=5)
        db.execute('PRAGMA query_only=ON')
        return db

    def _initialize(self):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS model_budget_reservations(
                reservation_id TEXT PRIMARY KEY,
                response_id TEXT UNIQUE,
                source_hash TEXT,
                article_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                period_key TEXT NOT NULL,
                model TEXT,
                status TEXT NOT NULL,
                reserved_input_tokens INTEGER NOT NULL,
                reserved_output_tokens INTEGER NOT NULL,
                actual_input_tokens INTEGER,
                actual_output_tokens INTEGER,
                outcome TEXT,
                created_at TEXT NOT NULL,
                settled_at TEXT
            )''')
            db.execute('''CREATE INDEX IF NOT EXISTS model_budget_reservations_article
                          ON model_budget_reservations(article_id)''')
            db.execute('''CREATE INDEX IF NOT EXISTS model_budget_reservations_period
                          ON model_budget_reservations(period_key)''')
            db.execute('''CREATE TABLE IF NOT EXISTS model_budget_events(
                event_id TEXT PRIMARY KEY,
                dedup_key TEXT NOT NULL UNIQUE,
                period_key TEXT NOT NULL,
                article_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                level TEXT NOT NULL,
                budget_scope TEXT NOT NULL,
                dimension TEXT NOT NULL,
                cap INTEGER NOT NULL,
                projected INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                finished_at TEXT
            )''')
            db.commit()

    def _period_key(self, at):
        period = self.production_schedule.period_key(at)
        initial = getattr(self.production_schedule, 'initial', None)
        if period is None and initial is not None and at >= initial:
            # A due-gate gap does not end the active budget period. Clamp to
            # initial production when it started less than a day ago.
            period = self.production_schedule.period_key(max(initial, at - timedelta(days=1)))
        if not isinstance(period, str) or not period:
            raise ValueError('production period unavailable')
        return period

    @contextmanager
    def scope(self, article_id, stage, now=None):
        if self._active.get() is not None:
            raise RuntimeError('model budget scope already active')
        article_id = _safe_text(article_id, 'article id')
        stage = _safe_text(stage, 'stage')
        at = _aware(now if now is not None else datetime.now(JST))
        period_key = self._period_key(at)
        token = self._active.set({'articleId': article_id, 'stage': stage,
                                  'at': at.isoformat(), 'periodKey': period_key})
        try:
            yield self
        finally:
            self._active.reset(token)

    @staticmethod
    def _payload_bound(payload):
        if not isinstance(payload, dict) or not _positive_int(payload.get('max_tokens')):
            raise ValueError('invalid model payload')
        try:
            encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, OverflowError):
            raise ValueError('invalid model payload') from None
        return len(encoded), payload['max_tokens']

    @staticmethod
    def _totals(db, where='', params=()):
        row = db.execute('''SELECT count(*),
            coalesce(sum(CASE WHEN status IN ('settled','imported')
                THEN actual_input_tokens ELSE reserved_input_tokens END),0),
            coalesce(sum(CASE WHEN status IN ('settled','imported')
                THEN actual_output_tokens ELSE reserved_output_tokens END),0)
            FROM model_budget_reservations ''' + where, params).fetchone()
        return {'calls': int(row[0]), 'inputTokens': int(row[1]), 'outputTokens': int(row[2])}

    def _event(self, db, context, level, budget_scope, dimension, cap, projected):
        period = context['periodKey']
        article = context['articleId']
        if budget_scope == 'period':
            dedup = '|'.join((level, budget_scope, period, dimension))
        else:
            dedup = '|'.join((level, budget_scope, period, article, dimension))
        event_id = _digest(dedup)
        db.execute('''INSERT OR IGNORE INTO model_budget_events
            (event_id,dedup_key,period_key,article_id,stage,level,budget_scope,dimension,
             cap,projected,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (event_id, dedup, period, article, context['stage'], level, budget_scope,
             dimension, cap, projected, 'pending', context['at']))
        return event_id

    def _limits(self, db, context, additions):
        article = self._totals(db, 'WHERE article_id=? AND period_key=?',
                               (context['articleId'], context['periodKey']))
        period = self._totals(db, 'WHERE period_key=?', (context['periodKey'],))
        violations = []
        for budget_scope, current in (('article', article), ('period', period)):
            for dimension in DIMENSIONS:
                projected = current[dimension] + additions[dimension]
                cap = self.config[budget_scope][dimension]
                if projected > cap:
                    event_id = self._event(db, context, 'hold', budget_scope,
                                           dimension, cap, projected)
                    violations.append((budget_scope, dimension, cap, projected, event_id))
        return article, period, violations

    def _batch_call_scope(self, db, context):
        """Return a supplemental batch lifetime call count under this transaction."""
        try:
            row = db.execute('SELECT data FROM jobs WHERE id=?',
                             (context['articleId'],)).fetchone()
        except sqlite3.OperationalError as error:
            if 'no such table: jobs' in str(error):
                return None
            raise
        if row is None:
            return None
        try:
            job = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        if job.get('kind') != 'supplemental_article':
            return None
        batch_id, cap = job.get('batchId'), job.get('batchCallCap')
        if not isinstance(batch_id, str) or not batch_id or cap != 96:
            raise ValueError('invalid supplemental batch budget binding')
        members = []
        for member_id, raw in db.execute('SELECT id,data FROM jobs'):
            try:
                member = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if (member.get('kind') == 'supplemental_article'
                    and member.get('batchId') == batch_id):
                if member.get('batchCallCap') != cap:
                    raise ValueError('supplemental batch budget conflict')
                members.append(member_id)
        if context['articleId'] not in members or len(members) > 3:
            raise ValueError('invalid supplemental batch membership')
        placeholders = ','.join('?' for _ in members)
        calls = db.execute('SELECT count(*) FROM model_budget_reservations WHERE article_id IN ('
                           + placeholders + ')', members).fetchone()[0]
        return {'id': batch_id, 'cap': cap, 'calls': int(calls)}

    def _warnings(self, db, context, article, period, additions, request_bytes=None,
                  include_article=True):
        ratio = self.config['warningRatio']
        scopes = [('period', period)]
        if include_article:
            scopes.insert(0, ('article', article))
        for budget_scope, current in scopes:
            for dimension in DIMENSIONS:
                projected = current[dimension] + additions[dimension]
                cap = self.config[budget_scope][dimension]
                if projected >= cap * ratio:
                    self._event(db, context, 'warning', budget_scope,
                                dimension, cap, projected)
        if request_bytes is not None and request_bytes >= self.config['requestInputBytes'] * ratio:
            self._event(db, context, 'warning', 'request', 'inputBytes',
                        self.config['requestInputBytes'], request_bytes)

    def reserve(self, payload, model=None):
        context = self._active.get()
        if context is None:
            raise RuntimeError('model budget scope required')
        input_bound, output_bound = self._payload_bound(payload)
        if model is None:
            model = payload.get('model')
        if model is not None:
            model = _safe_text(model, 'model')
        additions = {'calls': 1, 'inputTokens': input_bound, 'outputTokens': output_bound}
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            request_cap = self.config['requestInputBytes']
            if input_bound > request_cap:
                event_id = self._event(db, context, 'hold', 'request', 'inputBytes',
                                       request_cap, input_bound)
                db.commit()
                raise BudgetHold(reason_code='request_input_bytes_cap', budget_scope='request',
                                 dimension='inputBytes', cap=request_cap, projected=input_bound,
                                 article_id=context['articleId'], stage=context['stage'],
                                 period_key=context['periodKey'], event_id=event_id)
            batch = self._batch_call_scope(db, context)
            if batch is not None and batch['calls'] + 1 > batch['cap']:
                projected = batch['calls'] + 1
                event_id = self._event(db, context, 'hold', 'batch', 'calls',
                                       batch['cap'], projected)
                db.commit()
                raise BudgetHold(reason_code='batch_calls_cap', budget_scope='batch',
                                 dimension='calls', cap=batch['cap'], projected=projected,
                                 article_id=context['articleId'], stage=context['stage'],
                                 period_key=context['periodKey'], event_id=event_id)
            article, period, violations = self._limits(db, context, additions)
            if violations:
                db.commit()
                budget_scope, dimension, cap, projected, event_id = violations[0]
                raise BudgetHold(reason_code=budget_scope + '_' + self._reason_dimension(dimension) + '_cap',
                                 budget_scope=budget_scope, dimension=dimension, cap=cap,
                                 projected=projected, article_id=context['articleId'],
                                 stage=context['stage'], period_key=context['periodKey'],
                                 event_id=event_id)
            reservation_id = uuid.uuid4().hex
            db.execute('''INSERT INTO model_budget_reservations
                (reservation_id,response_id,source_hash,article_id,stage,period_key,model,status,
                 reserved_input_tokens,reserved_output_tokens,actual_input_tokens,actual_output_tokens,
                 outcome,created_at,settled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (reservation_id, None, None, context['articleId'], context['stage'],
                 context['periodKey'], model, 'reserved', input_bound, output_bound,
                 None, None, None, context['at'], None))
            self._warnings(db, context, article, period, additions, input_bound)
            db.commit()
            return reservation_id

    @staticmethod
    def _reason_dimension(dimension):
        return {'calls': 'calls', 'inputTokens': 'input_tokens',
                'outputTokens': 'output_tokens'}[dimension]

    def settle(self, reservation_id, usage=None, outcome='success', response_id=None):
        reservation_id = _safe_text(reservation_id, 'reservation id')
        if outcome not in OUTCOMES:
            raise ValueError('invalid model outcome')
        if response_id is not None:
            response_id = _safe_text(response_id, 'response id')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT article_id,stage,period_key,status,
                reserved_input_tokens,reserved_output_tokens,created_at
                FROM model_budget_reservations WHERE reservation_id=?''',
                             (reservation_id,)).fetchone()
            if row is None:
                raise ValueError('model reservation not found')
            article_id, stage, period_key, status, reserved_input, reserved_output, created_at = row
            if response_id is not None:
                bound = db.execute('''SELECT reservation_id FROM model_budget_reservations
                                      WHERE response_id=?''', (response_id,)).fetchone()
                if bound is not None and bound[0] != reservation_id:
                    raise ValueError('model response already bound')
            if status == 'unknown':
                db.commit()
                return {'status': 'already_unknown', 'reservationId': reservation_id,
                        'chargedInputTokens': reserved_input,
                        'chargedOutputTokens': reserved_output}
            if status in ('settled', 'imported'):
                db.commit()
                return {'status': 'already_settled', 'reservationId': reservation_id}
            measured = _usage(usage)
            now = datetime.now(JST).isoformat()
            if outcome == 'unknown' or measured is None:
                db.execute('''UPDATE model_budget_reservations SET status='unknown',outcome='unknown',
                              response_id=coalesce(response_id,?),settled_at=?
                              WHERE reservation_id=?''', (response_id, now, reservation_id))
                db.commit()
                return {'status': 'unknown', 'reservationId': reservation_id,
                        'chargedInputTokens': reserved_input,
                        'chargedOutputTokens': reserved_output}
            actual_input, actual_output = measured
            db.execute('''UPDATE model_budget_reservations SET status='settled',outcome=?,
                          response_id=coalesce(response_id,?),
                          actual_input_tokens=?,actual_output_tokens=?,settled_at=?
                          WHERE reservation_id=?''',
                       (outcome, response_id, actual_input, actual_output, now, reservation_id))
            context = {'articleId': article_id, 'stage': stage, 'periodKey': period_key,
                       'at': now}
            # Totals already include the replacement actual values; use zero additions.
            zero = {'calls': 0, 'inputTokens': 0, 'outputTokens': 0}
            article = self._totals(db, 'WHERE article_id=? AND period_key=?',
                                   (article_id, period_key))
            period = self._totals(db, 'WHERE period_key=?', (period_key,))
            self._warnings(db, context, article, period, zero)
            exceeded = None
            for budget_scope, totals in (('article', article), ('period', period)):
                for dimension in DIMENSIONS:
                    cap = self.config[budget_scope][dimension]
                    if totals[dimension] > cap:
                        event_id = self._event(db, context, 'hold', budget_scope, dimension,
                                               cap, totals[dimension])
                        if exceeded is None:
                            exceeded = (budget_scope, dimension, cap, totals[dimension], event_id)
            db.commit()
            if exceeded is not None:
                budget_scope, dimension, cap, projected, event_id = exceeded
                raise BudgetHold(reason_code=budget_scope + '_' + self._reason_dimension(dimension) + '_cap',
                    budget_scope=budget_scope, dimension=dimension, cap=cap, projected=projected,
                    article_id=article_id, stage=stage, period_key=period_key, event_id=event_id)
            return {'status': 'settled', 'reservationId': reservation_id,
                    'outcome': outcome, 'chargedInputTokens': actual_input,
                    'chargedOutputTokens': actual_output}

    def has_request_reservation(self, article_id, stage, period_key):
        """True means a provider attempt may already have occurred for this exact scope."""
        with self._connect() as db:
            return db.execute('''SELECT 1 FROM model_budget_reservations
                WHERE article_id=? AND stage=? AND period_key=? LIMIT 1''',
                (article_id, stage, period_key)).fetchone() is not None

    def import_usage(self, records):
        if not isinstance(records, list):
            raise ValueError('model usage records required')
        prepared = []
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('invalid model usage record')
            response_id = _safe_text(record.get('responseId'), 'response id')
            article_id = (UNATTRIBUTED_ARTICLE if record.get('articleId') in (None, '')
                          else _safe_text(record.get('articleId'), 'article id'))
            stage = _safe_text(record.get('stage'), 'stage')
            at = _aware(record.get('at'), 'usage timestamp')
            period = self._period_key(at)
            usage_value = record.get('usage') if 'usage' in record else {
                'input': record.get('input'), 'output': record.get('output')}
            measured = _usage(usage_value)
            if measured is None:
                raise ValueError('invalid model usage record')
            source_hash = _digest(_canonical(record))
            prepared.append((response_id, article_id, stage, at.isoformat(), period,
                             measured[0], measured[1], source_hash))
        imported = existing = 0
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for response_id, article_id, stage, at, period, inputs, outputs, source_hash in prepared:
                prior = db.execute('''SELECT source_hash,article_id,stage,period_key,status,
                                      actual_input_tokens,actual_output_tokens
                                      FROM model_budget_reservations
                                      WHERE response_id=?''', (response_id,)).fetchone()
                if prior is not None:
                    same_measured = (prior[1] == article_id and prior[2] == stage
                                     and prior[3] == period and prior[4] in ('settled', 'imported')
                                     and prior[5] == inputs and prior[6] == outputs)
                    if prior[0] == source_hash:
                        existing += 1
                        continue
                    if prior[0] is None and same_measured:
                        db.execute('''UPDATE model_budget_reservations SET source_hash=?
                                      WHERE response_id=?''', (source_hash, response_id))
                        existing += 1
                        continue
                    raise ValueError('model usage response conflict')
                reservation_id = 'import-' + _digest(response_id)
                db.execute('''INSERT INTO model_budget_reservations
                    (reservation_id,response_id,source_hash,article_id,stage,period_key,model,status,
                     reserved_input_tokens,reserved_output_tokens,actual_input_tokens,actual_output_tokens,
                     outcome,created_at,settled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (reservation_id, response_id, source_hash, article_id, stage, period, None,
                     'imported', 0, 0, inputs, outputs, 'success', at, at))
                imported += 1
                context = {'articleId': article_id, 'stage': stage,
                           'periodKey': period, 'at': at}
                totals_article = self._totals(db, 'WHERE article_id=? AND period_key=?',
                                              (article_id, period))
                totals_period = self._totals(db, 'WHERE period_key=?', (period,))
                zero = {'calls': 0, 'inputTokens': 0, 'outputTokens': 0}
                attributed = article_id != UNATTRIBUTED_ARTICLE
                self._warnings(db, context, totals_article, totals_period, zero,
                               include_article=attributed)
                scopes = [('period', totals_period)]
                if attributed:
                    scopes.insert(0, ('article', totals_article))
                for budget_scope, totals in scopes:
                    for dimension in DIMENSIONS:
                        cap = self.config[budget_scope][dimension]
                        if totals[dimension] > cap:
                            self._event(db, context, 'hold', budget_scope, dimension,
                                        cap, totals[dimension])
            db.commit()
        return {'imported': imported, 'existing': existing}

    def inspect(self, now=None):
        at = _aware(now if now is not None else datetime.now(JST))
        period_key = self._period_key(at)
        with self._read() as db:
            period = self._totals(db, 'WHERE period_key=?', (period_key,))
            articles = {}
            for (article_id,) in db.execute(
                    'SELECT DISTINCT article_id FROM model_budget_reservations '
                    'WHERE article_id<>? AND period_key=? ORDER BY article_id',
                    (UNATTRIBUTED_ARTICLE, period_key)):
                articles[article_id] = self._totals(
                    db, 'WHERE article_id=? AND period_key=?', (article_id, period_key))
            legacy = self._totals(db, 'WHERE article_id=? AND period_key=?',
                                  (UNATTRIBUTED_ARTICLE, period_key))
            statuses = Counter(row[0] for row in db.execute(
                'SELECT status FROM model_budget_reservations'))
            events = Counter(row[0] for row in db.execute('SELECT status FROM model_budget_events'))
        return {'status': 'read_only', 'periodKey': period_key,
                'period': period, 'articles': articles, 'legacyUnattributed': legacy,
                'reservationsByStatus': dict(sorted(statuses.items())),
                'eventsByStatus': dict(sorted(events.items())),
                'limits': copy.deepcopy(self.config),
                'reservationInputUnit': 'utf8_payload_bytes_upper_bound'}

    @staticmethod
    def _event_value(row):
        keys = ('id', 'periodKey', 'articleId', 'stage', 'level', 'budgetScope',
                'dimension', 'cap', 'projected', 'status', 'createdAt')
        return dict(zip(keys, row))

    def pending_events(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('invalid event limit')
        with self._read() as db:
            rows = db.execute('''SELECT event_id,period_key,article_id,stage,level,
                budget_scope,dimension,cap,projected,status,created_at
                FROM model_budget_events WHERE status='pending'
                ORDER BY created_at,event_id LIMIT ?''', (limit,)).fetchall()
        return [self._event_value(row) for row in rows]

    def claim_event(self, event_id):
        event_id = _safe_text(event_id, 'event id')
        now = datetime.now(JST).isoformat()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('''UPDATE model_budget_events SET status='in_flight',claimed_at=?
                                    WHERE event_id=? AND status='pending' ''',
                                 (now, event_id)).rowcount
            if changed != 1:
                db.commit()
                return None
            row = db.execute('''SELECT event_id,period_key,article_id,stage,level,
                budget_scope,dimension,cap,projected,status,created_at
                FROM model_budget_events WHERE event_id=?''', (event_id,)).fetchone()
            db.commit()
        return self._event_value(row)

    def finish_event(self, event_id, verified):
        event_id = _safe_text(event_id, 'event id')
        if type(verified) is not bool:
            raise ValueError('verified boolean required')
        final = 'verified' if verified else 'unknown'
        now = datetime.now(JST).isoformat()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM model_budget_events WHERE event_id=?',
                             (event_id,)).fetchone()
            if row is None:
                raise ValueError('budget event not found')
            if row[0] == final:
                db.commit()
                return {'id': event_id, 'status': final}
            if row[0] != 'in_flight':
                raise ValueError('budget event not claimed')
            db.execute('''UPDATE model_budget_events SET status=?,finished_at=?
                          WHERE event_id=?''', (final, now, event_id))
            db.commit()
        return {'id': event_id, 'status': final}
