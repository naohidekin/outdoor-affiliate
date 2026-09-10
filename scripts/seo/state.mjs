import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
export const DEFAULT_ROOT = path.join(os.homedir(), ".secretary", "state", "campgearlab-seo");
export const CHECKPOINT_DAYS = [7, 14, 28, 42];
const SITE_HOST = "camp-gear-lab.com";
const TERMINAL = new Set(["retained", "revised", "rolled_back", "inconclusive"]);
const ACTIVE = new Set(["proposed", "approved", "publishing", "verification_pending", "published", "observing", "paused"]);
const PUBLICATION_EVENTS = new Set(["publication_prepared", "remote_applied", "verification_pending", "publication_failed", "publication_verified"]);
export const DEFAULT_POLICY = Object.freeze({
  schemaVersion: 1,
  maxActiveExperiments: 3,
  maxNewPerRun: 1,
  models: { "gpt-6-astra": { maxInputTokens: null, maxOutputTokens: null } },
});

function isoNow(now) { return typeof now === "function" ? now() : new Date().toISOString(); }
function isIso(value) { return typeof value === "string" && !Number.isNaN(Date.parse(value)); }
function sourceDay(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  if (!isIso(value)) return null;
  const parts = new Intl.DateTimeFormat("en", { timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(value));
  return `${parts.find((part) => part.type === "year").value}-${parts.find((part) => part.type === "month").value}-${parts.find((part) => part.type === "day").value}`;
}
function assert(condition, message) { if (!condition) throw new Error(message); }
function clone(value) { return structuredClone(value); }
const UNDEFINED = "__seo_state_undefined__";
function encodeUndefined(value) {
  if (value === undefined) return { [UNDEFINED]: true };
  if (Array.isArray(value)) return value.map(encodeUndefined);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, encodeUndefined(item)]));
  return value;
}
function decodeUndefined(value) {
  if (Array.isArray(value)) return value.map(decodeUndefined);
  if (value && typeof value === "object") {
    if (Object.keys(value).length === 1 && value[UNDEFINED] === true) return undefined;
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, decodeUndefined(item)]));
  }
  return value;
}
function statePath(root) { return path.join(root, "state.json"); }
function lockPath(root) { return path.join(root, ".state.lock"); }
function policyPath(root) { return path.join(root, "policy.json"); }
function defaultState() { return { schemaVersion: 1, experiments: [] }; }

