"""Bounded mixed-topic planning for regular production periods from 2026-11-20.

It accepts the already-sanitized analytics projection and fetches only explicitly allowlisted
fixed primary-source URLs through the caller's hardened request function.  It
never receives raw GSC queries or arbitrary URLs.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


JST = timezone(timedelta(hours=9))
MIXED_TOPIC_START = date(2026, 11, 20)
TOPIC_TYPES = {"product", "seasonal_problem", "knowhow"}
INTENTS = {"informational", "commercial_investigation", "transactional"}
MAX_PROPOSALS = 9
PUBLIC_SOURCE_ALLOWLIST = {
    "https://www.coleman.co.jp/customersupport/faq/": "tent-care",
    "https://www.snowpeak.co.jp/contents/campstarterbook/": "camp-care",
    "https://www.montbell.jp/generalpage/disp.php?id=507": "layering-concept-only",
    "https://www.coleman.co.jp/customersupport/faq/?category=sleeping-bag": "coleman-synthetic-wash-decision",
    "https://www.thermos.jp/goods/pdpts": "thermos-parts-lookup",
    "https://www.thermos.jp/goods/ptpds": "thermos-parts-lookup",
    "https://www.thermos.jp/goods/ptpdl?g=900067140990": "thermos-parts-fit-example",
    "https://www.thermos.jp/goods/ptpdl?g=900068940990": "thermos-parts-fit-example",
}
SOURCE_IDS = {
    "https://www.coleman.co.jp/customersupport/faq/": "coleman-care",
    "https://www.snowpeak.co.jp/contents/campstarterbook/": "snowpeak-care",
    "https://www.montbell.jp/generalpage/disp.php?id=507": "montbell-layering",
    "https://www.coleman.co.jp/customersupport/faq/?category=sleeping-bag": "coleman-synthetic-wash",
    "https://www.thermos.jp/goods/pdpts": "thermos-product-parts",
    "https://www.thermos.jp/goods/ptpds": "thermos-parts-product",
    "https://www.thermos.jp/goods/ptpdl?g=900067140990": "thermos-jnls-gasket-fit",
    "https://www.thermos.jp/goods/ptpdl?g=900068940990": "thermos-jnls1000-gasket-fit",
}
FIT_EXAMPLES = {
    "https://www.thermos.jp/goods/ptpdl?g=900067140990": {
        "part": "JNL-Sパッキンセット（フタパッキン・せんパッキン各1個）",
        "partJan": "4562344398367", "model": "JNL-S500",
        "color": "BK-J （ブラックジェイド）", "productJan": "4562344397339"},
    "https://www.thermos.jp/goods/ptpdl?g=900068940990": {
        "part": "JNL-S1000パッキンセット（フタパッキン・せんパッキン各1個）",
        "partJan": "4562344404532", "model": "JNL-S1000",
        "color": "MLGY （ミネラルグレー）", "productJan": "4562344400664"},
}


def _fit_capsule(url):
    item = FIT_EXAMPLES[url]
    return ("部品：" + item["part"] + "\n\n部品JAN：" + item["partJan"] +
            "\n\n適合製品一覧：品番=" + item["model"] + "；色名=" + item["color"] +
            "；JANコード=" + item["productJan"])


class _FitHTML(HTMLParser):
    """Small tree for the fixed fit pages only; never use alt/script/price text."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "attrs": {}, "children": []}
        self.stack = [self.root]
        self.malformed = False

    def handle_starttag(self, tag, attrs):
        if len({key for key, _ in attrs}) != len(attrs):
            self.malformed = True
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if len(self.stack) > 1 and self.stack[-1]["tag"] == tag:
            self.stack.pop()
        elif tag in {"main", "h1", "h2", "table", "tr", "td", "th"}:
            self.malformed = True

    def handle_data(self, data):
        self.stack[-1]["children"].append(data)

    @staticmethod
    def hidden(node):
        attrs = node["attrs"]
        style = re.sub(r"\s+", "", attrs.get("style", "")).lower()
        return (node["tag"] in ("script", "style", "noscript", "template") or
                "hidden" in attrs or "inert" in attrs or attrs.get("aria-hidden", "").lower() == "true" or
                bool(re.search(r"(?:display:none|visibility:hidden)", style)) or
                bool(set(attrs.get("class", "").split()) & {"hidden", "d-none", "is-hidden"}))

    @classmethod
    def nodes(cls, node):
        if cls.hidden(node):
            return
        yield node
        for child in node["children"]:
            if isinstance(child, dict):
                yield from cls.nodes(child)

    @classmethod
    def text(cls, node, exclude=()):
        if cls.hidden(node) or set(node["attrs"].get("class", "").split()) & set(exclude):
            return ""
        return "".join(child if isinstance(child, str) else cls.text(child, exclude)
                       for child in node["children"])


def fit_example_excerpt(url, html):
    """Return only the registered part + exact same-row product, or omit."""
    if url not in FIT_EXAMPLES:
        return None
    tree = _FitHTML()
    try:
        tree.feed(html)
        tree.close()
    except (ValueError, TypeError):
        return None
    if tree.malformed or len(tree.stack) != 1:
        return None
    norm = lambda value: " ".join(value.split())
    roots = [n for n in tree.nodes(tree.root) if n["tag"] == "main"]
    if len(roots) != 1:
        return None
    nodes = list(tree.nodes(roots[0]))
    headings = [n for n in nodes if n["tag"] == "h1"]
    item = FIT_EXAMPLES[url]
    if len(headings) != 1 or norm(tree.text(headings[0], ("_price", "_code"))) != item["part"]:
        return None
    codes = [n for n in tree.nodes(headings[0]) if "_code" in n["attrs"].get("class", "").split()]
    if len(codes) != 1 or norm(tree.text(codes[0])) != "JANコード：" + item["partJan"]:
        return None
    labels = [n for n in nodes if n["tag"] == "h2" and norm(tree.text(n)) == "適合製品一覧"]
    areas = [n for n in nodes if n["attrs"].get("id") == "list_area"]
    if len(labels) != 1 or len(areas) != 1 or nodes.index(labels[0]) > nodes.index(areas[0]):
        return None
    if any(n["tag"] in ("h1", "h2") for n in
           nodes[nodes.index(labels[0]) + 1:nodes.index(areas[0])]):
        return None
    tables = [n for n in tree.nodes(areas[0]) if n["tag"] == "table"]
    if len(tables) != 1:
        return None
    rows = [n for n in tree.nodes(tables[0]) if n["tag"] == "tr"]
    extracted = []
    for row in rows:
        cells = [n for n in tree.nodes(row) if n["tag"] in ("td", "th")]
        if (len(cells) != 3 or any(n["attrs"].get(k, "1") != "1"
                                 for n in cells for k in ("colspan", "rowspan"))):
            return None
        extracted.append(([n["tag"] for n in cells], [norm(tree.text(n)) for n in cells]))
    if not extracted or extracted[0] != (["th"] * 3, ["品番", "色名", "JANコード"]):
        return None
    if any(tags != ["td"] * 3 for tags, _ in extracted[1:]):
        return None
    matching = [values for _, values in extracted[1:]
                if values[:2] == [item["model"], item["color"]]]
    if matching != [[item["model"], item["color"], item["productJan"]]]:
        return None
    return _fit_capsule(url)


def _lookup_blocks(url, html):
    """Keep legacy blocks unchanged; pdpts has one visible div-only location note."""
    parsed = _Blocks()
    parsed.feed(html)
    blocks = list(parsed.blocks)
    if url == 'https://www.thermos.jp/goods/pdpts':
        tree = _FitHTML()
        tree.feed(html)
        areas = [n for n in tree.nodes(tree.root) if n['attrs'].get('id') == 'list_area']
        if not tree.malformed and len(areas) == 1:
            matches = re.findall(
                r'製品の品番・色名は[^。]{0,180}底面(?:シール|ラベル)[^。]{0,180}JANコード付近に記載されております。',
                ' '.join(tree.text(areas[0]).split()))
            if len(matches) == 1 and matches[0] not in blocks:
                blocks.append(matches[0])
    return blocks
