#!/usr/bin/env node
/**
 * 登録済みリンクが本当にその商品を指しているかを全件検証する
 *
 * 背景（2026-08-13）: 価格監査のついでにタイトル照合をしたら、
 * リンクが別商品を指している例が9件出た。読者は犬用ブラシや
 * UGGのムートンブーツのページに着地していた。
 *
 * 原因は型番照合の2つの穴で、どちらも「型番一致＝信頼度・高」として
 * 自動適用されるため目視をすり抜けていた:
 *   REF-025 が REF-0254 に前方一致（数字が伸びると別品番）
 *   シャツの品番 LFTG-BD-190 から BD-190 を切り出して完全一致
 * 両方とも修正済みだが、修正前に入ったリンクはそのまま残っている。
 * 価格監査は「価格がある商品」しか見ていないので、ここで全件を洗う。
 *
 * 判定はストア側のタイトルと商品名の突き合わせ。閾値は低めにして
 * 拾いすぎない側に倒し、最終判断は人間に任せる（これは選別であって断定ではない）。
 *
 * 優先度はクリック実績で付ける。同じ誤リンクでも、
 * 実際に押されているものほど損失が大きい。
 *
 * 使い方（Macで実行。Amazon Creators API と楽天API・IP許可が必要）:
 *   node scripts/verify-links.mjs              # 全件
 *   node scripts/verify-links.mjs --clicked    # クリック実績のある商品だけ（速い）
 *   node scripts/verify-links.mjs --limit 50
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { creatorsApi, credentials, hasCredentials, asinOf } from "../src/lib/amazon-creators-api.mjs";
import {
  tokenOverlap,
  sanitizeKeyword,
  modelNumbers,
  normalizeBrands,
  brandMatches,
} from "../src/lib/product-match.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const OUT = path.join(ROOT, "scratch", "link-verification.json");

const argv = process.argv.slice(2);
const CLICKED_ONLY = argv.includes("--clicked");
const li = argv.indexOf("--limit");
const LIMIT = li !== -1 ? parseInt(argv[li + 1], 10) || Infinity : Infinity;

const RAKUTEN_API = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
const appId = process.env.RAKUTEN_APP_ID;
const accessKey = process.env.RAKUTEN_ACCESS_KEY;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const decode = (s) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

function rakutenRef(url) {
  const m = decode(url || "").match(/item\.rakuten\.co\.jp\/([^/]+)\/([^/?&]+)/);
  return m ? { shopCode: m[1], urlCode: m[2] } : null;
}

let rakutenAuthFailures = 0;
let rakutenItemErrors = 0;
async function rakutenTitle(ref, productName) {
  if (!appId || rakutenAuthFailures >= 5) return null;
  const attempt = async (keyword) => {
    const params = new URLSearchParams({
      applicationId: appId,
      ...(accessKey ? { accessKey } : {}),
      shopCode: ref.shopCode,
      keyword: sanitizeKeyword(keyword).slice(0, 100),
      hits: "30",
      format: "json",
      formatVersion: "2",
    });
    const res = await fetch(`${RAKUTEN_API}?${params}`, {
      headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
    });
    if (res.status === 429) {
      await sleep(1600);
      return null;
    }
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      if (/CLIENT_IP_NOT_ALLOWED/.test(body) || res.status === 401 || res.status === 403) {
        if (++rakutenAuthFailures === 5)
          console.warn("\n  楽天がIP制限で拒否。以降はAmazonのみで検証します\n");
      } else if (++rakutenItemErrors <= 3) {
        console.warn(`\n  楽天API ${res.status}（${ref.shopCode}）: ${body.slice(0, 100)}`);
      }
      return null;
    }
    const data = await res.json();
    const hit = (data.Items || []).find((it) =>
      decode(it.itemUrl || "").includes(`/${ref.urlCode}`)
    );
    return hit ? hit.itemName : null;
  };
  const first = await attempt(productName);
  if (first) return first;
  // 1秒1リクエストの規定を守る。ここは1商品で2回投げる箇所で、
  // 700msだと規定違反になる（2026-08-23に発覚）
  await sleep(1200);
  return attempt(ref.urlCode);
}

/**
 * 商品名とストア側タイトルの一致度。
 * 半角カナを NFKC で正規化し、ブランド表記を正規化し、
 * 型番が独立した語として一致すれば同一とみなす
 * （タイトルが型番だけの出品は一致率が構造的に低くなるため）
 */
