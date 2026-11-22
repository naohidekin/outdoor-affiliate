"""Strict, offline apparel identity contracts.

This module never fetches a page and never treats prose, a search result, or a
merchant title as product identity.  A caller supplies the final page URL and
HTML from its existing bounded transport.  Identity comes only from one
JSON-LD Product/ProductModel node bound to the exact page URL.

Generic model guides use ``optionState=selectable``: no fixed colour or size is
invented, but the official/merchant node must explicitly expose non-empty
colour and size options.  A fixed purchasable variant instead requires exact
variant, colour and size values.  Missing evidence is a hold, never a pass.
"""
from html.parser import HTMLParser
from html import unescape
import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit


APPAREL_CLASSES = {
    "outerwear": {"outerwear", "apparel-outerwear", "wear-outerwear", "アウター"},
    "down": {"down", "down-jacket", "apparel-down", "ダウン", "ダウンジャケット"},
    "hardshell": {"hardshell", "hard-shell", "apparel-hardshell", "ハードシェル"},
    "fleece": {"fleece", "apparel-fleece", "フリース"},
    "active-layer": {"active-layer", "active-insulation", "apparel-active-layer",
                     "アクティブレイヤー", "アクティブインサレーション"},
    "heavy-layer": {"heavy-layer", "heavyweight-layer", "apparel-heavy-layer",
                    "ヘビーレイヤー", "ヘビーウェイトレイヤー"},
    "base-layer": {"base-layer", "baselayer", "apparel-base-layer",
                   "ベースレイヤー"},
}
BROAD_APPAREL_CATEGORIES = {"wear", "apparel", "clothing", "ウェア"}

# Configured, bounded primary-domain allowlist.  Additions require a separately
# verified official source; do not infer domains from merchant/search results.
OFFICIAL_DOMAINS = {
    "arc'teryx": ("arcteryx.jp",),
    "arc’teryx": ("arcteryx.jp",),
    "arcteryx": ("arcteryx.jp",),
    "アークテリクス": ("arcteryx.jp",),
    "millet": ("millet.jp",),
    "ミレー": ("millet.jp",),
    "finetrack": ("finetrack.com",),
    "ファイントラック": ("finetrack.com",),
    "columbia": ("columbiasports.co.jp",),
    "コロンビア": ("columbiasports.co.jp",),
    "mont-bell": ("montbell.jp", "montbell.com"),
    "montbell": ("montbell.jp", "montbell.com"),
    "モンベル": ("montbell.jp", "montbell.com"),
    "patagonia": ("patagonia.jp",),
    "パタゴニア": ("patagonia.jp",),
    "the north face": ("goldwin.co.jp",),
    "thenorthface": ("goldwin.co.jp",),
    "ザ・ノース・フェイス": ("goldwin.co.jp",),
    "ザノースフェイス": ("goldwin.co.jp",),
    "nanga": ("nanga.jp",),
    "ナンガ": ("nanga.jp",),
}

MODEL_KEYS = ("model", "modelNumber", "型番", "品番", "モデル番号")
GENDER_KEYS = ("gender", "性別", "対象")
FABRIC_KEYS = ("fabric", "material", "素材", "生地")
WEIGHT_KEYS = ("weight", "重量", "質量")
OPTION_KEYS = ("optionState", "option_state", "選択状態")
VARIANT_KEYS = ("variant", "variantId", "variantSku", "sku", "バリエーション", "SKU")
COLOR_KEYS = ("color", "colour", "カラー", "色")
SIZE_KEYS = ("size", "サイズ")
MERCHANTS = ("amazon", "rakuten", "yahoo")


class ApparelIdentityError(ValueError):
    pass


def _norm(value):
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _value(specs, keys):
    values = [value.strip() for key in keys for value in [specs.get(key)]
              if isinstance(value, str) and value.strip()]
    return values[0] if len(set(values)) == 1 else ""


def apparel_class(product):
    """Return a canonical apparel class, or None for gear/ambiguous input."""
    if not isinstance(product, dict):
        return None
    specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
    category = _norm(product.get("categoryId"))
    explicit = _norm(_value(specs, ("apparelClass", "apparelCategory", "衣類区分")))

    def resolve(value):
        matches = [name for name, aliases in APPAREL_CLASSES.items()
                   if value in {_norm(alias) for alias in aliases}]
        return matches[0] if len(matches) == 1 else None

    category_class, explicit_class = resolve(category), resolve(explicit)
    if category in {_norm(value) for value in BROAD_APPAREL_CATEGORIES}:
        return explicit_class
    if category_class and explicit and explicit_class != category_class:
        return None
    return category_class


def apparel_requested(product):
    """True when input asks for apparel, including malformed classifications."""
    if not isinstance(product, dict):
        return False
    category = _norm(product.get("categoryId"))
    specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
    explicit = _value(specs, ("apparelClass", "apparelCategory", "衣類区分"))
    aliases = {_norm(value) for values in APPAREL_CLASSES.values() for value in values}
    return bool(category in aliases
                or category in {_norm(value) for value in BROAD_APPAREL_CATEGORIES}
                or explicit)


def official_domains(product):
    return OFFICIAL_DOMAINS.get(_norm(product.get("brand")), ()) if isinstance(product, dict) else ()


def apparel_contract(product):
    """Build the immutable catalogue-side contract or raise a bounded hold."""
    kind = apparel_class(product)
    if not kind:
        raise ApparelIdentityError("explicit apparel classification required")
    specs = product.get("specs") or {}
    brand = product.get("brand")
    domains = official_domains(product)
    model = _value(specs, MODEL_KEYS)
    gender = _value(specs, GENDER_KEYS)
    fabric = _value(specs, FABRIC_KEYS)
    weight = _value(specs, WEIGHT_KEYS)
    option_state = _norm(_value(specs, OPTION_KEYS))
    if (not isinstance(brand, str) or not brand.strip() or not domains or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,}", model)
            or not re.search(r"\d", model) or
            not gender or option_state not in ("fixed", "selectable")):
        raise ApparelIdentityError("apparel model/gender/options incomplete")
    contract = {"class": kind, "brand": brand.strip(), "model": model,
                "gender": gender, "optionState": option_state}
    if fabric:
        contract["fabric"] = fabric
    if weight:
        contract["weight"] = weight
    if option_state == "fixed":
        color, size = (_value(specs, keys) for keys in (COLOR_KEYS, SIZE_KEYS))
        if not all((color, size)):
            raise ApparelIdentityError("fixed apparel color/size required")
        contract.update(color=color, size=size,
                        canonicalVariant=model + ":" + color + ":" + size)
    return contract


def is_merchant_field(key):
    return isinstance(key, str) and any(key.startswith(channel) and key[len(channel):] in (
        "OptionState", "Variant", "Color", "Size") for channel in MERCHANTS)


def merchant_contract(product, channel):
    """Return the expected option state for one configured merchant URL."""
    if channel not in MERCHANTS or not isinstance(product, dict):
        raise ApparelIdentityError("unsupported apparel merchant")
    specs = product.get("specs") if isinstance(product.get("specs"), dict) else {}
    state = _norm(specs.get(channel + "OptionState"))
    if state not in ("fixed", "selectable"):
        raise ApparelIdentityError("merchant option state required")
    result = {"merchantChannel": channel, "merchantOptionState": state}
    if state == "fixed":
        values = {name: specs.get(channel + suffix) for name, suffix in (
            ("merchantVariant", "Variant"), ("merchantColor", "Color"),
            ("merchantSize", "Size"))}
        if any(not isinstance(value, str) or not value.strip() for value in values.values()):
            raise ApparelIdentityError("fixed merchant variant/color/size required")
        result.update({key: value.strip() for key, value in values.items()})
    return result


