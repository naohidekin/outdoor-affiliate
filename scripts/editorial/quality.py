"""Dependency-free, offline checks; ``passed`` is NEVER publication approval.

Inputs are JSON-compatible objects, not paths. No network, model calls or writes.
The runner must resolve/check public DNS and redirects before fetching images or
affiliate links; this module only rejects unsafe URL literals. Mandatory evidence
always stays pending: metadata and string preservation cannot certify truth.

Optional bundle fields:
  affiliateConfig.amazonPartnerTag: expected tag, supplied by the runner from
    AMAZON_PARTNER_TAG (no hard-coded account fallback).
  purchaseEvidence: [{productId, channel: amazon|rakuten|yahoo, status: NA,
    reason, checkedAt: timezone-aware ISO timestamp, reviewedBy}].
  products[].yahooAvailable: true requires yahooUrl or matching NA evidence.
Missing Amazon/Rakuten destinations require NA evidence; at least one usable
purchase destination remains necessary. Remove an unsuitable product from the
article AND its shortcodes rather than fabricating a link or evidence.
"""
import ipaddress
import os
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit


BRIEF_FIELDS = ("purpose", "reader", "conclusion", "headings", "facts", "numbers",
                "links", "requiredExpressions", "protected", "style", "length", "cta", "format")
SHORTCODE = re.compile(r"\{\{(product|comparison|ranking):([^{}]*)\}\}")
SITE_HOSTS = {"camp-gear-lab.com", "www.camp-gear-lab.com"}
HEADING_PREFIX = r"(?:(?: {0,3}>[ \t]?)|(?: {0,3}(?:[-+*]|[0-9]+[.)])[ \t]+))* {0,3}"


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _checked(value):
    if not _text(value):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.tzinfo is not None and stamp.utcoffset() is not None
    except ValueError:
        return False


def _url_error(value, relative=False):
    """Validate literal URLs only. DNS/redirect safety belongs to the runner."""
    if not _text(value) or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return "empty, whitespace, control character or backslash"
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return "malformed percent encoding"
    try:
        p = urlsplit(value)
        if relative and not p.scheme and not p.netloc:
            if value.startswith("//") or ":" in value.split("/")[0] or re.match(r"(?:www\.|(?:https?|htps|hhttps)\/)", value, re.I):
                return "invalid relative destination"
            return None
        if p.scheme not in ("http", "https") or not p.netloc:
            return "http/https absolute URL required"
        host = p.hostname
        if not host or p.username is not None or p.password is not None:
            return "missing host or credentials in URL"
        if p.port is not None and not 1 <= p.port <= 65535:
            return "invalid port"
        host = host.lower().rstrip(".")
        if "%" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid")):
            return "local or invalid hostname"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # Reject inet_aton aliases (127.1, decimal/octal/hex IPv4).
            if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host):
                return "ambiguous numeric address"
            ascii_host = host.encode("idna").decode("ascii")
            if "." not in ascii_host or len(ascii_host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in ascii_host.split(".")
            ):
                return "invalid public hostname"
        else:
            if not address.is_global or (getattr(address, "ipv4_mapped", None) and not address.ipv4_mapped.is_global):
                return "non-public IP address"
    except (ValueError, UnicodeError):
        return "malformed URL"
    return None


