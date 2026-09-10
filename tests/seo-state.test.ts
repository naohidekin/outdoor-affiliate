import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import {
  canonicalUrl,
  createStore,
  getDueCheckpoints,
} from "../scripts/seo/state.mjs";
import { runCli } from "../scripts/seo/cli.mjs";
import { renderReport } from "../scripts/seo/report.mjs";

async function withRoot(run: (root: string) => Promise<void>) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "seo-state-"));
  try { await run(root); } finally { await fs.rm(root, { recursive: true, force: true }); }
}

function proposal(url = "https://camp-gear-lab.com/guides/chair#intro") {
  return {
    urls: { canonical: url, linkSourcePages: ["https://camp-gear-lab.com/guides/tent#links"] },
    queryTargets: ["camp chair"],
    baseline: { source: "gsc", sourceTimezone: "America/Los_Angeles", capturedAt: "2026-09-01T00:00:00.000Z", metrics: { clicks: 2 } },
    hypothesis: "関連リンクで発見性が上がる", evidenceUrls: ["https://developers.google.com/search/docs"],
    expectedOutcome: "clicks increase", falsification: "28日後に改善がない", beforeContentHash: "sha256:abc",
  };
}
function approval(manifestHash = "manifest-1") { return { model: "gpt-6-astra", rationale: "approved", manifestHash }; }
async function verifiedJournal(root: string, experimentId: string, manifestHash = "manifest-1") {
  await fs.mkdir(path.join(root, "snapshots"), { recursive: true });
  await fs.writeFile(path.join(root, "snapshots", `${experimentId}.json`), JSON.stringify({ experimentId, status: "verified", manifestHash }));
}

test("canonicalUrl strips fragments only for same site URLs", () => {
  assert.equal(canonicalUrl("https://camp-gear-lab.com/a#one"), "https://camp-gear-lab.com/a");
  assert.throws(() => canonicalUrl("https://example.com/a"));
});

test("propose persists full durable experiment record and prevents same-page conflict", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root, now: () => "2026-09-01T00:00:00.000Z", policy: { maxNewPerRun: 3 } });
    const first = await store.propose(proposal());
    assert.equal(first.status, "proposed");
    assert.equal(first.urls.canonical, "https://camp-gear-lab.com/guides/chair");
    assert.equal(first.baseline.sourceTimezone, "America/Los_Angeles");
    assert.ok(first.id);
    await assert.rejects(() => store.propose(proposal("https://camp-gear-lab.com/guides/chair")), /active experiment/i);
    await assert.rejects(() => store.propose(proposal("https://camp-gear-lab.com/guides/tent")), /link source/i);
  });
});

test("approval and terminal decisions require gpt-6-astra with rationale", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root });
    const experiment = await store.propose(proposal());
    await assert.rejects(() => store.approve(experiment.id, { model: "other", rationale: "ok" }), /gpt-6-astra/);
    const approved = await store.approve(experiment.id, { model: "gpt-6-astra", rationale: "evidence reviewed" });
    assert.equal(approved.status, "approved");
    await assert.rejects(() => store.transition(experiment.id, "retained", { model: "gpt-6-astra" }), /rationale/);
  });
});

test("observation clock starts only after verified publication and duplicate events do not reset it", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root });
    const experiment = await store.propose(proposal());
    await store.approve(experiment.id, approval()); await verifiedJournal(root, experiment.id);
    await store.event(experiment.id, { eventId: "publish-1", type: "publication_verified", manifestHash: "manifest-1", occurredAt: "2026-09-03T12:00:00.000Z" });
    await store.event(experiment.id, { eventId: "publish-1", type: "publication_verified", manifestHash: "manifest-1", occurredAt: "2026-09-04T12:00:00.000Z" });
    const saved = await store.get(experiment.id);
    assert.equal(saved.publishedAt, "2026-09-03T12:00:00.000Z");
    assert.deepEqual(getDueCheckpoints(saved, "2026-09-09T11:59:59.000Z"), []);
    assert.deepEqual(getDueCheckpoints(saved, "2026-09-10T12:00:00.000Z").map((item) => item.day), [7]);
  });
});

test("verified publication requires the matching durable publisher journal", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root }); const experiment = await store.propose(proposal());
    await store.approve(experiment.id, approval("manifest-safe"));
    await assert.rejects(() => store.event(experiment.id, { eventId: "forged", type: "publication_verified", manifestHash: "manifest-safe", occurredAt: "2026-09-03T12:00:00.000Z" }), /journal is missing/);
    await verifiedJournal(root, experiment.id, "different");
    await assert.rejects(() => store.event(experiment.id, { eventId: "forged", type: "publication_verified", manifestHash: "manifest-safe", occurredAt: "2026-09-03T12:00:00.000Z" }), /hash mismatch/);
  });
});