SOURCE_KEYWORDS = {
    "https://www.coleman.co.jp/customersupport/faq/": ("乾燥",),
    "https://www.snowpeak.co.jp/contents/campstarterbook/": ("乾燥", "保管"),
    "https://www.montbell.jp/generalpage/disp.php?id=507": ("レイヤリング",),
    "https://www.coleman.co.jp/customersupport/faq/?category=sleeping-bag": ("ウォッシャブル", "化繊", "ラベル"),
    "https://www.thermos.jp/goods/pdpts": ("品番", "色名", "JAN"),
    "https://www.thermos.jp/goods/ptpds": ("交換用部品名", "JAN"),
}
HIGH_RISK = re.compile(
    r"低体温|凍傷|雪山|登山安全|サバイバル|救命|応急処置|医療|治療|診断|服薬|一酸化炭素|死亡|極寒"
)
UNVERIFIED_FIRSTHAND = re.compile(
    r"実測|実証|検証済み|実体験|愛用|使って|使った|使用歴|tested|hands.on", re.I
)
CLAIM_SCOPE_PATTERNS = {
    "tent-care": re.compile(r"テント|幕|乾燥|保管|汚れ|撤収"),
    "camp-care": re.compile(r"テント|幕|寝袋|シュラフ|乾燥|保管|汚れ|撤収"),
    "layering-concept-only": re.compile(r"レイヤリング|重ね着|肌着|中間着|上着|ウェア"),
    "coleman-synthetic-wash-decision": re.compile(
        r"(?=.*(?:コールマン|coleman))(?=.*(?:化繊|ウォッシャブル))"
        r"(?=.*(?:寝袋|シュラフ))(?=.*(?:洗濯|洗える|洗う|手洗い|ラベル|ウォッシャブル))", re.I),
    "thermos-parts-lookup": re.compile(
        r"(?=.*(?:サーモス|thermos))(?=.*(?:部品|パーツ|パッキン))(?=.*(?:探|検索|品番|色名|JAN|適合))", re.I),
}

# These pages support a decision/lookup, not physical care/repair instructions.
NARROW_SCOPE_EXCLUSIONS = {
    "coleman-synthetic-wash-decision": re.compile(
        r"ダウン|羽毛|水温|洗剤|乾燥機|乾かし方|乾燥手順|洗い方|(?:手洗い|洗濯)(?:の|する)?(?:実践|手順|方法|やり方)|耐寒|保温性能"),
    "thermos-parts-lookup": re.compile(
        r"漂白|洗剤|洗浄|分解|修理|互換|取り付け|取付け|(?:交換|取り外し)(?:の)?(?:手順|方法|やり方)|保温性能|保冷性能"),
}
NARROW_OUTLINE_FAMILIES = {
    "wash": re.compile(r"ウォッシャブル|化繊|洗濯|手洗い|縫付|縫い付|ラベル|丸洗い"),
    "parts": re.compile(r"部品|パーツ|パッキン|(?<![A-Za-z])(?:JAN|AND)(?![A-Za-z])|(?:品番|色名).*検索|検索.*(?:品番|色名)", re.I),
}


class TopicSelectionError(ValueError):
    pass


class ResearchProposalsRejected(TopicSelectionError):
    """A received response contained no contract-valid research proposals."""

    def __init__(self, reason, *, response_id, count, rejections):
        super().__init__(reason)
        self.response_id = response_id
        self.count = count
        self.rejections = rejections


class NonproductSourceHold(TopicSelectionError):
    pass


