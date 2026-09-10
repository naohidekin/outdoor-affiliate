import { seoRoot } from './article-guard.mjs';
import fs from "node:fs/promises";
import path from "node:path";

const RATE_DATE = "2026-09-11";
const SOURCES = [
  "https://learn.chatgpt.com/docs/pricing",
  "https://developers.openai.com/api/docs/models/gpt-6-astra",
];

const RATES = {
  "gpt-6-astra": { credits: [250, 25, 1250], api: [10, 1, 50] },
  "gpt-5.6-terra": { credits: [50, 5, 300], api: [2, 0.2, 12] },
  "gpt-5.6-luna": { credits: [5, 0.5, 30], api: [0.2, 0.02, 1.2] },
  "gpt-5.6-sol": { credits: [100, 10, 500], api: [4, 0.4, 20] },
};

const n = (v) => typeof v === "number" && Number.isFinite(v) ? v : null;
const first = (o, names) => { for (const k of names) if (o && Object.hasOwn(o, k)) return o[k]; return undefined; };
const num = (o, names) => n(first(o, names));
const iso = (v) => { const t = Date.parse(v ?? ""); return Number.isFinite(t) ? new Date(t).toISOString() : null; };

function contextModel(context) {
  if (!context || typeof context !== "object") return null;
  const value = first(context, ["model", "model_name", "modelName", "model_slug", "modelSlug"]);
  return typeof value === "string" && value ? value : null;
}

function lineTime(record) {
  return iso(first(record, ["timestamp", "created_at", "createdAt", "time", "date"])) ||
    iso(first(record?.payload, ["timestamp", "created_at", "createdAt", "time", "date"]));
}

function usageObject(record) {
  if (!record || typeof record !== "object") return null;
  if (record.token_count && typeof record.token_count === "object") return record.token_count;
  if (record.tokenCount && typeof record.tokenCount === "object") return record.tokenCount;
  if (record.type === "token_count" || record.type === "token-count") return record;
  if (record.payload && typeof record.payload === "object") {
    if (record.payload.token_count && typeof record.payload.token_count === "object") return record.payload.token_count;
    if (record.payload.tokenCount && typeof record.payload.tokenCount === "object") return record.payload.tokenCount;
    if (record.payload.type === "token_count" || record.payload.type === "token-count") return record.payload.info || record.payload;
  }
  return null;
}

function totals(value) {
  const usage = value?.total_token_usage && typeof value.total_token_usage === "object"
    ? value.total_token_usage : value;
  return {
    inputTokens: num(usage, ["input_tokens", "inputTokens", "input"]),
    cachedInputTokens: num(usage, ["cached_input_tokens", "cachedInputTokens", "cache_read_input_tokens", "cacheReadInputTokens", "cached_input"]),
    cacheWriteInputTokens: num(usage, ["cache_write_input_tokens", "cacheWriteInputTokens", "cache_write_input", "cache_write_tokens"]),
    outputTokens: num(usage, ["output_tokens", "outputTokens", "output"]),
    reasoningOutputTokens: num(usage, ["reasoning_output_tokens", "reasoningOutputTokens", "reasoning_tokens"]),
  };
}

function addKnown(a, b) { return a == null || b == null ? null : a + b; }
function delta(now, previous) {
  const out = {};
  for (const key of Object.keys(now)) {
    const x = now[key], p = previous?.[key];
    if (x == null) out[key] = null;
    else if (p == null) out[key] = x;
    else out[key] = x >= p ? x - p : undefined;
  }
  return out;
}

