"""Once-per-JST-day deterministic GA4/GSC collection for the existing runner."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from reporting import _atomic

JST = timezone(timedelta(hours=9))
MAX_BYTES = 4 * 1024 * 1024


def _now(value=None):
    value = value or datetime.now(JST)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('daily_metrics_aware_time_required')
    return value.astimezone(JST)


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('daily_metrics_invalid')
    return date.fromisoformat(value)


def _zone(value):
    try:
        return ZoneInfo(value)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValueError('daily_metrics_invalid') from None


def _period(value, now, *, gsc):
    if not isinstance(value, dict) or value.get('status') != 'ok':
        raise ValueError('daily_metrics_invalid')
    start, end = _day(value.get('startDate')), _day(value.get('endDate'))
    zone = _zone(value.get('dateBasis'))
    if gsc and value.get('dateBasis') != 'America/Los_Angeles':
        raise ValueError('daily_metrics_invalid')
    if start > end or (end - start).days != 27:
        raise ValueError('daily_metrics_invalid')
    today = now.astimezone(zone).date()
    if end >= today:
        raise ValueError('daily_metrics_invalid')
    if gsc:
        settled = _day(value.get('settledThrough'))
        if end > settled or settled >= today:
            raise ValueError('daily_metrics_invalid')
    elif end > today - timedelta(days=3):
        raise ValueError('daily_metrics_invalid')
    return start, end


def _validated_snapshot(value, now):
    if not isinstance(value, dict) or value.get('schemaVersion') != 1 \
            or value.get('collectionKind') != 'daily' \
            or value.get('operationTimezone') != 'Asia/Tokyo':
        raise ValueError('daily_metrics_invalid')
    try:
        collected = datetime.fromisoformat(value['collectedAt'].replace('Z', '+00:00'))
    except (KeyError, AttributeError, ValueError):
        raise ValueError('daily_metrics_invalid') from None
    if collected.tzinfo is None or collected > now or collected.astimezone(JST).date() != now.date():
        raise ValueError('daily_metrics_invalid')
    current = _period(value.get('current'), now, gsc=True)
    previous = _period(value.get('previous'), now, gsc=True)
    ga4 = _period(value.get('ga4'), now, gsc=False)
    previous_ga4 = _period(value.get('previousGa4'), now, gsc=False)
    if previous[1] + timedelta(days=1) != current[0] or ga4 != current or previous_ga4 != previous:
        raise ValueError('daily_metrics_invalid')
    if value['ga4'].get('dateBasis') != value['previousGa4'].get('dateBasis'):
        raise ValueError('daily_metrics_invalid')
    pt_today = now.astimezone(ZoneInfo('America/Los_Angeles')).date()
    if value['current'].get('settledThrough') != value['current'].get('endDate') \
            or not 1 <= (pt_today - current[1]).days <= 11:
        raise ValueError('daily_metrics_invalid')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError):
        raise ValueError('daily_metrics_invalid') from None
    if len(encoded) > MAX_BYTES:
        raise ValueError('daily_metrics_invalid')
    return json.loads(encoded)


def _marker(config, now):
    return Path(config['stateRoot']) / 'daily-metrics' / (now.date().isoformat() + '.json')


def collect_daily_metrics(config, env, *, now=None, runner=subprocess.run):
    """Attempt collection at most once for one JST day; preserve prior latest on failure."""
    if config.get('dailyMetricsEnabled') is not True:
        return {'status': 'disabled'}
    now = _now(now)
    if now.hour < 8:
        return {'status': 'not_due', 'day': now.date().isoformat()}
    marker = _marker(config, now)
    marker.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            status = json.loads(marker.read_text()).get('status')
        except (OSError, ValueError, TypeError):
            status = 'unknown'
        return {'status': 'already_' + status if status in ('success', 'failed') else 'requires_reconciliation',
                'day': now.date().isoformat()}
    attempt = {'status': 'in_flight', 'day': now.date().isoformat(), 'at': now.isoformat()}
    with os.fdopen(fd, 'w') as stream:
        json.dump(attempt, stream); stream.flush(); os.fsync(stream.fileno())
    child_env = {key: value for key, value in os.environ.items() if key in ('PATH', 'HOME', 'TMPDIR')}
    child_env.update({key: value for key, value in dict(env or {}).items()
                      if key in ('INDEXING_CREDENTIALS', 'GOOGLE_CREDENTIALS', 'GA4_PROPERTY_ID')})
    child_env['TZ'] = 'Asia/Tokyo'
    try:
        result = runner([config.get('node', 'node'),
                         str(Path(__file__).with_name('collect-report-metrics.mjs'))],
                        input=json.dumps({'kind': 'daily', 'seoRepo': config['seoRepo'],
                                          'now': now.isoformat()}),
                        env=child_env, capture_output=True, text=True, timeout=150)
        if result.returncode or len(result.stdout.encode()) > MAX_BYTES:
            raise ValueError('daily_metrics_collection_failed')
        snapshot = _validated_snapshot(json.loads(result.stdout), now)
        latest = Path(config['seoStateRoot']) / 'metrics' / 'latest.json'
        _atomic(latest, snapshot)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()
        _atomic(marker, {'status': 'success', 'day': now.date().isoformat(),
                         'at': now.isoformat(), 'snapshotSha256': hashlib.sha256(encoded).hexdigest(),
                         'currentEnd': snapshot['current']['endDate']})
        return {'status': 'success', 'day': now.date().isoformat(),
                'currentEnd': snapshot['current']['endDate']}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        _atomic(marker, {'status': 'failed', 'day': now.date().isoformat(),
                         'at': now.isoformat(), 'reason': 'daily_metrics_collection_failed'})
        return {'status': 'failed', 'day': now.date().isoformat(),
                'reason': 'daily_metrics_collection_failed'}


def require_fresh_daily_metrics(config, now=None):
    """Fail closed only when the caller is about to start new research."""
    if config.get('dailyMetricsEnabled') is not True:
        return {'status': 'disabled'}
    now = _now(now)
    marker = _marker(config, now)
    try:
        receipt = json.loads(marker.read_text())
        snapshot = json.loads((Path(config['seoStateRoot']) / 'metrics' / 'latest.json').read_text())
        snapshot = _validated_snapshot(snapshot, now)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()
        if receipt.get('status') != 'success' or receipt.get('snapshotSha256') != hashlib.sha256(encoded).hexdigest():
            raise ValueError('daily_metrics_not_fresh')
        if receipt.get('status') != 'success' or receipt.get('day') != now.date().isoformat():
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ValueError('daily_metrics_not_fresh') from None
    return {'status': 'fresh', 'day': now.date().isoformat(),
            'currentEnd': snapshot['current']['endDate']}
