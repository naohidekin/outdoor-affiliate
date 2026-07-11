#!/usr/bin/env node

/**
 * リンク切れ自動修復パイプライン（link-check の後段。日曜 7:00）
 *
 * 思想: 「害の除去は全自動、商品の差し替えだけ人間の1クリック承認」
 *  1. link-check-report.json の broken を再検証
 *     （Creators APIキーがあれば getItems で確定判定。HTTPはCAPTCHAで判定不能になりやすい）
 *  2. 死亡確定リンクは amazonUrl を自動で空に = 隔離
 *     （サイトでは楽天ボタンだけ残る。壊れリンクの露出を即座に止める）
 *  3. Creators APIキーがあれば代替候補を自動検索し、提案ファイルに書き出す
 *     → 管理画面 /admin/link-check の「候補に差し替え」ボタンで1クリック適用
 *  4. Supabase同期 + git commit/push（本番管理画面へ提案を届ける）
 *
 * 使い方:
 *   node scripts/link-fix.mjs             # 本実行
 *   node scripts/link-fix.mjs --dry-run   # 書き込み・同期・pushなし
 *   node scripts/link-fix.mjs --no-push   # git pushだけ抑止
 */

import fs from "fs";
import path from "path";
import { execSync } from "child_process";
import { fileURLToPath } from "url";
import { checkKillSwitch } from "../src/lib/x-agent-utils.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const DATA_DIR = path.join(ROOT, "data");
const DRY_RUN = process.argv.includes("--dry-run");
const NO_PUSH = process.argv.includes("--no-push");

// .env.local 手動読み込み（check-amazon-links.js と同方式）
const envPath = path.join(ROOT, ".env.local");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf-8").split("\n")) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m && !process.env[m[1].trim()]) process.env[m[1].trim()] = m[2].trim();
  }
}

// Creators API 認証情報（2026年5月にPA-API v5は廃止。後継のCreators APIを使う）
// アソシエイト・セントラル → Creators API で発行した「認証情報ID」(amzn1...) と
// 「Credential Secret」。旧変数名 AMAZON_ACCESS_KEY/SECRET_KEY に入れてあっても読める。
const CREDENTIAL_ID = process.env.AMAZON_CREDENTIAL_ID || process.env.AMAZON_ACCESS_KEY;
const CREDENTIAL_SECRET = process.env.AMAZON_CREDENTIAL_SECRET || process.env.AMAZON_SECRET_KEY;
const CREDENTIAL_VERSION = process.env.AMAZON_CREDENTIAL_VERSION || "3.3"; // 日本のLWA
const PARTNER_TAG = process.env.AMAZON_PARTNER_TAG || "camp78-22";
const HAS_API = Boolean(CREDENTIAL_ID && CREDENTIAL_SECRET);
if (HAS_API && /^AKIA/.test(CREDENTIAL_ID)) {
  console.log("⚠️ AKIA形式の旧PA-APIキーが設定されています。PA-APIは廃止済みのため、Creators APIの認証情報ID(amzn1...)に差し替えてください。");
}

// ─── URL再検証（check-amazon-links.js と同じ判定基準） ───────────

async function checkUrl(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    const res = await fetch(url, {
      method: "GET",
      signal: controller.signal,
      redirect: "follow",
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Accept: "text/html,application/xhtml+xml",
        "Accept-Language": "ja,en;q=0.9",
      },
    });
    clearTimeout(timeout);
    const text = await res.text();
    const isNotFound =
      res.status === 404 ||
      text.includes("ページが見つかりません") ||
      text.includes("currently unavailable") ||
      text.includes("Page Not Found");
    const isDogPage = text.includes("SORRY") && text.includes("www.amazon.co.jp");
    // CAPTCHA/ロボットチェックは「判定不能」扱い（隔離しない）
    const isCaptcha = text.includes("api-services-support@amazon.com") || text.includes("Enter the characters");
    if (isCaptcha) return { verdict: "unknown" };
    if (isNotFound || isDogPage) return { verdict: "dead" };
    if (res.ok) return { verdict: "alive" };
    return { verdict: "unknown", status: res.status };
  } catch {
    // ネットワークエラーは判定不能（安全側: 隔離しない）
    return { verdict: "unknown" };
  }
}