def _destinations(text):
    """Return (offset, destination) for inline/reference/HTML/autolinks.

    Balanced parentheses and escaped characters in inline destinations are
    handled explicitly; a regex ending at the first ')' loses URL suffixes.
    Reference definitions are also protected separately by inspect_polish.
    """
    result = []
    for m in re.finditer(r"\]\(", text):
        start = m.end()
        while start < len(text) and text[start].isspace():
            start += 1
        if start < len(text) and text[start] == "<":
            end = text.find(">", start + 1)
            if end >= 0:
                result.append((start, text[start + 1:end]))
            continue
        end, depth = start, 0
        while end < len(text):
            char = text[end]
            if char == "\\" and end + 1 < len(text):
                end += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            elif char.isspace() and depth == 0:
                break
            end += 1
        result.append((start, text[start:end]))
    for m in re.finditer(r"(?m)^ {0,3}\[[^\]\n]+\]:[ \t]*(?:<([^>\n]+)>|(\S+))", text):
        result.append((m.start(), m.group(1) or m.group(2)))
    for m in re.finditer(r"\b(?:href|src)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", text, re.I):
        result.append((m.start(), next(g for g in m.groups() if g is not None)))
    for m in re.finditer(r"<((?:https?://|mailto:)[^<>\s]+)>", text, re.I):
        result.append((m.start(), m.group(1)))
    return sorted(result)


def _reference_uses(text, include_images=True):
    definitions = {}
    for m in re.finditer(r"(?m)^ {0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|(\S+))", text):
        definitions[" ".join(m.group(1).lower().split())] = m.group(2) or m.group(3)
    uses = []
    pattern = r"!?\[([^\]\n]+)\](?:\[([^\]\n]*)\])?"
    for m in re.finditer(pattern, text):
        if not include_images and m.group().startswith("!"):
            continue
        if text[m.end():m.end() + 1] in ("(", ":"):
            continue
        key = " ".join((m.group(2) or m.group(1)).lower().split())
        if key in definitions:
            uses.append((m.start(), definitions[key]))
    return uses


def _article_links(text):
    links = list(_reference_uses(text, include_images=False))
    for offset, dest in _destinations(text):
        # Destination offsets follow ]( and optional whitespace, never ![...](.
        if re.search(r"(?<!!)\[[^\]\n]+\]\(\s*$", text[:offset]):
            links.append((offset, dest))
    return sorted(links)


def _without_code(text):
    return _code_pattern().sub("", text)


def _code_pattern():
    return re.compile(r"(?m)^ {0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^ {0,3}\1[ \t]*(?=\n|$)|\Z)"
                      r"|^(?:(?: {4}|\t)[^\n]*(?:\n|$))+|(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\2(?!`)"
                      r"|<pre\b[^>]*>[\s\S]*?</pre\s*>|<code\b[^>]*>[\s\S]*?</code\s*>", re.I)


def _headings(text):
    pattern = re.compile(r"(?m)^" + HEADING_PREFIX + r"#{1,6}(?:[ \t]+[^\n]*|[ \t]*)$"
                         r"|^ {0,3}\S[^\n]*\n {0,3}(?:=+|-+)[ \t]*$"
                         r"|<h[1-6]\b[^>]*>[\s\S]*?</h[1-6]\s*>", re.I)
    return list(pattern.finditer(text))


def _protected(text):
    tokens = []
    def collect(kind, pattern):
        for m in re.finditer(pattern, text, re.M | re.I):
            tokens.append((m.start(), kind, m.group()))
    for m in _headings(text):
        tokens.append((m.start(), "heading", m.group()))
    for m in _code_pattern().finditer(text):
        tokens.append((m.start(), "code", m.group()))
    collect("table", r"^[^\n]*\|[^\n]*$|<table\b[^>]*>[\s\S]*?</table\s*>")
    collect("shortcode", r"\{\{[\s\S]*?\}\}|::\w+\{[^\n]*\}")
    collect("product_id", r"\bproductIds?\b\s*[:=]\s*(?:\[[^\]\n]*\]|[^\s,;]+)")
    collect("number", r"[+−-]?[0-9０-９]+(?:[.,．，/：:〜～–-][0-9０-９]+)*(?:[ \t]*(?:[A-Za-z]+|℃|°C|%|％|万円|円|年|月|日|時間|分|秒|泊|人|名|個|台|選))?"
            r"|[〇零一二三四五六七八九十百千万億]+(?:円|年|月|日|時間|分|秒|泊|人|名|個|台|選)?")
    collect("url", r"[a-z][a-z0-9+.-]*://[^\s<>\"']+")
    collect("reference", r"^ {0,3}\[[^\]\n]+\]:[^\n]*$")
    # Protect entire disclosure lines, including lines containing HTML badges.
    collect("disclosure", r"^[^\n]*(?:広告|アフィリエイト|アソシエイト|スポンサー|プロモーション|提供[:：]|\bPR\b|\bsponsored\b|\baffiliate\b)[^\n]*$")
    for offset, destination in _destinations(text):
        tokens.append((offset, "link_destination", destination))
    for offset, destination in _reference_uses(text):
        tokens.append((offset, "reference_link_destination", destination))
    return [(kind, value) for _, kind, value in sorted(tokens)]


