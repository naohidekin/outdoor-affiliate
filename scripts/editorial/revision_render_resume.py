"""One explicit guide continuation after a deterministic render fix.

Draft and polish must be exact successful StageJournal cache hits. Both the
ordinary final-review and independent-review paths may make new paid calls.  Caller holds runtime.flock.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from ledger import canonical, fingerprint


JOB = "revision-f9ff27c8f570270bdd012b12"
SPEC_SHA = "8f1bd53b514c073b7eed1ba759b67aee1dd697e2066712fd5d46ad9e53f08ad0"
SCOPE = "guide_render_fix_cached_draft_polish_v1"
OWNER_GRANT_SHA = "7971cd7bfcbb89a599920c58d56b40ae99c57d595e6e7984e462bf26a581325e"
OWNER_RECEIPT_SHA = "6caee83229eba9ae01f7ebebadff2d3b8fd0d4331a29fe9bae7974198454b602"
DRAFT_KEY = "stage_journal:v1:f7fb4b207861bd2047f320b563bda207f1b14e3fe7f1e0626821ca940ab2f85b"
DRAFT_OUTPUT = "fd88db9119a3b12dab171c41e13465390fff124c333e1006fab05010cc5dd4cc"
POLISH_KEY = "stage_journal:v1:2dae167279bb4c938940f19ac8abaf57f97b4216d72cdc238b557a0633a1eadc"
POLISH_OUTPUT = "8fd6a00fac4f35db3b469632e698d527687267fc0b07979e3ea8dd2fab9f18eb"
ARTIFACTS = {
    "producer-marker.json": ("revision-production-attempts/" + JOB + ".json",
                             "4ed500c8f8b6f0ef2fcb48995542a71f3e028dc67b3cac0586c4934deaaeeacd"),
    "old-preview.json": ("previews/" + JOB +
                         "/b60ad9cb6d9e087b6eabf045e2b5c8200e8f0ab0b6a5317b175c86404d60b3dd/result.json",
                         "3eb0868b50162ea74dd29e0bffe5e52c366aa06733ffcb13dce5d77555020f43"),
    "old-source.json": ("research/artifacts/" + JOB +
                        "/e91bef2fbf7c01b075a667c7b7fbd7fdd68514ca2f81eebacbd28ad38c64c031/source.json",
                        "7c92fb48d2ebdaabcbdce1f85e026d3db1f6d45b5ef4a9c6dd3f2fd56f408533"),
    "old-candidate.json": ("research/artifacts/" + JOB +
                           "/e91bef2fbf7c01b075a667c7b7fbd7fdd68514ca2f81eebacbd28ad38c64c031/candidate.json",
                           "41e7b337395ae33384263b7e244f3dd37417e868d1bfe0ed86c8002722e0c40e"),
}


def require(condition, reason):
    if not condition:
        raise ValueError("revision_render_resume_" + reason)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_exact(root, relative, expected):
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()) and path.is_file()
            and not path.is_symlink(), "artifact_missing")
    raw = path.read_bytes()
    require(_sha(raw) == expected, "artifact_changed")
    return raw


def _write_exclusive(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _owner(runtime, proof):
    require(isinstance(proof, dict) and set(proof) == {
        "ownerGrant", "jobId", "specSha256", "scope"}, "owner_proof")
    require(proof["jobId"] == JOB and proof["specSha256"] == SPEC_SHA
            and proof["scope"] == SCOPE, "owner_scope")
    grant = runtime.ledger.validate_existing_improvement_owner_grant(proof["ownerGrant"])
    require(grant == proof["ownerGrant"] and fingerprint(grant) == OWNER_GRANT_SHA
            and grant.get("instructionReceiptSha256") == OWNER_RECEIPT_SHA,
            "owner_grant")
    return copy.deepcopy(proof)


def _state(runtime, owner_proof):
    runtime._require_running()
    proof = _owner(runtime, owner_proof)
    folder = runtime.root / "revision-render-resumes" / JOB
    require(not (folder / "claim.json").exists() and not (folder / "result.json").exists(),
            "already_claimed")
    job = runtime.ledger.get_job(JOB)
    require(job.get("kind") == "article_revision" and job.get("stage") == "error"
            and (job.get("error") or {}).get("reason") == "render_preview_failed"
            and all(job.get(key) is None for key in ("bundle", "review", "approval", "publication")),
            "job_state")
    require(fingerprint(job.get("revisionContext")) == SPEC_SHA
            and (job.get("theme") or {}).get("slug") ==
            "montbell-light-alpine-down-parka-1101606-guide", "specification")
    with sqlite3.connect(runtime.ledger.db_path) as db:
        records = [json.loads(row[0]) for row in db.execute(
            "SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
        records = [record for record in records if record.get("jobId") == JOB]
        require(len(records) == 2 and not any(record.get("stage") == "final_review"
                                              for record in records), "stage_scope")
        for key, stage, output in ((DRAFT_KEY, "draft", DRAFT_OUTPUT),
                                   (POLISH_KEY, "polish", POLISH_OUTPUT)):
            record = next((item for item in records if item.get("stageKey") == key), None)
            batches = record.get("usageBatches") if isinstance(record, dict) else None
            require(record is not None and record.get("stage") == stage
                    and record.get("status") == "succeeded" and record.get("attempts") == 1
                    and record.get("maxAttempts") == 2 and record.get("outputHash") == output
                    and fingerprint(record.get("output")) == output
                    and record.get("responseReceiptCount") == 1
                    and record.get("missingUsage") is False
                    and record.get("missingUsageAttemptCount") == 0
                    and isinstance(batches, list) and len(batches) == 1
                    and batches[0].get("reason") == "initial"
                    and batches[0].get("usageMissing") is False
                    and isinstance(batches[0].get("records"), list)
                    and len(batches[0]["records"]) == 1
                    and isinstance(batches[0]["records"][0].get("usage"), dict)
                    and not record.get("successorKey") and not record.get("predecessorKey"),
                    "cached_stage_changed")
        managers = db.execute("SELECT value FROM meta WHERE key LIKE 'editorial_manager:%'").fetchall()
        require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')",
                               (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM requests WHERE job_id=?", (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id IN (?,?) "
                                   "AND status IN ('reserved','in_flight','unknown')",
                                   (JOB, runtime._budget_article_id(JOB))).fetchone(), "unresolved")
    require(not any(runtime._revision_manager_blocks(row[0], job) for row in managers), "manager")
    artifacts = {name: {"relativePath": relative, "sha256": expected}
                 for name, (relative, expected) in ARTIFACTS.items()
                 if _read_exact(runtime.root, relative, expected) is not None}
    return job, proof, artifacts


def prepare(runtime, owner_proof):
    job, proof, artifacts = _state(runtime, owner_proof)
    manifest = {"schemaVersion": 1, "kind": SCOPE, "jobId": JOB,
                "specSha256": SPEC_SHA, "ownerProof": proof,
                "jobStateSha256": fingerprint({key: job.get(key) for key in
                                                ("id", "stage", "error", "revisionContext")}),
                "cachedStages": {"draft": {"stageKey": DRAFT_KEY, "outputHash": DRAFT_OUTPUT},
                                 "polish": {"stageKey": POLISH_KEY, "outputHash": POLISH_OUTPUT}},
                "artifacts": artifacts, "newPaidStagesAllowed": ["final_review", "independent_review"],
                "ownerApprovalGranted": False, "publicationAllowed": False}
    return {**manifest, "manifestSha256": fingerprint(manifest)}


def execute(runtime, manifest, owner_proof):
    """Single-use continuation. Caller must hold runtime.flock."""
    expected = prepare(runtime, owner_proof)
    require(manifest == expected, "manifest_changed")
    folder = runtime.root / "revision-render-resumes" / JOB
    claim = {"status": "claimed", "manifest": copy.deepcopy(manifest),
             "claimSha256": fingerprint(manifest)}
    _write_exclusive(folder / "claim.json", canonical(claim).encode())
    try:
        for name, binding in manifest["artifacts"].items():
            raw = _read_exact(runtime.root, binding["relativePath"], binding["sha256"])
            _write_exclusive(folder / "archive" / name, raw)
        require(not hasattr(runtime, "_cache_only_stage_keys"), "cache_guard_active")
        runtime._cache_only_stage_keys = {"draft": DRAFT_KEY, "polish": POLISH_KEY}
        try:
            result = runtime._make_article(runtime.ledger.get_job(JOB), runtime._context())
        finally:
            del runtime._cache_only_stage_keys
            runtime._save_usage()
        current = runtime.ledger.get_job(JOB)
        require(current.get("approval") is None and current.get("publication") is None,
                "approval_or_publication_changed")
    except Exception as error:
        failure = {"status": "requires_reconciliation", "jobId": JOB,
                   "manifestSha256": manifest["manifestSha256"],
                   "failureType": type(error).__name__, "ownerApprovalGranted": False,
                   "publicationPerformed": False}
        _write_exclusive(folder / "result.json", canonical(failure).encode())
        raise
    completed = {"status": "completed", "jobId": JOB,
                 "manifestSha256": manifest["manifestSha256"],
                 "resultSha256": fingerprint(result), "ownerApprovalGranted": False,
                 "publicationPerformed": False}
    _write_exclusive(folder / "result.json", canonical(completed).encode())
    return completed
