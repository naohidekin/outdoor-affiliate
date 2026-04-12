/**
 * X投稿自動化 — エージェント共通ユーティリティ
 *
 * 全エージェントスクリプトで共通的に使う関数群。
 * .env.local 読み込み・データJSON読み書き・KILLスイッチ・
 * 投稿履歴管理・類似度計算・書き出しパターン分類を提供。
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "..", "data");

// ─── .env.local ローダー ───���───────────────────────────

/**
 * .env.local を読み込んで process.env にセット。
 * 既存スクリプト全体で重複していた15行を共通化。
 */
export function loadEnv() {
  const envPath = path.join(__dirname, "..", "..", ".env.local");
  if (!fs.existsSync(envPath)) return;
  const content = fs.readFileSync(envPath, "utf-8");
  for (const line of content.split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match) {
      process.env[match[1].trim()] = match[2].trim().replace(/^["']|["']$/g, "");
    }
  }
}

// ─── JSON ファイル読み書き ──────��──────────────────────

/**
 * data/ 配下の JSON を読む。ファイルが無い場合は null。
 */
export function readJson(filename) {
  const filePath = path.join(DATA_DIR, filename);
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

/**
 * data/ 配下に JSON を書く。
 */
export function writeJson(filename, data) {
  const filePath = path.join(DATA_DIR, filename);
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + "\n", "utf-8");
}

// ─── KILL SWITCH ────────���─────────────────────────────

/**
 * kill-switch.json を確認。
 * @returns {{ killed: boolean, reason: string }}
 */
export function checkKillSwitch() {
  const data = readJson("kill-switch.json");
  if (!data) {
    // ファイルが無い場合は自動作成して正常返却
    writeJson("kill-switch.json", {
      enabled: false,
      reason: "",
      enabledAt: null,
      enabledBy: "manual",
    });
    console.warn("[kill-switch] ファイルが存在しなかったため自動作成しました");
    return { killed: false, reason: "" };
  }
  return {
    killed: !!data.enabled,
    reason: data.reason || "",
  };
}

// ─── 投稿��歴管理 ────────────────���───────────────────

/**
 * post-history.json を読み取り。
 * @returns {{ version: number, maxEntries: number, entries: Array }}
 */
export function loadPostHistory() {
  const data = readJson("post-history.json");
  if (!data) return { version: 1, maxEntries: 100, entries: [] };
  return data;
}

/**
 * post-history.json に1件追記（FIFO、maxEntries を超えたら古い方を削除）。
 */
export function appendToPostHistory(entry) {
  const data = loadPostHistory();
  data.entries.push(entry);
  if (data.entries.length > data.maxEntries) {
    data.entries = data.entries.slice(-data.maxEntries);
  }
  writeJson("post-history.json", data);
}

// ─── テキスト前処理 ──────────────────────────────────

/**
 * ハッシュタグと URL を除去してトリム。
 */
function cleanText(text) {
  return text
    .replace(/#\S+/g, "")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\*広告を含みます/g, "")
    .trim();
}

/**
 * 文字レベル bigram の Set を生成。
 */
function toBigrams(text) {
  const chars = [...cleanText(text)];
  const set = new Set();
  for (let i = 0; i < chars.length - 1; i++) {
    set.add(chars[i] + chars[i + 1]);
  }
  return set;
}

// ─── 類似度計算 ──────────────────────────────────────

/**
 * 2テキスト間の bigram Jaccard 係数を返す (0.0〜1.0)。
 * 形態素分析ライブラリ不要で日本語テキストの類似度を簡易判定。
 */
export function bigramJaccard(textA, textB) {
  const a = toBigrams(textA);
  const b = toBigrams(textB);
  if (a.size === 0 && b.size === 0) return 0;
  let intersection = 0;
  for (const bg of a) {
    if (b.has(bg)) intersection++;
  }
  const union = new Set([...a, ...b]).size;
  return union === 0 ? 0 : intersection / union;
}

// ─── 書き出しパターン分類 ─────────────────────────────

/**
 * テキストの第1文を各カテゴリの例文と bigram Jaccard で比較し、
 * 最もマッチするカテゴリ ID を返す。
 *
 * @param {string} text - 投稿テキスト全文
 * @param {object} patternsData - first-line-patterns.json のパースデータ
 * @returns {string} カテゴリ ID（例: "conclusion_first"）
 */
export function classifyFirstLinePattern(text, patternsData) {
  if (!patternsData || !patternsData.categories) return "unknown";

  // 第1文を抽出（。で区切るか、改行で区切るか、全文が短い場合はそのまま）
  const firstLine = text.split(/[。\n]/)[0] + "。";

  let bestId = "unknown";
  let bestScore = -1;

  for (const cat of patternsData.categories) {
    for (const example of cat.examples) {
      const score = bigramJaccard(firstLine, example);
      if (score > bestScore) {
        bestScore = score;
        bestId = cat.id;
      }
    }
  }

  return bestId;
}
