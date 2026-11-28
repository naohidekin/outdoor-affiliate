"""Bounded deterministic reports on the existing tick; no LLM or approval changes."""
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import urlsplit

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


def valid_report_reconciliation(root, kind, period, scope):
    """Verify additive native-delivery evidence without changing either receipt."""
    root = Path(root).resolve()
    if kind not in ('weekly','editorial','monthly') or not isinstance(period,str) \
            or not isinstance(scope,dict) or not scope:
        return False
    receipt = read_snapshot(root/'report-reconciliations'/kind/(period+'.json'))
    if not receipt or receipt.get('status') != 'evidence_reconciled' \
            or receipt.get('kind') != kind or receipt.get('period') != period \
            or receipt.get('scope') != scope:
        return False

    def bound(spec, expected=None):
        if not isinstance(spec,dict) or set(spec) != {'path','sha256'} \
                or not isinstance(spec.get('path'),str) \
                or not re.fullmatch(r'[a-f0-9]{64}',str(spec.get('sha256',''))):
            return None
        path = root/spec['path']
        try:
            resolved = path.resolve()
            if resolved.parent != root and root not in resolved.parents or path.is_symlink() \
                    or not path.is_file() or (expected and spec['path'] != expected):
                return None
            raw = path.read_bytes()
            if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != spec['sha256']:
                return None
            return raw
        except OSError:
            return None

    original = bound(receipt.get('original'),f'reports/{kind}/{period}.json')
    outbound = bound(receipt.get('outbound'))
    proof_raw = bound(receipt.get('nativeProof'))
    if original is None or outbound is None or proof_raw is None:
        return False
    try: proof,outbound_value = json.loads(proof_raw),json.loads(outbound)
    except (ValueError,TypeError): return False
    expected = outbound_value.get('expected') if isinstance(outbound_value,dict) else None
    text = expected.get('text') if isinstance(expected,dict) else None
    if not isinstance(text,str) or outbound_value.get('status') != 'sent_unverified' \
            or expected.get('channel') != scope.get('channel_id') \
            or expected.get('thread_ts') != scope.get('thread_ts'):
        return False
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    proof_scope = proof.get('scope') if isinstance(proof,dict) else None
    bot = scope.get('bot_user_id')
    parts = proof.get('parts') if isinstance(proof,dict) else None
    valid_parts = isinstance(parts,list) and len(parts) == 2 and all(
        isinstance(part,dict) and set(part) == {'ts','textSha256','chars','user','thread_ts'}
        and re.fullmatch(r'\d{10}\.\d{6}',str(part.get('ts','')))
        and re.fullmatch(r'[a-f0-9]{64}',str(part.get('textSha256','')))
        and type(part.get('chars')) is int and part['chars'] >= 0
        and part.get('user') == bot and part.get('thread_ts') == scope.get('thread_ts')
        for part in parts)
    return bool(isinstance(proof,dict) and proof.get('status') == 'verified'
        and proof.get('readOnly') is True and proof.get('scanComplete') is True
        and proof.get('joinMode') == 'decodedNewline'
        and proof.get('expectedTextSha256') == proof.get('observedTextSha256') == text_hash
        and proof.get('outboundSha256') == receipt['outbound']['sha256']
        and proof.get('originalReportSha256') == receipt['original']['sha256']
        and proof_scope == scope
        and isinstance(bot,str) and bool(bot) and valid_parts
        and [part['ts'] for part in parts] == sorted(part['ts'] for part in parts)
        and outbound_value.get('message_ts') == parts[-1]['ts'])


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


def _awaiting_astra(job):
    if job.get('stage') != 'review' or not (job.get('kind') == 'article_revision'
                                           or 'catalogCorrectionContext' in job):
        return False
    from ledger import valid_astra_review
    try:
        valid_astra_review(job.get('astraReview'), job.get('revision'))
        return False
    except ValueError:
        return True