export function canonicalUrl(input) {
  let url;
  try { url = new URL(input); } catch { throw new Error(`invalid URL: ${input}`); }
  assert(url.protocol === "https:" && url.hostname.toLowerCase() === SITE_HOST, "URL must be https://camp-gear-lab.com");
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function requireProposal(input) {
  assert(input && typeof input === "object", "proposal must be an object");
  assert(!Object.hasOwn(input, "id"), "proposal id must not be supplied");
  const urls = input.urls || {};
  const canonical = canonicalUrl(urls.canonical);
  const links = Array.isArray(urls.linkSourcePages) ? urls.linkSourcePages.map(canonicalUrl) : [];
  assert(Array.isArray(input.queryTargets) && input.queryTargets.length, "queryTargets is required");
  assert(input.baseline && input.baseline.source === "gsc", "baseline source must be gsc");
  assert(input.baseline.sourceTimezone === "America/Los_Angeles", "baseline GSC sourceTimezone must be America/Los_Angeles");
  assert(isIso(input.baseline.capturedAt), "baseline capturedAt must be an ISO instant");
  for (const field of ["hypothesis", "expectedOutcome", "falsification", "beforeContentHash"]) assert(typeof input[field] === "string" && input[field], `${field} is required`);
  assert(Array.isArray(input.evidenceUrls) && input.evidenceUrls.length, "evidenceUrls is required");
  return {
    urls: { canonical, linkSourcePages: [...new Set(links)] },
    queryTargets: clone(input.queryTargets), baseline: clone(input.baseline), hypothesis: input.hypothesis,
    evidenceUrls: clone(input.evidenceUrls), expectedOutcome: input.expectedOutcome,
    falsification: input.falsification, beforeContentHash: input.beforeContentHash,
    ...(input.metadata === undefined ? {} : { metadata: clone(input.metadata) }),
  };
}

function assertAstra(decision) {
  assert(decision && decision.model === "gpt-6-astra", "decision model must be gpt-6-astra");
  assert(typeof decision.rationale === "string" && decision.rationale.trim(), "decision rationale is required");
}
function assertModelBounds(decision, limits) {
  const bounds = limits.models?.[decision.model];
  if (!bounds) return;
  const usage = decision.usage || decision;
  if (usage.inputTokens !== undefined && bounds.maxInputTokens != null) assert(usage.inputTokens <= bounds.maxInputTokens, `model input exceeds policy limit (${bounds.maxInputTokens})`);
  if (usage.outputTokens !== undefined && bounds.maxOutputTokens != null) assert(usage.outputTokens <= bounds.maxOutputTokens, `model output exceeds policy limit (${bounds.maxOutputTokens})`);
}
function activeUrlSet(experiment) { return new Set([experiment.urls.canonical, ...(experiment.urls.linkSourcePages || [])]); }
function hasConflict(experiment, candidate) {
  const a = activeUrlSet(experiment); const b = activeUrlSet(candidate);
  for (const url of b) if (a.has(url)) return url;
  return null;
}
function history(experiment, type, at, details = {}) {
  experiment.history.push({ id: crypto.randomUUID(), type, at, ...clone(details) });
}

async function readJson(filename, fallback) {
  try { return decodeUndefined(JSON.parse(await fs.readFile(filename, "utf8"))); }
  catch (error) { if (error.code === "ENOENT") return clone(fallback); throw error; }
}
async function atomicJson(filename, value) {
  const temporary = `${filename}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(encodeUndefined(value), null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, filename);
}
async function assertVerifiedPublicationJournal(root, experiment, input) {
  const type = input?.type || input?.status;
  if (type !== "publication_verified") return;
  assert(typeof input.manifestHash === "string" && input.manifestHash, "verified publication event requires manifestHash");
  const journal = await readJson(path.join(root, "snapshots", `${experiment.id}.json`), undefined);
  assert(journal, "verified publication journal is missing");
  assert(journal.experimentId === experiment.id && journal.status === "verified", "publication journal is not verified for this experiment");
  assert(journal.manifestHash === input.manifestHash, "publication journal manifest hash mismatch");
  assert(experiment.approval?.manifestHash === journal.manifestHash, "approved manifest hash does not match publication journal");
}
async function acquire(root, now) {
  await fs.mkdir(root, { recursive: true });
  const token = crypto.randomUUID();
  try {
    const handle = await fs.open(lockPath(root), "wx", 0o600);
    await handle.writeFile(JSON.stringify({ pid: process.pid, token, createdAt: isoNow(now) }));
    await handle.close();
  } catch (error) {
    if (error.code === "EEXIST") throw new Error(`active lock at ${lockPath(root)}; refusing to steal it`);
    throw error;
  }
  return async () => {
    try {
      const lock = JSON.parse(await fs.readFile(lockPath(root), "utf8"));
      if (lock.token === token) await fs.rm(lockPath(root), { force: true });
    } catch (error) { if (error.code !== "ENOENT") throw error; }
  };
}

export function getDueCheckpoints(experiment, now = new Date().toISOString()) {
  if (!experiment?.publishedAt || experiment.status !== "observing") return [];
  const publishedAt = Date.parse(experiment.publishedAt);
  const observed = new Set((experiment.observations || []).filter(isSettledObservation).map((item) => item.checkpointDay));
  const current = Date.parse(now);
  return CHECKPOINT_DAYS
    .filter((day) => current >= publishedAt + day * 86400000 && !observed.has(day))
    .map((day) => ({ day, dueAt: new Date(publishedAt + day * 86400000).toISOString(), late: current > publishedAt + day * 86400000 }));
}

export function validateObservation(input) {
  assert(input && typeof input === "object", "observation must be an object");
  assert(typeof input.observationId === "string" && input.observationId, "observationId is required");
  assert(isIso(input.observedAt), "observedAt must be an ISO instant");
  assert(input.source === "gsc", "observation source must be gsc");
  assert(input.sourceTimezone === "America/Los_Angeles", "GSC sourceTimezone must be America/Los_Angeles");
  assert(typeof input.sourceValid === "boolean", "sourceValid must be boolean");
  assert(typeof input.checkpointDay === "number" && CHECKPOINT_DAYS.includes(input.checkpointDay), "checkpointDay must be 7, 14, 28, or 42");
  assert(input.metrics && typeof input.metrics === "object" && !Array.isArray(input.metrics), "metrics must be an object");
  assert(input.causalityClaim === false, "observations must not claim causality");
  const metrics = input.metrics;
  const numeric = { clicks: [0, Infinity], impressions: [0, Infinity], ctr: [0, 1], position: [Number.MIN_VALUE, Infinity] };
  for (const [name, [min, max]] of Object.entries(numeric)) {
    const value = metrics[name];
    if (value !== undefined && value !== null) assert(typeof value === "number" && Number.isFinite(value) && value >= min && value <= max, `${name} is out of range`);
  }
  if (input.sourceValid) {
    for (const field of ["periodStart", "periodEnd", "settledThrough"]) assert(sourceDay(input[field]), `${field} must be a PT date or ISO instant for a valid source`);
    assert(sourceDay(input.periodStart) <= sourceDay(input.periodEnd) && sourceDay(input.periodEnd) <= sourceDay(input.settledThrough) && sourceDay(input.settledThrough) <= sourceDay(input.observedAt), "observation periods must be ordered and settled");
    assert(["clicks", "impressions", "ctr", "position"].some((name) => typeof metrics[name] === "number" && Number.isFinite(metrics[name])), "a valid source requires an actual GSC metric");
  }
  return clone(input);
}

export function isSettledObservation(observation) {
  return observation?.sourceValid === true
    && ["periodStart", "periodEnd", "settledThrough"].every((field) => sourceDay(observation[field]))
    && sourceDay(observation.periodStart) <= sourceDay(observation.periodEnd)
    && sourceDay(observation.periodEnd) <= sourceDay(observation.settledThrough)
    && ["clicks", "impressions", "ctr", "position"].some((name) => typeof observation.metrics?.[name] === "number" && Number.isFinite(observation.metrics[name]));
}

export function applyPublicationEvent(experiment, event) {
  assert(event && typeof event.eventId === "string" && event.eventId, "eventId is required");
  event = { ...event, type: event.type || event.status };
  assert(typeof event.type === "string" && event.type, "event type is required");
  assert(PUBLICATION_EVENTS.has(event.type), `unsupported publication event: ${event.type}`);
  assert(isIso(event.occurredAt), "event occurredAt must be an ISO instant");
  if ((experiment.events || []).some((item) => item.eventId === event.eventId)) return experiment;
  const saved = clone(event);
  experiment.events.push(saved);
  if (experiment.publishedAt && saved.type !== "publication_verified") return experiment;
  if (saved.type === "publication_prepared" || saved.type === "remote_applied") experiment.status = "publishing";
  if (saved.type === "verification_pending") experiment.status = "verification_pending";
  if (saved.type === "publication_failed") experiment.status = "approved";
  if (saved.type === "publication_verified") {
    experiment.publishedAt ||= saved.occurredAt;
    experiment.status = "observing";
  }
  return experiment;
}

/** Maps the publisher journal to an idempotent event for store.event(). */
export function publicationEventFromJournal(journal) {
  const types = { prepared: "publication_prepared", remote_applied: "remote_applied", verification_pending: "verification_pending", verified: "publication_verified" };
  assert(journal && types[journal.status], "unknown publisher journal status");
  assert(typeof journal.manifestHash === "string" && journal.manifestHash, "publisher journal manifestHash is required");
  return {
    eventId: `${journal.manifestHash}:${journal.status}`,
    type: types[journal.status],
    occurredAt: journal.verifiedAt || journal.updatedAt || journal.createdAt || new Date().toISOString(),
    manifestHash: journal.manifestHash,
    journalStatus: journal.status,
  };
}

/** @param {{root?: string, dryRun?: boolean, now?: () => string, policy?: {schemaVersion?: number, maxActiveExperiments?: number, maxNewPerRun?: number, models?: Record<string, {maxInputTokens?: number|null, maxOutputTokens?: number|null}>}, runId?: string}} [options] */
export function createStore({ root, dryRun = false, now, policy: suppliedPolicy, runId } = {}) {
  root = path.resolve(root || process.env.SEO_STATE_ROOT || DEFAULT_ROOT);
  const effectiveRunId = runId || `jst-${new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo" }).format(new Date(isoNow(now)))}`;
  async function policy() { return { ...DEFAULT_POLICY, ...(await readJson(policyPath(root), DEFAULT_POLICY)), ...(suppliedPolicy || {}) }; }
  async function mutate(fn) {
    if (dryRun) {
      const state = await readJson(statePath(root), defaultState());
      return fn(state, await policy(), true);
    }
    const release = await acquire(root, now);
    try {
      const state = await readJson(statePath(root), defaultState());
      const result = await fn(state, await policy(), false);
      await atomicJson(statePath(root), state);
      return result;
    } finally { await release(); }
  }
  async function get(id) { return clone((await readJson(statePath(root), defaultState())).experiments.find((item) => item.id === id)); }
  async function mustGet(state, id) { const item = state.experiments.find((entry) => entry.id === id); assert(item, `experiment not found: ${id}`); return item; }
  return {
    root,
    async init() {
      if (dryRun) return { root, dryRun: true, policy: await policy() };
      const release = await acquire(root, now);
      try {
        const state = await readJson(statePath(root), defaultState());
        await atomicJson(statePath(root), state);
        try { await fs.access(policyPath(root)); } catch (error) { if (error.code === "ENOENT") await atomicJson(policyPath(root), { ...DEFAULT_POLICY, ...(suppliedPolicy || {}) }); else throw error; }
        return { root, policy: await policy() };
      } finally { await release(); }
    },
    async list() { return clone((await readJson(statePath(root), defaultState())).experiments); },
    get,
    async propose(input) { return mutate(async (state, limits) => {
      const candidate = requireProposal(input); const at = isoNow(now);
      const active = state.experiments.filter((item) => ACTIVE.has(item.status));
      assert(active.length < limits.maxActiveExperiments, `max active experiments reached (${limits.maxActiveExperiments})`);
      const createdThisRun = state.experiments.filter((item) => item.runId === effectiveRunId).length;
      assert(createdThisRun < limits.maxNewPerRun, `max new experiments per run reached (${limits.maxNewPerRun})`);
      for (const item of active) { const conflict = hasConflict(item, candidate); if (conflict) {
        const itemUsesAsSource = item.urls.linkSourcePages.includes(conflict);
        const candidateUsesAsSource = candidate.urls.linkSourcePages.includes(conflict);
        throw new Error(itemUsesAsSource || candidateUsesAsSource ? `active experiment owns link source: ${conflict}` : `active experiment already owns URL: ${conflict}`);
      } }
      const experiment = { ...candidate, id: crypto.randomUUID(), runId: effectiveRunId, status: "proposed", createdAt: at, updatedAt: at, events: [], observations: [], history: [] };
      history(experiment, "proposed", at, { actor: input.actor || "operator" }); state.experiments.push(experiment); return clone(experiment);
    }); },
    async approve(id, decision) { return mutate(async (state, limits) => {
      assertAstra(decision); assertModelBounds(decision, limits); const experiment = await mustGet(state, id); assert(experiment.status === "proposed", "only proposed experiments can be approved");
      experiment.status = "approved"; experiment.approval = clone(decision); experiment.updatedAt = isoNow(now); history(experiment, "approved", experiment.updatedAt, decision); return clone(experiment);
    }); },
    async transition(id, status, decision) { return mutate(async (state, limits) => {
      assert(TERMINAL.has(status), `unsupported terminal status: ${status}`); assertAstra(decision); assertModelBounds(decision, limits); const experiment = await mustGet(state, id);
      assert(!TERMINAL.has(experiment.status), "experiment is already terminal");
      if (status === "rolled_back") throw new Error("rolled_back requires a separately verified forward rollback experiment");
      if (["retained", "revised"].includes(status)) {
        assert(experiment.publishedAt, `${status} requires verified publication`);
        assert((experiment.observations || []).some(isSettledObservation), `${status} requires a valid settled observation`);
      }
      experiment.status = status; experiment.finalDecision = clone(decision); experiment.updatedAt = isoNow(now); history(experiment, status, experiment.updatedAt, decision); return clone(experiment);
    }); },
    async event(id, input) { return mutate(async (state) => {
      const experiment = await mustGet(state, id); assert(["approved", "publishing", "verification_pending", "observing"].includes(experiment.status), "publication event is not valid for this status"); await assertVerifiedPublicationJournal(root, experiment, input);
      const before = experiment.events.length; applyPublicationEvent(experiment, input); if (experiment.events.length !== before) { experiment.updatedAt = isoNow(now); history(experiment, input.type || input.status, experiment.updatedAt, { eventId: input.eventId }); } return clone(experiment);
    }); },
    async record(id, input) { return mutate(async (state) => {
      const experiment = await mustGet(state, id); assert(experiment.publishedAt, "cannot record an observation before publication is verified"); assert(experiment.status === "observing", "observations can only be recorded while observing");
      if (experiment.observations.some((item) => item.observationId === input?.observationId)) return clone(experiment);
      const observation = validateObservation(input);
      if (observation.sourceValid) {
        assert(sourceDay(observation.periodStart) > sourceDay(experiment.publishedAt), "valid observation period must start after the publication PT day");
        const periodDays = Math.round((Date.parse(`${sourceDay(observation.periodEnd)}T12:00:00Z`) - Date.parse(`${sourceDay(observation.periodStart)}T12:00:00Z`)) / 86400000) + 1;
        assert(periodDays >= observation.checkpointDay, "observation period is shorter than its checkpoint");
      }
      assert(Date.parse(observation.observedAt) >= Date.parse(experiment.publishedAt) + observation.checkpointDay * 86400000, "observation checkpoint is not due yet");
      experiment.observations.push(observation); experiment.status = "observing"; experiment.updatedAt = isoNow(now); history(experiment, "observation_recorded", experiment.updatedAt, { observationId: observation.observationId }); return clone(experiment);
    }); },
    async pause(id, reason) { return mutate(async (state) => { const experiment = await mustGet(state, id); assert(ACTIVE.has(experiment.status) && experiment.status !== "paused", "experiment cannot be paused"); experiment.resumeStatus = experiment.status; experiment.status = "paused"; experiment.updatedAt = isoNow(now); history(experiment, "paused", experiment.updatedAt, { reason: reason || null }); return clone(experiment); }); },
    async resume(id) { return mutate(async (state) => { const experiment = await mustGet(state, id); assert(experiment.status === "paused", "experiment is not paused"); experiment.status = experiment.resumeStatus || "approved"; delete experiment.resumeStatus; experiment.updatedAt = isoNow(now); history(experiment, "resumed", experiment.updatedAt); return clone(experiment); }); },
    async due(at = isoNow(now)) { const experiments = await this.list(); const awaitingPublication = experiments.filter((item) => ["approved", "publishing", "verification_pending"].includes(item.status)); const due = experiments.flatMap((item) => getDueCheckpoints(item, at).map((checkpoint) => ({ experimentId: item.id, url: item.urls.canonical, ...checkpoint }))); return { awaitingPublication, due, late: due.filter((item) => item.late) }; },
    async reportData(at = isoNow(now)) { return { generatedAt: at, experiments: await this.list(), due: await this.due(at), policy: await policy() }; },
  };
}
