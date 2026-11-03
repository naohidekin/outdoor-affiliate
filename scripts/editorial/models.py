"""Editorial model boundary: injected transport, strict JSON, no filesystem/env reads.

Context supplies catalog, references, images, CLAUDE and SKILL text (no paths are
opened). Review checks contain facts/images/affiliate/medical/render booleans.
Social requires publicReadback={verified: True, url, content, images} bound to the
bundle. These checks are supplied by independent verification, never by an LLM.
"""
import copy
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from quality import _protected, inspect_polish


CLAUDE_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
BRIEF_FIELDS = ("purpose", "reader", "conclusion", "headings", "facts", "numbers", "links",
                "requiredExpressions", "protected", "style", "length", "cta", "format", "externalSafe")
ARTICLE_FIELDS = ("slug", "title", "categoryId", "content", "excerpt", "metaDescription",
                  "faqs", "tags", "productIds", "author")
LIST_BRIEF_FIELDS = ("headings", "facts", "numbers", "links", "requiredExpressions", "protected")
WRITER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["article", "brief"],
    "properties": {
        "article": {"type": "object", "additionalProperties": False, "required": list(ARTICLE_FIELDS),
                    "properties": {**{field: {"type": "string"} for field in ARTICLE_FIELDS
                                      if field not in ("faqs", "tags", "productIds")},
                                   "faqs": {"type": "array", "items": {"type": "object",
                                               "additionalProperties": False, "required": ["question", "answer"],
                                               "properties": {"question": {"type": "string"}, "answer": {"type": "string"}}}},
                                   "tags": {"type": "array", "items": {"type": "string"}},
                                   "productIds": {"type": "array", "items": {"type": "string"}}}},
        "brief": {"type": "object", "additionalProperties": False, "required": list(BRIEF_FIELDS),
                  "properties": {**{field: {"type": "array", "items": {"type": "string"}}
                                    for field in LIST_BRIEF_FIELDS},
                                 **{field: {"type": "string"} for field in BRIEF_FIELDS
                                    if field not in LIST_BRIEF_FIELDS + ("externalSafe",)},
                                 "externalSafe": {"type": "boolean"}}}}
}
CATEGORIES = ("facts", "images", "affiliate", "medical", "render")
SECRET = re.compile(
    r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,}|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)"
    r"[\s\"']*[:=]\s*[\"']?[^\s\"',}]+|"
    r"authorization[\s\"']*[:=]|bearer\s+\S+|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]+|xox[baprs]-[\w-]+",
    re.IGNORECASE)


