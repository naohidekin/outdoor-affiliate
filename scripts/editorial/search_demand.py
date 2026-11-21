"""Private GSC query rows -> bounded controlled topic facets and measured totals.

No network/logging/writes. Raw terms (including their hashes) never leave this
module. Identical query strings are counted once, selecting one entire row
with greatest observed impressions, then clicks/completeness; conflicting copies
are disclosed. CTR comes from summed counts, position is impression-weighted.
Missing counts/weights stay unknown, never become zero or inferred demand.
"""
from datetime import date
import hashlib
import json
import math
import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_ROWS = 10000
MAX_GROUPS = 40
MAX_QUERY_LENGTH = 512
MAX_SAFE = 2**53 - 1
FACET_KEYS = ('garments', 'brands', 'problems', 'seasons', 'intents', 'gearTypes')
ALIASES = {
    'garments': {
        'down': ('ダウン', 'down jacket', 'down vest'),
        'fleece': ('フリース', 'fleece', 'シャミース'),
        'active_insulation': ('アクティブインサレーション', 'アクティブ インサレーション', 'active insulation'),
        'base_layer': ('インナー', 'ジオライン', 'ベースレイヤー', 'ベース レイヤー', 'ベースレイヤ', '肌着', 'アンダーウェア', 'アンダーウエア', 'base layer', 'baselayer'),
        'hard_shell': ('ハードシェル', 'ハード シェル', 'hard shell', 'hardshell'),
        'soft_shell': ('ソフトシェル', 'ソフト シェル', 'soft shell', 'softshell'),
        'jacket': ('ジャケット', 'jacket'),
    },
    'brands': {
        'montbell': ('モンベル', 'montbell', 'mont-bell'),
        'the_north_face': ('ノースフェイス', 'ノースフェース', 'ザ・ノース・フェイス', 'thenorthface', 'the north face', 'north face'),
        'patagonia': ('パタゴニア', 'patagonia'), 'arcteryx': ('アークテリクス', "arc'teryx", 'arcteryx'),
        'mammut': ('マムート', 'mammut'), 'marmot': ('マーモット', 'marmot'),
        'millet': ('ミレー', 'millet'), 'finetrack': ('ファイントラック', 'finetrack'),
        'icebreaker': ('アイスブレーカー', 'icebreaker'), 'smartwool': ('スマートウール', 'smartwool'),
        'workman': ('ワークマン', 'workman'), 'uniqlo': ('ユニクロ', 'uniqlo'),
        'columbia': ('コロンビア', 'columbia'), 'nanga': ('ナンガ', 'nanga'),
        'taion': ('タイオン', 'taion'), 'montane': ('モンテイン', 'montane'), 'rab': ('ラブ', 'rab'),
        'karrimor': ('カリマー', 'karrimor'), 'snow_peak': ('スノーピーク', 'snow peak', 'snowpeak'),
        'coleman': ('コールマン', 'coleman'), 'thermos': ('サーモス', 'thermos'),
        'soto': ('ソト', 'soto'), 'iwatani': ('イワタニ', 'iwatani'), 'msr': ('エムエスアール', 'msr'),
        'nemo': ('ニーモ', 'nemo'), 'dod': ('ディーオーディー', 'dod'), 'ogawa': ('小川キャンパル', 'オガワ', 'ogawa'),
        'logos': ('ロゴス', 'logos'), 'helinox': ('ヘリノックス', 'helinox'),
    },
    'problems': {
        'cold': ('寒い', '寒さ', '防寒', '冷える', '寒く', '保温', 'cold'),
        'layering': ('レイヤリング', '重ね着', 'layering'),
        'moisture': ('蒸れ', 'ムレ'), 'sweat_cold': ('汗冷え', '汗びえ'),
        'breathability': ('透湿', 'breathability'), 'quick_dry': ('速乾', 'quick dry', 'quick-drying'),
        'condensation': ('結露', 'condensation'), 'rain': ('雨', '防水', 'rain'), 'wind': ('風', '防風', 'wind'),
        'washing': ('洗濯', '手洗い', '洗える', '洗う', 'washing'),
        'care': ('手入れ', 'メンテナンス', '汚れ', 'サビ', '錆', 'maintenance'),
        'fit': ('サイズ', '着丈', '身幅', 'サイズ感', 'size', 'fit'),
        'compatibility': ('適合', '互換', 'パッキン', '交換部品', 'compatibility'),
        'packing': ('収納', '片付け', '撤収', 'packing'),
    },
    'seasons': {'winter': ('冬', 'winter'), 'autumn': ('秋', 'autumn', 'fall'),
                'spring': ('春', 'spring'), 'summer': ('夏', 'summer')},
    'intents': {
        'comparison': ('比較', '違い', 'どっち', 'どちら', '比べ', 'compare', 'comparison', 'versus', 'vs'),
        'selection': ('選び方', '選ぶ', 'おすすめ', 'お勧め', 'ランキング', 'recommendation'),
        'care': ('手入れ', 'メンテナンス', '洗濯', '洗う', '洗える', '手洗い', 'maintenance'),
        'parts_lookup': ('部品', 'パーツ', '品番', 'パッキン', 'parts'),
    },
    'gearTypes': {
        'apparel': ('ウェア', 'ウエア', 'アウター', '防寒着', '衣服', 'レイヤリング', '重ね着', 'apparel', 'layering'),
        'tent': ('テント', 'tent'), 'sleeping_bag': ('寝袋', 'シュラフ', 'sleeping bag'),
        'sleeping_pad': ('スリーピングマット', 'スリーピングパッド', 'キャンプマット', 'sleeping pad'),
        'stove': ('バーナー', 'ストーブ', 'コンロ', 'stove', 'burner'),
        'cookware': ('クッカー', '調理器具', 'cookware'), 'bottle': ('水筒', 'ボトル', 'bottle'),
        'tumbler': ('タンブラー', 'tumbler'), 'chair': ('チェア', '椅子', 'chair'),
        'table': ('テーブル', 'table'), 'lantern': ('ランタン', 'lantern'),
        'backpack': ('バックパック', 'リュック', 'backpack'),
    },
}


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().replace('’', "'").replace('‘', "'").split())


