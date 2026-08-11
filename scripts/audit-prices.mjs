#!/usr/bin/env node
/**
 * 登録価格と実売価格の突き合わせ（両モール）
 *
 * 背景（2026-08-11）: 楽天リンクの照合中、候補は正しいのに「価格乖離」で
 * 落ちるものが続いた。中身を見ると**登録価格のほうが誤っていた**。
 *   スノーピーク アメニティドームS  登録¥44,000 / 公式店の実売¥19,800
 *     （Mサイズの価格がSに入っていると思われる）
 *   タトンカ Tarp 4 TC             登録¥80,233 / 同シリーズTarp 1が¥15,499
 * スクリプトが出す「最有力候補の実売/登録価格の中央値=112%」も、
 * 全体として登録価格が古い方向にずれていることを示していた。
 *
 * 価格が誤っていると二重に損をする:
 *  - サイトに嘘の値段が出る（リンク切れより読者の信頼を削る）
 *  - 価格ゲート（登録価格の60〜200%）が正しい候補を弾き、リンク修復が進まない
 *
 * 実売の取り方は「その商品ページそのもの」を引く。検索で拾い直すと
 * 別商品を掴むので、照合の意味がなくなる。
 *   Amazon … amazonUrl のASIN → Creators API getItems
 *   楽天   … affiliateUrl の item.rakuten.co.jp/{shop}/{code}/ → itemCode で直引き
 *
 * 使い方（Macで実行。両APIの認証情報が必要。楽天はIP許可リストも）:
 *   node scripts/audit-prices.mjs                 # 監査のみ（書き込まない）
 *   node scripts/audit-prices.mjs --limit 50      # 件数を絞って試す
 *   node scripts/audit-prices.mjs --apply         # 確度の高いものだけ登録価格を直す
 *
 * --apply が直すのは「両モールの実売が10%以内で一致し、かつ登録価格から
 * 20%以上ずれている」ものだけ。片方しか取れないものは人間に回す。
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { creatorsApi, credentials, hasCredentials, asinOf } from "../src/lib/amazon-creators-api.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const OUT = path.join(ROOT, "scratch", "price-audit.json");

const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const argVal = (n) => {
  const i = argv.indexOf(n);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : null;
};
const LIMIT = parseInt(argVal("--limit") || "", 10) || Infinity;

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

if (!hasCredentials() && !appId) {
  console.error("Amazon / 楽天いずれの認証情報もありません（.env.local を確認）");
  process.exit(1);
}

/** アフィリエイトURLから楽天の itemCode（shop:code）を取り出す */
function itemCodeOf(affiliateUrl) {
  const m = decode(affiliateUrl || "").match(/item\.rakuten\.co\.jp\/([^/]+)\/([^/?&]+)/);
  return m ? `${m[1]}:${m[2]}` : null;
}

let rakutenFailures = 0;
async function rakutenPrice(itemCode) {
  if (!appId || rakutenFailures >= 5) return null;
  const params = new URLSearchParams({
    applicationId: appId,
    ...(accessKey ? { accessKey } : {}),
    itemCode,
    format: "json",
    formatVersion: "2",
  });
  try {
    const res = await fetch(`${RAKUTEN_API}?${params}`, {
      headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      if (/CLIENT_IP_NOT_ALLOWED|wrong_parameter|401|403/.test(body) || res.status >= 401) {
        if (++rakutenFailures >= 5) {
          console.warn("\n  楽天APIの認証エラーが5回続いたので、以降はAmazonのみで判定します");
          console.warn("  （curl -4 -s ifconfig.me のIPを許可リストに登録してください）\n");
        }
      }
      return null;
    }
    const data = await res.json();
    const it = (data.Items || [])[0];
    return it ? { price: it.itemPrice, name: it.itemName } : null;
  } catch {
    return null;
  }
}

// ─── 本処理 ──────────────────────────────────────────
const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));

// 記事露出。同じ間違いでも読まれている商品ほど実害が大きい
const exposure = new Map();
for (const a of articles) {
  if (a.status !== "published") continue;
  const ids = new Set(a.productIds || []);
  for (const m of (a.content || "").matchAll(/\{\{(?:product|comparison|ranking):([^}|]+)\}\}/g)) {
    for (const id of m[1].split(",")) ids.add(id.trim());
  }
  for (const id of ids) exposure.set(id, (exposure.get(id) || 0) + 1);
}

const targets = products
  .filter((p) => p.price && (asinOf(p.amazonUrl) || itemCodeOf(p.affiliateUrl)))
  .sort((a, b) => (exposure.get(b.id) || 0) - (exposure.get(a.id) || 0))
  .slice(0, LIMIT);

console.log(`価格監査: ${targets.length}件（${APPLY ? "APPLY" : "監査のみ"}）`);
console.log(`  Amazon: ${targets.filter((p) => asinOf(p.amazonUrl)).length}件 / 楽天: ${targets.filter((p) => itemCodeOf(p.affiliateUrl)).length}件\n`);

