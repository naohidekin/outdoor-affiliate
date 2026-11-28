import copy, json, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from ledger import fingerprint
import revision_semantic_correction as correction


def bundle():
    product = {"id": "product-1", "amazonUrl": "https://www.amazon.co.jp/dp/example",
               "affiliateUrl": "https://item.rakuten.co.jp/example/item"}
    return {"article": {"content": "前。" + correction.BODY_OLD + "後。", "faqs": [
                {"question": "q0", "answer": "a0"}, {"question": "q1", "answer": "a1"},
                {"question": correction.FAQ_OLD, "answer": "Amazonと楽天市場は異なります。"}]},
            "brief": {"protected": [], "requiredExpressions": [], "format": "guide"},
            "products": [product], "images": [], "references": []}


class Ledger:
    def __init__(self, db, job): self.db_path, self.job = db, job
    def get_job(self, _): return copy.deepcopy(self.job)
    def validate_existing_improvement_owner_grant(self, grant): return copy.deepcopy(grant)


class Catalog:
    def __init__(self, runtime): self.runtime = runtime
    def gather_revision(self, *args): return copy.deepcopy(self.runtime.gathered)


class Runtime:
    def __init__(self, root):
        self.root = root; self.saved = 0; self.calls = []; self.stage_inputs = []
        value = bundle(); revision = fingerprint(value)
        base = {"id": "article-1", "title": "guide", "slug": "guide",
                "categoryId": "category", "productIds": ["product-1"]}
        self.context = {"revisionArticles": [copy.deepcopy(base)],
                        "products": copy.deepcopy(value["products"])}
        self.job = {"id": correction.JOB, "kind": "article_revision", "stage": "review",
                    "revision": revision, "bundle": value, "review": {"valid": True},
                    "astraReview": None, "approval": None, "publication": None,
                    "revisionContext": {"baseArticle": base, "baseHash": fingerprint(base),
                                        "baseProducts": copy.deepcopy(value["products"])},
                    "theme": {"slug": "guide"}}
        db = root / "ledger.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.executescript("CREATE TABLE meta(key PRIMARY KEY,value);"
                                     "CREATE TABLE effects(job_id,status);CREATE TABLE requests(job_id);"
                                     "CREATE TABLE model_budget_reservations(article_id,status);")
        self.ledger = Ledger(db, self.job)
        self.config = {"modelBudget": {"article": {"calls": 32, "inputTokens": 1, "outputTokens": 1},
                                       "period": {"calls": 128, "inputTokens": 1, "outputTokens": 1}}}
        self.gathered = {"checks": {"facts": True, "images": True, "affiliate": True},
                         "products": copy.deepcopy(value["products"]), "evidence": {}}
        self.catalog = Catalog(self)
        self.models = type("Models", (), {"polish": lambda s,content,brief:
            {"content": content, "model": "gemini-3.8-flash"}})()
    def _require_running(self): pass
    def _budget_article_id(self, value): return value
    def _wise_context(self, value): return value
    def _context(self): return copy.deepcopy(self.context)
    def _source_dependencies(self, value): return copy.deepcopy(value)
    def _model_routes(self): return {"polish": {"requested": "gemini-3.8-flash"}}
    def _run_model_stage(self, job, stage, inputs, operation, model):
        self.calls.append(stage); self.stage_inputs.append(copy.deepcopy(inputs)); return operation()
    def _finish_article_review(self, *args):
        self.calls.extend(["final_review", "independent_review"]); self.job["revision"] = "new"; return {"ok": True}
    def _save_usage(self): self.saved += 1


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        self.grant = {"instructionReceiptSha256": "r" * 64}
        qa = {"actualInvoiceUsd": None, "actualModel": None,
              "fingerprint": self.runtime.job["revision"], "issues": copy.deepcopy(correction.ISSUES),
              "kind": "independent_article_review_v1", "outputCapEnforced": False,
              "passed": False, "requestedModel": "gpt-6-astra", "reservedOutputTokens": 16384,
              "usage": {"input_tokens": 1, "output_tokens": 1}}
        self.qa = qa
        record = {"jobId": correction.JOB, "stage": "independent_review", "status": "succeeded",
                  "attempts": 1, "maxAttempts": 1, "output": qa, "outputHash": fingerprint(qa),
                  "responseReceiptCount": 1, "missingUsage": False}
        with sqlite3.connect(self.runtime.ledger.db_path) as connection:
            connection.execute("INSERT INTO meta VALUES (?,?)", ("qa", json.dumps(record)))
        self.patches = [patch.object(correction, "SPEC_SHA", fingerprint(self.runtime.job["revisionContext"])),
                        patch.object(correction, "V1_REVISION", self.runtime.job["revision"]),
                        patch.object(correction, "V1_REVIEW_SHA", fingerprint(self.runtime.job["review"])),
                        patch.object(correction, "QA_KEY", "qa"),
                        patch.object(correction, "QA_OUTPUT_SHA", fingerprint(qa)),
                        patch.object(correction, "OWNER_GRANT_SHA", fingerprint(self.grant)),
                        patch.object(correction, "OWNER_RECEIPT_SHA", self.grant["instructionReceiptSha256"]),
                        patch.object(correction, "validate_context", lambda value: copy.deepcopy(value)),
                        patch.object(correction, "_config", lambda value: {"article": {"calls": 32}, "period": {"calls": 128}}),
                        patch.object(correction, "inspect_polish", lambda old,new: {"passed": True})]
        for item in self.patches: item.start()
    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def test_exact_two_corrections_only(self):
        before = bundle(); after = correction._correct(before)
        expected = copy.deepcopy(before)
        expected["article"]["faqs"][2]["question"] = correction.FAQ_NEW
        expected["article"]["content"] = expected["article"]["content"].replace(
            correction.BODY_OLD, correction.BODY_NEW)
        self.assertEqual(expected, after); self.assertEqual(bundle(), before)

    def test_issue_drift_blocks_before_claim(self):
        with sqlite3.connect(self.runtime.ledger.db_path) as connection:
            record = json.loads(connection.execute("SELECT value FROM meta WHERE key='qa'").fetchone()[0])
            record["output"]["issues"].pop(); record["outputHash"] = fingerprint(record["output"])
            connection.execute("UPDATE meta SET value=? WHERE key='qa'", (json.dumps(record),))
        with self.assertRaisesRegex(ValueError, "qa_changed"):
            correction.prepare(self.runtime, self.grant)
        self.assertFalse((self.root / "revision-semantic-corrections").exists())

    def test_live_baseline_drift_blocks_before_polish_or_claim(self):
        self.runtime.context["revisionArticles"][0]["title"] = "drifted"
        with self.assertRaisesRegex(ValueError, "live_baseline"):
            correction.prepare(self.runtime, self.grant)
        self.assertEqual([], self.runtime.calls)
        self.assertFalse((self.root / "revision-semantic-corrections").exists())

    def test_missing_purchase_evidence_blocks_before_polish_or_claim(self):
        self.runtime.gathered["products"][0]["amazonUrl"] = ""
        with self.assertRaisesRegex(ValueError, "purchase evidence required"):
            correction.prepare(self.runtime, self.grant)
        self.assertEqual([], self.runtime.calls)
        self.assertFalse((self.root / "revision-semantic-corrections").exists())

    def test_single_use_calls_no_draft_and_grants_no_approval(self):
        manifest = correction.prepare(self.runtime, self.grant)
        result = correction.execute(self.runtime, manifest, self.grant)
        self.assertEqual("completed", result["status"])
        self.assertEqual(["polish", "final_review", "independent_review"], self.runtime.calls)
        self.assertIn(correction.BODY_NEW, self.runtime.stage_inputs[0]["brief"]["protected"])
        self.assertNotIn(correction.BODY_NEW, self.runtime.job["bundle"]["brief"]["protected"])
        self.assertIsNone(self.runtime.job["approval"]); self.assertIsNone(self.runtime.job["publication"])
        folder = self.root / "revision-semantic-corrections" / correction.JOB
        self.assertTrue((folder / "v1-archive.json").is_file())
        archive = json.loads((folder / "v1-archive.json").read_text())
        self.assertEqual(fingerprint(archive["freshSource"]["gathered"]),
                         archive["freshSource"]["fingerprint"])
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            correction.prepare(self.runtime, self.grant)


if __name__ == "__main__": unittest.main()
