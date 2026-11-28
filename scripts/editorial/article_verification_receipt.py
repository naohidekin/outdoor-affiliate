"""Bounded program proof for one exact article revision; no model decisions."""
import copy
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from ledger import canonical, fingerprint


SCHEMA_VERSION = 1
KIND = "article_verification_receipt_v1"
MAX_RECEIPT_BYTES = 64 * 1024
MAX_PROJECTION_BYTES = 12 * 1024
SITE = "https://camp-gear-lab.com"
LINK = re.compile(r"(?<!!)\[([^\]\n]{1,160})\]\((/articles/([a-z0-9][a-z0-9-]*))(?:\s+[\"'][^\"']*[\"'])?\)")


def require(value, reason):
    if not value:
        raise ValueError("article_verification_receipt_" + reason)


def _unknown_availability(value):
    if value is None: return True
    return isinstance(value, str) and value.strip().casefold() in {
        "", "unknown", "不明", "未確認", "未確認です", "記載なし", "n/a"}


def _normalized(value):
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        result.pop("checkedAt", None)
        for key, item in list(result.items()): result[key] = _normalized(item)
    elif isinstance(result, list):
        result = [_normalized(item) for item in result]
    return result


class _PublicPage(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.title = ""; self.description = ""; self.canonical = ""; self.headings = []
        self._title = False; self._heading = None; self._title_parts = []; self._heading_parts = []
        self.feed(raw)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title": self._title = True; self._title_parts = []
        if tag in ("h1", "h2", "h3"): self._heading = tag; self._heading_parts = []
        if tag == "meta" and attrs.get("name", "").casefold() == "description":
            self.description = attrs.get("content", "").strip()
        if tag == "link" and attrs.get("rel", "").casefold() == "canonical":
            self.canonical = attrs.get("href", "").strip()

    def handle_data(self, data):
        if self._title: self._title_parts.append(data)
        if self._heading: self._heading_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "title" and self._title:
            self.title = re.sub(r"\s+", " ", "".join(self._title_parts)).strip()[:300]
            self._title = False
        if tag == self._heading:
            text = re.sub(r"\s+", " ", "".join(self._heading_parts)).strip()
            if text and len(self.headings) < 8: self.headings.append(text[:200])
            self._heading = None


def _internal_targets(content, request):
    found = []
    for match in LINK.finditer(content or ""):
        item = {"anchor": match[1], "path": match[2], "slug": match[3]}
        if item not in found: found.append(item)
    require(len(found) <= 3, "internal_link_limit")
    result = []
    for item in found:
        expected = SITE + item["path"]
        response = request(expected, {"Accept": "text/html", "Cache-Control": "no-cache"},
                           allowed_domains=["camp-gear-lab.com"], exact_domains=True)
        require(response.get("status") == 200 and response.get("url") == expected,
                "internal_link_readback")
        body = response.get("body")
        require(isinstance(body, bytes) and body, "internal_link_readback")
        content_type = response.get("headers", {}).get("content-type", "").split(";")[0].lower()
        require(content_type == "text/html", "internal_link_content_type")
        try: page = _PublicPage(body.decode("utf-8"))
        except UnicodeError: raise ValueError("article_verification_receipt_internal_link_encoding") from None
        require(page.title and page.description and page.headings, "internal_link_semantic_evidence")
        if page.canonical:
            require(page.canonical.rstrip("/") == expected, "internal_link_canonical")
        result.append({**item, "url": expected, "status": 200, "finalUrl": response["url"],
                       "bodySha256": hashlib.sha256(body).hexdigest(), "title": page.title,
                       "excerpt": page.description[:500], "headings": page.headings})
    return result


def _social_card(bundle):
    article = bundle.get("article") or {}; manifest = (article.get("generationMeta") or {}).get("socialCard")
    cards = [item for item in bundle.get("images", [])
             if isinstance(item, dict) and item.get("role") == "social-card"]
    if manifest is None and not cards:
        return {"status": "not_present"}
    require(isinstance(manifest, dict) and len(cards) == 1 and cards[0].get("verified") is True,
            "social_card")
    for field in ("url", "sha256", "size", "contentType", "width", "height"):
        require(manifest.get(field) == cards[0].get(field), "social_card")
    evidence = manifest.get("rendererEvidence")
    require(isinstance(evidence, dict) and isinstance(evidence.get("displayText"), dict)
            and isinstance(evidence.get("sourceCrops"), list), "social_card_renderer")
    from social_cards import _heading
    shown = evidence["displayText"]
    require(isinstance(article.get("title"), str) and article["title"]
            and shown.get("title") == article["title"]
            and shown.get("heading") == _heading(article["title"])
            and shown.get("brand") == "Camp Gear Lab"
            and isinstance(shown.get("label"), str), "social_card_text")
    sources = [{key: copy.deepcopy(item.get(key)) for key in ("productId", "sha256")}
               for item in manifest.get("sources", []) if isinstance(item, dict)]
    crops = [{key: copy.deepcopy(item.get(key)) for key in
              ("productId", "sha256", "displaySha256", "originalWidth", "originalHeight")}
             for item in evidence["sourceCrops"] if isinstance(item, dict)]
    require(sources and crops and {item["productId"] for item in sources} ==
            {item["productId"] for item in crops}, "social_card_sources")
    display = {key: copy.deepcopy(evidence["displayText"].get(key))
               for key in ("title", "heading", "productNames", "label", "brand")}
    return {"sha256": manifest["sha256"], "size": manifest["size"],
            "contentType": manifest["contentType"], "width": manifest["width"],
            "height": manifest["height"], "templateVersion": manifest.get("templateVersion"),
            "sources": sources, "renderer": {"contentHash": evidence.get("contentHash"),
            "displayText": display, "sourceCrops": crops,
            "renderEngine": evidence.get("renderEngine")}}


def build(job, bundle, gathered, preview, medical, structural, source_dependencies, request):
    revision = fingerprint(bundle)
    require(job.get("id") and isinstance(preview, dict) and preview.get("passed") is True
            and preview.get("failures") == [] and isinstance(medical, dict)
            and medical.get("passed") is True and structural.get("passed") is True,
            "hard_checks")
    flags = gathered.get("checks") or {}
    require(all(flags.get(key) is True for key in ("facts", "images", "affiliate")), "source_flags")
    viewport = preview.get("viewportEvidence")
    presentation = preview.get("productPresentation")
    require(all(isinstance(viewport, dict) and isinstance(viewport.get(name), dict)
                and viewport[name].get("allAnchorsVerified") is True for name in ("desktop", "mobile")),
            "viewport_evidence")
    require(all(isinstance(presentation, dict) and isinstance(presentation.get(name), list)
                for name in ("desktop", "mobile")), "product_presentation")
    targets = _internal_targets(bundle["article"].get("content", ""), request)
    rendered_links = {link for name in ("desktop", "mobile")
                      for link in viewport[name].get("internalLinks", [])}
    require(all(item["path"] in rendered_links for item in targets), "internal_link_not_rendered")
    selected = [product for product in bundle.get("products", [])
                if product.get("id") in bundle["article"].get("productIds", [])]
    require(len(selected) == len(bundle["article"].get("productIds", [])) <= 11, "product_scope")
    image_proofs = []
    for product in selected:
        matches = [item for item in bundle.get("images", []) if isinstance(item, dict)
                   and item.get("productId") == product["id"] and item.get("url") == product.get("imageUrl")
                   and item.get("verified") is True]
        require(len(matches) == 1, "product_image_binding")
        image_proofs.append({"productId": product["id"], "url": matches[0]["url"],
                             "urlSha256": hashlib.sha256(matches[0]["url"].encode()).hexdigest(),
                             "sha256": matches[0].get("sha256"), "size": matches[0].get("size")})
    readback = [item for item in preview.get("imageReadback", []) if isinstance(item, dict)]
    for expected in image_proofs:
        require(any(item.get("url") == expected["url"] and item.get("sha256") == expected["sha256"]
                    and item.get("size") == expected["size"] and item.get("verified") is True
                    for item in readback), "image_readback")
    product_bindings = []
    destinations = {}
    for product in selected:
        channels = []
        for channel, field in (("rakuten", "affiliateUrl"), ("amazon", "amazonUrl"), ("yahoo", "yahooUrl")):
            value = product.get(field)
            if isinstance(value, str) and value.startswith("https://"):
                channels.append(channel); destinations[(product["id"], channel)] = value
        product_bindings.append({"productId": product["id"], "name": product.get("name"),
            "price": product.get("price"),
            "rating": product.get("rating"), "availability": product.get("availability"),
            "imageUrlSha256": next(item["urlSha256"] for item in image_proofs
                                   if item["productId"] == product["id"]),
            "imageSha256": next(item["sha256"] for item in image_proofs
                                if item["productId"] == product["id"]), "channels": channels})
    affiliate_views = {}
    for name in ("desktop", "mobile"):
        raw = preview.get("clicksVerified", {}).get(name, [])
        require(isinstance(raw, list), "affiliate_clicks")
        observed = []
        for item in raw:
            key = (item.get("productId"), item.get("store")) if isinstance(item, dict) else None
            require(key in destinations and item.get("href") == destinations[key]
                    and isinstance(item.get("placement"), str) and item["placement"], "affiliate_click_binding")
            observed.append({"productId": key[0], "channel": key[1], "placement": item["placement"]})
        require(set(destinations) == {(item["productId"], item["channel"]) for item in observed},
                "affiliate_channel_coverage")
        bindings = sorted({(item["productId"], item["channel"], item["placement"]) for item in observed})
        affiliate_views[name] = {"count": len(raw),
            "bindings": [{"productId": item[0], "channel": item[1], "placement": item[2]}
                         for item in bindings],
            "destinationObservationsSha256": fingerprint(raw)}
    target_paths = {item["path"] for item in targets}
    receipt = {"schemaVersion": SCHEMA_VERSION, "kind": KIND, "jobId": job["id"],
               "revision": revision, "bundleSha256": revision,
               "sourceDependenciesSha256": fingerprint(source_dependencies),
               "productBindings": product_bindings,
               "checks": {"facts": {"passed": True}, "images": {"passed": True,
                   "readback": [{key: item[key] for key in ("productId", "urlSha256", "sha256", "size")}
                                for item in image_proofs], "socialCard": _social_card(bundle)},
                   "affiliate": {"passed": True, "viewports": affiliate_views},
                   "medical": {"passed": True, "riskCount": len(medical.get("risks", [])),
                               "scope": medical.get("scope")},
                   "render": {"passed": True, "previewSha256": fingerprint(preview),
                              "viewports": {name: {"internalLinks": [path for path in
                                  viewport[name].get("internalLinks", []) if path in target_paths],
                                  "allAnchorsVerified": True,
                                  "productPresentation": copy.deepcopy(presentation[name])}
                                            for name in ("desktop", "mobile")}}},
               "internalTargets": targets}
    validate(receipt, job["id"], revision)
    return receipt


def validate(receipt, job_id, revision):
    require(isinstance(receipt, dict) and receipt.get("schemaVersion") == SCHEMA_VERSION
            and receipt.get("kind") == KIND and receipt.get("jobId") == job_id
            and receipt.get("revision") == revision and receipt.get("bundleSha256") == revision,
            "binding")
    checks = receipt.get("checks")
    require(isinstance(checks, dict) and set(checks) ==
            {"facts", "images", "affiliate", "medical", "render"}
            and all(isinstance(checks[key], dict) and checks[key].get("passed") is True
                    for key in checks), "checks")
    require(re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("sourceDependenciesSha256", ""))),
            "source_hash")
    products = receipt.get("productBindings")
    require(isinstance(products, list) and len(products) <= 11
            and len({item.get("productId") for item in products if isinstance(item, dict)}) == len(products),
            "product_bindings")
    expected_ids = {item["productId"] for item in products}
    for item in products:
        require(set(item) == {"productId", "name", "price", "rating", "availability",
                              "imageUrlSha256", "imageSha256", "channels"}
                and isinstance(item["name"], str) and item["name"]
                and isinstance(item["channels"], list) and len(item["channels"]) == len(set(item["channels"]))
                and all(channel in ("rakuten", "amazon", "yahoo") for channel in item["channels"])
                and re.fullmatch(r"[a-f0-9]{64}", str(item["imageSha256"]))
                and re.fullmatch(r"[a-f0-9]{64}", str(item["imageUrlSha256"])), "product_bindings")
    image_rows = checks["images"].get("readback")
    require(isinstance(image_rows, list) and {item.get("productId") for item in image_rows} == expected_ids
            and all(re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", "")))
                    and re.fullmatch(r"[a-f0-9]{64}", str(item.get("urlSha256", "")))
                    and type(item.get("size")) is int and item["size"] > 0 for item in image_rows),
            "image_readback")
    require(all(next(row for row in image_rows if row["productId"] == item["productId"])["sha256"]
                == item["imageSha256"]
                and next(row for row in image_rows if row["productId"] == item["productId"])["urlSha256"]
                == item["imageUrlSha256"] for item in products), "image_binding")
    card = checks["images"].get("socialCard")
    if card != {"status": "not_present"}:
        require(isinstance(card, dict) and card.get("width") == 1200 and card.get("height") == 630
                and card.get("contentType") == "image/png" and re.fullmatch(
                    r"[a-f0-9]{64}", str(card.get("sha256", ""))), "social_card")
        sources = card.get("sources"); renderer = card.get("renderer") or {}; crops = renderer.get("sourceCrops")
        by_id = {item["productId"]: item for item in products}
        require(isinstance(sources, list) and 1 <= len(sources) <= 2
                and len({item.get("productId") for item in sources}) == len(sources)
                and all(item.get("productId") in by_id and item.get("sha256") ==
                        by_id[item["productId"]]["imageSha256"] for item in sources)
                and isinstance(crops, list) and len(crops) == len(sources)
                and [item.get("productId") for item in crops] ==
                [item.get("productId") for item in sources]
                and all(crop.get("sha256") == source.get("sha256") ==
                        by_id[source["productId"]]["imageSha256"]
                        and re.fullmatch(r"[a-f0-9]{64}", str(crop.get("displaySha256", "")))
                        and type(crop.get("originalWidth")) is int and crop["originalWidth"] > 0
                        and type(crop.get("originalHeight")) is int and crop["originalHeight"] > 0
                        for source, crop in zip(sources, crops)), "social_card_sources")
        display = renderer.get("displayText")
        expected_names = [by_id[item["productId"]]["name"] for item in sources]
        require(isinstance(display, dict) and set(display) ==
                {"title", "heading", "productNames", "label", "brand"}
                and display.get("productNames") == expected_names
                and all(isinstance(display.get(key), str) and display[key]
                        for key in ("title", "heading"))
                and display.get("brand") == "Camp Gear Lab"
                and isinstance(display.get("label"), str)
                and re.fullmatch(r"[a-f0-9]{64}", str(renderer.get("contentHash", "")))
                and isinstance(renderer.get("renderEngine"), str) and renderer["renderEngine"],
                "social_card_text")
    expected_channels = {(item["productId"], channel) for item in products for channel in item["channels"]}
    affiliate_views = checks["affiliate"].get("viewports")
    render_views = checks["render"].get("viewports")
    require(set(affiliate_views or {}) == {"desktop", "mobile"}
            and set(render_views or {}) == {"desktop", "mobile"}
            and re.fullmatch(r"[a-f0-9]{64}", str(checks["render"].get("previewSha256", ""))),
            "viewport_bindings")
    for name in ("desktop", "mobile"):
        affiliate = affiliate_views[name]; bindings = affiliate.get("bindings")
        require(type(affiliate.get("count")) is int and affiliate["count"] >= len(expected_channels)
                and re.fullmatch(r"[a-f0-9]{64}", str(affiliate.get("destinationObservationsSha256", "")))
                and {(item.get("productId"), item.get("channel")) for item in bindings or []}
                == expected_channels, "affiliate_channel_coverage")
        view = render_views[name]; presentation = view.get("productPresentation")
        require(view.get("allAnchorsVerified") is True and isinstance(view.get("internalLinks"), list)
                and isinstance(presentation, list) and len(presentation) == len(products)
                and {item.get("productId") for item in presentation} == expected_ids,
                "render_presentation")
        by_id = {item["productId"]: item for item in products}
        for item in presentation:
            expected = by_id[item["productId"]]
            require(item.get("componentCount", 0) >= 1 and item.get("priceInput") == expected["price"]
                    and item.get("ratingInput") == expected["rating"]
                    and item.get("availabilityInput") == expected["availability"], "render_product_binding")
            if not (isinstance(expected["price"], (int, float)) and expected["price"] > 0):
                require(item.get("merchantCheckDisplayed") is True
                        and item.get("zeroPriceDisplayed") is False, "render_zero_price")
            if not (isinstance(expected["rating"], (int, float)) and expected["rating"] > 0):
                require(item.get("ratingClaimDisplayed") is False, "render_zero_rating")
            if _unknown_availability(expected["availability"]):
                require(item.get("availabilityClaimDisplayed") is False, "render_unknown_stock")
    require(checks["medical"].get("riskCount") == 0, "medical")
    targets = receipt.get("internalTargets")
    require(isinstance(targets, list) and len(targets) <= 3
            and all(item.get("status") == 200 and item.get("url") == item.get("finalUrl")
                    and re.fullmatch(r"[a-f0-9]{64}", str(item.get("bodySha256", "")))
                    and item.get("title") and item.get("excerpt") and item.get("headings")
                    for item in targets), "internal_targets")
    encoded = canonical(receipt).encode()
    require(len(encoded) <= MAX_RECEIPT_BYTES, "too_large")
    return copy.deepcopy(receipt)