test("validated observations preserve unknown values and are idempotent", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root });
    const experiment = await store.propose(proposal());
    await store.approve(experiment.id, approval()); await verifiedJournal(root, experiment.id);
    await store.event(experiment.id, { eventId: "publish-1", type: "publication_verified", manifestHash: "manifest-1", occurredAt: "2026-09-03T12:00:00.000Z" });
    const observation = { observationId: "gsc-7", observedAt: "2026-09-10T12:00:00.000Z", source: "gsc", sourceTimezone: "America/Los_Angeles", sourceValid: true, checkpointDay: 7, periodStart: "2026-09-04T12:00:00.000Z", periodEnd: "2026-09-10T12:00:00.000Z", settledThrough: "2026-09-10T12:00:00.000Z", metrics: { clicks: 0, impressions: undefined, ctr: null }, causalityClaim: false };
    await store.record(experiment.id, observation);
    await store.record(experiment.id, observation);
    const saved = await store.get(experiment.id);
    assert.equal(saved.observations.length, 1);
    assert.equal(saved.observations[0].metrics.clicks, 0);
    assert.equal(saved.observations[0].metrics.ctr, null);
    assert.ok(Object.hasOwn(saved.observations[0].metrics, "impressions"));
  });
});

test("controlled experiment fields cannot be supplied by a proposal", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root });
    await assert.rejects(() => store.propose({ ...proposal(), id: "chosen-by-user" }), /id must not/i);
    const experiment = await store.propose(proposal());
    assert.equal(experiment.status, "proposed");
    assert.notEqual(experiment.id, "chosen-by-user");
  });
});

test("invalid or incomplete observations do not close a due checkpoint", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root }); const experiment = await store.propose(proposal());
    await store.approve(experiment.id, approval()); await verifiedJournal(root, experiment.id);
    await store.event(experiment.id, { eventId: "publish", type: "publication_verified", manifestHash: "manifest-1", occurredAt: "2026-09-03T12:00:00.000Z" });
    await store.record(experiment.id, { observationId: "failed-source", observedAt: "2026-09-10T12:00:00.000Z", source: "gsc", sourceTimezone: "America/Los_Angeles", sourceValid: false, checkpointDay: 7, metrics: { clicks: null }, causalityClaim: false });
    const saved = await store.get(experiment.id);
    assert.deepEqual(getDueCheckpoints(saved, "2026-09-10T12:00:00.000Z").map((item) => item.day), [7]);
    await assert.rejects(() => store.record(experiment.id, { observationId: "incomplete", observedAt: "2026-09-10T12:00:00.000Z", source: "gsc", sourceTimezone: "America/Los_Angeles", sourceValid: true, checkpointDay: 7, metrics: { clicks: null }, causalityClaim: false }), /actual metric|periodStart/i);
    await assert.rejects(() => store.record(experiment.id, { observationId: "forged-period", observedAt: "2026-09-10T12:00:00.000Z", source: "gsc", sourceTimezone: "America/Los_Angeles", sourceValid: true, checkpointDay: 7, periodStart: "2026-09-20", periodEnd: "2026-09-19", settledThrough: "2026-08-01", metrics: { unrelated: 1 }, causalityClaim: false }), /ordered|actual GSC metric/);
    await assert.rejects(() => store.record(experiment.id, { observationId: "unrelated-metric", observedAt: "2026-09-10T12:00:00.000Z", source: "gsc", sourceTimezone: "America/Los_Angeles", sourceValid: true, checkpointDay: 7, periodStart: "2026-09-04", periodEnd: "2026-09-10", settledThrough: "2026-09-10", metrics: { unrelated: 1 }, causalityClaim: false }), /actual GSC metric/);
  });
});

test("terminal, paused and unpublished experiments cannot be made observing", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root, policy: { maxNewPerRun: 3 } });
    const unpublished = await store.propose(proposal());
    await store.approve(unpublished.id, { model: "gpt-6-astra", rationale: "approved" });
    await assert.rejects(() => store.record(unpublished.id, { observationId: "no", observedAt: "2026-09-10T12:00:00.000Z", source: "gsc", sourceTimezone: "America/Los_Angeles", sourceValid: false, checkpointDay: 7, metrics: {}, causalityClaim: false }), /before publication/i);
    await store.transition(unpublished.id, "inconclusive", { model: "gpt-6-astra", rationale: "abandoned before publishing" });
    assert.deepEqual(getDueCheckpoints(await store.get(unpublished.id), "2026-10-01T00:00:00.000Z"), []);
  });
});