class _JsonLd(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self._capture = False
        self._parts = []
        self.documents = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = {key.casefold(): value for key, value in attrs}
        self._capture = tag.casefold() == "script" and _norm(attrs.get("type")) == "application/ld+json"
        if self._capture:
            self._parts = []

    def handle_data(self, data):
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() == "script" and self._capture:
            try:
                value = json.loads("".join(self._parts))
                self.documents.append(value)
            except (TypeError, ValueError):
                pass
            self._capture = False
            self._parts = []


def _nodes(value):
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _nodes(item)
        yield value
        for key in ("hasVariant", "isVariantOf"):
            child = value.get(key)
            if isinstance(child, (dict, list)):
                yield from _nodes(child)
    elif isinstance(value, list):
        for item in value:
            yield from _nodes(item)


def _types(node):
    value = node.get("@type")
    return {_norm(item) for item in (value if isinstance(value, list) else [value])}


def _scalar(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        amount = value.get("value")
        unit = value.get("unitText") or value.get("unitCode") or ""
        if isinstance(amount, (str, int, float)) and not isinstance(amount, bool):
            return (str(amount) + (" " + str(unit) if unit else "")).strip()
    return ""


def _values(value):
    values = value if isinstance(value, list) else [value]
    return [text for item in values for text in [_scalar(item)] if text]


def _brand(node):
    value = node.get("brand")
    if isinstance(value, dict):
        value = value.get("name")
    return _scalar(value)


_NEW_BRAND_ALIAS_GROUPS = (
    ("finetrack", "ファイントラック"), ("millet", "ミレー"),
    ("arc'teryx", "arc’teryx", "arcteryx", "アークテリクス"),
)
_BRAND_ALIAS_GROUPS = (
    ("mont-bell", "montbell", "モンベル"),
    ("the north face", "thenorthface", "ザ・ノース・フェイス", "ザノースフェイス"),
    ("columbia", "コロンビア"), ("patagonia", "パタゴニア"), ("nanga", "ナンガ"),
) + _NEW_BRAND_ALIAS_GROUPS


def _brand_matches(actual, expected):
    left, right = _norm(actual), _norm(expected)
    return left == right or any(left in {_norm(v) for v in group}
                                and right in {_norm(v) for v in group} for group in _BRAND_ALIAS_GROUPS)


def _field(node, keys):
    values = [_scalar(node.get(key)) for key in keys if key in node]
    values = [value for value in values if value]
    return values[0] if len({_norm(value) for value in values}) == 1 else ""


def _canonical_page(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            return ""
        path = parsed.path or "/"
        return urlunsplit(("https", parsed.netloc.casefold(), path.rstrip("/") or "/", parsed.query, ""))
    except (TypeError, ValueError):
        return ""


def _urls(value, page_url):
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("url") or item.get("contentUrl")
        if isinstance(item, str) and item.strip():
            result.append(urljoin(page_url, item.strip()))
    return result


def inspect_apparel_page(product, page_url, html, image_url=None, source_role="manufacturer",
                         channel=None):
    """Return exact JSON-compatible evidence, or None without a complete match."""
    if source_role not in ("manufacturer", "purchase"):
        return None
    try:
        contract = apparel_contract(product)
    except ApparelIdentityError:
        return None
    target_url = _canonical_page(page_url)
    if not target_url or not isinstance(html, str):
        return None
    if source_role == "purchase":
        return _inspect_merchant(product, page_url, html, channel)
    if (contract['model'] == '40275'
            and _norm(contract['brand']) in ('patagonia', 'パタゴニア')):
        from official_patagonia_apparel import inspect_official_patagonia
        return inspect_official_patagonia(product, page_url, html, image_url)
    if contract['model'] == 'NA62650':
        from goldwin_na62650 import inspect_goldwin_na62650
        return inspect_goldwin_na62650(product, page_url, html, image_url)
    if contract['model'].upper() in ('MIV01248', 'X000010878', 'X000010854'):
        from official_shopify_apparel import inspect_official_shopify
        return inspect_official_shopify(product, page_url, html, image_url)
    if (_norm(contract['brand']) in ('finetrack', 'ファイントラック')
            and contract['model'] == 'FUM0422'):
        return _inspect_finetrack(product, page_url, html, image_url)
    product_nodes = [node for document in _JsonLd(html).documents for node in _nodes(document)
                     if isinstance(node, dict) and _types(node) & {"product", "productmodel"}]
    matches = []
    for root in product_nodes:
        node_url = _canonical_page(_scalar(root.get("url")))
        if node_url != target_url or not _brand_matches(_brand(root), contract["brand"]):
            continue
        model = _field(root, ("model", "mpn", "productID"))
        if _norm(model) != _norm(contract["model"]):
            continue
        gender = _field(root, ("gender", "suggestedGender"))
        audience = root.get("audience")
        if not gender and isinstance(audience, dict):
            gender = _field(audience, ("suggestedGender", "gender"))
        fabric = _field(root, ("material", "fabric"))
        weight = _field(root, ("weight",))
        if _norm(gender) != _norm(contract["gender"]):
            continue
        if source_role == "manufacturer" and any(
                _norm({"fabric": fabric, "weight": weight}.get(key)) != _norm(contract[key])
                for key in ("fabric", "weight") if key in contract):
            continue
        # Merchant weight is often package- or selected-variant weight.  It is
        # never used to prove the maker's average-garment claim.  Explicit
        # material is still a contradiction when it disagrees.
        if source_role == "purchase" and fabric and "fabric" in contract and _norm(fabric) != _norm(contract["fabric"]):
            continue

        variants = [node for value in [root.get("hasVariant", [])] for node in _nodes(value)
                    if isinstance(node, dict) and _types(node) & {"product", "productmodel"}]
        selected = root
        if contract["optionState"] == "fixed":
            exact = [node for node in variants + [root]
                     if _norm(_field(node, ("color", "colour"))) == _norm(contract["color"])
                     and _norm(_field(node, ("size",))) == _norm(contract["size"])]
            if len(exact) != 1:
                continue
            selected = exact[0]
            colors, sizes = [contract["color"]], [contract["size"]]
        else:
            option_nodes = variants or [root]
            colors = sorted({_norm(value): value for node in option_nodes
                             for value in _values(node.get("color") or node.get("colour"))}.values(),
                            key=_norm)
            sizes = sorted({_norm(value): value for node in option_nodes
                            for value in _values(node.get("size"))}.values(), key=_norm)
            if not colors or not sizes:
                continue

        images = list(dict.fromkeys(_urls(selected.get("image"), page_url)))
        if selected is not root and not images:
            continue
        if contract["optionState"] == "selectable":
            images = list(dict.fromkeys(images + _urls(root.get("image"), page_url)))
        if image_url is not None and image_url not in images:
            continue
        binding = dict(contract, colors=colors, sizes=sizes, imageUrls=images,
                       sourceUrl=page_url, sourceKind="json-ld-product")
        source_variant = _field(selected, ("sku", "mpn", "productID"))
        if source_variant:
            binding["sourceVariant"] = source_variant
        matches.append(binding)
    if len(matches) == 1:
        return matches[0]
    return _inspect_montbell(product, page_url, html, image_url) if source_role == "manufacturer" else None


_FINETRACK_PAGE = ('https://www.finetrack.com/c/wear-drylayer/'
                   'wear-drylayer-basic/wear-drylayer-basic-men/FUM0422')
_FINETRACK_WEARING_IMAGE = ('https://finetrack.itembox.cloud/product/005/000000000524/'
                          '000000000524-11.jpg?size=l&w=NTUw&t=20240321151606')
# Observed on the exact page, not computed from SKU/title or a merchant listing.
_FINETRACK_GTINS = {
    '524h1v1': '4573406384235', '524h2v1': '4573406384242',
    '524h3v1': '4573406384259', '524h4v1': '4573406384266',
    '524h5v1': '4573406384273', '524h1v2': '4573406384280',
    '524h2v2': '4573406384297', '524h3v2': '4573406384303',
    '524h4v2': '4573406384310', '524h5v2': None,
}


class _FinetrackDOM(HTMLParser):
    """Small page tree; facts are read only from explicit primary containers."""
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or '' for key, value in attrs}
        parent = self.stack[-1] if self.stack else None
        hidden = (bool(parent and parent['hidden']) or tag in
                  ('script', 'style', 'template', 'nav', 'aside', 'footer')
                  or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)',
                                    attrs.get('style', ''), re.I)))
        node = dict(tag=tag, attrs=attrs, parent=parent, children=[], text=[],
                    hidden=hidden, closed=tag in self._VOID)
        self.nodes.append(node)
        if parent is not None:
            parent['children'].append(node)
        if tag not in self._VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i]['tag'] == tag), None)
        if index is not None:
            self.stack[index]['closed'] = True
            del self.stack[index:]

    def handle_data(self, data):
        for node in self.stack:
            if not node['hidden']:
                node['text'].append(data if not self.stack[-1]['hidden'] else '')


