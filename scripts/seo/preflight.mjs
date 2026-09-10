#!/usr/bin/env node
// Read-only guard for SEO operations. It deliberately never loads credentials or invokes models.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { getDueCheckpoints } from "./state.mjs";

const DEFAULT_ROOT = path.join(os.homedir(), ".secretary", "state", "campgearlab-seo");
const DEFAULT_POLICY = { maxActiveExperiments: 3, maxNewPerRun: 1, budget: { targetCreditsPerOperationRun: 50, maxWeeklyOperationCredits: 200, maxMetricsAgeHours: 72 } };
const ACTIVE = new Set(["proposed", "approved", "publishing", "verification_pending", "published", "observing", "paused"]);
const JST = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });

function date(value) { const time = Date.parse(value || ""); return Number.isFinite(time) ? time : null; }
function jst(value) { return `${JST.format(new Date(value)).replaceAll("/", "-")} JST`; }
function nested(base, extra) { return { ...base, ...(extra || {}), budget: { ...base.budget, ...(extra?.budget || {}) } }; }
function sourceOk(metrics) {
  const current = metrics?.current;
  return current?.status === "ok" && current.dateBasis === "America/Los_Angeles" && typeof current.settledThrough === "string";
}

/** @param {{state?: any, usage?: any, metrics?: any, policy?: any, now?: string}} [input] */
export function evaluatePreflight({ state = {}, usage, metrics, policy, now = new Date().toISOString() } = {}) {
  const resolvedPolicy = nested(DEFAULT_POLICY, policy);
  const nowAt = date(now);
  if (nowAt == null) throw new Error("now must be an ISO instant");
  const experiments = Array.isArray(state.experiments) ? state.experiments : [];
  const activeCount = experiments.filter((item) => ACTIVE.has(item.status)).length;
  const due = experiments.flatMap((item) => getDueCheckpoints(item, now).map((checkpoint) => ({ experimentId: item.id, url: item.urls?.canonical, ...checkpoint })));
  const awaitingPublication = experiments.filter((item) => ["approved", "publishing", "verification_pending"].includes(item.status));
  const windowStart = nowAt - 7 * 86400000;
  const operationRuns = Array.isArray(usage?.runs) ? usage.runs.filter((run) => run.kind === "operations" && date(run.finishedAt || run.startedAt) != null && date(run.finishedAt || run.startedAt) >= windowStart && date(run.finishedAt || run.startedAt) <= nowAt) : [];
  const unknownOperationCost = operationRuns.some((run) => typeof run.codexCreditsEstimate !== "number" || !Number.isFinite(run.codexCreditsEstimate));
  const operationCredits = unknownOperationCost ? null : operationRuns.reduce((sum, run) => sum + run.codexCreditsEstimate, 0);
  const reasons = [];
  if (!Array.isArray(usage?.runs)) reasons.push("usage_ledger_missing");
  if (!metrics) reasons.push("gsc_metrics_missing");
  else if (!sourceOk(metrics)) reasons.push("gsc_metrics_unavailable");
  else if (date(metrics.collectedAt)==null || date(metrics.collectedAt)>nowAt || nowAt - date(metrics.collectedAt) > resolvedPolicy.budget.maxMetricsAgeHours * 3600000) reasons.push("gsc_metrics_stale");
  if (unknownOperationCost) reasons.push("operation_cost_unknown");
  if (operationCredits != null && operationCredits >= resolvedPolicy.budget.maxWeeklyOperationCredits) reasons.push("weekly_operation_budget_reached");
  if (activeCount >= resolvedPolicy.maxActiveExperiments) reasons.push("max_active_experiments");
  return {
    schemaVersion: 1,
    generatedAt: now,
    generatedAtJst: jst(now),
    newWorkAllowed: reasons.length === 0,
    reasons,
    actionsAllowedDuringFreeze: ["observe", "report", "recover_publication"],
    due,
    late: due.filter((item) => item.late),
    awaitingPublication: awaitingPublication.map((item) => ({ id: item.id, url: item.urls?.canonical, status: item.status })),
    activeExperimentCount: activeCount,
    limits: { maxActiveExperiments: resolvedPolicy.maxActiveExperiments, maxNewPerRun: resolvedPolicy.maxNewPerRun },
    budget: {
      targetCreditsPerOperationRun: resolvedPolicy.budget.targetCreditsPerOperationRun,
      maxWeeklyOperationCredits: resolvedPolicy.budget.maxWeeklyOperationCredits,
      operationCreditsLast7Days: operationCredits,
      operationRunCountLast7Days: operationRuns.length,
      paidUsd: "unknown",
      apiComparisonUsd: "unknown",
    },
    metrics: metrics ? { collectedAt: metrics.collectedAt ?? null, settledThrough: metrics.current?.settledThrough ?? null, dateBasis: metrics.current?.dateBasis ?? null } : null,
  };
}

async function readJson(file) {
  try { return JSON.parse(await fs.readFile(file, "utf8")); }
  catch (error) { if (error.code === "ENOENT") return undefined; throw error; }
}
function args(argv) {
  const out = { root: process.env.SEO_STATE_ROOT || DEFAULT_ROOT, now: undefined, policy: undefined };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--root") out.root = argv[++index];
    else if (argv[index] === "--now") out.now = argv[++index];
    else if (argv[index] === "--policy") out.policy = argv[++index];
    else if (argv[index] === "--help") out.help = true;
    else throw new Error(`unknown argument: ${argv[index]}`);
  }
  return out;
}
export async function main(argv = process.argv.slice(2)) {
  const options = args(argv);
  if (options.help) return { help: "node scripts/seo/preflight.mjs [--root $SEO_STATE_ROOT] [--policy docs/seo-department/policy.json]" };
  const root = path.resolve(options.root);
  const policyFile = options.policy ? path.resolve(options.policy) : path.resolve("docs/seo-department/policy.json");
  return evaluatePreflight({
    state: await readJson(path.join(root, "state.json")),
    usage: await readJson(path.join(root, "usage.json")),
    metrics: await readJson(path.join(root, "metrics", "latest.json")),
    policy: await readJson(policyFile), now: options.now || new Date().toISOString(),
  });
}
if (import.meta.url === `file://${process.argv[1]}`) main().then((result) => console.log(JSON.stringify(result, null, 2))).catch((error) => { console.error(`SEO preflight failed: ${error.message}`); process.exitCode = 1; });
