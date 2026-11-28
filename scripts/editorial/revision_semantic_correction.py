"""One exact semantic correction after a failed independent review."""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3

from ledger import canonical, fingerprint
from model_budget import _config
from quality import inspect_polish
from purchase_evidence import require_prewrite_purchase_evidence, validate_purchase_evidence
from revisions import validate_context

JST = timezone(timedelta(hours=9))


JOB = "revision-f9ff27c8f570270bdd012b12"
SPEC_SHA = "8f1bd53b514c073b7eed1ba759b67aee1dd697e2066712fd5d46ad9e53f08ad0"
V1_REVISION = "c22e26965485682334d7ce26f80108d41dafb8f81a96829496728a94e95d6cd5"
V1_REVIEW_SHA = "d10a56acb9295b08b1a14b09c4dec456993fba5dfc03b0f0364b41b2e8f7f2fe"
QA_KEY = "stage_journal:v1:719a2361a1db0c4064da41ba60fbc4a2f9b85dc398738e0273240ba18ecb828c"
QA_OUTPUT_SHA = "4a933ff94b02c8d6f6b225ff62e87d57ea7b4d5e444f9c9a585c208b31522ede"
OWNER_GRANT_SHA = "7971cd7bfcbb89a599920c58d56b40ae99c57d595e6e7984e462bf26a581325e"
OWNER_RECEIPT_SHA = "6caee83229eba9ae01f7ebebadff2d3b8fd0d4331a29fe9bae7974198454b602"
FAQ_OLD = "AmazonとLで選べる内容は同じですか？"
FAQ_NEW = "Amazonと楽天市場で選べる内容は同じですか？"
BODY_OLD = "あごに当たらないジッパー仕様やインナードローコードは、着たときの快適さや裾からの冷気対策に関わる部分です。"
BODY_NEW = "インナードローコードアジャスターは公式の特長欄に記載されていますが、具体的な作用は今回の根拠では未確認です。"
ISSUES = [
    {"code": "quality_regression",
     "detail": "「AmazonとLで選べる内容は同じですか？」の「L」はサイズ表記であり、回答およびbriefが扱うAmazonと楽天市場の比較と一致しません。",
     "location": "publicBundle.article.faqs[2].question"},
    {"code": "unsupported_claim",
     "detail": "インナードローコードを「裾からの冷気対策」に結び付けていますが、提示されたメーカー抜粋は機構名を列挙するのみで、設置位置や冷気対策の機能を裏付けていません。気温下の快適性を保証しないという但し書きは、この説明の根拠にはなりません。",
     "location": "publicBundle.article.content「フードとポケットの仕様はどう選びに効く？」第3段落"},
]
QA_FIELDS = {"actualInvoiceUsd", "actualModel", "fingerprint", "issues", "kind",
             "outputCapEnforced", "passed", "requestedModel", "reservedOutputTokens", "usage"}


def require(value, reason):
    if not value:
        raise ValueError("revision_semantic_correction_" + reason)


def _write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value).encode())
        stream.flush(); os.fsync(stream.fileno())


def _correct(bundle):
    candidate = copy.deepcopy(bundle)
    article = candidate.get("article") or {}
    faqs, content = article.get("faqs"), article.get("content")
    require(isinstance(faqs, list) and len(faqs) > 2
            and sum(item.get("question") == FAQ_OLD for item in faqs if isinstance(item, dict)) == 1
            and faqs[2].get("question") == FAQ_OLD, "faq_scope")
    require(isinstance(content, str) and content.count(BODY_OLD) == 1
            and FAQ_NEW not in content and BODY_NEW not in content, "body_scope")
    brief = candidate.get("brief") or {}
    protected = list(brief.get("protected") or []) + list(brief.get("requiredExpressions") or [])
    require(not any(FAQ_OLD in str(item) or BODY_OLD in str(item) for item in protected),
            "brief_scope")
    faqs[2]["question"] = FAQ_NEW
    article["content"] = content.replace(BODY_OLD, BODY_NEW)
    return candidate