def _ft_class(node, name):
    return name in (node['attrs'].get('class') or '').split()


def _ft_inside(node, parent):
    current = node['parent']
    while current is not None:
        if current is parent:
            return True
        current = current['parent']
    return False


def _ft_text(node):
    return ' '.join(''.join(node['text']).split())


def _ft_image(value):
    """Decode entities and query ordering only; no guessed CDN transformations."""
    if not isinstance(value, str) or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return None
    decoded = unescape(value)
    if re.search(r'[\s\\\x00-\x1f\x7f]', decoded):
        return None
    parsed = urlsplit(decoded)
    if (parsed.scheme != 'https' or parsed.netloc != 'finetrack.itembox.cloud'
            or parsed.fragment or not re.fullmatch(
                r'/product/005/000000000524/000000000524-\d{2}\.jpg', parsed.path)):
        return None
    return parsed.path, tuple(sorted(parsed.query.split('&')))


def _ft_gallery_visible(node, layout):
    while node is not layout:
        attrs = node['attrs']
        if ('hidden' in attrs or node['tag'] in ('nav', 'aside', 'template')
                or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attrs.get('style', ''), re.I)
                or (attrs.get('aria-hidden') == 'true'
                    and not _ft_class(node, 'fs-c-productCarouselMainImage__image'))):
            return False
        node = node['parent']
    return True


def _inspect_finetrack(product, page_url, html, image_url):
    """FUM0422 only: primary DOM facts plus same-page ProductGroup children."""
    try:
        contract = apparel_contract(product)
        if (page_url != _FINETRACK_PAGE or contract['model'] != 'FUM0422'
                or contract['class'] != 'base-layer'
                or _norm(contract['brand']) not in ('finetrack', 'ファイントラック')):
            return None
        page = _FinetrackDOM(html)
        canonicals = [n['attrs'].get('href') for n in page.nodes
                      if n['tag'] == 'link' and n['attrs'].get('rel') == 'canonical']
        bodies = [n for n in page.nodes if n['tag'] == 'body']
        layouts = [n for n in page.nodes if _ft_class(n, 'fs-l-productLayout')]
        outlines = [n for n in page.nodes if _ft_class(n, 'pro-detailOutline')]
        forms = [n for n in page.nodes if n['attrs'].get('id') == 'fs_form']
        if (canonicals != [_FINETRACK_PAGE] or len(bodies) != 1 or len(layouts) != 1
                or len(outlines) != 1 or len(forms) != 1):
            return None
        body, layout, outline, form = bodies[0], layouts[0], outlines[0], forms[0]
        if (body['attrs'].get('id') != 'fs_ProductDetails'
                or not _ft_class(body, 'fs-body-product-FUM0422')
                or any(n['hidden'] or not n['closed'] for n in (layout, outline, form))
                or not _ft_inside(layout, form) or not _ft_inside(form, body)
                or not _ft_inside(outline, body) or _ft_inside(outline, layout)
                or layout['attrs'].get('data-product-id') != '524'):
            return None

        def texts(container, cls):
            return [_ft_text(n) for n in page.nodes if _ft_inside(n, container)
                    and _ft_class(n, cls) and not n['hidden'] and n['closed']]

        if (texts(layout, 'fs-c-productNumber__number') != ['FUM0422']
                or texts(layout, 'c-label--mens') != ["MEN'S"]
                or _norm(contract['gender']) != _norm("Men's")
                or texts(outline, 'pro-detailHeading') != ['商品詳細']):
            return None
        titles = texts(layout, 'fs-c-productNameHeading__name')
        if len(titles) != 1 or not titles[0]:
            return None
        facts = {}
        summaries = [n for n in outline['children'] if n['tag'] == 'div']
        if not summaries or summaries[0]['hidden'] or not summaries[0]['closed']:
            return None
        for n in page.nodes:
            if not _ft_inside(n, summaries[0]) or n['hidden'] or n['tag'] != 'div':
                continue
            children = n['children']
            if len(children) == 2 and _ft_text(children[0]) in ('素材', '重量'):
                label, value = map(_ft_text, children)
                if label in facts or any(c['hidden'] or not c['closed'] for c in children):
                    return None
                facts[label] = value
        if facts != {'素材': 'ポリエステル100%', '重量': '46g'}:
            return None
        if any(_norm(contract[k]) != _norm(facts[label]) for k, label in
               (('fabric', '素材'), ('weight', '重量')) if k in contract):
            return None
        roots = [n for d in _JsonLd(html).documents for n in _nodes(d)
                 if isinstance(n, dict) and 'productgroup' in _types(n)]
        if len(roots) != 1:
            return None
        root = roots[0]
        if (root.get('@id') != page_url or root.get('url') != page_url
                or root.get('productGroupID') != '524' or root.get('name') != titles[0]
                or _brand(root) != 'finetrack'):
            return None
        if any(any(k in root for k in keys) and _norm(_field(root, keys)) != _norm(expected)
                   for keys, expected in ((('model', 'mpn'), 'FUM0422'),
                       (('gender', 'suggestedGender'), "Men's"),
                       (('material', 'fabric'), facts['素材']), (('weight',), facts['重量']))):
            return None
        variants = root.get('hasVariant')
        if not isinstance(variants, list) or not variants or len(variants) > 20:
            return None
        galleries = [n for n in page.nodes if n['attrs'].get('id') == 'fs_productCarouselMainImage']
        if (len(galleries) != 1 or not _ft_inside(galleries[0], layout)
                or galleries[0]['hidden'] or not galleries[0]['closed']):
            return None
        gallery = [n for n in page.nodes if n['tag'] == 'img' and _ft_inside(n, galleries[0])
                   and _ft_gallery_visible(n, layout)]
        rows, seen_skus, seen_gtins, seen_ids, seen_options = [], set(), set(), set(), set()
        for child in variants:
            if not isinstance(child, dict) or _types(child) != {'product'}:
                return None
            sku, gtin, ident = (child.get(k) for k in ('sku', 'gtin13', '@id'))
            color, size = (_field(child, (k,)) for k in ('color', 'size'))
            prefix = {'S': 'S', 'M': 'M', 'L': 'L', 'XL': 'XL', 'XXL': 'XX'}.get(size)
            fragment = ident[len(page_url) + 1:] if isinstance(ident, str) and ident.startswith(page_url + '#') else ''
            code = fragment[len(prefix):] if prefix and fragment.startswith(prefix) else ''
            if (not isinstance(sku, str) or not re.fullmatch(r'524h[1-5]v[12]', sku)
                    or child.get('productID') != sku
                    or gtin != _FINETRACK_GTINS.get(sku)
                    or ('gtin13' in child and (not isinstance(gtin, str)
                        or not re.fullmatch(r'\d{13}', gtin) or
                        sum(int(v) * (1 if i % 2 == 0 else 3) for i, v in enumerate(gtin)) % 10))
                    or not color or code not in ('BK', 'PA')
                    or color != {'BK': 'ブラック', 'PA': 'ペイルグレー'}[code]
                    or sku in seen_skus or (gtin is not None and gtin in seen_gtins) or ident in seen_ids
                    or (color, size) in seen_options or child.get('hasVariant') or child.get('isVariantOf')):
                return None
            if (sku != '524h' + str(('S', 'M', 'L', 'XL', 'XXL').index(size) + 1)
                    + 'v' + {'BK': '1', 'PA': '2'}[code]
                    or child.get('name') != titles[0] + ' ' + size + ' ' + color):
                return None
            if ('url' in child and child['url'] != page_url) or ('brand' in child and _brand(child) != 'finetrack'):
                return None
            for keys, expected in ((('model', 'mpn'), 'FUM0422'),
                                   (('gender', 'suggestedGender'), "Men's"),
                                   (('material', 'fabric'), facts['素材']), (('weight',), facts['重量'])):
                if any(k in child for k in keys) and _norm(_field(child, keys)) != _norm(expected):
                    return None
            child_image = _ft_image(child.get('image'))
            if not child_image or child_image[0] == urlsplit(_FINETRACK_WEARING_IMAGE).path:
                return None
            images = [unescape(child['image'])]
            images += [n['attrs']['src'] for n in gallery
                       if n['attrs'].get('alt') == 'FUM0422-' + code
                       and _ft_image(n['attrs'].get('src'))
                       and _ft_image(n['attrs']['src'])[0] == child_image[0]]
            if len(images) < 2:
                return None
            row = dict(sku=sku, color=color, size=size, imageUrls=images)
            if gtin is not None:
                row['gtin13'] = gtin
            else:
                row['missingFields'] = ['gtin13']
            rows.append(row)
            seen_skus.add(sku)
            seen_gtins.add(gtin)
            seen_ids.add(ident)
            seen_options.add((color, size))
        if contract['optionState'] == 'fixed':
            rows = [r for r in rows if _norm(r['color']) == _norm(contract['color'])
                    and _norm(r['size']) == _norm(contract['size'])]
            if len(rows) != 1:
                return None
        images = list(dict.fromkeys(v for r in rows for v in r['imageUrls']))
        wearing_example = False
        if image_url is not None:
            if image_url == _FINETRACK_WEARING_IMAGE:
                if (contract['optionState'] != 'selectable'
                        or sum(n['attrs'].get('src') == _FINETRACK_WEARING_IMAGE for n in gallery) != 1):
                    return None
                wearing_example = True
            else:
                image_key = _ft_image(image_url)
                if image_key is None or not any(_ft_image(v) == image_key for v in images):
                    return None
            images.append(image_url)  # Retain only after source membership is proved.
        result = dict(contract, fabric=facts['素材'], weight=facts['重量'],
                      colors=sorted({r['color'] for r in rows}), sizes=sorted({r['size'] for r in rows}),
                      imageUrls=list(dict.fromkeys(images)), manufacturerVariants=rows,
                      sourceUrl=page_url, sourceKind='finetrack-primary-productgroup-dom')
        if wearing_example:
            # Product-level wearing example; not evidence of a selected colour/size.
            result.update(imageScope='primary-product-wearing-example', imageScopeUrl=image_url)
        if contract['optionState'] == 'fixed':
            result['sourceVariant'] = rows[0]['sku']
        excerpt = '商品番号 FUM0422\n' + titles[0] + " MEN'S\n重量 " + facts['重量'] + '\n素材 ' + facts['素材']
        result['manufacturerExcerpt'] = dict(text=excerpt, sourceUrl=page_url, model='FUM0422',
            excerptSHA256=hashlib.sha256(excerpt.encode('utf-8')).hexdigest(),
            scope='primary product number/name/mark and 商品詳細 weight/material rows',
            conditions=['Public primary manufacturer facts, not personal experience.'])
        return result
    except (ApparelIdentityError, TypeError, ValueError, KeyError):
        return None


