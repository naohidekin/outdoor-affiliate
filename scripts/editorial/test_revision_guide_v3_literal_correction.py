import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ledger import canonical, fingerprint
import article_verification_receipt
import independent_article_review
import revision_guide_v3_literal_correction as correction


def article_bundle():
    filler = "選び方を確認するための既存本文です。" * 190
    content = (filler + correction.DELETE_PHRASE + "比較します。" +
               correction.DELETE_SENTENCE + "確認を終えます。")
    image_url = "https://images.example/product.png"
    product = {"id": "product-1", "name": "Product", "imageUrl": image_url,
               "amazonUrl": "https://amazon.example/item",
               "affiliateUrl": "https://rakuten.example/item",
               "price": None, "rating": None, "availability": None}
    image = {"productId": "product-1", "url": image_url, "verified": True,
             "sha256": "d" * 64, "size": 100}
    reference = {"url": "https://maker.example/product", "text": "official source"}
    return {"article": {"id": correction.JOB, "content": content,
                         "productIds": ["product-1"]},
            "brief": {"format": "guide", "protected": ["確認を終えます。"] +
                      ["公式出典の全文引用" + str(index) for index in range(7)],
                      "requiredExpressions": ["比較します。"], "style": "既存文体を保つ。"},
            "products": [product], "images": [image], "references": [reference]}


class Ledger:
    def __init__(self, db_path, job): self.db_path, self.job = db_path, job
    def get_job(self, _): return copy.deepcopy(self.job)
    def validate_existing_improvement_owner_grant(self, grant): return copy.deepcopy(grant)


class Catalog:
    def __init__(self, runtime): self.runtime, self.calls = runtime, 0
    def gather_revision(self, *args):
        self.calls += 1
        return copy.deepcopy(self.runtime.gathered)


