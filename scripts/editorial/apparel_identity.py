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


def _brand_matches(actual, expected):
    groups = (
        {"mont-bell", "montbell", "モンベル"},
        {"the north face", "thenorthface", "ザ・ノース・フェイス", "ザノースフェイス"},
        {"columbia", "コロンビア"}, {"patagonia", "パタゴニア"},
        {"nanga", "ナンガ"},
    )
    left, right = _norm(actual), _norm(expected)
    return left == right or any(left in {_norm(v) for v in group}
                                and right in {_norm(v) for v in group} for group in groups)


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


class _MontbellProduct(HTMLParser):
    """Extract only Mont-bell's primary product DOM, excluding related cards."""
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
        self.stack.append((tag, attrs))
        depth = len(self.stack)
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
        depth = len(self.stack)
        if self._title_depth == depth and tag == "h2":
            self._title_depth = None
        if self._select_depth == depth and tag == "select":
            self._select_depth = None
        if self._spec_heading_depth == depth and tag == "h4":
            self._spec_heading_depth = None
        if self._spec_depth == depth and tag == "p":
            self._spec_depth = None
        if self._main_depth == depth and tag == "div":
            self._main_depth = None
        if self.stack:
            self.stack.pop()


class _MerchantProduct(HTMLParser):
    """Primary Amazon/Rakuten product projection; ignores recommendations."""
    def __init__(self, source):
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


def _inspect_merchant(product, page_url, html, channel):
    try:
        contract = apparel_contract(product)
        merchant = merchant_contract(product, channel)
        page = _MerchantProduct(html)
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
                    or not _exact_token(title, contract["model"])
                    or not _gender_matches(title, contract["gender"])):
                return None
            image = page.primary_images[0]
            if not _exact_token(image.get("alt", ""), contract["model"]):
                return None
            if merchant["merchantOptionState"] == "fixed":
                dimensions = _amazon_selected_dimensions(page.twister_states, asin.group(1))
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
                return None
            source_kind = "rakuten-primary-product-dom"
        else:
            return None
        return dict(contract, **merchant, colors=colors, sizes=sizes,
                    imageUrls=images, sourceUrl=page_url, sourceKind=source_kind)
    except (ApparelIdentityError, TypeError, ValueError):
        return None


def _brand_matches_in_text(text, expected):
    groups = (
        ("mont-bell", "montbell", "モンベル"),
        ("the north face", "thenorthface", "ザ・ノース・フェイス", "ザノースフェイス"),
        ("columbia", "コロンビア"), ("patagonia", "パタゴニア"), ("nanga", "ナンガ"),
    )
    wanted = _norm(expected)
    aliases = next((group for group in groups if wanted in {_norm(v) for v in group}), (expected,))
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
            "merchantColor", "merchantSize", "imageUrls")
    return {key: binding[key] for key in keys if key in binding}


def binding_matches_product(binding, product, channel=None):
    """Validate a retained source projection against current catalogue input."""
    try:
        contract = apparel_contract(product)
    except ApparelIdentityError:
        return False
    allowed = ("json-ld-product", "montbell-product-dom") if channel is None else (
        "amazon-primary-product-dom", "rakuten-primary-product-dom")
    if not isinstance(binding, dict) or binding.get("sourceKind") not in allowed:
        return False
    if any(_norm(binding.get(key)) != _norm(value) for key, value in contract.items()):
        return False
    if channel is not None:
        try:
            merchant = merchant_contract(product, channel)
        except ApparelIdentityError:
            return False
        if any(_norm(binding.get(key)) != _norm(value) for key, value in merchant.items()):
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