// ─── Amazon Creators API（PA-API v5の後継。OAuth2 client_credentials） ───
// 認証: 認証情報バージョンに応じたLWAエンドポイントでトークン取得（1時間有効）
// API:  https://creatorsapi.amazon/catalog/v1/{getItems|searchItems}
//       marketplaceは x-marketplace ヘッダー、JSONキーはlowerCamelCase

const TOKEN_ENDPOINTS = {
  "3.1": "https://api.amazon.com/auth/o2/token",
  "3.2": "https://api.amazon.co.uk/auth/o2/token",
  "3.3": "https://api.amazon.co.jp/auth/o2/token",
};
const API_BASE = "https://creatorsapi.amazon";
const MARKETPLACE = "www.amazon.co.jp";

let cachedToken = null;

async function getAccessToken() {
  if (cachedToken && Date.now() < cachedToken.expiresAt) return cachedToken.token;
  const endpoint = TOKEN_ENDPOINTS[CREDENTIAL_VERSION] || TOKEN_ENDPOINTS["3.3"];
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "client_credentials",
      client_id: CREDENTIAL_ID,
      client_secret: CREDENTIAL_SECRET,
      scope: "creatorsapi::default",
    }),
  });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 200);
    throw new Error(`Creators APIトークン取得失敗 ${res.status}: ${detail}`);
  }
  const data = await res.json();
  cachedToken = {
    token: data.access_token,
    expiresAt: Date.now() + (Number(data.expires_in || 3600) - 60) * 1000,
  };
  return cachedToken.token;
}

