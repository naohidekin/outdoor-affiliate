import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ledger import canonical, fingerprint
from runtime import normalize_revision_social_card
from social_cards import SocialCards
from test_social_cards import CARD, ENV, FakeCatalog, fixture
import revision_semantic_card_continuation as continuation


class Ledger:
    def __init__(self, path, job): self.db_path, self.job = path, job
    def get_job(self, _): return copy.deepcopy(self.job)
    def validate_existing_improvement_owner_grant(self, grant): return copy.deepcopy(grant)


class Catalog:
    def __init__(self, runtime): self.runtime, self.calls = runtime, 0
    def gather_revision(self, *args):
        self.calls += 1
        return copy.deepcopy(self.runtime.gathered)


class Runtime:
    def __init__(self, root):
        self.root, self.saved, self.paid = root, 0, []
        self.config = {"modelBudget": None}
        product = {"id": "product-1", "name": "Product", "imageUrl": "https://maker.example/p.png",
                   "amazonUrl": "https://www.amazon.co.jp/dp/example",
                   "affiliateUrl": "https://item.rakuten.co.jp/example/item"}
        base = {"id": "article-1", "title": "Guide", "slug": "guide", "categoryId": "wear",
                "productIds": ["product-1"], "content": "published"}
        old_card = {"role": "social-card", "verified": True, "url": "https://images.example/old.png"}
        article = {"id": "article-1", "title": "Guide", "slug": "guide", "categoryId": "wear",
                   "productIds": ["product-1"], "content": "前。" +
                   continuation._correct.__globals__["BODY_OLD"] + "後。",
                   "faqs": [{"question": "q0", "answer": "a0"}, {"question": "q1", "answer": "a1"},
                            {"question": continuation._correct.__globals__["FAQ_OLD"], "answer": "answer"}],
                   "generationMeta": {"socialCard": {"url": old_card["url"]}}}
        self.bundle = {"article": article,
                       "brief": {"protected": [], "requiredExpressions": [], "format": "guide"},
                       "products": [product], "images": [{"productId": "product-1",
                           "url": product["imageUrl"], "verified": True}, old_card],
                       "references": [], "wisePolicy": "wise-current"}
        binding = {"baseArticle": base, "baseHash": fingerprint(base),
                   "baseProducts": [copy.deepcopy(product)]}
        self.job = {"id": continuation.JOB, "kind": "article_revision", "stage": "review",
                    "revision": fingerprint(self.bundle), "bundle": copy.deepcopy(self.bundle),
                    "review": {"valid": True}, "astraReview": None, "approval": None,
                    "publication": None, "revisionContext": binding, "theme": {"slug": "guide"}}
        self.context = {"revisionArticles": [base], "products": [copy.deepcopy(product)],
                        "wisePolicy": {"id": "wise-current"}}
        self.gathered = {"checks": {"facts": True, "images": True, "affiliate": True},
                         "products": [copy.deepcopy(product)],
                         "images": [copy.deepcopy(self.bundle["images"][0])], "references": [], "evidence": {}}
        db = root / "ledger.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.executescript("CREATE TABLE meta(key PRIMARY KEY,value);"
                "CREATE TABLE effects(job_id,status);CREATE TABLE requests(job_id);"
                "CREATE TABLE model_budget_reservations(article_id,status);")
        self.ledger, self.catalog = Ledger(db, self.job), Catalog(self)
    def _require_running(self): pass
    def _budget_article_id(self, value): return value
    def _wise_context(self, value): return copy.deepcopy(value)
    def _context(self): return copy.deepcopy(self.context)
    def _source_dependencies(self, value): return copy.deepcopy(value)
    def _revision_manager_blocks(self, value, job): return False
    def _save_usage(self): self.saved += 1
    def _finish_article_review(self, job, context, gathered, bundle, source, preservation,
                               polished, source_dependencies):
        self.paid.extend(["final_review", "independent_review"])
        self.job["revision"] = fingerprint(bundle)
        return {"status": "awaiting_approval"}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        self.grant = {"instructionReceiptSha256": "r" * 64}
        self.proof = {"ownerGrant": self.grant, "jobId": continuation.JOB,
                      "specSha256": fingerprint(self.runtime.job["revisionContext"]),
                      "semanticManifestSha256": "m" * 64, "scope": continuation.SCOPE}
        source = continuation._correct(self.runtime.bundle)
        polished = {"content": source["article"]["content"], "model": "gemini-3.8-flash",
                    "usage": {"responseId": "paid-once", "input": 1, "output": 1}}
        output = {"polished": polished, "preservation": {"passed": True, "failures": []}}
        fresh = copy.deepcopy(self.runtime.gathered)
        archive = {"bundle": copy.deepcopy(self.runtime.bundle), "review": {"valid": True},
                   "independentReview": {"passed": False},
                   "freshSource": {"kind": "fresh_revision_source_v1", "gathered": fresh,
                                   "fingerprint": fingerprint(fresh)}}
        manifest = {"manifestSha256": "m" * 64, "jobId": continuation.JOB,
                    "v1Revision": fingerprint(self.runtime.bundle),
                    "specSha256": fingerprint(self.runtime.job["revisionContext"]),
                    "correctedSourceSha256": fingerprint(source)}
        values = {
            "semantic-claim.json": {"status": "claimed", "manifest": manifest},
            "semantic-result.json": {"failureType": "ValueError", "jobId": continuation.JOB,
                "manifestSha256": "m" * 64, "ownerApprovalGranted": False,
                "publicationPerformed": False, "status": "requires_reconciliation"},
            "semantic-v1-archive.json": archive,
            "semantic-driver-claim.json": {"status": "claimed", "manifestSha256": "m" * 64},
            "semantic-driver-result.json": {"status": "completed", "result": {
                "status": "attention", "reason": "social_card_evidence_missing"}},
        }
        self.artifacts = {}
        for name, value in values.items():
            path = self.root / "inputs" / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(canonical(value))
            self.artifacts[name] = (str(path.relative_to(self.root)), hashlib.sha256(path.read_bytes()).hexdigest())
        record = {"jobId": continuation.JOB, "stageKey": "polish-key", "stage": "polish",
                  "status": "succeeded", "createdAt": "2026-11-28T23:19:06.530482+09:00",
                  "attempts": 1, "maxAttempts": 2, "output": output,
                  "outputHash": fingerprint(output), "responseReceiptCount": 1,
                  "missingUsage": False, "missingUsageAttemptCount": 0,
                  "successorKey": None, "predecessorKey": None}
        with sqlite3.connect(self.runtime.ledger.db_path) as connection:
            connection.execute("INSERT INTO meta VALUES (?,?)", ("polish-key", canonical(record)))
        patches = patch.multiple(continuation,
            SPEC_SHA=fingerprint(self.runtime.job["revisionContext"]),
            V1_REVISION=fingerprint(self.runtime.bundle), OWNER_GRANT_SHA=fingerprint(self.grant),
            OWNER_RECEIPT_SHA=self.grant["instructionReceiptSha256"], SEMANTIC_MANIFEST_SHA="m" * 64,
            POLISH_KEY="polish-key", POLISH_OUTPUT_SHA=fingerprint(output),
            POLISH_RECORD_SHA=fingerprint(record), ARTIFACTS=self.artifacts)
        patches.start(); self.addCleanup(patches.stop)
        validator = patch.object(continuation, "validate_context", lambda value: copy.deepcopy(value))
        validator.start(); self.addCleanup(validator.stop)
        self.proof["specSha256"] = continuation.SPEC_SHA

    def tearDown(self): self.temp.cleanup()

    def test_prepare_uses_saved_source_and_execute_reuses_paid_polish_once(self):
        manifest = continuation.prepare(self.runtime, self.proof)
        self.assertEqual(0, self.runtime.catalog.calls)
        result = continuation.execute(self.runtime, manifest, self.proof)
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, self.runtime.catalog.calls)
        self.assertEqual(["final_review", "independent_review"], self.runtime.paid)
        self.assertEqual(["final_review", "independent_review"], manifest["newPaidStagesAllowed"])
        folder = self.root / "revision-semantic-card-continuations" / continuation.JOB
        self.assertTrue((folder / "archive" / "semantic-polish-stage.json").is_file())
        fresh = json.loads((folder / "current-fresh-source.json").read_text())
        self.assertEqual(fingerprint(fresh["gathered"]), fresh["fingerprint"])
        self.assertIsNone(self.runtime.job["approval"]); self.assertIsNone(self.runtime.job["publication"])

    def test_drift_or_unresolved_state_blocks_before_claim_and_paid_review(self):
        cases = [lambda: self.runtime.context["revisionArticles"][0].update(content="changed"),
                 lambda: self.runtime.context["wisePolicy"].update(id="changed")]
        for index, change in enumerate(cases):
            with self.subTest(index=index):
                original = copy.deepcopy(self.runtime.context); change()
                with self.assertRaises(ValueError): continuation.prepare(self.runtime, self.proof)
                self.assertEqual([], self.runtime.paid)
                self.assertFalse((self.root / "revision-semantic-card-continuations").exists())
                self.runtime.context = original

    def test_fresh_purchase_evidence_failure_stops_before_claim_or_paid_review(self):
        manifest = continuation.prepare(self.runtime, self.proof)
        self.runtime.gathered["products"][0]["amazonUrl"] = ""
        with self.assertRaisesRegex(ValueError, "purchase evidence required"):
            continuation.execute(self.runtime, manifest, self.proof)
        self.assertEqual([], self.runtime.paid)
        self.assertFalse((self.root / "revision-semantic-card-continuations").exists())

    def test_paid_polish_receipt_drift_blocks_prepare(self):
        with sqlite3.connect(self.runtime.ledger.db_path) as connection:
            record = json.loads(connection.execute(
                "SELECT value FROM meta WHERE key='polish-key'").fetchone()[0])
            record["output"]["polished"]["usage"]["responseId"] = "changed"
            connection.execute("UPDATE meta SET value=? WHERE key='polish-key'", (canonical(record),))
        with self.assertRaisesRegex(ValueError, "polish_changed"):
            continuation.prepare(self.runtime, self.proof)
        self.assertEqual(0, self.runtime.catalog.calls)
        self.assertEqual([], self.runtime.paid)

    def test_budget_cap_drift_blocks_before_source_or_paid_review(self):
        self.runtime.config["modelBudget"] = {"article": {"calls": 33}}
        with self.assertRaisesRegex(ValueError, "budget_caps"):
            continuation.prepare(self.runtime, self.proof)
        self.assertEqual(0, self.runtime.catalog.calls)
        self.assertEqual([], self.runtime.paid)


