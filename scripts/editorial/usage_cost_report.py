"""Read-only, deterministic model usage/cost summaries for existing reports."""
from collections import defaultdict
import copy
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

JST = timezone(timedelta(hours=9))
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_USAGE_FILES = 5000
TOKEN_KEYS = {
    'input': ('input_tokens', 'input', 'prompt_tokens'),
    'output': ('output_tokens', 'output', 'completion_tokens'),
    'cache_read': ('cache_read_input_tokens', 'cached_input_tokens', 'cached_prompt_tokens'),
    'cache_write': ('cache_write_input_tokens', 'cache_creation_input_tokens'),
}


def _now(value):
    value = value or datetime.now(JST)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('usage_report_aware_time_required')
    return value.astimezone(JST)


def _window(kind, now, period_key):
    if kind == 'weekly':
        end = now.date() - timedelta(days=(now.weekday() - 3) % 7)
        start, basis = end - timedelta(days=6), 'completed_fri_thu'
    elif kind == 'monthly':
        end = now.date().replace(day=1) - timedelta(days=1)
        start, basis = end.replace(day=1), 'previous_calendar_month'
    elif kind == 'production':
        try:
            start = date.fromisoformat(period_key)
        except (TypeError, ValueError):
            raise ValueError('production_period_key_invalid') from None
        end, basis = start + timedelta(days=6), 'configured_production_period'
    else:
        raise ValueError('usage_report_kind_invalid')
    return start, end, basis


def _read_json(path):
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _parse_at(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(JST) if parsed.tzinfo is not None else None
    except (AttributeError, ValueError, OverflowError):
        return None


def _stage_records(root):
    db_path = root / 'ledger.sqlite3'
    if not db_path.is_file() or db_path.is_symlink():
        return []
    uri = 'file:' + quote(str(db_path), safe='/') + '?mode=ro'
    result = []
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            rows = db.execute("SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")
            for (raw,) in rows:
                try:
                    record = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                for batch in record.get('usageBatches', []):
                    if not isinstance(batch, dict):
                        continue
                    for call in batch.get('records', []):
                        if isinstance(call, dict):
                            item = copy.deepcopy(call)
                            item.setdefault('articleId', record.get('jobId'))
                            item.setdefault('stage', record.get('stage'))
                            result.append((batch.get('recordedAt') or record.get('updatedAt'), item))
    except (OSError, sqlite3.Error):
        return []
    return result


def _usage_records(root):
    result = []
    folder = root / 'usage'
    try:
        paths = sorted(folder.glob('*.json'))[:MAX_USAGE_FILES]
    except OSError:
        paths = []
    for path in paths:
        value = _read_json(path)
        if value is None:
            continue
        for call in value.get('calls', []):
            if isinstance(call, dict):
                result.append((call.get('at') or value.get('at'), copy.deepcopy(call)))
    # Canonical usage files win ties because they retain article/stage attribution.
    # Resolve response identity before any caller applies a reporting window, so
    # journal/save timestamp skew cannot charge one response in adjacent periods.
    canonical, seen = [], set()
    for at, call in result + _stage_records(root):
        response_id = call.get('responseId')
        if isinstance(response_id, str) and response_id:
            if response_id in seen:
                continue
            seen.add(response_id)
        canonical.append((at, call))
    return canonical


def _number(value):
    return value if (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value) and value >= 0) else None


def _token(usage, names, *, required=False):
    present = [usage[name] for name in names if name in usage]
    if len(present) > 1 or (present and (type(present[0]) is not int or present[0] < 0)):
        return None
    return present[0] if present else (None if required else 0)