test("retained and revised decisions require verified publication and settled evidence", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root }); const experiment = await store.propose(proposal());
    await store.approve(experiment.id, approval());
    await assert.rejects(() => store.transition(experiment.id, "retained", { model: "gpt-6-astra", rationale: "no publication" }), /verified publication/);
    await verifiedJournal(root, experiment.id);
    await store.event(experiment.id, { eventId: "published", type: "publication_verified", manifestHash: "manifest-1", occurredAt: "2026-09-03T12:00:00.000Z" });
    await assert.rejects(() => store.transition(experiment.id, "retained", { model: "gpt-6-astra", rationale: "no settled evidence" }), /settled observation/);
    await store.record(experiment.id, { observationId: "settled", observedAt: "2026-09-10T12:00:00.000Z", source: "gsc", sourceTimezone: "America/Los_Angeles", sourceValid: true, checkpointDay: 7, periodStart: "2026-09-04T12:00:00.000Z", periodEnd: "2026-09-10T12:00:00.000Z", settledThrough: "2026-09-10T12:00:00.000Z", metrics: { clicks: 4, impressions: 20, ctr: 0.2, position: 4.5 }, causalityClaim: false });
    assert.equal((await store.transition(experiment.id, "retained", { model: "gpt-6-astra", rationale: "reviewed settled cohort" })).status, "retained");
  });
});

test("dry run never creates files", async () => {
  await withRoot(async (root) => {
    const store = createStore({ root, dryRun: true });
    const proposed = await store.propose(proposal());
    assert.equal(proposed.status, "proposed");
    await assert.rejects(fs.access(path.join(root, "state.json")));
  });
});

test("exclusive lock is never stolen based on age", async () => {
  await withRoot(async (root) => {
    await fs.mkdir(root, { recursive: true });
    await fs.writeFile(path.join(root, ".state.lock"), JSON.stringify({ pid: 99999, createdAt: "2000-01-01T00:00:00.000Z" }));
    const store = createStore({ root });
    await assert.rejects(() => store.propose(proposal()), /active lock/i);
  });
});

test("concurrent writers leave one visible failure instead of corrupting state", async () => {
  await withRoot(async (root) => {
    const left = createStore({ root });
    const right = createStore({ root });
    const results = await Promise.allSettled([left.propose(proposal()), right.propose(proposal("https://camp-gear-lab.com/guides/stove"))]);
    assert.equal(results.filter((item) => item.status === "fulfilled").length, 1);
    assert.equal(results.filter((item) => item.status === "rejected").length, 1);
    assert.equal((await left.list()).length, 1);
  });
});

test("CLI decide records an explicit Astra inconclusive decision and run id persists", async () => {
  await withRoot(async (root) => {
    const proposalFile = path.join(root, "proposal.json");
    const decisionFile = path.join(root, "decision.json");
    await fs.writeFile(proposalFile, JSON.stringify(proposal()));
    await fs.writeFile(decisionFile, JSON.stringify({ status: "inconclusive", model: "gpt-6-astra", rationale: "publication was cancelled" }));
    const messages: string[] = [];
    assert.equal(await runCli(["--root", root, "--run-id", "weekly-1", "propose", "--file", proposalFile], { stdout: (value: string) => messages.push(value), stderr: () => {} }), 0);
    const id = JSON.parse(messages[0]).id;
    assert.equal(await runCli(["--root", root, "decide", id, "--file", decisionFile], { stdout: () => {}, stderr: () => {} }), 0);
    const store = createStore({ root });
    assert.equal((await store.get(id)).status, "inconclusive");
  });
});

test("report never calls raw click deltas a Top 1 and separates estimates from actual USD", () => {
  const report = renderReport({ generatedAt: "2026-09-11T00:00:00.000Z", experiments: [{ ...proposal(), id: "e1", status: "observing", observations: [{ sourceValid: true, periodStart: "2026-09-04", periodEnd: "2026-09-10", settledThrough: "2026-09-10", observedAt: "2026-09-11T00:00:00.000Z", metrics: { clicks: 5 }, comparison: { days: 7, queryCohort: { queries: ["camp chair"], pages: ["https://camp-gear-lab.com/guides/chair"], devices: ["MOBILE"] }, previousPeriod: { pageMetrics: { clicks: 3 } }, pageMetrics: { clicks: 5 } } }] }], usage: { runs: [{ kind: "operations", codexCreditsEstimate: 3, apiUsdEstimate: 0.2, actualUsd: null }] } });
  assert.doesNotMatch(report, /Top 1|Top 2|Top 3/);
  assert.match(report, /実 USD: 不明/);
  assert.match(report, /API 比較推定/);
  assert.match(report, /query 1件.*page 1件.*device 1件/);
});
