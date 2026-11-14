"""Pure merchant-title product identity inspection.

URL, ASIN, destination, and account binding deliberately remain the caller's
responsibility.  This module only classifies evidence present in a product
record, its approved model, and a merchant title.
"""
import re


_BRAND_ALIASES = (
    frozenset(('snow peak', 'snowpeak', 'スノーピーク')),
    frozenset(('soto', 'ソト')),
    frozenset(('uniflame', 'ユニフレーム')),
    frozenset(('captain stag', 'キャプテンスタッグ')),
    frozenset(('iwatani', 'イワタニ', '岩谷産業')),
    frozenset(('primus', 'プリムス')),
    frozenset(('jetboil', 'ジェットボイル')),
    frozenset(('coleman', 'コールマン')),
    frozenset(('logos', 'ロゴス')),
    frozenset(('mont-bell', 'montbell', 'モンベル')),
    frozenset(('tokyo camp', 'tokyocamp')),
)

_TYPE_PATTERNS = {
    'burner': r'バーナー|ストーブ|コンロ|burner|stove',
    'tent': r'テント|シェルター|ドーム|tent|shelter',
    'tarp': r'タープ|tarp',
    'chair': r'チェア|椅子|chair',
    'table': r'テーブル|table',
    'lantern': r'ランタン|lantern',
    'sleeping-bag': r'寝袋|シュラフ|sleeping\s*bag',
    'cooler': r'クーラー|cooler',
    'firepit': r'(?:焚き?火台|ファイアグリル|fire\s*pit|fire\s*grill)(?!\s*用)',
}

_BODY_EXCLUSION = re.compile(
    r'本体(?:は|を)?(?:含ま(?:れ)?ません|付属しません|別売|なし)'
    r'|本体(?:なし|別売)'
    r'|(?:body|main\s+unit)\s+(?:is\s+)?(?:not\s+included|sold\s+separately)'
    r'|without\s+(?:the\s+)?(?:body|main\s+unit)',
    re.I,
)

_ACCESSORY_ONLY = re.compile(
    r'本体(?:は|を)?(?:含ま(?:れ)?ません|付属しません|別売|なし)'
    r'|本体(?:なし|別売)'
    r'|専用(?:収納|保護)?(?:ケース|バッグ|カバー|アダプタ|スタンド|シート|マット|ポール|フレーム)'
    r'|(?:グランド|ルーフ|フライ)シート'
    r'|(?:交換|互換)(?:用|品|パーツ)?'
    r'|(?:carrying|storage|protective)\s+(?:case|bag|cover)'
    r'|(?:case|bag|cover|adapter|replacement|footprint)\s+only',
    re.I,
)

_ACCESSORY_NOUN = re.compile(
    r'ケース|バッグ|カバー|アダプタ|焼き網|ロストル|交換パーツ|グランドシート'
    r'|ルーフシート|フライシート|インナーテント|インナーマット|マット|ポール'
    r'|フレーム|ペグ|ロープ|スタンド'
    r'|case|bag|cover|adapter|replacement|footprint',
    re.I,
)


def _result(status, reason):
    return {'status': status, 'reason': reason}


def _compact(value):
    return re.sub(r'[\s\-‐‑–—－_]+', '', value or '').casefold()


def _brand_names(brand):
    normalized = _compact(brand)
    for aliases in _BRAND_ALIASES:
        if normalized in {_compact(alias) for alias in aliases}:
            return aliases
    return frozenset((brand,))


def _brand_in_title(names, title):
    return any(_brand_name_in_title(name, title) for name in names)


_BRAND_SEPARATOR = r'[\s\-‐‑–—－_]*'


def _english_brand_pattern(name):
    parts = re.findall(r'[A-Za-z0-9]+', name)
    return r'(?<![A-Za-z0-9])' + _BRAND_SEPARATOR.join(map(re.escape, parts)) + r'(?![A-Za-z0-9])'


def _japanese_brand_pattern(name):
    normalized = re.sub(r'[\s\-‐‑–—－_]+', '', name)
    return _BRAND_SEPARATOR.join(map(re.escape, normalized))


def _brand_name_in_title(name, title):
    if not name:
        return False
    if not re.search(r'[A-Za-z0-9]', name):
        return _compact(name) in _compact(title)
    return bool(re.search(_english_brand_pattern(name), title, re.I))


def _has_other_known_brand(names, title):
    expected = {_compact(name) for name in names}
    return any(
        _compact(alias) not in expected and _brand_name_in_title(alias, title)
        for aliases in _BRAND_ALIASES
        for alias in aliases
    )


def _model_matches(model, title):
    # Delayed to avoid catalog -> merchant_identity import cycles at call sites.
    try:
        from .catalog import model_matches
    except ImportError:
        from catalog import model_matches
    return model_matches(model, title)


