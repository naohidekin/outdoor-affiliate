"""Read-only bounded excerpts and measured-usage summary; no SEO decisions.

Weekly is seven inclusive JST dates through today, distinct from the analytics
report's rolling 28-day measurement window. Monthly is the previous JST calendar
month. Only dated agent reports, usage.json and editorial usage/*.json are read;
sourcePaths, provider bodies and raw logs are never followed or rendered.
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import itertools
import json
import math
import re

JST = timezone(timedelta(hours=9))
MAX_BYTES = 128 * 1024
MAX_FILES = 32
MAX_SCAN = 512
MAX_ROWS = 1000
MAX_TEXT = 4500
OMITTED = '…（省略）'
LABELS = ('実施内容', '判断理由', '結果・欠測', '次の作業')
ALIASES = {'実施内容': '実施内容', '判断理由': '判断理由', '判断の理由': '判断理由',
           '結果・欠測': '結果・欠測', '結果/欠測': '結果・欠測', '結果': '結果・欠測',
           '欠測': '結果・欠測', '次の作業': '次の作業', '翌週方針': '次の作業',
           '次の作業・翌週方針': '次の作業', '次の作業/翌週方針': '次の作業'}
REPORT = re.compile(r'agent-campgearlab-seo-(\d{4}-\d{2}-\d{2})-[A-Za-z0-9_.-]+\.md\Z')
SECRET = re.compile(r'(?i)(?:api[_ -]?key|access[_ -]?token|authorization|password|private[_ -]?key)\s*[:=]|'
                    r'-----BEGIN|\bxox[baprs]-|\bxapp-|\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{12,}|\bAIza[A-Za-z0-9_-]{20,}')


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit - len(OMITTED)] + OMITTED


def _now(now):
    now = now or datetime.now(JST)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError('timezone-aware now required')
    return now.astimezone(JST)


def _period(kind, now):
    today = now.date()
    if kind == 'weekly':
        return today - timedelta(days=6), today
    if kind == 'monthly':
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    raise ValueError('kind must be weekly or monthly')


def _instant(value):
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return at.astimezone(JST) if at.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _num(value):
    if type(value) not in (int, float):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def _format(value):
    if value is None:
        return '未確認'
    return f'{value:.5g}' if value >= 10 ** 9 else f'{value:,.4f}'.rstrip('0').rstrip('.')


def _clean(text):
    """Remove operational identifiers/paths, not substantive numeric evidence."""
    if SECRET.search(text) or re.search(r'\bsourcePaths\b', text, re.I):
        return '（機密・内部参照の行は省略）'
    text = re.sub(r'(?:https?://|https?%3a(?:%2f){2})[^\s<>）)\]]+',
                  '（URL省略）', text, flags=re.I)
    text = re.sub(r'(?<![:/\w])(?:~?/|[A-Za-z]:\\)[^\s、。）」)\]]+', '（内部パス省略）', text)
    text = re.sub(r'(?<![\w/])(?:scripts|reports|state|model-artifacts|usage|docs)/[^\s、。）」)\]]+',
                  '（内部パス省略）', text)
    text = re.sub(r'\b(?:experimentId|request_id|manifest_hash|nonce|responseId|threadId|runId)\s*[:：=]\s*[^\s、。]+',
                  '（内部ID省略）', text, flags=re.I)
    text = re.sub(r'\b(?:commit|sha256|hash|revision)\s*[:：=]?\s+[A-Za-z0-9._-]+',
                  '（内部ID省略）', text, flags=re.I)
    text = re.sub(r'\b(?:exp|experiment|article|camp|run|req|request)-[A-Za-z0-9_-]+\b|'
                  r'\bmsg_[A-Za-z0-9_-]+\b|\b[0-9a-f]{24,}\b|'
                  r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', '（内部ID省略）', text, flags=re.I)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    # Output is plain-text Slack: prevent manual mention/link control strings.
    return re.sub(r'<[^>]*>', '（参照省略）', text).strip()


class _Reader:
    def __init__(self):
        self.count = 0
        self.notes = set()

    def read(self, path, as_json=False):
        if self.count >= MAX_FILES:
            self.notes.add('ファイル数上限により省略あり')
            return None
        self.count += 1
        try:
            if path.is_symlink() or not path.is_file():
                self.notes.add('読取不可・リンクの記録を除外')
                return None
            with path.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                self.notes.add('128KiB超の記録を省略')
                return None
            text = raw.decode('utf-8')
            return json.loads(text) if as_json else text
        except (OSError, ValueError, UnicodeError, RecursionError):
            self.notes.add('未取得・不正な記録あり')
            return None

    def files(self, folder):
        if folder is None:
            return []
        try:
            if folder.is_symlink():
                self.notes.add('リンクされた参照先は省略')
                return []
            with_scan = list(itertools.islice(folder.iterdir(), MAX_SCAN + 1))
            if len(with_scan) > MAX_SCAN:
                self.notes.add('ディレクトリ件数上限により省略あり')
            return with_scan[:MAX_SCAN]
        except OSError:
            self.notes.add('参照先の記録なし・取得未確認')
            return []


def _sections(text):
    sections = {key: [] for key in LABELS}
    active = None
    mode = None
    in_code = False
    names = '|'.join(sorted(map(re.escape, ALIASES), key=len, reverse=True))
    label = re.compile(r'^\s*(?:#{1,6}\s*)?(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*|【)?('
                       + names + r')(?:\*\*|】)?\s*(?:[:：]\s*(.*)|$)')
    for line in text.splitlines():
        if line.lstrip().startswith(('```', '~~~')):
            in_code = not in_code
            active = None
            continue
        if in_code:
            continue
        if not line.strip():
            if mode == 'inline':
                active = None
            continue
        match = label.match(line)
        if match:
            active = ALIASES[match[1]]
            mode = 'heading' if re.match(r'^\s*#{1,6}\s', line) else 'inline'
            line = match[2] or ''
        elif re.match(r'^\s*#{1,6}\s', line):
            active = None
        elif mode == 'inline' and re.match(r'^\s*(?:[-*+]\s+)?(?:\*\*|【)?[^\s:：]{1,30}(?:\*\*|】)?\s*[:：]', line):
            active = None
        if active and line.strip():
            # Never relabel historic experimental numbers as this period's work.
            if re.search(r'過去|旧実験|ベースライン|参考値|履歴', line) and re.search(r'\d', line):
                sections[active].append('（過去参照の数値は省略）')
            else:
                sections[active].append(_clean(line.strip()))
    return sections


def _reports(root, start, end, reader, kind):
    candidates = []
    for path in reader.files(root / 'reports' if root else None):
        match = REPORT.fullmatch(path.name)
        if not match:
            continue
        try:
            day = date.fromisoformat(match[1])
        except ValueError:
            continue
        if start <= day <= end:
            candidates.append((day, path))
    candidates.sort(key=lambda entry: (entry[0], entry[1].name), reverse=True)
    limit = 12 if kind == 'monthly' else 3
    entries = []
    for day, path in candidates:
        if len(entries) >= limit or reader.count >= MAX_FILES - 2:
            break
        text = reader.read(path)
        if text is None:
            continue
        sections = _sections(text)
        lines = [f'{day.isoformat()}のAstra記録（抜粋）']
        labels = (('実施内容', '判断理由' if sections['判断理由'] else '結果・欠測')
                  if kind == 'monthly' else LABELS)
        for label in labels:
            value = ' '.join(sections[label])
            lines.append(label + ': ' + (_clip(value, 100 if kind == 'monthly' else 155) if value else '該当ラベルの記録なし'))
        entries.append('\n'.join(lines))
    if len(candidates) > len(entries):
        reader.notes.add(f'Astra期間内{len(candidates)}件中{len(entries)}件抜粋（{len(candidates) - len(entries)}件省略）')
    return '\n\n'.join(entries) if entries else 'Astra判断・実施記録: 記録なし（未実行とは断定しません）'


def _kind(value):
    return value if value in ('operations', 'implementation', 'research', 'editorial', 'article', 'social') else '区分未確認'


def _model(value):
    if isinstance(value, str) and len(value) <= 65 and re.fullmatch(r'(?:gpt-|claude-|gemini-|codex-|o[1-9])[A-Za-z0-9_.-]*', value):
        return value
    return 'モデル未確認'


def _usage(seo_root, editorial_root, start, end, now, reader):
    groups, seen = {}, set()
    unknown, allocated = 0, 0
    run_credits = []

    def eligible(at):
        nonlocal unknown
        if at is None:
            unknown += 1
            return False
        return start <= at.date() <= end and at <= now

    def add(kind, row, editorial=False):
        key = (_kind(kind), _model(row.get('model')))
        if key not in groups and len(groups) >= 64:
            reader.notes.add('モデル区分数上限により省略あり')
            return
        totals = groups.setdefault(key, {key: [] for key in ('input', 'cache', 'output', 'credits', 'api')})
        usage = row.get('usage') if isinstance(row.get('usage'), dict) else {}
        values = (dict(input=row.get('input'), cache=usage.get('cache_read_input_tokens'),
                       output=row.get('output'), credits=None, api=None) if editorial else
                  dict(input=row.get('inputTokens'), cache=row.get('cachedInputTokens'),
                       output=row.get('outputTokens'), credits=row.get('codexCreditsEstimate'), api=row.get('apiUsdEstimate')))
        for field, value in values.items():
            totals[field].append(_num(value))

    data = reader.read(seo_root / 'usage.json', True) if seo_root else None
    runs = data.get('runs') if isinstance(data, dict) else None
    if isinstance(runs, list):
        if len(runs) > MAX_ROWS:
            reader.notes.add('SEO使用量件数上限により省略あり')
        for run in runs[:MAX_ROWS]:
            if not isinstance(run, dict):
                continue
            identity = run.get('id')
            if isinstance(identity, str) and identity in seen:
                continue
            if isinstance(identity, str):
                seen.add(identity)
            finished, started = _instant(run.get('finishedAt')), _instant(run.get('startedAt'))
            at = finished or started
            if finished is None and started is not None:
                reader.notes.add('終了時刻未記録分は開始時刻で配分')
            if not eligible(at):
                continue
            allocated += 1
            run_credits.append(_num(run.get('codexCreditsEstimate')))
            models = run.get('models')
            if isinstance(models, list):
                for model in models[:MAX_ROWS]:
                    if isinstance(model, dict):
                        add(run.get('kind'), model)
    elif data is not None:
        reader.notes.add('SEO使用量形式が未確認')
    files = sorted((p for p in reader.files(editorial_root / 'usage' if editorial_root else None)
                    if p.suffix == '.json'), key=lambda p: p.name)
    if len(files) > MAX_FILES - reader.count:
        reader.notes.add('編集使用量ファイル上限により省略あり')
    for path in files:
        if reader.count >= MAX_FILES:
            break
        data = reader.read(path, True)
        if not isinstance(data, dict) or not isinstance(data.get('calls'), list):
            reader.notes.add('編集使用量の未取得・形式未確認あり')
            continue
        if not eligible(_instant(data.get('at'))):
            continue
        allocated += 1
        if len(data['calls']) > MAX_ROWS:
            reader.notes.add('編集使用量件数上限により省略あり')
        for call in data['calls'][:MAX_ROWS]:
            if not isinstance(call, dict):
                continue
            identity = call.get('responseId')
            if isinstance(identity, str) and ('editorial', identity) in seen:
                continue
            if isinstance(identity, str):
                seen.add(('editorial', identity))
            add('editorial', call, True)

    def known(values):
        numeric = [v for v in values if v is not None]
        return _num(sum(numeric)) if numeric else None

    lines = ['使用量（期間内・既知分のみ。欠損値を0扱いしません）',
             '実請求USD: 未確認。API比較推定は実費ではない。料金の再計算はしていません。',
             '過去分・日時不明の期間未配分: ' + (str(unknown) + '件（期間合計へ含めず）' if unknown else ('確認した記録にはなし' if allocated else '確認できる記録なし'))]
    if not allocated:
        lines.append('対象期間へ配分できる使用量: 記録なし')
    if len(groups) > 8:
        reader.notes.add('使用モデルは8区分まで表示（他は省略）')
    for (kind, model), totals in sorted(groups.items())[:8]:
        kind = '編集運用・復旧' if kind == 'editorial' else kind
        values = {key: _format(known(value)) for key, value in totals.items()}
        lines.append(f"{kind} / {model}: 入力{values['input']}・キャッシュ入力{values['cache']}・出力{values['output']} tokens / "
                     f"Codex credits推定{values['credits']} / API比較推定USD {values['api']}（実費ではない）")
    if run_credits:
        lines.append('SEO実行単位のCodex credits推定（既知分・モデル別と重複）: ' + _format(known(run_credits)))
    return '\n'.join(lines)


def build_seo_summary(seo_root, editorial_root, kind='weekly', now=None):
    """Return weekly <=4500 / monthly <=6000 chars; missing roots allowed. No writes."""
    now = _now(now)
    start, end = _period(kind, now)
    seo_root = Path(seo_root) if seo_root else None
    editorial_root = Path(editorial_root) if editorial_root else None
    reader = _Reader()
    reports = _reports(seo_root, start, end, reader, kind)
    usage = _usage(seo_root, editorial_root, start, end, now, reader)
    lines = [f'SEO作業・使用量の記録 {start.isoformat()}〜{end.isoformat()}（JST）',
             '既存記録の抜粋です。新しいSEO判断や因果・成果の判定は追加していません。',
             _clip(reports, 3400 if kind == 'monthly' else 2250), _clip(usage, 1550)]
    if reader.notes:
        lines.append('確認範囲: ' + ' / '.join(sorted(reader.notes)))
    lines.append('予定（JST）: SEOは月・木14時、記事は水曜9時。週次報告は月曜20時、編集状況は木曜20時、月次報告は毎月5日20時。')
    return _clip('\n\n'.join(lines), 6000 if kind == 'monthly' else MAX_TEXT)


def summary(config, kind='weekly', now=None):
    return build_seo_summary(config.get('seoStateRoot'), config.get('stateRoot'), kind, now)