def _pattern(alias, short_brand=False):
    escaped = re.escape(alias).replace(r'\ ', r'\s+')
    if alias == 'インナー':
        return re.compile(r'インナー(?![\s・-]*(?:テント|ダウン))')
    if short_brand and not alias.isascii() and len(alias) <= 2:
        return re.compile(r'(?<![a-z0-9ぁ-んァ-ヶ一-龠])' + escaped + r'(?![a-z0-9ぁ-んァ-ヶ一-龠])')
    return re.compile((r'(?<![a-z0-9])' + escaped + r'(?![a-z0-9])') if alias.isascii() else escaped)


PATTERNS = {facet: {name: tuple(_pattern(_normal(a), facet == 'brands') for a in aliases)
                   for name, aliases in values.items()} for facet, values in ALIASES.items()}


def classify_topic(text):
    """Return only controlled sorted facet lists; never return input fragments."""
    clean = _normal(text[:4096]) if isinstance(text, str) else ''
    result = {key: sorted(name for name, patterns in PATTERNS[key].items()
                          if any(p.search(clean) for p in patterns)) for key in FACET_KEYS}
    # Down sleeping bags do not establish garment demand.
    if 'sleeping_bag' in result['gearTypes'] and 'down' in result['garments'] and not re.search(
            r'ジャケット|ベスト|ウェア|ウエア|アウター|\b(?:jacket|vest|apparel)\b', clean):
        result['garments'].remove('down')
    if result['garments'] and 'apparel' not in result['gearTypes']:
        result['gearTypes'] = sorted([*result['gearTypes'], 'apparel'])
    return result


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _period(value):
    try:
        start, end, zone = (value[k] for k in ('startDate', 'endDate', 'dateBasis'))
        if not all(isinstance(v, str) for v in (start, end, zone)) or not all(
                re.fullmatch(r'\d{4}-\d{2}-\d{2}', v) for v in (start, end)):
            return None
        if date.fromisoformat(start) > date.fromisoformat(end):
            return None
        ZoneInfo(zone)
        return dict(startDate=start, endDate=end, dateBasis=zone)
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return None


def _number(value, count=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)) or (isinstance(value, str) and len(value) > 64):
        return None
    try:
        n = float(value)
        return (int(n) if count else n) if math.isfinite(n) and 0 <= n <= MAX_SAFE and (not count or n.is_integer()) else None
    except (ValueError, OverflowError):
        return None


def _metrics(row):
    clicks, impressions = (_number(row.get(k), True) for k in ('clicks', 'impressions'))
    position = _number(row.get('position'))
    if clicks is not None and impressions is not None and clicks > impressions:
        clicks = None
    if position == 0 and impressions != 0:
        position = None
    return dict(clicks=clicks, impressions=impressions, position=position)


