// scripts/x/lib/file-lock.mjs
// JSONL I/O + kill-switch + id/jst ヘルパー。段階分割パイプライン共通基盤。
// 既存の data/kill-switch.json（enabled フラグが X 投稿系を止める）に接続する。
import { readFileSync, writeFileSync, appendFileSync, existsSync, renameSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "../../..");

// .env.local を手動読み込み（既存スクリプトと同じ流儀。dotenv 非依存）。
export function loadEnv() {
  const envPath = resolve(ROOT, ".env.local");
  if (!existsSync(envPath)) return;
  for (const line of readFileSync(envPath, "utf8").split("\n")) {
    const eq = line.indexOf("=");
    if (eq > 0 && !line.trimStart().startsWith("#")) {
      const key = line.slice(0, eq).trim();
      const val = line.slice(eq + 1).trim().replace(/^["']|["']$/g, "");
      if (!process.env[key]) process.env[key] = val;
    }
  }
}

export const POSTS_PATH = resolve(ROOT, "data/x/posts.jsonl");
export const IDEA_BANK_PATH = resolve(ROOT, "data/x/ideas.jsonl");
const KILL_SWITCH_PATH = resolve(ROOT, "data/kill-switch.json");

// ─── JST タイムスタンプ ───────────────────────────────────────────────
// scripts は Date.now を使える（Workflow スクリプトの制約は無関係）。
export function jstNow() {
  return new Date(Date.now() + 9 * 3600 * 1000).toISOString().replace("Z", "+09:00");
}

export function jstDateStamp() {
  return jstNow().slice(0, 10).replace(/-/g, "");
}

// ─── ID 生成（prefix-YYYYMMDD-xxxx、既存と衝突しない） ────────────────
export function generateId(prefix, existing = []) {
  const stamp = jstDateStamp();
  const used = new Set(existing.map((e) => e.id));
  for (let i = 0; i < 10000; i++) {
    const rand = Math.random().toString(36).slice(2, 6);
    const id = `${prefix}-${stamp}-${rand}`;
    if (!used.has(id)) return id;
  }
  return `${prefix}-${stamp}-${Date.now().toString(36).slice(-4)}`;
}

// ─── JSONL 読み書き ──────────────────────────────────────────────────
export function readJsonl(path) {
  if (!existsSync(path)) return [];
  const raw = readFileSync(path, "utf8").trim();
  if (!raw) return [];
  return raw
    .split("\n")
    .filter(Boolean)
    .map((line, i) => {
      try {
        return JSON.parse(line);
      } catch {
        console.warn(`[file-lock] skip malformed jsonl line ${i + 1} in ${path}`);
        return null;
      }
    })
    .filter(Boolean);
}

export function appendJsonl(path, record) {
  appendFileSync(path, JSON.stringify(record) + "\n", "utf8");
}

// 全書き換え（updatePost で使用）。tmp→rename でアトミックに。
export function writeJsonl(path, records) {
  const tmp = path + ".tmp";
  writeFileSync(tmp, records.map((r) => JSON.stringify(r)).join("\n") + "\n", "utf8");
  renameSync(tmp, path);
}

// posts.jsonl 内の 1 レコードを status/scores 等でパッチ更新する。
export function updatePost(id, patch, path = POSTS_PATH) {
  const posts = readJsonl(path);
  const idx = posts.findIndex((p) => p.id === id);
  if (idx === -1) {
    console.warn(`[file-lock] updatePost: id not found: ${id}`);
    return null;
  }
  posts[idx] = { ...posts[idx], ...patch };
  writeJsonl(path, posts);
  return posts[idx];
}

// ─── Kill switch ─────────────────────────────────────────────────────
// 既存セマンティクス: enabled=true が「キルスイッチON（停止）」。
// orchestrate.js が連続エラー時に enabled=true をセットして止める。
// researchEnabled=true は research 段の停止、articleEnabled は記事系（本パイプラインは無関係）。
function readKillSwitch() {
  if (!existsSync(KILL_SWITCH_PATH)) return {};
  try {
    return JSON.parse(readFileSync(KILL_SWITCH_PATH, "utf8"));
  } catch {
    return {};
  }
}

export function isKillSwitchOn() {
  return readKillSwitch().enabled === true;
}

export function isResearchKilled() {
  return readKillSwitch().researchEnabled === true;
}