class _MontbellProduct(HTMLParser):
    """Extract only Mont-bell's primary product DOM, excluding related cards."""
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title_parts = []
        self.main_text = []
        self.spec_parts = []
        self.sizes = []
        self.images = []
        self.product_ids = []
        self.color_sets = []
        self._title_depth = None
        self._main_depth = None
        self._select_depth = None
        self._spec_heading_depth = None
        self._spec_pending = False
        self._spec_depth = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        depth = len(self.stack) + 1
        if tag not in self._VOID:
            self.stack.append((tag, attrs))
        classes = set(attrs.get("class", "").split())
        if tag == "h2" and "ttlType01" in classes:
            self._title_depth = depth
        if tag == "div" and attrs.get("id") == "maindataCont":
            self._main_depth = depth
        in_main = self._main_depth is not None and depth > self._main_depth
        if in_main and tag == "select" and attrs.get("name") == "sel_size":
            self._select_depth = depth
        if in_main and tag == "option" and self._select_depth:
            value = attrs.get("value", "").strip()
            if value:
                self.sizes.append(value)
        if in_main and tag == "input":
            if attrs.get("name") == "product_id":
                self.product_ids.append(attrs.get("value", "").strip())
            if attrs.get("name") == "all_color":
                self.color_sets.append([v for v in attrs.get("value", "").split(",") if v])
        if in_main and tag in ("a", "img"):
            value = attrs.get("href") if tag == "a" else attrs.get("src")
            if value and "/common/images/product/prod_" in value:
                self.images.append(value)
        if tag == "h4" and "ttlType03" in classes:
            self._spec_heading_depth = depth
        elif tag == "p" and self._spec_pending:
            self._spec_depth = depth
            self._spec_pending = False
        if tag == "br" and self._spec_depth:
            self.spec_parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        depth = len(self.stack)
        if self._title_depth and depth >= self._title_depth:
            self.title_parts.append(data)
        if self._main_depth and depth > self._main_depth:
            self.main_text.append(data)
        if self._spec_heading_depth and depth >= self._spec_heading_depth and "仕様" in data:
            self._spec_pending = True
        if self._spec_depth and depth >= self._spec_depth:
            self.spec_parts.append(data)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is None:
            return
        closed_depth = index + 1
        for field in ('_title_depth', '_select_depth', '_spec_heading_depth',
                      '_spec_depth', '_main_depth'):
            active_depth = getattr(self, field)
            if active_depth is not None and active_depth >= closed_depth:
                setattr(self, field, None)
        del self.stack[index:]


