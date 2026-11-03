"""Offline, bounded analytics evidence and deterministic Japanese Slack reports.

No network, environment access or writes. analyticsRoot is reserved for the runtime;
only seoStateRoot/metrics/latest.json is read. Dates retain their source timezone.
Raw search queries/referrer strings never cross this boundary. Weekly means 28
inclusive source dates, not a calendar week. Monthly requires the previous JST
calendar month; collectors must supply separate exact calendar snapshots.
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import ipaddress
import json
import math
import re

JST = timezone(timedelta(hours=9))
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
MAX_EVIDENCE = 30
FIELDS = ('clicks', 'impressions', 'ctr', 'position')


def _now(value):
    value = value or datetime.now(JST)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('now must be a timezone-aware datetime')
    return value.astimezone(JST)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, OverflowError):
        return None


def _stats(row, fields=FIELDS):
    row = row if isinstance(row, dict) else {}
    return {key: _number(row.get(key)) for key in fields}


def _url(value, relative=False):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    decoded = unquote(value.split('?', 1)[0].split('#', 1)[0])
    if re.search(r'[\x00-\x20<>|@\\]|\d{7,}', decoded):
        return None
    try:
        u = urlsplit(value)
        # Published article slugs are ASCII. Reject encoded path delimiters,
        # including double encoding, before a private query can masquerade as
        # a visible page path in reports or model input.
        if '%' in u.path or '%' in u.netloc:
            return None
        if relative and not u.scheme and not u.netloc and u.path.startswith('/articles/'):
            return u.path
        if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password:
            return None
        host = u.hostname.lower()
        if host == 'localhost' or '.' not in host or u.port not in (None, 80, 443):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        return urlunsplit((u.scheme, u.netloc.lower(), u.path or '/', '', ''))
    except ValueError:
        return None


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid date')
    return date.fromisoformat(value)


def _zone(value):
    try:
        return ZoneInfo(value) if isinstance(value, str) else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _period(raw, now, gsc, warnings, label):
    if not isinstance(raw, dict) or raw.get('status') != 'ok':
        warnings.append(f'{label}: 未取得または取得保留')
        return None
    try:
        start, end = _day(raw.get('startDate')), _day(raw.get('endDate'))
        zone = _zone(raw.get('dateBasis'))
        today = now.astimezone(zone or JST).date()
        if start > end or end >= today:
            raise ValueError('future or incomplete period')
        if gsc and (not zone or end > _day(raw.get('settledThrough'))
                    or _day(raw.get('settledThrough')) >= today):
            raise ValueError('unsettled GSC')
    except (ValueError, TypeError):
        warnings.append(f'{label}: 未来・未確定・不正な期間を除外')
        return None
    if not zone:
        warnings.append(f'{label}: タイムゾーン未検証')
    return dict(startDate=start.isoformat(), endDate=end.isoformat(),
                dateBasis=raw.get('dateBasis') if zone else 'unverified')


def _rows(raw, key):
    rows = raw.get(key, [])
    return rows[:MAX_ROWS] if isinstance(rows, list) else []


def _gsc(raw, now, warnings, label):
    period = _period(raw, now, True, warnings, label)
    if not period:
        return None
    site = _url(raw.get('siteUrl'))
    pages = {}
    for row in _rows(raw, 'pages'):
        if not isinstance(row, dict):
            continue
        url = _url(row.get('url'))
        if not url or not site or urlsplit(url).netloc != urlsplit(site).netloc:
            continue
        # Query-string variants can collapse: never sum duplicate page metrics.
        clean = dict(url=url, **_stats(row))
        if url not in pages or (clean['impressions'] or 0) > (pages[url]['impressions'] or 0):
            pages[url] = clean
    candidates = []
    for row in _rows(raw, 'candidates'):
        if not isinstance(row, dict):
            continue
        url = _url(row.get('url'))
        if not url or not site or urlsplit(url).netloc != urlsplit(site).netloc:
            continue
        for sample in _rows(row, 'queries')[:12]:
            if not isinstance(sample, dict):
                continue
            clean = _stats(sample)
            if clean['position'] is not None and 3 < clean['position'] <= 20 and (clean['impressions'] or 0) >= 30:
                candidates.append(dict(url=url, **clean, metricScope='query_page_sample'))
                break
    ordered = sorted(pages.values(), key=lambda p: (-(p['impressions'] or 0), p['url']))
    return dict(**period, status='ok', siteUrl=site,
                country=raw.get('country') if raw.get('country') in ('jpn', 'JPN') else 'unverified',
                searchType=raw.get('searchType') if raw.get('searchType') in ('web', 'image', 'video', 'news') else 'unverified',
                settledThrough=raw['settledThrough'], summary=_stats(raw.get('summary') or {}),
                pages=ordered[:MAX_EVIDENCE], candidates=candidates[:MAX_EVIDENCE])


def _ai_referrals(raw):
    rows = []
    allowed = {'chatgpt.com', 'chat.openai.com', 'perplexity.ai', 'copilot.microsoft.com',
               'gemini.google.com', 'claude.ai'}
    for row in _rows(raw, 'aiReferrals'):
        try:
            source = row['dimensionValues'][0]['value'].lower()
            path = _url(row['dimensionValues'][1]['value'], relative=True)
            values = row['metricValues']
            sessions = _number(values[0]['value'])
            events = _number(values[1]['value'])
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
        if source in allowed and path and path.startswith('/articles/'):
            rows.append(dict(source=source, path=path, sessions=sessions, keyEvents=events))
    return sorted(rows, key=lambda row: (-(row['sessions'] or 0), row['source'], row['path']))[:MAX_EVIDENCE]


def _ga4(raw, now, warnings, label='GA4'):
    period = _period(raw, now, False, warnings, label)
    if not period:
        return None
    pages = {}
    valid = True
    source_rows = _rows(raw, 'landingPages')
    for row in source_rows:
        try:
            path = _url(row['dimensionValues'][0]['value'], relative=True)
            values = row['metricValues']
            stats = {key: _number(values[i].get('value')) for i, key in enumerate(('sessions', 'engagedSessions', 'keyEvents'))}
        except (KeyError, IndexError, TypeError, AttributeError):
            valid = False
            continue
        if not path or not path.startswith('/articles/'):
            valid = False
            continue
        # LandingPagePlusQueryString is disjoint: sum variants after stripping queries.
        existing = pages.setdefault(path, dict(path=path, sessions=0, engagedSessions=0, keyEvents=0))
        for key, value in stats.items():
            if value is None or existing[key] is None:
                existing[key] = None
                valid = False
            else:
                existing[key] = _number(existing[key] + value)
    if not valid or len(source_rows) >= MAX_ROWS or len(pages) > MAX_EVIDENCE:
        warnings.append(f'{label}: 欠損・除外・件数上限あり。取得範囲のみの集計')
    coverage = raw.get('coverage')
    verified = (isinstance(coverage, dict) and coverage.get('verified') is True
                and coverage.get('scope') == 'site' and coverage.get('complete') is True
                and valid and len(source_rows) < MAX_ROWS)
    return dict(**period, status='ok', landingPages=sorted(pages.values(), key=lambda p: p['path'])[:MAX_EVIDENCE],
                sessions=(_number(sum(p['sessions'] for p in pages.values()))
                          if pages and all(p['sessions'] is not None for p in pages.values()) else None),
                coverageVerified=verified, aiReferrals=_ai_referrals(raw), revenue='未接続')


def _opportunities(current, ga4):
    if not current:
        return []
    match = (ga4 and all(current[k] == ga4[k] for k in ('startDate', 'endDate')))
    landing = {p['path']: p for p in ga4['landingPages']} if match else {}
    options = []
    seen = set()
    for page in current['pages'] + current['candidates']:
        impressions, position = page['impressions'], page['position']
        if impressions is None or position is None or impressions < 30 or not 3 < position <= 20:
            continue
        if page['url'] in seen or not urlsplit(page['url']).path.startswith('/articles/'):
            continue
        seen.add(page['url'])
        options.append(dict(action='improve_existing', url=page['url'],
                            reason='表示実績と平均掲載順位を根拠に既存記事の見出し・内容を確認',
                            gsc=dict(_stats(page), metricScope=page.get('metricScope', 'page')), ga4=(dict(landing[urlsplit(page['url']).path],
                                      sourcePeriod={k: ga4[k] for k in ('startDate', 'endDate', 'dateBasis')})
                                 if urlsplit(page['url']).path in landing else None),
                            cannibalizationCheck='required', publication='manual_review'))
    return sorted(options, key=lambda p: (-p['gsc']['impressions'], p['gsc']['position'], p['url']))[:3]


def _context(metrics, now):
    warnings = []
    out = dict(schemaVersion=1, status='unavailable', collectedAt=None,
               evidence=dict(current=None, previous=None, ga4=None), opportunities=[],
               uncertainty=warnings, provenance=dict(source='Google collector snapshot', operationTimezone='Asia/Tokyo'))
    try:
        if not isinstance(metrics, dict) or metrics.get('schemaVersion') != 1:
            raise ValueError('schema')
        collected = datetime.fromisoformat(metrics['collectedAt'].replace('Z', '+00:00'))
        if collected.tzinfo is None or not timedelta(0) <= now - collected <= timedelta(hours=72):
            raise ValueError('freshness')
    except (KeyError, ValueError, TypeError, AttributeError):
        warnings.append('指標の取得時刻が不明・未来・72時間超のため利用保留')
        return out
    out['collectedAt'] = collected.astimezone(JST).isoformat()
    current = _gsc(metrics.get('current'), now, warnings, 'GSC')
    if current and (now.date() - _day(current['endDate'])).days > 35:
        warnings.append('GSC: 対象期間が古いため保留')
        current = None
    previous = _gsc(metrics.get('previous'), now, warnings, '比較GSC')
    ga4 = _ga4(metrics.get('ga4'), now, warnings)
    if ga4 and (now.date() - _day(ga4['endDate'])).days > 35:
        warnings.append('GA4: 対象期間が古いため保留')
        ga4 = None
    out['evidence'] = dict(current=current, previous=previous, ga4=ga4)
    out['status'] = 'ok' if current or ga4 else 'unavailable'
    out['opportunities'] = _opportunities(current, ga4)
    if current and ga4 and current['dateBasis'] != ga4['dateBasis']:
        warnings.append('GSCとGA4は日付表記が同じでもタイムゾーンが異なり、集計時刻は一致しません')
    warnings.append('検索語は非開示。カニバリゼーション・季節性は未検証。改善案は上位モデルの審査待ち')
    return out


class Analytics:
    def __init__(self, config):
        self.config = dict(config)

    def load_context(self, now=None):
        now = _now(now)
        try:
            path = Path(self.config['seoStateRoot']) / 'metrics' / 'latest.json'
            with path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('oversized')
            metrics = json.loads(data)
        except (OSError, ValueError, KeyError, TypeError):
            metrics = None
        return _context(metrics, now)


def _range(source):
    return f"{source['startDate']}〜{source['endDate']} ({source['dateBasis']})"


def _value(value):
    return '未取得' if value is None else f'{value:,.2f}'.rstrip('0').rstrip('.')


def _change(current, previous):
    if current is None or previous is None:
        return '比較未取得'
    if previous == 0:
        return '前期0のため増減率なし'
    change = (current / previous - 1) * 100
    return f'{change:+.1f}%' if math.isfinite(change) else '増減率算出不可'


def _comparison(current, previous):
    if not current or not previous:
        return False
    a, b = _day(current['startDate']), _day(current['endDate'])
    c, d = _day(previous['startDate']), _day(previous['endDate'])
    return (d == a - timedelta(days=1) and b - a == d - c
            and all(current.get(k) == previous.get(k) for k in ('dateBasis', 'siteUrl', 'country', 'searchType')))


def build_report(metrics, previous_ga4=None, kind='weekly', jobs=None, now=None):
    """Accept a raw collector snapshot (previousGa4 supported); return Slack-ready data.

    Monthly comparison is the preceding calendar month, even if lengths differ.
    No publication or queue mutation occurs. jobs only contributes bounded counts.
    """
    if kind not in ('weekly', 'monthly'):
        raise ValueError('kind must be weekly or monthly')
    now = _now(now)
    context = _context(metrics, now)
    evidence = context['evidence']
    warnings = context['uncertainty']
    first = now.date().replace(day=1)
    end = first - timedelta(days=1)
    start = end.replace(day=1)
    expected = (start.isoformat(), end.isoformat())
    for key in ('current', 'ga4'):
        source = evidence[key]
        if source and ((kind == 'monthly' and (source['startDate'], source['endDate']) != expected)
                       or (kind == 'weekly' and (_day(source['endDate']) - _day(source['startDate'])).days != 27)):
            evidence[key] = None
            warnings.append(f'{key}: 指定レポート期間と不一致のため保留')
    current, previous, ga4 = (evidence[k] for k in ('current', 'previous', 'ga4'))
    comparable = _comparison(current, previous)
    if kind == 'monthly' and current and previous:
        prior_end = start - timedelta(days=1)
        comparable = ((previous['startDate'], previous['endDate']) ==
                      (prior_end.replace(day=1).isoformat(), prior_end.isoformat()) and
                      all(current.get(k) == previous.get(k) for k in ('dateBasis', 'siteUrl', 'country', 'searchType')))
    title = f"月次SEOレポート {end:%Y年%m月}" if kind == 'monthly' else '週次SEOレポート（直近28日・暦週ではありません）'
    lines = [title]
    if current:
        lines.append('GSC: ' + _range(current))
        if comparable:
            lines.append('比較期間: ' + _range(previous))
        else:
            warnings.append('GSC比較期間・集計条件が未確認のため増減率は保留')
        totals = current['summary']
        for key, label in (('clicks', 'クリック'), ('impressions', '表示'), ('ctr', 'CTR'), ('position', '平均掲載順位')):
            value = totals[key]
            rendered = f'{value * 100:.2f}%' if key == 'ctr' and value is not None else _value(value)
            change = _change(value, previous['summary'][key]) if comparable else '比較保留'
            lines.append(f'{label}: {rendered}（{change}）')
    else:
        lines.append('GSC: 対象期間の確定データ待ち')
    if ga4:
        label = 'サイト全体セッション' if ga4['coverageVerified'] else '取得した記事入口の合計'
        lines.append(f"GA4: {_range(ga4)} / {label}: {_value(ga4['sessions'])}")
        raw_previous = previous_ga4 if previous_ga4 is not None else (metrics if isinstance(metrics, dict) else {}).get('previousGa4')
        old = _ga4(raw_previous, now, warnings, '比較GA4')
        evidence['previousGa4'] = old
        ga_compare = _comparison(ga4, old)
        if kind == 'monthly' and old:
            prior_end = start - timedelta(days=1)
            ga_compare = ((old['startDate'], old['endDate']) == (prior_end.replace(day=1).isoformat(), prior_end.isoformat())
                          and old['dateBasis'] == ga4['dateBasis'])
        if ga_compare and ga4['dateBasis'] != 'unverified' and old['coverageVerified'] and ga4['coverageVerified']:
            lines.append(f"GA4比較: {_range(old)} / {_change(ga4['sessions'], old['sessions'])}")
        else:
            warnings.append('GA4比較は期間・タイムゾーン・網羅性の確認待ち')
    else:
        lines.append('GA4: 対象期間データ待ち')
    if ga4 and ga4['aiReferrals']:
        lines.append('AI参照流入: 取得した参照元の範囲のみ。引用数・AI回答への掲載数ではありません')
    lines.append('売上・購入・注文: 未接続（0件とは判定しません）')
    options = _opportunities(current, ga4)
    for i, option in enumerate(options, 1):
        lines.append(f"改善候補{i}: {option['url']} / {'検索語別サンプル表示' if option['gsc']['metricScope'] == 'query_page_sample' else 'ページ表示'}{_value(option['gsc']['impressions'])}・平均順位{_value(option['gsc']['position'])} / 既存記事改善、競合記事との重複確認が必要")
    if not options:
        lines.append('改善候補: 判断に足る指標待ち')
    bounded_jobs = [job for job in (jobs or [])[:MAX_ROWS] if isinstance(job, dict)]
    if bounded_jobs and not all(isinstance(job.get('stage'), str) for job in bounded_jobs):
        lines.append('承認待ち件数: 状態未確認 / 未承認の公開なし')
    else:
        article_pending = sum(job.get('stage') in ('review', 'awaiting_approval') for job in bounded_jobs)
        social_pending = sum(job.get('stage') in ('social_review', 'social_awaiting_approval') for job in bounded_jobs)
        lines.append(f'承認待ち: 記事{article_pending}件・SNS{social_pending}件 / 未承認の公開なし')
    lines.append('注意: ' + ' / '.join(dict.fromkeys(warnings)))
    evidence['uncertainty'] = list(dict.fromkeys(warnings))
    evidence['provenance'] = dict(context['provenance'], collectedAt=context['collectedAt'])
    return dict(title=title, text='\n'.join(lines), evidence=evidence, opportunities=options)