def _tokens(call):
    usage = call.get('usage')
    if not isinstance(usage, dict):
        if type(call.get('input')) is int and type(call.get('output')) is int:
            usage = {'input': call['input'], 'output': call['output']}
        else:
            return None
    values = {name: _token(usage, keys, required=name in ('input', 'output'))
              for name, keys in TOKEN_KEYS.items()}
    if any(value is None for value in values.values()):
        return None
    values.update(cache_write_5m=0, cache_write_1h=0, cache_write_ttl_known=False)
    creation = usage.get('cache_creation')
    if isinstance(creation, dict):
        allowed = {'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'}
        if set(creation) - allowed:
            return None
        nested = list(creation.values())
        if any(type(value) is not int or value < 0 for value in nested):
            return None
        if values['cache_write'] and values['cache_write'] != sum(nested):
            return None
        values['cache_write'] = sum(nested)
        values['cache_write_5m'] = creation.get('ephemeral_5m_input_tokens', 0)
        values['cache_write_1h'] = creation.get('ephemeral_1h_input_tokens', 0)
        values['cache_write_ttl_known'] = True
    if 'cached_prompt_tokens' in usage:
        if 'prompt_tokens' not in usage or values['cache_read'] > values['input']:
            return None
        values['input'] -= values['cache_read']
    return values


def _pricing(config, now):
    raw = config.get('modelUsagePricing', {})
    if not isinstance(raw, dict):
        raise ValueError('model_usage_pricing_invalid')
    result = {}
    required = {'inputUsdPerMillion', 'outputUsdPerMillion', 'source', 'checkedAt'}
    allowed = required | {'cacheReadUsdPerMillion', 'cacheWriteUsdPerMillion',
                          'cacheWrite5mUsdPerMillion', 'cacheWrite1hUsdPerMillion',
                          'ratesValidUntil'}
    for model, value in raw.items():
        try:
            if not isinstance(model, str) or not model or not isinstance(value, dict):
                raise ValueError()
            if not required <= set(value) or set(value) - allowed:
                raise ValueError()
            checked = _parse_at(value['checkedAt'])
            if (not isinstance(value['source'], str) or not value['source']
                    or checked is None or checked > now):
                raise ValueError()
            for key in allowed - {'source', 'checkedAt', 'ratesValidUntil'}:
                if key in value and _number(value[key]) is None:
                    raise ValueError()
            expiry = value.get('ratesValidUntil')
            if expiry is not None:
                expiry_date = date.fromisoformat(expiry[:10])
                if now.date() > expiry_date:
                    continue
            result[model] = copy.deepcopy(value)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError('model_usage_pricing_invalid') from None
    return result


def _counter():
    return {'calls': 0, 'inputTokens': 0, 'outputTokens': 0,
            'cacheReadTokens': 0, 'cacheWriteTokens': 0}


def _add(counter, tokens):
    counter['calls'] += 1
    if tokens is not None:
        counter['inputTokens'] += tokens['input']
        counter['outputTokens'] += tokens['output']
        counter['cacheReadTokens'] += tokens['cache_read']
        counter['cacheWriteTokens'] += tokens['cache_write']


def _cost(tokens, price):
    keys = [('input', 'inputUsdPerMillion'), ('output', 'outputUsdPerMillion'),
            ('cache_read', 'cacheReadUsdPerMillion')]
    if tokens['cache_write_ttl_known']:
        keys += [('cache_write_5m', 'cacheWrite5mUsdPerMillion'),
                 ('cache_write_1h', 'cacheWrite1hUsdPerMillion')]
    else:
        keys.append(('cache_write', 'cacheWriteUsdPerMillion'))
    if any(tokens[token] and key not in price for token, key in keys):
        return None
    return sum(tokens[token] * price.get(key, 0) / 1_000_000 for token, key in keys)


def _budget_snapshot(root, config, now):
    try:
        from model_budget import ModelBudget, _config
        from production_schedule import ProductionSchedule
        inspector = object.__new__(ModelBudget)  # inspect-only: avoid schema writes in reports.
        inspector.root, inspector.db_path = root, root / 'ledger.sqlite3'
        inspector.production_schedule = ProductionSchedule(config.get('productionSchedule'))
        inspector.config = _config(config.get('modelBudget'))
        raw = inspector.inspect(now)
    except (OSError, sqlite3.Error, ValueError):
        return {'status': 'unavailable'}

    def projected(totals, limits):
        value = copy.deepcopy(totals)
        value['ratios'] = {key: totals[key] / limits[key] for key in
                           ('calls', 'inputTokens', 'outputTokens')}
        value['remaining'] = {key: max(0, limits[key] - totals[key]) for key in
                              ('calls', 'inputTokens', 'outputTokens')}
        return value
    return {'status': 'read_only', 'periodKey': raw['periodKey'],
            'period': projected(raw['period'], raw['limits']['period']),
            'articles': {article: projected(value, raw['limits']['article'])
                         for article, value in raw['articles'].items()},
            'articleLabels': _article_labels(root, raw['articles']),
            'legacyUnattributed': raw['legacyUnattributed']}