class SocialCardNormalizationIntegrationTests(unittest.TestCase):
    def test_real_builder_replaces_only_old_card_and_preserves_product_proof(self):
        value = fixture()
        old = {"url": "https://old.example/card.png", "sha256": "f" * 64, "size": 10,
               "contentType": "image/png", "width": 1200, "height": 630}
        value["article"]["generationMeta"] = {"prior": "keep", "socialCard": copy.deepcopy(old)}
        value["images"].append(dict(old, role="social-card", verified=True))
        product_proof = copy.deepcopy(value["images"][0])
        normalized = normalize_revision_social_card(value)
        self.assertEqual([product_proof], normalized["images"])
        self.assertEqual("keep", normalized["article"]["generationMeta"]["prior"])
        catalog = FakeCatalog(public=CARD)
        def storage(data, path):
            return {"verified": True, "path": path, "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data), "url": ENV["SUPABASE_URL"] +
                    "/storage/v1/object/public/editorial-social-cards/" + path}
        cards = SocialCards({}, ENV, catalog,
                            renderer=lambda spec, path: {"bytes": CARD, "evidence": {"displayText": spec["heading"]}},
                            storage=storage)
        rebuilt = cards.build(normalized)
        self.assertEqual(1, len([image for image in rebuilt["images"]
                                if image.get("role") == "social-card"]))
        self.assertEqual(product_proof, rebuilt["images"][0])

    def test_no_prior_card_is_valid_but_manifest_only_duplicate_or_unrelated_card_fails(self):
        self.assertEqual(fixture(), normalize_revision_social_card(fixture()))
        old = {"url": "https://old.example/card.png", "sha256": "f" * 64, "size": 10,
               "contentType": "image/png", "width": 1200, "height": 630}
        manifest_only = fixture()
        manifest_only["article"]["generationMeta"] = {"socialCard": copy.deepcopy(old)}
        with self.assertRaisesRegex(ValueError, "social_card_previous_evidence_invalid"):
            normalize_revision_social_card(manifest_only)
        duplicate = copy.deepcopy(manifest_only)
        duplicate["images"].extend([dict(old, role="social-card", verified=True),
                                    dict(old, role="social-card", verified=True)])
        with self.assertRaisesRegex(ValueError, "social_card_previous_evidence_invalid"):
            normalize_revision_social_card(duplicate)
        unrelated = copy.deepcopy(manifest_only)
        unrelated["images"].append(dict(old, role="social-card", verified=True, sha256="e" * 64))
        with self.assertRaisesRegex(ValueError, "social_card_previous_evidence_invalid"):
            normalize_revision_social_card(unrelated)


if __name__ == "__main__": unittest.main()