def projection(receipt, job_id, revision):
    value = validate(receipt, job_id, revision)
    checks = value["checks"]
    render_views = {}
    for name in ("desktop", "mobile"):
        view = checks["render"]["viewports"][name]
        presentation = view["productPresentation"]
        render_views[name] = {
            "verifiedProductIds": [item["productId"] for item in presentation],
            "count": len(presentation),
            "presentationSha256": fingerprint(presentation),
            "unknownValuesPassed": True,
            "allAnchorsVerified": view["allAnchorsVerified"],
            "internalLinks": copy.deepcopy(view["internalLinks"]),
        }
    public_checks = {
        "facts": copy.deepcopy(checks["facts"]),
        "images": compact_images_projection(checks["images"]),
        "affiliate": compact_affiliate_projection(checks["affiliate"]),
        "medical": copy.deepcopy(checks["medical"]),
        "render": {"passed": True, "previewSha256": checks["render"]["previewSha256"],
                   "viewports": render_views},
    }
    result = {"schemaVersion": value["schemaVersion"], "kind": value["kind"],
            "jobId": value["jobId"], "revision": value["revision"],
            "bundleSha256": value["bundleSha256"],
            "sourceDependenciesSha256": value["sourceDependenciesSha256"],
            "checks": public_checks,
            "internalTargets": copy.deepcopy(value["internalTargets"]),
            "receiptSha256": fingerprint(value)}
    require(len(canonical(result).encode()) <= MAX_PROJECTION_BYTES, "projection_too_large")
    return result


