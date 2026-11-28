"""Pure SEO feedback lineage tests; no providers, models, approvals, or writes outside temp fixtures."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from ledger import fingerprint
from seo_feedback import JST, assess, build_feedback, render_markdown


REVISION = "a" * 64
OWNER = "UOWNER"
URL = "https://camp-gear-lab.com/articles/stove"
NOW = datetime(2026, 11, 28, 21, tzinfo=JST)


def analytics():
    def period(start, end, clicks, impressions):
        return {"status": "ok", "siteUrl": "https://camp-gear-lab.com/", "country": "jpn",
                "searchType": "web", "dateBasis": "America/Los_Angeles",
                "startDate": start, "endDate": end, "settledThrough": end,
                "summary": {"clicks": clicks, "impressions": impressions,
                            "ctr": clicks / impressions, "position": 7.0},
                "pages": [{"url": URL, "clicks": clicks, "impressions": impressions,
                           "ctr": clicks / impressions, "position": 7.0}]}
    return {"schemaVersion": 1, "status": "ok", "collectedAt": NOW.isoformat(),
            "evidence": {"previous": period("2026-09-01", "2026-09-28", 2, 100),
                         "current": period("2026-10-02", "2026-10-29", 5, 125)}}


def job():
    baseline = {"startDate": "2026-09-01", "endDate": "2026-09-28",
                "dateBasis": "America/Los_Angeles"}
    analysis = {"kind": "routine_existing_improvement_v1", "period": "2026-09-28",
                "targetUrl": URL, "rank": 1,
                "metricsReceipt": {"sourceId": "analytics:" + "b" * 64,
                    "collectedAt": "2026-09-29T12:00:00+09:00", "currentPeriod": baseline,
                    "ga4Period": dict(baseline), "opportunityHash": "c" * 64,
                    "candidateSetHash": "d" * 64, "protectedWinnerUrlsHash": "e" * 64,
                    "gsc": {}, "ga4": {}, "intentEvidence": {}},
                "sourceProof": {"sourceId": "catalog-gather:" + "f" * 64,
                    "receiptHash": "f" * 64, "checkedAt": "2026-09-29T12:00:00+09:00",
                    "productIds": ["p1"], "checks": {"facts": True, "images": True, "affiliate": True}},
                "baseArticleHash": "1" * 64, "baseProductsHash": "2" * 64,
                "constraints": {}}
    approval = {"request_id": "request-one", "revision": REVISION, "user_id": OWNER,
                "action": "approved", "at": "2026-09-30T09:00:00+09:00"}
    publication = {"verified": True, "revision": REVISION, "url": URL,
                   "at": "2026-09-30T12:00:00+09:00", "remoteUpdatedAt": "2026-09-30T03:00:00Z",
                   "readback": {"verified": True, "fingerprint": REVISION}}
    return {"id": "revision-one", "kind": "article_revision", "revision": REVISION,
            "theme": {"slug": "stove", "productIds": ["p1"]}, "approval": approval,
            "publication": publication, "revisionContext": {"baseArticle": {"slug": "stove"},
                "targetProductIds": ["p1"], "analysisBinding": analysis}}


def receipts(root, value):
    audit_key = fingerprint({"id": value["id"], "revision": value["revision"],
                             "publication": value["publication"]})
    audit = {"schemaVersion": 1, "id": value["id"], "revision": value["revision"],
             "publication": value["publication"], "auditKey": audit_key, "status": "success",
             "attempts": [{"status": "success", "result": {"passed": True}}]}
    index_key = fingerprint([value["id"], value["revision"], value["publication"]["at"]])
    tracking = {"id": value["id"], "revision": value["revision"], "url": URL,
                "checks": [{"sitemap": "current", "index": "indexed",
                            "expectedLastmod": value["publication"]["remoteUpdatedAt"]}]}
    for folder, key, data in (("post-publication-audits", audit_key, audit),
                              ("index-tracking", index_key, tracking)):
        path = root / folder
        path.mkdir(exist_ok=True)
        (path / (key + ".json")).write_text(json.dumps(data))
    return audit_key, index_key


class SeoFeedbackTests(unittest.TestCase):
    def run_assessment(self, mutate_job=None, mutate_analytics=None, mutate_files=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value, metrics = job(), analytics()
            if mutate_job:
                mutate_job(value)
            audit_key, index_key = receipts(root, value)
            if mutate_analytics:
                mutate_analytics(metrics)
            if mutate_files:
                mutate_files(root, audit_key, index_key)
            before = copy.deepcopy((value, metrics))
            files = {path: path.read_bytes() for path in root.rglob("*.json")}
            result = assess(value, root, metrics, OWNER, NOW)
            self.assertEqual(before, (value, metrics))
            self.assertEqual(files, {path: path.read_bytes() for path in root.rglob("*.json")})
            return result

    def test_complete_lineage_separates_observed_workflow_from_measurement(self):
        result = self.run_assessment()
        self.assertEqual("postchange_performance_measured", result["status"])
        self.assertEqual("reanalysis_observed", result["workflow"]["status"])
        self.assertEqual("measured_postchange_performance", result["measurement"]["status"])
        self.assertEqual("not_causally_attributed", result["measurement"]["effect"])
        self.assertEqual(3.0, result["measurement"]["observedChange"]["clicks"])
        self.assertTrue(all(key.endswith("Sha256") or key.endswith("SourceId")
                            for key in result["sourceEvidence"]))
        encoded = json.dumps(result, ensure_ascii=False)
        for secret in ("queries", "nonce", "content", "improvement", "causal_proven"):
            self.assertNotIn(secret, encoded)

    def test_tampered_audit_or_index_requires_reconciliation(self):
        changes = (
            lambda root, audit, index: self.change(root / "post-publication-audits" / (audit + ".json"),
                                                    lambda value: value.update(revision="0" * 64)),
            lambda root, audit, index: self.change(root / "index-tracking" / (index + ".json"),
                                                    lambda value: value.update(revision="0" * 64)),
            lambda root, audit, index: (root / "post-publication-audits" /
                                        (audit + ".json")).write_text("{broken"),
        )
        for change in changes:
            with self.subTest(change=change):
                result = self.run_assessment(mutate_files=change)
                self.assertEqual("requires_reconciliation", result["status"])
                self.assertEqual("postpublication_evidence_invalid", result["reason"])

    @staticmethod
    def change(path, operation):
        value = json.loads(path.read_text())
        operation(value)
        path.write_text(json.dumps(value))

    def test_old_or_wrong_owner_approval_never_links_publication(self):
        for change in (lambda value: value["approval"].update(revision="0" * 64),
                       lambda value: value["approval"].update(user_id="OTHER"),
                       lambda value: value["approval"].update(at="2026-10-01T00:00:00+09:00")):
            with self.subTest(change=change):
                result = self.run_assessment(mutate_job=change)
                self.assertEqual("requires_reconciliation", result["status"])

    def test_normal_owner_publication_and_index_waits_are_not_reconciliation(self):
        changes = (
            (lambda value: value.update(approval=None), "waiting_owner_approval"),
            (lambda value: value.update(approval=None, revision=None), "waiting_owner_approval"),
            (lambda value: value.update(publication=None), "waiting_publication"),
        )
        for change, reason in changes:
            with self.subTest(reason=reason):
                value = job()
                change(value)
                result = assess(value, Path("/unused"), analytics(), OWNER, NOW)
                self.assertEqual("waiting", result["status"])
                self.assertEqual(reason, result["reason"])
        result = self.run_assessment(mutate_files=lambda root, audit, index:
            self.change(root / "index-tracking" / (index + ".json"),
                        lambda value: value["checks"][-1].update(index="not_indexed")))
        self.assertEqual("postchange_performance_measured", result["status"])
        self.assertEqual("waiting_indexing", result["workflow"]["indexTracking"])
        self.assertEqual("reanalysis_observed", result["workflow"]["status"])

    def test_stale_and_gsc_lag_wait_without_zero(self):
        changes = (lambda value: value.update(collectedAt=(NOW - timedelta(hours=73)).isoformat()),
                   lambda value: value["evidence"]["current"].update(settledThrough="2026-10-28"))
        for change in changes:
            result = self.run_assessment(mutate_analytics=change)
            self.assertEqual("waiting", result["status"])
            self.assertEqual("waiting", result["measurement"]["status"])
            self.assertNotIn('"clicks": 0', json.dumps(result))

    def test_missing_page_or_baseline_waits_and_never_invents_zero(self):
        changes = (lambda value: value["evidence"]["current"].update(pages=[]),
                   lambda value: value["evidence"]["previous"].pop("startDate"))
        for change in changes:
            result = self.run_assessment(mutate_analytics=change)
            self.assertEqual("waiting", result["status"])
            self.assertEqual("waiting", result["measurement"]["status"])
            self.assertNotIn("observedChange", result["measurement"])

    def test_period_containing_prepublication_or_overlap_waits(self):
        changes = (lambda value: value["evidence"]["current"].update(startDate="2026-09-30"),
                   lambda value: value["evidence"]["previous"].update(endDate="2026-10-03",
                                                                      settledThrough="2026-10-03"))
        for change in changes:
            result = self.run_assessment(mutate_analytics=change)
            self.assertEqual("waiting", result["status"])
            self.assertNotEqual("measured", result["measurement"]["status"])

    def test_adjacent_rolling_period_uses_older_bound_analysis_baseline(self):
        def bind_baseline(value):
            metrics = value["revisionContext"]["analysisBinding"]["metricsReceipt"]
            metrics["currentPeriod"] = {"startDate": "2026-08-05", "endDate": "2026-09-01",
                                        "dateBasis": "America/Los_Angeles"}
            metrics["gsc"] = {"clicks": 2, "impressions": 100, "ctr": .02,
                              "position": 9.0, "metricScope": "page"}
            metrics["observationScope"] = {"siteUrl": "https://camp-gear-lab.com/",
                                           "country": "jpn", "searchType": "web"}
        def adjacent_periods(value):
            value["evidence"]["previous"].update(
                startDate="2026-09-02", endDate="2026-09-29", settledThrough="2026-09-29")
            value["evidence"]["current"].update(
                startDate="2026-09-30", endDate="2026-10-27", settledThrough="2026-10-27")
        result = self.run_assessment(mutate_job=bind_baseline, mutate_analytics=adjacent_periods)
        self.assertEqual("postchange_performance_measured", result["status"])
        self.assertEqual("analysis_binding", result["measurement"]["before"]["source"])
        self.assertEqual(2.0, result["measurement"]["before"]["metrics"]["clicks"])
        self.assertEqual(3.0, result["measurement"]["observedChange"]["clicks"])
        self.assertEqual("2026-09-30", result["measurement"]["after"]["period"]["startDate"])

    def test_non_analysis_job_is_not_applicable(self):
        result = assess({"id": "article-one", "kind": "article"}, Path("/unused"),
                        analytics(), OWNER, NOW)
        self.assertEqual("not_applicable", result["status"])

    def test_new_content_measures_only_absolute_future_performance_without_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = job()
            value.pop("revisionContext")
            value.pop("kind")
            value["theme"]["sourceIds"] = ["demand:winter-shell"]
            value["theme"]["searchDemandEvidence"] = {"query": "private-person@example.invalid"}
            receipts(root, value)
            metrics = analytics()
            metrics["evidence"].pop("previous")
            result = assess(value, root, metrics, OWNER, NOW)
        self.assertEqual("postchange_performance_measured", result["status"])
        self.assertEqual("complete_postpublication_page_period", result["reason"])
        self.assertEqual("measured_new_content_performance", result["measurement"]["status"])
        self.assertIsNone(result["measurement"]["before"])
        self.assertIs(result["measurement"]["baselineUnavailable"], True)
        self.assertEqual(5.0, result["measurement"]["after"]["metrics"]["clicks"])
        self.assertNotIn("observedChange", result["measurement"])
        self.assertEqual("not_causally_attributed", result["measurement"]["effect"])
        self.assertEqual("reanalysis_observed", result["workflow"]["status"])
        self.assertTrue(result["sourceEvidence"]["sourceEvidenceAvailable"])
        self.assertRegex(result["sourceEvidence"]["themeEvidenceSha256"], r"^[a-f0-9]{64}$")
        self.assertNotIn("analysisMetricsSourceId", result["sourceEvidence"])
        self.assertNotIn("private-person", json.dumps(result))

    def test_nonproduct_reference_order_is_semantic_set_but_receipts_remain_required(self):
        def nonproduct(value):
            value.pop("revisionContext")
            value.pop("kind")
            value["theme"].update(productIds=[], sourceIds=["public:second", "public:first", "gsc:bound"],
                                  nonProductContract={
                                      "sourceReceiptSha256": "4" * 64,
                                      "references": [
                                          {"id": "public:first", "receiptSha256": "5" * 64},
                                          {"id": "public:second", "receiptSha256": "6" * 64}]})
        result = self.run_assessment(mutate_job=nonproduct)
        self.assertNotEqual("lineage_binding_invalid", result["reason"])
        for corrupt in (
                lambda refs: refs.append(copy.deepcopy(refs[0])),
                lambda refs: refs[0].update(receiptSha256="invalid"),
                lambda refs: refs[0].update(id="public:other")):
            def invalid(value, operation=corrupt):
                nonproduct(value)
                operation(value["theme"]["nonProductContract"]["references"])
            with self.subTest(corrupt=corrupt):
                failed = self.run_assessment(mutate_job=invalid)
                self.assertEqual("requires_reconciliation", failed["status"])
                self.assertEqual("lineage_binding_invalid", failed["reason"])

    def test_new_content_mixed_period_or_missing_page_stays_waiting(self):
        def new_content(value):
            value.pop("revisionContext")
            value.pop("kind")
            value["theme"]["sourceIds"] = ["demand:winter-shell"]
        for change, reason in (
                (lambda metrics: metrics["evidence"]["current"].update(startDate="2026-09-29"),
                 "after_period_includes_prepublication"),
                (lambda metrics: metrics["evidence"]["current"].update(pages=[]),
                 "page_measurement_missing")):
            with self.subTest(reason=reason):
                result = self.run_assessment(mutate_job=new_content, mutate_analytics=change)
                self.assertEqual("waiting", result["status"])
                self.assertEqual(reason, result["reason"])
                self.assertNotIn("observedChange", result["measurement"])

    def test_raw_snapshot_recovers_target_below_top_thirty_for_measurement_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = job()
            value.pop("revisionContext")
            value.pop("kind")
            value["theme"]["sourceIds"] = ["demand:winter-shell"]
            receipts(root, value)
            projected = analytics()
            projected["evidence"]["current"]["pages"] = [
                {"url": f"https://camp-gear-lab.com/articles/leader-{index}",
                 "clicks": 10, "impressions": 1000 - index, "ctr": .01, "position": 3.0}
                for index in range(30)]
            raw = {"schemaVersion": 1, "collectedAt": projected["collectedAt"],
                   "current": copy.deepcopy(projected["evidence"]["current"]),
                   "previous": copy.deepcopy(projected["evidence"]["previous"])}
            raw["current"]["pages"].append(
                {"url": URL, "clicks": 1, "impressions": 2, "ctr": .5, "position": 8.0})
            raw["current"]["queries"] = [{"query": "private-query"}]
            raw["current"]["queryPages"] = [{"url": URL, "query": "private-query"}]
            result = build_feedback([value], root, projected, NOW, owner_id=OWNER,
                                    metrics_snapshot=raw)
        row = result["rows"][0]
        self.assertEqual("measured_new_content_performance", row["measurement"]["status"])
        self.assertIsNone(row["measurement"]["before"])
        self.assertEqual(1.0, row["measurement"]["after"]["metrics"]["clicks"])
        self.assertEqual(1, result["summary"]["postchangePerformanceMeasured"])
        self.assertEqual(1, result["summary"]["newContentObserved"])
        self.assertIn("no pre-publication baseline; not evidence of improvement causation",
                      render_markdown(result))
        self.assertNotIn("private-query", json.dumps(result))

    def test_raw_snapshot_mismatch_or_mixed_period_never_false_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = job()
            value.pop("revisionContext")
            value.pop("kind")
            value["theme"]["sourceIds"] = ["demand:winter-shell"]
            receipts(root, value)
            projected = analytics()
            projected["evidence"]["current"]["pages"] = []
            base = {"schemaVersion": 1, "collectedAt": projected["collectedAt"],
                    "current": copy.deepcopy(analytics()["evidence"]["current"]),
                    "previous": copy.deepcopy(analytics()["evidence"]["previous"])}
            cases = []
            mismatched = copy.deepcopy(base)
            mismatched["collectedAt"] = (NOW - timedelta(hours=1)).isoformat()
            cases.append(mismatched)
            mixed = copy.deepcopy(base)
            mixed["current"]["startDate"] = "2026-09-29"
            cases.append(mixed)
            stale = copy.deepcopy(base)
            stale["current"].update(startDate="2026-10-02", endDate="2026-10-23",
                                    settledThrough="2026-10-23")
            cases.append(stale)
            for snapshot in cases:
                with self.subTest(snapshot=snapshot["current"]["startDate"]):
                    result = build_feedback([value], root, projected, NOW, owner_id=OWNER,
                                            metrics_snapshot=snapshot)
                    self.assertEqual("waiting", result["rows"][0]["status"])
                    self.assertNotIn("observedChange", result["rows"][0]["measurement"])
                    if snapshot is mixed:
                        self.assertEqual("page_measurement_missing", result["rows"][0]["reason"])

    def test_analytics_collected_before_publication_is_not_reanalysis(self):
        def recent_publication(value):
            value["approval"]["at"] = "2026-11-28T19:00:00+09:00"
            value["publication"]["at"] = "2026-11-28T20:00:00+09:00"
        result = self.run_assessment(mutate_job=recent_publication, mutate_analytics=lambda value:
            value.update(collectedAt="2026-11-28T19:30:00+09:00"))
        self.assertEqual("waiting", result["status"])
        self.assertEqual("analytics_not_postpublication", result["reason"])
        self.assertEqual("publication_observed", result["workflow"]["status"])

    def test_runtime_projection_is_bounded_semantic_and_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = job()
            receipts(root, value)
            jobs = [copy.deepcopy(value) for _ in range(12)]
            for index, item in enumerate(jobs):
                item["id"] = "revision-" + str(index)
                receipts(root, item)
            first = build_feedback(jobs, root, analytics(), NOW, owner_id=OWNER)
            later = build_feedback(jobs, root, analytics(), NOW + timedelta(minutes=1), owner_id=OWNER)
            self.assertEqual(10, len(first["rows"]))
            self.assertEqual(first["semanticSha256"], later["semanticSha256"])
            self.assertNotEqual(first["generatedAt"], later["generatedAt"])
            self.assertEqual(10, first["summary"]["postchangePerformanceMeasured"])
            self.assertEqual(0, first["summary"]["newContentObserved"])
            text = render_markdown(first)
            self.assertIn("Post-change performance measured: 10", text)
            self.assertNotIn("queries", text)


if __name__ == "__main__":
    unittest.main()