def _state(runtime, owner_grant):
    runtime._require_running()
    grant = runtime.ledger.validate_existing_improvement_owner_grant(owner_grant)
    require(grant == owner_grant and fingerprint(grant) == OWNER_GRANT_SHA
            and grant.get("instructionReceiptSha256") == OWNER_RECEIPT_SHA, "owner_grant")
    folder = runtime.root / "revision-semantic-corrections" / JOB
    require(not (folder / "claim.json").exists() and not (folder / "result.json").exists(),
            "already_claimed")
    job = runtime.ledger.get_job(JOB)
    require(job.get("kind") == "article_revision" and job.get("stage") == "review"
            and job.get("revision") == V1_REVISION and fingerprint(job.get("bundle")) == V1_REVISION
            and fingerprint(job.get("review")) == V1_REVIEW_SHA and not job.get("astraReview")
            and not job.get("approval") and not job.get("publication"), "job_state")
    binding = validate_context(job.get("revisionContext"))
    require(fingerprint(binding) == SPEC_SHA, "specification")
    limits = _config(runtime.config.get("modelBudget"))
    require(limits["article"]["calls"] == 32 and limits["period"]["calls"] == 128,
            "budget_caps")
    with sqlite3.connect(runtime.ledger.db_path) as db:
        row = db.execute("SELECT value FROM meta WHERE key=?", (QA_KEY,)).fetchone()
        require(row is not None, "qa_missing")
        record = json.loads(row[0]); output = record.get("output")
        require(record.get("jobId") == JOB and record.get("stage") == "independent_review"
                and record.get("status") == "succeeded" and record.get("attempts") == 1
                and record.get("maxAttempts") == 1 and record.get("outputHash") == QA_OUTPUT_SHA
                and fingerprint(output) == QA_OUTPUT_SHA and record.get("responseReceiptCount") == 1
                and record.get("missingUsage") is False and set(output or {}) == QA_FIELDS
                and output.get("fingerprint") == V1_REVISION and output.get("passed") is False
                and output.get("issues") == ISSUES and isinstance(output.get("usage"), dict), "qa_changed")
        require(not db.execute("SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')",
                               (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM requests WHERE job_id=?", (JOB,)).fetchone()
                and not db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id IN (?,?) "
                                   "AND status IN ('reserved','in_flight','unknown')",
                                   (JOB, runtime._budget_article_id(JOB))).fetchone(), "unresolved")
    corrected = _correct(job["bundle"])
    return job, grant, output, corrected


def _preflight(runtime, job, corrected):
    context = runtime._wise_context(runtime._context())
    binding = validate_context(job["revisionContext"])
    base = binding["baseArticle"]
    live = next((item for item in context.get("revisionArticles", context.get("articles", []))
                 if item.get("id") == base["id"]), None)
    require(live is not None and fingerprint(live) == binding["baseHash"], "live_baseline")
    live_products = {item["id"]: item for item in context.get("products", [])}
    require(all(live_products.get(item["id"]) == item for item in binding["baseProducts"]),
            "live_product_baseline")
    gathered = runtime.catalog.gather_revision(job["theme"], context, binding)
    require(all(gathered.get("checks", {}).get(key) is True for key in
                ("facts", "images", "affiliate")) and not gathered.get("blocked"), "fresh_source")
    now = datetime.now(JST)
    require_prewrite_purchase_evidence(gathered, now)
    corrected = copy.deepcopy(corrected)
    corrected.pop("purchaseEvidence", None)
    if gathered.get("purchaseEvidence"):
        corrected = validate_purchase_evidence(corrected, gathered["purchaseEvidence"], now)
    sanitized = runtime._source_dependencies(gathered)
    receipt = {"kind": "fresh_revision_source_v1", "gathered": sanitized,
               "fingerprint": fingerprint(sanitized)}
    return context, gathered, corrected, sanitized, receipt


def _manifest(grant, corrected, receipt):
    manifest = {"schemaVersion": 1, "kind": "revision_semantic_correction_v1",
                "jobId": JOB, "specSha256": SPEC_SHA, "v1Revision": V1_REVISION,
                "v1ReviewSha256": V1_REVIEW_SHA, "qaStageKey": QA_KEY,
                "qaOutputSha256": QA_OUTPUT_SHA, "ownerGrant": grant,
                "correction": {"faqOld": FAQ_OLD, "faqNew": FAQ_NEW,
                               "bodyOld": BODY_OLD, "bodyNew": BODY_NEW},
                "correctedSourceSha256": fingerprint(corrected),
                "freshSourceSha256": receipt["fingerprint"],
                "newPaidStagesAllowed": ["polish", "final_review", "independent_review"],
                "ownerApprovalGranted": False, "publicationAllowed": False}
    return {**manifest, "manifestSha256": fingerprint(manifest)}


def prepare(runtime, owner_grant):
    job, grant, qa, corrected = _state(runtime, owner_grant)
    _, _, corrected, _, receipt = _preflight(runtime, job, corrected)
    return _manifest(grant, corrected, receipt)


def execute(runtime, manifest, owner_grant):
    """Single-use correction. Caller holds runtime.flock."""
    job, grant, qa, source = _state(runtime, owner_grant)
    context, gathered, source, source_dependencies, receipt = _preflight(runtime, job, source)
    require(manifest == _manifest(grant, source, receipt), "manifest_changed")
    folder = runtime.root / "revision-semantic-corrections" / JOB
    archive = {"bundle": copy.deepcopy(job["bundle"]), "review": copy.deepcopy(job["review"]),
               "independentReview": copy.deepcopy(qa), "freshSource": receipt}
    _write_once(folder / "claim.json", {"status": "claimed", "manifest": manifest,
                "freshSourceSha256": receipt["fingerprint"]})
    _write_once(folder / "v1-archive.json", archive)
    try:
        polish_brief = copy.deepcopy(source["brief"])
        require(isinstance(polish_brief.get("protected"), list), "polish_brief")
        polish_brief["protected"].append(BODY_NEW)
        polish_inputs = {"content": source["article"]["content"],
                         "brief": copy.deepcopy(polish_brief),
                         "dependencies": {"sourceBundle": runtime._source_dependencies(source),
                                          "verifiedSource": source_dependencies,
                                          "routes": runtime._model_routes()},
                         "schemaVersion": {"stage": 1, "input": "exact-source+brief",
                                           "output": "polish+preservation"}}
        def operation():
            candidate = runtime.models.polish(source["article"]["content"], polish_brief)
            preservation = inspect_polish(source["article"]["content"], candidate["content"])
            require(preservation.get("passed") is True, "polish_preservation")
            return {"polished": candidate, "preservation": preservation}
        polished_stage = runtime._run_model_stage(
            job, "polish", polish_inputs, operation,
            runtime._model_routes()["polish"]["requested"])
        polished, preservation = polished_stage["polished"], polished_stage["preservation"]
        require(FAQ_OLD not in polished["content"] and BODY_OLD not in polished["content"]
                and BODY_NEW in polished["content"], "polish_reintroduced_issue")
        bundle = copy.deepcopy(source); bundle["article"]["content"] = polished["content"]
        result = runtime._finish_article_review(job, context, gathered, bundle, source,
                                                preservation, polished, source_dependencies)
        current = runtime.ledger.get_job(JOB)
        require(current.get("approval") is None and current.get("publication") is None,
                "approval_or_publication_changed")
    except Exception as error:
        _write_once(folder / "result.json", {"status": "requires_reconciliation",
                    "jobId": JOB, "manifestSha256": manifest["manifestSha256"],
                    "failureType": type(error).__name__, "ownerApprovalGranted": False,
                    "publicationPerformed": False})
        raise
    finally:
        runtime._save_usage()
    completed = {"status": "completed", "jobId": JOB,
                 "manifestSha256": manifest["manifestSha256"],
                 "revision": current.get("revision"), "resultSha256": fingerprint(result),
                 "ownerApprovalGranted": False, "publicationPerformed": False}
    _write_once(folder / "result.json", completed)
    return completed