def compact_affiliate_projection(affiliate):
    columns = ["productId", "channel", "placement"]
    rows, lookup, viewports = [], {}, {}
    for name in ("desktop", "mobile"):
        source = affiliate["viewports"][name]
        indices = []
        for binding in source["bindings"]:
            row = tuple(binding[column] for column in columns)
            if row not in lookup:
                lookup[row] = len(rows); rows.append(list(row))
            indices.append(lookup[row])
        viewports[name] = {"count": source["count"], "bindingIndices": indices,
            "destinationObservationsSha256": source["destinationObservationsSha256"]}
    dictionaries = {column: [] for column in columns}
    dictionary_indices = {column: {} for column in columns}
    encoded_rows = []
    for row in rows:
        encoded = []
        for column, value in zip(columns, row):
            if value not in dictionary_indices[column]:
                dictionary_indices[column][value] = len(dictionaries[column])
                dictionaries[column].append(value)
            encoded.append(dictionary_indices[column][value])
        encoded_rows.append(encoded)
    return {"passed": True, "encoding": "column-dictionary-indices-v1",
            "bindingColumns": columns, "bindingDictionaries": dictionaries,
            "bindingRows": encoded_rows, "viewports": viewports}


def compact_images_projection(images):
    columns = ["productId", "urlSha256", "sha256", "size"]
    return {"passed": True, "readbackColumns": columns,
            "readbackRows": [[item[column] for column in columns]
                             for item in images["readback"]],
            "socialCard": copy.deepcopy(images["socialCard"])}


