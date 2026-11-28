"""Finite v3 literal correction for the exact reviewed guide v2 revision."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from ledger import canonical, fingerprint, valid_review
from model_budget import _config, _usage
from purchase_evidence import require_prewrite_purchase_evidence, validate_purchase_evidence
from quality import inspect_polish
from revisions import validate_context
from wise_contract import require_current_review


JST = timezone(timedelta(hours=9))
JOB = "revision-f9ff27c8f570270bdd012b12"
V2_REVISION = "3297abdbd24dbf0b017db91e3ea8ee7d109c73c2cc17a69c58b559558e084ff6"
OWNER_GRANT_SHA = "7971cd7bfcbb89a599920c58d56b40ae99c57d595e6e7984e462bf26a581325e"
OWNER_RECEIPT_SHA = "6caee83229eba9ae01f7ebebadff2d3b8fd0d4331a29fe9bae7974198454b602"
SCOPE = "guide_v3_exact_literal_deletion_v1"
ADAPTER_VERSION = "independent-review-public-proof-v2"
BUDGET_CAPS = {
    "article": {"calls": 32, "inputTokens": 2_000_000, "outputTokens": 262_144},
    "period": {"calls": 128, "inputTokens": 8_000_000, "outputTokens": 1_048_576},
}
DELETE_PHRASE = "800フィルパワーはダウンのかさ高を示す数値で、"
DELETE_SENTENCE = (
    "Amazonと楽天で選択方式が違い、同じ色・サイズが並ぶとは限らないので、"
    "購入画面での確認を習慣にしてください。"
)
POLISH_NEGATIVE_CONSTRAINT = (
    "今回削除したフィルパワーの独自定義と販売先全体の選択方式の一般化を、"
    "言い換えでも再追加しない。事実・数値・条件は確定仕様の範囲を保つ。"
)
DELETIONS = (
    {"text": DELETE_PHRASE, "reason": "unsupported_material_explanation"},
    {"text": DELETE_SENTENCE, "reason": "unsupported_merchant_behavior_advice"},
)
SHA = re.compile(r"[a-f0-9]{64}")


def require(value, reason):
    if not value:
        raise ValueError("revision_guide_v3_literal_correction_" + reason)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = canonical(value).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read_artifact(root, binding):
    require(isinstance(binding, dict) and set(binding) == {"relativePath", "sha256"}
            and isinstance(binding["relativePath"], str)
            and isinstance(binding["sha256"], str) and SHA.fullmatch(binding["sha256"]),
            "source_artifact_binding")
    root = Path(root).resolve()
    candidate = root / binding["relativePath"]
    path = candidate.resolve()
    require(not Path(binding["relativePath"]).is_absolute()
            and not candidate.is_symlink() and path.is_relative_to(root) and path.is_file()
            and path.stat().st_size <= 8_000_000, "source_artifact_missing")
    raw = path.read_bytes()
    require(_sha(raw) == binding["sha256"], "source_artifact_changed")
    return raw


PREFLIGHT_KEYS = {
    "schemaVersion", "kind", "jobId", "revision", "status", "checkedAt",
    "adapterVersion", "adapterSha256", "receiptModuleSha256",
    "projectionContractSha256", "v2SourceArtifactSha256", "freshSourceSha256",
    "renderPreviewSha256", "proofSha256",
}


def validate_preflight(root, job, marker, *, fresh_source_sha256,
                       v2_source_artifact_sha256, now=None):
    """Validate and return the exact render/program-proof preflight marker."""
    import article_verification_receipt as verification
    import independent_article_review as adapter
    now = now or datetime.now(JST)
    require(isinstance(now, datetime) and now.tzinfo is not None, "preflight_clock")
    require(isinstance(marker, dict) and set(marker) == PREFLIGHT_KEYS
            and marker["schemaVersion"] == 1
            and marker["kind"] == "guide_v3_render_program_preflight_v1"
            and marker["jobId"] == JOB and marker["revision"] == V2_REVISION
            and marker["status"] == "passed"
            and marker["adapterVersion"] == ADAPTER_VERSION
            and all(isinstance(marker[key], str) and SHA.fullmatch(marker[key])
                    for key in ("adapterSha256", "receiptModuleSha256",
                                "projectionContractSha256", "v2SourceArtifactSha256",
                                "freshSourceSha256", "renderPreviewSha256", "proofSha256")),
            "preflight_marker")
    try:
        checked = datetime.fromisoformat(marker["checkedAt"].replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError("revision_guide_v3_literal_correction_preflight_time") from None
    require(checked.tzinfo is not None
            and timedelta(0) <= now.astimezone(JST) - checked.astimezone(JST)
                <= timedelta(hours=6), "preflight_freshness")
    adapter_path = Path(adapter.__file__).resolve()
    receipt_path = Path(verification.__file__).resolve()
    contract = adapter.proof_contract()
    require(not adapter_path.is_symlink() and adapter_path.is_file()
            and not receipt_path.is_symlink() and receipt_path.is_file()
            and getattr(adapter, "PROJECTION_VERSION", None) == ADAPTER_VERSION
            and isinstance(contract, dict)
            and contract.get("projectionVersion") == ADAPTER_VERSION
            and contract.get("contractSha256") == marker["projectionContractSha256"]
            and isinstance(contract.get("implementations"), dict)
            and contract["implementations"].get("independent_article_review.py")
                == marker["adapterSha256"]
            and contract["implementations"].get("article_verification_receipt.py")
                == marker["receiptModuleSha256"]
            and _sha(adapter_path.read_bytes()) == marker["adapterSha256"]
            and _sha(receipt_path.read_bytes()) == marker["receiptModuleSha256"],
            "preflight_implementation")
    require(marker["v2SourceArtifactSha256"] == v2_source_artifact_sha256
            and marker["freshSourceSha256"] == fresh_source_sha256,
            "preflight_source")
    root = Path(root).resolve()
    preview_path = root / "seo-loop-recovery/20261128/guide-v3-render-preview.json"
    require(preview_path.is_file() and not preview_path.is_symlink()
            and preview_path.stat().st_size <= 8_000_000, "preflight_preview_missing")
    try:
        preview = json.loads(preview_path.read_bytes())
    except (UnicodeDecodeError, ValueError):
        raise ValueError("revision_guide_v3_literal_correction_preflight_preview") from None
    require(isinstance(preview, dict) and preview.get("passed") is True
            and preview.get("failures") == []
            and fingerprint(preview) == marker["renderPreviewSha256"],
            "preflight_preview")
    receipt_path = (root / "article-verification-receipts" / JOB /
                    (V2_REVISION + ".json"))
    receipt = verification.load(receipt_path, JOB, V2_REVISION, marker["proofSha256"])
    require(receipt["checks"]["render"].get("previewSha256")
            == marker["renderPreviewSha256"]
            and receipt["sourceDependenciesSha256"]
                == marker["v2SourceArtifactSha256"], "preflight_receipt_preview")
    source_path = (root / "article-verification-sources" / JOB /
                   (receipt["sourceDependenciesSha256"] + ".json"))
    verification.load_source(source_path, receipt["sourceDependenciesSha256"],
                             job["bundle"])
    projected_job = copy.deepcopy(job)
    projected_job["review"] = copy.deepcopy(job["review"])
    projected_job["review"]["programVerification"] = {
        "schemaVersion": 1, "kind": "article_verification_receipt_v1",
        "revision": V2_REVISION, "receiptSha256": marker["proofSha256"],
        "sourceDependenciesSha256": receipt["sourceDependenciesSha256"],
    }
    snapshot = adapter._public_snapshot(projected_job, root)
    program = snapshot.get("checks", {}).get("programVerification", {})
    require(program.get("receiptSha256") == marker["proofSha256"]
            and program.get("checks", {}).get("render", {}).get("previewSha256")
                == marker["renderPreviewSha256"]
            and program.get("contract", {}).get("contractSha256")
                == marker["projectionContractSha256"], "preflight_program_proof")
    return copy.deepcopy(marker)


def _evidence(value):
    fields = {"schemaVersion", "kind", "jobId", "revision", "specSha256",
              "liveBaseSha256", "finalReviewSha256", "qa", "sourceArtifact",
              "preflightMarker", "ownerCommandSha256"}
    qa_fields = {"stageKey", "recordSha256", "outputSha256", "usageSha256",
                 "budgetReservationId", "budgetReservationSha256", "issueCount"}
    require(isinstance(value, dict) and set(value) == fields
            and value["schemaVersion"] == 1
            and value["kind"] == "guide_v3_literal_correction_evidence_v1"
            and value["jobId"] == JOB and value["revision"] == V2_REVISION
            and all(isinstance(value[key], str) and SHA.fullmatch(value[key])
                    for key in ("specSha256", "liveBaseSha256", "finalReviewSha256",
                                "ownerCommandSha256"))
            and isinstance(value["qa"], dict) and set(value["qa"]) == qa_fields
            and value["qa"]["issueCount"] == 5
            and isinstance(value["qa"]["stageKey"], str)
            and value["qa"]["stageKey"].startswith("stage_journal:v1:")
            and isinstance(value["qa"]["budgetReservationId"], str)
            and all(isinstance(value["qa"][key], str) and SHA.fullmatch(value["qa"][key])
                    for key in ("recordSha256", "outputSha256", "usageSha256",
                                "budgetReservationSha256")), "evidence")
    require(isinstance(value["preflightMarker"], dict)
            and set(value["preflightMarker"]) == {"relativePath", "sha256"}
            and isinstance(value["preflightMarker"]["relativePath"], str)
            and isinstance(value["preflightMarker"]["sha256"], str)
            and SHA.fullmatch(value["preflightMarker"]["sha256"]), "preflight_binding")
    return copy.deepcopy(value)


def _correct(bundle):
    result = copy.deepcopy(bundle)
    article = result.get("article") or {}
    content = article.get("content")
    brief = result.get("brief") or {}
    protected = brief.get("protected")
    required = brief.get("requiredExpressions")
    require(isinstance(content, str) and content.count(DELETE_PHRASE) == 1
            and content.count(DELETE_SENTENCE) == 1, "literal_scope")
    require(brief.get("format") == "guide" and isinstance(protected, list)
            and isinstance(required, list)
            and all(isinstance(item, str) and item for item in protected + required),
            "brief_contract")
    before_constraints = protected + required
    present_protected = [item for item in protected if item in content]
    require(all(item in content for item in required), "required_expression_missing")
    require(not any(deletion["text"] in item or item in deletion["text"]
                    for item in before_constraints for deletion in DELETIONS),
            "brief_deletion_conflict")
    article["content"] = content.replace(DELETE_PHRASE, "").replace(DELETE_SENTENCE, "")
    after = article["content"]
    require(len(after) >= 3000
            and all(item in after for item in present_protected + required)
            and DELETE_PHRASE not in after and DELETE_SENTENCE not in after,
            "corrected_content")
    return result


def _constraint_baseline(bundle):
    article, brief = bundle.get("article") or {}, bundle.get("brief") or {}
    content = article.get("content")
    protected = list(brief.get("protected") or [])
    required = list(brief.get("requiredExpressions") or [])
    constraints = protected + required
    require(isinstance(content, str)
            and all(isinstance(item, str) and item for item in constraints),
            "constraint_baseline")
    require(all(item in content for item in required), "required_expression_missing")
    def receipt(values):
        present = [item for item in values if item in content]
        absent = [item for item in values if item not in content]
        return {"totalCount": len(values), "presentCount": len(present),
                "preexistingAbsentCount": len(absent),
                "presentSha256": [hashlib.sha256(item.encode()).hexdigest()
                                   for item in present],
                "preexistingAbsentSha256": [hashlib.sha256(item.encode()).hexdigest()
                                             for item in absent]}
    return {"method": "precorrection_literal_presence_v1",
            "protected": receipt(protected),
            "requiredExpressions": receipt(required)}


def _budget_row(db, reservation_id):
    cursor = db.execute("SELECT * FROM model_budget_reservations WHERE reservation_id=?",
                        (reservation_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip((item[0] for item in cursor.description), row))


def _state(runtime, raw_evidence, owner_grant):
    runtime._require_running()
    evidence = _evidence(raw_evidence)
    grant = runtime.ledger.validate_existing_improvement_owner_grant(owner_grant)
    require(grant == owner_grant and fingerprint(grant) == OWNER_GRANT_SHA
            and grant.get("instructionReceiptSha256") == OWNER_RECEIPT_SHA, "owner_grant")
    limits = _config(runtime.config.get("modelBudget"))
    require(all(limits[scope][field] == expected
                for scope, values in BUDGET_CAPS.items()
                for field, expected in values.items()), "budget_caps")
    command = (runtime.config.get("editorialManager") or {}).get("command")
    require(isinstance(command, list) and command
            and all(isinstance(part, str) and part for part in command)
            and fingerprint(command) == evidence["ownerCommandSha256"],
            "owner_command")
    folder = runtime.root / "revision-guide-v3-literal-corrections" / JOB
    require(not (folder / "claim.json").exists() and not (folder / "result.json").exists(),
            "already_claimed")
    job = runtime.ledger.get_job(JOB)
    require(job.get("kind") == "article_revision" and job.get("stage") == "review"
            and job.get("revision") == V2_REVISION
            and fingerprint(job.get("bundle")) == V2_REVISION
            and not job.get("astraReview") and not job.get("approval")
            and not job.get("publication") and not job.get("social"), "job_state")
    valid_review(job.get("review"), V2_REVISION, job.get("bundle"))
    require_current_review(job.get("bundle"), job.get("review"), runtime.config.get("repo"))
    require(fingerprint(job.get("review")) == evidence["finalReviewSha256"], "final_review")
    binding = validate_context(job.get("revisionContext"))
    require(fingerprint(binding) == evidence["specSha256"]
            and binding["baseHash"] == evidence["liveBaseSha256"], "specification")
    source_raw = _read_artifact(runtime.root, evidence["sourceArtifact"])
    preflight_raw = _read_artifact(runtime.root, evidence["preflightMarker"])
    try:
        preflight = json.loads(preflight_raw)
    except (UnicodeDecodeError, ValueError):
        raise ValueError("revision_guide_v3_literal_correction_preflight_marker") from None
    qa = evidence["qa"]
    with sqlite3.connect(runtime.ledger.db_path) as db:
        row = db.execute("SELECT value FROM meta WHERE key=?", (qa["stageKey"],)).fetchone()
        require(row is not None, "qa_missing")
        record = json.loads(row[0])
        output = record.get("output") if isinstance(record, dict) else None
        usage = output.get("usage") if isinstance(output, dict) else None
        reservation = _budget_row(db, qa["budgetReservationId"])
        require(fingerprint(record) == qa["recordSha256"]
                and record.get("jobId") == JOB and record.get("stage") == "independent_review"
                and record.get("status") == "succeeded" and record.get("attempts") == 1
                and record.get("maxAttempts") == 1 and record.get("outputHash") == qa["outputSha256"]
                and fingerprint(output) == qa["outputSha256"]
                and record.get("responseReceiptCount") == 1
                and record.get("missingUsage") is False
                and output.get("kind") == "independent_article_review_v1"
                and output.get("fingerprint") == V2_REVISION
                and output.get("passed") is False
                and isinstance(output.get("issues"), list)
                and len(output["issues"]) == qa["issueCount"]
                and output.get("requestedModel") == "gpt-6-astra"
                and (output.get("actualModel") is None
                     or isinstance(output.get("actualModel"), str)
                     and bool(output["actualModel"]))
                and isinstance(usage, dict) and fingerprint(usage) == qa["usageSha256"],
                "qa_changed")
        review_records = [json.loads(item[0]) for item in db.execute(
            "SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
        same_revision = [item for item in review_records
                         if isinstance(item, dict)
                         and item.get("jobId") == JOB
                         and item.get("stage") == "independent_review"
                         and isinstance(item.get("output"), dict)
                         and item["output"].get("fingerprint") == V2_REVISION]
        require(len(same_revision) == 1
                and same_revision[0].get("stageKey") == qa["stageKey"],
                "duplicate_v2_qa")
        measured = _usage(usage)
        require(reservation is not None
                and fingerprint(reservation) == qa["budgetReservationSha256"]
                and reservation.get("article_id") == runtime._budget_article_id(JOB)
                and reservation.get("stage") == "independent_review"
                and reservation.get("status") == "settled"
                and reservation.get("outcome") == "success"
                and measured == (reservation.get("actual_input_tokens"),
                                 reservation.get("actual_output_tokens")),
                "qa_usage_changed")
        require(not db.execute("SELECT 1 FROM effects WHERE job_id=?", (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM requests WHERE job_id=?", (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM model_budget_reservations "
                                   "WHERE article_id IN (?,?) "
                                   "AND status IN ('reserved','in_flight','unknown')",
                                   (JOB, runtime._budget_article_id(JOB))).fetchone(), "unresolved")
    corrected = _correct(job["bundle"])
    return job, binding, grant, evidence, record, source_raw, preflight, corrected


def _fresh(runtime, job, binding, corrected):
    context = runtime._wise_context(runtime._context())
    base = binding["baseArticle"]
    live = next((item for item in context.get("revisionArticles", context.get("articles", []))
                 if item.get("id") == base["id"]), None)
    require(live is not None and fingerprint(live) == binding["baseHash"], "live_baseline")
    products = {item["id"]: item for item in context.get("products", [])}
    require(all(products.get(item["id"]) == item for item in binding["baseProducts"]),
            "live_product_baseline")
    gathered = runtime.catalog.gather_revision(job["theme"], context, binding)
    require(all(gathered.get("checks", {}).get(key) is True
                for key in ("facts", "images", "affiliate"))
            and not gathered.get("blocked"), "fresh_source")
    now = datetime.now(JST)
    require_prewrite_purchase_evidence(gathered, now)
    source = copy.deepcopy(corrected)
    source.pop("purchaseEvidence", None)
    if gathered.get("purchaseEvidence"):
        source = validate_purchase_evidence(source, gathered["purchaseEvidence"], now)
    dependencies = runtime._source_dependencies(gathered)
    return context, gathered, source, dependencies, fingerprint(dependencies)


def _manifest(grant, evidence, preflight, source, fresh_sha):
    manifest = {
        "schemaVersion": 1, "kind": SCOPE, "jobId": JOB,
        "v2Revision": V2_REVISION, "specSha256": evidence["specSha256"],
        "ownerGrant": grant, "evidenceSha256": fingerprint(evidence),
        "programPreflight": preflight,
        "literalDeletions": copy.deepcopy(list(DELETIONS)),
        "constraintBaseline": _constraint_baseline(source),
        "correctedSourceSha256": fingerprint(source), "freshSourceSha256": fresh_sha,
        "newPaidStagesAllowed": ["polish", "final_review", "independent_review"],
        "ownerApprovalGranted": False, "publicationAllowed": False,
    }
    return {**manifest, "manifestSha256": fingerprint(manifest)}


def prepare(runtime, evidence, owner_grant):
    job, binding, grant, evidence, _, _, preflight, corrected = _state(
        runtime, evidence, owner_grant)
    _, _, source, _, fresh_sha = _fresh(runtime, job, binding, corrected)
    preflight = validate_preflight(
        runtime.root, job, preflight, fresh_source_sha256=fresh_sha,
        v2_source_artifact_sha256=evidence["sourceArtifact"]["sha256"])
    return _manifest(grant, evidence, preflight, source, fresh_sha)


def execute(runtime, manifest, evidence, owner_grant):
    """Run one new polish/final/Astra chain. Caller holds runtime.flock."""
    state = _state(runtime, evidence, owner_grant)
    job, binding, grant, evidence, qa_record, source_raw, preflight, corrected = state
    context, gathered, source, dependencies, fresh_sha = _fresh(
        runtime, job, binding, corrected)
    preflight = validate_preflight(
        runtime.root, job, preflight, fresh_source_sha256=fresh_sha,
        v2_source_artifact_sha256=evidence["sourceArtifact"]["sha256"])
    require(manifest == _manifest(grant, evidence, preflight, source, fresh_sha),
            "manifest_changed")
    folder = runtime.root / "revision-guide-v3-literal-corrections" / JOB
    _write_once(folder / "claim.json", {"status": "claimed", "manifest": manifest})
    try:
        _write_once(folder / "v2-archive.json", {
            "bundle": copy.deepcopy(job["bundle"]), "review": copy.deepcopy(job["review"]),
            "independentReviewRecord": qa_record,
            "sourceArtifactSha256": evidence["sourceArtifact"]["sha256"],
        })
        archive = folder / "source-artifact.bin"
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(source_raw); stream.flush(); os.fsync(stream.fileno())
        polish_brief = copy.deepcopy(source["brief"])
        style = polish_brief.get("style", "")
        require(isinstance(style, str)
                and POLISH_NEGATIVE_CONSTRAINT not in style, "polish_brief_style")
        polish_brief["style"] = ((style + "\n") if style else "") + POLISH_NEGATIVE_CONSTRAINT
        polish_inputs = {
            "content": source["article"]["content"], "brief": copy.deepcopy(polish_brief),
            "dependencies": {"sourceBundle": runtime._source_dependencies(source),
                             "verifiedSource": dependencies,
                             "routes": runtime._model_routes(),
                             "literalCorrectionManifest": manifest["manifestSha256"]},
            "schemaVersion": {"stage": 1, "input": "exact-v3-literal-source+brief",
                              "output": "polish+preservation"},
        }
        def operation():
            candidate = runtime.models.polish(source["article"]["content"], polish_brief)
            preservation = inspect_polish(source["article"]["content"], candidate["content"])
            require(preservation.get("passed") is True, "polish_preservation")
            return {"polished": candidate, "preservation": preservation}
        polished_stage = runtime._run_model_stage(
            job, "polish", polish_inputs, operation,
            runtime._model_routes()["polish"]["requested"])
        polished, preservation = polished_stage["polished"], polished_stage["preservation"]
        content = polished.get("content")
        original_content = job["bundle"]["article"]["content"]
        constraints = ([item for item in source["brief"]["protected"]
                        if item in original_content]
                       + source["brief"]["requiredExpressions"])
        require(isinstance(content, str) and len(content) >= 3000
                and DELETE_PHRASE not in content and DELETE_SENTENCE not in content
                and all(item in content for item in constraints), "polish_reintroduced_deletion")
        bundle = copy.deepcopy(source)
        bundle["article"]["content"] = content
        result = runtime._finish_article_review(job, context, gathered, bundle, source,
                                                preservation, polished, dependencies)
        current = runtime.ledger.get_job(JOB)
        require(current.get("approval") is None and current.get("publication") is None
                and current.get("social") is None, "authority_changed")
    except Exception as error:
        _write_once(folder / "result.json", {
            "status": "requires_reconciliation", "jobId": JOB,
            "manifestSha256": manifest["manifestSha256"],
            "failureType": type(error).__name__, "ownerApprovalGranted": False,
            "publicationPerformed": False,
        })
        raise
    finally:
        runtime._save_usage()
    completed = {
        "status": "completed", "jobId": JOB,
        "manifestSha256": manifest["manifestSha256"],
        "revision": current.get("revision"), "resultSha256": fingerprint(result),
        "ownerApprovalGranted": False, "publicationPerformed": False,
    }
    _write_once(folder / "result.json", completed)
    return completed
