import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from buffer_publisher import BufferPublisher
from buffer_owner_oauth_client import (
    BufferOwnerOAuthClient,
    BufferOwnerOAuthError,
    CHANNEL_ID,
    ENTRYPOINT,
    NODE,
    ORGANIZATION_ID,
    OWNER_HOME,
    SERVICE_ID,
)


CONTEXT = {
    "jobId": "article-" + "1" * 24,
    "revision": "a" * 64,
    "approvalRequestId": "camp-" + "2" * 24,
    "phase": "fixture",
    "ordinal": 1,
}


def operation_id(method, context=CONTEXT):
    raw = json.dumps(
        [context["jobId"], context["revision"], context["approvalRequestId"]],
        separators=(",", ":"),
    ).encode()
    return "camp-buffer:v1:{}:{}:{}:{}".format(
        hashlib.sha256(raw).hexdigest(), context["ordinal"], context["phase"], method
    )


def limits():
    return [
        {"name": "short", "window": 900, "quota": 100, "remaining": 91, "resetAfter": 12},
        {"name": "daily", "window": 86400, "quota": 1000, "remaining": 901, "resetAfter": 20},
        {"name": "monthly", "window": 2592000, "quota": 3000, "remaining": 2901,
         "resetAfter": 30},
    ]


def receipt(method, context=CONTEXT, calls=None):
    return {
        "receiptId": "fixture-only",
        "operationId": operation_id(method, context),
        "querySha256": "c" * 64,
        "observedAt": "2026-11-29T00:00:00Z",
        "physicalCalls": calls or {"graphql": 1, "oauthRefresh": 0, "total": 1},
    }


def success(method, value, context=CONTEXT, rate_limits=None):
    return {
        "version": 1,
        "ok": True,
        "value": value,
        "rate_limits": limits() if rate_limits is None else rate_limits,
        "retry_after": None,
        "receipt": receipt(method, context),
    }


def failure(method, outcome="refused", code="buffer_api_http_401", context=CONTEXT,
            failure_receipt=None, retry_after=60):
    return {
        "version": 1,
        "ok": False,
        "error": {"code": code, "outcome": outcome},
        "rate_limits": [],
        "retry_after": retry_after,
        "receipt": failure_receipt,
    }


def completed(value, returncode=0, stderr=b""):
    return subprocess.CompletedProcess(
        [NODE, ENTRYPOINT], returncode, json.dumps(value, separators=(",", ":")).encode(), stderr
    )


def post_value(identifier="post_1", status="draft"):
    return {
        "id": identifier,
        "channelId": CHANNEL_ID,
        "channelService": "twitter",
        "status": status,
        "dueAt": None,
        "sentAt": None,
        "text": "本文",
        "assets": [],
    }


def incoming_asset(identifier=None):
    return {
        "id": identifier,
        "type": "image",
        "mimeType": "image/png",
        "source": "https://example.com/source.png",
        "thumbnail": "https://example.com/thumbnail.png",
    }


def channel_value():
    return {
        "id": CHANNEL_ID,
        "organizationId": ORGANIZATION_ID,
        "name": "Camp Gear Lab",
        "service": "twitter",
        "serviceId": SERVICE_ID,
        "isDisconnected": False,
        "isLocked": False,
        "isQueuePaused": False,
        "timezone": "Asia/Tokyo",
        "postingSchedule": [],
        "linkShortening": {"isEnabled": False},
    }


def create_value():
    asset = {
        "image": {
            "url": "https://example.com/card.png",
            "thumbnailUrl": "https://example.com/card.png",
            "metadata": {"altText": "記事カード"},
        }
    }
    return {
        "channelId": CHANNEL_ID,
        "text": "本文",
        "assets": [asset],
        "metadata": {
            "twitter": {
                "isAiGenerated": False,
                "thread": [
                    {"text": "本文", "assets": [copy.deepcopy(asset)]},
                    {"text": "https://campgearlab.com/article", "assets": []},
                ],
            }
        },
        "mode": "addToQueue",
        "schedulingType": "automatic",
        "needsApproval": False,
        "saveToDraft": True,
        "aiAssisted": True,
        "source": "camp-editorial-slack",
    }