// Amazon は10件ずつまとめて引ける
const amazonPrice = new Map();
if (hasCredentials()) {
  const withAsin = targets.filter((p) => asinOf(p.amazonUrl));
  const tag = credentials().partnerTag;
  for (let i = 0; i < withAsin.length; i += 10) {
    const batch = withAsin.slice(i, i + 10);
    try {
      const data = await creatorsApi("/catalog/v1/getItems", {
        itemIds: batch.map((p) => asinOf(p.amazonUrl)),
        partnerTag: tag,
        resources: ["itemInfo.title", "offersV2.listings.price"],
      });
      for (const it of data.itemsResult?.items || []) {
        const amount = it.offersV2?.listings?.[0]?.price?.money?.amount;
        if (typeof amount === "number") {
          amazonPrice.set(it.asin, { price: Math.round(amount), name: it.itemInfo?.title?.displayValue || "" });
        }
      }
    } catch (e) {
      console.warn(`  Amazonバッチ${Math.floor(i / 10) + 1}失敗: ${String(e.message).slice(0, 60)}`);
    }
    process.stdout.write(`\r  Amazon ${Math.min(i + 10, withAsin.length)}/${withAsin.length}`);
    if (i + 10 < withAsin.length) await sleep(3000);
  }
  console.log("");
}

// 楽天は1件ずつ。itemCode指定なので確実にその商品ページの値が返る
const results = [];
let done = 0;
for (const p of targets) {
  const asin = asinOf(p.amazonUrl);
  const code = itemCodeOf(p.affiliateUrl);
  const amz = asin ? amazonPrice.get(asin) : null;
  let rak = null;
  if (code) {
    rak = await rakutenPrice(code);
    await sleep(1100); // 楽天は毎秒1リクエストが目安
  }
  done++;
  process.stdout.write(`\r  楽天 ${done}/${targets.length}`);
  if (!amz && !rak) continue;

  const prices = [amz?.price, rak?.price].filter((x) => typeof x === "number" && x > 0);
  const market = Math.round(prices.reduce((a, b) => a + b, 0) / prices.length);
  const ratio = market / p.price;
  // 両モールが互いに10%以内なら市場価格として信頼できる
  const agree =
    prices.length === 2 && Math.abs(prices[0] - prices[1]) / Math.max(...prices) <= 0.1;

  results.push({
    id: p.id,
    name: p.name,
    exposure: exposure.get(p.id) || 0,
    registered: p.price,
    amazon: amz?.price ?? null,
    rakuten: rak?.price ?? null,
    market,
    ratio: Math.round(ratio * 100),
    agree,
    sources: prices.length,
  });
}
console.log("\n");

// ─── 出力 ───────────────────────────────────────────
const off = (r) => Math.abs(r.ratio - 100);
const suspicious = results.filter((r) => off(r) >= 20).sort((a, b) => b.exposure - a.exposure || off(b) - off(a));
const confident = suspicious.filter((r) => r.agree);
const single = suspicious.filter((r) => !r.agree);

const fmt = (r) =>
  `  ${String(r.exposure).padStart(2)}記事  ${r.id.padEnd(30)} ${r.name.slice(0, 26).padEnd(28)}\n` +
  `          登録¥${String(r.registered).padStart(7)}  →  実売¥${String(r.market).padStart(7)}（${r.ratio}%）` +
  `  Amazon:${r.amazon ? "¥" + r.amazon : "—"} 楽天:${r.rakuten ? "¥" + r.rakuten : "—"}`;

console.log(`── 両モールが一致して登録価格とずれる ${confident.length}件（確度が高い）──`);
for (const r of confident) console.log(fmt(r));

console.log(`\n── 片方しか取れない / 両モールが割れる ${single.length}件（要目視）──`);
for (const r of single.slice(0, 25)) console.log(fmt(r));
if (single.length > 25) console.log(`  … 他${single.length - 25}件（レポート参照）`);

const ratios = results.map((r) => r.ratio).sort((a, b) => a - b);
console.log(`\n── まとめ ──`);
console.log(`  照合できた商品: ${results.length}件`);
console.log(`  実売/登録 の中央値: ${ratios[Math.floor(ratios.length / 2)]}%`);
console.log(`  20%以上ずれ: ${suspicious.length}件（うち両モール一致 ${confident.length}件）`);

if (APPLY) {
  const ts = new Date().toISOString();
  const byId = new Map(products.map((p) => [p.id, p]));
  let n = 0;
  for (const r of confident) {
    const p = byId.get(r.id);
    if (!p) continue;
    console.log(`  ¥${p.price} → ¥${r.market}  ${p.name.slice(0, 34)}`);
    p.price = r.market;
    p.updatedAt = ts; // 進めないと同期のauto-pullで巻き戻る
    n++;
  }
  fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
  console.log(`\nproducts.json 反映: ${n}件（両モール一致分のみ）`);
  console.log("次: git diff で確認 → npm run db:sync -- --no-pull");
} else {
  console.log("\n適用: --apply … 両モールが一致した分だけ登録価格を直します");
}

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ ranAt: new Date().toISOString(), results, confident, single }, null, 2));
console.log(`レポート: ${OUT}`);