def _article_labels(root, articles):
    jobs = {}
    uri = 'file:' + quote(str(root / 'ledger.sqlite3'), safe='/') + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            for raw, in db.execute('SELECT data FROM jobs'):
                job = json.loads(raw)
                if not isinstance(job, dict) or job.get('id') not in articles:
                    continue
                theme = job.get('theme')
                label = ((theme.get('title') or theme.get('slug'))
                         if isinstance(theme, dict) else theme)
                if isinstance(label, str) and label.strip():
                    jobs[job['id']] = label.strip().replace('\n', ' ')[:60]
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass
    labels, hidden = {}, 0
    for article in articles:
        if article in jobs:
            labels[article] = jobs[article]
        elif isinstance(article, str) and len(article) <= 40 and not re.fullmatch(r'[a-f0-9]{32,}', article):
            labels[article] = article
        else:
            hidden += 1
            labels[article] = f'記事scope {hidden}'
    return labels


def _unknown_reservations(root, period_key):
    path = root / 'ledger.sqlite3'
    if not path.is_file():
        return None
    uri = 'file:' + quote(str(path), safe='/') + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            row = db.execute("SELECT count(*) FROM model_budget_reservations "
                             "WHERE status='unknown' AND period_key=?", (period_key,)).fetchone()
            return int(row[0])
    except sqlite3.Error:
        return None


def _codex_task_usage(root, now):
    value = _read_json(root / 'task-usage' / 'codex-task.json')
    unavailable = {'status': 'unavailable',
                   'reason': 'task_attributed_codex_tokens_unavailable'}
    if value is None:
        return unavailable
    observed = _parse_at(value.get('observedAt'))
    if not (value.get('source') == 'codex_local_thread_counters'
            and value.get('unit') == 'local_cumulative_token_counter'
            and value.get('scope') == 'registered_camp_task_threads_only'
            and value.get('taskAttribution') is True
            and value.get('subscriptionPercent') is None
            and value.get('attributionOverlapUnknown') is True
            and observed is not None and timedelta(0) <= now - observed <= timedelta(hours=24)
            and isinstance(value.get('threads'), list)):
        return unavailable
    main, helpers = [], []
    for thread in value['threads']:
        if not isinstance(thread, dict) or thread.get('role') not in ('main', 'helper'):
            return unavailable
        if any(type(thread.get(key)) is not int or thread[key] < 0
               for key in ('counter', 'periodBaseline')):
            return unavailable
        delta = thread.get('delta')
        status = thread.get('status', 'measured' if type(delta) is int else None)
        if ((type(delta) is not int or delta < 0)
                and not (delta is None and status == 'baseline_only')):
            return unavailable
        baseline = _parse_at(thread.get('baselineAt'))
        if baseline is None or thread.get('coveragePartial') is not True:
            return unavailable
        clean = {key: thread[key] for key in
                 ('role', 'counter', 'periodBaseline', 'delta', 'coveragePartial')}
        clean.update(status=status, baselineAt=baseline.isoformat())
        (main if thread['role'] == 'main' else helpers).append(clean)
    if len(main) != 1:
        return unavailable
    return {'status': 'available', 'source': value['source'], 'unit': value['unit'],
            'observedAt': observed.isoformat(), 'main': main[0], 'helpers': helpers,
            'attributionOverlapUnknown': True, 'subscriptionPercent': None}