def expand_affiliate_projection(projected):
    columns = projected.get("bindingColumns"); rows = projected.get("bindingRows")
    dictionaries = projected.get("bindingDictionaries")
    require(projected.get("encoding") == "column-dictionary-indices-v1"
            and columns == ["productId", "channel", "placement"]
            and isinstance(dictionaries, dict) and set(dictionaries) == set(columns)
            and all(isinstance(dictionaries[column], list)
                    and all(isinstance(value, str) and value for value in dictionaries[column])
                    and len(dictionaries[column]) == len(set(dictionaries[column]))
                    for column in columns)
            and isinstance(rows, list) and all(isinstance(row, list) and len(row) == len(columns)
                    and all(type(index) is int and 0 <= index < len(dictionaries[column])
                            for column, index in zip(columns, row)) for row in rows),
            "affiliate_projection_encoding")
    decoded = [[dictionaries[column][index] for column, index in zip(columns, row)]
               for row in rows]
    viewports = projected.get("viewports")
    require(isinstance(viewports, dict) and set(viewports) == {"desktop", "mobile"}
            and all(isinstance(value.get("bindingIndices"), list)
                    and all(type(index) is int and 0 <= index < len(decoded)
                            for index in value["bindingIndices"])
                    for value in viewports.values()), "affiliate_projection_encoding")
    return {"passed": projected["passed"], "viewports": {name: {
        "count": value["count"],
        "bindings": [dict(zip(columns, decoded[index])) for index in value["bindingIndices"]],
        "destinationObservationsSha256": value["destinationObservationsSha256"]}
        for name, value in viewports.items()}}


