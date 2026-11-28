"""Finite owner opt-in for SNS after two exact published article revisions."""
import copy
from datetime import datetime
import hashlib
import json
import re

from ledger import canonical, fingerprint


TARGETS = {
    "revision-81d57bccd5f033c369187f4d":
        "b4ce9c20e9583518017b513122d808b9ee9608b2aacd0964438e0f47991d54e5",
    "revision-f9ff27c8f570270bdd012b12":
        "ded75faab74686aebee40963df0454c429b7519ca240bb7ae52cb0aa7d57ae7c",
}
RETIREMENTS = {
    "article-eb2ead3c6e9b793107f9e127":
        "64d47f50eea066b611718ebfb8e06053a8a743d7ff1ef209091d28a6f0451546",
    "article-42e59288744a55545f896d2d":
        "3d5014172910959e92850985a3308abf69a139d4b811cca1ca82ab2f6d6994d6",
}
OPT_IN_KIND = "owner_exact_revision_social_opt_in_v1"
RETIREMENT_KIND = "owner_priority_retirement_v1"
OPT_IN_SCOPE = "exact_two_revision_social_after_publication_v1"
RETIREMENT_SCOPE = "exact_two_inactive_buffer_socials_v1"
SHA = re.compile(r"[a-f0-9]{64}")


def require(value, reason):
    if not value:
        raise ValueError("revision_social_opt_in_" + reason)


def _owner_grant(value, job_id, revision, kind, scope):
    fields = {"schemaVersion", "kind", "scope", "jobId", "revision",
              "instructionReference", "instructionSha256"}
    require(isinstance(value, dict) and set(value) == fields
            and value.get("schemaVersion") == 1 and value.get("kind") == kind
            and value.get("scope") == scope and value.get("jobId") == job_id
            and value.get("revision") == revision
            and isinstance(value.get("instructionReference"), str)
            and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,240}", value["instructionReference"])
            and SHA.fullmatch(str(value.get("instructionSha256", ""))), "owner_grant")
    return json.loads(canonical(value))


def _publication(job):
    publication = job.get("publication") or {}
    readback = publication.get("readback") or {}
    require(job.get("kind") == "article_revision" and job.get("stage") == "published"
            and job.get("revision") == TARGETS.get(job.get("id"))
            and publication.get("verified") is True
            and publication.get("revision") == job.get("revision")
            and readback.get("verified") is True
            and readback.get("fingerprint") == job.get("revision")
            and isinstance(publication.get("url"), str)
            and publication["url"].startswith("https://camp-gear-lab.com/articles/")
            and not job.get("social"), "publication")
    return publication


def _private_json(path):
    require(path.is_file() and not path.is_symlink()
            and path.stat().st_mode & 0o777 == 0o600, "evidence_file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError):
        raise ValueError("revision_social_opt_in_evidence_file") from None
    return raw, value


def _audit(runtime, job, publication):
    require(runtime._social_audit_success(job) is True, "post_audit")
    key = fingerprint({"id": job["id"], "revision": job["revision"],
                       "publication": publication})
    relative = "post-publication-audits/" + key + ".json"
    raw, value = _private_json(runtime.root / relative)
    result = value.get("result") or {}
    require(value.get("schemaVersion") == 1 and value.get("id") == job["id"]
            and value.get("revision") == job["revision"]
            and value.get("publication") == publication and value.get("auditKey") == key
            and value.get("status") == "success" and result.get("passed") is True
            and result.get("status") == "passed" and result.get("issues") == [], "post_audit")
    return {"path": relative, "sha256": hashlib.sha256(raw).hexdigest()}


def _instant(value, reason):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError("revision_social_opt_in_" + reason) from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, reason)
    return parsed


def _index_observation(runtime, job, publication):
    key = fingerprint([job["id"], job["revision"], publication.get("at")])
    relative = "index-tracking/" + key + ".json"
    _, value = _private_json(runtime.root / relative)
    checks = value.get("checks")
    require(value.get("id") == job["id"] and value.get("revision") == job["revision"]
            and value.get("url") == publication["url"]
            and isinstance(checks, list) and checks, "index_observation")
    latest = checks[-1]
    proof = latest.get("inspection") if isinstance(latest, dict) else None
    require(isinstance(latest, dict) and latest.get("sitemap") == "current"
            and isinstance(proof, dict) and proof.get("verdict") in {"PASS", "NEUTRAL", "FAIL"}
            and not proof.get("error"), "index_observation")
    crawl = proof.get("lastCrawlTime")
    if proof["verdict"] != "PASS":
        observation = "not_indexed"
    elif proof.get("googleCanonical") != publication["url"]:
        observation = "canonical_unverified"
    elif crawl is None:
        observation = "indexed_crawl_time_unavailable"
    elif _instant(crawl, "last_crawl_time") < _instant(
            publication.get("remoteUpdatedAt"), "publication_update_time"):
        observation = "indexed_before_current_revision"
    else:
        observation = "indexed_current_revision"
    return {"path": relative, "checkSha256": fingerprint(latest),
            "sitemap": latest["sitemap"], "index": latest.get("index"),
            "gscObservation": observation, "lastCrawlTime": crawl}


