"""Offline exact revision-SNS opt-in and owner-priority retirement contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dispatcher import buffer_social_eligible, buffer_social_outstanding
from ledger import Ledger, fingerprint
import revision_social_opt_in as optin
from test_social_publisher import approved_job


JOB = "revision-test000000000000000001"
REVISION = "a" * 64
NOW = "2026-11-29T04:06:44+09:00"
URL = "https://camp-gear-lab.com/articles/test"


def grant(job_id, revision, *, retirement=False):
    return {
        "schemaVersion": 1,
        "kind": optin.RETIREMENT_KIND if retirement else optin.OPT_IN_KIND,
        "scope": optin.RETIREMENT_SCOPE if retirement else optin.OPT_IN_SCOPE,
        "jobId": job_id,
        "revision": revision,
        "instructionReference": "codex-thread:owner-priority-20261129",
        "instructionSha256": "b" * 64,
    }


def revision_job(revision=REVISION):
    return {
        "id": JOB, "kind": "article_revision", "stage": "published",
        "revision": revision, "social": None, "theme": {"slug": "test"},
        "publication": {"verified": True, "revision": revision, "url": URL,
            "at": NOW, "remoteUpdatedAt": NOW,
            "readback": {"verified": True, "fingerprint": revision}},
    }


def buffer_job(index):
    return {"id": "article-" + str(index), "stage": "social_approved",
            "social": {"proposal": {"deliveryMode": "buffer_x"}}}


class Budget:
    config = {"article": {"calls": 32}, "period": {"calls": 128}}


class FakeLedger:
    def __init__(self, job, jobs=None):
        self.job = copy.deepcopy(job)
        self.jobs = copy.deepcopy(jobs if jobs is not None else [job])

    def get_job(self, job_id):
        if job_id != self.job["id"]:
            raise KeyError(job_id)
        return copy.deepcopy(self.job)

    def list_jobs(self):
        return copy.deepcopy(self.jobs)

    def arm_revision_social_opt_in(self, manifest):
        self.job["revisionSocialOptIn"] = copy.deepcopy(manifest)
        return copy.deepcopy(self.job)


class FakeRuntime:
    def __init__(self, root, job, jobs=None, ledger=None):
        self.root = root
        self.ledger = ledger or FakeLedger(job, jobs)
        self.model_budget = Budget()

    def _social_audit_success(self, job):
        return True

    def _budget_article_id(self, job_id):
        return "article:" + "c" * 64


def private_json(root, relative, value):
    path = root / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False)
    return path


def evidence(runtime, job, *, sitemap="current", verdict="PASS",
             crawl="2026-11-29T03:00:00+09:00"):
    publication = job["publication"]
    audit_key = fingerprint({"id": job["id"], "revision": job["revision"],
                             "publication": publication})
    audit = {"schemaVersion": 1, "id": job["id"], "revision": job["revision"],
             "publication": publication, "auditKey": audit_key, "status": "success",
             "result": {"passed": True, "status": "passed", "issues": []}}
    private_json(runtime.root, "post-publication-audits/" + audit_key + ".json", audit)
    index_key = fingerprint([job["id"], job["revision"], publication["at"]])
    inspection = {"verdict": verdict, "coverageState": "fixture",
                  "googleCanonical": URL, "lastCrawlTime": crawl}
    check = {"at": NOW, "day": 0, "sitemap": sitemap, "lastmod": NOW,
             "expectedLastmod": NOW,
             "index": "indexed" if verdict == "PASS" else "not_indexed",
             "inspection": inspection}
    private_json(runtime.root, "index-tracking/" + index_key + ".json",
                 {"id": job["id"], "revision": job["revision"], "url": URL,
                  "startedAt": NOW, "checks": [check]})


class RevisionSocialOptInTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "private"
        self.root.mkdir(mode=0o700)
        self.job = revision_job()
        self.runtime = FakeRuntime(self.root, self.job)
        evidence(self.runtime, self.job)
        self.targets = patch.dict(optin.TARGETS, {JOB: REVISION}, clear=True)
        self.targets.start()

    def tearDown(self):
        self.targets.stop()
        self.tmp.cleanup()

    def test_prepare_binds_owner_publication_audit_and_actual_stale_gsc_without_index_gate(self):
        manifest = optin.prepare(self.runtime, JOB, grant(JOB, REVISION))
        self.assertEqual("indexed_before_current_revision",
                         manifest["indexObservation"]["gscObservation"])
        self.assertEqual("current", manifest["indexObservation"]["sitemap"])
        self.assertEqual(fingerprint(self.job["publication"]), manifest["publicationSha256"])
        self.assertNotIn("instructionReference", json.dumps(manifest))
        wrong = grant(JOB, REVISION)
        wrong["instructionSha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "owner_grant"):
            optin.arm(self.runtime, manifest, wrong)

    def test_sitemap_must_be_current_but_actual_nonpass_gsc_is_allowed(self):
        root = Path(self.tmp.name) / "other"
        root.mkdir(mode=0o700)
        runtime = FakeRuntime(root, self.job)
        evidence(runtime, self.job, verdict="NEUTRAL")
        manifest = optin.prepare(runtime, JOB, grant(JOB, REVISION))
        self.assertEqual("not_indexed", manifest["indexObservation"]["gscObservation"])

        root = Path(self.tmp.name) / "missing"
        root.mkdir(mode=0o700)
        runtime = FakeRuntime(root, self.job)
        evidence(runtime, self.job, sitemap="missing")
        with self.assertRaisesRegex(ValueError, "index_observation"):
            optin.prepare(runtime, JOB, grant(JOB, REVISION))

    def test_outstanding_three_and_existing_attempt_block_without_model_or_approval(self):
        self.runtime.ledger.jobs = [self.job, buffer_job(1), buffer_job(2), buffer_job(3)]
        with self.assertRaisesRegex(ValueError, "outstanding_cap"):
            optin.prepare(self.runtime, JOB, grant(JOB, REVISION))
        self.runtime.ledger.jobs[-1]["stage"] = "social_rejected"
        self.assertEqual(JOB, optin.prepare(
            self.runtime, JOB, grant(JOB, REVISION))["jobId"])
        folder = self.root / "social-attempts"
        folder.mkdir(mode=0o700)
        private_json(self.root, "social-attempts/" + JOB + ".json", {"status": "in_flight"})
        with self.assertRaisesRegex(ValueError, "prior_attempt"):
            optin.prepare(self.runtime, JOB, grant(JOB, REVISION))

    def test_real_ledger_consumes_grant_into_separate_unapproved_social(self):
        root = Path(self.tmp.name) / "ledger"
        ledger = Ledger(root, "owner", target_account_id="123")
        fixture = approved_job()
        proposal, review = copy.deepcopy(fixture["social"]["proposal"]), copy.deepcopy(fixture["social"]["review"])
        fixture.update(id=JOB, kind="article_revision", stage="published", social=None,
                       theme={"slug": "test"}, week="2026-11-27", error=None,
                       approval={"article": "preserved"})
        fixture["publication"].update(at=NOW, remoteUpdatedAt=NOW)
        revision = fixture["revision"]
        with patch.dict(optin.TARGETS, {JOB: revision}, clear=True):
            with ledger._tx() as db:
                ledger._put(db, copy.deepcopy(fixture), "fixture")
            runtime = FakeRuntime(root, fixture, ledger=ledger)
            evidence(runtime, fixture)
            owner = grant(JOB, revision)
            manifest = optin.prepare(runtime, JOB, owner)
            armed = optin.arm(runtime, manifest, owner)
            self.assertIsNone(armed["social"])
            with patch("revisions.validate_revision_bundle", return_value=True):
                updated = ledger.record_social(JOB, proposal, review)
            self.assertEqual("social_review", updated["stage"])
            self.assertIsNone(updated["social"]["approval"])
            self.assertEqual("consumed", updated["revisionSocialOptInResult"]["status"])
            self.assertTrue(buffer_social_eligible(
                updated, {"bufferSocialStartPeriod": "2026-11-27"}))


class SocialPriorityRetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "private"
        self.ledger = Ledger(self.root, "owner", target_account_id="123")
        self.job = approved_job()
        self.job.update(id="article-retire", theme={"slug": "retire"}, week="2026-11-27",
                        error=None, approval={"article": "preserved"})
        proposal = self.job["social"]["proposal"]
        proposal.pop("targetAccountId")
        proposal.update(deliveryMode="buffer_x", targetAccountIdX="123",
                        buffer={"organizationId": "org", "channelId": "channel",
                                "schedulingPolicy": "next_available_slot"})
        revision = fingerprint(proposal)
        self.job["social"]["revision"] = revision
        self.job["social"]["review"]["fingerprint"] = revision
        self.job["social"]["approval"]["revision"] = revision
        self.revision = revision
        self.retirements = patch.dict(optin.RETIREMENTS, {self.job["id"]: revision}, clear=True)
        self.retirements.start()
        with self.ledger._tx() as db:
            self.ledger._put(db, copy.deepcopy(self.job), "fixture")
        self.request = self.ledger.create_request(self.job["id"], "social")
        with self.ledger._tx() as db:
            db.execute("INSERT INTO effects VALUES (?,?,?,?)",
                       (self.job["id"], "publish", "success",
                        json.dumps({"status": "success", "verified": True})))
        folder = self.root / "buffer-publications"
        folder.mkdir(mode=0o700)
        self.marker = private_json(self.root, "buffer-publications/" + revision + ".json", {
            "revision": revision, "proposalFingerprint": revision, "phase": "unverified",
            "pending": None, "dueAt": None, "bufferRequests": 4,
            "result": {"status": "unverified", "verified": False,
                       "reason": "buffer_daily_capacity_unverified"}})

    def tearDown(self):
        self.retirements.stop()
        self.tmp.cleanup()

    def test_retirement_preserves_article_social_history_requests_and_marker_bytes(self):
        owner = grant(self.job["id"], self.revision, retirement=True)
        manifest = optin.prepare_retirement(self.ledger, self.job["id"], owner)
        original_marker = self.marker.read_bytes()
        before = self.ledger.get_job(self.job["id"])
        updated = optin.apply_retirement(self.ledger, manifest, owner)
        self.assertEqual("social_rejected", updated["stage"])
        self.assertIsNone(updated["social"])
        for key in ("bundle", "revision", "publication", "approval"):
            self.assertEqual(before[key], updated[key])
        history = updated["socialHistory"][-1]
        self.assertEqual(before["social"], history["social"])
        self.assertEqual("owner_priority_retirement", history["reason"])
        self.assertEqual(["publish"], [item["kind"] for item in history["sourceEffects"]])
        self.assertEqual(original_marker, self.marker.read_bytes())
        with self.ledger._tx() as db:
            request = json.loads(db.execute(
                "SELECT data FROM requests WHERE id=?", (self.request["request_id"],)).fetchone()[0])
        self.assertEqual("invalidated", request["status"])
        self.assertEqual("created", history["requests"][0]["status"])
        self.assertEqual(0, buffer_social_outstanding([updated]))
        self.assertEqual(updated, optin.apply_retirement(self.ledger, manifest, owner))

    def test_remote_id_or_effect_blocks_retirement_and_preserves_state(self):
        value = json.loads(self.marker.read_text())
        value["postId"] = "remote"
        self.marker.write_text(json.dumps(value))
        before = self.ledger.get_job(self.job["id"])
        with self.assertRaisesRegex(ValueError, "retirement_remote_effect"):
            optin.prepare_retirement(
                self.ledger, self.job["id"], grant(self.job["id"], self.revision, retirement=True))
        self.assertEqual(before, self.ledger.get_job(self.job["id"]))

    def test_social_effect_blocks_but_successful_article_publish_effect_does_not(self):
        owner = grant(self.job["id"], self.revision, retirement=True)
        self.assertEqual("publish", optin.prepare_retirement(
            self.ledger, self.job["id"], owner)["state"]["sourceEffects"][0]["kind"])
        with self.ledger._tx() as db:
            db.execute("INSERT INTO effects VALUES (?,?,?,?)",
                       (self.job["id"], "social", "unknown",
                        json.dumps({"status": "unknown"})))
        with self.assertRaisesRegex(ValueError, "retirement_effect"):
            optin.prepare_retirement(self.ledger, self.job["id"], owner)


if __name__ == "__main__":
    unittest.main()
