import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import contextmanager

from ledger import fingerprint
import revision_render_resume as recovery
from runtime import Runtime as EditorialRuntime
from stage_journal import StageBlocked, StageJournal


class Ledger:
    def __init__(self, path, job): self.db_path, self.job = path, job
    def get_job(self, _): return copy.deepcopy(self.job)
    def validate_existing_improvement_owner_grant(self, grant): return copy.deepcopy(grant)
    @contextmanager
    def _tx(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
    def _event(self, connection, job_id, kind, data):
        connection.execute("INSERT INTO events(job_id,kind,data) VALUES (?,?,?)",
                           (job_id, kind, json.dumps(data)))


class Runtime:
    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.job = {"id": recovery.JOB, "kind": "article_revision", "stage": "error",
                    "error": {"reason": "render_preview_failed"}, "bundle": None,
                    "review": None, "approval": None, "publication": None,
                    "revisionContext": {"spec": "bound"},
                    "theme": {"slug": "montbell-light-alpine-down-parka-1101606-guide"}}
        db = root / "ledger.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.executescript("CREATE TABLE effects(job_id,kind,status,data);"
                                     "CREATE TABLE requests(id,job_id,kind,data);"
                                     "CREATE TABLE model_budget_reservations(article_id,status);"
                                     "CREATE TABLE meta(key PRIMARY KEY,value);"
                                     "CREATE TABLE events(job_id,kind,data);")
        self.ledger = Ledger(db, self.job)
        self.stage_journal = StageJournal(self.ledger)
        self.draft_inputs = {"input": "draft", "dependencies": {"source": "bound"},
                             "schemaVersion": {"stage": 1}}
        self.polish_inputs = {"input": "polish", "dependencies": {"source": "bound"},
                              "schemaVersion": {"stage": 1}}
        self.draft_output = {"article": {"content": "draft"}, "brief": {"purpose": "guide"}}
        self.polish_output = {"polished": {"content": "polished"},
                              "preservation": {"passed": True}}
        self.draft_key = self.stage_journal.key(recovery.JOB, "draft", self.draft_inputs)
        self.polish_key = self.stage_journal.key(recovery.JOB, "polish", self.polish_inputs)
        for stage, inputs, output, key in (
                ("draft", self.draft_inputs, self.draft_output, self.draft_key),
                ("polish", self.polish_inputs, self.polish_output, self.polish_key)):
            self.stage_journal.run(recovery.JOB, stage, inputs,
                                   lambda value=output: copy.deepcopy(value), max_attempts=2)
            self.stage_journal.record_usage(recovery.JOB, stage, key, [{
                "responseId": stage + "-response", "model": "model",
                "usage": {"input_tokens": 1, "output_tokens": 1}}])
        self.paid = []
        self.saved = 0
    def _require_running(self): return None
    def _budget_article_id(self, value): return "article:" + value
    def _revision_manager_blocks(self, raw, job): return False
    def _context(self): return {"safe": True}
    def _save_usage(self): self.saved += 1
    def _make_article(self, job, context):
        if self._cache_only_stage_keys != {"draft": recovery.DRAFT_KEY,
                                           "polish": recovery.POLISH_KEY}:
            raise AssertionError("cache guard missing")
        self.paid.append("final_review")
        self.job["stage"] = "review"
        return {"status": "awaiting_approval"}

class RevisionRenderResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.runtime = Runtime(self.root)
        self.grant = {"ownerId": "owner", "taskRef": "owner-task:" + "a" * 64,
                      "instructionSha256": "b" * 64, "instructionReceiptSha256": "c" * 64}
        self.proof = {"ownerGrant": self.grant, "jobId": recovery.JOB,
                      "specSha256": recovery.SPEC_SHA, "scope": recovery.SCOPE}
        self.hashes = {}
        for name, (relative, _) in recovery.ARTIFACTS.items():
            raw = json.dumps({"name": name}, sort_keys=True).encode()
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            self.hashes[name] = (relative, hashlib.sha256(raw).hexdigest())
        self.patches = [patch.object(recovery, "SPEC_SHA", fingerprint(self.runtime.job["revisionContext"])),
                        patch.object(recovery, "ARTIFACTS", self.hashes),
                        patch.object(recovery, "OWNER_GRANT_SHA", fingerprint(self.grant)),
                        patch.object(recovery, "OWNER_RECEIPT_SHA", self.grant["instructionReceiptSha256"]),
                        patch.object(recovery, "DRAFT_KEY", self.runtime.draft_key),
                        patch.object(recovery, "DRAFT_OUTPUT", fingerprint(self.runtime.draft_output)),
                        patch.object(recovery, "POLISH_KEY", self.runtime.polish_key),
                        patch.object(recovery, "POLISH_OUTPUT", fingerprint(self.runtime.polish_output))]
        for item in self.patches: item.start()
        self.proof["specSha256"] = recovery.SPEC_SHA
    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def test_success_claims_archives_and_allows_only_final_review(self):
        manifest = recovery.prepare(self.runtime, self.proof)
        result = recovery.execute(self.runtime, manifest, self.proof)
        self.assertEqual("completed", result["status"])
        self.assertEqual(["final_review"], self.runtime.paid)
        self.assertEqual(1, self.runtime.saved)
        self.assertFalse(hasattr(self.runtime, "_cache_only_stage_keys"))
        folder = self.root / "revision-render-resumes" / recovery.JOB
        self.assertTrue((folder / "claim.json").is_file())
        self.assertEqual(set(self.hashes), {path.name for path in (folder / "archive").iterdir()})
        self.assertIsNone(self.runtime.job["approval"]); self.assertIsNone(self.runtime.job["publication"])
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            recovery.prepare(self.runtime, self.proof)

    def test_cache_or_state_drift_blocks_before_claim_and_paid_call(self):
        def update_stage(runtime, operation):
            with sqlite3.connect(runtime.ledger.db_path) as connection:
                value = json.loads(connection.execute(
                    "SELECT value FROM meta WHERE key=?", (runtime.draft_key,)).fetchone()[0])
                operation(value)
                connection.execute("UPDATE meta SET value=? WHERE key=?",
                                   (json.dumps(value), runtime.draft_key))
        for mutate in (lambda runtime, proof: update_stage(
                           runtime, lambda value: value.update(status="failed")),
                       lambda runtime, proof: update_stage(
                           runtime, lambda value: value["output"].update(tampered=True)),
                       lambda runtime, proof: update_stage(
                           runtime, lambda value: value.update(missingUsage=True)),
                       lambda runtime, proof: runtime.job.update(approval={"forged": True}),
                       lambda runtime, proof: proof.update(specSha256="0" * 64)):
            with self.subTest(mutate=mutate):
                runtime = Runtime(self.root / ("case" + str(len(list(self.root.glob("case*"))))))
                for name, (relative, _) in self.hashes.items():
                    source = self.root / relative; target = runtime.root / relative
                    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read_bytes())
                original_runtime, original_proof = self.runtime, self.proof
                self.runtime, self.proof = runtime, copy.deepcopy(self.proof)
                mutate(self.runtime, self.proof)
                with self.assertRaises(ValueError): recovery.prepare(self.runtime, self.proof)
                self.assertEqual([], self.runtime.paid)
                self.assertFalse((self.runtime.root / "revision-render-resumes").exists())
                self.runtime, self.proof = original_runtime, original_proof

    def test_other_valid_owner_grant_cannot_be_combined_with_manual_scope(self):
        other = copy.deepcopy(self.proof)
        other["ownerGrant"]["taskRef"] = "owner-task:" + "d" * 64
        with self.assertRaisesRegex(ValueError, "owner_grant"):
            recovery.prepare(self.runtime, other)

    def test_postclaim_cache_guard_failure_is_terminal_without_model_call(self):
        manifest = recovery.prepare(self.runtime, self.proof)
        def fail(job, context):
            self.assertTrue(hasattr(self.runtime, "_cache_only_stage_keys"))
            raise RuntimeError("cache-only stage missing")
        self.runtime._make_article = fail
        with self.assertRaises(RuntimeError): recovery.execute(self.runtime, manifest, self.proof)
        self.assertEqual([], self.runtime.paid)
        result = json.loads((self.root / "revision-render-resumes" / recovery.JOB /
                             "result.json").read_text())
        self.assertEqual("requires_reconciliation", result["status"])
        with self.assertRaisesRegex(ValueError, "already_claimed"):
            recovery.prepare(self.runtime, self.proof)


class RuntimeCacheGuardTests(unittest.TestCase):
    class Budget:
        def __init__(self): self.entered = 0
        @contextmanager
        def scope(self, *args):
            self.entered += 1
            yield
    class Ledger:
        def assert_not_owner_held(self, _): return None
    class Journal:
        def __init__(self, key, *, record=True, cache=True):
            self.value, self.record, self.cache = key, record, cache
        def key(self, *args): return self.value
        def status(self, **kwargs):
            return {"records": ([{"stageKey": self.value, "status": "succeeded"}]
                                if self.record else [])}
        def run(self, job_id, stage, inputs, operation, max_attempts=2):
            return {"cached": True} if self.cache else operation()
    class Guard:
        _run_model_stage = EditorialRuntime._run_model_stage
        def __init__(self, key, *, record=True, cache=True):
            self.ledger = RuntimeCacheGuardTests.Ledger()
            self.stage_journal = RuntimeCacheGuardTests.Journal(
                key, record=record, cache=cache)
            self.model_budget = RuntimeCacheGuardTests.Budget()
            self.models = type("Models", (), {"usage": []})()
            self._cache_only_stage_keys = {"draft": recovery.DRAFT_KEY}
        def _require_running(self): return None
        def _budget_article_id(self, value): return value
        def _usage_slice(self, *args, **kwargs): return []
        def _flush_budget_notifications(self): return None

    def test_exact_cache_hit_never_enters_budget(self):
        runtime = self.Guard(recovery.DRAFT_KEY)
        calls = []
        result = runtime._run_model_stage({"id": recovery.JOB}, "draft", {},
                                          lambda: calls.append("model"), "model")
        self.assertEqual({"cached": True}, result)
        self.assertEqual([], calls); self.assertEqual(0, runtime.model_budget.entered)

    def test_key_drift_missing_record_and_cache_race_block_before_budget(self):
        cases = (("different", True, True), (recovery.DRAFT_KEY, False, True),
                 (recovery.DRAFT_KEY, True, False))
        for key, record, cache in cases:
            with self.subTest(key=key, record=record, cache=cache):
                runtime = self.Guard(key, record=record, cache=cache)
                with self.assertRaises(StageBlocked):
                    runtime._run_model_stage({"id": recovery.JOB}, "draft", {},
                                             lambda: self.fail("model called"), "model")
                self.assertEqual(0, runtime.model_budget.entered)


if __name__ == "__main__": unittest.main()
