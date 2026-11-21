// Owner WISE-AS, pinned raw source. No model or network calls.
import { existsSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
const MODULE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
export const WISE_AXES = Object.freeze(["Wit", "Insight", "Sincere", "Empth", "AI-free", "Sense"]);
export const WISE_FLOORS = Object.freeze({ w: 2, i: 2, s: 2, e: 2, ai: 3, sense: 2 });
const PINNED = {"wise-master.md": "7f3a5a347bca6ffb57eccf053b2eef5a4c40c79cae8032b6ad7dcb95a4cd6144", "sense-master.md": "5099cf3df213c1a63f45aca9b28a1c3a858a0492fe6a4ae2c819f9f9fd85b2f8"};
const ARTIFACTS = {"SKILL.md": "bbe36130b55003ca8a35529bc68367f168cc565d075460acaca86849839d3dcc", "docs/WISE-GEARMAN.md": "43a983ac458c006426a2d241e800b65cad539a94b6d6b6ea1c246b1b4bedc5e2", "docs/sense-definition.md": "e56ed9144bcaf544f1270fd4481fb77ad20351e98de364a065711fca82046c41"};
const REQUIRED = ["rules/common/wise-contract.json", ...Object.keys(PINNED).map(name => `rules/common/${name}`), ...Object.keys(ARTIFACTS)];
const digest = (value) => createHash("sha256").update(value).digest("hex");
const stable = (value) => value && typeof value === "object"
  ? Array.isArray(value) ? value.map(stable) : Object.fromEntries(Object.keys(value).sort().map(k => [k, stable(value[k])]))
  : value;
function defaultWiseRoot() {
  for (const root of [MODULE_ROOT, resolve(process.cwd())]) {
    if (REQUIRED.every(name => existsSync(resolve(root, name)))) return root;
  }
  throw new Error("wise_policy_root_unavailable");
}
export function loadWisePolicy(root = defaultWiseRoot()) {
  const folder = resolve(root, "rules/common");
  const contract = JSON.parse(readFileSync(resolve(folder, "wise-contract.json"), "utf8"));
  if (contract.schemaVersion !== 1 || JSON.stringify(contract.axes) !== JSON.stringify(WISE_AXES)
      || JSON.stringify(stable(contract.floors)) !== JSON.stringify(stable(WISE_FLOORS))) throw new Error("wise_policy_contract_drift");
  if (JSON.stringify(stable(contract.artifacts)) !== JSON.stringify(stable(ARTIFACTS))) throw new Error("wise_artifact_contract_drift");
  for (const [name, hash] of Object.entries(ARTIFACTS)) {
    if (digest(readFileSync(resolve(root, name))) !== hash) throw new Error("wise_explanation_drift");
  }
  const raw = Object.entries(PINNED).map(([name, hash]) => {
    const value = readFileSync(resolve(folder, name));
    if (digest(value) !== hash || contract.sources?.[name]?.sha256 !== hash) throw new Error("wise_owner_source_drift");
    return value.toString("utf8");
  });
  return { id: digest(JSON.stringify(stable(contract))), axes: [...WISE_AXES], floors: {...WISE_FLOORS}, sourceHashes: {...PINNED}, text: raw.join("\n\n") };
}
export function validWiseScores(scores) {
  return scores && typeof scores === "object" && Object.keys(scores).length === 6
    && Object.keys(WISE_FLOORS).every(k => typeof scores[k] === "number" && Number.isFinite(scores[k]) && scores[k] >= 1 && scores[k] <= 4);
}
export function passesWise(scores) {
  return Boolean(validWiseScores(scores) && Object.entries(WISE_FLOORS).every(([key, floor]) => scores[key] >= floor));
}
export function wiseContentHash(text) { return digest(String(text ?? "")); }
export function requireWiseReview(artifact, policy = loadWisePolicy()) {
  const text = artifact?.content ?? artifact?.text ?? artifact?.body;
  if (typeof text !== "string" || artifact?.wiseContentHash !== wiseContentHash(text)
      || artifact?.wiseReviewPassed !== true || artifact?.wisePolicy !== policy.id || !passesWise(artifact?.wiseScores ?? artifact?.wise_scores)) throw new Error("current_wise_policy_review_required");
}

export function findWiseProof(text, candidates, policy = loadWisePolicy()) {
  return (candidates || []).find(candidate => {
    if ((candidate?.content ?? candidate?.text ?? candidate?.body) !== text) return false;
    try { requireWiseReview(candidate, policy); return true; } catch { return false; }
  }) ?? null;
}

export function requireWiseBinding(bundle, review, revision, policy = loadWisePolicy()) {
  if (bundle?.wisePolicy !== policy.id || review?.wisePolicy !== policy.id
      || review?.passed !== true || review?.fingerprint !== revision || !passesWise(review?.wiseScores)) {
    throw new Error("current_wise_policy_review_required");
  }
}