def usage_cost_report(root, config, kind='weekly', now=None, period_key=None):
    """Return bounded read-only usage, cost and budget evidence."""
    root, now = Path(root).resolve(), _now(now)
    if kind == 'production' and period_key is None:
        from production_schedule import ProductionSchedule
        period_key = ProductionSchedule(config.get('productionSchedule')).period_key(now)
    start, end, basis = _window(kind, now, period_key)
    prices = _pricing(config, now)
    models, stages = defaultdict(_counter), defaultdict(_counter)
    missing_usage = 0
    missing_article = missing_stage = 0
    invoice_values, actual_values, estimates = [], [], []
    invoice_known = actual_known = estimate_known = 0
    unknown_models = set()
    for at_raw, call in _usage_records(root):
        at = _parse_at(at_raw)
        if at is None or at > now or not start <= at.date() <= end:
            continue
        model = call.get('actualModel') if 'actualModel' in call else call.get('model')
        if not call.get('articleId'):
            missing_article += 1
        model = model if isinstance(model, str) and model else '実モデル未確認'
        tokens = _tokens(call)
        _add(models[model], tokens)
        stage = call.get('stage')
        if isinstance(stage, str) and stage:
            _add(stages[stage], tokens)
        else:
            missing_stage += 1
        if tokens is None:
            missing_usage += 1
        invoice = _number(call.get('actualInvoiceUsd'))
        actual = _number(call.get('actualUSD'))
        if invoice is not None:
            invoice_values.append(invoice); invoice_known += 1
        if actual is not None:
            actual_values.append(actual); actual_known += 1
        price = prices.get(model)
        estimate = _cost(tokens, price) if tokens is not None and price is not None else None
        if estimate is not None:
            estimates.append(estimate); estimate_known += 1
        elif tokens is not None:
            unknown_models.add(model)
    total = _counter()
    for value in models.values():
        for key in total:
            total[key] += value[key]
    total_calls = total['calls']
    money = lambda values, known: {'value': sum(values) if known else None,
                                    'knownCalls': known, 'totalCalls': total_calls,
                                    'complete': known == total_calls}
    budget = _budget_snapshot(root, config, now)
    codex_task = _codex_task_usage(root, now)
    return {
        'kind': kind,
        'window': {'start': start.isoformat(), 'end': end.isoformat(),
                   'timezone': 'Asia/Tokyo', 'basis': basis},
        'totals': total, 'models': dict(sorted(models.items())),
        'stages': dict(sorted(stages.items())),
        'missingUsage': {'calls': missing_usage},
        'missingAttribution': {'calls': max(missing_article, missing_stage),
                               'articleCalls': missing_article, 'stageCalls': missing_stage},
        'costs': {'actualInvoiceUSD': money(invoice_values, invoice_known),
                  'actualUSD': money(actual_values, actual_known),
                  'estimatedUSD': {**money(estimates, estimate_known),
                                   'basis': 'current_rate_rough_estimate',
                                   'qualification': 'rough_estimate_at_current_configured_rates'},
                  'unknownModels': sorted(unknown_models)},
        'reservations': {'unknownCalls': _unknown_reservations(root, budget.get('periodKey'))
                         if budget.get('periodKey') else None,
                         'label': 'reserved_not_measured'},
        'budget': budget,
        'subscription': {
            'percent': None, 'reason': 'subscription_denominator_not_available',
            'scope': 'task_attributed_only',
            'claudeIncludedApiCredits': {'percent': None, 'reason': 'verified_plan_pool_unavailable'},
            'chatgptCodex': {'percent': None, 'taskUsage': codex_task,
                             'reason': ('verified_plan_pool_unavailable'
                                        if codex_task['status'] == 'available'
                                        else 'task_attributed_codex_tokens_unavailable')},
        },
    }


def _usd(value):
    return '未確定' if value is None else f'${value:.4f}'


def _cost_text(value):
    rendered = _usd(value['value'])
    if value['knownCalls'] != value['totalCalls']:
        rendered += f'（{value["knownCalls"]}/{value["totalCalls"]}件のみ）'
    return rendered