async function creatorsApi(apiPath, payload) {
  const token = await getAccessToken();
  const res = await fetch(`${API_BASE}${apiPath}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "x-marketplace": MARKETPLACE,
    },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`Creators API ${res.status}: ${text.slice(0, 200)}`);
  return JSON.parse(text);
}

async function searchItems(keywords) {
  const data = await creatorsApi("/catalog/v1/searchItems", {
    keywords: keywords.slice(0, 100),
    searchIndex: "All",
    itemCount: 5,
    partnerTag: PARTNER_TAG,
    resources: ["itemInfo.title", "itemInfo.byLineInfo", "offersV2.listings.price"],
  });
  return data.searchResult?.items || [];
}

// ─── Creators API getItems による生死判定 ─────────────────
// HTTPスクレイピングはAmazonのCAPTCHAでほぼ全滅するため、
// キーがあれば正規API（getItems）でASINの生死を確定させる。
//   - itemsResult に居てオファーあり → alive
//   - itemsResult に居るがオファーなし → dead（「現在お取り扱いできません」ページ相当）
//   - errors で InvalidParameterValue / ItemNotAccessible → dead（ASIN消滅）
//   - API呼び出し自体の失敗 → unknown（安全側: 隔離しない）

function asinOf(url) {
  const m = (url || "").match(/\/dp\/([A-Z0-9]{10})/);
  return m ? m[1] : null;
}

async function verifyAsinsViaApi(asins) {
  const verdicts = new Map();
  for (let i = 0; i < asins.length; i += 10) {
    const batch = asins.slice(i, i + 10);
    try {
      const data = await creatorsApi("/catalog/v1/getItems", {
        itemIds: batch,
        partnerTag: PARTNER_TAG,
        resources: ["itemInfo.title", "offersV2.listings.price"],
      });
      const found = new Map((data.itemsResult?.items || []).map((it) => [it.asin, it]));
      const deadAsins = new Set();
      for (const e of data.errors || []) {
        if (e.code !== "InvalidParameterValue" && e.code !== "ItemNotAccessible") continue;
        const m = (e.message || "").match(/\b([A-Z0-9]{10})\b/);
        if (m && batch.includes(m[1])) deadAsins.add(m[1]);
      }
      for (const asin of batch) {
        const it = found.get(asin);
        if (it) verdicts.set(asin, it.offersV2?.listings?.length ? "alive" : "dead");
        else if (deadAsins.has(asin)) verdicts.set(asin, "dead");
        else verdicts.set(asin, "unknown");
      }
    } catch (err) {
      console.log(`  ⚠️ Creators API getItems 失敗（このバッチは判定不能扱い）: ${err.message}`);
      for (const asin of batch) verdicts.set(asin, "unknown");
    }
    await new Promise((r) => setTimeout(r, 1200)); // レート制限対策
  }
  return verdicts;
}

// ─── 候補スコアリング ─────────────────────────────────

function tokenize(s) {
  return (s || "")
    .toLowerCase()
    .replace(/[（）()【】\[\]「」・/／|,、。.\-]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length >= 2);
}

function scoreCandidate(product, item) {
  const title = item.itemInfo?.title?.displayValue || "";
  const brandInfo = item.itemInfo?.byLineInfo?.brand?.displayValue || "";
  const pTokens = tokenize(product.name);
  const tTokens = new Set(tokenize(title + " " + brandInfo));
  if (pTokens.length === 0) return 0;
  const overlap = pTokens.filter((t) => tTokens.has(t)).length / pTokens.length;
  const brandOk = product.brand
    ? tokenize(title + " " + brandInfo).some((t) => tokenize(product.brand).includes(t))
    : true;
  return overlap * (brandOk ? 1 : 0.5);
}

// ─── メイン ───────────────────────────────────────────

async function main() {
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.log(`[link-fix] Kill Switch 有効 — 停止 (${ks.reason})`);
    return;
  }

  const reportPath = path.join(DATA_DIR, "link-check-report.json");
  if (!fs.existsSync(reportPath)) {
    console.log("[link-fix] link-check-report.json がありません。先に check:links を実行してください。");
    return;
  }
  const report = JSON.parse(fs.readFileSync(reportPath, "utf-8"));
  const broken = report.broken || [];
  if (broken.length === 0) {
    console.log("[link-fix] リンク切れ0件。何もしません。");
    return;
  }

  console.log(`[link-fix] 開始${DRY_RUN ? " [DRY RUN]" : ""} — 再検証対象 ${broken.length} 件 / Creators API: ${HAS_API ? "あり" : "なし（検索リンクのみ提案）"}`);

  const products = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "products.json"), "utf-8"));
  const byId = new Map(products.map((p) => [p.id, p]));

  const falsePositives = [];
  const unknown = [];
  const quarantined = [];

  // 1a. Creators API getItems で一括判定（CAPTCHAの影響を受けない正規ルート）
  let apiVerdicts = new Map();
  if (HAS_API) {
    const asins = [
      ...new Set(
        broken
          .filter((b) => byId.get(b.id)?.amazonUrl)
          .map((b) => asinOf(b.url))
          .filter(Boolean)
      ),
    ];
    if (asins.length > 0) {
      console.log(`[link-fix] Creators API getItems で ${asins.length} ASIN を照会します...`);
      apiVerdicts = await verifyAsinsViaApi(asins);
    }
  }

  // 1b. 再検証（API判定を優先、確定しなかったものだけHTTPで再確認）
  for (const item of broken) {
    const product = byId.get(item.id);
    if (!product) { console.log(`  ⏭️ 商品なし: ${item.id}`); continue; }
    if (!product.amazonUrl) { console.log(`  ⏭️ 既に隔離済み: ${item.id}`); continue; }

    const asin = asinOf(item.url);
    let verdict = asin ? apiVerdicts.get(asin) : undefined;
    let source = "Creators API";
    if (verdict !== "alive" && verdict !== "dead") {
      const result = await checkUrl(item.url);
      verdict = result.verdict;
      source = "HTTP";
      await new Promise((r) => setTimeout(r, 1200));
    }

    if (verdict === "alive") {
      falsePositives.push({ id: item.id, name: item.name, url: item.url });
      console.log(`  ✅ 誤検知（${source}で生存確認）: ${item.name.slice(0, 30)}`);
    } else if (verdict === "unknown") {
      unknown.push({ id: item.id, name: item.name, url: item.url });
      console.log(`  ❓ 判定不能（隔離しない）: ${item.name.slice(0, 30)}`);
    } else {
      quarantined.push({ id: item.id, name: item.name, url: item.url });
      console.log(`  🔴 死亡確定（${source}） → 隔離: ${item.name.slice(0, 30)}`);
    }
  }

  // 2. 隔離: amazonUrl を空に（サイトは楽天ボタンだけ残る）
  const now = new Date().toISOString();
  const proposals = [];
  for (const q of quarantined) {
    const product = byId.get(q.id);
    if (!DRY_RUN) {
      product.amazonUrl = "";
      product.updatedAt = now; // pull時のマージ巻き戻し防止
    }

    // 3. 代替候補の検索
    let candidate = null;
    let confidence = 0;
    if (HAS_API) {
      try {
        const items = await searchItems(`${product.brand || ""} ${product.name}`.trim());
        let best = null;
        let bestScore = 0;
        for (const it of items) {
          const s = scoreCandidate(product, it);
          if (s > bestScore) { bestScore = s; best = it; }
        }
        if (best && bestScore >= 0.35) {
          candidate = {
            asin: best.asin,
            title: best.itemInfo?.title?.displayValue || "",
            price: best.offersV2?.listings?.[0]?.price?.money?.amount ?? null,
            url: `https://www.amazon.co.jp/dp/${best.asin}?tag=${PARTNER_TAG}`,
          };
          confidence = Math.round(bestScore * 100);
        }
        await new Promise((r) => setTimeout(r, 1200)); // レート制限対策
      } catch (err) {
        console.log(`  ⚠️ 候補検索失敗 (${q.id}): ${err.message}`);
      }
    }

    proposals.push({
      id: q.id,
      name: q.name,
      brand: product.brand || "",
      oldUrl: q.url,
      quarantinedAt: now,
      candidate,
      confidence,
      searchUrl: `https://www.amazon.co.jp/s?k=${encodeURIComponent(`${product.brand || ""} ${product.name}`.trim())}`,
    });
  }

  // 4. 書き出し
  const proposalsPath = path.join(DATA_DIR, "link-fix-proposals.json");
  const out = {
    generatedAt: now,
    reportCheckedAt: report.checkedAt || "",
    quarantined: proposals,
    falsePositives,
    unknown,
  };
  if (DRY_RUN) {
    console.log("\n[DRY RUN] 書き込みスキップ。提案内容:");
    console.log(JSON.stringify(out, null, 2).slice(0, 2000));
    return;
  }
  fs.writeFileSync(path.join(DATA_DIR, "products.json"), JSON.stringify(products, null, 2) + "\n", "utf-8");
  fs.writeFileSync(proposalsPath, JSON.stringify(out, null, 2) + "\n", "utf-8");
  console.log(`\n[link-fix] 隔離 ${quarantined.length} 件 / 誤検知復帰 ${falsePositives.length} 件 / 判定不能 ${unknown.length} 件 / 候補あり ${proposals.filter((p) => p.candidate).length} 件`);

  // 5. Supabase同期（隔離をサイトに即反映）
  if (quarantined.length > 0) {
    try {
      console.log("[link-fix] Supabaseへ同期します...");
      execSync("node --dns-result-order=ipv4first scripts/sync-to-supabase.js", { stdio: "inherit", cwd: ROOT });
    } catch (err) {
      console.error("[link-fix] Supabase同期失敗（次回db:syncで反映されます）:", err.message);
    }
  }

  // 6. git commit + push（本番管理画面に提案を届ける）
  if (!NO_PUSH) {
    try {
      execSync("git add data/products.json data/link-fix-proposals.json", { cwd: ROOT });
      execSync(
        `git commit -m "data: link-fix 週次実行（隔離${quarantined.length}件・候補${proposals.filter((p) => p.candidate).length}件）"`,
        { cwd: ROOT }
      );
      execSync("git push", { cwd: ROOT, stdio: "inherit" });
      console.log("[link-fix] git push 完了");
    } catch {
      console.log("[link-fix] git commit/push スキップ（変更なし or 失敗。手動で反映してください）");
    }
  }
}

main().catch((err) => {
  console.error("[link-fix] エラー:", err.message);
  process.exit(1);
});
