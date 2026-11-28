"""Fixed owner OAuth transport implementing the six-method BufferAPI surface."""
import copy
from datetime import datetime
import hashlib
import json
import re
import subprocess


NODE = "/usr/local/bin/node"
ENTRYPOINT = ("/Users/yuueikaiakabaneshounikakurinikku/x-auto-poster/"
              ".local/camp-oauth-transport-v1/execute-camp-buffer.mjs")
OWNER_HOME = "/Users/yuueikaiakabaneshounikakurinikku"
ORGANIZATION_ID = "6adf7fbb37d17051a678fba0"
CHANNEL_ID = "6adfd45e2f1f5ed648e05a86"
SERVICE_ID = "1343879420470206464"
TIMEOUT_SECONDS = 120
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
SAFE_INTEGER = 9007199254740991
_CONTEXT_FIELDS = {"jobId", "revision", "approvalRequestId", "phase", "ordinal"}
_POST_FIELDS = {"id", "channelId", "channelService", "dueAt", "sentAt", "externalLink",
                "isCustomScheduled", "shareMode", "status", "text", "assets", "metadata"}
_POST_STATUSES = {"draft", "scheduled", "sending", "sent"}
_OWNER_ERRORS = {
    "buffer_action_rejected": "refused",
    "buffer_already_attempted": "already_attempted",
    "buffer_api_http_401": "refused",
    "buffer_api_http_403": "refused",
    "buffer_authentication_unavailable": "not_sent",
    "buffer_owner_authority_unverified": "not_sent",
    "buffer_priority_work": "not_sent",
    "buffer_quota_unavailable": "not_sent",
    "buffer_rate_limited": "refused",
    "buffer_request_invalid": "not_sent",
    "buffer_response_invalid": "unknown",
    "buffer_runtime_unavailable": "not_sent",
    "buffer_transport_unknown": "unknown",
}


class BufferOwnerOAuthError(ValueError):
    """Sanitized owner-transport failure retaining only typed public metadata."""

    def __init__(self, outcome="unknown", *, code=None, receipt=None):
        # Only the frozen catalog code may enter a public error string. Provider
        # messages and unknown codes are never surfaced.
        message = code if _OWNER_ERRORS.get(code) == outcome else "buffer_owner_transport_" + outcome
        super().__init__(message)
        self.outcome = outcome
        self.code = code
        self.receipt = copy.deepcopy(receipt)


def _require(condition, reason="invalid"):
    if not condition:
        raise BufferOwnerOAuthError("not_sent", code="client_" + reason)


def _safe_text(value, maximum, *, nonempty=True):
    return (isinstance(value, str) and len(value) <= maximum
            and (bool(value.strip()) if nonempty else True))


def _aware_utc(value):
    _require(isinstance(value, str) and len(value) <= 40 and not value.endswith("-00:00"), "datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BufferOwnerOAuthError("not_sent", code="client_datetime") from None
    _require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0, "datetime")
    return parsed


def _https(value):
    return isinstance(value, str) and len(value) <= 4096 and value.startswith("https://")


