import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { evaluatePreflight, main } from "../scripts/seo/preflight.mjs";

const policy = { maxActiveExperiments: 3, maxNewPerRun: 1, budget: { targetCreditsPerOperationRun: 50, maxWeeklyOperationCredits: 200, maxMetricsAgeHours: 72 } };
const metrics = (collectedAt = "2026-09-10T00:00:00.000Z") => ({ collectedAt, current: { status: "ok", dateBasis: "America/Los_Angeles", settledThrough: "2026-09-09" } });

test("preflight allows new work only with fresh GSC and known operation costs", () => {
  const value = evaluatePreflight({ state: { experiments: [] }, usage: { runs: [{ kind: "implementation", finishedAt: "2026-09-10T00:00:00.000Z", codexCreditsEstimate: null }] }, metrics: metrics(), policy, now: "2026-09-11T00:00:00.000Z" });
  assert.equal(value.newWorkAllowed, true);
  assert.deepEqual(value.reasons, []);
  assert.equal(value.budget.operationCreditsLast7Days, 0);
  assert.equal(value.budget.paidUsd, "unknown");
});

test("unknown operation cost, stale GSC, and active cap block interventions but keep due work visible", () => {
  const active = Array.from({ length: 3 }, (_, index) => ({ id: String(index), status: "observing", urls: { canonical: `https://camp-gear-lab.com/articles/${index}` }, publishedAt: "2026-08-01T00:00:00.000Z", observations: [] }));
  const value = evaluatePreflight({ state: { experiments: active }, usage: { runs: [{ kind: "operations", finishedAt: "2026-09-10T00:00:00.000Z", codexCreditsEstimate: null }] }, metrics: metrics("2026-09-01T00:00:00.000Z"), policy, now: "2026-09-11T00:00:00.000Z" });
  assert.equal(value.newWorkAllowed, false);
  assert.ok(value.reasons.includes("operation_cost_unknown"));
  assert.ok(value.reasons.includes("gsc_metrics_stale"));
  assert.ok(value.reasons.includes("max_active_experiments"));
  assert.equal(value.due.length, 9);
});

test("only operation runs inside the trailing seven-day window count toward cap", () => {
  const value = evaluatePreflight({ state: { experiments: [] }, usage: { runs: [
    { kind: "operations", finishedAt: "2026-09-10T00:00:00.000Z", codexCreditsEstimate: 190 },
    { kind: "implementation", finishedAt: "2026-09-10T00:00:00.000Z", codexCreditsEstimate: 999 },
    { kind: "operations", finishedAt: "2026-09-01T23:59:59.000Z", codexCreditsEstimate: 99 },
  ] }, metrics: metrics(), policy, now: "2026-09-11T00:00:00.000Z" });
  assert.equal(value.budget.operationCreditsLast7Days, 190);
  assert.equal(value.newWorkAllowed, true);
  const capped = evaluatePreflight({ state: { experiments: [] }, usage: { runs: [{ kind: "operations", finishedAt: "2026-09-10T00:00:00.000Z", codexCreditsEstimate: 200 }] }, metrics: metrics(), policy, now: "2026-09-11T00:00:00.000Z" });
  assert.ok(capped.reasons.includes("weekly_operation_budget_reached"));
});

test("preflight main is read-only and returns JST-labelled output", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "seo-preflight-"));
  try {
    await fs.mkdir(path.join(root, "metrics"), { recursive: true });
    await fs.writeFile(path.join(root, "state.json"), JSON.stringify({ experiments: [] }));
    await fs.writeFile(path.join(root, "usage.json"), JSON.stringify({ runs: [] }));
    await fs.writeFile(path.join(root, "metrics", "latest.json"), JSON.stringify(metrics()));
    const before = await fs.readdir(root, { recursive: true });
    const result = await main(["--root", root, "--now", "2026-09-11T00:00:00.000Z"]);
    assert.ok("generatedAtJst" in result);
    assert.match(result.generatedAtJst, /JST$/);
    assert.deepEqual(await fs.readdir(root, { recursive: true }), before);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});