export function parseSessionUsage(text, options = {}) {
  const since = options.since ? Date.parse(options.since) : -Infinity;
  const until = options.until ? Date.parse(options.until) : Infinity;
  const totalsByModel = new Map();
  let previous = null, model = null;
  let selectedFirstAt = null, selectedLastAt = null;
  const requests = [];
  const anomalies = [];
  for (const [lineNo, line] of String(text ?? "").split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    let record;
    try { record = JSON.parse(line); } catch { continue; }
    const at = lineTime(record);
    const ctx = record.turn_context ?? record.turnContext ??
      (record.type === "turn_context" ? (record.payload || record) : null) ??
      (record.payload?.type === "turn_context" ? (record.payload.payload || record.payload) : null);
    const nextModel = contextModel(ctx);
    if (nextModel) model = nextModel;
    const usage = usageObject(record);
    if (!usage) continue;
    const current = totals(usage);
    // Rate-limit-only events have info:null and no counters. Preserve the last
    // cumulative baseline rather than turning the next total into a full delta.
    if (Object.values(current).every(value => value == null)) continue;
    const d = delta(current, previous);
    previous = current;
    const reset = Object.values(d).some((v) => v === undefined);
    if (reset) { anomalies.push({ line: lineNo + 1, type: "counter_reset" }); continue; }
    if (!at || Date.parse(at) < since || Date.parse(at) > until) continue;
    const key = model || "unknown";
    if (!selectedFirstAt) selectedFirstAt = at;
    selectedLastAt = at;
    requests.push({ model: key, at, tokens: { ...d } });
    const row = totalsByModel.get(key) || { inputTokens: 0, cachedInputTokens: 0, cacheWriteInputTokens: 0, outputTokens: 0, reasoningOutputTokens: 0, unknown: false };
    for (const k of Object.keys(row).filter((k) => k.endsWith("Tokens"))) {
      if (d[k] == null) row.unknown = true;
      row[k] = addKnown(row[k], d[k]);
    }
    totalsByModel.set(key, row);
  }
  const models = [...totalsByModel].map(([modelName, row]) => ({ model: modelName, ...row }));
  return { startedAt: selectedFirstAt, finishedAt: selectedLastAt, models, requests, anomalies, attribution: anomalies.length ? "measured_with_anomalies" : "tokens_measured" };
}

export function estimateUsage(model, tokens, options = {}) {
  const inputTokens = n(tokens?.inputTokens ?? tokens?.input_tokens);
  const cachedInputTokens = n(tokens?.cachedInputTokens ?? tokens?.cached_input_tokens);
  const cacheWriteInputTokens = n(tokens?.cacheWriteInputTokens ?? tokens?.cache_write_input_tokens);
  const outputTokens = n(tokens?.outputTokens ?? tokens?.output_tokens);
  const reasoningOutputTokens = n(tokens?.reasoningOutputTokens ?? tokens?.reasoning_output_tokens) ?? 0;
  const uncached = inputTokens == null || cachedInputTokens == null || cachedInputTokens > inputTokens
    ? null : Math.max(0, inputTokens - cachedInputTokens - (cacheWriteInputTokens ?? 0));
  const rate = RATES[model];
  if (!rate || uncached == null || outputTokens == null) return { codexCreditsEstimate: null, apiUsdEstimate: null, uncachedInputTokens: uncached };
  const long = inputTokens > 272_000;
  const multiplier = options.fastMode && model === "gpt-6-astra" ? 2.5 : 1;
  const inputFactor = long ? 2 : 1;
  // Codex credit pricing stays at the published standard rates; the documented
  // long-context surcharge below is an API comparison estimate only.
  const credits = (uncached * rate.credits[0] + cachedInputTokens * rate.credits[1] + outputTokens * rate.credits[2]) / 1e6 * multiplier;
  // Codex logs omit cache-write counters. Published Codex pricing needs only
  // total input, cached input and output. Do not fabricate the missing API field.
  const api = cacheWriteInputTokens == null ? null : (uncached * rate.api[0] * inputFactor + cachedInputTokens * rate.api[1] * inputFactor + cacheWriteInputTokens * rate.api[0] * 1.25 + outputTokens * rate.api[2] * (long ? 1.5 : 1)) / 1e6;
  return { codexCreditsEstimate: cacheWriteInputTokens > 0 ? null : credits, apiUsdEstimate: api, uncachedInputTokens: uncached, reasoningOutputTokens };
}

function parseArgs(argv) {
  const out = { sessions: [], since: undefined, until: undefined, kind: "implementation", root: seoRoot(), write: false, id: undefined };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--session") out.sessions.push(argv[++i]);
    else if (a === "--since") out.since = argv[++i];
    else if (a === "--until") out.until = argv[++i];
    else if (a === "--kind") out.kind = argv[++i];
    else if (a === "--id") out.id = argv[++i];
    else if (a === "--root") out.root = argv[++i];
    else if (a === "--write") out.write = true;
  }
  if (!out.sessions.length) throw new Error("at least one --session FILE is required");
  if (!["implementation", "operations"].includes(out.kind)) throw new Error("--kind must be implementation or operations");
  return out;
}

