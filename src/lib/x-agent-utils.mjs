// @ts-nocheck
/**
 * X投稿自動化 — エージェント共通ユーティリティ
 *
 * 全エージェントスクリプトで共通的に使う関数群。
 * .env.local 読み込み・データJSON読み書き・KILLスイッチ・
 * 投稿履歴管理・類似度計算・書き出しパターン分類を提供。
 */

import fs from "fs";
import path from "path";
import dns from "dns";
import https from "https";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "..", "data");

// ─── .env.local ローダー ───���───────────────────────────

/**
 * .env.local を読み込んで process.env にセット。
 * 既存スクリプト全体で重複していた15行を共通化。
 */
export function loadEnv() {
  // IPv4優先: Node.js undiciがIPv6を先に試みてタイムアウトする問題を回避
  dns.setDefaultResultOrder("ipv4first");
  // 子プロセス（orchestrator → agent）にも伝搬させる
  if (!process.env.NODE_OPTIONS?.includes("--dns-result-order")) {
    process.env.NODE_OPTIONS = [process.env.NODE_OPTIONS, "--dns-result-order=ipv4first"].filter(Boolean).join(" ");
  }

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
 * data/ 配下に JSON を書く（ロックファイルで排他制御）。
 * Vercel等の read-only filesystem では書き込み不能のため、エラーは
 * 捕捉してログだけ出す（生成本体を止めない）。
 */
export function writeJson(filename, data) {
  const filePath = path.join(DATA_DIR, filename);
  const lockPath = filePath + ".lock";
  const maxWait = 10_000;
  const start = Date.now();

  // ロック取得（スピンウェイト）。read-only fs ではここで失敗するので即諦める。
  let locked = false;
  while (Date.now() - start < maxWait) {
    try {
      fs.writeFileSync(lockPath, String(process.pid), { flag: "wx" });
      locked = true;
      break;
    } catch (err) {
      // EROFS / EACCES は read-only filesystem なので即時諦める
      if (err && (err.code === "EROFS" || err.code === "EACCES")) {
        console.warn(`[writeJson] ${filename} 書き込みスキップ（read-only fs）: ${err.code}`);
        return;
      }
      // ロック競合 — 古いロック（30秒超）は強制解除
      try {
        const lockStat = fs.statSync(lockPath);
        if (Date.now() - lockStat.mtimeMs > 30_000) {
          fs.unlinkSync(lockPath);
          continue;
        }
      } catch { /* stat/unlink 失敗は無視 */ }
      // 100ms待機してリトライ
      const waitEnd = Date.now() + 100;
      while (Date.now() < waitEnd) { /* busy wait */ }
    }
  }
  if (!locked) {
    console.warn(`[writeJson] ${filename} ロック取得失敗、書き込みスキップ`);
    return;
  }

  try {
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + "\n", "utf-8");
  } catch (err) {
    if (err && (err.code === "EROFS" || err.code === "EACCES")) {
      console.warn(`[writeJson] ${filename} 書き込みスキップ（read-only fs）: ${err.code}`);
    } else {
      throw err;
    }
  } finally {
    try { fs.unlinkSync(lockPath); } catch { /* cleanup */ }
  }
}

// ─── KILL SWITCH ────────���─────────────────────────────

/**
 * kill-switch.json を確認。
 * @returns {{ killed: boolean, articleKilled: boolean, reason: string }}
 */
export function checkKillSwitch() {
  const data = readJson("kill-switch.json");
  if (!data) {
    // ファイルが無い場合は自動作成して正常返却
    writeJson("kill-switch.json", {
      enabled: false,
      articleEnabled: false,
      reason: "",
      enabledAt: null,
      enabledBy: "manual",
    });
    console.warn("[kill-switch] ファイルが存在しなかったため自動作成しました");
    return { killed: false, articleKilled: false, reason: "" };
  }
  return {
    killed: !!data.enabled,
    articleKilled: !!data.articleEnabled,
    reason: data.reason || "",
  };
}

/**
 * 記事パイプライン用 Kill Switch チェック。
 * enabled（全体停止）または articleEnabled（記事のみ停止）のいずれかで停止。
 * @returns {{ killed: boolean, reason: string }}
 */
export function checkArticleKillSwitch() {
  const ks = checkKillSwitch();
  if (ks.killed) return { killed: true, reason: ks.reason };
  if (ks.articleKilled) return { killed: true, reason: "記事パイプライン Kill Switch 有効" };
  return { killed: false, reason: "" };
}

/**
 * リサーチ系（viral-scout / youtube-researcher / x-search）用 Kill Switch チェック。
 * 投稿停止(enabled)とは独立。researchEnabled が明示的に true の場合のみ停止する。
 * → デフォルトでは「投稿を止めても研究は継続」の設計。
 * @returns {{ killed: boolean, reason: string }}
 */
export function checkResearchKillSwitch() {
  const data = readJson("kill-switch.json");
  if (!data) return { killed: false, reason: "" };
  if (data.researchEnabled) {
    return { killed: true, reason: data.reason || "リサーチ Kill Switch 有効" };
  }
  return { killed: false, reason: "" };
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

// ─── IPv4強制 fetch（undici フォールバック）────────────

/**
 * Node.js native https で IPv4 を強制する fetch 関数。
 * undici (native fetch) が IPv6 タイムアウトで失敗する環境用。
 * Anthropic SDK の `fetch` オプションに渡して使う。
 */
export function ipv4Fetch(url, init = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const body = init.body || null;
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: parsed.pathname + parsed.search,
      method: init.method || "GET",
      family: 4, // IPv4 強制
      headers: {},
    };

    // Headers を plain object に変換
    if (init.headers) {
      if (typeof init.headers.forEach === "function") {
        init.headers.forEach((v, k) => { options.headers[k] = v; });
      } else if (typeof init.headers.entries === "function") {
        for (const [k, v] of init.headers.entries()) { options.headers[k] = v; }
      } else {
        Object.assign(options.headers, init.headers);
      }
    }

    const req = https.request(options, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const buffer = Buffer.concat(chunks);
        const responseHeaders = new Headers();
        for (const [k, v] of Object.entries(res.headers)) {
          if (v) responseHeaders.set(k, Array.isArray(v) ? v.join(", ") : v);
        }
        resolve(new Response(buffer, {
          status: res.statusCode,
          statusText: res.statusMessage,
          headers: responseHeaders,
        }));
      });
    });

    req.on("error", reject);
    if (init.signal) {
      init.signal.addEventListener("abort", () => req.destroy());
    }
    if (body) req.write(body);
    req.end();
  });
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