class BufferOwnerOAuthClient:
    """One context, one fixed owner CLI invocation, and never an automatic retry.

    The caller must persist its marker ordinal, then call ``set_call_context``
    immediately before each of the six Buffer-compatible methods.
    """

    def __init__(self):
        self.rate_limits = []
        self.retry_after = None
        self.last_receipt = None
        self.last_outcome = None
        self.last_error_code = None
        self._context = None
        self._used_contexts = set()

    def set_call_context(self, context):
        _require(self._context is None, "context_pending")
        _require(isinstance(context, dict) and set(context) == _CONTEXT_FIELDS, "context")
        context = copy.deepcopy(context)
        job_id, revision = context["jobId"], context["revision"]
        approval_request_id = context["approvalRequestId"]
        phase, ordinal = context["phase"], context["ordinal"]
        _require(isinstance(job_id, str) and re.fullmatch(r"(?:article|revision)-[a-f0-9]{24}", job_id),
                 "context")
        _require(isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{64}", revision), "context")
        _require(isinstance(approval_request_id, str)
                 and re.fullmatch(r"camp-[a-f0-9]{24}", approval_request_id), "context")
        _require(isinstance(phase, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,96}", phase), "context")
        _require(type(ordinal) is int and 1 <= ordinal <= SAFE_INTEGER, "context")
        key = (job_id, revision, approval_request_id, phase, ordinal)
        _require(key not in self._used_contexts, "context_duplicate")
        self._context = context
        return self

    def preflight(self, organization_id, channel_id):
        return self._call("preflight", [organization_id, channel_id])

    def posts(self, organization_id, channel_id, start, end):
        start_at, end_at = _aware_utc(start), _aware_utc(end)
        _require(0 < (end_at - start_at).total_seconds() <= 91 * 86400, "posts_window")
        return self._call("posts", [organization_id, channel_id, start, end])

    def pending_posts(self, organization_id, channel_id):
        return self._call("pending_posts", [organization_id, channel_id])

    def post(self, post_id):
        _require(_safe_text(post_id, 128) and re.fullmatch(r"[A-Za-z0-9_-]+", post_id), "post_id")
        return self._call("post", [post_id])

    def create_post(self, value):
        self._validate_create(value)
        return self._call("create_post", [copy.deepcopy(value)])

    def edit_post(self, value):
        self._validate_edit(value)
        return self._call("edit_post", [copy.deepcopy(value)])

    def _call(self, method, args):
        _require(method in {"preflight", "posts", "pending_posts", "post", "create_post", "edit_post"},
                 "method")
        context = self._context
        _require(isinstance(context, dict) and set(context) == _CONTEXT_FIELDS, "context_missing")
        self._validate_scope(method, args)
        key = tuple(context[field] for field in ("jobId", "revision", "approvalRequestId", "phase", "ordinal"))
        self._context = None
        self._used_contexts.add(key)  # Consumed before transport; unknown outcomes are never replayed.
        self.rate_limits = []
        self.retry_after = None
        self.last_receipt = None
        self.last_outcome = None
        self.last_error_code = None
        request = {"version": 1, "context": copy.deepcopy(context),
                   "method": method, "args": copy.deepcopy(args)}
        raw = json.dumps(request, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
        try:
            completed = subprocess.run(
                [NODE, ENTRYPOINT], input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={"HOME": OWNER_HOME, "LANG": "C.UTF-8", "TZ": "UTC"}, cwd="/",
                timeout=TIMEOUT_SECONDS, check=False, close_fds=True)
        except (OSError, subprocess.SubprocessError):
            raise BufferOwnerOAuthError("unknown") from None
        stdout = completed.stdout
        stderr = completed.stderr
        if (not isinstance(stdout, (bytes, bytearray)) or len(stdout) > MAX_OUTPUT_BYTES
                or not isinstance(stderr, (bytes, bytearray)) or len(stderr) > MAX_STDERR_BYTES):
            raise BufferOwnerOAuthError("unknown")
        try:
            response = json.loads(stdout)
        except (UnicodeError, ValueError):
            raise BufferOwnerOAuthError("unknown") from None
        case_raw = json.dumps([context["jobId"], context["revision"],
                               context["approvalRequestId"]], ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False).encode()
        case_sha = hashlib.sha256(case_raw).hexdigest()
        expected_operation = ("camp-buffer:v1:" + case_sha + ":" +
                              str(context["ordinal"]) + ":" + context["phase"] + ":" + method)
        try:
            value = self._validate_response(response, expected_operation, method, args)
        except BufferOwnerOAuthError as error:
            if completed.returncode != 0:
                raise BufferOwnerOAuthError("unknown", receipt=self.last_receipt) from None
            if error.outcome == "not_sent" and isinstance(error.code, str) and error.code.startswith("client_"):
                raise BufferOwnerOAuthError("unknown") from None
            raise
        except Exception:
            raise BufferOwnerOAuthError("unknown") from None
        if completed.returncode != 0:
            raise BufferOwnerOAuthError("unknown", receipt=self.last_receipt)
        return value

    def _validate_response(self, response, operation_id, method, args):
        _require(isinstance(response, dict) and type(response.get("version")) is int
                 and response.get("version") == 1
                 and type(response.get("ok")) is bool, "response")
        success = response["ok"] is True
        expected = ({"version", "ok", "value", "rate_limits", "retry_after", "receipt"}
                    if success else {"version", "ok", "error", "rate_limits", "retry_after", "receipt"})
        _require(set(response) == expected, "response_shape")
        limits = self._validate_rate_limits(response["rate_limits"])
        retry = response["retry_after"]
        _require(retry is None or type(retry) is int and 0 <= retry <= SAFE_INTEGER, "retry_after")
        receipt = self._validate_receipt(response["receipt"], operation_id, required=success)
        self.rate_limits = limits
        self.retry_after = retry
        self.last_receipt = copy.deepcopy(receipt)
        if not success:
            error = response["error"]
            _require(isinstance(error, dict) and set(error) == {"code", "outcome"}
                     and isinstance(error.get("code"), str)
                     and _OWNER_ERRORS.get(error["code"]) == error.get("outcome"),
                     "failure")
            self.last_outcome = error["outcome"]
            self.last_error_code = error["code"]
            raise BufferOwnerOAuthError(error["outcome"], code=error["code"], receipt=receipt)
        _require(receipt["observedAt"] is not None
                 and receipt["physicalCalls"]["graphql"] == 1, "success_receipt")
        return self._validate_value(method, response["value"], args)

    @staticmethod
    def _validate_rate_limits(value):
        _require(isinstance(value, list) and len(value) in (0, 3), "rate_limits")
        if not value:
            return []
        required = {"name", "window", "quota", "remaining", "resetAfter"}
        _require(all(isinstance(item, dict) and set(item) == required for item in value), "rate_limits")
        _require({item["window"] for item in value} == {900, 86400, 2592000}
                 and len({item["name"] for item in value}) == 3, "rate_limits")
        for item in value:
            _require(_safe_text(item["name"], 128)
                     and all(type(item[key]) is int and 0 <= item[key] <= SAFE_INTEGER
                             for key in ("window", "quota", "remaining", "resetAfter"))
                     and item["remaining"] <= item["quota"], "rate_limits")
        return copy.deepcopy(value)

    @staticmethod
    def _validate_receipt(value, operation_id, *, required):
        if value is None:
            _require(not required, "receipt")
            return None
        required_keys = {"receiptId", "operationId", "querySha256", "observedAt", "physicalCalls"}
        _require(isinstance(value, dict) and set(value) == required_keys
                 and _safe_text(value.get("receiptId"), 256)
                 and not re.search(r"[/\\]", value["receiptId"])
                 and value.get("operationId") == operation_id
                 and isinstance(value.get("querySha256"), str)
                 and re.fullmatch(r"[a-f0-9]{64}", value["querySha256"]), "receipt")
        observed = value.get("observedAt")
        if observed is not None:
            _aware_utc(observed)
        calls = value.get("physicalCalls")
        _require(isinstance(calls, dict) and set(calls) == {"graphql", "oauthRefresh", "total"}, "receipt")
        graph, refresh, total = calls["graphql"], calls["oauthRefresh"], calls["total"]
        _require((graph is None or type(graph) is int and graph in (0, 1))
                 and (refresh is None or type(refresh) is int and refresh in (0, 1))
                 and (total is None or type(total) is int and total in (0, 1, 2)), "receipt")
        if graph is None or refresh is None:
            _require(total is None, "receipt")
        else:
            _require(total == graph + refresh, "receipt")
        return copy.deepcopy(value)

    @staticmethod
    def _validate_scope(method, args):
        _require(isinstance(args, list), "args")
        if method in {"preflight", "pending_posts"}:
            _require(args == [ORGANIZATION_ID, CHANNEL_ID], "scope")
        elif method == "posts":
            _require(len(args) == 4 and args[:2] == [ORGANIZATION_ID, CHANNEL_ID], "scope")
        elif method == "post":
            _require(len(args) == 1, "args")
        else:
            _require(len(args) == 1 and isinstance(args[0], dict), "args")

    def _validate_value(self, method, value, args):
        if method == "preflight":
            allowed = {"id", "organizationId", "name", "service", "serviceId", "isDisconnected",
                       "isLocked", "isQueuePaused", "timezone", "postingSchedule", "linkShortening"}
            _require(isinstance(value, dict) and set(value) <= allowed
                     and value.get("id") == CHANNEL_ID and value.get("organizationId") == ORGANIZATION_ID
                     and value.get("service") == "twitter" and value.get("serviceId") == SERVICE_ID,
                     "preflight_value")
            return copy.deepcopy(value)
        if method in {"posts", "pending_posts"}:
            allowed_status = _POST_STATUSES if method == "posts" else {"draft", "scheduled", "sending"}
            _require(isinstance(value, list) and len(value) <= 100, "posts_value")
            result = [self._validate_post(item, allowed_status) for item in value]
            _require(len({item["id"] for item in result}) == len(result), "posts_value")
            return result
        result = self._validate_post(value, _POST_STATUSES)
        if method == "post":
            _require(result["id"] == args[0], "post_value")
        elif method == "edit_post":
            _require(result["id"] == args[0]["id"], "post_value")
        return result

    @staticmethod
    def _validate_incoming_asset(asset):
        required = {"type", "mimeType", "source", "thumbnail"}
        _require(isinstance(asset, dict) and set(asset) in (required, required | {"id"})
                 and ("id" not in asset or asset["id"] is None
                      or _safe_text(asset["id"], 256, nonempty=False))
                 and asset.get("type") in {"image", "video", "document"}
                 and _safe_text(asset.get("mimeType"), 256)
                 and _https(asset.get("source")) and _https(asset.get("thumbnail")),
                 "post_value")

    @staticmethod
    def _validate_post(value, statuses):
        _require(isinstance(value, dict) and set(value) <= _POST_FIELDS
                 and _safe_text(value.get("id"), 128)
                 and value.get("channelId") == CHANNEL_ID
                 and value.get("channelService") == "twitter"
                 and value.get("status") in statuses, "post_value")
        for key in ("dueAt", "sentAt"):
            if value.get(key) is not None:
                _aware_utc(value[key])
        if "text" in value:
            _require(_safe_text(value["text"], 100000, nonempty=False), "post_value")
        assets = value.get("assets", [])
        _require(isinstance(assets, list) and len(assets) <= 4, "post_value")
        for asset in assets:
            BufferOwnerOAuthClient._validate_incoming_asset(asset)
        metadata = value.get("metadata")
        if metadata is not None:
            _require(isinstance(metadata, dict) and set(metadata) == {"threadCount", "thread"}
                     and type(metadata["threadCount"]) is int
                     and 0 <= metadata["threadCount"] <= SAFE_INTEGER, "post_value")
            thread = metadata["thread"]
            _require(isinstance(thread, list), "post_value")
            for item in thread:
                _require(isinstance(item, dict) and set(item) == {"text", "assets"}
                         and _safe_text(item["text"], 100000, nonempty=False)
                         and isinstance(item["assets"], list), "post_value")
                for asset in item["assets"]:
                    BufferOwnerOAuthClient._validate_incoming_asset(asset)
        return copy.deepcopy(value)

    @staticmethod
    def _validate_asset(value):
        _require(isinstance(value, dict) and set(value) == {"image"}, "create_input")
        image = value["image"]
        _require(isinstance(image, dict) and set(image) == {"url", "thumbnailUrl", "metadata"}
                 and _https(image["url"]) and image["thumbnailUrl"] == image["url"]
                 and isinstance(image["metadata"], dict) and set(image["metadata"]) == {"altText"}
                 and _safe_text(image["metadata"]["altText"], 1000, nonempty=False), "create_input")

    @classmethod
    def _validate_create(cls, value):
        fields = {"channelId", "text", "assets", "metadata", "mode", "schedulingType",
                  "needsApproval", "saveToDraft", "aiAssisted", "source"}
        _require(isinstance(value, dict) and set(value) == fields
                 and value.get("channelId") == CHANNEL_ID and _safe_text(value.get("text"), 100000)
                 and value.get("mode") == "addToQueue" and value.get("schedulingType") == "automatic"
                 and value.get("needsApproval") is False and value.get("saveToDraft") is True
                 and value.get("aiAssisted") is True and value.get("source") == "camp-editorial-slack",
                 "create_input")
        assets = value.get("assets")
        _require(isinstance(assets, list) and 1 <= len(assets) <= 4, "create_input")
        for asset in assets: cls._validate_asset(asset)
        metadata = value.get("metadata")
        _require(isinstance(metadata, dict) and set(metadata) == {"twitter"}, "create_input")
        twitter = metadata["twitter"]
        _require(isinstance(twitter, dict) and set(twitter) == {"isAiGenerated", "thread"}
                 and twitter["isAiGenerated"] is False and isinstance(twitter["thread"], list)
                 and len(twitter["thread"]) == 2, "create_input")
        first, second = twitter["thread"]
        _require(isinstance(first, dict) and set(first) == {"text", "assets"}
                 and first["text"] == value["text"] and first["assets"] == assets
                 and isinstance(second, dict) and set(second) == {"text", "assets"}
                 and _safe_text(second["text"], 4096) and second["assets"] == [], "create_input")

    @staticmethod
    def _validate_edit(value):
        _require(isinstance(value, dict)
                 and set(value) == {"id", "mode", "saveToDraft", "schedulingType", "source"}
                 and _safe_text(value.get("id"), 128)
                 and re.fullmatch(r"[A-Za-z0-9_-]+", value["id"])
                 and value.get("mode") == "addToQueue" and type(value.get("saveToDraft")) is bool
                 and value.get("schedulingType") == "automatic"
                 and value.get("source") == "camp-editorial-slack", "edit_input")