def expand_images_projection(projected):
    columns = projected["readbackColumns"]
    return {"passed": projected["passed"],
            "readback": [dict(zip(columns, row)) for row in projected["readbackRows"]],
            "socialCard": copy.deepcopy(projected["socialCard"])}


def write_once(path, receipt):
    path = Path(path); raw = canonical(receipt).encode()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        require(not path.is_symlink() and path.read_bytes() == raw, "immutable_changed")
        return fingerprint(receipt)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return fingerprint(receipt)


def write_source_once(path, source):
    path = Path(path); raw = canonical(source).encode()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        require(not path.is_symlink() and path.read_bytes() == raw, "source_immutable_changed")
        return fingerprint(source)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return fingerprint(source)


def load_source(path, expected_sha, bundle):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "source_missing")
    source = json.loads(path.read_bytes())
    require(fingerprint(source) == expected_sha, "source_hash")
    raw = source.get("normalizedSource")
    require(isinstance(raw, dict), "normalized_source")
    selected = set((bundle.get("article") or {}).get("productIds", []))
    products = source.get("products"); raw_products = raw.get("products", raw.get("catalog"))
    require(isinstance(products, list) and isinstance(raw_products, list), "source_products")
    bundle_products = [item for item in bundle.get("products", []) if item.get("id") in selected]
    copied_products = [item for item in products if item.get("id") in selected]
    gathered_products = [item for item in raw_products if item.get("id") in selected]
    require(len(bundle_products) == len(copied_products) == len(gathered_products) == len(selected)
            and [_normalized(item) for item in bundle_products] ==
            [_normalized(item) for item in copied_products] ==
            [_normalized(item) for item in gathered_products], "source_products")
    copied_references = source.get("references"); raw_references = raw.get("references")
    require(isinstance(copied_references, list) and isinstance(raw_references, list)
            and _normalized(bundle.get("references", [])) == _normalized(copied_references)
            == _normalized(raw_references), "source_references")
    bundle_images = [item for item in bundle.get("images", []) if item.get("productId") in selected]
    copied_images = [item for item in source.get("images", []) if item.get("productId") in selected]
    raw_images = raw.get("images")
    require(isinstance(raw_images, list), "source_images")
    gathered_images = [item for item in raw_images if item.get("productId") in selected]
    require(_normalized(bundle_images) == _normalized(copied_images) ==
            _normalized(gathered_images), "source_images")
    return source


def load(path, job_id, revision, expected_sha):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "missing")
    value = json.loads(path.read_bytes())
    require(fingerprint(value) == expected_sha, "hash")
    return validate(value, job_id, revision)