def usage_cost_summary(root, config, kind='weekly', now=None, period_key=None):
    """Render a short Japanese inline summary; performs no model or network call."""
    data = usage_cost_report(root, config, kind=kind, now=now, period_key=period_key)
    start, end = date.fromisoformat(data['window']['start']), date.fromisoformat(data['window']['end'])
    weekdays = '月火水木金土日'
    lines = [f'モデル利用・費用（{start:%Y/%m/%d}（{weekdays[start.weekday()]}）〜'
             f'{end:%Y/%m/%d}（{weekdays[end.weekday()]}）JST、金〜木の費用窓）']
    for model, row in data['models'].items():
        lines.append(f'・{model}: {row["calls"]}回／入力{row["inputTokens"]:,}／出力{row["outputTokens"]:,}'
                     f'／cache読{row["cacheReadTokens"]:,}・書{row["cacheWriteTokens"]:,}')
    if not data['models']:
        lines.append('・対象期間の利用記録なし')
    if data['stages']:
        lines.append('stage別: ' + '、'.join(f'{name} {row["calls"]}回' for name, row in data['stages'].items()))
    unknown_reservations = data['reservations']['unknownCalls']
    reservation_text = '読取不可' if unknown_reservations is None else f'{unknown_reservations}件'
    lines.append(f'欠測: usage欠測{data["missingUsage"]["calls"]}件、帰属不明 '
                 f'article {data["missingAttribution"]["articleCalls"]}件／'
                 f'stage {data["missingAttribution"]["stageCalls"]}件、予約値のみ・未実測'
                 f'{reservation_text}')
    costs = data['costs']
    lines.append('費用（混算なし）: 実請求USD ' + _cost_text(costs['actualInvoiceUSD']) +
                 '／実測USD ' + _cost_text(costs['actualUSD']) +
                 '／現行単価による概算 ' + _cost_text(costs['estimatedUSD']))
    if costs['unknownModels']:
        lines.append('概算単価不明（0円扱いしない）: ' + '、'.join(costs['unknownModels']))
    budget = data['budget']
    if budget.get('status') == 'read_only':
        row = budget['period']
        lines.append(f'現在production period（{budget["periodKey"]}）予算: '
                     f'calls {row["calls"]}/{row["calls"] + row["remaining"]["calls"]} '
                     f'({row["ratios"]["calls"]:.1%})、入力残{row["remaining"]["inputTokens"]:,}、'
                     f'出力残{row["remaining"]["outputTokens"]:,}（上記費用窓とは別）')
        for article, value in list(budget['articles'].items())[:5]:
            label = budget['articleLabels'].get(article, '記事scope')
            lines.append(f'・記事予算 {label}: calls {value["ratios"]["calls"]:.1%}／'
                         f'入力 {value["ratios"]["inputTokens"]:.1%}／出力 {value["ratios"]["outputTokens"]:.1%}')
        if len(budget['articles']) > 5:
            lines.append(f'・記事予算は残り{len(budget["articles"]) - 5}件省略')
    else:
        lines.append('現在production period予算: 読取不可')
    codex = data['subscription']['chatgptCodex']['taskUsage']
    if codex['status'] == 'available':
        main = codex['main']
        if main['delta'] is None:
            lines.append(f'Codexこのタスク分（ローカル累積counter、課金token未認証）: '
                         f'親 累積counter {main["counter"]:,}／期間delta未取得。'
                         f'baseline {main["baselineAt"][:10]}（report窓とは別、coverage partial）。')
        else:
            helper_values = '、'.join(
                '未取得' if item['delta'] is None else f'{item["delta"]:,}'
                for item in codex['helpers']) or 'なし'
            lines.append(f'Codexこのタスク分（ローカル累積counter、課金token未認証）: '
                         f'親delta {main["delta"]:,}／helper各delta {helper_values}。'
                         f'baseline {main["baselineAt"][:10]}（report窓とは別）。'
                         '親子重複不明のため合算なし。')
    else:
        lines.append('Codexこのタスク分token未取得（アカウント全体の利用率を代理値にしません）')
    lines.append('サブスク使用率: 算出不可（このタスクへの帰属と検証済み契約分母が未確認）')
    return '\n'.join(lines)