def editorial_report(jobs, now=None, rolling=False, kind='editorial'):
    now = _now(now)
    jobs = jobs[:1000]
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6 if rolling else now.weekday())
    end = now
    label = '直近7日の編集作業' if rolling else '今週の編集状況'
    if kind == 'monthly':
        end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = '前月の編集作業'
    published = [j for j in jobs if _published_between(j, start, end)]
    astra_waiting = sum(_awaiting_astra(j) for j in jobs)
    waiting = sum(j.get('stage') == 'review' and not _awaiting_astra(j) for j in jobs)
    social_waiting = sum(j.get('stage') == 'social_review' for j in jobs)
    paused = sum(j.get('stage') in ('held', 'error') for j in jobs)
    lines = [label + f'（{start:%Y/%m/%d}〜{end:%Y/%m/%d} JST）',
             f'新編集台帳で確認した期間内公開: {len(published)}件',
             '旧経路を含むサイト全体の公開件数ではありません。']
    for job in published[:20]:
        title = str((job.get('bundle') or {}).get('article', {}).get('title') or (job.get('theme') or {}).get('title') or '記事')[:120].replace('\n', ' ')
        url = (job.get('publication') or {}).get('url')
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            safe = bool(parsed and parsed.scheme == 'https' and parsed.hostname == 'camp-gear-lab.com'
                        and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                        and parsed.path.startswith('/articles/') and '%' not in url)
        except ValueError:
            safe = False
        lines.append(f'・{title}' + ('\n' + url if safe else '（公開URL未確認）'))
    if len(published) > 20:
        lines.append(f'公開記事の一覧は20件まで表示、残り{len(published) - 20}件は省略。')
    if len(jobs) == 1000:
        lines.append('台帳の確認は最大1000件。件数は確認範囲内です。')
    lines += [f'現在の確認待ち・保留（{now:%Y/%m/%d %H:%M} JST時点、対象期間の実績とは別）',
             f'Astra品質確認待ち（承認カード未送信）: {astra_waiting}件',
             f'記事の確認待ち（繰越含む）: {waiting}件',
             f'SNS原稿の確認待ち: {social_waiting}件', f'保留・確認が必要: {paused}件']
    visible = [j for j in jobs if j.get('stage') in ('review', 'social_review', 'held', 'error')]
    for job in visible[:3]:
        title = str((job.get('theme') or {}).get('title') or '記事')[:120].replace('\n', ' ')
        state = {'review': '内容確認待ち', 'social_review': 'SNS原稿確認待ち', 'held': '保留',
                 'error': '確認が必要'}.get(job.get('stage'), '処理中')
        if _awaiting_astra(job):
            state = 'Astra品質確認待ち（承認カード未送信）'
        lines.append(f'・{title}：{state}')
    lines.append('状況共有のみです。承認の再依頼や新しい承認ボタンは発行していません。')
    return '\n'.join(lines)


def seo_status(root, editorial_root=None, kind='weekly', now=None):
    """Render bounded period work/usage inline; missing helper fails closed."""
    from seo_summary import build_seo_summary
    return build_seo_summary(root, editorial_root, kind=kind, now=now)


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
            if valid_report_reconciliation(self.root,kind,period,self.config.get('slack',{})):
                return {'kind':kind,'period':period,'status':'evidence_reconciled'}
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
                from seo_summary import manager_usage_summary, stage_usage_summary
                text = (editorial_report(jobs, now=now) + '\n\n' +
                        manager_usage_summary(self.root, kind='editorial', now=now) + '\n\n' +
                        stage_usage_summary(self.root, kind='weekly', now=now))
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
                learning = {'status': 'unavailable'}
                try:
                    from editorial_learning import build_receipt, store_receipt
                    learning = store_receipt(self.root, build_receipt(
                        kind, period, report['evidence'], jobs, now=now))
                except Exception:
                    # Learning is additive evidence only. It must never change an
                    # existing report send/reconciliation outcome or trigger retry.
                    pass
                text = report['text']
                unavailable = kind == 'monthly' and not all(report['evidence'].get(k) for k in ('current', 'ga4'))
                text = editorial_report(jobs, now=now, rolling=kind == 'weekly', kind=kind) + '\n\n' + text
                text += '\n\n' + seo_status(self.config.get('seoStateRoot'), self.root, kind=kind, now=now)
            from usage_cost_report import usage_cost_summary
            feedback = read_snapshot(self.root / 'seo-feedback' / 'latest.json')
            summary = feedback.get('summary') if isinstance(feedback, dict) else None
            keys = ('reanalysisObserved', 'measurementWaiting',
                    'postchangePerformanceMeasured', 'requiresReconciliation')
            if isinstance(summary, dict) and all(type(summary.get(k)) is int
                                               and 0 <= summary[k] <= 10 for k in keys):
                text += ('\n\nSEO改善循環：再分析確認' + str(summary['reanalysisObserved'])
                         + '件／公開後の計測待ち' + str(summary['measurementWaiting'])
                         + '件／公開後の実測' + str(summary['postchangePerformanceMeasured'])
                         + '件／照合が必要' + str(summary['requiresReconciliation'])
                         + '件。前後の数値変化は、改稿による因果効果の証明ではありません。')
            text += '\n\n' + usage_cost_summary(
                self.root, self.config, kind='monthly' if kind == 'monthly' else 'weekly', now=now)
            if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                raise ValueError('report_text_invalid')
            receipt = previous_warning if unavailable and previous_warning else self.slack.notice(text)
            if not isinstance(receipt, dict) or receipt.get('verified') is not True or not receipt.get('message_ts'):
                raise ValueError('report_delivery_unknown')
            status = 'verified_unavailable' if unavailable else 'verified'
            _atomic(marker, {'status': status, 'kind': kind, 'period': period,
                             'at': now.isoformat(), 'receipt': receipt,
                             **({'learning': learning} if kind in ('weekly', 'monthly') else {}),
                             **({'retryAfter': (now + timedelta(days=1)).isoformat()} if unavailable else {})})
            return {'kind': kind, 'period': period, 'status': 'data_pending' if unavailable else 'verified'}
        except Exception:
            # Preserve the durable in_flight receipt; even a transport exception
            # may follow a successful Slack send. No raw exception is persisted.
            return {'kind': kind, 'period': period, 'status': 'requires_reconciliation'}

    def tick(self, jobs=None, now=None):
        return [self.send(kind, jobs=jobs, now=now) for kind in ('weekly', 'editorial', 'monthly')]
