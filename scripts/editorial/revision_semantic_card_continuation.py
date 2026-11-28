"""Finite continuation after the guide semantic run failed before final review."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sqlite3

from ledger import canonical, fingerprint
from model_budget import _config
from purchase_evidence import require_prewrite_purchase_evidence, validate_purchase_evidence
from quality import inspect_polish
from revision_semantic_correction import _correct
from revisions import validate_context


JST = timezone(timedelta(hours=9))
JOB = "revision-f9ff27c8f570270bdd012b12"
SPEC_SHA = "8f1bd53b514c073b7eed1ba759b67aee1dd697e2066712fd5d46ad9e53f08ad0"
V1_REVISION = "c22e26965485682334d7ce26f80108d41dafb8f81a96829496728a94e95d6cd5"
SCOPE = "guide_semantic_social_card_continuation_v1"
OWNER_GRANT_SHA = "7971cd7bfcbb89a599920c58d56b40ae99c57d595e6e7984e462bf26a581325e"
OWNER_RECEIPT_SHA = "6caee83229eba9ae01f7ebebadff2d3b8fd0d4331a29fe9bae7974198454b602"
SEMANTIC_MANIFEST_SHA = "ed14270fb7fdadc1828ae2fed7d19d42f2e48a649792fc05c83815a6b79aa711"
POLISH_KEY = "stage_journal:v1:49797fbad1feb35154de594560e4612920a4414cb946f0af72af0c8ba6a13828"
POLISH_OUTPUT_SHA = "31a498d48089095f9d40f491de1970b0f087f2e67d484f44513370a238b49d9f"
POLISH_RECORD_SHA = "6564424bdd5a61fbae196593fa93d49cde33cf4c5b32101e01782d61b4a18192"
POLISH_CREATED_AT = "2026-11-28T23:19:06.530482+09:00"
BUDGET_CAPS = {"article": {"calls": 32, "inputTokens": 2_000_000, "outputTokens": 262_144},
               "period": {"calls": 128, "inputTokens": 8_000_000, "outputTokens": 1_048_576}}
ARTIFACTS = {
    "semantic-claim.json": ("revision-semantic-corrections/" + JOB + "/claim.json",
                            "80cf6cf5a846f605a1d8c4158f2c8edc8106818007f45b890c173ebc5e228095"),
    "semantic-result.json": ("revision-semantic-corrections/" + JOB + "/result.json",
                             "39a55c8e94ef5097190f0a366241e15caed2a11ca93f4d668e72c11135a0baa7"),
    "semantic-v1-archive.json": ("revision-semantic-corrections/" + JOB + "/v1-archive.json",
                                 "5a3715c5e624768885deeeddad6b6c6f8975898637854d71dcac8ef2e1565a4c"),
    "semantic-driver-claim.json": ("seo-loop-recovery/20261128/semantic-driver-claim.json",
                                   "eb204034e8f1a6c3dbd2886209b22525cbf0530c7966bf00d4e6db4b3815821c"),
    "semantic-driver-result.json": ("seo-loop-recovery/20261128/semantic-driver-result.json",
                                    "2cccc6efe0c6e583e4362cde7b010949e2f0580632d04c224f0d638b3381d9dd"),
}


def require(value, reason):
    if not value:
        raise ValueError("revision_semantic_card_continuation_" + reason)


def _read(root, relative, expected):
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()) and path.is_file()
            and not path.is_symlink(), "artifact_missing")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, "artifact_changed")
    return raw, json.loads(raw)


def _write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value).encode())
        stream.flush()
        os.fsync(stream.fileno())


def _owner(runtime, proof):
    require(isinstance(proof, dict) and set(proof) == {
        "ownerGrant", "jobId", "specSha256", "semanticManifestSha256", "scope"}, "owner_proof")
    require(proof["jobId"] == JOB and proof["specSha256"] == SPEC_SHA
            and proof["semanticManifestSha256"] == SEMANTIC_MANIFEST_SHA
            and proof["scope"] == SCOPE, "owner_scope")
    grant = runtime.ledger.validate_existing_improvement_owner_grant(proof["ownerGrant"])
    require(grant == proof["ownerGrant"] and fingerprint(grant) == OWNER_GRANT_SHA
            and grant.get("instructionReceiptSha256") == OWNER_RECEIPT_SHA, "owner_grant")
    return copy.deepcopy(proof)


def _baseline(runtime, job):
    context = runtime._wise_context(runtime._context())
    binding = validate_context(job["revisionContext"])
    base = binding["baseArticle"]
    live = next((article for article in context.get("revisionArticles", context.get("articles", []))
                 if article.get("id") == base["id"]), None)
    require(live is not None and fingerprint(live) == binding["baseHash"], "live_baseline")
    products = {product["id"]: product for product in context.get("products", [])}
    require(all(products.get(product["id"]) == product for product in binding["baseProducts"]),
            "live_product_baseline")
    return context, binding


def _state(runtime, owner_proof):
    runtime._require_running()
    proof = _owner(runtime, owner_proof)
    folder = runtime.root / "revision-semantic-card-continuations" / JOB
    require(not (folder / "claim.json").exists() and not (folder / "result.json").exists(),
            "already_claimed")
    job = runtime.ledger.get_job(JOB)
    require(job.get("kind") == "article_revision" and job.get("stage") == "review"
            and job.get("revision") == V1_REVISION and fingerprint(job.get("bundle")) == V1_REVISION
            and job.get("astraReview") is None and job.get("approval") is None
            and job.get("publication") is None, "job_state")
    require(fingerprint(validate_context(job.get("revisionContext"))) == SPEC_SHA, "specification")
    limits = _config(runtime.config.get("modelBudget"))
    require({scope: {key: limits[scope][key] for key in ("calls", "inputTokens", "outputTokens")}
             for scope in ("article", "period")} == BUDGET_CAPS, "budget_caps")
    context, binding = _baseline(runtime, job)
    raw = {}; artifacts = {}
    for name, (relative, expected) in ARTIFACTS.items():
        body, value = _read(runtime.root, relative, expected)
        raw[name] = (body, value)
        artifacts[name] = {"relativePath": relative, "sha256": expected}
    claim = raw["semantic-claim.json"][1]
    result = raw["semantic-result.json"][1]
    archive = raw["semantic-v1-archive.json"][1]
    driver_claim = raw["semantic-driver-claim.json"][1]
    driver_result = raw["semantic-driver-result.json"][1]
    manifest = claim.get("manifest") or {}
    require(claim.get("status") == "claimed" and manifest.get("manifestSha256") == SEMANTIC_MANIFEST_SHA
            and manifest.get("jobId") == JOB and manifest.get("v1Revision") == V1_REVISION
            and manifest.get("specSha256") == SPEC_SHA, "semantic_claim")
    require(result == {"failureType": "ValueError", "jobId": JOB,
                       "manifestSha256": SEMANTIC_MANIFEST_SHA, "ownerApprovalGranted": False,
                       "publicationPerformed": False, "status": "requires_reconciliation"},
            "semantic_result")
    require(driver_claim.get("manifestSha256") == SEMANTIC_MANIFEST_SHA
            and driver_claim.get("status") == "claimed"
            and driver_result.get("status") == "completed"
            and driver_result.get("result") == {"status": "attention",
                                                  "reason": "social_card_evidence_missing"},
            "driver_result")
    require(fingerprint(archive.get("bundle")) == V1_REVISION
            and isinstance(archive.get("freshSource"), dict)
            and fingerprint(archive["freshSource"].get("gathered")) ==
            archive["freshSource"].get("fingerprint"), "semantic_archive")
    with sqlite3.connect(runtime.ledger.db_path) as db:
        row = db.execute("SELECT value FROM meta WHERE key=?", (POLISH_KEY,)).fetchone()
        require(row is not None, "polish_missing")
        polish = json.loads(row[0])
        require(fingerprint(polish) == POLISH_RECORD_SHA and polish.get("stageKey") == POLISH_KEY
                and polish.get("stage") == "polish" and polish.get("status") == "succeeded"
                and polish.get("createdAt") == POLISH_CREATED_AT and polish.get("attempts") == 1
                and polish.get("maxAttempts") == 2 and polish.get("outputHash") == POLISH_OUTPUT_SHA
                and fingerprint(polish.get("output")) == POLISH_OUTPUT_SHA
                and polish.get("responseReceiptCount") == 1 and polish.get("missingUsage") is False
                and polish.get("missingUsageAttemptCount") == 0 and not polish.get("successorKey")
                and not polish.get("predecessorKey"), "polish_changed")
        later = [json.loads(value) for value, in db.execute(
            "SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
        require(not any(item.get("jobId") == JOB and item.get("stage") in
                        ("final_review", "independent_review")
                        and str(item.get("createdAt", "")) >= POLISH_CREATED_AT for item in later),
                "later_review_exists")
        managers = db.execute("SELECT value FROM meta WHERE key LIKE 'editorial_manager:%'").fetchall()
        require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')",
                               (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM requests WHERE job_id=?", (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id IN (?,?) "
                                   "AND status IN ('reserved','in_flight','unknown')",
                                   (JOB, runtime._budget_article_id(JOB))).fetchone(), "unresolved")
    require(not any(runtime._revision_manager_blocks(value, job) for value, in managers), "manager")
    source = _correct(archive["bundle"])
    source.pop("purchaseEvidence", None)
    saved_gathered = archive["freshSource"]["gathered"]
    if saved_gathered.get("purchaseEvidence"):
        source["purchaseEvidence"] = copy.deepcopy(saved_gathered["purchaseEvidence"])
    require(fingerprint(source) == manifest.get("correctedSourceSha256"), "corrected_source")
    require(source.get("wisePolicy") == (context.get("wisePolicy") or {}).get("id"),
            "wise_policy_changed")
    output = polish["output"]
    require(inspect_polish(source["article"]["content"], output["polished"]["content"])
            == output["preservation"] and output["preservation"].get("passed") is True,
            "polish_preservation")
    return job, proof, context, binding, source, output, saved_gathered, artifacts, raw, polish


def prepare(runtime, owner_proof):
    job, proof, context, binding, source, output, saved, artifacts, raw, polish = _state(
        runtime, owner_proof)
    manifest = {"schemaVersion": 1, "kind": SCOPE, "jobId": JOB, "specSha256": SPEC_SHA,
                "semanticManifestSha256": SEMANTIC_MANIFEST_SHA, "ownerProof": proof,
                "jobRevision": V1_REVISION, "correctedSourceSha256": fingerprint(source),
                "savedFreshSourceSha256": fingerprint(saved),
                "cachedPolish": {"stageKey": POLISH_KEY, "outputHash": POLISH_OUTPUT_SHA,
                                  "recordSha256": POLISH_RECORD_SHA},
                "artifacts": artifacts,
                "newPaidStagesAllowed": ["final_review", "independent_review"],
                "ownerApprovalGranted": False, "publicationAllowed": False}
    return {**manifest, "manifestSha256": fingerprint(manifest)}


def execute(runtime, manifest, owner_proof):
    """Continue once under runtime.flock; never calls draft or polish."""
    state = _state(runtime, owner_proof)
    job, proof, context, binding, source, output, saved, artifacts, raw, polish = state
    require(manifest == prepare(runtime, owner_proof), "manifest_changed")
    gathered = runtime.catalog.gather_revision(job["theme"], context, binding)
    require(all(gathered.get("checks", {}).get(key) is True for key in
                ("facts", "images", "affiliate")) and not gathered.get("blocked"), "fresh_source")
    now = datetime.now(JST)
    require_prewrite_purchase_evidence(gathered, now)
    normalized = runtime._source_dependencies(gathered)
    for field in ("products", "images", "references"):
        require(runtime._source_dependencies({field: gathered.get(field)}) ==
                runtime._source_dependencies({field: saved.get(field)}), "fresh_" + field)
    source = copy.deepcopy(source)
    source.pop("purchaseEvidence", None)
    if gathered.get("purchaseEvidence"):
        source = validate_purchase_evidence(source, gathered["purchaseEvidence"], now)
    polished, preservation = copy.deepcopy(output["polished"]), copy.deepcopy(output["preservation"])
    bundle = copy.deepcopy(source)
    bundle["article"]["content"] = polished["content"]
    folder = runtime.root / "revision-semantic-card-continuations" / JOB
    _write_once(folder / "claim.json", {"status": "claimed", "manifest": manifest,
                "freshSourceSha256": fingerprint(normalized)})
    _write_once(folder / "current-fresh-source.json",
                {"kind": "current_normalized_revision_source_v1", "gathered": normalized,
                 "fingerprint": fingerprint(normalized)})
    for name, (body, value) in raw.items():
        path = folder / "archive" / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
    _write_once(folder / "archive" / "semantic-polish-stage.json", polish)
    try:
        result = runtime._finish_article_review(job, context, gathered, bundle, source,
                                                preservation, polished, normalized)
        current = runtime.ledger.get_job(JOB)
        require(current.get("approval") is None and current.get("publication") is None,
                "approval_or_publication_changed")
    except Exception as error:
        _write_once(folder / "result.json", {"status": "requires_reconciliation", "jobId": JOB,
                    "manifestSha256": manifest["manifestSha256"],
                    "failureType": type(error).__name__, "ownerApprovalGranted": False,
                    "publicationPerformed": False})
        raise
    finally:
        runtime._save_usage()
    completed = {"status": "completed", "jobId": JOB,
                 "manifestSha256": manifest["manifestSha256"],
                 "resultSha256": fingerprint(result), "ownerApprovalGranted": False,
                 "publicationPerformed": False}
    _write_once(folder / "result.json", completed)
    return completed