def inspect_polish(source, candidate):
    """Compare body strings, strictly retaining ordered protected tokens.

    Does not mutate source, apply a candidate, or establish semantic equivalence.
    A passing result still requires upper-model/human fact and meaning review.
    """
    failures = []
    if not _text(source) or not _text(candidate):
        failures.append("body_strings: source and candidate must be nonempty body strings")
    elif _protected(source) != _protected(candidate):
        failures.append("protected_content: headings/URLs/numbers/shortcodes/IDs/tables/code/disclosures/link destinations changed, reordered or removed")
    return {"passed": not failures, "failures": failures}


def _mandatory():
    return [{"kind": kind, "status": "pending", "owner": owner} for kind, owner in (
        ("fact_completeness_and_firsthand_experience", "upper_reviewer"),
        ("medical_legal_advertising_review", "upper_reviewer"),
        ("meaning_and_conclusion_preservation", "upper_reviewer"),
        ("render_and_image_identity", "main_runner_and_reviewer"),
        ("affiliate_live_destination_and_product_identity", "main_runner_and_reviewer"),
        ("public_dns_redirect_and_image_live_verification", "main_runner"),
        ("quality_scores_and_format_length", "upper_reviewer"),
        ("slack_article_version_approval", "human"),
    )]


def inspect_bundle(bundle):
    """Check structure and supplied evidence. ``passed`` covers offline checks only."""
    failures, warnings = [], []
    def fail(code, message):
        failures.append(f"{code}: {message}")
    def url(value, path, relative=False):
        error = _url_error(value, relative)
        if error:
            fail("url", f"{path}: {error}")
        return error is None

    result = {"passed": False, "failures": failures, "warnings": warnings,
              "mandatory_evidence": _mandatory()}
    if not isinstance(bundle, dict):
        fail("schema", "bundle must be an object")
        return result
    article = bundle.get("article")
    if not isinstance(article, dict):
        fail("schema", "article must be an object")
        return result
    for key in ("id", "slug", "title", "content", "excerpt", "categoryId", "author"):
        if not _text(article.get(key)):
            fail("article", f"{key} must be nonempty text")
    content = article.get("content") if isinstance(article.get("content"), str) else ""
    visible = _without_code(content)
    for m in _headings(visible):
        if re.match(HEADING_PREFIX + r"#(?:\s|$)|<h1\b", m.group(), re.I) or re.search(r"\n {0,3}=+[ \t]*$", m.group()):
            fail("h1", "body must start headings at H2")
    meta = article.get("metaDescription")
    if not _text(meta) or len(meta) > 160 or re.search(r"[\r\n<>]|\{\{", meta):
        fail("meta_description", "plain nonempty description of at most 160 characters required")
    faqs = article.get("faqs")
    if not isinstance(faqs, list) or not 3 <= len(faqs) <= 5:
        fail("faq", "3–5 FAQ entries required")
    elif any(not isinstance(f, dict) or not _text(f.get("question")) or not _text(f.get("answer")) for f in faqs):
        fail("faq", "every FAQ needs question and answer")

    brief = bundle.get("brief")
    if not isinstance(brief, dict):
        fail("brief", "writing specification required")
        brief = {}
    for key in BRIEF_FIELDS:
        value = brief.get(key)
        if key in ("headings", "facts", "numbers", "links", "requiredExpressions", "protected"):
            if not isinstance(value, list):
                fail("brief", f"{key} must be a list (empty means no confirmed entries)")
        elif not _text(value):
            fail("brief", f"{key} required")

    # Validate every structured URL, including source/eyecatch/evidence URLs.
    def walk(value, path="bundle"):
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}.{key}"
                if isinstance(key, str) and (key.lower().endswith("url") or key == "eyecatch") and item not in (None, "") and isinstance(item, str):
                    url(item, child)
                walk(item, child)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")
        elif isinstance(value, str):
            for _, dest in _destinations(value):
                url(dest, path, relative=True)
            for m in re.finditer(r"[a-z][a-z0-9+.-]*://[^\s<>\"')\]]+", value, re.I):
                url(m.group(), path)
    walk(bundle)

    # Only distinct, non-self article Markdown destinations count, never code/images.
    internal = set()
    for offset, dest in _article_links(visible):
        if _url_error(dest, relative=True):
            continue
        parsed = urlsplit(dest)
        if parsed.netloc and parsed.hostname not in SITE_HOSTS:
            continue
        if re.fullmatch(r"/articles/[^/]+/?", parsed.path) and parsed.path.rstrip("/") != f"/articles/{article.get('slug')}":
            internal.add(parsed.path.rstrip("/"))
    if not 2 <= len(internal) <= 3:
        fail("internal_links", "2–3 distinct other article destinations required")

    def records(key):
        value = bundle.get(key)
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            fail("schema", f"{key} must be a list of objects")
            return []
        return value
    products, images, references = records("products"), records("images"), records("references")
    product_map = {}
    for product in products:
        pid = product.get("id")
        if not _text(pid) or pid in product_map:
            fail("product", "unique nonempty product IDs required")
        else:
            product_map[pid] = product
    ids = article.get("productIds")
    if not isinstance(ids, list) or any(not _text(i) for i in ids):
        fail("product", "productIds must be a list of IDs")
        ids = []
    if len(set(ids)) != len(ids):
        fail("product", "duplicate productIds")
    selected = set(ids)
    used = set()
    for m in SHORTCODE.finditer(visible):
        tag_ids = [s.strip() for s in m.group(2).split(",")]
        if any(not s for s in tag_ids) or len(set(tag_ids)) != len(tag_ids) or (m.group(1) == "product" and len(tag_ids) != 1):
            fail("product", "malformed product shortcode")
        if m.group(1) == "product" and m.group(2) != tag_ids[0]:
            fail("product", "product card renderer requires exact ID without surrounding whitespace")
        used.update(tag_ids)
    if re.search(r"\{\{(?:product|comparison|ranking)\b", SHORTCODE.sub("", visible)):
        fail("product", "unparseable product shortcode")
    for pid in selected | used:
        if pid not in product_map:
            fail("product", f"unknown product ID {pid}")
    if used != selected:
        fail("product", "shortcode product IDs and article.productIds must agree")
    for count in re.findall(r"([0-9０-９]+)\s*選", str(article.get("title", ""))):
        if int(count) != len(selected):
            fail("selection", "title selection count disagrees with unique article products")
    if brief.get("format") in ("ranking", "comparison") and not any(m.group(1) == "comparison" for m in SHORTCODE.finditer(visible)):
        fail("comparison", "ranking/comparison needs comparison shortcode")

    if not references:
        fail("reference", "checked references required; presence does not prove completeness")
    for ref in references:
        url(ref.get("url"), "references.url")
        if not _checked(ref.get("checkedAt")):
            fail("reference", "checkedAt must include date, time and timezone")
    for image in images:
        url(image.get("url"), "images.url")
        if image.get("sha256") is not None and not re.fullmatch(r"[a-fA-F0-9]{64}", str(image["sha256"])):
            fail("image", "invalid sha256")

    evidence = bundle.get("purchaseEvidence", [])
    if not isinstance(evidence, list) or any(not isinstance(e, dict) for e in evidence):
        fail("purchase", "purchaseEvidence must be a list of objects")
        evidence = []
    def na(pid, channel):
        return any(e.get("productId") == pid and e.get("channel") == channel and e.get("status") == "NA"
                   and _text(e.get("reason")) and _checked(e.get("checkedAt")) and _text(e.get("reviewedBy")) for e in evidence)
    config = bundle.get("affiliateConfig", {})
    if not isinstance(config, dict):
        fail("affiliate", "affiliateConfig must be an object")
        config = {}
    expected_tag = config.get("amazonPartnerTag") or os.environ.get("AMAZON_PARTNER_TAG")
    if not expected_tag:
        warnings.append("amazon_tag: expected account tag not supplied; runner must bind AMAZON_PARTNER_TAG")

    for pid in sorted(product_map):
        product = product_map.get(pid)
        if product is None:
            continue
        image_url = product.get("imageUrl")
        url(image_url, f"product {pid}.imageUrl")
        if not any(i.get("productId") == pid and i.get("url") == image_url and i.get("verified") is True for i in images):
            fail("image", f"{pid}: matching runner verified image metadata required")
        usable = 0
        for channel, field in (("rakuten", "affiliateUrl"), ("amazon", "amazonUrl"), ("yahoo", "yahooUrl")):
            value = product.get(field)
            if value in (None, ""):
                if (channel != "yahoo" or product.get("yahooAvailable") is True) and not na(pid, channel):
                    fail("purchase", f"{pid}: missing {channel}; remove product or provide explicit NA evidence")
                continue
            if not url(value, f"product {pid}.{field}"):
                continue
            p = urlsplit(value)
            valid = True
            if channel == "rakuten":
                valid = p.scheme == "https" and p.hostname == "hb.afl.rakuten.co.jp" and bool(re.match(r"/ichiba/[^/]+/", p.path))
                for key in ("pc", "m"):
                    for target in parse_qs(p.query).get(key, []):
                        if not url(target, f"product {pid}.rakuten.{key}"):
                            valid = False
                        elif urlsplit(target).hostname not in ("item.rakuten.co.jp", "m.rakuten.co.jp", "product.rakuten.co.jp", "www.rakuten.co.jp", "search.rakuten.co.jp"):
                            valid = False
            elif channel == "amazon":
                match = re.fullmatch(r"/(?:[^/]+/)?(?:dp|gp/product)/([A-Z0-9]{10})/?", p.path)
                tags = parse_qs(p.query).get("tag", [])
                valid = p.scheme == "https" and p.hostname in ("amazon.co.jp", "www.amazon.co.jp") and bool(match)
                valid = valid and len(tags) == 1 and bool(re.fullmatch(r"[A-Za-z0-9_-]+-22", tags[0]))
                if expected_tag:
                    valid = valid and tags == [expected_tag]
                if product.get("asin") is not None:
                    valid = valid and bool(match) and product["asin"] == match.group(1)
            elif channel == "yahoo":
                valid = p.scheme == "https" and p.hostname in ("store.shopping.yahoo.co.jp", "shopping.yahoo.co.jp")
                if p.hostname == "ck.jp.ap.valuecommerce.com":
                    targets = parse_qs(p.query).get("vc_url", [])
                    valid = p.scheme == "https" and len(targets) == 1
                    for target in targets:
                        if not url(target, f"product {pid}.yahoo.vc_url"):
                            valid = False
                        elif urlsplit(target).hostname not in ("store.shopping.yahoo.co.jp", "shopping.yahoo.co.jp"):
                            valid = False
            if not valid:
                fail("affiliate", f"{pid}: invalid {channel} host/path/tag/ASIN identity")
            else:
                usable += 1
        if usable == 0:
            fail("purchase", f"{pid}: no usable purchase destination; remove product")
    warnings.append("offline_only: metadata is not proof of facts, image identity, live links or rendered output")
    result["passed"] = not failures
    return result