def validate_manifest(value):
    fields = {"schemaVersion", "kind", "scope", "jobId", "revision",
              "publicationSha256", "postAudit", "indexObservation",
              "ownerGrantSha256", "budgetArticleId"}
    require(isinstance(value, dict) and set(value) == fields
            and value.get("schemaVersion") == 1 and value.get("kind") == OPT_IN_KIND
            and value.get("scope") == OPT_IN_SCOPE
            and TARGETS.get(value.get("jobId")) == value.get("revision")
            and all(SHA.fullmatch(str(value.get(key, "")))
                    for key in ("publicationSha256", "ownerGrantSha256"))
            and isinstance(value.get("budgetArticleId"), str)
            and value["budgetArticleId"].startswith("article:"), "manifest")
    audit, index = value.get("postAudit"), value.get("indexObservation")
    require(isinstance(audit, dict) and set(audit) == {"path", "sha256"}
            and audit["path"].startswith("post-publication-audits/")
            and SHA.fullmatch(str(audit["sha256"])), "manifest")
    require(isinstance(index, dict) and set(index) == {
                "path", "checkSha256", "sitemap", "index", "gscObservation", "lastCrawlTime"}
            and index["path"].startswith("index-tracking/")
            and SHA.fullmatch(str(index["checkSha256"]))
            and index["gscObservation"] in {"not_indexed", "canonical_unverified",
                "indexed_crawl_time_unavailable", "indexed_before_current_revision",
                "indexed_current_revision"}, "manifest")
    return json.loads(canonical(value))


def prepare(runtime, job_id, owner_grant):
    require(job_id in TARGETS, "target")
    job = runtime.ledger.get_job(job_id)
    publication = _publication(job)
    grant = _owner_grant(owner_grant, job_id, job["revision"], OPT_IN_KIND, OPT_IN_SCOPE)
    require(not (runtime.root / "social-attempts" / (job_id + ".json")).exists(), "prior_attempt")
    from dispatcher import buffer_social_outstanding
    require(buffer_social_outstanding(runtime.ledger.list_jobs()) < 3, "outstanding_cap")
    limits = runtime.model_budget.config
    require(limits["article"]["calls"] <= 32 and limits["period"]["calls"] <= 128,
            "budget_caps")
    manifest = {"schemaVersion": 1, "kind": OPT_IN_KIND, "scope": OPT_IN_SCOPE,
        "jobId": job_id, "revision": job["revision"],
        "publicationSha256": fingerprint(publication),
        "postAudit": _audit(runtime, job, publication),
        "indexObservation": _index_observation(runtime, job, publication),
        "ownerGrantSha256": fingerprint(grant),
        "budgetArticleId": runtime._budget_article_id(job_id)}
    return validate_manifest(manifest)


def require_ready(runtime, job):
    manifest = validate_manifest(job.get("revisionSocialOptIn"))
    publication = _publication(job)
    require(manifest["publicationSha256"] == fingerprint(publication)
            and manifest["budgetArticleId"] == runtime._budget_article_id(job["id"]), "state_drift")
    require(manifest["postAudit"] == _audit(runtime, job, publication), "state_drift")
    current = _index_observation(runtime, job, publication)
    require(current["path"] == manifest["indexObservation"]["path"], "state_drift")
    raw = json.loads((runtime.root / current["path"]).read_text())
    require(any(fingerprint(item) == manifest["indexObservation"]["checkSha256"]
                for item in raw.get("checks", []) if isinstance(item, dict)), "state_drift")
    return manifest


def eligible(job):
    try:
        manifest = validate_manifest(job.get("revisionSocialOptIn"))
        return (job.get("kind") == "article_revision" and job.get("stage") == "published"
                and not job.get("social") and manifest["jobId"] == job.get("id")
                and manifest["revision"] == job.get("revision"))
    except (TypeError, ValueError):
        return False