class ModelError(RuntimeError):
    """Safe to display; never contains provider exception messages or bodies."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite")

    failed = False
    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        # Also catch overflowing exponents, which parse_constant does not see.
        json.dumps(result, allow_nan=False)
        if not isinstance(result, dict):
            failed = True
    except (TypeError, ValueError, OverflowError, RecursionError):
        failed = True
    if failed:
        raise ModelError("Invalid JSON response")
    return result


def _request(url, headers, payload, timeout):
    request = Request(url, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                      headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return _strict_json(response.read().decode("utf-8"))


def _require(value, fields):
    if not isinstance(value, dict) or any(field not in value for field in fields):
        raise ModelError("Missing required response fields")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _brief(value):
    _require(value, BRIEF_FIELDS)
    if value["externalSafe"] is not True:
        raise ModelError("Public sanitized writing brief required")
    for field in ("headings", "facts", "numbers", "links", "requiredExpressions", "protected"):
        if not isinstance(value[field], list) or any(not isinstance(item, str) for item in value[field]):
            raise ModelError("Invalid writing brief lists")
    for field in ("purpose", "reader", "conclusion", "style", "length", "cta", "format"):
        if not _text(value[field]):
            raise ModelError("Incomplete approved writing brief")


class Models:
    def __init__(self, env, request=None, artifact_sink=None):
        self.env = dict(env)
        self.request = request if request is not None else _request
        self.artifact_sink = artifact_sink
        self.usage = []

    def _safe_public(self, value):
        failed = False
        try:
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError):
            failed = True
            serialized = ""
        if failed:
            raise ModelError("Non-JSON model input")
        keys = [v for k, v in self.env.items() if re.search(r"key|token|secret|password", k, re.I)
                and isinstance(v, str) and v]
        if SECRET.search(serialized) or any(key in serialized for key in keys):
            raise ModelError("Sensitive data blocked before model request")
        return serialized

    def _call(self, instruction, data, model, gemini=False, fallback=None, schema=None):
        # One deadline and retry budget across primary and fallback attempts.
        deadline = time.monotonic() + 180
        key_name = "GEMINI_API_KEY" if gemini else "ANTHROPIC_API_KEY"
        key = self.env.get(key_name)
        if not _text(key):
            raise ModelError("Missing provider credential")
        prompt = instruction + "\nReturn ONLY a complete JSON object, no fences or commentary.\n" + self._safe_public(data)
        url = GEMINI_URL if gemini else CLAUDE_URL
        headers = {"Content-Type": "application/json"}
        if gemini:
            headers["Authorization"] = "Bearer " + key
        else:
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        retries = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ModelError("Model request deadline exceeded")
            payload = {"model": model, "max_tokens": 16384,
                       "messages": [{"role": "user", "content": prompt}]}
            if gemini:
                payload["response_format"] = {"type": "json_object"}
            elif schema is not None:
                payload["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
            status = None
            failed = False
            try:
                raw = self.request(url, headers, payload, remaining)
            except Exception as error:
                # Capture only a numeric status. Never retain provider messages,
                # body, credential-bearing request or chained exceptions.
                status = error.code if isinstance(error, HTTPError) else getattr(error, "status", None)
                if type(status) is not int:
                    status = None
                failed = True
            if failed:
                if status == 404 and fallback and fallback != model:
                    model, fallback = fallback, None
                    continue
                if status in (429, 503) and retries < 2:
                    delay = 2 ** retries
                    retries += 1
                    if deadline - time.monotonic() <= delay:
                        raise ModelError("Model request deadline exceeded")
                    time.sleep(delay)
                    continue
                raise ModelError("Provider request failed" + (" (HTTP %d)" % status if status else ""), status)
            if time.monotonic() > deadline:
                raise ModelError("Model request deadline exceeded")
            break
        _require(raw, ("id", "model", "usage"))
        usage = raw["usage"]
        input_key, output_key = ("prompt_tokens", "completion_tokens") if gemini else ("input_tokens", "output_tokens")
        _require(usage, (input_key, output_key))
        if not _text(raw["id"]) or not _text(raw["model"]) or any(
                type(usage[k]) is not int or usage[k] < 0 for k in (input_key, output_key)):
            raise ModelError("Invalid provider usage metadata")
        record = {"responseId": raw["id"], "model": raw["model"], "input": usage[input_key],
                  "output": usage[output_key], "usage": copy.deepcopy(usage), "actualUSD": None}
        self.usage.append(record)
        if gemini:
            choices = raw.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ModelError("Invalid completion envelope")
            choice = choices[0]
            if choice.get("finish_reason") != "stop":
                raise ModelError("Incomplete completion")
            _require(choice.get("message"), ("content",))
            content = choice["message"]["content"]
        else:
            if raw.get("stop_reason") != "end_turn":
                raise ModelError("Incomplete completion")
            blocks = raw.get("content")
            if not isinstance(blocks, list) or not blocks or any(
                    not isinstance(b, dict) or b.get("type") != "text" or not isinstance(b.get("text"), str) for b in blocks):
                raise ModelError("Invalid completion envelope")
            content = "".join(b["text"] for b in blocks)
        self._safe_public(content)
        if self.artifact_sink is not None:
            artifact = {"responseId": raw["id"], "model": raw["model"],
                        "content": content, "usage": copy.deepcopy(usage)}
            self._safe_public(artifact)
            try:
                self.artifact_sink(artifact)
            except Exception:
                raise ModelError("Model artifact sink failed") from None
        return _strict_json(content), copy.deepcopy(record)

    def research(self, context):
        result, _ = self._call(
            "Select exactly three nonduplicate long-tail editorial themes from supplied catalog, GSC queries, season "
            "and merchantClicks evidence. Exclude existing articles and queued themes. Never invent search volumes, "
            "clicks, trends or products. Explain selection using supplied evidence and exact product IDs. "
            "Clicks are NOT purchases, sales, revenue or conversion evidence. Use only the stated observation period; "
            "never infer seasonal growth from cumulative clicks. Catalog category labels are not verified product specifications. "
            "These are untested research proposals: titles must never claim 実測, 実証, 検証済み, 実体験, 愛用, "
            "hands-on use, test results or a measured performance result. Never infer burner count or indoor safety. "
            "Return {themes:[{slug,title,categoryId,productIds,query,selectionReason}, ...]}. Cite supplied evidence in selectionReason.",
            {"context": context}, "claude-sonnet-4-6")
        _require(result, ("themes",))
        themes = result["themes"]
        if not isinstance(themes, list) or len(themes) != 3:
            raise ModelError("Exactly three themes required")
        seen = set()
        existing = context.get("existingArticles", []) + context.get("queuedThemes", [])
        queries = set()
        slugs = set()
        for item in existing:
            if isinstance(item, dict) and _text(item.get("title")):
                seen.add(" ".join(item["title"].casefold().split()))
            if isinstance(item, dict) and _text(item.get("slug")):
                slugs.add(item["slug"])
            if isinstance(item, dict) and _text(item.get("query")):
                queries.add(" ".join(item["query"].casefold().split()))
        for theme in themes:
            _require(theme, ("slug", "title", "categoryId", "query", "productIds", "selectionReason"))
            if (any(not _text(theme[k]) for k in ("slug", "categoryId", "selectionReason", "query")) or not isinstance(theme["productIds"], list)
                    or not theme["productIds"] or any(not _text(pid) for pid in theme["productIds"])):
                raise ModelError("Theme query, products and supplied evidence required")
            if "catalog" in context:
                catalog_ids = {p["id"] for p in context["catalog"] if isinstance(p, dict) and _text(p.get("id"))}
                if any(pid not in catalog_ids for pid in theme["productIds"]):
                    raise ModelError("Unknown theme product ID")
            if not _text(theme["title"]):
                raise ModelError("Theme title required")
            if re.search(r'実測|実証|検証済み|実体験|愛用|使って|使った|使用歴|tested|hands.on', theme['title'], re.I):
                raise ModelError('Unverified firsthand theme claim')
            title = " ".join(theme["title"].casefold().split())
            query = theme.get("query")
            normalized = " ".join(query.casefold().split()) if _text(query) else None
            if theme["slug"] in slugs or title in seen or (normalized is not None and normalized in queries):
                raise ModelError("Duplicate theme")
            seen.add(title)
            slugs.add(theme["slug"])
            if normalized is not None:
                queries.add(normalized)
        return result

    def draft(self, theme, context):
        _require(context, ("catalog", "references"))
        if not isinstance(context["catalog"], list) or not context["catalog"]:
            raise ModelError("Verified catalog required")
        if not any(context.get(k) for k in ("CLAUDE", "claude", "template", "templates")) or not any(
                context.get(k) for k in ("SKILL", "skill", "template", "templates")):
            raise ModelError("Existing CLAUDE/SKILL article templates required in context")
        result, _ = self._call(
            "As upper editor return ONLY {article,brief}. Do not repeat products, references, or images; "
            "those verified records are assembled locally. article must contain slug,title,"
            "categoryId,content,excerpt (at least 20 characters),metaDescription (50-160 characters),faqs (3-5 "
            "objects with nonempty question and answer),tags (list),productIds,author (exactly ギア男). "
            "Content length by brief.format: ranking/comparison 5000-8000 characters; guide/how-to 3000-5000; "
            "review 2000-3500. Include 2-3 distinct internal Markdown links /articles/slug. "
            "Ranking/comparison must include concrete {{comparison:exact-product-ids}} tags. Use ONLY supplied verified catalog/specifications/references and exact product IDs. "
            "Use supplied CLAUDE/SKILL article template, no body H1. "
            "Never invent ownership, experiences, prices, reviews, medical advice or claims. Without verified experiences "
            "explicitly label the article as research. No synthetic missing data. Resolve editorial purpose, reader, "
            "conclusion, structure and factual constraints yourself. Set approved writing brief with ALL fields: "
            + ", ".join(BRIEF_FIELDS) + ". facts/numbers/links/headings/requiredExpressions/protected are lists; "
            "externalSafe must be true ONLY for sanitized public data. The brief must fully specify all known facts, "
            "exact numbers, links, immutable claims, disclosure, style, length, CTA and output format. "
            "Cite only supplied references and use supplied product URLs. "
            "Do not claim images, affiliate destinations or rendering are live-verified.",
            {"theme": theme, "context": context},
            self.env.get("ARTICLE_WRITER_MODEL") or "claude-opus-4-8",
            fallback=self.env.get("ARTICLE_WRITER_FALLBACK_MODEL") or "claude-sonnet-4-6",
            schema=WRITER_SCHEMA)
        if set(result) != {"article", "brief"}:
            raise ModelError("Invalid writer response fields")
        _require(result["article"], ARTICLE_FIELDS)
        _require(result["brief"], BRIEF_FIELDS)
        if set(result["article"]) != set(ARTICLE_FIELDS) or set(result["brief"]) != set(BRIEF_FIELDS):
            raise ModelError("Invalid writer response fields")
        _brief(result["brief"])
        catalog = context["catalog"]
        if any(not isinstance(p, dict) or not _text(p.get("id")) for p in catalog):
            raise ModelError("Invalid catalog product IDs")
        selected_ids = theme.get("productIds") if isinstance(theme, dict) else None
        if selected_ids is None:
            selected_ids = [p["id"] for p in catalog]
        if (not isinstance(selected_ids, list) or not selected_ids or
                any(not _text(pid) for pid in selected_ids) or len(selected_ids) != len(set(selected_ids))):
            raise ModelError("Invalid selected product IDs")
        selected = [copy.deepcopy(next((p for p in catalog if p["id"] == pid), None)) for pid in selected_ids]
        if any(p is None for p in selected):
            raise ModelError("Unknown theme product ID")
        if not isinstance(context["references"], list) or not isinstance(context.get("images", []), list):
            raise ModelError("Invalid supplied evidence lists")
        result.update(products=selected, references=copy.deepcopy(context["references"]),
                      images=copy.deepcopy([image for image in context.get("images", [])
                                            if isinstance(image, dict) and image.get("productId") in selected_ids]))
        if (not _text(result["article"]["content"]) or not isinstance(result["article"]["productIds"], list)
                or any(not _text(pid) for pid in result["article"]["productIds"])):
            raise ModelError("Invalid article")
        article = result["article"]
        if (any(not _text(article[k]) for k in ("slug", "title", "categoryId", "excerpt", "metaDescription"))
                or len(article["excerpt"]) < 20 or not 50 <= len(article["metaDescription"]) <= 160
                or article["author"] != "ギア男" or not isinstance(article["tags"], list)
                or any(not _text(tag) for tag in article["tags"])
                or not isinstance(article["faqs"], list) or not 3 <= len(article["faqs"]) <= 5):
            raise ModelError("Invalid article metadata")
        for faq in article["faqs"]:
            _require(faq, ("question", "answer"))
            if set(faq) != {"question", "answer"} or not _text(faq["question"]) or not _text(faq["answer"]):
                raise ModelError("Incomplete FAQ")
        lengths = {"ranking": (5000, 8000), "comparison": (5000, 8000), "guide": (3000, 5000),
                   "how-to": (3000, 5000), "review": (2000, 3500)}
        format_name = result["brief"]["format"]
        if format_name not in lengths:
            raise ModelError("Unknown article format")
        lower, upper = lengths[format_name]
        if not lower <= len(article["content"]) <= upper:
            raise ModelError("Article length outside existing SKILL limits")
        internal = re.findall(r"(?<!!)\[[^\]\n]+\]\((/articles/[^)\s]+)\)", article["content"])
        if not 2 <= len(set(internal)) <= 3:
            raise ModelError("Two to three distinct internal article links required")
        if format_name in ("ranking", "comparison") and not re.search(r"\{\{comparison:[^}]+\}\}", article["content"]):
            raise ModelError("Concrete product comparison component required")
        for field in ("products", "references", "images"):
            if not isinstance(result[field], list):
                raise ModelError("Invalid bundle lists")
        selected = result["products"]
        if any(p not in catalog for p in selected):
            raise ModelError("Unverified or modified catalog product")
        ids = [p["id"] for p in selected]
        if len(ids) != len(set(ids)) or result["article"]["productIds"] != ids:
            raise ModelError("Article product IDs do not match supplied products")
        for match in re.finditer(r"\{\{(?:product|comparison|ranking):([^}]+)\}\}", result["article"]["content"]):
            if any(pid.strip() not in ids for pid in match.group(1).split(",")):
                raise ModelError("Unknown product ID in article component")
        if any(ref not in context["references"] for ref in result["references"]):
            raise ModelError("Unverified reference")
        for image in result["images"]:
            _require(image, ("productId", "url"))
            if "images" in context and not any(isinstance(known, dict) and
                    all(k in known and known[k] == v for k, v in image.items()) for known in context["images"]):
                raise ModelError("Modified or invented image evidence")
            if "images" not in context and image.get("verified") is True:
                raise ModelError("Independent image verification required")
            if not any(p["id"] == image["productId"] and p.get("imageUrl") == image["url"] for p in selected):
                raise ModelError("Unverified product image")
        self._safe_public(result)
        return result

    def polish(self, source, brief):
        _brief(brief)
        if not _text(source):
            raise ModelError("Source content required")
        parts = re.split(r'((?:\r?\n[ \t]*){2,})', source)
        paragraphs = parts[::2]
        fixed = tuple(token for field in ("protected", "requiredExpressions")
                      for token in brief[field] if token)
        eligible = [index for index, paragraph in enumerate(paragraphs)
                    if paragraph.strip() and not _protected(paragraph)
                    and not any(token in paragraph for token in fixed)]
        result, usage = self._call(
            "Return ONLY {edits:[{index:integer,text:string}]}. Edit prose in eligible paragraphs only. "
            "Indices refer to the supplied eligible paragraph indices. Preserve all facts, meaning, numbers, "
            "links, headings, shortcodes, disclosure and protected expressions. Do not add medical advice. "
            "Use edits:[] if no correction is needed. Do not grade or approve publication.",
            {"source": source, "brief": brief,
             "editable": [{"index": i, "text": paragraphs[i]} for i in eligible]},
            "gemini-3.8-flash", gemini=True)
        if set(result) != {"edits"} or not isinstance(result["edits"], list):
            raise ModelError("Invalid polish edits")
        seen = set()
        for edit in result["edits"]:
            if (not isinstance(edit, dict) or set(edit) != {"index", "text"}
                    or type(edit["index"]) is not int or edit["index"] not in eligible
                    or edit["index"] in seen or not _text(edit["text"])
                    or re.search(r'(?:\r?\n[ \t]*){2,}', edit["text"])
                    or _protected(edit["text"])
                    or any(token in edit["text"] for token in fixed)):
                raise ModelError("Invalid polish edits")
            seen.add(edit["index"])
            parts[edit["index"] * 2] = edit["text"]
        candidate = ''.join(parts)
        if inspect_polish(source, candidate)["passed"] is not True:
            raise ModelError("Polish protected content changed")
        usage["polishEditsApplied"] = len(seen)
        usage["polishOutcome"] = "edited" if seen else "no_changes"
        return {"content": candidate, "model": usage["model"], "usage": usage}

    def review(self, bundle, checks):
        result, usage = self._call(
            "Final upper-model review using supplied full bundle, brief, references and independent checks. "
            "Return {passed:boolean,score:number,facts:boolean,images:boolean,affiliate:boolean,medical:boolean,"
            "render:boolean,evidence:object,issues:list}. Score 0-10; pass threshold 7.5. "
            "Never certify live images, affiliate destinations or rendering from LLM opinion. Missing independent "
            "evidence must fail. checks.evidence.facts certifies catalog product specifications ONLY; it does not "
            "certify every claim in the article. Independently audit every factual claim and inference in the title, "
            "body, metadata, excerpt and FAQs against the exact catalog records, primary references and, when supplied, "
            "checks.approvedTheme and its Astra constraints. Reject reversed or unsupported product comparisons, "
            "fictional anecdotes or firsthand experience, extrapolation beyond stated measurement conditions, and "
            "price or availability claims without current independent proof. A repeated number or cited URL alone does "
            "not establish the surrounding claim. Mark facts false and passed false, with specific issues, whenever "
            "provenance or approved-theme compliance is missing. Check medical claims and protected brief. "
            "Compare checks.sourceContent to the candidate for unchanged meaning and conclusions. "
            "If checks.editorialRules is supplied, apply its WISE/Supervisor rubric and also return criteria "
            "with eleven numeric 0-10 scores: wise_w,wise_i,wise_s,wise_e,wise_ai,wise_sense,affiliate_links,"
            "comparison_table,internal_links,faq,word_count. Overall score must not exceed their mean. "
            "For social proposals every claim must be supported by checks.factualSource; numeric/URL checks alone "
            "do not establish factual truth. Reject new claims, changed advertising disclosures or unsupported benefits. "
            "Model assertions are opinions and cannot substitute for external evidence.",
            {"bundle": bundle, "checks": checks}, self.env.get("ARTICLE_REVIEW_MODEL") or "claude-sonnet-4-6")
        _require(result, ("passed", "score", "evidence", "issues") + CATEGORIES)
        if type(result["passed"]) is not bool or any(type(result[k]) is not bool for k in CATEGORIES) or (
                type(result["score"]) not in (int, float) or not math.isfinite(result["score"]) or
                not 0 <= result["score"] <= 10 or not isinstance(result["issues"], list) or
                not isinstance(result["evidence"], dict)):
            raise ModelError("Invalid review result")
        supplied = checks.get("evidence", checks) if isinstance(checks, dict) else {}
        if isinstance(checks, dict) and checks.get('editorialRules'):
            fields = ('wise_w', 'wise_i', 'wise_s', 'wise_e', 'wise_ai', 'wise_sense',
                      'affiliate_links', 'comparison_table', 'internal_links', 'faq', 'word_count')
            criteria = result.get('criteria', {})
            if not isinstance(criteria, dict) or any(type(criteria.get(k)) not in (int, float) or
                    not math.isfinite(criteria[k]) or not 0 <= criteria[k] <= 10 for k in fields):
                raise ModelError('Complete WISE Supervisor scores required')
            result['score'] = min(result['score'], sum(criteria[k] for k in fields) / len(fields))
        supplied = supplied if isinstance(supplied, dict) else {}
        missing = [k for k in CATEGORIES if supplied.get(k) is not True]
        for field in missing:
            result[field] = False
            result["issues"].append("Missing independent %s evidence" % field)
        offline_failed = not isinstance(checks, dict) or checks.get("passed") is False or bool(checks.get("failures"))
        if offline_failed:
            result["issues"].append("Independent offline checks failed")
        result["passed"] = (result["passed"] and result["score"] >= 7.5 and not result["issues"]
                            and all(result[k] is True for k in CATEGORIES) and not missing)
        result["model"] = usage["model"]
        result["evidence"] = {"model": result["evidence"], "checks": copy.deepcopy(checks)}
        return result

    def social(self, bundle, url):
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ModelError("Public HTTPS article URL required")
        _require(bundle, ("article", "images", "publicReadback"))
        _require(bundle["article"], ("content",))
        rb = bundle["publicReadback"]
        _require(rb, ("verified", "url", "content", "images"))
        if rb["verified"] is not True or rb["url"] != url or rb["content"] != bundle["article"]["content"] or rb["images"] != bundle["images"]:
            raise ModelError("Matching public article and images readback required")
        result, _ = self._call(
            "Generate an X announcement ONLY after the supplied matching public readback. "
            "Return {text,replyText,url,images,platform:'x'}. Main text must contain NO URLs, "
            "the exact public article URL goes in replyText. Keep every advertising/affiliate disclosure "
            "from the source. Preserve product/fact constraints and use only readback images. "
            "Follow supplied social rules. Do not post or claim approval.",
            {"bundle": bundle, "url": url}, "claude-sonnet-4-6")
        _require(result, ("text", "replyText", "url", "images", "platform"))
        if not _text(result["text"]) or not _text(result["replyText"]) or result["platform"] != "x" or (
                result["url"] != url or url not in result["replyText"] or
                re.search(r"https?://|www\.|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/|\b)", result["text"], re.I) or
                not isinstance(result["images"], list) or any(i not in rb["images"] for i in result["images"])):
            raise ModelError("Invalid social announcement")
        disclosure = re.compile(r"広告|アフィリエイト|(?<![a-z])PR(?![a-z])|#ad\b|affiliate|sponsored", re.I)
        for marker in disclosure.findall(bundle["article"]["content"]):
            if marker.casefold() not in result["text"].casefold():
                raise ModelError("Social advertising disclosure removed")
        return result
