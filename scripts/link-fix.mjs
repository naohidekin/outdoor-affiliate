#!/usr/bin/env node

/**
 * リンク切れ自動修復パイプライン（link-check の後段。日曜 7:00）
 *
 * 思想: 「害の除去は全自動、商品の差し替えだけ人間の1クリック承認」
 *  1. link-check-report.json の broken を再検証（CAPTCHA等の誤検知を除去）
 *  2. 死亡確定リンクは amazonUrl を自動で空に = 隔離
 *     （サイトでは楽天ボタンだけ残る。壊れリンクの露出を即座に止める）
 *  3. PA-APIキーがあれば代替候補を自動検索し、提案ファイルに書き出す
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
import crypto from "crypto";
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

const ACCESS_KEY = process.env.AMAZON_ACCESS_KEY;
const SECRET_KEY = process.env.AMAZON_SECRET_KEY;
const PARTNER_TAG = process.env.AMAZON_PARTNER_TAG || "camp78-22";
const HAS_PAAPI = Boolean(ACCESS_KEY && SECRET_KEY);

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

// ─── PA-API v5 SearchItems（price-monitor.js と同じ署名方式） ───────

const HOST = "webservices.amazon.co.jp";
const REGION = "us-west-2";
const SERVICE = "ProductAdvertisingAPI";

function hmacSha256(key, data) {
  return crypto.createHmac("sha256", key).update(data).digest();
}
function sha256hex(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}
function getSignatureKey(key, dateStamp) {
  const kDate = hmacSha256("AWS4" + key, dateStamp);
  const kRegion = hmacSha256(kDate, REGION);
  const kService = hmacSha256(kRegion, SERVICE);
  return hmacSha256(kService, "aws4_request");
}

async function searchItems(keywords) {
  const operation = "SearchItems";
  const apiPath = "/paapi5/searchitems";
  const payload = {
    Keywords: keywords.slice(0, 100),
    SearchIndex: "All",
    ItemCount: 5,
    PartnerTag: PARTNER_TAG,
    PartnerType: "Associates",
    Marketplace: "www.amazon.co.jp",
    Resources: ["ItemInfo.Title", "ItemInfo.ByLineInfo", "Offers.Listings.Price"],
  };
  const body = JSON.stringify(payload);
  const now = new Date();
  const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const dateStamp = amzDate.slice(0, 8);
  const headers = {
    "content-encoding": "amz-1.0",
    "content-type": "application/json; charset=utf-8",
    host: HOST,
    "x-amz-date": amzDate,
    "x-amz-target": `com.amazon.paapi5.v1.ProductAdvertisingAPIv1.${operation}`,
  };
  const signedHeaders = Object.keys(headers).sort().join(";");
  const canonicalHeaders = Object.keys(headers).sort().map((k) => `${k}:${headers[k]}`).join("\n");
  const canonicalRequest = ["POST", apiPath, "", canonicalHeaders + "\n", signedHeaders, sha256hex(body)].join("\n");
  const credentialScope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const stringToSign = ["AWS4-HMAC-SHA256", amzDate, credentialScope, sha256hex(canonicalRequest)].join("\n");
  const signature = crypto.createHmac("sha256", getSignatureKey(SECRET_KEY, dateStamp)).update(stringToSign).digest("hex");
  const authHeader = `AWS4-HMAC-SHA256 Credential=${ACCESS_KEY}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;

  const res = await fetch(`https://${HOST}${apiPath}`, {
    method: "POST",
    headers: { ...headers, Authorization: authHeader },
    body,
  });
  if (!res.ok) throw new Error(`PA-API ${res.status}`);
  const data = await res.json();
  return data.SearchResult?.Items || [];
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
  const title = item.ItemInfo?.Title?.DisplayValue || "";
  const brandInfo = item.ItemInfo?.ByLineInfo?.Brand?.DisplayValue || "";
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

  console.log(`[link-fix] 開始${DRY_RUN ? " [DRY RUN]" : ""} — 再検証対象 ${broken.length} 件 / PA-API: ${HAS_PAAPI ? "あり" : "なし（検索リンクのみ提案）"}`);

  const products = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "products.json"), "utf-8"));
  const byId = new Map(products.map((p) => [p.id, p]));

  const falsePositives = [];
  const unknown = [];
  const quarantined = [];

  // 1. 再検証（1.2秒間隔）
  for (const item of broken) {
    const product = byId.get(item.id);
    if (!product) { console.log(`  ⏭️ 商品なし: ${item.id}`); continue; }
    if (!product.amazonUrl) { console.log(`  ⏭️ 既に隔離済み: ${item.id}`); continue; }

    const result = await checkUrl(item.url);
    if (result.verdict === "alive") {
      falsePositives.push({ id: item.id, name: item.name, url: item.url });
      console.log(`  ✅ 誤検知（生存確認）: ${item.name.slice(0, 30)}`);
    } else if (result.verdict === "unknown") {
      unknown.push({ id: item.id, name: item.name, url: item.url });
      console.log(`  ❓ 判定不能（隔離しない）: ${item.name.slice(0, 30)}`);
    } else {
      quarantined.push({ id: item.id, name: item.name, url: item.url });
      console.log(`  🔴 死亡確定 → 隔離: ${item.name.slice(0, 30)}`);
    }
    await new Promise((r) => setTimeout(r, 1200));
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
    if (HAS_PAAPI) {
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
            asin: best.ASIN,
            title: best.ItemInfo?.Title?.DisplayValue || "",
            price: best.Offers?.Listings?.[0]?.Price?.Amount ?? null,
            url: `https://www.amazon.co.jp/dp/${best.ASIN}?tag=${PARTNER_TAG}`,
          };
          confidence = Math.round(bestScore * 100);
        }
        await new Promise((r) => setTimeout(r, 1200)); // PA-APIレート制限
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
