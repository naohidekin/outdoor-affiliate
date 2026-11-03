"""Bounded deterministic reports on the existing tick; no LLM or approval changes."""
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess

JST = timezone(timedelta(hours=9))
MAX_BYTES = 4 * 1024 * 1024


def _now(now=None):
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        raise ValueError('report_aware_time_required')
    return now.astimezone(JST)


def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_snapshot(path):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def slot(kind, now=None, manual=False):
    """Catch up within this JST week/month only; never replay old periods."""
    now = _now(now)
    monday = now.date() - timedelta(days=now.weekday())
    if kind in ('weekly', 'editorial'):
        day = monday + timedelta(days=0 if kind == 'weekly' else 3)
        due = datetime.combine(day, datetime.min.time(), JST).replace(hour=20)
        return monday.isoformat() if manual or now >= due else None
    if kind == 'monthly':
        due = now.replace(day=5, hour=20, minute=0, second=0, microsecond=0)
        return (now.date().replace(day=1) - timedelta(days=1)).strftime('%Y-%m') if manual or now >= due else None
    raise ValueError('report_kind_invalid')


def _published_between(job, start, end):
    publication = job.get('publication') or {}
    if publication.get('verified') is not True:
        return False
    try:
        at = datetime.fromisoformat(publication.get('at', '').replace('Z', '+00:00'))
        return at.tzinfo is not None and start <= at <= end
    except (ValueError, TypeError):
        return False


def editorial_report(jobs, now=None, rolling=False):
    now = _now(now)
    jobs = jobs[:1000]
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6 if rolling else now.weekday())
    published = sum(_published_between(j, start, now) for j in jobs)
    waiting = sum(j.get('stage') == 'review' for j in jobs)
    social_waiting = sum(j.get('stage') == 'social_review' for j in jobs)
    paused = sum(j.get('stage') in ('held', 'error') for j in jobs)
    lines = [('直近7日の編集作業' if rolling else '今週の編集状況') + f'（{start:%m/%d}〜{now:%m/%d} JST）',
             f'期間内の公開確認済み: {published}件', f'記事の確認待ち（繰越含む）: {waiting}件',
             f'SNS原稿の確認待ち: {social_waiting}件', f'保留・確認が必要: {paused}件']
    visible = [j for j in jobs if j.get('stage') in ('review', 'social_review', 'held', 'error')
               or _published_between(j, start, now)]
    for job in visible[:3]:
        title = str((job.get('theme') or {}).get('title') or '記事')[:120].replace('\n', ' ')
        state = ('公開確認済み' if (job.get('publication') or {}).get('verified') else
                 {'review': '内容確認待ち', 'held': '保留', 'error': '確認が必要',
                  'candidate': '制作候補', 'approved': '承認済み・公開確認待ち'}.get(job.get('stage'), '処理中'))
        lines.append(f'・{title}：{state}')
    lines.append('状況共有のみです。承認の再依頼や新しい承認ボタンは発行していません。')
    return '\n'.join(lines)


def seo_status(root, editorial_root=None, kind='weekly', now=None):
    """Use only bounded structured metadata, never forward historical prose."""
    if root and editorial_root:
        try:
            from seo_summary import build_seo_summary
        except ImportError:
            pass  # Explicit unavailable fallback while the helper is unconfigured.
        else:
            return build_seo_summary(root, editorial_root, kind=kind, now=now)
    if not root:
        return 'SEO実行状況: 参照先未設定\n費用: 実費未確認'
    root = Path(root)
    latest = read_snapshot(root / 'reports' / 'latest.json') or {}
    at = latest.get('generatedAt')
    try:
        parsed = datetime.fromisoformat(at.replace('Z', '+00:00'))
        at = parsed.astimezone(JST).strftime('%m/%d %H:%M JST') if parsed.tzinfo else '時刻未確認'
    except (ValueError, TypeError, AttributeError):
        at = '時刻未確認'
    status = {'healthy': '正常', 'completed': '完了', 'success': '成功', 'ok': '正常',
              'blocked': '保留', 'error': '確認が必要', 'skipped': '見送り'}.get(latest.get('executionStatus'), '未確認')
    lines = [f'SEO最新実行: {status}（{at}）']
    if latest.get('modelExecuted') is False:
        lines.append('上記実行でAstraの新しい判断は行っていません。過去の判断を今週の実績には数えません。')
    elif latest.get('modelExecuted') is True:
        lines.append('上記実行にモデル実行の記録あり。判断本文はSEOレポートで確認してください。')
    lines.append('SEO判断の参照先: reports/latest.json・対応レポート（履歴本文は転送しません）')
    lines.append('費用: 対象期間の集計は未接続・実費未確定。利用量や推計値は請求確定額ではありません。')
    lines.append('次の編集制作: 水曜09時JST以降、週3候補・未公開3件の上限に従います。')
    return '\n'.join(lines)