class _AmazonPrimaryFacts(HTMLParser):
    """Extract facts only from Amazon's primary detail table ancestry."""
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _ANCESTORS = {'dp', 'dp-container', 'voyagerNorthstarBTF',
                  'voyagerNorthstarATFData_feature_div'}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.colors = []
        self._table_depth = None
        self._row_depth = None
        self._label_depth = None
        self._value_depth = None
        self._label_parts = []
        self._value_parts = []
        self.feed(source)

    @staticmethod
    def _classes(attrs):
        return set(str(attrs.get('class', '')).split())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        path = self.stack + [(tag, attrs)]
        depth = len(path)
        if tag == 'table':
            ids = {item.get('id') for _, item in path}
            classes = self._classes(attrs)
            if (self._ANCESTORS <= ids
                    and {'a-keyvalue', 'voyager-ns-desktop-table'} <= classes):
                self._table_depth = depth
        elif tag == 'tr' and self._table_depth:
            self._row_depth = depth
            self._label_parts, self._value_parts = [], []
        elif tag == 'th' and self._row_depth and 'voyager-ns-desktop-table-label' in self._classes(attrs):
            self._label_depth = depth
        elif tag == 'td' and self._row_depth and 'voyager-ns-desktop-table-value' in self._classes(attrs):
            self._value_depth = depth
        if tag not in self._VOID:
            self.stack.append((tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self._label_depth:
            self._label_parts.append(data)
        if self._value_depth:
            self._value_parts.append(data)

    def handle_endtag(self, tag):
        depth = len(self.stack)
        if tag == 'th' and self._label_depth == depth:
            self._label_depth = None
        if tag == 'td' and self._value_depth == depth:
            self._value_depth = None
        if tag == 'tr' and self._row_depth == depth:
            label = ' '.join(' '.join(self._label_parts).split())
            value = ' '.join(' '.join(self._value_parts).split())
            if _norm(label) == _norm('カラー'):
                self.colors.append(value)
            self._row_depth = None
            self._label_depth = None
            self._value_depth = None
            self._label_parts, self._value_parts = [], []
        if tag == 'table' and self._table_depth == depth:
            self._table_depth = None
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is not None:
            del self.stack[index:]


class _RakutenPrimaryMetadata(HTMLParser):
    """Keep each Rakuten Product scope intact and collect one page-level OG image."""
    _VOID = _AmazonPrimaryFacts._VOID

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.active = []
        self.products = []
        self.og_images = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        depth = len(self.stack) + 1
        if ("itemscope" in attrs
                and _norm(attrs.get("itemtype")).endswith("schema.org/product")):
            self.active.append((depth, {"names": [], "skus": [], "images": []}))
        if tag == "meta":
            prop, content = _norm(attrs.get("itemprop")), attrs.get("content")
            if self.active and prop in ("name", "sku", "image") and content:
                self.active[-1][1][{"name": "names", "sku": "skus",
                                    "image": "images"}[prop]].append(content.strip())
            og = _norm(attrs.get("property") or attrs.get("name"))
            if og == "og:image" and isinstance(content, str) and content.strip():
                self.og_images.append(content.strip())
        if tag not in self._VOID:
            self.stack.append((tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        depth = len(self.stack)
        while self.active and self.active[-1][0] == depth:
            _, product = self.active.pop()
            self.products.append(product)
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is not None:
            del self.stack[index:]


class _MerchantProduct(HTMLParser):
    """Primary Amazon/Rakuten product projection; ignores recommendations."""
    def __init__(self, source, *, amazon=False):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title_parts = []
        self.product_title_parts = []
        self.canonicals = []
        self.primary_images = []
        self.item_names = []
        self.item_skus = []
        self.item_images = []
        self.hidden_asins = []
        self.options = {}
        self.twister_states = []
        self.primary_color_facts = _AmazonPrimaryFacts(source).colors if amazon else []
        self._title_depth = None
        self._product_title_depth = None
        self._select_depth = None
        self._select_name = None
        self._state_depth = None
        self._state_parts = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append((tag, attrs))
        depth = len(self.stack)
        if tag == "title":
            self._title_depth = depth
        if attrs.get("id") == "productTitle":
            self._product_title_depth = depth
        if tag == "link" and _norm(attrs.get("rel")) == "canonical" and attrs.get("href"):
            self.canonicals.append(attrs["href"])
        if tag == "img" and attrs.get("id") == "landingImage":
            url = attrs.get("data-old-hires") or attrs.get("src")
            if url:
                self.primary_images.append({"url": url, "alt": attrs.get("alt", "")})
        nearest_scope = next((scope for _, scope in reversed(self.stack)
                              if "itemscope" in scope), {})
        product_scope = _norm(nearest_scope.get("itemtype")).endswith("schema.org/product")
        if tag == "meta" and product_scope:
            prop, content = _norm(attrs.get("itemprop")), attrs.get("content")
            if prop == "name" and content:
                self.item_names.append(content)
            elif prop == "sku" and content:
                self.item_skus.append(content)
            elif prop == "image" and content:
                self.item_images.append(content)
        if (tag == "input" and attrs.get("name") == "ASIN"
                and isinstance(attrs.get("value"), str) and attrs["value"].strip()):
            self.hidden_asins.append(attrs["value"].strip())
        if tag == "select" and attrs.get("name"):
            self._select_depth, self._select_name = depth, _norm(attrs["name"])
        if tag == "option" and self._select_depth:
            value = attrs.get("value", "").strip()
            if value:
                self.options.setdefault(self._select_name, []).append(value)
        if tag == "script" and _norm(attrs.get("type")) == "a-state":
            try:
                descriptor = json.loads(attrs.get("data-a-state", "{}"))
            except (TypeError, ValueError):
                descriptor = {}
            if descriptor.get("key") == "desktop-twister-sort-filter-data":
                self._state_depth = depth
                self._state_parts = []

    def handle_data(self, data):
        depth = len(self.stack)
        if self._title_depth and depth >= self._title_depth:
            self.title_parts.append(data)
        if self._product_title_depth and depth >= self._product_title_depth:
            self.product_title_parts.append(data)
        if self._state_depth and depth >= self._state_depth:
            self._state_parts.append(data)

    def handle_endtag(self, tag):
        depth = len(self.stack)
        if self._title_depth == depth and tag == "title":
            self._title_depth = None
        if self._product_title_depth == depth:
            self._product_title_depth = None
        if self._select_depth == depth and tag == "select":
            self._select_depth, self._select_name = None, None
        if self._state_depth == depth and tag == "script":
            try:
                value = json.loads("".join(self._state_parts))
                if isinstance(value, dict):
                    self.twister_states.append(value)
            except (TypeError, ValueError):
                pass
            self._state_depth, self._state_parts = None, []
        if self.stack:
            self.stack.pop()


def _exact_token(text, value):
    if not isinstance(text, str) or not isinstance(value, str) or not value.strip():
        return False
    normalized, token = unicodedata.normalize("NFKC", text), unicodedata.normalize("NFKC", value.strip())
    if re.fullmatch(r"[A-Za-z0-9._/-]+", token):
        return bool(re.search(r"(?<![A-Za-z0-9._/-])" + re.escape(token)
                              + r"(?![A-Za-z0-9._/-])", normalized, re.I))
    return token.casefold() in normalized.casefold()


def _gender_matches(text, expected):
    groups = {
        "men": {"men's", "mens", "men", "メンズ", "男性用"},
        "women": {"women's", "womens", "women", "レディース", "女性用"},
        "unisex": {"unisex", "ユニセックス"},
    }
    wanted = next((name for name, values in groups.items()
                   if _norm(expected) in {_norm(value) for value in values}), None)
    normalized = unicodedata.normalize("NFKC", text) if isinstance(text, str) else ""
    detected = set()
    if (re.search(r"(?<![A-Za-z])men(?:'s|s)?(?![A-Za-z])", normalized, re.I)
            or "メンズ" in normalized or "男性用" in normalized):
        detected.add("men")
    if (re.search(r"(?<![A-Za-z])women(?:'s|s)?(?![A-Za-z])", normalized, re.I)
            or "レディース" in normalized or "女性用" in normalized):
        detected.add("women")
    if (re.search(r"(?<![A-Za-z])unisex(?![A-Za-z])", normalized, re.I)
            or "ユニセックス" in normalized):
        detected.add("unisex")
    return wanted is not None and detected == {wanted}


def _amazon_primary_model_matches(text, contract):
    """One observed label separator; never a general slash/model boundary."""
    if _exact_token(text, contract['model']):
        return True
    if (contract['model'] != 'FUM0422'
            or _norm(contract['brand']) not in ('finetrack', 'ファイントラック')
            or _norm(contract['gender']) != _norm("Men's")
            or not isinstance(text, str)):
        return False
    normalized = unicodedata.normalize('NFKC', text)
    return bool(re.search(r'\(メンズ\)/FUM0422(?![A-Za-z0-9._/-])', normalized, re.I))


def _inspect_merchant(product, page_url, html, channel):
    try:
        contract = apparel_contract(product)
        merchant = merchant_contract(product, channel)
        page = _MerchantProduct(html, amazon=channel == "amazon")
        canonical = page.canonicals[0] if len(page.canonicals) == 1 else ""
        parsed = urlsplit(page_url)
        if channel == "amazon":
            asin = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)", parsed.path)
            canonical_url = urlsplit(canonical)
            canonical_asin = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)",
                                       canonical_url.path)
            title = " ".join(" ".join(page.product_title_parts).split())
            selected_asins = set(page.hidden_asins)
            if (parsed.hostname not in ("amazon.co.jp", "www.amazon.co.jp") or not asin
                    or canonical_url.hostname not in ("amazon.co.jp", "www.amazon.co.jp")
                    or not canonical_asin
                    or len(page.primary_images) != 1 or not title
                    or selected_asins != {asin.group(1)}
                    or not _brand_matches_in_text(title, contract["brand"])
                    or not _amazon_primary_model_matches(title, contract)
                    or not _gender_matches(title, contract["gender"])):
                return None
            image = page.primary_images[0]
            if not _amazon_primary_model_matches(image.get("alt", ""), contract):
                return None
            if merchant["merchantOptionState"] == "fixed":
                dimensions = _amazon_selected_dimensions(page.twister_states, asin.group(1))
                if dimensions is None:
                    dimensions = _amazon_size_with_primary_color(
                        page.twister_states, asin.group(1), page.primary_color_facts,
                        merchant["merchantColor"])
                if asin.group(1) != merchant["merchantVariant"]:
                    return None
                if dimensions is None:
                    # Some fixed, non-twister Amazon listings expose no
                    # variation state.  The selected hidden ASIN, exact
                    # product-title variant and primary image remain scoped
                    # to the one requested product; title alone is never used.
                    if (page.twister_states
                            or not _exact_token(title, merchant["merchantColor"])
                            or not _exact_token(title, merchant["merchantSize"])):
                        return None
                elif (not _exact_token(dimensions["color"], merchant["merchantColor"])
                      or not _exact_token(dimensions["size"], merchant["merchantSize"])):
                    return None
                colors, sizes = [merchant["merchantColor"]], [merchant["merchantSize"]]
            else:
                # Amazon's ordinary selects are not reliably scoped to the
                # primary product and may come from recommendation cards.
                # Until a selected-child-bound option projection is present,
                # a selectable Amazon destination is an explicit hold.
                return None
            source_kind, images = "amazon-primary-product-dom", [image["url"]]
        elif channel == "rakuten":
            if (_rakuten_product_page(canonical) != _rakuten_product_page(page_url)
                    or parsed.hostname != "item.rakuten.co.jp"
                    or len(page.item_names) != 1 or len(page.item_skus) != 1
                    or not page.item_images):
                return None
            title, sku = page.item_names[0], page.item_skus[0]
            variant_options = _rakuten_variant_options(html)
            if (not _brand_matches_in_text(title, contract["brand"])
                    or not _gender_matches(title, contract["gender"])
                    or not (_exact_token(title, contract["model"])
                            or contract["model"].casefold() in sku.casefold())):
                return None
            if merchant["merchantOptionState"] == "fixed":
                if (variant_options is not None
                        or merchant["merchantVariant"].casefold() != sku.casefold()
                        or not _exact_token(title, merchant["merchantColor"])
                        or not _exact_token(title, merchant["merchantSize"])):
                    return None
                colors, sizes = [merchant["merchantColor"]], [merchant["merchantSize"]]
            else:
                colors = variant_options["colors"] if variant_options else []
                sizes = variant_options["sizes"] if variant_options else []
                if not colors or not sizes:
                    return None
            tokens = (_norm(contract["model"]), _norm(merchant.get("merchantVariant")),
                      _norm(sku.rsplit(":", 1)[-1]))
            images = list(dict.fromkeys(value for value in page.item_images
                                        if any(token and token in _norm(value)
                                               for token in tokens)))
            if not images:
                metadata = _RakutenPrimaryMetadata(html)
                page_parts = [part for part in urlsplit(canonical).path.split("/") if part]
                if len(page_parts) != 2:
                    return None
                source_sku = page_parts[0] + ":" + page_parts[1]
                nodes = [node for node in metadata.products
                         if list(dict.fromkeys(node["skus"])) == [source_sku]]
                if (len(nodes) != 1
                        or list(dict.fromkeys(nodes[0]["names"])) != [title]):
                    return None
                og_images = list(dict.fromkeys(metadata.og_images))
                og_assets = [_rakuten_shop_image(value, page_parts[0])
                             for value in og_images]
                if len(og_assets) != 1 or og_assets[0] is None:
                    return None
                node_images = list(dict.fromkeys(nodes[0]["images"]))
                matched = [value for value in node_images
                           if _rakuten_shop_image(value, page_parts[0]) == og_assets[0]]
                if len(matched) != 1:
                    return None
                # Product metadata proves membership; the declared OG URL is
                # the exact no-redirect fetch target retained in the proof.
                images = [og_images[0]]
                image_identity = {"imageIdentityMode": "rakuten-primary-og-raster-v1",
                                  "merchantSourceSku": source_sku}
            else:
                image_identity = {}
            source_kind = "rakuten-primary-product-dom"
        else:
            return None
        return dict(contract, **merchant, colors=colors, sizes=sizes,
                    imageUrls=images, sourceUrl=page_url, sourceKind=source_kind,
                    **(image_identity if channel == "rakuten" else {}))
    except (ApparelIdentityError, TypeError, ValueError):
        return None


def _brand_matches_in_text(text, expected):
    wanted = _norm(expected)
    aliases = next((group for group in _BRAND_ALIAS_GROUPS if wanted in {_norm(v) for v in group}), (expected,))
    if aliases in _NEW_BRAND_ALIAS_GROUPS:
        return any(re.search(r"(?<![\w.'’/-])" + re.escape(_norm(alias))
                             + r"(?![\w.'’/-])", _norm(text)) for alias in aliases)
    return any(_exact_token(text, alias) for alias in aliases)


def _amazon_selected_dimensions(states, asin):
    if not isinstance(states, list) or len(states) != 1:
        return None
    dimensions = states[0].get("sortedDimValuesForAllDims")
    if not isinstance(dimensions, dict):
        return None
    result = {}
    for source, target in (("color_name", "color"), ("size_name", "size")):
        values = dimensions.get(source)
        selected = [item for item in values or [] if isinstance(item, dict)
                    and item.get("dimensionValueState") == "SELECTED"]
        if (len(selected) != 1 or selected[0].get("defaultAsin") != asin
                or not isinstance(selected[0].get("dimensionValueDisplayText"), str)
                or not selected[0]["dimensionValueDisplayText"].strip()):
            return None
        result[target] = selected[0]["dimensionValueDisplayText"].strip()
    return result


def _amazon_size_with_primary_color(states, asin, primary_colors, expected_color):
    """Bind a size-only child ASIN to one independent primary-table color."""
    if not isinstance(states, list) or len(states) != 1:
        return None
    dimensions = states[0].get("sortedDimValuesForAllDims")
    if not isinstance(dimensions, dict) or set(dimensions) != {"size_name"}:
        return None
    values = dimensions["size_name"]
    if not isinstance(values, list):
        return None
    selected = [item for item in values if isinstance(item, dict)
                and item.get("dimensionValueState") == "SELECTED"]
    if (len(selected) != 1 or selected[0].get("defaultAsin") != asin
            or not isinstance(selected[0].get("dimensionValueDisplayText"), str)
            or not selected[0]["dimensionValueDisplayText"].strip()
            or not isinstance(primary_colors, list) or len(primary_colors) != 1
            or not isinstance(primary_colors[0], str) or not primary_colors[0].strip()
            or _norm(primary_colors[0]) != _norm(expected_color)):
        return None
    return {"color": primary_colors[0].strip(),
            "size": selected[0]["dimensionValueDisplayText"].strip()}


def _rakuten_variant_options(html):
    """Read only Rakuten's primary itemInfoSku variant selector projection."""
    marker = '"itemInfoSku":'
    decoder = json.JSONDecoder()
    values = []
    start = 0
    while True:
        index = html.find(marker, start)
        if index < 0:
            break
        try:
            value, _ = decoder.raw_decode(html[index + len(marker):].lstrip())
        except (TypeError, ValueError):
            start = index + len(marker)
            continue
        if isinstance(value, dict):
            values.append(value)
        start = index + len(marker)
    unique = {json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")): value for value in values}
    if len(unique) != 1:
        return None
    value = next(iter(unique.values()))
    result = {}
    for selector in value.get("variantSelectors", []):
        if not isinstance(selector, dict) or not isinstance(selector.get("values"), list):
            return None
        label = _norm(selector.get("label"))
        key = "sizes" if label == _norm("サイズ") else "colors" if label == _norm("カラー") else None
        if key:
            options = [item.get("value", "").strip() for item in selector["values"]
                       if isinstance(item, dict) and isinstance(item.get("value"), str)
                       and item["value"].strip()]
            if not options or key in result:
                return None
            result[key] = options
    return result if set(result) == {"colors", "sizes"} else None


def _rakuten_product_page(url):
    """Canonical Rakuten item URL, ignoring only observed affiliate tracking."""
    canonical = _canonical_page(url)
    if not canonical:
        return ""
    parsed = urlsplit(canonical)
    if parsed.hostname != "item.rakuten.co.jp":
        return ""
    query = parse_qs(parsed.query, keep_blank_values=True)
    allowed = {"scid": ["af_pc_etc"], "sc2id": ["af_101_0_0"]}
    if any(key not in allowed or values != allowed[key]
           for key, values in query.items()):
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _rakuten_shop_image(url, shop):
    """Return one host-independent Rakuten shop asset key, or None."""
    try:
        parsed = urlsplit(url)
        parts = [part for part in parsed.path.split("/") if part]
        blocked = re.compile(r"(?:^|[/_.-])(no[-_]?image|dummy|placeholder|spacer|loading|blank|logo)(?:[/_.-]|$)", re.I)
        if (parsed.scheme != "https"
                or parsed.hostname not in ("shop.r10s.jp", "tshop.r10s.jp", "image.rakuten.co.jp")
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or len(parts) < 3 or parts[0] != shop
                or blocked.search(parsed.path)
                or not re.search(r"\.(?:jpe?g|png|webp)$", parsed.path, re.I)):
            return None
        return "/".join(parts)
    except (TypeError, ValueError):
        return None


def merchant_raster_candidate(binding, page_url):
    """Validate metadata for the one Rakuten image route requiring byte proof."""
    if not isinstance(binding, dict) or binding.get("imageIdentityMode") != "rakuten-primary-og-raster-v1":
        return None
    page = _rakuten_product_page(page_url)
    parts = [part for part in urlsplit(page).path.split("/") if part]
    images = binding.get("imageUrls")
    if (len(parts) != 2 or binding.get("sourceKind") != "rakuten-primary-product-dom"
            or binding.get("merchantChannel") != "rakuten"
            or binding.get("merchantSourceSku") != parts[0] + ":" + parts[1]
            or not isinstance(images, list) or len(images) != 1
            or _rakuten_shop_image(images[0], parts[0]) is None):
        return None
    return images[0]


MONTBELL_EXCERPT_LIMIT = 4000


class _ExcerptText(HTMLParser):
    """Visible source text only; never script, navigation or purchase controls."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = (tag in ('script', 'style', 'template', 'noscript', 'nav', 'header', 'footer',
                          'aside', 'form', 'select', 'button')
                  or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attrs.get('style', ''), re.I))
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
                       'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append((tag, bool(hidden) or bool(self.stack and self.stack[-1][1])))
        if tag in ('p', 'br', 'h4', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        if tag in ('p', 'h4', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)


def _montbell_excerpt(html, page_url, model):
    """Bound 商品情報 + 仕様, before 機能 or 詳細情報; invalid scope yields no excerpt."""
    starts = list(re.finditer(r'<h3\b[^>]*>\s*商品情報\s*</h3\s*>', html, re.I))
    if len(starts) != 1:
        return None
    start = starts[0].end()
    end = re.search(r'<h4\b[^>]*>\s*(機能)\s*</h4\s*>|'
                    r'<h3\b[^>]*>\s*(詳細情報)\s*</h3\s*>', html[start:], re.I)
    if end is None:
        return None
    fragment = html[start:start + end.start()]
    if (len(fragment) > 32000 or re.search(r'<h[1-3]\b', fragment, re.I)
            or len(re.findall(r'<h4\b[^>]*>\s*仕様\s*</h4\s*>', fragment, re.I)) != 1):
        return None
    page = _ExcerptText()
    page.feed(fragment)
    text = '\n'.join(' '.join(line.split()) for line in ''.join(page.parts).splitlines() if line.strip())
    if (not text or len(text) > MONTBELL_EXCERPT_LIMIT
            or re.search(r'価格|税込|税抜|[¥￥]|\d[\d,]*\s*円|在庫|入荷|カート|関連商品|おすすめ商品', text)):
        return None
    return {'sourceUrl': page_url, 'model': model, 'text': text,
            'excerptSHA256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'scope': '商品情報 through 仕様, before first ' + (end.group(1) or end.group(2))}


_MONTBELL_DETAIL_HEADINGS = {
    '1107704': ('スパイラル スランテックカフ（特許取得済）', 'フラットシーマー'),
    '1114881': ('素材の特徴＜シャミース＞',
                '着丈はそのままでゆったり着られる＜リラックスサイズ＞',
                '注意事項（38-990）', 'スパイラル スランテックカフ（特許取得済）'),
}


class _MontbellDetails(_ExcerptText):
    """Visible paragraphs under named h4s in one closed 詳細情報 section."""
    def __init__(self, source, headings):
        super().__init__()
        self.headings = headings
        self.heading = None
        self.active = self.closed = False
        self.detail_count = 0
        self.current = None
        self.sections = []
        self.seen = set()
        self.duplicate = False
        self.paragraph = None
        self.feed(source)

    def _finish(self):
        if self.current is not None:
            heading, parts, bad = self.current
            if heading in self.seen:
                self.duplicate = True
            self.seen.add(heading)
            text = '\n'.join(' '.join(line.split()) for line in ''.join(parts).splitlines() if line.strip())
            if not bad and self.paragraph is None and text and len(text) <= 1800:
                self.sections.append((heading, text))
        self.current = self.paragraph = None

    def handle_starttag(self, tag, attrs):
        if tag in ('h1', 'h2', 'h3', 'h4'):
            self._finish()
            if tag != 'h4' and self.active:
                self.active, self.closed = False, True
            self.heading = (tag, [])
        super().handle_starttag(tag, attrs)
        if self.current and not self.heading:
            if tag == 'p' and not self.stack[-1][1]:
                if self.paragraph is not None:
                    self.current[2] = True
                self.paragraph = len(self.stack)
            if tag == 'br' and self.paragraph:
                self.current[1].append('\n')

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        if self.heading:
            self.heading[1].append(data)
        elif self.current:
            if self.paragraph:
                self.current[1].append(data)
            elif data.strip():
                self.current[2] = True  # Unscoped captions/text are not prose evidence.

    def handle_endtag(self, tag):
        if tag in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
                   'meta', 'param', 'source', 'track', 'wbr'):
            return
        if self.current and self.paragraph:
            if not self.stack or self.stack[-1][0] != tag:
                self.current[2] = True
            if tag == 'p':
                if len(self.stack) != self.paragraph:
                    self.current[2] = True
                self.current[1].append('\n')
                self.paragraph = None
        if self.heading and self.heading[0] == tag:
            heading = (' '.join(''.join(self.heading[1]).split())
                       if self.stack and self.stack[-1][0] == tag else '')
            if tag == 'h3' and heading == '詳細情報':
                self.detail_count += 1
                self.active, self.closed = True, False
            elif tag == 'h4' and self.active and heading in self.headings:
                self.current = [heading, [], False]
            self.heading = None
        super().handle_endtag(tag)


def _montbell_details(html, page_url, model):
    headings = _MONTBELL_DETAIL_HEADINGS.get(model)
    if not headings:
        return []
    page = _MontbellDetails(html, headings)
    if page.detail_count != 1 or not page.closed or page.duplicate:
        return []
    result = []
    for heading, text in page.sections:
        if (re.search(r'価格|税込|税抜|[¥￥]|\d[\d,]*\s*円|在庫|入荷|カート|関連商品|おすすめ商品|写真は', text)
                or any(value != model for value in re.findall(r'(?<!\d)\d{7}(?!\d)', text))):
            continue
        result.append({'heading': heading, 'text': text, 'sourceUrl': page_url, 'model': model,
                       'excerptSHA256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                       'scope': '詳細情報 / ' + heading + ', before next h4 or major heading',
                       'conditions': ['Public primary manufacturer claims, not personal experience.',
                                      'Attribute manufacturer claims; preserve all source qualifiers.']})
    return result[:4]


def _inspect_montbell(product, page_url, html, image_url):
    try:
        contract = apparel_contract(product)
        parsed = urlsplit(page_url)
        query = parse_qs(parsed.query)
        if (parsed.scheme != "https" or parsed.hostname != "webshop.montbell.jp"
                or parsed.path != "/goods/disp.php"
                or query.get("product_id") != [contract["model"]]):
            return None
        page = _MontbellProduct(html)
        title = " ".join(" ".join(page.title_parts).split())
        main = " ".join(" ".join(page.main_text).split())
        specs = "\n".join(line.strip() for line in "".join(page.spec_parts).splitlines()
                           if line.strip())
        if (page.product_ids != [contract["model"]]
                or "#" + contract["model"] not in main
                or "モンベル" not in main
                or contract["model"] not in title + " #" + contract["model"]):
            return None
        gender = "Men's" if "Men's" in title else "Women's" if "Women's" in title else ""
        material = re.search(r"【素材】(.+?)(?=\n(?:【|保温材))", specs)
        weight = re.search(r"【(?:平均)?重量】([^\n]+)", specs)
        if (not _brand_matches("モンベル", contract["brand"])
                or _norm(gender) != _norm(contract["gender"])
                or ("fabric" in contract and (not material or _norm(material.group(1)) != _norm(contract["fabric"])))
                or ("weight" in contract and (not weight or _norm(weight.group(1)) != _norm(contract["weight"])))):
            return None
        available_colors = page.color_sets[0] if len(page.color_sets) == 1 else []
        available_sizes = list(dict.fromkeys(page.sizes))
        if not available_colors or not available_sizes:
            return None
        images = list(dict.fromkeys(urljoin(page_url, value) for value in page.images
                                    if re.fullmatch(r"/common/images/product/prod_[ck]/[ck]_"
                                                    + re.escape(contract["model"])
                                                    + r"_[a-z0-9-]+\.jpg", value, re.I)))
        if image_url is not None and image_url not in images:
            return None
        if contract["optionState"] == "fixed":
            if (not any(_norm(value) == _norm(contract["color"])
                        for value in available_colors)
                    or not any(_norm(value) == _norm(contract["size"])
                               for value in available_sizes)):
                return None
            color_image = re.compile(r"_" + re.escape(contract["model"])
                                     + r"_" + re.escape(contract["color"])
                                     + r"\.jpg$", re.I)
            images = [value for value in images if color_image.search(urlsplit(value).path)]
            if not images or (image_url is not None and image_url not in images):
                return None
            colors, sizes = [contract["color"]], [contract["size"]]
        else:
            colors, sizes = available_colors, available_sizes
        result = dict(contract, colors=colors, sizes=sizes, imageUrls=images,
                      sourceUrl=page_url, sourceKind="montbell-product-dom")
        excerpt = _montbell_excerpt(html, page_url, contract['model'])
        if excerpt:
            result['manufacturerExcerpt'] = excerpt
        details = _montbell_details(html, page_url, contract['model'])
        if details:
            result['manufacturerDetails'] = details
        return result
    except (ApparelIdentityError, TypeError, ValueError):
        return None


def claim_binding(binding, key, value):
    """Bind only identity fields actually proved by the apparel Product node."""
    if not isinstance(binding, dict) or not isinstance(value, str) or not value:
        return None
    field = next((name for name, aliases in (
        ("class", ("apparelClass", "apparelCategory", "衣類区分")),
        ("model", MODEL_KEYS), ("gender", GENDER_KEYS), ("fabric", FABRIC_KEYS),
        ("weight", WEIGHT_KEYS), ("optionState", OPTION_KEYS),
        ("color", COLOR_KEYS), ("size", SIZE_KEYS),
    ) if key in aliases), None)
    if field is None or _norm(binding.get(field)) != _norm(value):
        return None
    return {"unit": "bound-apparel-product", "sourceKind": binding.get("sourceKind"),
            "model": binding["model"], "field": key,
            "value": value, "excerpt": key + ": " + value[:500],
            "conditions": ["exact apparel product/variant binding"]}


def public_binding(binding):
    """Projection retained by quality checks; excludes page-local image lists."""
    if not isinstance(binding, dict):
        return None
    keys = ("class", "brand", "model", "gender", "fabric", "weight", "optionState",
            "canonicalVariant", "sourceVariant", "color", "size", "colors", "sizes", "sourceKind",
            "merchantChannel", "merchantOptionState", "merchantVariant",
            "merchantColor", "merchantSize", "imageUrls", "imageIdentityMode",
            "merchantSourceSku", "merchantImageProof", "imageScope", "imageScopeUrl")
    return {key: binding[key] for key in keys if key in binding}


def binding_matches_product(binding, product, channel=None):
    """Validate a retained source projection against current catalogue input."""
    try:
        contract = apparel_contract(product)
    except ApparelIdentityError:
        return False
    allowed = ("json-ld-product", "montbell-product-dom", "finetrack-primary-productgroup-dom", "official-shopify-product", "goldwin-na62650-primary-dom", "patagonia-primary-product-dom") if channel is None else (
        "amazon-primary-product-dom", "rakuten-primary-product-dom")
    if not isinstance(binding, dict) or binding.get("sourceKind") not in allowed:
        return False
    if any(_norm(binding.get(key)) != _norm(value) for key, value in contract.items()):
        return False
    if binding.get('sourceKind') == 'patagonia-primary-product-dom':
        from official_patagonia_apparel import R1_URL
        if (channel is not None or contract['model'] != '40275'
                or contract['class'] != 'fleece' or contract['optionState'] != 'selectable'
                or _norm(contract['brand']) not in ('patagonia', 'パタゴニア')
                or _norm(contract['gender']) not in ("men's", 'men', 'メンズ')
                or ('sourceUrl' in binding and binding['sourceUrl'] != R1_URL)):
            return False
    if binding.get('sourceKind') == 'goldwin-na62650-primary-dom':
        from goldwin_na62650 import FABRIC, WEIGHT, retained_options_match
        if (channel is not None or contract['model'] != 'NA62650'
                or contract['class'] != 'fleece' or contract['optionState'] != 'selectable'
                or _norm(contract['brand']) not in ('the north face', 'thenorthface', 'ザ・ノース・フェイス', 'ザノースフェイス')
                or _norm(contract['gender']) not in ("men's", 'メンズ', 'male')
                or binding.get('fabric') != FABRIC or binding.get('weight') != WEIGHT
                or not retained_options_match(binding)):
            return False
    if ('imageScope' in binding or 'imageScopeUrl' in binding
            or (isinstance(binding.get('imageUrls'), list)
                and _FINETRACK_WEARING_IMAGE in binding['imageUrls'])):
        if (channel is not None or contract['model'] != 'FUM0422'
                or _norm(contract['brand']) not in ('finetrack', 'ファイントラック')
                or contract['optionState'] != 'selectable'
                or binding.get('sourceKind') != 'finetrack-primary-productgroup-dom'
                or binding.get('imageScope') != 'primary-product-wearing-example'
                or binding.get('imageScopeUrl') != _FINETRACK_WEARING_IMAGE
                or not isinstance(binding.get('imageUrls'), list)
                or _FINETRACK_WEARING_IMAGE not in binding['imageUrls']):
            return False
    if channel is not None:
        try:
            merchant = merchant_contract(product, channel)
        except ApparelIdentityError:
            return False
        if any(_norm(binding.get(key)) != _norm(value) for key, value in merchant.items()):
            return False
    mode = binding.get("imageIdentityMode")
    if mode is not None:
        proof = binding.get("merchantImageProof")
        if (mode != "rakuten-primary-og-raster-v1" or channel != "rakuten"
                or not isinstance(proof, dict)
                or set(proof) != {"sourceUrl", "finalUrl", "sha256", "size",
                                  "contentType", "width", "height"}
                or binding.get("imageUrls") != [proof.get("sourceUrl")]
                or proof.get("finalUrl") != proof.get("sourceUrl")
                or not re.fullmatch(r"[a-f0-9]{64}", str(proof.get("sha256", "")))
                or type(proof.get("size")) is not int or proof["size"] <= 0
                or proof.get("contentType") not in ("image/jpeg", "image/png")
                or type(proof.get("width")) is not int or proof["width"] < 300
                or type(proof.get("height")) is not int or proof["height"] < 300):
            return False
    state = (binding.get("merchantOptionState") if channel is not None
             else contract["optionState"])
    if state == "selectable":
        complete = (isinstance(binding.get("colors"), list) and bool(binding["colors"])
                and all(isinstance(v, str) and v.strip() for v in binding["colors"])
                and isinstance(binding.get("sizes"), list) and bool(binding["sizes"])
                and all(isinstance(v, str) and v.strip() for v in binding["sizes"]))
        if not complete:
            return False
        if channel is not None and contract["optionState"] == "fixed":
            return (any(_norm(value) == _norm(contract["color"])
                        or _exact_token(value, contract["color"])
                        for value in binding["colors"])
                    and any(_norm(value) == _norm(contract["size"])
                            for value in binding["sizes"]))
        return True
    color = merchant["merchantColor"] if channel is not None else contract["color"]
    size = merchant["merchantSize"] if channel is not None else contract["size"]
    return binding.get("colors") == [color] and binding.get("sizes") == [size]