def _aware(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


class _Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.blocks, self.hidden = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag in ("p", "li", "dd", "dt", "h2", "h3", "h4"):
            self.stack.append([tag, []])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden:
            self.hidden -= 1
        if self.stack and self.stack[-1][0] == tag:
            _, parts = self.stack.pop()
            value = " ".join("".join(parts).split())
            if value:
                self.blocks.append(value)

    def handle_data(self, data):
        if not self.hidden:
            for _, parts in self.stack:
                parts.append(data)


def _primary_excerpt(url, blocks):
    keywords = SOURCE_KEYWORDS[url]
    anchor = next((b for b in blocks if 20 <= len(b) <= 500 and all(k in b for k in keywords)), None)
    if PUBLIC_SOURCE_ALLOWLIST[url] == 'thermos-parts-lookup':
        if anchor is None:
            return None
        selected = [anchor]
        for block in blocks:
            if (block not in selected and 10 <= len(block) <= 500 and len(selected) < 4
                    and re.search(r"品番|色名|JAN|交換用部品|適合|AND|半角|全角|表記|スペース", block, re.I)
                    and len("\n\n".join(selected + [block])) <= 500):
                selected.append(block)
        if url == "https://www.thermos.jp/goods/pdpts":
            location = next((b for b in blocks if b not in selected and
                             re.search(r"底.{0,20}(?:ラベル|シール|品番)|ラベル.{0,20}品番", b) and
                             10 <= len(b) <= 500 and len("\n\n".join(selected + [b])) <= 500), None)
            if location:
                selected.append(location)
        return "\n\n".join(selected)
    if anchor is not None:
        return anchor
    # Preserve the existing bounded noncontiguous-paragraph extraction.
    matches = [b for b in blocks if 20 <= len(b) <= 300 and any(k in b for k in keywords)]
    selected = matches[:2]
    return "\n\n".join(selected) if all(any(k in b for b in selected) for k in keywords) else None


def collect_primary_sources(request, *, period, output_path, now=None):
    """Fetch each fixed allowlisted primary page once for a mixed period."""
    now = (now or datetime.now(JST)).astimezone(JST)
    if not mixed_period(period):
        raise TopicSelectionError("mixed_sources_before_effective_period")
    sources, failures = [], []
    for index, (url, scope) in enumerate(PUBLIC_SOURCE_ALLOWLIST.items(), 1):
        try:
            response = request(url, {"Accept": "text/html", "Cache-Control": "no-cache"})
            status = response.get("status")
            final_url = response.get("url") or url
            content_type = (response.get("headers") or {}).get("content-type", "").split(";", 1)[0].lower()
            raw_body = response["body"]
            if not isinstance(raw_body, bytes) or len(raw_body) > 2 * 1024 * 1024:
                raise ValueError("bounded HTML body required")
            body = raw_body.decode("utf-8")
        except (KeyError, UnicodeError, OSError, ValueError, TypeError):
            failures.append({"url": url, "reason": "fetch_failed"})
            continue
        if status != 200:
            failures.append({"url": url, "reason": "http_status_not_200", "httpStatus": status})
            continue
        if final_url != url or content_type not in ("text/html", "application/xhtml+xml"):
            failures.append({"url": url, "reason": "canonical_or_content_type_mismatch",
                             "httpStatus": status})
            continue
        if url in FIT_EXAMPLES:
            excerpt = fit_example_excerpt(url, body)
        else:
            excerpt = _primary_excerpt(url, _lookup_blocks(url, body))
        if not excerpt or len(excerpt) > 500:
            failures.append({"url": url, "reason": "bounded_claim_not_found"})
            continue
        checked = now.isoformat()
        source_id = SOURCE_IDS[url]
        receipt = {"id": source_id, "url": url, "canonicalUrl": final_url,
                   "checkedAt": checked, "httpStatus": 200, "excerpt": excerpt,
                   "claimScope": scope}
        sources.append({**receipt, "title": source_id, "excerptSha256": _sha(excerpt),
                        "receiptSha256": _sha(_canonical(receipt)), "id": "public:" + source_id,
                        "kind": "public-primary", "scope": scope})
    status = "verified" if len(sources) == len(PUBLIC_SOURCE_ALLOWLIST) else (
             "partial" if sources else "unavailable")
    value = {"schemaVersion": 1, "period": period, "collectedAt": now.isoformat(),
             "status": status, "sources": sources, "sourceFailures": failures,
             "coverage": {"verified": len(sources), "expected": len(PUBLIC_SOURCE_ALLOWLIST)}}
    path = Path(output_path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    fd = temp.open("x")
    try:
        json.dump(value, fd, ensure_ascii=False, allow_nan=False)
        fd.flush()
    finally:
        fd.close()
    temp.chmod(0o600)
    temp.replace(path)
    return {"status": status, "sources": sources, "illustrations": [],
            "sourceFailures": failures,
            "reason": None if status == "verified" else "primary_source_coverage_" + status}


def reverify_bound_public_sources(request, references, *, now=None):
    """Re-read immutable bound excerpts without changing their editorial receipt."""
    checked_at = (now or datetime.now(JST)).astimezone(JST).isoformat()
    observations = []
    for reference in references:
        try:
            validate_public_reference(reference)
        except TopicSelectionError:
            raise NonproductSourceHold("nonproduct_source_recheck_changed") from None
        url = reference.get("url") if isinstance(reference, dict) else None
        if (url not in PUBLIC_SOURCE_ALLOWLIST or reference.get("canonicalUrl") != url
                or reference.get("scope") != PUBLIC_SOURCE_ALLOWLIST[url]
                or reference.get("claimScope") != PUBLIC_SOURCE_ALLOWLIST[url]
                or reference.get("id") != "public:" + SOURCE_IDS[url]):
            raise NonproductSourceHold("nonproduct_source_recheck_changed")
        try:
            response = request(url, {"Accept": "text/html", "Cache-Control": "no-cache"})
            content_type = (response.get("headers") or {}).get("content-type", "").split(";", 1)[0].lower()
            body = response["body"]
            if (response.get("status") != 200 or (response.get("url") or url) != url
                    or content_type not in ("text/html", "application/xhtml+xml")
                    or not isinstance(body, bytes) or len(body) > 2 * 1024 * 1024):
                raise NonproductSourceHold("nonproduct_source_recheck_changed")
            html = body.decode("utf-8")
        except NonproductSourceHold:
            raise
        except (KeyError, UnicodeError, OSError, ValueError, TypeError):
            raise NonproductSourceHold("nonproduct_source_recheck_unavailable") from None
        raw_excerpt = str(reference.get("excerpt", ""))
        if url in FIT_EXAMPLES:
            if fit_example_excerpt(url, html) != raw_excerpt:
                raise NonproductSourceHold("nonproduct_source_recheck_changed")
        else:
            try:
                blocks = _lookup_blocks(url, html)
            except (ValueError, TypeError):
                raise NonproductSourceHold("nonproduct_source_recheck_unavailable") from None
            visible_blocks = {" ".join(block.split()) for block in blocks if block.strip()}
            excerpt_parts = [" ".join(part.split()) for part in raw_excerpt.split("\n\n")
                             if part.strip()]
            if not excerpt_parts or any(part not in visible_blocks for part in excerpt_parts):
                raise NonproductSourceHold("nonproduct_source_recheck_changed")
        observations.append({"sourceId": reference.get("id"), "url": url,
                             "checkedAt": checked_at, "httpStatus": 200,
                             "boundExcerptSha256": _sha(raw_excerpt),
                             "responseSha256": hashlib.sha256(body).hexdigest()})
    return {"schemaVersion": 1, "status": "verified", "checkedAt": checked_at,
            "observations": observations}


def _clean_text(value, limit=500):
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value if value and len(value) <= limit else None


def mixed_period(period_key):
    try:
        return date.fromisoformat(period_key) >= MIXED_TOPIC_START
    except (TypeError, ValueError):
        return False


def editorial_signals(analytics, feed):
    """Create stable IDs from bounded page-level aggregates; no query text."""
    records = []
    evidence = analytics.get("evidence", {}) if isinstance(analytics, dict) else {}
    for kind, source in (("gsc", evidence.get("current")), ("ga4", evidence.get("ga4"))):
        if not isinstance(source, dict) or source.get("status") != "ok":
            continue
        rows = source.get("pages") if kind == "gsc" else source.get("landingPages")
        for row in rows or []:
            locator = row.get("url") if kind == "gsc" else row.get("path")
            if not isinstance(locator, str) or not locator:
                continue
            values = {key: row.get(key) for key in
                      (("clicks", "impressions", "ctr", "position") if kind == "gsc"
                       else ("sessions", "engagedSessions", "keyEvents"))}
            if kind == "gsc":
                values["averagePosition"] = values.pop("position")
            identity = json.dumps([kind, source.get("startDate"), source.get("endDate"), locator, values],
                                  sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            records.append({"id": kind + ":" + _sha(identity)[:20], "kind": kind,
                            "locator": locator, "period": {key: source.get(key) for key in
                            ("startDate", "endDate", "dateBasis")}, "metrics": values})
    current, previous = evidence.get("current"), evidence.get("previous")
    if isinstance(current, dict) and isinstance(previous, dict):
        try:
            current_days = (date.fromisoformat(current["endDate"]) - date.fromisoformat(current["startDate"])).days
            previous_days = (date.fromisoformat(previous["endDate"]) - date.fromisoformat(previous["startDate"])).days
        except (KeyError, TypeError, ValueError):
            current_days = previous_days = -1
        prior = {row.get("url"): row for row in previous.get("pages", []) if isinstance(row, dict)}
        if current_days == previous_days >= 0 and current.get("dateBasis") == previous.get("dateBasis"):
            for row in current.get("pages", []):
                old = prior.get(row.get("url")) if isinstance(row, dict) else None
                if not isinstance(old, dict):
                    continue
                pairs = {}
                comparable = True
                for source_key, output_key in (("clicks", "clicks"), ("impressions", "impressions"),
                                               ("ctr", "ctr"), ("position", "averagePosition")):
                    before, after = old.get(source_key), row.get(source_key)
                    if (isinstance(before, bool) or isinstance(after, bool)
                            or not isinstance(before, (int, float)) or not isinstance(after, (int, float))):
                        comparable = False
                        break
                    pairs[output_key] = {"current": after, "previous": before,
                                         "relativeChange": ((after - before) / before if before > 0 else None)}
                if comparable:
                    identity = _canonical([row.get("url"), current["startDate"], current["endDate"], pairs])
                    records.append({"id": "gsc-change:" + _sha(identity)[:20],
                                    "kind": "own_site_gsc_period_comparison", "locator": row.get("url"),
                                    "status": "measured", "metrics": pairs,
                                    "limitations": "own-site page aggregate; not market demand or Google Trends"})
    current_demand = current.get("searchDemand") if isinstance(current, dict) else None
    previous_demand = previous.get("searchDemand") if isinstance(previous, dict) else None
    if (isinstance(current_demand, dict) and current_demand.get("status") == "available"
            and isinstance(current_demand.get("groups"), list)):
        current_period = current_demand.get("period")
        previous_period = previous_demand.get("period") if isinstance(previous_demand, dict) else None
        safe_period = _demand_period(current_period)
        if safe_period is None:
            current_demand = None
        comparable = (isinstance(previous_demand, dict)
                      and previous_demand.get("status") == "available"
                      and isinstance(previous_demand.get("groups"), list)
                      and _comparable_periods(current_period, previous_period))
        prior_groups = {}
        if comparable:
            for group in previous_demand.get("groups", []):
                if isinstance(group, dict) and _controlled_facets(group.get("facets")) is not None:
                    prior_groups[group.get("id")] = group
                    facet_id = group.get("facetId")
                    if isinstance(facet_id, str):
                        prior_groups[facet_id] = group
        for group in current_demand["groups"][:40] if current_demand else []:
            if not isinstance(group, dict):
                continue
            facets = _controlled_facets(group.get("facets"))
            metrics = _demand_metrics(group.get("metrics"))
            query_count = group.get("queryCount")
            signal_id = group.get("id")
            if (facets is None or metrics is None or not isinstance(signal_id, str)
                    or not re.fullmatch(r"gsc-demand:[a-f0-9]{64}", signal_id)
                    or isinstance(query_count, bool)
                    or not isinstance(query_count, int) or not 1 <= query_count <= 10000):
                continue
            old = prior_groups.get(group.get("facetId")) or prior_groups.get(signal_id)
            previous_values = None
            if (isinstance(old, dict) and _controlled_facets(old.get("facets")) == facets
                    and _demand_metrics(old.get("metrics")) is not None):
                old_count = old.get("queryCount")
                if isinstance(old_count, int) and not isinstance(old_count, bool) and old_count >= 0:
                    previous_values = {"queryCount": old_count,
                                       "metrics": _demand_metrics(old["metrics"]),
                                       "period": _demand_period(previous_period)}
            records.append({"id": signal_id, "kind": "own_site_query_demand",
                            "facets": facets, "queryCount": query_count, "metrics": metrics,
                            "period": safe_period,
                            "coverage": _demand_coverage(current_demand.get("coverage")),
                            "previous": previous_values,
                            "limitations": "own-site search sample; not market search volume"})
    for item in feed.get("sources", []):
        records.append({"id": item["id"], "kind": "public_reference", "url": item["url"],
                        "title": item["title"], "excerpt": item["excerpt"], "scope": item["scope"],
                        "checkedAt": item["checkedAt"], "receiptSha256": item["receiptSha256"],
                        "excerptSha256": item["excerptSha256"]})
    return sorted(records, key=lambda item: item["id"])


FACET_KEYS = ("garments", "brands", "problems", "seasons", "intents", "gearTypes")
TOPICAL_FACETS = ("garments", "brands", "problems", "gearTypes")


def _controlled_facets(value):
    if not isinstance(value, dict) or set(value) != set(FACET_KEYS):
        return None
    try:
        from search_demand import ALIASES
    except ImportError:
        try:
            from .search_demand import ALIASES
        except (ImportError, ValueError):
            return None
    result = {}
    for key in FACET_KEYS:
        items = value.get(key)
        if (not isinstance(items, list) or len(items) > 40
                or any(not isinstance(item, str) or not item or len(item) > 80 for item in items)
                or len(items) != len(set(items)) or any(item not in ALIASES[key] for item in items)):
            return None
        result[key] = list(items)
    return result


def _demand_metrics(value):
    keys = ("clicks", "impressions", "ctr", "averagePosition")
    if not isinstance(value, dict) or any(key not in value for key in keys):
        return None
    result = {}
    for key in keys:
        item = value.get(key)
        if item is not None and (isinstance(item, bool) or not isinstance(item, (int, float))
                                 or not math.isfinite(item) or not 0 <= item <= 2**53 - 1):
            return None
        result[key] = item
    if (not isinstance(result["clicks"], (int, type(None)))
            or not isinstance(result["impressions"], (int, type(None)))
            or (result["clicks"] is not None and result["impressions"] is not None
                and result["clicks"] > result["impressions"])
            or (result["ctr"] is not None and result["ctr"] > 1)
            or result["averagePosition"] == 0):
        return None
    return result


def _demand_period(value):
    # GSC's reporting dates are source-native Pacific dates.  They are evidence
    # windows, not operational timestamps, and must never be relabelled as JST.
    if (not isinstance(value, dict) or value.get("dateBasis") != "America/Los_Angeles"
            or not _comparable_periods(value, value)):
        return None
    return {key: value[key] for key in ("startDate", "endDate", "dateBasis")}


DEMAND_COVERAGE_FIELDS = {
    "source", "scope", "marketDemand", "trendVerified", "positionAggregation",
    "inputRowCount", "processedRowCount", "uniqueQueryCount", "classifiedQueryCount",
    "unclassifiedQueryCount", "duplicateRowCount", "conflictingDuplicateCount",
    "invalidRowCount", "missingMetricsQueryCount", "observedGroupCount", "exportedGroupCount",
    "inputTruncated", "groupsTruncated", "observedRowsComplete", "status",
    "selectionPolicy", "preferredGroupLimit", "preferredGroupCount", "globalFillGroupCount",
    "observedSeasonalGroupCount", "exportedSeasonalGroupCount",
    "observedApparelGroupCount", "exportedApparelGroupCount",
    "observedBrandComparisonGroupCount", "exportedBrandComparisonGroupCount",
}


def _demand_coverage(value):
    if not isinstance(value, dict):
        return None
    safe = {key: item for key, item in value.items()
            if key in DEMAND_COVERAGE_FIELDS and
            (item is None or isinstance(item, (int, bool))
             or isinstance(item, float) and math.isfinite(item))}
    enums = {"selectionPolicy": {"preferred_context_round_robin_then_global_v1"},
             "source": {"own_site_gsc_query_aggregates"},
             "scope": {"observed_query_rows_only", "own_site_search_sample"},
             "positionAggregation": {"impression_weighted"},
             "status": {"available", "partial"}}
    for key, allowed in enums.items():
        if value.get(key) in allowed:
            safe[key] = value[key]
    return safe


def _comparable_periods(current, previous):
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return False
    try:
        current_days = (date.fromisoformat(current["endDate"]) -
                        date.fromisoformat(current["startDate"])).days
        previous_days = (date.fromisoformat(previous["endDate"]) -
                         date.fromisoformat(previous["startDate"])).days
    except (KeyError, TypeError, ValueError):
        return False
    return current_days == previous_days >= 0 and current.get("dateBasis") == previous.get("dateBasis")


def _normal(value):
    return re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龠]", "", str(value).casefold())


def _grams(value):
    value = _normal(value)
    return {value[i:i + 2] for i in range(max(0, len(value) - 1))}


def _similar(left, right):
    a, b = _normal(left), _normal(right)
    if not a or not b:
        return False
    if a == b or (min(len(a), len(b)) >= 8 and (a in b or b in a)):
        return True
    ga, gb = _grams(a), _grams(b)
    return bool(ga and gb and len(ga & gb) / len(ga | gb) >= 0.72)


def allowed_claim_scopes(proposal):
    """Primary topic only; outline text can never legitimize an unrelated source."""
    text = " ".join([str(proposal.get("title", "")), str(proposal.get("readerQuestion", ""))])
    narrow = [scope for scope in NARROW_SCOPE_EXCLUSIONS if CLAIM_SCOPE_PATTERNS[scope].search(text)]
    if narrow:
        all_text = text + " " + " ".join(map(str, proposal.get("outline", [])))
        if len(narrow) != 1 or NARROW_SCOPE_EXCLUSIONS[narrow[0]].search(all_text):
            return []
        if (narrow == ["thermos-parts-lookup"] and
                any(source in {"public:" + SOURCE_IDS[url] for url in FIT_EXAMPLES}
                    for source in proposal.get("sourceIds", []))):
            return narrow + ["thermos-parts-fit-example"]
        return narrow
    return sorted(scope for scope, pattern in CLAIM_SCOPE_PATTERNS.items() if pattern.search(text))


def _scope_family(scope):
    return {"layering-concept-only": "layering", "coleman-synthetic-wash-decision": "wash",
            "thermos-parts-lookup": "parts", "thermos-parts-fit-example": "parts"}.get(scope, "care")


def _outline_scope_families(proposal):
    text = " ".join(str(item) for item in proposal.get("outline", []))
    families = {_scope_family(scope) for scope, pattern in CLAIM_SCOPE_PATTERNS.items() if pattern.search(text)}
    families.update(family for family, pattern in NARROW_OUTLINE_FAMILIES.items() if pattern.search(text))
    primary = " ".join([str(proposal.get("title", "")), str(proposal.get("readerQuestion", ""))])
    if (CLAIM_SCOPE_PATTERNS["coleman-synthetic-wash-decision"].search(primary)
            and not re.search(r"テント|幕|乾燥|保管|汚れ|撤収", text)):
        families.discard("care")  # The sleeping-bag noun alone is not a general-care claim.
    return families


def validate_proposals(raw, *, catalog_ids, existing_ids=(), category_ids=None):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PROPOSALS:
        raise TopicSelectionError("one_to_nine_proposals_required")
    required = {"slug", "title", "categoryId", "productIds", "topicType", "query",
                "readerQuestion", "intent", "outline", "priority", "overlapRationale",
                "selectionReason", "sourceIds", "proposedAction", "overlapArticleIds", "needsStatus"}
    result = []
    for proposal in raw:
        if not isinstance(proposal, dict) or set(proposal) != required:
            raise TopicSelectionError("proposal_fields")
        if (proposal["topicType"] not in TOPIC_TYPES or proposal["intent"] not in INTENTS
                or not isinstance(proposal["priority"], int) or not 1 <= proposal["priority"] <= 100
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", str(proposal["slug"]))
                or not _clean_text(proposal["title"], 80)
                or UNVERIFIED_FIRSTHAND.search(proposal["title"])
                or any(not _clean_text(proposal[key], 500) for key in
                       ("categoryId", "query", "readerQuestion", "overlapRationale", "selectionReason"))
                or (category_ids is not None and proposal["categoryId"] not in set(category_ids))
                or not isinstance(proposal["outline"], list) or not 3 <= len(proposal["outline"]) <= 5
                or any(not _clean_text(value, 40) for value in proposal["outline"])
                or not isinstance(proposal["sourceIds"], list) or not proposal["sourceIds"]
                or len(set(proposal["sourceIds"])) != len(proposal["sourceIds"])
                or proposal["proposedAction"] not in ("new", "existing_update", "hold")
                or proposal["needsStatus"] not in ("not_applicable", "measured_change", "seasonal_hypothesis")
                or (proposal["topicType"] == "seasonal_problem" and
                    proposal["needsStatus"] not in ("measured_change", "seasonal_hypothesis"))
                or (proposal["topicType"] != "seasonal_problem" and proposal["needsStatus"] != "not_applicable")
                or not isinstance(proposal["overlapArticleIds"], list)
                or len(set(proposal["overlapArticleIds"])) != len(proposal["overlapArticleIds"])
                or any(value not in set(existing_ids) for value in proposal["overlapArticleIds"])
                or (proposal["proposedAction"] == "existing_update" and not proposal["overlapArticleIds"])
                or (proposal["proposedAction"] == "new" and proposal["overlapArticleIds"])):
            raise TopicSelectionError("proposal_contract")
        ids = proposal["productIds"]
        if (not isinstance(ids, list) or len(set(ids)) != len(ids)
                or any(pid not in catalog_ids for pid in ids)
                or (proposal["topicType"] == "product" and not ids)):
            raise TopicSelectionError("proposal_product_route")
        result.append(json.loads(json.dumps(proposal, ensure_ascii=False)))
    return result


def _topic_text(value):
    return " ".join(str(value.get(key, "")) for key in ("title", "readerQuestion", "query"))


def _facets(value, classifier):
    try:
        return _controlled_facets(classifier(value))
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def _facet_matches(left, right):
    return {key: sorted(set(left.get(key, [])) & set(right.get(key, [])))
            for key in FACET_KEYS}


def _related_match(left, right):
    matches = _facet_matches(left, right)
    for key in (*TOPICAL_FACETS, "intents"):
        if left.get(key) and right.get(key) and not matches[key]:
            return None
    return matches if matches["garments"] or matches["gearTypes"] else None


def _direct_match(candidate, demand):
    matches = _related_match(candidate, demand)
    if matches is None:
        matches = _facet_matches(candidate, demand)
        no_explicit_subject = not any(
            candidate.get(key) or demand.get(key) for key in ("garments", "gearTypes"))
        contradiction = any(candidate.get(key) and demand.get(key) and not matches[key]
                            for key in ("brands", "problems", "seasons", "intents"))
        if (not no_explicit_subject or contradiction
                or not matches["problems"] or not matches["seasons"]):
            return None
    for key in ("garments", "brands", "problems", "seasons", "gearTypes"):
        if candidate.get(key) and not set(candidate[key]).issubset(demand.get(key, [])):
            return None
    if ("comparison" in candidate.get("intents", []) and len(candidate.get("brands", [])) >= 2
            and ("comparison" not in demand.get("intents", [])
                 or not set(candidate["brands"]).issubset(demand.get("brands", [])))):
        return None
    return matches


def _has_observed_metric(value):
    if not isinstance(value, dict):
        return False
    for item in value.values():
        if isinstance(item, dict) and _has_observed_metric(item):
            return True
        if (isinstance(item, (int, float)) and not isinstance(item, bool)
                and math.isfinite(item) and item >= 0):
            return True
    return False


def _article_texts(article):
    values = [article.get(key, "") for key in
              ("slug", "title", "query", "readerQuestion", "excerpt", "conclusion")]
    values.extend(article.get("headings") or [])
    values.extend(article.get("faqQuestions") or [])
    for faq in article.get("faqs") or []:
        if isinstance(faq, dict):
            values.extend((faq.get("question", ""), faq.get("answer", "")))
    for section in article.get("sections") or []:
        if isinstance(section, dict):
            values.extend((section.get("heading", ""), section.get("text", "")))
    return [str(value) for value in values if isinstance(value, str) and value.strip()]


def _rich_overlap(proposal, articles, classifier):
    candidate = [proposal.get(key, "") for key in ("title", "readerQuestion", "query")]
    candidate_facets = _facets(_topic_text(proposal), classifier) or {key: [] for key in FACET_KEYS}
    for article in articles:
        if article.get("categoryId") != proposal.get("categoryId"):
            continue
        article_facets = _facets(" ".join(_article_texts(article)), classifier) or {
            key: [] for key in FACET_KEYS}
        shared = _related_match(candidate_facets, article_facets)
        if ("comparison" in candidate_facets.get("intents", [])
                and len(candidate_facets.get("brands", [])) >= 2
                and not set(candidate_facets["brands"]).issubset(article_facets.get("brands", []))):
            continue
        if any(_similar(value, covered) for value in candidate for covered in _article_texts(article)):
            if shared:
                return article
    return None


def _article_for_signal(signal, existing):
    locator = signal.get("locator")
    if not isinstance(locator, str) or not locator:
        return None
    try:
        parsed = urlsplit(locator)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme:
        if (parsed.scheme != "https" or parsed.hostname != "camp-gear-lab.com"
                or port is not None or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment):
            return None
        path = parsed.path.rstrip("/")
    else:
        if not locator.startswith("/articles/") or "?" in locator or "#" in locator:
            return None
        path = locator.rstrip("/")
    for article in existing:
        slug = article.get("slug")
        if isinstance(slug, str) and slug and path == "/articles/" + slug:
            return article
    return None


def _need_evidence(proposal, signal_map, existing, classifier):
    candidate = _facets(_topic_text(proposal), classifier)
    unknown = {key: [] for key in FACET_KEYS}
    if candidate is None:
        return "unknown", unknown, [], []
    direct, proxy = [], []
    direct_matched = {key: set() for key in FACET_KEYS}
    proxy_matched = {key: set() for key in FACET_KEYS}
    for source_id in proposal.get("sourceIds", []):
        signal = signal_map.get(source_id, {})
        if signal.get("kind") == "own_site_query_demand":
            demand_facets = _controlled_facets(signal.get("facets"))
            query_count = signal.get("queryCount")
            demand_metrics = _demand_metrics(signal.get("metrics"))
            measured_need = (demand_metrics is not None and any(
                isinstance(demand_metrics[key], (int, float)) and demand_metrics[key] > 0
                for key in ("clicks", "impressions")))
            shared = (_direct_match(candidate, demand_facets or {})
                      if isinstance(query_count, int) and not isinstance(query_count, bool)
                      and query_count > 0 and measured_need
                      else None)
            if shared:
                direct.append(signal)
                for key, values in shared.items():
                    direct_matched[key].update(values)
        elif signal.get("kind") in ("gsc", "ga4", "own_site_gsc_period_comparison"):
            if not _has_observed_metric(signal.get("metrics")):
                continue
            article = _article_for_signal(signal, existing)
            if article is None or article.get("categoryId") != proposal.get("categoryId"):
                continue
            article_facets = _facets(" ".join(_article_texts(article)), classifier)
            shared = _related_match(candidate, article_facets or {})
            if shared:
                proxy.append(signal)
                for key, values in shared.items():
                    proxy_matched[key].update(values)
    basis = "direct_matched_query_group" if direct else "related_page_proxy" if proxy else "unknown"
    matched = direct_matched if direct else proxy_matched
    return basis, {key: sorted(values) for key, values in matched.items()}, direct, proxy


NARROW_TOPIC = re.compile(
    r"(?:ソール|靴底).*(?:手入れ|洗|汚れ)|(?:洗濯表示|ケアラベル|ラベルだけ)|"
    r"(?:部品|パーツ|パッキン).*(?:適合|品番|探|検索|確認)|(?:適合|品番).*(?:部品|パーツ|パッキン)|"
    r"(?:ポール|ジョイント|グロメット).*(?:掃除|清掃|手入れ|汚れ)|"
    r"(?:掃除|清掃|手入れ|汚れ).*(?:ポール|ジョイント|グロメット)|"
    r"(?:洗濯表示|ケアラベル|ラベル).*(?:確認|読む|見方|判断)"
)

NARROW_FAMILIES = (
    re.compile(r"ソール|靴底"), re.compile(r"洗濯表示|ケアラベル|ラベル"),
    re.compile(r"部品|パーツ|パッキン|適合|品番"),
    re.compile(r"ポール|ジョイント|グロメット"),
)
NARROW_TERMS = re.compile(
    r"ソール|靴底|洗濯表示|ケアラベル|ラベル|部品|パーツ|パッキン|適合|品番|ポール|ジョイント|グロメット")


def _narrow_target(proposal, existing, candidate_facets, classifier):
    candidates = []
    proposal_text = _topic_text(proposal)
    families = [pattern for pattern in NARROW_FAMILIES if pattern.search(proposal_text)]
    wanted_terms = set(NARROW_TERMS.findall(proposal_text))
    for article in existing:
        if article.get("categoryId") != proposal.get("categoryId"):
            continue
        article_text = " ".join(_article_texts(article))
        if not families or not any(pattern.search(article_text) for pattern in families):
            continue
        article_facets = _facets(article_text, classifier)
        article_facets = article_facets or {key: [] for key in FACET_KEYS}
        if any(candidate_facets.get(key) and article_facets.get(key)
               and not set(candidate_facets[key]) & set(article_facets[key])
               for key in ("garments", "gearTypes")):
            continue
        shared = _related_match(candidate_facets, article_facets)
        article_terms = set(NARROW_TERMS.findall(article_text))
        term_matches = wanted_terms & article_terms
        candidate_brands = set(candidate_facets.get("brands", []))
        article_brands = set(article_facets.get("brands", []))
        if candidate_brands and article_brands and not candidate_brands & article_brands:
            continue
        if shared or term_matches:
            score = sum(len(values) for values in (shared or {}).values()) + len(term_matches)
            candidates.append((-score, str(article.get("slug", "")), article))
    candidates.sort(key=lambda value: (value[0], value[1]))
    return candidates[0][2] if candidates else None


def _update_record(record, article, reason):
    record.update(status="existing_update", reason=reason,
                  existingArticleId=article.get("id"), existingSlug=article.get("slug"),
                  baseVersion=article.get("updatedAt"), contentHash=article.get("contentSha256"),
                  existingCoverage={key: article.get(key) for key in
                                    ("bodyCoverage", "contentSha256", "faqsSha256")},
                  nextStep="queue_existing_update_proposal_only_for_separate_owner_approval")


def _score_rationale(proposal, basis, matches, direct, proxy):
    preference = []
    if matches.get("seasons"):
        preference.append("seasonal")
    if matches.get("garments"):
        preference.append("apparel")
    if len(matches.get("brands", [])) >= 2 and "comparison" in matches.get("intents", []):
        preference.append("brand_comparison")
    signals = direct or proxy
    observed = []
    for signal in signals:
        metrics = signal.get("metrics") if isinstance(signal.get("metrics"), dict) else {}
        observed.append({"sourceId": signal.get("id"), "queryCount": signal.get("queryCount"),
                         "clicks": metrics.get("clicks"), "impressions": metrics.get("impressions")})
    pairs = [(row["queryCount"] if isinstance(row.get("queryCount"), int) else -1,
              row["impressions"] if isinstance(row.get("impressions"), (int, float)) else -1)
             for row in observed]
    strongest = max(pairs, default=(-1, -1))
    strength = {"queryCount": strongest[0] if strongest[0] >= 0 else None,
                "impressions": strongest[1] if strongest[1] >= 0 else None}
    tier = 2 if basis == "direct_matched_query_group" else 1 if basis == "related_page_proxy" else 0
    return {"needTier": tier,
            "matchedFacets": matches, "observed": observed,
            "observedStrength": strength, "preferenceReasons": preference,
            "aiPriority": proposal.get("priority")}


def select_proposals(proposals, *, signals, existing, queued, feed, limit=3,
                     classify_topic=None):
    """Deterministic relevant-need and full-index overlap gate."""
    if classify_topic is None:
        try:
            from search_demand import classify_topic
        except ImportError:
            try:
                from .search_demand import classify_topic
            except (ImportError, ValueError):
                classify_topic = lambda _text: {key: [] for key in FACET_KEYS}
    signal_ids = [item.get("id") for item in signals if isinstance(item, dict)]
    if len(signal_ids) != len(signals) or len(signal_ids) != len(set(signal_ids)):
        raise TopicSelectionError("editorial_signal_identity_invalid")
    signal_map = {item["id"]: item for item in signals}
    public_ids = {item["id"] for item in feed.get("sources", [])}
    public_scopes = {item["id"]: item.get("scope") for item in feed.get("sources", [])}
    illustrations = feed.get("illustrations", [])
    decisions, eligible = [], []
    seen = list(existing) + list(queued)
    for index, proposal in enumerate(proposals):
        record = {"proposal": proposal, "sourceIds": list(proposal["sourceIds"]),
                  "status": "rejected", "reason": None, "needBasis": "unknown"}
        unknown = [source for source in proposal["sourceIds"] if source not in signal_map]
        referenced_public = [source for source in proposal["sourceIds"] if source in public_ids]
        scopes = set(allowed_claim_scopes(proposal))
        source_families = {_scope_family(public_scopes[source]) for source in referenced_public}
        overlap = _rich_overlap(proposal, seen, classify_topic)
        structured_existing = next((item for item in existing
                                    if item.get("id") in proposal["overlapArticleIds"]), None)
        need_basis, matches, direct, proxy = _need_evidence(
            proposal, signal_map, existing, classify_topic)
        record["needBasis"] = need_basis
        record["scoreRationale"] = _score_rationale(
            proposal, need_basis, matches, direct, proxy)
        candidate_facets = _facets(_topic_text(proposal), classify_topic) or {
            key: [] for key in FACET_KEYS}
        narrow = bool(NARROW_TOPIC.search(_topic_text(proposal)))
        narrow_target = _narrow_target(proposal, existing, candidate_facets, classify_topic) if narrow else None
        if unknown:
            record["reason"] = "unknown_evidence_id"
        elif HIGH_RISK.search(" ".join([proposal["title"], proposal["readerQuestion"], *proposal["outline"]])):
            record["reason"] = "high_stakes_nonproduct_excluded" if not proposal["productIds"] else "high_stakes_topic_excluded"
        elif not proposal["productIds"] and (feed.get("status") not in ("verified", "partial")
                                              or not referenced_public):
            record["reason"] = "verified_nonproduct_source_route_required"
        elif not proposal["productIds"] and (not scopes or
                                              any(public_scopes[source] not in scopes
                                                  for source in referenced_public)):
            record["reason"] = "nonproduct_claim_scope_mismatch"
        elif not proposal["productIds"] and not _outline_scope_families(proposal).issubset(
                source_families):
            record["reason"] = "nonproduct_outline_scope_uncovered"
        elif proposal["proposedAction"] == "hold":
            record.update(status="hold", reason="semantic_overlap_ambiguous_hold")
        elif proposal["proposedAction"] == "existing_update":
            if structured_existing is None:
                record.update(status="hold", reason="existing_update_target_unknown")
            else:
                _update_record(record, structured_existing,
                               "model_overlap_routed_to_existing_update")
        elif overlap is not None:
            if overlap in existing:
                _update_record(record, overlap, "rich_existing_content_overlap")
            else:
                record["reason"] = "overlaps_queued_theme"
        elif narrow:
            if narrow_target is None:
                record.update(status="hold", reason="narrow_topic_target_unknown")
            else:
                _update_record(record, narrow_target, "narrow_topic_routed_to_existing_update")
        elif need_basis == "unknown":
            record["reason"] = "relevant_search_need_required"
        elif (proposal["needsStatus"] == "measured_change" and not any(
                signal.get("kind") == "own_site_gsc_period_comparison" for signal in proxy)):
            record["reason"] = "measured_change_evidence_required"
        else:
            record["status"] = "eligible"
            record["reason"] = "relevant_need_and_overlap_checks_passed"
            eligible.append((index, proposal, record))
        decisions.append(record)
        if record["status"] in ("eligible", "selected", "existing_update"):
            seen.append(proposal)
    def rank(item):
        rationale = item[2]["scoreRationale"]
        facet_count = min(3, sum(bool(values) for values in rationale["matchedFacets"].values()))
        strength = rationale["observedStrength"]
        query_count = strength["queryCount"] if strength["queryCount"] is not None else -1
        impressions = strength["impressions"] if strength["impressions"] is not None else -1
        preference = min(2, len(rationale["preferenceReasons"]))
        return (-rationale["needTier"], -preference, -query_count, -impressions,
                -facet_count, -item[1]["priority"], item[1]["slug"], item[0])
    eligible.sort(key=rank)
    chosen = eligible[:min(limit, 3)]
    eligible = eligible[min(limit, 3):]
    for _, _, record in chosen:
        record.update(status="selected", reason="deterministic_relevant_need_rank")
    for _, _, record in eligible:
        record.update(status="rejected", reason="period_selection_limit")
    selected = [item["proposal"] for item in decisions if item["status"] == "selected"]
    if len(selected) < min(limit, 3):
        for record in decisions:
            if record["status"] == "selected":
                record.update(status="hold", reason="insufficient_qualified_period_pool")
        return {"selected": [], "decisions": decisions, "status": "hold",
                "eligibleCount": len(selected), "unfilled": min(limit, 3) - len(selected),
                "holdReason": "insufficient_qualified_period_pool"}
    return {"selected": selected, "decisions": decisions,
            "status": "selected", "eligibleCount": len(selected), "unfilled": 0,
            "holdReason": None}


def bind_nonproduct_theme(theme, feed):
    if theme.get("productIds") != []:
        return theme
    wanted = set(theme.get("sourceIds", []))
    references = [item for item in feed.get("sources", []) if item["id"] in wanted]
    scopes = allowed_claim_scopes(theme)
    source_families = {_scope_family(item.get("scope")) for item in references}
    if (not references or not scopes
            or any(item.get("scope") not in scopes for item in references)
            or not _outline_scope_families(theme).issubset(source_families)):
        raise TopicSelectionError("nonproduct_claim_scope_mismatch")
    bound = json.loads(json.dumps(theme, ensure_ascii=False))
    receipt_sha = _sha(_canonical([item["receiptSha256"] for item in references]))
    bound["nonProductContract"] = {
        "route": "verified_public_sources", "commerce": "not_applicable",
        "references": references, "images": [], "sourceReceiptSha256": receipt_sha,
        "allowedClaimScopes": scopes,
    }
    validate_nonproduct_contract(bound)
    return bound


def validate_public_reference(item):
    """Validate the full fixed-registry receipt, never a caller's verified flag."""
    fields = {"id", "url", "canonicalUrl", "checkedAt", "httpStatus", "excerpt", "claimScope",
              "title", "excerptSha256", "receiptSha256", "kind", "scope"}
    if not isinstance(item, dict) or set(item) != fields:
        raise TopicSelectionError("nonproduct_reference_receipt_invalid")
    url = item["url"]
    if (not isinstance(url, str) or url not in PUBLIC_SOURCE_ALLOWLIST or
            item["id"] != "public:" + SOURCE_IDS[url] or item["canonicalUrl"] != url or
            type(item["httpStatus"]) is not int or item["httpStatus"] != 200 or
            _aware(item["checkedAt"]) is None or item["kind"] != "public-primary" or
            item["scope"] != PUBLIC_SOURCE_ALLOWLIST[url] or item["claimScope"] != item["scope"] or
            not isinstance(item["title"], str) or not item["title"].strip() or
            not isinstance(item["excerpt"], str) or not 1 <= len(item["excerpt"]) <= 500):
        raise TopicSelectionError("nonproduct_reference_receipt_invalid")
    receipt = {key: item[key] for key in
               ("url", "canonicalUrl", "checkedAt", "httpStatus", "excerpt", "claimScope")}
    receipt["id"] = SOURCE_IDS[url]
    if (item["excerptSha256"] != _sha(item["excerpt"]) or
            item["receiptSha256"] != _sha(_canonical(receipt)) or
            (url in FIT_EXAMPLES and item["excerpt"] != _fit_capsule(url))):
        raise TopicSelectionError("nonproduct_reference_receipt_invalid")
    return item


def validate_nonproduct_contract(theme):
    contract = theme.get("nonProductContract") if isinstance(theme, dict) else None
    fields = {"route", "commerce", "references", "images", "sourceReceiptSha256", "allowedClaimScopes"}
    if (not isinstance(contract, dict) or set(contract) != fields or theme.get("productIds") != [] or
            contract["route"] != "verified_public_sources" or contract["commerce"] != "not_applicable" or
            contract["allowedClaimScopes"] != allowed_claim_scopes(theme)):
        raise TopicSelectionError("nonproduct_contract_required")
    refs = contract["references"]
    if not isinstance(refs, list) or not refs or contract["images"] != []:
        raise TopicSelectionError("nonproduct_evidence_incomplete")
    for item in refs:
        validate_public_reference(item)
    ids = [item["id"] for item in refs]
    source_ids = theme.get("sourceIds")
    if (not isinstance(source_ids, list) or any(not isinstance(i, str) for i in source_ids) or
            len(set(source_ids)) != len(source_ids) or len(set(ids)) != len(ids) or
            set(ids) != {i for i in source_ids if i.startswith("public:")} or
            any(item["scope"] not in contract["allowedClaimScopes"] for item in refs) or
            contract["sourceReceiptSha256"] != _sha(_canonical([r["receiptSha256"] for r in refs])) or
            not _outline_scope_families(theme).issubset({_scope_family(r["scope"]) for r in refs})):
        raise TopicSelectionError("nonproduct_evidence_incomplete")
    return contract


def gather_nonproduct(theme, catalog):
    validate_nonproduct_contract(theme)
    contract = theme.get("nonProductContract") if isinstance(theme, dict) else None
    if (theme.get("productIds") != [] or not isinstance(contract, dict)
            or contract.get("route") != "verified_public_sources"
            or contract.get("commerce") != "not_applicable"
            or contract.get("allowedClaimScopes") != allowed_claim_scopes(theme)):
        raise TopicSelectionError("nonproduct_contract_required")
    references, images = contract.get("references"), contract.get("images")
    if (not references or contract.get("sourceReceiptSha256") !=
            _sha(_canonical([item.get("receiptSha256") for item in references]))
            or any(item.get("scope") not in contract["allowedClaimScopes"] for item in references)
            or not _outline_scope_families(theme).issubset(
                {_scope_family(item.get("scope")) for item in references})):
        raise TopicSelectionError("nonproduct_evidence_incomplete")
    related = [article for article in catalog.get("articles", [])
               if article.get("status") == "published" and article.get("slug") != theme.get("slug")]
    related.sort(key=lambda article: article.get("categoryId") != theme.get("categoryId"))
    return {"theme": theme, "catalog": [], "products": [], "productIds": [],
            "existingArticles": [{key: article.get(key) for key in
                ("title", "slug", "categoryId", "excerpt")} for article in related[:5]],
            "categories": [category for category in catalog.get("categories", [])
                           if category.get("id") == theme.get("categoryId")],
            "merchantClicks": [], "references": references, "images": images,
            "checks": {"facts": True, "images": False, "affiliate": "not_applicable"},
            "commercialRoute": {"status": "not_applicable", "reason": "productIds_empty_verified_nonproduct"},
            "evidence": {"publicSources": references, "ownedIllustrations": images}, "blocked": False}


EDITORIAL_CONTEXT_FIELDS = {"schemaVersion", "articleType", "sourceApplicability",
                            "commerceApplicability", "imageApplicability", "sourceIds",
                            "sourceReceiptSha256", "imageProofIds"}


def editorial_context(theme, images=None):
    contract = theme.get("nonProductContract") if isinstance(theme, dict) else None
    if not isinstance(contract, dict):
        raise TopicSelectionError("nonproduct_contract_required")
    return {
        "schemaVersion": 1,
        "articleType": "nonproduct",
        "sourceApplicability": "verified_public_references",
        "commerceApplicability": "not_applicable",
        "imageApplicability": "owned_illustration",
        "sourceIds": [item["id"] for item in contract["references"]],
        "sourceReceiptSha256": contract["sourceReceiptSha256"],
        "imageProofIds": [item["id"] for item in (images if images is not None else contract["images"])],
    }


def validate_nonproduct_bundle(bundle):
    """Return the bound context or fail; empty products alone grant nothing."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get("article"), dict):
        raise TopicSelectionError("nonproduct_bundle_required")
    article = bundle["article"]
    context = (article.get("generationMeta") or {}).get("editorialContext")
    if (not isinstance(context, dict) or set(context) != EDITORIAL_CONTEXT_FIELDS
            or context.get("schemaVersion") != 1 or context.get("articleType") != "nonproduct"
            or context.get("sourceApplicability") != "verified_public_references"
            or context.get("commerceApplicability") != "not_applicable"
            or context.get("imageApplicability") != "owned_illustration"
            or article.get("productIds") != [] or bundle.get("products") != []):
        raise TopicSelectionError("nonproduct_editorial_context_invalid")
    references = bundle.get("references")
    images = bundle.get("images")
    if not isinstance(references, list) or not references:
        raise TopicSelectionError("nonproduct_source_binding_invalid")
    for item in references:
        validate_public_reference(item)
    if len({item['id'] for item in references}) != len(references):
        raise TopicSelectionError("nonproduct_source_binding_invalid")
    fit = any(r['scope'] == 'thermos-parts-fit-example' for r in references)
    if fit:
        effective_scopes = allowed_claim_scopes({'title': article.get('title', ''),
            'sourceIds': [r['id'] for r in references], 'outline': []})
        if (not effective_scopes or any(r['scope'] not in effective_scopes for r in references)):
            raise TopicSelectionError("nonproduct_claim_scope_mismatch")
    if (not isinstance(references, list) or not references or
            [item.get("id") for item in references] != context["sourceIds"]
            or context["sourceReceiptSha256"] !=
            _sha(_canonical([item.get("receiptSha256") for item in references]))):
        raise TopicSelectionError("nonproduct_source_binding_invalid")
    for item in references:
        validate_public_reference(item)
        receipt = {key: item.get(key) for key in
                   ("id", "url", "canonicalUrl", "checkedAt", "httpStatus", "excerpt", "claimScope")}
        checked = _aware(item.get("checkedAt"))
        raw_id = str(item.get("id", "")).removeprefix("public:")
        receipt["id"] = raw_id
        if (item.get("url") not in PUBLIC_SOURCE_ALLOWLIST
                or item.get("canonicalUrl") != item.get("url") or item.get("httpStatus") != 200
                or checked is None or item.get("kind") != "public-primary"
                or item.get("scope") != PUBLIC_SOURCE_ALLOWLIST[item.get("url")]
                or item.get("claimScope") != item.get("scope")
                or item.get("id") != "public:" + SOURCE_IDS[item.get("url")]
                or item.get("excerptSha256") != _sha(str(item.get("excerpt", "")))
                or item.get("receiptSha256") != _sha(_canonical(receipt))):
            raise TopicSelectionError("nonproduct_reference_receipt_invalid")
    bound_images = [item for item in images or [] if item.get("id") in context["imageProofIds"]]
    if (len(bound_images) != len(context["imageProofIds"]) or not bound_images
            or any(item.get("verified") is not True
                   or item.get("role") != "eyecatch" or item.get("contentType") != "image/png"
                   or item.get("width") != 1200 or item.get("height") != 630
                   or item.get("ownership") != "owned_editorial_illustration"
                   or item.get("depictsRealProduct") is not False
                   or _aware(item.get("checkedAt")) is None
                   or item.get("referenceIds") != context["sourceIds"]
                   or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("compositionSha256", "")))
                   or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", "")))
                   or not isinstance(item.get("size"), int) or not 0 < item["size"] <= 2 * 1024 * 1024
                   for item in bound_images)):
        raise TopicSelectionError("nonproduct_image_binding_invalid")
    if article.get("eyecatch") != bound_images[0].get("url") or len(bound_images) != 1:
        raise TopicSelectionError("nonproduct_eyecatch_binding_invalid")
    if fit:
        image = bound_images[0]
        renderer = image.get('rendererEvidence')
        if (not isinstance(renderer, dict) or renderer.get('passed') is not True or
                renderer.get('evidencePassed') is not True or renderer.get('networkRequests') != 0 or
                renderer.get('sourceIds') != context['sourceIds'] or
                renderer.get('sourceReceiptSha256') != context['sourceReceiptSha256'] or
                renderer.get('contentHash') != image['compositionSha256'] or
                renderer.get('pngSha256') != image['sha256']):
            raise TopicSelectionError("nonproduct_image_binding_invalid")
    route = bundle.get("commercialRoute")
    expected = {"status": "not_applicable", "reason": "verified_nonproduct_article",
                "verifiedBy": "deterministic_contract_v1"}
    if route != expected:
        raise TopicSelectionError("nonproduct_commercial_route_invalid")
    prose = str(article.get("content", "")) + "\n" + _canonical(article.get("faqs", []))
    if (re.search(r"\{\{(?:product|comparison|ranking|price):", prose)
            or re.search(r"https?://[^\s)\]<>]*(?:amazon\.|rakuten\.|hb\.afl\.|shopping\.yahoo)", prose, re.I)
            or bundle.get("purchaseEvidence") not in (None, [])
            or "affiliateConfig" in bundle):
        raise TopicSelectionError("nonproduct_hidden_commerce_route")
    return context


def nonproduct_affiliate_review(bundle):
    validate_nonproduct_bundle(bundle)
    return {"applicability": "not_applicable", "measured": False,
            "provenanceFingerprint": _sha(_canonical(bundle["commercialRoute"]))}