class Reporter:
    def __init__(self, config, slack, env=None, collector=None):
        self.config, self.slack, self.env = dict(config), slack, dict(env or {})
        self.root = Path(config['stateRoot'])
        self.analytics_root = Path(config.get('analyticsRoot') or self.root / 'analytics')
        self.collector = collector or self._collect_month

    def _collect_month(self, month, now):
        if not self.config.get('seoRepo'):
            raise ValueError('monthly_collector_unconfigured')
        child_env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR')}
        child_env.update({k: v for k, v in self.env.items()
                          if k in ('INDEXING_CREDENTIALS', 'GOOGLE_CREDENTIALS', 'GA4_PROPERTY_ID')})
        child_env['TZ'] = 'Asia/Tokyo'
        try:
            result = subprocess.run([self.config.get('node', 'node'),
                str(Path(__file__).with_name('collect-report-metrics.mjs'))],
                input=json.dumps({'seoRepo': self.config['seoRepo'], 'month': month, 'now': now.isoformat()}),
                env=child_env, capture_output=True, text=True, timeout=240)
            if result.returncode or len(result.stdout.encode()) > MAX_BYTES:
                raise ValueError('monthly_collection_unavailable')
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or data.get('schemaVersion') != 1:
                raise ValueError('monthly_collection_unavailable')
            return data
        except (OSError, subprocess.SubprocessError, ValueError):
            raise ValueError('monthly_collection_unavailable') from None

    def send(self, kind, jobs=None, now=None, manual=False):
        if self.config.get('reportsEnabled') is not True:
            return {'kind': kind, 'status': 'disabled'}
        slot(kind, now, manual)  # Validate before using kind in a path.
        folder = self.root / 'reports' / kind
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        with (folder / '.flock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'kind': kind, 'status': 'busy'}
            return self._send(kind, jobs, now, manual)

    def _send(self, kind, jobs=None, now=None, manual=False):
        now = _now(now)
        period = slot(kind, now, manual)
        if period is None:
            return {'kind': kind, 'status': 'not_due'}
        marker = self.root / 'reports' / kind / (period + '.json')
        # O_EXCL also protects manual commands from concurrent ticks. Once a
        # send might have happened, no error path automatically retries it.
        marker.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        previous_warning = None
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = read_snapshot(marker) or {}
            if kind == 'monthly' and existing.get('status') == 'verified_unavailable':
                if not manual and now.isoformat() < existing.get('retryAfter', ''):
                    return {'kind': kind, 'period': period, 'status': 'data_pending'}
                previous_warning = existing.get('receipt')
                fd = os.open(marker, os.O_WRONLY | os.O_TRUNC)
            else:
                return {'kind': kind, 'period': period,
                        'status': 'already_verified' if existing.get('status') == 'verified' else 'requires_reconciliation'}
        with os.fdopen(fd, 'w') as stream:
            json.dump({'status': 'in_flight', 'at': now.isoformat(), 'kind': kind, 'period': period}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(marker.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        try:
            jobs = jobs or []
            unavailable = False
            if kind == 'editorial':
                text = editorial_report(jobs, now=now)
            else:
                from analytics import build_report
                if kind == 'monthly':
                    try:
                        metrics = self.collector(period, now)
                        _atomic(self.analytics_root / 'monthly' / period / 'snapshot.json', metrics)
                    except Exception:
                        metrics = None
                else:
                    source = self.config.get('seoStateRoot')
                    metrics = read_snapshot(Path(source) / 'metrics' / 'latest.json') if source else None
                statuses = [{'stage': j.get('stage')} for j in jobs[:1000]]
                report = build_report(metrics, kind=kind, jobs=statuses, now=now)
                text = report['text']
                unavailable = kind == 'monthly' and not all(report['evidence'].get(k) for k in ('current', 'ga4'))
                if kind == 'weekly':
                    text = editorial_report(jobs, now=now, rolling=True) + '\n\n' + text
                text += '\n\n' + seo_status(self.config.get('seoStateRoot'), self.root, kind=kind, now=now)
            if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                raise ValueError('report_text_invalid')
            receipt = previous_warning if unavailable and previous_warning else self.slack.notice(text)
            if not isinstance(receipt, dict) or receipt.get('verified') is not True or not receipt.get('message_ts'):
                raise ValueError('report_delivery_unknown')
            status = 'verified_unavailable' if unavailable else 'verified'
            _atomic(marker, {'status': status, 'kind': kind, 'period': period,
                             'at': now.isoformat(), 'receipt': receipt,
                             **({'retryAfter': (now + timedelta(days=1)).isoformat()} if unavailable else {})})
            return {'kind': kind, 'period': period, 'status': 'data_pending' if unavailable else 'verified'}
        except Exception:
            # Preserve the durable in_flight receipt; even a transport exception
            # may follow a successful Slack send. No raw exception is persisted.
            return {'kind': kind, 'period': period, 'status': 'requires_reconciliation'}

    def tick(self, jobs=None, now=None):
        return [self.send(kind, jobs=jobs, now=now) for kind in ('weekly', 'editorial', 'monthly')]