def _model_family(model):
    match = re.match(r'[A-Za-z]+', model or '')
    return match.group(0).casefold() if match else ''


def _conflicting_model_evidence(model, title):
    if _compact(model) and _compact(model) in _compact(title):
        return True
    if model.isdigit():
        return any(len(candidate) == len(model) for candidate in re.findall(r'(?<!\d)\d+(?!\d)', title))
    family = _model_family(model)
    if not family:
        return False
    candidates = re.findall(
        r'(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)*(?![A-Za-z0-9])',
        title,
    )
    return any(_model_family(candidate) == family for candidate in candidates)


def _sizes(text):
    values = set()
    for match in re.finditer(r'(?<![A-Za-z])([SML])(?=\s|$|サイズ|size|型)', text or '', re.I):
        values.add(match.group(1).upper())
    words = {'small': 'S', 'medium': 'M', 'large': 'L'}
    for word, value in words.items():
        if re.search(r'(?<![A-Za-z])' + word + r'(?![A-Za-z])', text or '', re.I):
            values.add(value)
    return values


def _product_type(product):
    category = (product.get('categoryId') or '').casefold()
    if category == 'light' and re.search(r'ストリングライト|string\s*lights?', product.get('name', ''), re.I):
        return 'string-light', r'(?:ストリングライト|string\s*lights?)(?!\s*用)'
    if category in _TYPE_PATTERNS:
        return category, _TYPE_PATTERNS[category]
    name = product.get('name', '')
    for kind, pattern in _TYPE_PATTERNS.items():
        if re.search(pattern, name, re.I):
            return kind, pattern
    return None, None


def _without_identity_tokens(title, brand_names, model):
    value = title
    for name in sorted(brand_names, key=len, reverse=True):
        pattern = _english_brand_pattern(name) if re.search(r'[A-Za-z0-9]', name) else _japanese_brand_pattern(name)
        value = re.sub(pattern, ' ', value, flags=re.I)
    return re.sub(re.escape(model), ' ', value, flags=re.I)


def _is_accessory_only(product_name, title, type_pattern, brand_names, model):
    if _ACCESSORY_ONLY.search(product_name or ''):
        return False
    if _BODY_EXCLUSION.search(title or ''):
        return True
    description = _without_identity_tokens(title or '', brand_names, model)
    explicit_body = bool(re.search(r'本体(?:付き|セット|\+|＋|$|\s)', title or '', re.I))
    if _ACCESSORY_ONLY.search(description) and not explicit_body:
        return True
    accessory = bool(_ACCESSORY_NOUN.search(description))
    # A category word plus "bundle" can still describe accessories only.
    # Generic set wording never substitutes for explicit body evidence.
    return accessory and not explicit_body


def inspect_merchant_identity(product, model, title):
    """Return a conservative identity verdict with a stable safe-code reason."""
    if not isinstance(product, dict):
        return _result('unverified', 'product_identity_missing')
    brand = product.get('brand')
    if not isinstance(brand, str) or not brand.strip():
        return _result('unverified', 'product_brand_missing')
    if not isinstance(model, str) or not model.strip():
        return _result('unverified', 'product_model_missing')
    if not isinstance(title, str) or not title.strip():
        return _result('unverified', 'merchant_title_missing')

    kind, type_pattern = _product_type(product)
    if not kind:
        return _result('unverified', 'product_type_missing')

    if not _model_matches(model, title):
        if _conflicting_model_evidence(model, title):
            return _result('failed', 'merchant_model_mismatch')
        return _result('unverified', 'merchant_model_evidence_missing')

    brand_names = _brand_names(brand)
    if not _brand_in_title(brand_names, title):
        if _has_other_known_brand(brand_names, title):
            return _result('failed', 'merchant_brand_mismatch')
        return _result('unverified', 'merchant_brand_evidence_missing')

    product_sizes = _sizes(product.get('name', ''))
    title_sizes = _sizes(title)
    if len(title_sizes) > 1 and (not product_sizes or product_sizes & title_sizes):
        return _result('unverified', 'merchant_variant_evidence_conflicting')
    if product_sizes and title_sizes and not product_sizes & title_sizes:
        return _result('failed', 'merchant_variant_mismatch')

    if _is_accessory_only(product.get('name', ''), title, type_pattern, brand_names, model):
        return _result('failed', 'merchant_accessory_only')

    if not re.search(type_pattern, title, re.I):
        tent_name = re.search(r'ランド(?:ロック|ネスト(?:シェルター|ドーム)?)', product.get('name', ''))
        if kind != 'tent' or not tent_name or _compact(tent_name.group(0)) not in _compact(title):
            return _result('unverified', 'merchant_product_type_evidence_missing')

    return _result('passed', 'merchant_identity_confirmed')
