"""Read-only lineage and post-change SEO measurement projection.

The caller supplies one ledger job and the existing sanitized Analytics context.
This module performs no provider calls, writes, approvals, or causal attribution.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ledger import fingerprint


JST = timezone(timedelta(hours=9))
HASH = re.compile(r"^[a-f0-9]{64}$")
MAX_RECEIPT_BYTES = 256 * 1024


def _hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode()
    return _hash_bytes(encoded)


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _read(root, relative):
    path = Path(root).resolve() / relative
    if not path.exists():
        return "missing", None, None
    try:
        if (path.is_symlink() or path.parent.is_symlink() or not path.is_file()
                or path.stat().st_size > MAX_RECEIPT_BYTES):
            return "invalid", None, None
        raw = path.read_bytes()
        return "ok", json.loads(raw), _hash_bytes(raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return "invalid", None, None


def _result(status, reason, job_id=None, revision=None, **extra):
    value = {"schemaVersion": 1, "status": status, "reason": reason,
             "jobId": job_id, "revision": revision,
             "workflow": {"status": "not_observed"},
             "measurement": {"status": "not_measured", "effect": "not_causally_attributed"},
             "limitations": [
                 "Workflow completion is distinct from measured post-change performance.",
                 "Missing page measurements are unknown, never zero.",
                 "Before/after changes are observations, not proof that editing caused them.",
             ]}
    value.update(extra)
    return value


def _lineage(job, owner_id):
    if not isinstance(job, dict):
        return None, "not_analysis_revision"
    context = job.get("revisionContext")
    analysis = context.get("analysisBinding") if isinstance(context, dict) else None
    routine = job.get("kind") == "article_revision" and isinstance(analysis, dict) \
        and analysis.get("kind") == "routine_existing_improvement_v1"
    if not routine and job.get("kind") == "article_revision":
        return None, "not_analysis_revision"
    base = context.get("baseArticle") if routine else None
    theme = job.get("theme")
    if not routine and (not isinstance(theme, dict) or "sourceIds" not in theme):
        return None, "not_analysis_revision"
    revision = job.get("revision")
    approval = job.get("approval")
    publication = job.get("publication")
    readback = publication.get("readback") if isinstance(publication, dict) else None
    metrics = analysis.get("metricsReceipt") if routine else None
    proof = analysis.get("sourceProof") if routine else None
    slug = base.get("slug") if routine and isinstance(base, dict) else (
        theme.get("slug") if isinstance(theme, dict) else None)
    url = "https://camp-gear-lab.com/articles/" + str(slug or "")
    if (not isinstance(owner_id, str) or not owner_id.strip() or not isinstance(theme, dict)
            or not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)):
        return None, "lineage_binding_invalid"
    if routine and (not isinstance(base, dict) or theme.get("slug") != base.get("slug")
            or theme.get("productIds") != context.get("targetProductIds")
            or analysis.get("targetUrl") != url
            or not isinstance(metrics, dict) or not isinstance(proof, dict)
            or not re.fullmatch(r"analytics:[a-f0-9]{64}", str(metrics.get("sourceId", "")))
            or not all(HASH.fullmatch(str(metrics.get(key, ""))) for key in
                       ("opportunityHash", "candidateSetHash", "protectedWinnerUrlsHash"))
            or not HASH.fullmatch(str(proof.get("receiptHash", "")))
            or proof.get("sourceId") != "catalog-gather:" + str(proof.get("receiptHash", ""))
            or proof.get("productIds") != context.get("targetProductIds")
            or proof.get("checks") != {"facts": True, "images": True, "affiliate": True}):
        return None, "lineage_binding_invalid"
    theme_evidence = None
    if not routine:
        source_ids = theme.get("sourceIds")
        contract = theme.get("nonProductContract")
        if (not isinstance(source_ids, list) or not source_ids
                or len(source_ids) != len(set(source_ids))
                or any(not isinstance(item, str) or not item for item in source_ids)):
            return None, "not_analysis_revision"
        theme_evidence = {"sourceIds": sorted(source_ids),
                          "searchDemandEvidence": theme.get("searchDemandEvidence")}
        if theme.get("productIds") == []:
            refs = contract.get("references") if isinstance(contract, dict) else None
            receipt = contract.get("sourceReceiptSha256") if isinstance(contract, dict) else None
            if (not isinstance(refs, list) or not refs or not HASH.fullmatch(str(receipt or ""))
                    or [item.get("id") for item in refs] !=
                       [item for item in source_ids if item.startswith("public:")]
                    or any(not HASH.fullmatch(str(item.get("receiptSha256", ""))) for item in refs)):
                return None, "lineage_binding_invalid"
            theme_evidence["nonProductSourceReceiptSha256"] = receipt
            theme_evidence["publicSourceIds"] = [item["id"] for item in refs]
        try:
            theme_evidence = _canonical_hash(theme_evidence)
        except (TypeError, ValueError, OverflowError):
            return None, "lineage_binding_invalid"
    if not isinstance(approval, dict):
        return None, "waiting_owner_approval"
    if (not isinstance(revision, str) or not HASH.fullmatch(revision)
            or approval.get("user_id") != owner_id or approval.get("revision") != revision):
        return None, "owner_revision_approval_invalid"
    if approval.get("source") == "codex":
        evidence = approval.get("evidence")
        try:
            expected = ("codex-" + fingerprint({"article_id": job.get("id"), "revision": revision,
                        "actor": owner_id, "evidence": evidence}) if isinstance(evidence, dict) else None)
        except (TypeError, ValueError, OverflowError):
            expected = None
        if (not isinstance(evidence, dict) or evidence.get("source") != "codex"
                or not all(isinstance(evidence.get(key), str) and evidence[key].strip()
                           for key in ("thread_id", "message_id", "text"))
                or approval.get("request_id") != expected):
            return None, "owner_revision_approval_invalid"
    elif approval.get("action") != "approved":
        return None, "owner_revision_approval_invalid"
    approved_at = _instant(approval.get("at"))
    if approved_at is None:
        return None, "owner_revision_approval_invalid"
    if not isinstance(publication, dict) or publication.get("verified") is not True:
        return None, "waiting_publication"
    published_at = _instant(publication.get("at"))
    if (published_at is None or approved_at > published_at
            or publication.get("revision") != revision or publication.get("url") != url
            or not isinstance(readback, dict) or readback.get("verified") is not True
            or readback.get("fingerprint") != revision):
        return None, "verified_publication_missing"
    if routine:
        baseline = metrics.get("currentPeriod")
        if not isinstance(baseline, dict) or not _day(baseline.get("startDate")) or not _day(baseline.get("endDate")):
            return None, "analysis_baseline_missing"
    return {"context": context, "analysis": analysis, "approvalAt": approved_at,
            "publicationAt": published_at, "url": url, "revision": revision,
            "kind": "routine_revision" if routine else "new_content",
            "themeEvidenceSha256": theme_evidence}, None


def _workflow(job, root, lineage):
    revision, publication = lineage["revision"], job["publication"]
    audit_key = fingerprint({"id": job["id"], "revision": revision, "publication": publication})
    audit_state, audit, audit_sha = _read(
        root, Path("post-publication-audits") / (audit_key + ".json"))
    index_key = fingerprint([job["id"], revision, publication["at"]])
    index_state, tracking, index_sha = _read(root, Path("index-tracking") / (index_key + ".json"))
    if audit_state == "missing":
        return None, "waiting_postpublication_audit", None
    if (audit_state != "ok" or index_state == "invalid" or not isinstance(audit, dict)
            or tracking is not None and not isinstance(tracking, dict)):
        return None, "postpublication_evidence_invalid", None
    attempts = audit.get("attempts") if isinstance(audit, dict) else None
    checks = tracking.get("checks") if isinstance(tracking, dict) else None
    latest = checks[-1] if isinstance(checks, list) and checks else None
    if (audit.get("schemaVersion") != 1 or audit.get("auditKey") != audit_key
            or audit.get("id") != job["id"] or audit.get("revision") != revision
            or audit.get("publication") != publication or not isinstance(attempts, list)):
        return None, "postpublication_evidence_invalid", None
    if (audit.get("status") != "success" or not attempts
            or attempts[-1].get("status") != "success"
            or (attempts[-1].get("result") or {}).get("passed") is not True):
        return None, "waiting_postpublication_audit", None
    index_status = "waiting_indexing"
    hashes = {"auditReceiptSha256": audit_sha}
    if tracking is not None:
        if (not isinstance(tracking, dict) or tracking.get("id") != job["id"]
                or tracking.get("revision") != revision or tracking.get("url") != lineage["url"]):
            return None, "postpublication_evidence_invalid", None
        hashes["indexReceiptSha256"] = index_sha
        if isinstance(latest, dict):
            if latest.get("expectedLastmod") != publication.get("remoteUpdatedAt"):
                return None, "postpublication_evidence_invalid", None
            if latest.get("sitemap") == "current" and latest.get("index") == "indexed":
                index_status = "indexed"
    selection = "routine_analysis_binding" if lineage["kind"] == "routine_revision" else "theme_source_binding"
    return ({"status": "publication_observed", "analysisSelection": selection,
             "ownerRevisionApproval": "observed", "publication": "verified",
             "postPublicationAudit": "passed", "indexTracking": index_status}, None, hashes)


def _number(value):
    try:
        return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) else None)
    except (OverflowError, ValueError):
        return None


def _period(source):
    if not isinstance(source, dict) or source.get("status") != "ok":
        return None
    start, end, settled = (_day(source.get(key)) for key in
                           ("startDate", "endDate", "settledThrough"))
    try:
        zone = ZoneInfo(source.get("dateBasis"))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return None
    if not start or not end or not settled or start > end or settled != end:
        return None
    return start, end, zone


def _page(source, url):
    rows = source.get("pages") if isinstance(source, dict) else None
    matches = [row for row in rows if isinstance(row, dict) and row.get("url") == url] \
        if isinstance(rows, list) else []
    if len(matches) != 1:
        return None
    row = matches[0]
    values = {key: _number(row.get(key)) for key in ("clicks", "impressions", "ctr", "position")}
    if (any(values[key] is None for key in ("clicks", "impressions", "ctr"))
            or values["clicks"] < 0 or values["impressions"] < 0
            or not 0 <= values["ctr"] <= 1
            or values["position"] is not None and values["position"] < 0):
        return None
    return values


def _measurement(analytics, lineage, now):
    if not isinstance(analytics, dict) or analytics.get("status") != "ok":
        return None, "analytics_missing"
    collected = _instant(analytics.get("collectedAt"))
    if collected is None or collected > now or now - collected > timedelta(hours=72):
        return None, "analytics_stale"
    if collected <= lineage["publicationAt"]:
        return None, "analytics_not_postpublication"
    if lineage["kind"] == "new_content":
        return None, "new_content_baseline_unavailable"
    evidence = analytics.get("evidence")
    current = evidence.get("current") if isinstance(evidence, dict) else None
    previous = evidence.get("previous") if isinstance(evidence, dict) else None
    current_period, previous_period = _period(current), _period(previous)
    if current_period is None or previous_period is None:
        return None, "complete_gsc_periods_pending"
    cs, ce, zone = current_period
    ps, pe, previous_zone = previous_period
    if (current.get("siteUrl") != "https://camp-gear-lab.com/"
            or current.get("country") not in ("jpn", "JPN") or current.get("searchType") != "web"
            or zone.key != previous_zone.key
            or any(current.get(key) != previous.get(key) for key in
                   ("siteUrl", "country", "searchType"))
            or pe >= cs or ce - cs != pe - ps):
        return None, "periods_not_comparable"
    publication_day = lineage["publicationAt"].astimezone(zone).date()
    if pe >= publication_day:
        return None, "before_period_not_prepublication"
    if cs <= publication_day:
        return None, "after_period_includes_prepublication"
    if (now.astimezone(zone).date() - ce).days > 35:
        return None, "analytics_stale"
    baseline = lineage["analysis"]["metricsReceipt"]["currentPeriod"]
    baseline_end = _day(baseline.get("endDate")) if isinstance(baseline, dict) else None
    if (baseline_end is None or baseline_end >= publication_day
            or baseline.get("dateBasis") != current.get("dateBasis")):
        return None, "analysis_baseline_not_prepublication"
    before, after = _page(previous, lineage["url"]), _page(current, lineage["url"])
    if before is None or after is None:
        return None, "page_measurement_missing"
    period_fields = ("startDate", "endDate", "dateBasis", "settledThrough")
    return ({"status": "measured_postchange_performance", "metricScope": "page",
             "before": {"period": {key: previous[key] for key in period_fields}, "metrics": before},
             "after": {"period": {key: current[key] for key in period_fields}, "metrics": after},
             "observedChange": {key: after[key] - before[key] if before[key] is not None
                                and after[key] is not None else None for key in before},
             "effect": "not_causally_attributed"}, None)


def assess(job, root, analytics, owner_id, now=None):
    """Return a bounded deterministic projection; never mutate inputs or state."""
    now = now or datetime.now(JST)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("seo_feedback_aware_time_required")
    now = now.astimezone(JST)
    job_id = job.get("id") if isinstance(job, dict) and isinstance(job.get("id"), str) else None
    revision = job.get("revision") if isinstance(job, dict) and isinstance(job.get("revision"), str) else None
    lineage, error = _lineage(job, owner_id)
    if error == "not_analysis_revision":
        return _result("not_applicable", error, job_id, revision)
    if error:
        status = "waiting" if error.startswith("waiting_") else "requires_reconciliation"
        return _result(status, error, job_id, revision)
    workflow, error, receipt_hashes = _workflow(job, root, lineage)
    if error:
        status = "waiting" if error.startswith("waiting_") else "requires_reconciliation"
        return _result(status, error, job_id, revision)
    measurement, error = _measurement(analytics, lineage, now)
    collected = _instant(analytics.get("collectedAt")) if isinstance(analytics, dict) else None
    if isinstance(analytics, dict) and analytics.get("status") == "ok" \
            and collected is not None and collected > lineage["publicationAt"] and collected <= now \
            and now - collected <= timedelta(hours=72):
        workflow["status"] = "reanalysis_observed"
    source_evidence = {
        **receipt_hashes,
    }
    if lineage["kind"] == "routine_revision":
        source_evidence.update(
            analysisMetricsSourceId=lineage["analysis"]["metricsReceipt"]["sourceId"],
            analysisOpportunitySha256=lineage["analysis"]["metricsReceipt"]["opportunityHash"],
            catalogSourceReceiptSha256=lineage["analysis"]["sourceProof"]["receiptHash"])
    else:
        source_evidence.update(themeEvidenceSha256=lineage["themeEvidenceSha256"],
                               sourceEvidenceAvailable=True)
    evidence = analytics.get("evidence") if isinstance(analytics, dict) else None
    for label in ("current", "previous"):
        value = evidence.get(label) if isinstance(evidence, dict) else None
        if isinstance(value, dict):
            try:
                source_evidence["analytics" + label.title() + "Sha256"] = _canonical_hash(value)
            except (TypeError, ValueError, OverflowError):
                pass
    if error:
        result = _result("waiting", error, job_id, revision,
                         workflow=workflow, sourceEvidence=source_evidence,
                         measurement={"status": "waiting", "reason": error,
                                      "effect": "not_causally_attributed"},
                         targetUrl=lineage["url"],
                         publicationAt=lineage["publicationAt"].isoformat())
        return result
    return _result("postchange_performance_measured", "complete_nonoverlapping_page_periods", job_id, revision,
                   workflow=workflow, measurement=measurement, sourceEvidence=source_evidence,
                   targetUrl=lineage["url"], publicationAt=lineage["publicationAt"].isoformat())


def build_feedback(jobs, root, analytics, now=None, *, owner_id):
    """Build at most ten safe rows for Runtime persistence and planning context."""
    now = now or datetime.now(JST)
    rows = []
    for job in (jobs if isinstance(jobs, list) else [])[:1000]:
        row = assess(job, root, analytics, owner_id, now)
        if row["status"] != "not_applicable":
            rows.append(row)
    priority = {"requires_reconciliation": 0, "waiting": 1,
                "postchange_performance_measured": 2}
    rows.sort(key=lambda row: (priority.get(row["status"], 3),
                               row.get("publicationAt", ""), row.get("jobId") or ""))
    rows = rows[:10]
    summary = {
        "reanalysisObserved": sum(row["workflow"]["status"] == "reanalysis_observed" for row in rows),
        "measurementWaiting": sum(row["measurement"]["status"] == "waiting" for row in rows),
        "postchangePerformanceMeasured": sum(
            row["measurement"]["status"] == "measured_postchange_performance" for row in rows),
        "requiresReconciliation": sum(row["status"] == "requires_reconciliation" for row in rows),
    }
    semantic = {"schemaVersion": 1, "summary": summary, "rows": rows}
    return {**semantic, "generatedAt": now.astimezone(JST).isoformat(),
            "semanticSha256": _canonical_hash(semantic)}


def render_markdown(projection):
    """Render a compact safe report; no body, query, nonce, or provider detail."""
    if not isinstance(projection, dict) or not isinstance(projection.get("rows"), list):
        raise ValueError("seo_feedback_projection_required")
    summary = projection.get("summary") or {}
    lines = ["# SEO feedback", "",
             "- Reanalysis observed: " + str(summary.get("reanalysisObserved", 0)),
             "- Measurement waiting: " + str(summary.get("measurementWaiting", 0)),
             "- Post-change performance measured: " + str(
                 summary.get("postchangePerformanceMeasured", 0)),
             "- Requires reconciliation: " + str(summary.get("requiresReconciliation", 0)), ""]
    for row in projection["rows"][:10]:
        lines.append("- " + str(row.get("jobId") or "unknown") + ": "
                     + str(row.get("reason") or row.get("status")))
    return "\n".join(lines) + "\n"