class Runtime:
    def __init__(self, root):
        self.root, self.calls, self.saved, self.stage_inputs = root, [], 0, []
        bundle = article_bundle()
        base = {"id": "article-1", "content": "published", "productIds": ["product-1"]}
        binding = {"baseArticle": base, "baseHash": fingerprint(base),
                   "baseProducts": copy.deepcopy(bundle["products"])}
        revision = fingerprint(bundle)
        review = {"passed": True, "fingerprint": revision,
                  "evidence": {key: True for key in
                               ("facts", "images", "affiliate", "medical", "render")}}
        self.job = {"id": correction.JOB, "kind": "article_revision", "stage": "review",
                    "revision": revision, "bundle": bundle,
                    "review": review, "astraReview": None, "approval": None,
                    "publication": None, "social": None, "revisionContext": binding,
                    "theme": {"slug": "guide"}}
        self.context = {"revisionArticles": [copy.deepcopy(base)],
                        "products": copy.deepcopy(bundle["products"])}
        self.gathered = {"checks": {"facts": True, "images": True, "affiliate": True},
                         "blocked": False, "products": copy.deepcopy(bundle["products"]),
                         "images": copy.deepcopy(bundle["images"]),
                         "references": copy.deepcopy(bundle["references"]), "evidence": {}}
        self.config = {"repo": str(root), "modelBudget": copy.deepcopy(correction.BUDGET_CAPS),
                       "editorialManager": {"command": ["owner-cli", "review"]}}
        self.models = type("Models", (), {"polish": lambda _, content, brief:
            {"content": content, "model": "gemini-3.8-flash"}})()
        db = root / "ledger.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.executescript(
                "CREATE TABLE meta(key PRIMARY KEY,value);"
                "CREATE TABLE effects(job_id,status);CREATE TABLE requests(job_id);"
                "CREATE TABLE model_budget_reservations("
                "reservation_id PRIMARY KEY,response_id,source_hash,article_id,stage,period_key,"
                "model,status,reserved_input_tokens,reserved_output_tokens,actual_input_tokens,"
                "actual_output_tokens,outcome,created_at,settled_at);"
            )
        self.ledger, self.catalog = Ledger(db, self.job), Catalog(self)
    def _require_running(self): pass
    def _budget_article_id(self, _): return "article:shared"
    def _wise_context(self, value): return copy.deepcopy(value)
    def _context(self): return copy.deepcopy(self.context)
    def _source_dependencies(self, value): return copy.deepcopy(value)
    def _model_routes(self): return {"polish": {"requested": "gemini-3.8-flash"}}
    def _run_model_stage(self, job, stage, inputs, operation, model):
        self.calls.append(stage); self.stage_inputs.append(copy.deepcopy(inputs)); return operation()
    def _finish_article_review(self, job, context, gathered, bundle, source,
                               preservation, polished, dependencies):
        self.calls.extend(["final_review", "independent_review"])
        self.job["revision"] = fingerprint(bundle)
        return {"status": "awaiting_astra_review"}
    def _save_usage(self): self.saved += 1


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        self.grant = {"instructionReceiptSha256": "r" * 64}
        self.runtime.job["revision"] = fingerprint(self.runtime.job["bundle"])
        qa_output = {"kind": "independent_article_review_v1",
                     "fingerprint": self.runtime.job["revision"], "passed": False,
                     "issues": [{"code": "unsupported_claim", "location": str(i),
                                 "detail": "issue"} for i in range(5)],
                     "requestedModel": "gpt-6-astra", "actualModel": None,
                     "usage": {"input_tokens": 100, "output_tokens": 20}}
        self.record = {"stageKey": "stage_journal:v1:qa", "jobId": correction.JOB,
                       "stage": "independent_review", "status": "succeeded",
                       "attempts": 1, "maxAttempts": 1, "output": qa_output,
                       "outputHash": fingerprint(qa_output), "responseReceiptCount": 1,
                       "missingUsage": False}
        self.reservation = {
            "reservation_id": "qa-reservation", "response_id": "response",
            "source_hash": "source", "article_id": "article:shared",
            "stage": "independent_review", "period_key": "2026-11-27",
            "model": "gpt-6-astra", "status": "settled", "reserved_input_tokens": 0,
            "reserved_output_tokens": 16384, "actual_input_tokens": 100,
            "actual_output_tokens": 20, "outcome": "success",
            "created_at": "2026-11-28T00:00:00+09:00",
            "settled_at": "2026-11-28T00:01:00+09:00",
        }
        with sqlite3.connect(self.runtime.ledger.db_path) as connection:
            connection.execute("INSERT INTO meta VALUES (?,?)",
                               (self.record["stageKey"], canonical(self.record)))
            connection.execute("INSERT INTO model_budget_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               tuple(self.reservation.values()))
        preview = {"passed": True, "failures": [], "viewportEvidence": {}}
        preview_path = (self.root / "seo-loop-recovery/20261128" /
                        "guide-v3-render-preview.json")
        preview_path.parent.mkdir(parents=True)
        preview_path.write_text(canonical(preview))
        normalized_source = {
            "products": copy.deepcopy(self.runtime.job["bundle"]["products"]),
            "images": copy.deepcopy(self.runtime.job["bundle"]["images"]),
            "references": copy.deepcopy(self.runtime.job["bundle"]["references"])}
        source_value = {"normalizedSource": copy.deepcopy(normalized_source),
                        "products": copy.deepcopy(normalized_source["products"]),
                        "images": copy.deepcopy(normalized_source["images"]),
                        "references": copy.deepcopy(normalized_source["references"])}
        source_sha = fingerprint(source_value)
        source = (self.root / "article-verification-sources" / correction.JOB /
                  (source_sha + ".json"))
        source.parent.mkdir(parents=True)
        source.write_text(canonical(source_value))
        product = self.runtime.job["bundle"]["products"][0]
        image = self.runtime.job["bundle"]["images"][0]
        image_url_sha = hashlib.sha256(product["imageUrl"].encode()).hexdigest()
        channels = ["rakuten", "amazon"]
        bindings = [{"productId": product["id"], "channel": channel,
                     "placement": "primary"} for channel in channels]
        presentation = [{"productId": product["id"], "componentCount": 1,
                         "priceInput": None, "ratingInput": None,
                         "availabilityInput": None, "merchantCheckDisplayed": True,
                         "zeroPriceDisplayed": False, "ratingClaimDisplayed": False,
                         "availabilityClaimDisplayed": False}]
        receipt = {
            "schemaVersion": 1, "kind": "article_verification_receipt_v1",
            "jobId": correction.JOB, "revision": self.runtime.job["revision"],
            "bundleSha256": self.runtime.job["revision"],
            "sourceDependenciesSha256": source_sha,
            "productBindings": [{"productId": product["id"], "name": product["name"],
                "price": None, "rating": None, "availability": None,
                "imageUrlSha256": image_url_sha, "imageSha256": image["sha256"],
                "channels": channels}],
            "checks": {
                "facts": {"passed": True},
                "images": {"passed": True, "readback": [{"productId": product["id"],
                    "urlSha256": image_url_sha, "sha256": image["sha256"],
                    "size": image["size"]}], "socialCard": {"status": "not_present"}},
                "affiliate": {"passed": True, "viewports": {name: {
                    "count": 2, "bindings": copy.deepcopy(bindings),
                    "destinationObservationsSha256": "e" * 64}
                    for name in ("desktop", "mobile")}},
                "medical": {"passed": True, "riskCount": 0, "scope": "candidate"},
                "render": {"passed": True, "previewSha256": fingerprint(preview),
                    "viewports": {name: {"internalLinks": [],
                        "allAnchorsVerified": True,
                        "productPresentation": copy.deepcopy(presentation)}
                        for name in ("desktop", "mobile")}},
            },
            "internalTargets": [],
        }
        article_verification_receipt.validate(
            receipt, correction.JOB, self.runtime.job["revision"])
        receipt_path = (self.root / "article-verification-receipts" / correction.JOB /
                        (self.runtime.job["revision"] + ".json"))
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(canonical(receipt))
        contract = independent_article_review.proof_contract()
        marker = {
            "schemaVersion": 1, "kind": "guide_v3_render_program_preflight_v1",
            "jobId": correction.JOB, "revision": self.runtime.job["revision"],
            "status": "passed", "checkedAt": datetime.now(correction.JST).isoformat(),
            "adapterVersion": independent_article_review.PROJECTION_VERSION,
            "adapterSha256": hashlib.sha256(
                Path(independent_article_review.__file__).read_bytes()).hexdigest(),
            "receiptModuleSha256": hashlib.sha256(
                Path(article_verification_receipt.__file__).read_bytes()).hexdigest(),
            "projectionContractSha256": contract["contractSha256"],
            "v2SourceArtifactSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "freshSourceSha256": fingerprint(self.runtime.gathered),
            "renderPreviewSha256": fingerprint(preview),
            "proofSha256": fingerprint(receipt),
        }
        self.marker_path = self.root / "render-preflight.json"
        self.marker_path.write_text(canonical(marker))
        self.evidence = {
            "schemaVersion": 1, "kind": "guide_v3_literal_correction_evidence_v1",
            "jobId": correction.JOB, "revision": self.runtime.job["revision"],
            "specSha256": fingerprint(self.runtime.job["revisionContext"]),
            "liveBaseSha256": self.runtime.job["revisionContext"]["baseHash"],
            "finalReviewSha256": fingerprint(self.runtime.job["review"]),
            "ownerCommandSha256": fingerprint(
                self.runtime.config["editorialManager"]["command"]),
            "qa": {"stageKey": self.record["stageKey"],
                   "recordSha256": fingerprint(self.record),
                   "outputSha256": fingerprint(qa_output),
                   "usageSha256": fingerprint(qa_output["usage"]),
                   "budgetReservationId": self.reservation["reservation_id"],
                   "budgetReservationSha256": fingerprint(self.reservation),
                   "issueCount": 5},
            "sourceArtifact": {"relativePath": str(source.relative_to(self.root)),
                               "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
            "preflightMarker": {"relativePath": self.marker_path.name,
                                "sha256": hashlib.sha256(
                                    self.marker_path.read_bytes()).hexdigest()},
        }
        self.patches = [
            patch.object(correction, "V2_REVISION", self.runtime.job["revision"]),
            patch.object(correction, "OWNER_GRANT_SHA", fingerprint(self.grant)),
            patch.object(correction, "OWNER_RECEIPT_SHA", self.grant["instructionReceiptSha256"]),
            patch.object(correction, "validate_context", lambda value: copy.deepcopy(value)),
            patch.object(correction, "valid_review", lambda *args: None),
            patch.object(correction, "require_current_review", lambda *args: None),
            patch.object(correction, "inspect_polish", lambda old, new: {"passed": True}),
        ]
        for item in self.patches: item.start()
    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def test_exact_two_deletions_preserve_every_other_value_and_constraints(self):
        before = article_bundle(); after = correction._correct(before)
        expected = copy.deepcopy(before)
        expected["article"]["content"] = expected["article"]["content"].replace(
            correction.DELETE_PHRASE, "").replace(correction.DELETE_SENTENCE, "")
        self.assertEqual(expected, after)
        self.assertEqual(before, article_bundle())
        self.assertGreaterEqual(len(after["article"]["content"]), 3000)
        baseline = correction._constraint_baseline(before)
        self.assertEqual(7, baseline["protected"]["preexistingAbsentCount"])
        self.assertEqual(1, baseline["protected"]["presentCount"])
        self.assertEqual(0, baseline["requiredExpressions"]["preexistingAbsentCount"])
        self.assertEqual(1, baseline["requiredExpressions"]["presentCount"])

    def test_prepare_is_read_only_and_execute_uses_only_three_new_quality_stages(self):
        self.assertIsNone(self.record["output"]["actualModel"])
        self.assertEqual("gpt-6-astra", self.record["output"]["requestedModel"])
        manifest = correction.prepare(self.runtime, self.evidence, self.grant)
        self.assertEqual([], self.runtime.calls)
        self.assertFalse((self.root / "revision-guide-v3-literal-corrections").exists())
        self.assertEqual(correction.PREFLIGHT_KEYS,
                         set(manifest["programPreflight"]))
        self.assertEqual(7, manifest["constraintBaseline"]["protected"]
                         ["preexistingAbsentCount"])

        result = correction.execute(self.runtime, manifest, self.evidence, self.grant)

        self.assertEqual("completed", result["status"])
        self.assertEqual(["polish", "final_review", "independent_review"], self.runtime.calls)
        self.assertEqual(["polish", "final_review", "independent_review"],
                         manifest["newPaidStagesAllowed"])
        self.assertIn(correction.POLISH_NEGATIVE_CONSTRAINT,
                      self.runtime.stage_inputs[0]["brief"]["style"])
        self.assertEqual("既存文体を保つ。", self.runtime.job["bundle"]["brief"]["style"])
        self.assertIsNone(self.runtime.job["approval"])
        self.assertIsNone(self.runtime.job["publication"])
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            correction.prepare(self.runtime, self.evidence, self.grant)

    def test_adapter_qa_usage_duplicate_or_cap_drift_blocks_before_model(self):
        cases = ("adapter", "preview", "proof", "qa", "usage",
                 "duplicate", "caps", "command", "stale")
        for case in cases:
            with self.subTest(case=case):
                self.tearDown(); self.setUp()
                if case == "adapter":
                    marker = json.loads(self.marker_path.read_text())
                    marker["adapterSha256"] = "0" * 64
                    self.marker_path.write_text(canonical(marker))
                    self.evidence["preflightMarker"]["sha256"] = hashlib.sha256(
                        self.marker_path.read_bytes()).hexdigest()
                elif case in ("preview", "proof"):
                    marker = json.loads(self.marker_path.read_text())
                    marker["renderPreviewSha256" if case == "preview" else
                           "proofSha256"] = "0" * 64
                    self.marker_path.write_text(canonical(marker))
                    self.evidence["preflightMarker"]["sha256"] = hashlib.sha256(
                        self.marker_path.read_bytes()).hexdigest()
                elif case == "qa":
                    self.evidence["qa"]["outputSha256"] = "0" * 64
                elif case == "usage":
                    self.evidence["qa"]["budgetReservationSha256"] = "0" * 64
                elif case == "duplicate":
                    duplicate = copy.deepcopy(self.record)
                    duplicate["stageKey"] = "stage_journal:v1:duplicate"
                    with sqlite3.connect(self.runtime.ledger.db_path) as connection:
                        connection.execute("INSERT INTO meta VALUES (?,?)",
                                           (duplicate["stageKey"], canonical(duplicate)))
                elif case == "caps":
                    self.runtime.config["modelBudget"]["period"]["outputTokens"] -= 1
                elif case == "command":
                    self.runtime.config["editorialManager"]["command"].append("changed")
                else:
                    marker = json.loads(self.marker_path.read_text())
                    marker["checkedAt"] = (datetime.now(correction.JST) -
                                            timedelta(hours=7)).isoformat()
                    self.marker_path.write_text(canonical(marker))
                    self.evidence["preflightMarker"]["sha256"] = hashlib.sha256(
                        self.marker_path.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):
                    correction.prepare(self.runtime, self.evidence, self.grant)
                self.assertEqual([], self.runtime.calls)
                self.assertFalse((self.root / "revision-guide-v3-literal-corrections").exists())

    def test_fresh_source_or_brief_conflict_blocks_before_claim_or_model(self):
        manifest = correction.prepare(self.runtime, self.evidence, self.grant)
        self.runtime.gathered["checks"]["images"] = False
        with self.assertRaisesRegex(ValueError, "fresh_source"):
            correction.execute(self.runtime, manifest, self.evidence, self.grant)
        self.assertEqual([], self.runtime.calls)
        self.assertFalse((self.root / "revision-guide-v3-literal-corrections").exists())

        self.tearDown(); self.setUp()
        self.runtime.job["bundle"]["brief"]["protected"].append(correction.DELETE_PHRASE)
        self.runtime.job["revision"] = fingerprint(self.runtime.job["bundle"])
        with patch.object(correction, "V2_REVISION", self.runtime.job["revision"]):
            self.evidence["revision"] = self.runtime.job["revision"]
            with self.assertRaisesRegex(ValueError, "brief_deletion_conflict"):
                correction._correct(self.runtime.job["bundle"])


if __name__ == "__main__": unittest.main()
