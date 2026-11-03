"""Offline provider contract and fail-closed model tests (Python 3.9 stdlib)."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from models import Models, ModelError


ENV = {"ANTHROPIC_API_KEY": "test-claude-key", "GEMINI_API_KEY": "test-gemini-key"}


def brief():
    return dict(purpose="Help choose", reader="Beginners", conclusion="Choose by use",
                headings=["Choice"], facts=["Weight 2kg"], numbers=["2kg"],
                links=["https://maker.example/tent"], requiredExpressions=["広告"],
                protected=["{{product:tent-a}}"], style="Warm", length="3000-5000",
                cta="Check details", format="guide", externalSafe=True)


def bundle():
    return dict(article={"id": "a1", "title": "Tent", "content": "広告\n## Choice\nWeight 2kg {{product:tent-a}}\n"
                                    "[設営](/articles/setup) [撤収](/articles/pack)\n" + "検証済みの説明です。" * 350,
                         "productIds": ["tent-a"], "slug": "tent-guide", "categoryId": "tent",
                         "excerpt": "用途と重さを確かめて自分に合うテントを選びます。",
                         "metaDescription": "用途と重さを確かめて自分に合うテントを選ぶための調査記事です。" * 2,
                         "faqs": [{"question": "重さは？", "answer": "2kgです。"}] * 3,
                         "tags": ["tent"], "author": "ギア男"},
                products=[{"id": "tent-a", "specs": {"weight": "2kg"}, "imageUrl": "https://images.example/a.jpg"}],
                brief=brief(), references=[{"url": "https://maker.example/tent"}],
                images=[{"productId": "tent-a", "url": "https://images.example/a.jpg"}])


def context():
    b = bundle()
    return dict(catalog=b["products"], references=b["references"], images=b["images"],
                CLAUDE="Article template: no H1", SKILL="WISE score at least 7.5",
                gsc=[{"query": "winter tent weight", "impressions": 123}],
                season="winter", merchantClicks=[{"productId": "tent-a", "clicks": 8}])


def response(value, gemini=False, raw=None):
    content = raw if raw is not None else json.dumps(value)
    if gemini:
        return {"id": "g-1", "model": "gemini-3.8-flash", "usage": {"prompt_tokens": 31, "completion_tokens": 9},
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    return {"id": "c-1", "model": "claude-sonnet-4-6", "usage": {"input_tokens": 31, "output_tokens": 9},
            "content": [{"type": "text", "text": content}], "stop_reason": "end_turn"}


class Fake:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, copy.deepcopy(headers), copy.deepcopy(payload), timeout))
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def http(code):
    return HTTPError("https://provider.invalid", code, "test-claude-key SECRET BODY", {}, io.BytesIO(b"secret"))


THEMES = {"themes": [{"slug": "theme-%d" % i, "title": title, "query": title.lower(),
                       "categoryId": "tent", "selectionReason": "Season and verified catalog",
                       "productIds": ["tent-a"], "evidence": {"season": "winter"}}
                      for i, title in enumerate(("Winter tent weight choice", "Rain tent packing tips", "Family tent setup size"))]}
REVIEW = dict(passed=True, score=8.5, facts=True, images=True, affiliate=True, medical=True,
              render=True, evidence={"claim": "model opinion"}, issues=[])
FLAGS = dict(facts=True, images=True, affiliate=True, medical=True, render=True)


class ModelTests(unittest.TestCase):
    def test_research_rejects_unmeasured_firsthand_title(self):
        themes = copy.deepcopy(THEMES)
        themes['themes'][0]['title'] = '冬のバーナー実測結果'
        with self.assertRaisesRegex(ModelError, 'Unverified firsthand'):
            Models(ENV, Fake(response(themes))).research(context())

    def test_editorial_rubric_requires_all_scores_and_caps_overall_mean(self):
        checks = {'editorialRules': 'WISE Supervisor eleven criteria', 'evidence': FLAGS}
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(REVIEW))).review(bundle(), checks)
        result = copy.deepcopy(REVIEW)
        result['criteria'] = dict.fromkeys(('wise_w', 'wise_i', 'wise_s', 'wise_e', 'wise_ai', 'wise_sense',
            'affiliate_links', 'comparison_table', 'internal_links', 'faq', 'word_count'), 7)
        reviewed = Models(ENV, Fake(response(result))).review(bundle(), checks)
        self.assertFalse(reviewed['passed'])
        self.assertEqual(7, reviewed['score'])

    def test_research_complete_evidence_headers_usage(self):
        ctx = context()
        ctx["longEvidence"] = "z" * 12000 + "END-EVIDENCE"
        fake = Fake(response(THEMES))
        model = Models(ENV, fake)
        self.assertEqual(model.research(ctx), THEMES)
        url, headers, payload, timeout = fake.calls[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["x-api-key"], ENV["ANTHROPIC_API_KEY"])
        self.assertEqual(payload["model"], "claude-sonnet-4-6")
        self.assertIn("END-EVIDENCE", payload["messages"][0]["content"])
        self.assertLessEqual(timeout, 180)
        self.assertEqual(model.usage, [{"responseId": "c-1", "model": "claude-sonnet-4-6", "input": 31,
                                      "output": 9, "usage": {"input_tokens": 31, "output_tokens": 9}, "actualUSD": None}])

    def test_research_rejects_duplicates_wrong_count_and_existing_title(self):
        for value, ctx in [({"themes": []}, {}), ({"themes": [{"title": "same"}] * 3}, {}),
                           (THEMES, {"existingArticles": [{"title": "Winter tent weight choice"}]})]:
            with self.subTest(value=value):
                with self.assertRaises(ModelError):
                    Models(ENV, Fake(response(value))).research(ctx)

    def test_draft_404_only_fallback_preserves_full_bundle(self):
        fake = Fake(http(404), response(bundle()))
        model = Models(ENV, fake)
        self.assertEqual(model.draft(THEMES["themes"][0], context()), bundle())
        self.assertEqual([c[2]["model"] for c in fake.calls], ["claude-opus-4-8", "claude-sonnet-4-6"])
        self.assertIn("Article template: no H1", fake.calls[-1][2]["messages"][0]["content"])

    def test_overrides_and_nonretry_auth_bad_request(self):
        for status in (400, 401, 500):
            fake = Fake(http(status))
            with self.assertRaises(ModelError) as caught:
                Models(ENV, fake).draft({}, context())
            self.assertEqual(len(fake.calls), 1)
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertNotIn("test-claude-key", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
        env = dict(ENV, ARTICLE_WRITER_MODEL="writer", ARTICLE_WRITER_FALLBACK_MODEL="fallback", ARTICLE_REVIEW_MODEL="reviewer")
        fake = Fake(http(404), response(bundle()), response(REVIEW))
        model = Models(env, fake)
        model.draft({}, context())
        model.review(bundle(), FLAGS)
        self.assertEqual([c[2]["model"] for c in fake.calls], ["writer", "fallback", "reviewer"])

    def test_retry_bounded_on_only_429_503(self):
        for code in (429, 503):
            fake = Fake(http(code), http(code), response(THEMES))
            with patch("models.time.sleep"):
                self.assertEqual(Models(ENV, fake).research({}), THEMES)
            self.assertEqual(len(fake.calls), 3)
            fake = Fake(http(code), http(code), http(code), response(THEMES))
            with patch("models.time.sleep"), self.assertRaises(ModelError):
                Models(ENV, fake).research({})
            self.assertEqual(len(fake.calls), 3)

    def test_total_deadline_includes_fallback(self):
        fake = Fake(http(404), response(bundle()))
        with patch("models.time.monotonic", side_effect=[0, 0, 181]), self.assertRaises(ModelError):
            Models(ENV, fake).draft({}, context())
        self.assertEqual(len(fake.calls), 1)

    def test_strict_json_no_fences_trailing_text_nonfinite_or_duplicate_keys(self):
        for raw in ('```json\n{}\n```', '{} trailing', '{"themes":NaN}', '{"themes": [], "themes": []}', '[]'):
            with self.subTest(raw=raw), self.assertRaises(ModelError):
                Models(ENV, Fake(response(None, raw=raw))).research({})

    def test_no_missing_bundle_fields_or_invented_products_references(self):
        mutations = [lambda b: b.pop("brief"), lambda b: b["brief"].pop("facts"),
                     lambda b: b["brief"].update(externalSafe="true"),
                     lambda b: b["article"].update(productIds=["ghost"]),
                     lambda b: b["products"][0].update(price=100),
                     lambda b: b["references"].append({"url": "https://invented.example"}),
                     lambda b: b["images"][0].update(url="https://invented.example/a.jpg")]
        for mutate in mutations:
            b = bundle()
            mutate(b)
            with self.subTest(b=b), self.assertRaises(ModelError):
                Models(ENV, Fake(response(b))).draft({}, context())

    def test_polish_full_brief_source_unchanged_fixed_endpoint_and_usage(self):
        b = brief()
        b["protected"].append("TAIL" * 3000)
        before = copy.deepcopy(b)
        fake = Fake(response({"content": "Polished"}, gemini=True))
        model = Models(ENV, fake)
        result = model.polish("Original", b)
        self.assertEqual(result["content"], "Polished")
        self.assertEqual(result["model"], "gemini-3.8-flash")
        self.assertEqual(result["usage"]["output"], 9)
        self.assertEqual(b, before)
        self.assertEqual(fake.calls[0][0], "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        self.assertEqual(fake.calls[0][1]["Authorization"], "Bearer test-gemini-key")
        self.assertIn("TAIL" * 3000, fake.calls[0][2]["messages"][0]["content"])

    def test_polish_secret_and_external_safe_gate_before_network(self):
        for source, change in [("body", {"externalSafe": False}), ("body", {"externalSafe": 1}),
                               ("body", {"externalSafe": "true"}), ("sk-ant-12345678901234567890", {}),
                               ("Authorization: Bearer abcdef123456", {}), ("body", {"facts": ["api_key=secret"]}),
                               ("body", {"facts": [ENV["ANTHROPIC_API_KEY"]]})]:
            b = brief()
            b.update(change)
            fake = Fake()
            with self.subTest(source=source, change=change), self.assertRaises(ModelError):
                Models(ENV, fake).polish(source, b)
            self.assertEqual(fake.calls, [])

    def test_review_cannot_certify_live_checks_from_model(self):
        for checks in ({}, dict(FLAGS, images=False), dict(FLAGS, affiliate="true"), dict(FLAGS, render=None)):
            result = Models(ENV, Fake(response(REVIEW))).review(bundle(), checks)
            self.assertFalse(result["passed"])
            self.assertTrue(result["issues"])
        result = Models(ENV, Fake(response(REVIEW))).review(bundle(), FLAGS)
        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence"]["checks"], FLAGS)
        for value in (dict(REVIEW, score=7.4), dict(REVIEW, facts=False), dict(REVIEW, issues=["unverified"])):
            self.assertFalse(Models(ENV, Fake(response(value))).review(bundle(), FLAGS)["passed"])

    def test_social_requires_public_content_and_images_readback(self):
        b = bundle()
        url = "https://camp-gear-lab.com/articles/tent"
        fake = Fake()
        with self.assertRaises(ModelError):
            Models(ENV, fake).social(b, url)
        self.assertEqual(fake.calls, [])
        b["publicReadback"] = dict(verified=True, url=url, content=b["article"]["content"], images=b["images"])
        post = dict(text="広告 Gear selection", replyText=url, url=url, images=b["images"], platform="x")
        self.assertEqual(Models(ENV, Fake(response(post))).social(b, url), post)
        for change in ({"text": "広告 " + url}, {"replyText": "no link"}, {"text": "Gear selection"},
                       {"url": "https://other.example"}, {"platform": "threads"}):
            with self.subTest(change=change), self.assertRaises(ModelError):
                Models(ENV, Fake(response(dict(post, **change)))).social(b, url)

    def test_truncation_missing_usage_transport_errors_are_sanitized(self):
        truncated = response(THEMES)
        truncated["stop_reason"] = "max_tokens"
        missing_usage = response(THEMES)
        missing_usage.pop("usage")
        for value in (truncated, missing_usage, RuntimeError("SECRET test-claude-key")):
            with self.assertRaises(ModelError) as caught:
                Models(ENV, Fake(value)).research({})
            self.assertNotIn("SECRET", str(caught.exception))

    def test_research_rejects_missing_evidence_and_unknown_product(self):
        for field in ("slug", "categoryId", "query", "productIds", "selectionReason"):
            value = copy.deepcopy(THEMES)
            value["themes"][0].pop(field)
            with self.subTest(field=field), self.assertRaises(ModelError):
                Models(ENV, Fake(response(value))).research(context())
        value = copy.deepcopy(THEMES)
        value["themes"][0]["productIds"] = ["ghost"]
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(value))).research(context())

    def test_research_excludes_existing_query_even_when_title_differs(self):
        ctx = context()
        ctx["existingArticles"] = [{"title": "Different title", "query": "winter tent weight choice"}]
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(THEMES))).research(ctx)

    def test_draft_validates_runtime_required_article_shape(self):
        fields = ("slug", "title", "categoryId", "content", "excerpt", "metaDescription", "faqs", "tags", "productIds", "author")
        for field in fields:
            b = bundle()
            b["article"].pop(field)
            with self.subTest(field=field), self.assertRaises(ModelError):
                Models(ENV, Fake(response(b))).draft({}, context())
        for changes in ({"excerpt": "short"}, {"metaDescription": "short"}, {"metaDescription": "x" * 161},
                        {"faqs": []}, {"faqs": [{"question": "q", "answer": ""}] * 3},
                        {"tags": "tent"}, {"author": "other"}, {"content": "x" * 2999}):
            b = bundle()
            b["article"].update(changes)
            with self.subTest(changes=list(changes)), self.assertRaises(ModelError):
                Models(ENV, Fake(response(b))).draft({}, context())

    def test_draft_format_length_links_and_comparison_requirements(self):
        for format_name, lower, upper in (("ranking", 5000, 8000), ("comparison", 5000, 8000),
                                           ("guide", 3000, 5000), ("how-to", 3000, 5000), ("review", 2000, 3500)):
            for size, success in ((lower - 1, False), (lower, True), (upper, True), (upper + 1, False)):
                b = bundle()
                b["brief"]["format"] = format_name
                prefix = "## Choice\n[設営](/articles/setup) [撤収](/articles/pack)\n{{comparison:tent-a}}\n"
                b["article"]["content"] = prefix + "文" * (size - len(prefix))
                with self.subTest(format=format_name, size=size):
                    model = Models(ENV, Fake(response(b)))
                    if success:
                        self.assertEqual(model.draft({}, context())["article"]["content"], b["article"]["content"])
                    else:
                        with self.assertRaises(ModelError):
                            model.draft({}, context())
        for content in ("## Choice\n" + "文" * 4000,
                        "## Choice\n[a](/articles/a) [a](/articles/a)\n" + "文" * 4000):
            b = bundle()
            b["article"]["content"] = content
            with self.assertRaises(ModelError):
                Models(ENV, Fake(response(b))).draft({}, context())
        b = bundle()
        b["brief"]["format"] = "ranking"
        b["article"]["content"] += "文" * 2000
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(b))).draft({}, context())

    def test_main_can_replace_images_with_verified_evidence(self):
        ctx = context()
        ctx["images"][0].update(verified=True, sha256="observed", checkedAt="2026-11-03T12:00:00+09:00")
        b = Models(ENV, Fake(response(bundle()))).draft({}, ctx)
        self.assertEqual(b["images"], [{"productId": "tent-a", "url": "https://images.example/a.jpg"}])

    def test_usage_record_survives_rejected_completion(self):
        fake = Fake(response(None, raw="Not JSON"))
        model = Models(ENV, fake)
        with self.assertRaises(ModelError):
            model.research(context())
        self.assertEqual(model.usage[0]["responseId"], "c-1")
        self.assertEqual(model.usage[0]["input"], 31)

    def test_artifact_sink_captures_invalid_json_before_strict_parse_with_usage(self):
        artifacts = []
        model = Models(ENV, Fake(response(None, raw='not JSON')), artifact_sink=artifacts.append)
        with self.assertRaisesRegex(ModelError, 'Invalid JSON response'):
            model.research(context())
        self.assertEqual(artifacts, [{'responseId': 'c-1', 'model': 'claude-sonnet-4-6',
                                      'content': 'not JSON', 'usage': {'input_tokens': 31, 'output_tokens': 9}}])
        self.assertEqual(model.usage[0]['responseId'], artifacts[0]['responseId'])
        self.assertEqual(model.usage[0]['output'], 9)
        artifacts.clear()
        self.assertEqual(Models(ENV, Fake(response(THEMES)), artifact_sink=artifacts.append).research(context()), THEMES)
        self.assertEqual(artifacts[0]['usage'], {'input_tokens': 31, 'output_tokens': 9})

    def test_artifact_sink_blocks_secret_reflection_and_fails_closed(self):
        artifacts = []
        model = Models(ENV, Fake(response(None, raw='{"leak":"test-claude-key"}')),
                       artifact_sink=artifacts.append)
        with self.assertRaisesRegex(ModelError, 'Sensitive data blocked'):
            model.research(context())
        self.assertEqual(artifacts, [])
        def broken(_):
            raise RuntimeError('SECRET test-claude-key')
        model = Models(ENV, Fake(response(None, raw='not JSON')), artifact_sink=broken)
        with self.assertRaisesRegex(ModelError, '^Model artifact sink failed$') as caught:
            model.research(context())
        self.assertIsNone(caught.exception.__cause__)

    def test_runtime_binds_private_atomic_model_artifact_sink(self):
        from runtime import Runtime
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / 'env'
            env.write_text('ANTHROPIC_API_KEY=test-claude-key\n')
            runtime = Runtime({'stateRoot': str(root / 'state'), 'envFile': str(env),
                               'slack': {'user_id': 'U'}}, catalog=object(), slack=object())
            runtime.models.request = Fake(response(None, raw='not JSON'))
            with self.assertRaisesRegex(ModelError, 'Invalid JSON response'):
                runtime.models.research(context())
            name = hashlib.sha256(b'c-1').hexdigest() + '.json'
            artifact = root / 'state' / 'model-artifacts' / name
            self.assertTrue(artifact.exists())
            self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(artifact.read_text())['content'], 'not JSON')

    def test_malformed_bundle_rejected_with_safe_model_error(self):
        for patcher in (lambda b: b["article"].update(productIds=[{}]),
                        lambda b: b.update(products=[None]),
                        lambda b: b.update(images=[None])):
            b = bundle()
            patcher(b)
            with self.subTest(b=b), self.assertRaises(ModelError):
                Models(ENV, Fake(response(b))).draft({}, context())

    def test_offline_failure_cannot_be_overridden_by_model_or_flags(self):
        for checks in (dict(FLAGS, passed=False), dict(FLAGS, failures=["bad structure"]),
                       {"passed": False, "evidence": FLAGS}):
            self.assertFalse(Models(ENV, Fake(response(REVIEW))).review(bundle(), checks)["passed"])

    def test_draft_cannot_invent_image_verification(self):
        b = bundle()
        b["images"][0]["verified"] = True
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(b))).draft({}, context())

    def test_retry_budget_is_shared_across_fallback(self):
        fake = Fake(http(429), http(404), http(503), http(429), response(bundle()))
        with patch("models.time.sleep"), self.assertRaises(ModelError):
            Models(ENV, fake).draft({}, context())
        self.assertEqual(len(fake.calls), 4)

    def test_default_urllib_transport_has_same_request_contract(self):
        class LocalResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps(response(THEMES)).encode()
        with patch("models.urlopen", return_value=LocalResponse()) as opener:
            result = Models(ENV).research(context())
        self.assertEqual(result, THEMES)
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-api-key"), "test-claude-key")
        self.assertEqual(json.loads(request.data)["model"], "claude-sonnet-4-6")
        self.assertLessEqual(opener.call_args.kwargs["timeout"], 180)

    def test_keys_from_explicit_mapping_only(self):
        fake = Fake()
        with patch.dict("os.environ", ENV), self.assertRaises(ModelError):
            Models({}, fake).research({})
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