def _rank(m):
    return (m['impressions'] if m['impressions'] is not None else -1,
            m['clicks'] if m['clicks'] is not None else -1,
            sum(v is not None for v in m.values()), -(m['position'] if m['position'] is not None else MAX_SAFE))


def _aggregate(rows):
    result = {}
    for key in ('clicks', 'impressions'):
        total = sum(m[key] for m in rows) if all(m[key] is not None for m in rows) else None
        result[key] = total if total is None or total <= MAX_SAFE else None
    result['ctr'] = result['clicks'] / result['impressions'] if result['clicks'] is not None and result['impressions'] else None
    position = None
    if all(m['impressions'] is not None and (m['impressions'] == 0 or m['position'] is not None) for m in rows):
        weight = sum(m['impressions'] for m in rows)
        if weight:
            position = math.fsum(m['impressions'] * m['position'] for m in rows if m['impressions']) / weight
    result['averagePosition'] = position
    return result


def project_search_demand(rows, period):
    """Project ONE period's raw query aggregates. queryPages are never combined.

    facetId is SHA256(canonical controlled facets); id binds facets + period.
    Empty observed lists are distinguishable from absent/invalid datasets.
    Complete means only this returned row list, never all GSC/site/market demand.
    """
    period = _period(period)
    available = isinstance(rows, list) and period is not None
    coverage = dict(source='own_site_gsc_query_aggregates', scope='observed_query_rows_only',
        marketDemand=False, trendVerified=False, positionAggregation='impression_weighted',
        inputRowCount=len(rows) if isinstance(rows, list) else None,
        processedRowCount=None, uniqueQueryCount=None, classifiedQueryCount=None,
        unclassifiedQueryCount=None, duplicateRowCount=None, conflictingDuplicateCount=None,
        invalidRowCount=None, missingMetricsQueryCount=None, observedGroupCount=None,
        exportedGroupCount=None, inputTruncated=False, groupsTruncated=False, observedRowsComplete=False)
    out = dict(schemaVersion=1, status='available' if available else 'unavailable', period=period,
               coverage=coverage, groups=[])
    if not available:
        return out
    unique = {}; invalid = duplicates = 0; conflicts = set()
    for row in rows[:MAX_ROWS]:
        if not isinstance(row, dict) or not isinstance(row.get('query'), str) or not 1 <= len(row['query']) <= MAX_QUERY_LENGTH:
            invalid += 1; continue
        key = row['query']
        if not _normal(key):
            invalid += 1; continue
        metrics = _metrics(row)
        if key in unique:
            duplicates += 1
            if metrics != unique[key]:
                conflicts.add(key)
            if _rank(metrics) > _rank(unique[key]):
                unique[key] = metrics
        else:
            unique[key] = metrics
    grouped = {}; unclassified = 0
    for query, metrics in unique.items():
        facets = classify_topic(query)
        if not any(facets.values()):
            unclassified += 1; continue
        facet_id = _hash(facets)
        group = grouped.setdefault(facet_id, dict(facets=facets, rows=[]))
        group['rows'].append(metrics)
    groups = []
    for facet_id, group in grouped.items():
        groups.append(dict(id='gsc-demand:' + _hash({'facets': group['facets'], 'period': period}),
            facetId=facet_id, facets=group['facets'], queryCount=len(group['rows']), metrics=_aggregate(group['rows'])))
    groups.sort(key=lambda g: (-(g['metrics']['impressions'] if g['metrics']['impressions'] is not None else -1),
                               -(g['metrics']['clicks'] if g['metrics']['clicks'] is not None else -1), g['facetId']))
    coverage.update(processedRowCount=min(len(rows), MAX_ROWS), uniqueQueryCount=len(unique),
        classifiedQueryCount=len(unique)-unclassified, unclassifiedQueryCount=unclassified,
        duplicateRowCount=duplicates, conflictingDuplicateCount=len(conflicts), invalidRowCount=invalid,
        missingMetricsQueryCount=sum(any(v is None for v in m.values()) for m in unique.values()),
        observedGroupCount=len(groups), exportedGroupCount=min(len(groups), MAX_GROUPS),
        inputTruncated=len(rows)>MAX_ROWS, groupsTruncated=len(groups)>MAX_GROUPS,
        observedRowsComplete=len(rows)<=MAX_ROWS and not invalid and not conflicts)
    out['groups'] = groups[:MAX_GROUPS]
    return out
