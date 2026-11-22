"""Editorial model boundary: injected transport, strict JSON, pinned policy validation.

Context supplies catalog, references, images, CLAUDE and SKILL text (no paths are
opened except the pinned owner-policy contract). Review checks contain facts/images/affiliate/medical/render booleans.
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
from model_inputs import project_model_input
from writing_prompts import get_draft_specificity_prompt, get_polish_style_prompt
from wise_contract import load_policy, valid_scores, passes
from review_scoring import (CRITERIA_FIELDS, article_applicability, calculate as calculate_article_review,
                            verdict as article_verdict, validate_feedback, resolve_feedback, select_feedback, word_count_score)
from quality import purchase_anchor_issues, montbell_wear_claim_issues, SHORTCODE, SITE_HOSTS, _article_links, _protected, _without_code, inspect_polish


CLAUDE_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
BRIEF_FIELDS = ("purpose", "reader", "conclusion", "headings", "facts", "numbers", "links",
                "requiredExpressions", "protected", "style", "length", "cta", "format", "externalSafe")
ARTICLE_LENGTHS = {"ranking": (5000, 8000), "comparison": (5000, 8000), "guide": (3000, 5000),
                   "how-to": (3000, 5000), "review": (2000, 3500)}
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
MIXED_RESEARCH_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['proposals'],
    'properties': {'proposals': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False,
        'required': ['slug', 'title', 'categoryId', 'productIds', 'topicType', 'query',
                     'readerQuestion', 'intent', 'outline', 'priority', 'overlapRationale',
                     'selectionReason', 'sourceIds', 'proposedAction', 'overlapArticleIds', 'needsStatus'],
        'properties': {
            **{field: {'type': 'string'} for field in
               ('slug', 'title', 'categoryId', 'query', 'readerQuestion', 'overlapRationale', 'selectionReason')},
            **{field: {'type': 'array', 'items': {'type': 'string'}} for field in
               ('productIds', 'outline', 'sourceIds', 'overlapArticleIds')},
            'priority': {'type': 'integer'},
            'topicType': {'type': 'string', 'enum': ['product', 'seasonal_problem', 'knowhow']},
            'intent': {'type': 'string', 'enum': ['informational', 'commercial_investigation', 'transactional']},
            'proposedAction': {'type': 'string', 'enum': ['new', 'existing_update', 'hold']},
            'needsStatus': {'type': 'string', 'enum': ['not_applicable', 'measured_change', 'seasonal_hypothesis']},
        },
        # Ranges, lengths, membership and cross-field rules remain enforced by
        # validate_proposals(); do not send unsupported Claude wire constraints.
    }}},
}
SOCIAL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["text", "replyText"],
    "properties": {"text": {"type": "string"}, "replyText": {"type": "string"}}
}
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["passed", "score", *CATEGORIES, "evidence", "issues", "observations", "criteria", "wiseScores"],
    "properties": {"wiseScores": {"type": "object", "additionalProperties": False,
                       "required": ["w", "i", "s", "e", "ai", "sense"],
                       # Claude's wire schema cannot express numeric bounds.
                       # valid_scores()/passes() enforce the range and floors locally.
                       "properties": {k: {"type": "number"}
                                      for k in ("w", "i", "s", "e", "ai", "sense")}},
                   "passed": {"type": "boolean"}, "score": {"type": "number"},
                   **{field: {"type": "boolean"} for field in CATEGORIES},
                   "evidence": {"type": "object", "additionalProperties": False,
                                "required": ["summary"], "properties": {"summary": {"type": "string"}}},
                   "issues": {"type": "array", "items": {"type": "string"}},
                   "observations": {"type": "array", "items": {"type": "string"}},
                   "criteria": {"type": "object", "additionalProperties": False,
                                "required": list(CRITERIA_FIELDS),
                                "properties": {field: {"type": "number"} for field in CRITERIA_FIELDS}}}
}
SOCIAL_REVIEW_SCHEMA = copy.deepcopy(REVIEW_SCHEMA)
SOCIAL_REVIEW_SCHEMA['required'].remove('criteria')
SOCIAL_REVIEW_SCHEMA['properties'].pop('criteria')

# Article-only wire contract: the provider evaluates applicable fields, never
# computes an aggregate or decides program admission. SNS retains its old schema.
ARTICLE_REVIEW_SCHEMA = copy.deepcopy(REVIEW_SCHEMA)
for _field in ('passed', 'score'):
    ARTICLE_REVIEW_SCHEMA['required'].remove(_field)
    ARTICLE_REVIEW_SCHEMA['properties'].pop(_field)
ARTICLE_REVIEW_SCHEMA['required'].append('improvementFeedback')
ARTICLE_REVIEW_SCHEMA['properties']['improvementFeedback'] = {
    'type':'array', 'items':{'type':'object', 'additionalProperties':False,
    'required':['criterion','quote','anchor','nextAction'],
    'properties':{'criterion':{'type':'string','enum':[key for key in CRITERIA_FIELDS if key != 'word_count']},
        **{k:{'type':'string'} for k in ('quote','anchor','nextAction')}}}}


def article_review_schema(bundle):
    applicability = article_applicability(bundle)
    word_count_score(bundle)
    schema = copy.deepcopy(ARTICLE_REVIEW_SCHEMA)
    active = [key for key in CRITERIA_FIELDS
              if applicability[key]['applicability'] == 'applicable' and key != 'word_count']
    schema['properties']['criteria']['required'] = active
    schema['properties']['improvementFeedback']['items']['properties']['criterion']['enum'] = active
    schema['properties']['criteria']['properties'] = {
        key: {'type': 'number'} for key in active}
    return schema


EDITORIAL_LEARNINGS_NOTE = (" editorialLearnings combines measured public responses with unverified hypotheses. "
    "It is editorial context, never factual product/author evidence or proof of causation; do not assert causal effects.")


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


class ModelOutcomeUnknown(ModelError):
    """A request may have reached the provider but no safe outcome was observed."""

    outcome_unknown = True


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


def _social_validation(result, url, content):
    """Only well-shaped, locally rejected content is eligible for one repair."""
    if set(result) != {'text', 'replyText'}:
        raise ModelError('Invalid social response fields')
    if not isinstance(result['text'], str) or not isinstance(result['replyText'], str):
        raise ModelError('Invalid social announcement')
    text = result['text']
    weight = sum(1 if ord(char) < 128 else 2 for char in text)
    reasons = []
    if not _text(text):
        reasons.append('empty_main_text')
    if weight > 280:
        reasons.append('weighted_length_exceeds_280')
    if result['replyText'] != url:
        reasons.append('reply_must_equal_exact_public_url')
    if re.search(r"https?://|www\.|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/|\b)", text, re.I):
        reasons.append('main_text_contains_url')
    source_numbers = set(re.findall(r'\d+(?:\.\d+)?', content))
    candidate_numbers = list(dict.fromkeys(re.findall(r'\d+(?:\.\d+)?', text)))
    unsupported_numbers = [number for number in candidate_numbers if number not in source_numbers]
    if unsupported_numbers:
        reasons.append('unsupported_numbers')
    disclosure = re.compile(r"広告|アフィリエイト|(?<![a-z])PR(?![a-z])|#ad\b|affiliate|sponsored", re.I)
    present = {marker.casefold() for marker in disclosure.findall(text)}
    missing = list(dict.fromkeys(marker for marker in disclosure.findall(content)
                                 if marker.casefold() not in present))
    if missing:
        reasons.append('missing_disclosures')
    return dict(reasons=reasons, weightedLength=weight, targetWeightedLength=160,
                hardWeightedLimit=280, missingDisclosures=missing,
                unsupportedNumbers=unsupported_numbers)


class Models:
    def __init__(self, env, request=None, artifact_sink=None, budget=None):
        self.env = dict(env)
        self.request = request if request is not None else _request
        self.artifact_sink = artifact_sink
        self.budget = budget
        self.usage = []
        self.review_diagnostics = []

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
        self._safe_public(data)
        projected = project_model_input(data)
        prompt = instruction + "\nReturn ONLY a complete JSON object, no fences or commentary.\n" + self._safe_public(projected)
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
            hold = self.budget.reserve(payload, model=model) if self.budget is not None else None
            status = None
            failed = False
            try:
                raw = self.request(url, headers, payload, remaining)
            except ModelError:
                # A parsed provider response failed a known validation contract.
                if self.budget is not None:
                    self.budget.settle(hold, usage=None, outcome='unknown')
                raise
            except Exception as error:
                # Capture only a numeric status. Never retain provider messages,
                # body, credential-bearing request or chained exceptions.
                status = error.code if isinstance(error, HTTPError) else getattr(error, "status", None)
                if type(status) is not int:
                    status = None
                failed = True
            if failed:
                if self.budget is not None:
                    self.budget.settle(hold, usage=None, outcome='failed' if status is not None else 'unknown')
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
                if status is None:
                    raise ModelOutcomeUnknown("Provider outcome unknown")
                raise ModelError("Provider request failed" + (" (HTTP %d)" % status if status else ""), status)
            settle_error = None
            if self.budget is not None:
                try:
                    self.budget.settle(hold, usage=copy.deepcopy(raw.get('usage')) if isinstance(raw, dict) else None,
                                       outcome='success', response_id=raw.get('id') if isinstance(raw, dict) else None)
                except Exception as error:
                    settle_error = error
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
        if settle_error is not None:
            raise settle_error
        if time.monotonic() > deadline:
            raise ModelOutcomeUnknown("Provider outcome unknown")
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
            "Return {themes:[{slug,title,categoryId,productIds,query,selectionReason}, ...]}. Cite supplied evidence in selectionReason." + EDITORIAL_LEARNINGS_NOTE,
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

    def research_mixed(self, context):
        """One bounded research call; local code decides overlap and selection."""
        from topic_selection import validate_proposals, TopicSelectionError, MAX_PROPOSALS
        result, record = self._call(
            "Propose between one and nine regular-period Camp Gear Lab topics, preferably up to three for each "
            "topicType when evidence supports them; this is soft coverage, never a quota. This is proposal generation, "
            "not final selection. Use only supplied evidence IDs and never invent search volume, trend, clicks, "
            "products, ownership, experience or safety claims. GSC/GA4 are own-site aggregates, not market demand. "
            "A gsc-change record is only a matched own-site period comparison and never Google Trends. Calendar month "
            "is not evidence. topicType must be product, seasonal_problem or knowhow. product topics require existing "
            "productIds; seasonal_problem/knowhow may use verified existing productIds only when needed, otherwise []. "
            "For every proposal return readerQuestion, intent, "
            "a title of at most 80 characters, 3-5 concise outline headings of at most 40 characters each, "
            "ordinal priority 1-100, "
            "overlapRationale, selectionReason and exact sourceIds. "
            "Every new proposal must cite directly relevant supplied own-site query-demand or GSC/GA4 signal IDs; "
            "public references alone cannot qualify a new topic. Explain relevance and the limits of page-level "
            "evidence without presenting it as measured demand for the proposed query or market search volume. "
            "Prioritize seasonal reader problems, apparel choices and supported brand comparisons. Match the "
            "topic's garment/problem/brand facets to the supplied anonymized query-demand groups. Never use an "
            "unrelated popular page to justify a topic. Narrow parts lookup, component care and isolated label "
            "checks belong in an appropriate existing section/FAQ, not a padded new article; hold if no target "
            "can be identified. The program ranks demand and distinctness before your priority. "
            "intent is exactly informational, commercial_investigation or transactional, not free-text. "
            "Do not normalize prior proposals or invent missing sourceIds, productIds or needsStatus. "
            "Plan distinct reader decisions that the supplied primary evidence can substantively explain across "
            "the full existing format length. Do not stretch a short FAQ into repeated sections expecting the "
            "writer to supply missing facts. If the available evidence cannot support that scope, use the existing "
            "hold/action and rationale fields to state the limitation; add no new schema fields or source-count gate. "
            "Use only a supplied categoryId. Set needsStatus=measured_change for seasonal_problem only with an exact "
            "gsc-change evidence ID; otherwise set seasonal_hypothesis. All other topic types use not_applicable. "
            "Do not claim semantic uniqueness. Compare reader question and outline with bounded existing summaries. "
            "Set proposedAction=new with overlapArticleIds:[] only when distinct; existing_update with known article IDs "
            "for a semantic overlap; hold when ambiguous. Exclude medical, survival, extreme-cold, "
            "emergency and other high-stakes advice. Return ONLY {proposals:[...]}. Each proposal has exactly "
            "slug,title,categoryId,productIds,topicType,query,readerQuestion,intent,outline,priority,"
            "overlapRationale,selectionReason,sourceIds,proposedAction,overlapArticleIds,needsStatus." + EDITORIAL_LEARNINGS_NOTE,
            {"context": context}, "claude-sonnet-4-6", schema=MIXED_RESEARCH_SCHEMA)
        if not isinstance(result, dict) or set(result) != {"proposals"}:
            raise ModelError("Invalid mixed research response")
        catalog_ids = {item["id"] for item in context.get("catalog", [])
                       if isinstance(item, dict) and _text(item.get("id"))}
        existing_ids = {item["id"] for item in context.get("existingArticles", [])
                        if isinstance(item, dict) and _text(item.get("id"))}
        category_ids = {item["id"] for item in context.get("categories", [])
                        if isinstance(item, dict) and _text(item.get("id"))}
        raw = result["proposals"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PROPOSALS:
            raise TopicSelectionError("one_to_nine_proposals_required")
        valid, rejected, first_error = [], [], None
        for index, proposal in enumerate(raw):
            try:
                valid.extend(validate_proposals([proposal], catalog_ids=catalog_ids,
                    existing_ids=existing_ids, category_ids=category_ids))
            except (TopicSelectionError, TypeError) as error:
                if first_error is None:
                    first_error = error
                slug = proposal.get('slug') if isinstance(proposal, dict) else None
                rejected.append({'index': index, 'slug': slug if isinstance(slug, str) and len(slug) <= 80 else None,
                    'reason': str(error) if isinstance(error, TopicSelectionError) else 'proposal_contract_type'})
        if not valid:
            raise first_error
        result = {'proposals': valid}
        if rejected:
            result.update(contractRejections=rejected, rawProposalCount=len(raw), responseId=record['responseId'])
        return result

    def draft(self, theme, context):
        _require(context, ("catalog", "references"))
        nonproduct = theme.get("productIds") == [] and isinstance(context.get("commercialRoute"), dict)
        if not isinstance(context["catalog"], list) or (not context["catalog"] and not nonproduct):
            raise ModelError("Verified catalog required")
        if not any(context.get(k) for k in ("CLAUDE", "claude", "template", "templates")) or not any(
                context.get(k) for k in ("SKILL", "skill", "template", "templates")):
            raise ModelError("Existing CLAUDE/SKILL article templates required in context")
        instruction = (
            json.dumps(context.get("verifiedAuthorFacts", []), ensure_ascii=False) + "\n"
            "The JSON list above is verifiedAuthorFacts. Copy EACH item into article.content as a complete verbatim sentence, "
            "including its final punctuation. Do not paraphrase; do not shorten or embed it in a longer sentence "
            "by replacing its ending with が or another connective. Include every exact sentence in brief.protected too. "
            "Source provenance takes priority over style templates, including CLAUDE/SKILL storytelling examples. "
            "When verifiedAuthorFacts is empty, write NO first-person past narrative, including generic camping mishaps "
            "or past buying feelings; use third-person research instead. "
            "Do not turn these prohibitions into long reader-facing disclaimers. "
            "When existingArticle is supplied, rewrite that exact existing URL using editorialCorrectionInstructions. "
            "existingArticle and existingArticles supply identity/navigation only, not factual evidence; "
            "never infer product, experience or usage claims from their titles. "
            "Manufacturer-description references are bounded public primary excerpts, not verified personal experience. "
            "Distinguish manufacturer claims from independently verified performance and preserve their qualifications. "
            "This excerpt does not verify catalog description, price, rating or availability. "
            "Never infer winter warmth, safe cold temperatures or survival suitability from weight, fill power or layer class. "
            "Unless a supplied excerpt literally supports the claim, do not assert that a thin shell cannot stop wind, "
            "that average weight excludes size or individual variation, that storage dimensions assume ideal packing, "
            "that the garment suits indoor or high-activity use, or that 1000FP guarantees warmth. "
            "Missing evidence means 今回の根拠では未確認, not that the manufacturer never states it anywhere "
            "or publishes no temperature rating globally. Do not add scientific definitions of denier or fill power "
            "unless supplied by the sources. Explain purchase decisions using documented weight, storage, pockets "
            "and variant choices without inferring performance or safety, including in FAQs and metadata. "
            "Do not expose internal field names or values such as apparelClass or optionState in reader-facing prose; "
            "translate only supported product/variant distinctions into ordinary language. "
            "For a product guide, include a sourced Markdown comparison table of official, 楽天 and Amazon color/size/options when supplied references.apparelBinding confirms them. "
            "Include only confirmed channels and exact fixed/selectable variant differences; label it a purchase-option comparison, not a multi-product ranking, without inferring price or availability. "
            "Lead with concrete purchaser choices: explain how documented specifications and variant discrepancies affect what to select or check before buying. "
            "One concise research disclosure is enough; do not repeat editorial verification or moral claims in every section. "
            "Keep necessary source qualifications beside the relevant claim, without fabricating firsthand experience, scientific explanations, performance or safety claims. "
            "Raw merchant reference URLs are evidence only; purchase CTAs must use the exact supplied selected-product affiliateUrl or amazonUrl, never a raw listing URL or altered tag/ASIN. "
            "Legacy prose is NOT verified evidence: remove unsupported medical/child-safety claims and invented experiences. "
            "Only sourced manufacturer usage warnings may remain; never add clinical advice. "
            "Preserve every supplied verifiedAuthorFacts statement exactly; never infer ownership or experience from legacy prose. "
            "Use the existing length rules even if the legacy source is much longer. Keep ALL selected products and "
            "documented decision topics; accessories are not extra ranked main models. Do not invent a selection count. "
            "As upper editor return ONLY {article,brief}. Do not repeat products, references, or images; "
            "those verified records are assembled locally. article must contain slug,title,"
            "categoryId,content,excerpt (at least 20 characters),metaDescription (50-160 characters),faqs (3-5 "
            "objects with nonempty question and answer),tags (list),productIds,author (exactly ギア男). "
            "Do not create an empty ## FAQ heading or any empty FAQ section in article.content: "
            "either write the actual question-and-answer pairs under that heading or omit the body heading "
            "and let the structured article.faqs render. Keep the required body length unchanged. "
            "Content length by brief.format: ranking/comparison 5000-8000 characters; guide/how-to 3000-5000; "
            "review 2000-3500. Include 2-3 distinct internal Markdown links /articles/slug across the WHOLE article.content, "
            "not 2-3 per section. Use only exact destinations supplied by context.existingArticles, derived from their slugs; "
            "exclude the current article's slug. Repeated destinations count once; never invent another destination. "
            "Aim inside those ranges: guide/how-to body 4000-4700 characters, ranking/comparison 6000-7000, review 2500-3000. "
            "These are Japanese character counts (Python len of the decoded article.content string), NOT tokens, words, "
            "UTF-8 bytes or JSON escape lengths. Before writing, budget meaningful explanation across the required sections. "
            "For a guide, a possible 4200-character budget is introduction 300, five existing main sections 700 each, "
            "and conclusion 400; adapt the allocation to the supplied structure without adding unnecessary headings. "
            "In each section explain what the supplied facts mean for the reader's stated decision, distinguish documented "
            "options and their sourced limitations, and connect the reasoning to the conclusion. Do not infer unverified "
            "performance or usage advice. A 2200-2800-character outline is not a complete guide. "
            "Check the whole body against the character budget before returning; expand underexplained existing points "
            "using only supplied verified facts, without filler, repeated summaries, new facts or invented examples. "
            "Count ONLY article.content, excluding excerpt, metaDescription and structured FAQs; do not pad with repeated specifications. "
            "Selection reasons and data-correction history are editorial instructions, not publishable factual sources. "
            "Never turn obsolete internal catalog values into claims about online shops or other websites. "
            "Do not discuss this pipeline or its verification process in the article. Do not invent category weight comparisons, "
            "guaranteed vehicle/storage fit, material stability or cold-weather ignition performance from nominal specifications. "
            "Preserve source qualifiers in every clause, including FAQs: nominal g/h is not maximum/full-power consumption "
            "or a capacity-to-runtime basis without explicit sourcing; quoted weights do not imply fuel/accessory exclusions, "
            "approximate battery hours are not upper bounds, and LED count is not brightness. "
            "Handle-excluded dimensions do not establish overall height with the handle, and gotoku diameter does not certify "
            "pan stability or usage instructions. Honor supplied source constraints and explicit prior Astra rejections "
            "without inventing missing conditions. "
            "If context.apparelApprovalDisclosure is present, include every supplied requiredExpressions string "
            "verbatim in article.content and brief.requiredExpressions/protected; do not merge fixed and selectable "
            "merchant variants or claim they share a color or size. "
            "For product articles include {{product:exact-ID}} for every selected product so verified purchase cards can render. "
            "Product ranking/comparison must also include concrete {{comparison:exact-product-ids}} tags. "
            "For a verified nonproduct route, productIds must stay [] and no product/comparison/ranking/price shortcode, "
            "merchant recommendation, affiliate claim, real-product image claim, medical or survival advice may be added. "
            "Use ONLY supplied verified catalog/specifications/references and exact product IDs. "
            "Use supplied CLAUDE/SKILL article template, no body H1. "
            "Never invent ownership, experiences, prices, reviews, medical advice or claims. Without verified experiences "
            "explicitly label the article as research. No synthetic missing data. Resolve editorial purpose, reader, "
            "conclusion, structure and factual constraints yourself. Set approved writing brief with ALL fields: "
            + ", ".join(BRIEF_FIELDS) + ". facts/numbers/links/headings/requiredExpressions/protected are lists; "
            "externalSafe must be true ONLY for sanitized public data. The brief must fully specify all known facts, "
            "exact numbers, links, immutable claims, disclosure, style, length, CTA and output format. "
            "Cite only supplied references and use supplied product URLs. "
            "Do not claim images, affiliate destinations or rendering are live-verified.")
        instruction += '\n' + get_draft_specificity_prompt() + EDITORIAL_LEARNINGS_NOTE
        theme, context = copy.deepcopy((theme, context))
        result, record = self._call(instruction,
            {"theme": theme, "context": context},
            self.env.get("ARTICLE_WRITER_MODEL") or "claude-opus-4-8",
            fallback=self.env.get("ARTICLE_WRITER_FALLBACK_MODEL") or "claude-sonnet-4-6",
            schema=WRITER_SCHEMA)
        # Run EVERY non-length check first: source/schema/format errors are never
        # disguised as repairable length failures. _call already preserved the raw
        # first artifact and usage before this local validation.
        result = self._validate_draft(result, theme, context, check_length=False)
        lower, upper = ARTICLE_LENGTHS[result['brief']['format']]
        count = len(result['article']['content'])
        if lower <= count <= upper:
            return result
        previous = {key: copy.deepcopy(result[key]) for key in ('article', 'brief')}
        feedback = dict(format=result['brief']['format'], actualCharacters=count, minimum=lower, maximum=upper)
        repaired, repaired_record = self._call(
            instruction + "\nOne length-only repair: article.content has " + str(count) +
            " characters; the unchanged brief.format requires " + str(lower) + "-" + str(upper) +
            " characters. Minimum net addition required: " + str(max(0, lower - count)) +
            " characters; minimum net removal required: " + str(max(0, count - upper)) +
            " characters. These deltas reach the hard boundary only; aim for the format's interior target above. "
            "Plan the net change across existing sections and check the final decoded body character count; "
            "a small partial expansion that remains below the minimum fails. "
            "Return the same article and brief, changing ONLY article.content. "
            "Do not change brief.format or any other brief field, article identity or metadata. "
            "Do not add new facts, numbers, links, headings, claims or experiences. "
            "Keep verified author sentences and protected facts verbatim. Explain the existing verified facts "
            "more clearly within the existing structure, or remove redundant prose if too long. "
            "Preserve the exact text, occurrence count and order of all headings, numbers, URLs, link destinations, "
            "tables, code, product IDs, shortcodes and disclosure lines. Do not duplicate, move or remove these protected "
            "elements while expanding prose; do not repeat protected literals in added explanations. "
            "Kanji numeral occurrences are protected too, including ordinary wording such as 一方, 一枚 and 二つ. "
            "Write added explanations without new Arabic digits or Kanji numerals; use natural nonnumeric wording "
            "such as ただし, 肌着 and 両者. Do not restate existing material percentages in added paragraphs. "
            "Do not pad with repeated text or specifications. Do not reclassify the format. "
            "This is the only repair attempt; count ONLY article.content and satisfy the original hard range.",
            dict(theme=theme, context=context, previousCandidate=previous, validation=feedback),
            record['model'], schema=WRITER_SCHEMA)  # Same resolved Claude; no fallback or third generation.
        repaired = self._validate_draft(repaired, theme, context)
        literals = context.get('verifiedAuthorFacts', []) + previous['brief']['facts'] + previous['brief']['protected']
        if (repaired_record['model'] != record['model'] or repaired['brief'] != previous['brief']
                or any(repaired['article'][key] != previous['article'][key] for key in ARTICLE_FIELDS if key != 'content')
                or any(f in previous['article']['content'] and f not in repaired['article']['content'] for f in literals)
                or inspect_polish(previous['article']['content'], repaired['article']['content'])['passed'] is not True):
            raise ModelError('Length repair changed protected identity, brief or facts')
        return repaired

    def _validate_draft(self, result, theme, context, check_length=True):
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
        nonproduct = (selected_ids == [] and isinstance(context.get("commercialRoute"), dict)
                      and context["commercialRoute"].get("status") == "not_applicable")
        if (not isinstance(selected_ids, list) or (not selected_ids and not nonproduct) or
                any(not _text(pid) for pid in selected_ids) or len(selected_ids) != len(set(selected_ids))):
            raise ModelError("Invalid selected product IDs")
        selected = [copy.deepcopy(next((p for p in catalog if p["id"] == pid), None)) for pid in selected_ids]
        if any(p is None for p in selected):
            raise ModelError("Unknown theme product ID")
        if not isinstance(context["references"], list) or not isinstance(context.get("images", []), list):
            raise ModelError("Invalid supplied evidence lists")
        result.update(products=selected, references=copy.deepcopy(context["references"]),
                      images=copy.deepcopy(context.get("images", []) if nonproduct else
                          [image for image in context.get("images", [])
                           if isinstance(image, dict) and image.get("productId") in selected_ids]))
        if (not _text(result["article"]["content"]) or not isinstance(result["article"]["productIds"], list)
                or any(not _text(pid) for pid in result["article"]["productIds"])):
            raise ModelError("Invalid article")
        article = result["article"]
        if purchase_anchor_issues(article['content'], selected):
            raise ModelError('Purchase anchor must use exact selected canonical affiliate URLs')
        if montbell_wear_claim_issues(article, selected):
            raise ModelError('Unsupported Mont-bell apparel claim')
        if context.get("existingArticle"):
            if article.get("slug") != context["existingArticle"]["slug"]:
                raise ModelError("Revision source URL changed")
            if any(f not in article["content"] for f in context.get("verifiedAuthorFacts", [])):
                raise ModelError("Verified author fact removed")
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
        if article["productIds"] != selected_ids:
            raise ModelError("Article product IDs do not match supplied products")
        used_ids = set()
        for match in SHORTCODE.finditer(_without_code(article["content"])):
            tag_ids = [pid.strip() for pid in match.group(2).split(",")]
            if any(pid not in selected_ids for pid in tag_ids):
                raise ModelError("Unknown product ID in article component")
            used_ids.update(tag_ids)
        missing_ids = [pid for pid in selected_ids if pid not in used_ids]
        if missing_ids:
            separator = '' if article["content"].endswith('\n\n') else '\n\n'
            article["content"] += separator + '\n\n'.join('{{product:' + pid + '}}' for pid in missing_ids)
        format_name = result["brief"]["format"]
        if format_name not in ARTICLE_LENGTHS:
            raise ModelError("Unknown article format")
        lower, upper = ARTICLE_LENGTHS[format_name]
        existing = context.get('existingArticles')
        if (not isinstance(existing, list) or not existing or any(
                not isinstance(item, dict) or not isinstance(item.get('slug'), str)
                or not re.fullmatch(r'[^/\s?#]+', item['slug']) for item in existing)):
            raise ModelError('Known existing article slugs required')
        allowed = {'/articles/' + item['slug'] for item in existing}
        internal = set()
        for _, destination in _article_links(_without_code(article['content'])):
            parsed = urlsplit(destination)
            if not (destination.startswith('/articles/') or
                    parsed.hostname in SITE_HOSTS and parsed.path.startswith('/articles/')):
                continue
            if (parsed.path not in allowed or parsed.path == '/articles/' + article['slug']
                    or parsed.query or parsed.fragment):
                raise ModelError('Unknown or self internal article link')
            internal.add(parsed.path)
        if not 2 <= len(internal) <= 3:
            raise ModelError("Two to three distinct internal article links required")
        if not nonproduct and format_name in ("ranking", "comparison") and not re.search(r"\{\{comparison:[^}]+\}\}", article["content"]):
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
            _require(image, (("url",) if nonproduct else ("productId", "url")))
            if "images" in context and not any(isinstance(known, dict) and
                    all(k in known and known[k] == v for k, v in image.items()) for known in context["images"]):
                raise ModelError("Modified or invented image evidence")
            if "images" not in context and image.get("verified") is True:
                raise ModelError("Independent image verification required")
            if not nonproduct and not any(p["id"] == image["productId"] and p.get("imageUrl") == image["url"] for p in selected):
                raise ModelError("Unverified product image")
        self._safe_public(result)
        if check_length and not lower <= len(article["content"]) <= upper:
            raise ModelError("Article length outside existing SKILL limits")
        return result

    def polish(self, source, brief, *, article=True):
        _brief(brief)
        if not _text(source):
            raise ModelError("Source content required")
        bounds = ARTICLE_LENGTHS.get(brief['format']) if article else None
        if article and (bounds is None or not bounds[0] <= len(source) <= bounds[1]):
            raise ModelError('Article length outside existing SKILL limits')
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
            "Do not introduce ANY exact literal from brief.protected or brief.requiredExpressions into an eligible "
            "paragraph, even if natural. These forbiddenExpressions must remain ONLY in their original locked paragraphs. "
            "Do not move, copy or repeat them in edits. "
            "Use edits:[] if no correction is needed. Do not grade or approve publication.\n"
            + get_polish_style_prompt(),
            {"source": source, "brief": brief, "forbiddenExpressions": list(dict.fromkeys(fixed)),
             "editable": [{"index": i, "text": paragraphs[i]} for i in eligible]},
            "gemini-3.8-flash", gemini=True)
        if set(result) != {"edits"} or not isinstance(result["edits"], list):
            raise ModelError("Invalid polish edits")
        seen, accepted, rejected = set(), [], []
        for edit in result['edits']:
            if (not isinstance(edit, dict) or set(edit) != {'index','text'}
                    or type(edit['index']) is not int or not 0 <= edit['index'] < len(paragraphs)
                    or edit['index'] in seen or not isinstance(edit['text'], str)):
                raise ModelError('Invalid polish edits')
            index, text = edit['index'], edit['text']; seen.add(index)
            rejection = ('locked_or_ineligible_paragraph' if index not in eligible else
                         'empty_edit' if not text.strip() else
                         'paragraph_boundaries_changed' if re.search(r'(?:\r?\n[ \t]*){2,}', text) else
                         'protected_content_introduced' if _protected(text) else
                         'locked_expression_introduced' if any(token in text for token in fixed) else None)
            if rejection:
                if not article: raise ModelError('Invalid polish edits')
                rejected.append({'index':index,'reason':rejection}); continue
            accepted.append(index); parts[index * 2] = text
        candidate = ''.join(parts)
        rejection = ('whole_candidate_preservation_failed' if inspect_polish(source, candidate)['passed'] is not True else
                     'whole_candidate_length_out_of_bounds' if article and not bounds[0] <= len(candidate) <= bounds[1] else None)
        if rejection:
            if not article: raise ModelError('Polish protected content changed')
            rejected.extend({'index':index,'reason':rejection} for index in accepted)
            accepted, candidate = [], source
        outcome = ('partial' if accepted and rejected else 'edited' if accepted else
                   'no_changes_after_rejection' if rejected else 'no_changes')
        selection = {'actualResponseId':usage['responseId'], 'acceptedIndices':accepted,
                     'rejected':rejected, 'outcome':outcome, 'rawResponseAccepted':not rejected}
        usage['polishEditsApplied'] = len(accepted); usage['polishOutcome'] = outcome
        return {'content':candidate, 'model':usage['model'], 'usage':usage,
                'polishSelection':selection}

    def review(self, bundle, checks):
        article_review = (isinstance(checks, dict) and bool(checks.get('editorialRules'))
                          and checks.get('reviewKind') != 'social')
        try:
            article_schema = article_review_schema(bundle) if article_review else None
        except (ValueError, TypeError, KeyError):
            raise ModelError('Valid article applicability required') from None
        if isinstance(checks, dict) and 'articleMeasurements' in checks:
            article = bundle.get('article') if isinstance(bundle, dict) else None
            brief = bundle.get('brief') if isinstance(bundle, dict) else None
            content = article.get('content') if isinstance(article, dict) else None
            format_name = brief.get('format') if isinstance(brief, dict) else None
            if not isinstance(content, str) or not isinstance(format_name, str) or format_name not in ARTICLE_LENGTHS:
                raise ModelError('Invalid article measurement source')
            lower, upper = ARTICLE_LENGTHS[format_name]
            measured = dict(format=format_name, contentCharacters=len(content), minimumCharacters=lower,
                            maximumCharacters=upper, method='python_len_decoded_article_content')
            supplied = checks['articleMeasurements']
            if (not isinstance(supplied, dict) or supplied != measured or any(
                    type(supplied.get(key)) is not int
                    for key in ('contentCharacters', 'minimumCharacters', 'maximumCharacters'))):
                raise ModelError('Article measurements do not match actual content and format')
            if not lower <= len(content) <= upper:
                raise ModelError('Article length outside existing SKILL limits')
        policy = None
        if isinstance(checks, dict) and checks.get('wisePolicy'):
            policy = load_policy()
            if checks['wisePolicy'] != policy:
                raise ModelError('Owner WISE policy mismatch')
        review_prompt = (
            "Final upper-model review using supplied full bundle, brief, references and independent checks. "
            "When supplied, checks.articleMeasurements is the source of truth for body character count and format bounds; do not infer counts or manufacture scores from it. "
            "When bundle.inheritedPresentationContext exists, its clinicalReverified=false means unchanged template "
            "context, not newly verified medical guidance. Review the revised title/body/FAQs and their consistency "
            "with that inherited advice. Any contradiction is a blocker. The medical flag and evidence for this "
            "revision apply ONLY to candidate article content; never certify inherited clinical accuracy or the "
            "whole visible page as newly clinically verified. Do not remove inherited safety context to pass. "
            "Boolean contract: medical=true means you checked the candidate title/body/FAQs and found no unsupported "
            "medical, drug or child-safety claims; absence of such claims means medical=true after that actual check. "
            "medical=false means a risk or failed check, never N/A or simply that no medical claim was present. "
            "Return {passed:boolean,score:number,facts:boolean,images:boolean,affiliate:boolean,medical:boolean,"
            "render:boolean,evidence:object,issues:list,observations?:list}. Score 0-10; pass threshold 7.5. "
            "issues must contain ONLY required corrections or blockers. Put nonblocking observations in optional "
            "observations, never issues: do not list positive checks such as no medical claim, acknowledged limits "
            "of LLM render verification, or pending future human approval as failures. Do not hide real blockers. "
            "Never certify live images, affiliate destinations or rendering from LLM opinion. Missing independent "
            "evidence must fail. checks.evidence.facts certifies catalog product specifications ONLY; it does not "
            "certify every claim in the article. Independently audit every factual claim and inference in the title, "
            "body, metadata, excerpt and FAQs against the exact catalog records, primary references and, when supplied, "
            "checks.approvedTheme and its Astra constraints. Reject reversed or unsupported product comparisons, "
            "fictional anecdotes or firsthand experience, extrapolation beyond stated measurement conditions, and "
            "price or availability claims without current independent proof. A repeated number or cited URL alone does "
            "not establish the surrounding claim. Mark facts false and passed false, with specific issues, whenever "
            "provenance or approved-theme compliance is missing. Check medical claims and protected brief. "
            "Check source qualifiers in every clause, including each FAQ clause, not just matching numbers: nominal g/h "
            "does not establish maximum/full-power consumption or capacity-to-runtime without explicit sourcing; quoted weights "
            "do not imply fuel/accessory exclusions, approximate battery hours are not upper bounds, and LED count is not brightness. "
            "Handle-excluded dimensions do not establish overall height with the handle, and gotoku diameter does not certify "
            "pan stability or usage instructions. Verify that each explicit prior Astra rejection in checks.approvedSourceSpec "
            "has actually been removed; a blanket assertion of scope compliance is not verification. "
            "Compare checks.sourceContent to the candidate for unchanged meaning and conclusions. "
            "Apply owner WISE-AS: Wit, Insight, Sincere, Empth, AI-free, Sense. Never redefine axes. "
            "Do not impose an automatic score ceiling on Sincere or other axes merely because "
            "verifiedAuthorFacts is empty or the article is a research guide. Sincere may be grounded "
            "in verified evidence and concrete problem-awareness as well as genuine firsthand experience. "
            "Evaluate the actual prose against the pinned anchors; this does not require a high score, "
            "and generic or weakly grounded writing must still receive its earned low score. "
            "When checks.wisePolicy is supplied, use its pinned raw text as the scoring anchors and return "
            "wiseScores={w,i,s,e,ai,sense}, six independent 1-4 scores. Floors are 2,2,2,2,3,2. "
            "Keep this owner gate separate from factual, medical, SEO and affiliate checks. "
            "For social, score those six fields only; article layout/FAQ/length criteria do not apply. "
            "If checks.editorialRules is supplied for an article, apply its WISE/Supervisor rubric and return a nested criteria "
            "object, not flat top-level scores, with eleven numeric 0-10 scores: "
            "wise_w,wise_i,wise_s,wise_e,wise_ai,wise_sense,affiliate_links,"
            "comparison_table,internal_links,faq,word_count. passed=true requires empty issues and the actual "
            "unrounded mean of all eleven criteria to be at least 7.5; never round 7.4545 up. Overall score "
            "must not exceed their mean. Include observations as a list (empty if none) and evidence as exactly "
            "{summary:string}. "
            "When bundle.proposal is present, review that SNS proposal, not the source article as a new draft. "
            "Use checks.publicationReadback for publication status; historical source.article.status is not current. "
            "For images and render, audit consistency of the supplied independent verification records. "
            "For a strictly validated nonproduct bundle, checks.evidence.affiliate is a typed not-applicable "
            "record with measured=false. Treat affiliate=true in this review schema only as confirmation that "
            "the noncommercial applicability contract is valid and no commerce route exists; it is never a "
            "merchant-link measurement or affiliate PASS. "
            "Their flags may pass when those records support them; lack of your own browser is not itself failure. "
            "For SNS, render means verified platform format and length, not re-rendering the source article. "
            "Missing or contradictory independent evidence must still fail; never replace it with model opinion. "
            "For social proposals every claim must be supported by checks.factualSource; numeric/URL checks alone "
            "do not establish factual truth. Reject new claims, changed advertising disclosures or unsupported benefits. "
            "Model assertions are opinions and cannot substitute for external evidence.")
        if article_review:
            review_prompt = review_prompt.replace(
                "Return {passed:boolean,score:number,facts:boolean,images:boolean,affiliate:boolean,medical:boolean,"
                "render:boolean,evidence:object,issues:list,observations?:list}. Score 0-10; pass threshold 7.5. ",
                "Return ONLY the supplied article schema. Never return score or passed. "
                "Evaluate flags, issues, observations, wiseScores and applicable criteria independently. ")
            review_prompt = review_prompt.replace("Mark facts false and passed false, with specific issues, whenever ",
                                                  "Mark facts false with specific issues whenever ")
            start = review_prompt.index("If checks.editorialRules is supplied for an article,")
            end = review_prompt.index("When bundle.proposal is present,", start)
            review_prompt = (review_prompt[:start] +
                "For articles return criteria with exactly the applicable 0-10 fields required by the schema. "
                "The program alone determines applicability, aggregate and admission. Omitted criteria are typed "
                "not_applicable and unmeasured; never assign them 0, 5, 7.5 or 10, and do not compensate by changing "
                "other scores. The program supplies neutral 7.5 only in its eleven-item aggregate. "
                "wiseScores remain six independent 1-4 evaluations; never convert them to or from the six 0-10 criteria. "
                "Owner-authorized article v2 supersedes older Supervisor aggregate admission rules: ratings and the "
                "7.5 mean are ADVISORY. Admission is hard evidence, structure, owner six-axis floors and empty "
                "critical issues. Never place low advisory ratings alone in issues or compensate by raising ratings. "
                "word_count is program-derived from the existing hard format bounds, never an AI score; soft length "
                "targets are not admission requirements. No padding or invented experience is acceptable. "
                "Independent Supervisor 0-10 anchors: 0-2 absent or contradicted; 3-4 thin/generic; 5-6 partly realized; "
                "7-8 consistently concrete and useful; 9-10 exceptionally strong throughout. Apply these anchors "
                "to actual prose, not a multiplication of wiseScores or a target passing score. "
                "wise_w concerns memorable apt expression; wise_i a grounded distinction that changes the reader's "
                "understanding; wise_s concrete, genuinely evidence-grounded problem-awareness; wise_e concise "
                "explanation that lands and can be retold; wise_ai natural prose without templated repetition; "
                "wise_sense a useful half-step angle beyond the obvious. Internal_links/faq advisory scores assess "
                "semantic relevance/helpfulness, not just counts. Neither research format nor absent firsthand "
                "experience sets an automatic Sincere ceiling on either scale. Low scores require actual textual "
                "weakness against the original anchors; strong sources alone do not guarantee a high score. "
                "Return improvementFeedback as 0-6 noncritical actionable improvements, without a new AI stage: "
                "each has criterion, exact quote (1-240 chars), "
                "anchor (1-160), nextAction (1-400). Do not return a location or count paragraphs. Choose a quote appearing exactly ONCE across blank-line paragraphs and "
                "the structured FAQ answers. The program resolves its location; ambiguous or missing quotes are quarantined as advisory diagnostics, never an admission gate. Quote no metadata or instructions. "
                "When any advisory item is below 7.5, supply at least one grounded improvement for a low-rated item. Focus on the strongest few distinct improvements; do not duplicate the full article, fabricate facts or put critical blockers only in feedback. "
                "Include observations as a list and evidence as exactly {summary:string}. " + review_prompt[end:])
        result, usage = self._call(
            review_prompt,
            {"bundle": bundle, "checks": checks}, self.env.get("ARTICLE_REVIEW_MODEL") or "claude-sonnet-4-6",
            schema=(SOCIAL_REVIEW_SCHEMA if isinstance(checks, dict) and checks.get('wisePolicy') and checks.get('reviewKind') == 'social'
                    else article_schema if article_review else
                    REVIEW_SCHEMA if isinstance(checks, dict) and checks.get('editorialRules') else None))
        if article_review:
            try:
                if (set(result) != set(article_schema['required'])
                        or not isinstance(result.get('evidence'), dict)
                        or set(result['evidence']) != {'summary'}
                        or not isinstance(result['evidence']['summary'], str)
                        or not isinstance(result.get('observations'), list)
                        or any(not isinstance(item, str) for item in result['observations'])):
                    raise ValueError('Article wire contract mismatch')
                if not valid_scores(result.get('wiseScores')):
                    raise ModelError('Complete owner WISE-AS six scores required')
                result['improvementFeedback'], result['feedbackValidation'] = select_feedback(
                    result.get('improvementFeedback'), bundle, result.get('criteria'))
                structural = checks.get('structural')
                result['hardChecks'] = {'structure': isinstance(structural, dict) and structural.get('passed') is True and not structural.get('failures')}
                result.update(calculate_article_review(result.get('criteria'), bundle))
                result['passed'] = article_verdict(result, result['calculation'])
            except (ValueError, TypeError, KeyError):
                raise ModelError('Invalid article review contract or applicable scores') from None
        _require(result, ("passed", "score", "evidence", "issues") + CATEGORIES)
        if type(result["passed"]) is not bool or any(type(result[k]) is not bool for k in CATEGORIES) or (
                type(result["score"]) not in (int, float) or not math.isfinite(result["score"]) or
                not 0 <= result["score"] <= 10 or not isinstance(result["issues"], list) or
                not isinstance(result["evidence"], dict)):
            raise ModelError("Invalid review result")
        supplied = checks.get("evidence", checks) if isinstance(checks, dict) else {}
        if policy is not None or article_review:
            if not valid_scores(result.get('wiseScores')):
                raise ModelError('Complete owner WISE-AS six scores required')
            if policy is not None:
                result['wisePolicy'] = policy['id']
            if not passes(result['wiseScores']):
                result['issues'].append('Owner WISE-AS floor failed')
        supplied = supplied if isinstance(supplied, dict) else {}
        affiliate_na = False
        if isinstance(supplied.get('affiliate'), dict):
            try:
                from topic_selection import nonproduct_affiliate_review
                affiliate_na = supplied['affiliate'] == nonproduct_affiliate_review(bundle)
            except (ValueError, TypeError, KeyError):
                affiliate_na = False
        missing = [k for k in CATEGORIES
                   if supplied.get(k) is not True and not (k == 'affiliate' and affiliate_na)]
        for field in missing:
            result[field] = False
            result["issues"].append("Missing independent %s evidence" % field)
        offline_failed = not isinstance(checks, dict) or checks.get("passed") is False or bool(checks.get("failures"))
        if article_review and result['hardChecks']['structure'] is not True:
            result['issues'].append('Independent structural checks failed')
        if offline_failed:
            result["issues"].append("Independent offline checks failed")
        if article_review:
            result['passed'] = article_verdict(result, result['calculation'])
            self.review_diagnostics.append({
                'responseId': usage['responseId'], 'articleId': (bundle.get('article') or {}).get('id'),
                'scoringVersion': result['scoringVersion'], 'admissionMode': result['admissionMode'],
                'criteria': copy.deepcopy(result['criteria']), 'wiseScores': copy.deepcopy(result['wiseScores']),
                'hardChecks': copy.deepcopy(result['hardChecks']),
                'improvementFeedback': copy.deepcopy(result['improvementFeedback']),
                'feedbackValidation': copy.deepcopy(result['feedbackValidation']),
                'applicability': copy.deepcopy(result['applicability']),
                'calculation': copy.deepcopy(result['calculation']),
                'normalizedScore': result['score'], 'normalizedPassed': result['passed'],
                'issues': copy.deepcopy(result['issues'])})
        else:
            result["passed"] = (result["passed"] and result["score"] >= 7.5 and not result["issues"]
                                and all(result[k] is True for k in CATEGORIES) and not missing)
        result["model"] = usage["model"]
        result["evidence"] = {"model": result["evidence"], "checks": copy.deepcopy(checks)}
        return result

    def social(self, bundle, url):
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ModelError("Public HTTPS article URL required")
        _require(bundle, ("article", "images", "publicReadback", "brief"))
        _brief(bundle["brief"])
        _require(bundle["article"], ("content",))
        rb = bundle["publicReadback"]
        _require(rb, ("verified", "url", "content", "images"))
        if rb["verified"] is not True or rb["url"] != url or rb["content"] != bundle["article"]["content"] or rb["images"] != bundle["images"]:
            raise ModelError("Matching public article and images readback required")
        if not isinstance(rb['images'], list) or any(
                not isinstance(image, dict) or image.get('verified') is not True
                or not _text(image.get('url')) for image in rb['images']):
            raise ModelError('Verified public image records required')
        instruction = (
            "Generate an X announcement ONLY after the supplied matching public readback. "
            "Return ONLY {text,replyText}; URL, platform and verified image records are assembled locally. "
            "Main text must contain NO URLs. replyText must be exactly the supplied public article URL, "
            "with no label, Markdown, extra URL or surrounding whitespace. Target at most 160 weighted "
            "characters in text; hard limit 280. Count each ASCII character as 1 and each non-ASCII "
            "character as 2, including Japanese characters and punctuation. Choose only 1-2 supported points. "
            "Do not summarize every product specification or the complete article. Omit unselected facts "
            "rather than compressing all specifications into the announcement. Never truncate facts to fit. "
            "Keep every advertising/affiliate disclosure from the source, including PR when present. "
            "Use the full published article and approved brief as the factual source. Preserve the meaning, "
            "numbers, limits and measurement conditions of every selected claim; omitted facts remain in the source. "
            "Do not introduce any numeric token that does not appear exactly in the published article, including "
            "numeric counts inferred from prose; omit the number instead of converting words into digits. "
            "Never invent personal experience, ownership, friend questions, "
            "user testimonials or unsupported winter performance. Do not claim unknown measurement "
            "conditions differ, infer safety temperatures, or add warming/insulating gas-can advice. "
            "Follow supplied social rules, pinned owner WISE-AS raw text and approved factual constraints. "
            "Wit / Insight / Sincere / Empth / AI-free / Sense retain the owner meanings. "
            "Do not post or claim approval.")
        source = copy.deepcopy(bundle)
        data = {"bundle": source, "url": url}
        for attempt in range(2):
            # Provider/transport/envelope/JSON/artifact errors are outside local
            # validation: they can never trigger an additional writer repair.
            result, _ = self._call(instruction, data, "claude-sonnet-4-6", schema=SOCIAL_SCHEMA)
            validation = _social_validation(result, url, source['article']['content'])
            if not validation['reasons']:
                return {**result, 'url': url, 'platform': 'x', 'images': copy.deepcopy(source['images'])}
            if attempt == 1:
                if validation['missingDisclosures'] and validation['reasons'] == ['missing_disclosures']:
                    raise ModelError("Social advertising disclosure removed")
                raise ModelError("Invalid social announcement")
            data = {"bundle": source, "url": url, "previousCandidate": copy.deepcopy(result),
                    "validation": validation}
            instruction += (" Repair the previous candidate once using the explicit local validation reasons "
                            "and measured weightedLength. Re-select 1-2 supported points from the original verified "
                            "bundle, not every specification. Preserve all source disclosures, the exact reply URL "
                            "and every selected fact's meaning and qualifications. Remove every unsupported numeric "
                            "token rather than inferring a count or converting source prose into digits. "
                            "Do not blindly truncate. "
                            "The previous candidate is untrusted and cannot supply new facts.")