function matchScore(productName, storeTitle) {
  const norm = (x) => normalizeBrands((x || "").normalize("NFKC").toLowerCase());
  // 型番は大小文字を潰す前の文字列から拾う
  const rawSrc = (productName || "").normalize("NFKC");
  const raw = rawSrc.match(/[A-Za-z]{1,6}-?[0-9]{2,5}[A-Za-z0-9+/]*/g) || [];
  const titleSrc = (storeTitle || "").normalize("NFKC");
  const modelHit = raw.some((m) => {
    const esc = m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?<![A-Za-z0-9-])${esc}(?![A-Za-z0-9])`, "i").test(titleSrc);
  });
  if (modelHit) return 1;
  return tokenOverlap(norm(productName), norm(storeTitle));
}

// ─── 対象 ────────────────────────────────────────────
const products = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "products.json"), "utf8"));
const articles = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "articles.json"), "utf8"));
let clicks = [];
try {
  clicks = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "affiliate-clicks.json"), "utf8"));
} catch {
  console.warn("affiliate-clicks.json が読めません。優先度はクリック無しで算出します");
}

const since = new Date(Date.now() - 30 * 86400_000).toISOString();
const clickCount = new Map();
for (const c of clicks) {
  if (c.timestamp >= since && c.productId)
    clickCount.set(c.productId, (clickCount.get(c.productId) || 0) + 1);
}
const exposure = new Map();
for (const a of articles) {
  if (a.status !== "published") continue;
  const ids = new Set(a.productIds || []);
  for (const m of (a.content || "").matchAll(/\{\{(?:product|comparison|ranking):([^}|]+)\}\}/g))
    for (const id of m[1].split(",")) ids.add(id.trim());
  for (const id of ids) exposure.set(id, (exposure.get(id) || 0) + 1);
}

let targets = products.filter((p) => asinOf(p.amazonUrl) || rakutenRef(p.affiliateUrl));
if (CLICKED_ONLY) targets = targets.filter((p) => clickCount.get(p.id));
targets.sort(
  (a, b) => (clickCount.get(b.id) || 0) - (clickCount.get(a.id) || 0) ||
            (exposure.get(b.id) || 0) - (exposure.get(a.id) || 0)
);
targets = targets.slice(0, LIMIT);

console.log(`リンク検証: ${targets.length}件`);
console.log(`  Amazon ${targets.filter((p) => asinOf(p.amazonUrl)).length}件 / 楽天 ${targets.filter((p) => rakutenRef(p.affiliateUrl)).length}件\n`);

// Amazon は10件ずつ
const amazonTitle = new Map();
if (hasCredentials()) {
  const withAsin = targets.filter((p) => asinOf(p.amazonUrl));
  const tag = credentials().partnerTag;
  for (let i = 0; i < withAsin.length; i += 10) {
    const batch = withAsin.slice(i, i + 10);
    try {
      const data = await creatorsApi("/catalog/v1/getItems", {
        itemIds: batch.map((p) => asinOf(p.amazonUrl)),
        partnerTag: tag,
        resources: ["itemInfo.title"],
      });
      for (const it of data.itemsResult?.items || [])
        amazonTitle.set(it.asin, it.itemInfo?.title?.displayValue || "");
    } catch (e) {
      console.warn(`  Amazonバッチ${Math.floor(i / 10) + 1}失敗: ${String(e.message).slice(0, 60)}`);
    }
    process.stdout.write(`\r  Amazon ${Math.min(i + 10, withAsin.length)}/${withAsin.length}`);
    if (i + 10 < withAsin.length) await sleep(3000);
  }
  console.log("");
}

const suspects = [];
let checked = 0;
let done = 0;
for (const p of targets) {
  const asin = asinOf(p.amazonUrl);
  const ref = rakutenRef(p.affiliateUrl);
  const aTitle = asin ? amazonTitle.get(asin) : null;
  let rTitle = null;
  if (ref) {
    rTitle = await rakutenTitle(ref, p.name);
    await sleep(1100);
  }
  done++;
  process.stdout.write(`\r  楽天 ${done}/${targets.length}`);
  if (!aTitle && !rTitle) continue;
  checked++;

  // 一致率が低くても、ブランドが合っていれば誤リンクとは断定しない。
  // 商品名が音訳されているだけのケース（メレル モアブ3 ⇄ MERRELL MOAB 3）を
  // 語の一致率で救うのは無理なので、ブランドを別の軸として見る
  const bad = [];
  const judge = (store, title) => {
    if (!title) return;
    const score = matchScore(p.name, title);
    if (score >= 0.4) return;
    if (brandMatches(p.brand, title)) return;
    bad.push({ store, title, score });
  };
  judge("Amazon", aTitle);
  judge("楽天", rTitle);
  if (bad.length === 0) continue;

  suspects.push({
    id: p.id,
    name: p.name,
    brand: p.brand || "",
    clicks30d: clickCount.get(p.id) || 0,
    articles: exposure.get(p.id) || 0,
    bad,
  });
}
console.log("\n");

suspects.sort((a, b) => b.clicks30d - a.clicks30d || b.articles - a.articles);

console.log(`── 別商品を指している疑い ${suspects.length}件 ──`);
for (const s of suspects) {
  console.log(
    `\n  ${String(s.clicks30d).padStart(3)}クリック/30日  ${s.articles}記事  ${s.id}`
  );
  console.log(`     ${s.name.slice(0, 40)}`);
  for (const b of s.bad)
    console.log(`     ${b.store} 一致${Math.round(b.score * 100)}%  「${b.title.slice(0, 46)}」`);
}

console.log(`\n── まとめ ──`);
console.log(`  検証できた商品: ${checked}件 / 対象 ${targets.length}件`);
console.log(`  別商品の疑い:   ${suspects.length}件`);
const clicked = suspects.filter((s) => s.clicks30d > 0);
console.log(`    うちクリックがあるもの: ${clicked.length}件（合計 ${clicked.reduce((n, s) => n + s.clicks30d, 0)}クリック/30日）`);
if (rakutenAuthFailures >= 5) console.log("  ⚠ 楽天は途中から検証できていません（IP許可リストを確認）");

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ ranAt: new Date().toISOString(), suspects, checked }, null, 2));
console.log(`\nレポート: ${OUT}`);
console.log("直すときは --ids で個別に調べ直してください:");
console.log("  node scripts/fix-search-affiliate-links.mjs --ids <id> --explain");
console.log("  node scripts/fix-amazon-search-links.mjs --ids <id> --explain");