def authorized(job):
    """Keep the exact grant valid through review/approval/scheduling, never for another revision."""
    try:
        manifest = validate_manifest(job.get("revisionSocialOptIn"))
        if (job.get("kind") != "article_revision" or manifest["jobId"] != job.get("id")
                or manifest["revision"] != job.get("revision")):
            return False
        result = job.get("revisionSocialOptInResult")
        if result is None:
            return eligible(job)
        social = job.get("social") or {}
        return (isinstance(result, dict) and result.get("status") == "consumed"
                and result.get("manifestSha256") == fingerprint(manifest)
                and result.get("socialRevision") == social.get("revision")
                and fingerprint(social.get("proposal")) == social.get("revision"))
    except (TypeError, ValueError):
        return False


def arm(runtime, manifest, owner_grant):
    manifest = validate_manifest(manifest)
    grant = _owner_grant(owner_grant, manifest["jobId"], manifest["revision"],
                         OPT_IN_KIND, OPT_IN_SCOPE)
    require(manifest["ownerGrantSha256"] == fingerprint(grant), "owner_grant")
    require(prepare(runtime, manifest["jobId"], grant) == manifest, "state_drift")
    return runtime.ledger.arm_revision_social_opt_in(manifest)


def _retirement_state(ledger, job, db):
    revision = RETIREMENTS.get(job.get("id"))
    social = job.get("social") or {}
    proposal = social.get("proposal") or {}
    require(revision and job.get("stage") == "social_approved"
            and social.get("revision") == revision
            and fingerprint(proposal) == revision
            and proposal.get("deliveryMode") == "buffer_x"
            and not social.get("publication")
            and (social.get("approval") or {}).get("action") == "approved"
            and (social.get("approval") or {}).get("revision") == revision, "retirement_state")
    effects = [dict(kind=row[0], status=row[1], dataSha256=fingerprint(json.loads(row[2])))
               for row in db.execute("SELECT kind,status,data FROM effects WHERE job_id=?", (job["id"],))]
    require(not any(item["kind"] == "social" or item["kind"].startswith("buffer")
                    for item in effects), "retirement_effect")
    marker = ledger.root / "buffer-publications" / (revision + ".json")
    raw, value = _private_json(marker)
    forbidden = {"postId", "draftPostId", "createIntent", "scheduleIntent", "publicationIntent"}
    result = value.get("result") or {}
    require(value.get("revision") == revision and value.get("proposalFingerprint") == revision
            and value.get("phase") == "unverified" and value.get("pending") is None
            and value.get("dueAt") is None and not forbidden.intersection(value)
            and result.get("status") == "unverified" and result.get("verified") is False
            and result.get("reason") == "buffer_daily_capacity_unverified"
            and not (ledger.root / "social-outbox" / (revision + ".json")).exists()
            and not (ledger.root / "social-publications" / (revision + ".json")).exists(),
            "retirement_remote_effect")
    requests = [json.loads(row[0]) for row in db.execute(
        "SELECT data FROM requests WHERE job_id=? AND kind='social' ORDER BY id", (job["id"],))]
    return {"jobSha256": fingerprint(job), "socialRevision": revision,
            "bufferJournal": {"path": "buffer-publications/" + marker.name,
                              "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
            "requests": requests, "sourceEffects": effects}


def prepare_retirement(ledger, job_id, owner_grant):
    require(job_id in RETIREMENTS, "retirement_target")
    grant = _owner_grant(owner_grant, job_id, RETIREMENTS[job_id],
                         RETIREMENT_KIND, RETIREMENT_SCOPE)
    with ledger._tx() as db:
        job = ledger._get(db, job_id)
        state = _retirement_state(ledger, job, db)
    return {"schemaVersion": 1, "kind": RETIREMENT_KIND, "scope": RETIREMENT_SCOPE,
            "jobId": job_id, "revision": RETIREMENTS[job_id],
            "ownerGrantSha256": fingerprint(grant), "state": state}


def validate_retirement_manifest(manifest):
    require(isinstance(manifest, dict) and set(manifest) == {
        "schemaVersion", "kind", "scope", "jobId", "revision", "ownerGrantSha256", "state"}
        and manifest.get("schemaVersion") == 1 and manifest.get("kind") == RETIREMENT_KIND
        and manifest.get("scope") == RETIREMENT_SCOPE
        and RETIREMENTS.get(manifest.get("jobId")) == manifest.get("revision")
        and SHA.fullmatch(str(manifest.get("ownerGrantSha256", "")))
        and isinstance(manifest.get("state"), dict), "retirement_manifest")
    return json.loads(canonical(manifest))


def apply_retirement(ledger, manifest, owner_grant):
    manifest = validate_retirement_manifest(manifest)
    grant = _owner_grant(owner_grant, manifest["jobId"], manifest["revision"],
                         RETIREMENT_KIND, RETIREMENT_SCOPE)
    require(manifest["ownerGrantSha256"] == fingerprint(grant), "owner_grant")
    return ledger.retire_social_priority(copy.deepcopy(manifest), grant)