class BufferOwnerOAuthClientTests(unittest.TestCase):
    def client(self, context=None):
        client = BufferOwnerOAuthClient()
        client.set_call_context(copy.deepcopy(context or CONTEXT))
        return client

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_real_publisher_buffer_call_persists_context_before_fixed_cli(self, run):
        state = {
            "jobId": CONTEXT["jobId"],
            "revision": CONTEXT["revision"],
            "approvalRequestId": CONTEXT["approvalRequestId"],
            "phase": CONTEXT["phase"],
            "bufferRequests": 0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os.chmod(root, 0o700)
            marker = root / "marker.json"
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream)

            def owner_cli(command, **kwargs):
                self.assertEqual(command, [NODE, ENTRYPOINT])
                saved = json.loads(marker.read_text())
                request = json.loads(kwargs["input"])
                self.assertEqual(saved["bufferRequests"], 1)
                self.assertEqual(request["context"], {**CONTEXT, "ordinal": 1})
                response = success("pending_posts", [], request["context"], rate_limits=[])
                self.assertEqual(response["receipt"]["operationId"],
                                 operation_id("pending_posts", request["context"]))
                return completed(response)

            run.side_effect = owner_cli
            publisher = object.__new__(BufferPublisher)
            publisher.settings = {"maxBufferRequestsPerPost": 18}
            publisher.client = BufferOwnerOAuthClient()
            self.assertEqual(publisher._buffer_call(
                marker, state, "pending_posts", ORGANIZATION_ID, CHANNEL_ID
            ), [])
            self.assertEqual(run.call_count, 1)
            self.assertEqual(json.loads(marker.read_text())["bufferRequests"], 1)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_fixture_operation_fixed_cli_minimal_environment_and_rates(self, run):
        run.return_value = completed(success("pending_posts", [], rate_limits=limits()))
        client = self.client()
        self.assertEqual(client.pending_posts(ORGANIZATION_ID, CHANNEL_ID), [])
        self.assertEqual(client.rate_limits, limits())
        self.assertIsNone(client.retry_after)
        args, kwargs = run.call_args
        self.assertEqual(args[0], [NODE, ENTRYPOINT])
        self.assertEqual(kwargs["env"], {"HOME": OWNER_HOME, "LANG": "C.UTF-8", "TZ": "UTC"})
        self.assertEqual(kwargs["cwd"], "/")
        self.assertEqual(kwargs["timeout"], 120)
        self.assertFalse(kwargs["check"])
        self.assertTrue(kwargs["close_fds"])
        request = json.loads(kwargs["input"])
        self.assertEqual(request, {
            "version": 1,
            "context": CONTEXT,
            "method": "pending_posts",
            "args": [ORGANIZATION_ID, CHANNEL_ID],
        })
        self.assertEqual(operation_id("pending_posts"),
                         "camp-buffer:v1:4c02496c3b1fe3b896176c34538e0700b295aa167776cd180622aad482892dd1:1:fixture:pending_posts")

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_six_method_surface_and_positional_arguments(self, run):
        cases = [
            ("preflight", (ORGANIZATION_ID, CHANNEL_ID), channel_value()),
            ("posts", (ORGANIZATION_ID, CHANNEL_ID,
                       "2026-11-01T00:00:00Z", "2026-11-29T00:00:00Z"), [post_value()]),
            ("pending_posts", (ORGANIZATION_ID, CHANNEL_ID), [post_value()]),
            ("post", ("post_1",), post_value()),
            ("create_post", (create_value(),), post_value()),
            ("edit_post", ({"id": "post_1", "mode": "addToQueue", "saveToDraft": False,
                            "schedulingType": "automatic", "source": "camp-editorial-slack"},),
             post_value(status="scheduled")),
        ]
        for ordinal, (method, args, value) in enumerate(cases, 1):
            with self.subTest(method=method):
                context = {**CONTEXT, "ordinal": ordinal}
                run.return_value = completed(success(method, value, context))
                client = self.client(context)
                self.assertEqual(getattr(client, method)(*copy.deepcopy(args)), value)
                request = json.loads(run.call_args.kwargs["input"])
                self.assertEqual(request["method"], method)
                self.assertEqual(request["args"], list(args))
                self.assertEqual(request["context"], context)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_context_dict_is_copied_and_duplicate_or_pending_context_is_denied(self, run):
        supplied = copy.deepcopy(CONTEXT)
        client = BufferOwnerOAuthClient().set_call_context(supplied)
        supplied["phase"] = "tampered"
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_not_sent"):
            client.set_call_context(copy.deepcopy(CONTEXT))
        run.return_value = completed(success("pending_posts", []))
        client.pending_posts(ORGANIZATION_ID, CHANNEL_ID)
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["context"]["phase"], "fixture")
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_not_sent"):
            client.set_call_context(copy.deepcopy(CONTEXT))

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_timeout_consumes_context_once_and_never_retries(self, run):
        run.side_effect = subprocess.TimeoutExpired([NODE, ENTRYPOINT], 120)
        client = self.client()
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            client.pending_posts(ORGANIZATION_ID, CHANNEL_ID)
        self.assertEqual(run.call_count, 1)
        with self.assertRaises(BufferOwnerOAuthError):
            client.pending_posts(ORGANIZATION_ID, CHANNEL_ID)
        with self.assertRaises(BufferOwnerOAuthError):
            client.set_call_context(copy.deepcopy(CONTEXT))
        self.assertEqual(run.call_count, 1)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_structured_401_is_refused_without_retry(self, run):
        run.return_value = completed(failure("pending_posts"))
        client = self.client()
        with self.assertRaises(BufferOwnerOAuthError) as raised:
            client.pending_posts(ORGANIZATION_ID, CHANNEL_ID)
        self.assertEqual((raised.exception.outcome, raised.exception.code),
                         ("refused", "buffer_api_http_401"))
        self.assertEqual(str(raised.exception), "buffer_api_http_401")
        self.assertEqual((client.last_outcome, client.last_error_code),
                         ("refused", "buffer_api_http_401"))
        self.assertEqual(client.retry_after, 60)
        self.assertEqual(run.call_count, 1)

        context = {**CONTEXT, "ordinal": 2}
        run.return_value = completed(failure("pending_posts", context=context), returncode=1)
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).pending_posts(ORGANIZATION_ID, CHANNEL_ID)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_mutation_unknown_receipt_is_retained_and_not_replayed(self, run):
        unknown_receipt = receipt(
            "create_post", calls={"graphql": None, "oauthRefresh": None, "total": None}
        )
        run.return_value = completed(failure(
            "create_post", "unknown", "buffer_transport_unknown",
            failure_receipt=unknown_receipt, retry_after=None,
        ))
        client = self.client()
        with self.assertRaises(BufferOwnerOAuthError) as raised:
            client.create_post(create_value())
        self.assertEqual(raised.exception.outcome, "unknown")
        self.assertEqual(raised.exception.receipt, unknown_receipt)
        self.assertEqual(client.last_receipt, unknown_receipt)
        self.assertEqual((client.last_outcome, client.last_error_code),
                         ("unknown", "buffer_transport_unknown"))
        self.assertEqual(run.call_count, 1)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_partial_receipt_wrong_operation_and_nonzero_exit_are_unknown(self, run):
        malformed = success("pending_posts", [])
        del malformed["receipt"]["physicalCalls"]["total"]
        run.return_value = completed(malformed)
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client().pending_posts(ORGANIZATION_ID, CHANNEL_ID)

        wrong = success("pending_posts", [])
        wrong["receipt"]["operationId"] += "x"
        run.return_value = completed(wrong)
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client({**CONTEXT, "ordinal": 2}).pending_posts(ORGANIZATION_ID, CHANNEL_ID)

        context = {**CONTEXT, "ordinal": 3}
        run.return_value = completed(success("pending_posts", [], context), returncode=1,
                                     stderr=b"secret must not escape")
        with self.assertRaises(BufferOwnerOAuthError) as raised:
            self.client(context).pending_posts(ORGANIZATION_ID, CHANNEL_ID)
        self.assertEqual(str(raised.exception), "buffer_owner_transport_unknown")

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_post_cap_rate_shape_and_boolean_call_counts_fail_closed(self, run):
        run.return_value = completed(success("posts", [post_value("p" + str(i)) for i in range(101)]))
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client().posts(ORGANIZATION_ID, CHANNEL_ID,
                                "2026-11-01T00:00:00Z", "2026-11-29T00:00:00Z")

        context = {**CONTEXT, "ordinal": 2}
        run.return_value = completed(success("pending_posts", [], context, rate_limits=limits()[:2]))
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).pending_posts(ORGANIZATION_ID, CHANNEL_ID)

        context = {**CONTEXT, "ordinal": 4}
        untrusted = failure("pending_posts", "refused", "raw_provider_message", context)
        run.return_value = completed(untrusted)
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).pending_posts(ORGANIZATION_ID, CHANNEL_ID)

        context = {**CONTEXT, "ordinal": 5}
        mismatched = failure("pending_posts", "unknown", "buffer_api_http_401", context)
        run.return_value = completed(mismatched)
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).pending_posts(ORGANIZATION_ID, CHANNEL_ID)

        context = {**CONTEXT, "ordinal": 3}
        invalid = success("pending_posts", [], context)
        invalid["receipt"]["physicalCalls"] = {"graphql": True, "oauthRefresh": 0, "total": 1}
        run.return_value = completed(invalid)
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).pending_posts(ORGANIZATION_ID, CHANNEL_ID)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_unsafe_inputs_stop_before_subprocess(self, run):
        invalid_contexts = [
            {**CONTEXT, "extra": 1},
            {**CONTEXT, "jobId": "article-nothex"},
            {**CONTEXT, "revision": "A" * 64},
            {**CONTEXT, "approvalRequestId": "camp-../secret"},
            {**CONTEXT, "phase": "bad phase"},
            {**CONTEXT, "ordinal": True},
        ]
        for context in invalid_contexts:
            with self.subTest(context=context):
                with self.assertRaises(BufferOwnerOAuthError):
                    BufferOwnerOAuthClient().set_call_context(context)
        with self.assertRaises(BufferOwnerOAuthError):
            self.client().pending_posts("wrong", CHANNEL_ID)
        with self.assertRaises(BufferOwnerOAuthError):
            self.client({**CONTEXT, "ordinal": 2}).posts(
                ORGANIZATION_ID, CHANNEL_ID, "2026-11-01T00:00:00", "2026-11-29T00:00:00Z"
            )
        with self.assertRaises(BufferOwnerOAuthError):
            self.client({**CONTEXT, "ordinal": 3}).posts(
                ORGANIZATION_ID, CHANNEL_ID, "2026-01-01T00:00:00Z", "2026-11-29T00:00:00Z"
            )
        with self.assertRaises(BufferOwnerOAuthError):
            self.client({**CONTEXT, "ordinal": 4}).post("../../secret")
        self.assertEqual(run.call_count, 0)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_mutation_shape_is_exact_and_invalid_input_is_not_sent(self, run):
        value = create_value()
        value["dueAt"] = "2026-11-30T00:00:00Z"
        client = self.client()
        with self.assertRaises(BufferOwnerOAuthError):
            client.create_post(value)
        self.assertEqual(run.call_count, 0)

        three_part = create_value()
        three_part["metadata"]["twitter"]["thread"].append(
            {"text": "third", "assets": []}
        )
        with self.assertRaises(BufferOwnerOAuthError):
            self.client({**CONTEXT, "ordinal": 3}).create_post(three_part)
        self.assertEqual(run.call_count, 0)

        context = {**CONTEXT, "ordinal": 4}
        bad_edit = {"id": "post_1", "mode": "addToQueue", "saveToDraft": False,
                    "schedulingType": "automatic", "source": "other"}
        with self.assertRaises(BufferOwnerOAuthError):
            self.client(context).edit_post(bad_edit)
        self.assertEqual(run.call_count, 0)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_incoming_three_part_thread_and_nullable_asset_ids_are_valid(self, run):
        value = post_value()
        value["assets"] = [incoming_asset(None)]
        without_id = incoming_asset()
        del without_id["id"]
        value["metadata"] = {
            "threadCount": 3,
            "thread": [
                {"text": "first", "assets": [incoming_asset(None)]},
                {"text": "second", "assets": [without_id]},
                {"text": "third", "assets": []},
            ],
        }
        run.return_value = completed(success("pending_posts", [value]))
        result = self.client().pending_posts(ORGANIZATION_ID, CHANNEL_ID)
        self.assertIsNone(result[0]["assets"][0]["id"])
        self.assertEqual(len(result[0]["metadata"]["thread"]), 3)
        self.assertIsNone(result[0]["metadata"]["thread"][0]["assets"][0]["id"])
        self.assertNotIn("id", result[0]["metadata"]["thread"][1]["assets"][0])

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_boolean_version_and_wrong_post_or_edit_ids_are_unknown(self, run):
        invalid_version = success("pending_posts", [])
        invalid_version["version"] = True
        run.return_value = completed(invalid_version)
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client().pending_posts(ORGANIZATION_ID, CHANNEL_ID)

        context = {**CONTEXT, "ordinal": 2}
        run.return_value = completed(success("post", post_value("other"), context))
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).post("post_1")

        context = {**CONTEXT, "ordinal": 3}
        edit = {"id": "post_1", "mode": "addToQueue", "saveToDraft": False,
                "schedulingType": "automatic", "source": "camp-editorial-slack"}
        run.return_value = completed(success("edit_post", post_value("other"), context))
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).edit_post(edit)

    @patch("buffer_owner_oauth_client.subprocess.run")
    def test_bounded_output_and_response_binding_are_unknown_without_leaks(self, run):
        run.return_value = subprocess.CompletedProcess([NODE, ENTRYPOINT], 0, b"x" * (2 * 1024 * 1024 + 1), b"")
        with self.assertRaises(BufferOwnerOAuthError) as raised:
            self.client().pending_posts(ORGANIZATION_ID, CHANNEL_ID)
        self.assertNotIn("xxx", str(raised.exception))

        context = {**CONTEXT, "ordinal": 2}
        wrong_post = post_value()
        wrong_post["channelId"] = "other"
        run.return_value = completed(success("post", wrong_post, context))
        with self.assertRaisesRegex(BufferOwnerOAuthError, "buffer_owner_transport_unknown"):
            self.client(context).post("post_1")


if __name__ == "__main__":
    unittest.main()