function aggregate(parsed, id, kind, sourcePaths) {
  const models = parsed.flatMap((p) => p.models).reduce((map, row) => {
    const old = map.get(row.model) || { model: row.model, inputTokens: 0, cachedInputTokens: 0, cacheWriteInputTokens: 0, outputTokens: 0, reasoningOutputTokens: 0, unknown: false };
    for (const k of Object.keys(old).filter((k) => k.endsWith("Tokens"))) old[k] = addKnown(old[k], row[k]);
    old.unknown ||= row.unknown;
    map.set(row.model, old); return map;
  }, new Map());
  let codex = 0, api = 0, unknownCodex = false, unknownApi = false;
  const requests = parsed.flatMap((p) => p.requests || []);
  const resultModels = [...models.values()].map((row) => {
    const modelRequests = requests.filter((request) => request.model === row.model);
    const estimates = modelRequests.map((request) => estimateUsage(row.model, request.tokens));
    const credits = estimates.length && estimates.every((est) => est.codexCreditsEstimate != null)
      ? estimates.reduce((sum, est) => sum + est.codexCreditsEstimate, 0) : null;
    const apiEstimate = estimates.length && estimates.every((est) => est.apiUsdEstimate != null)
      ? estimates.reduce((sum, est) => sum + est.apiUsdEstimate, 0) : null;
    if (credits == null) unknownCodex = true; else codex += credits;
    if (apiEstimate == null) unknownApi = true; else api += apiEstimate;
    return { model: row.model, inputTokens: row.inputTokens, cachedInputTokens: row.cachedInputTokens, cacheWriteInputTokens: row.cacheWriteInputTokens, outputTokens: row.outputTokens, reasoningOutputTokens: row.reasoningOutputTokens, codexCreditsEstimate: credits, apiUsdEstimate: apiEstimate };
  });
  return { id, startedAt: parsed.map((p) => p.startedAt).filter(Boolean).sort()[0] ?? null, finishedAt: parsed.map((p) => p.finishedAt).filter(Boolean).sort().at(-1) ?? null, kind, models: resultModels, codexCreditsEstimate: unknownCodex || !resultModels.length ? null : codex, apiUsdEstimate: unknownApi || !resultModels.length ? null : api, actualUsd: null, accountCreditDelta: null, rateAssumptions:'Published standard Codex rates; fast-mode and account-specific adjustments are not identified by this log. API comparison unavailable when cache-write counters are absent.', attribution: parsed.some((p) => p.anomalies?.length) ? "measured_with_anomalies" : "tokens_measured", sourcePaths: sourcePaths.map((p) => path.basename(p)) };
}

async function writeLocked(file, update) {
  const lock = `${file}.lock`;
  await fs.mkdir(lock);
  try {
    let state = { schemaVersion: 1, rateDate: RATE_DATE, sources: SOURCES, runs: [] };
    try { state = JSON.parse(await fs.readFile(file, "utf8")); } catch (error) { if (error.code !== "ENOENT") throw error; }
    const next = update(state);
    const temp = `${file}.${process.pid}.tmp`;
    await fs.writeFile(temp, JSON.stringify(next, null, 2) + "\n");
    await fs.rename(temp, file);
  }
  finally { await fs.rm(lock, { recursive: true, force: true }); }
}

export async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const parsed = [];
  for (const file of args.sessions) parsed.push(parseSessionUsage(await fs.readFile(file, "utf8"), { since: args.since, until: args.until }));
  const id = args.id || path.basename(args.sessions[0], path.extname(args.sessions[0]));
  const run = aggregate(parsed, id, args.kind, args.sessions);
  const report = { schemaVersion: 1, rateDate: RATE_DATE, sources: SOURCES, run };
  if (args.write) {
    const file = path.resolve(args.root, "usage.json");
    await fs.mkdir(path.dirname(file), { recursive: true });
    await writeLocked(file, (state) => {
      state.schemaVersion = 1; state.rateDate = RATE_DATE; state.sources = SOURCES;
      state.runs = Array.isArray(state.runs) ? state.runs.filter((item) => item.id !== run.id) : [];
      state.runs.push(run);
      return state;
    });
  }
  return report;
}

if (import.meta.url === `file://${process.argv[1]}`) main().then((report) => console.log(JSON.stringify(report))).catch((error) => { console.error(error.message); process.exitCode = 1; });
