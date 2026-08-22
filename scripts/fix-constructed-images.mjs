#!/usr/bin/env node
/**
 * ASINから組み立てた画像URLを、正規の経路で取得した画像に差し替える
 *
 * 背景（2026-08-22）: 姉妹サイト japan-shop-helper.com のAmazonアソシエイトが
 * 「Amazon画像の無許可使用」を理由の1つとして閉鎖された。
 *
 * camp-gear-lab には m.media-amazon.com/images/P/{ASIN}... 形式の画像が34件ある。
 * これは scripts/fix-product-images.js:27 が ASIN から機械的に組み立てたもので、
 *   `https://m.media-amazon.com/images/P/${asin}.01._SCLZZZZZZZ_SX300_.jpg`
 * API が提供した画像URLではない。「API経由で取得した」と主張できない形なので、
 * 監査で最も指摘されやすい。
 *
 * 差し替え先の優先順位は CLAUDE.md の「商品画像」ルールに合わせる:
 *   1. 同じ商品が別IDで登録されていて、そちらがメーカー公式画像を持つ場合はそれを流用
 *   2. 楽天APIで商品ページの画像を引く（27/34件は楽天リンクを持っている）
 *   3. どちらも取れなければ空にする（誤った画像を出すより無い方がまし）
 *
 * Amazon Creators API の images.primary.large も規約上は正しい経路だが、
 * Amazon依存を減らす方針（2026-08-22 決定）により既定では使わない。
 * --allow-amazon を付けたときだけ最後の手段として使う。
 *
 * 楽天の出品者画像（thumbnail.image.rakuten.co.jp）はバッジやセール文言が
 * 入っていることがあり、CLAUDE.md では画質が悪いものとして扱っている。
 * クリーンな画像（shop.r10s.jp 等）があればそちらを優先する。
 *
 * 使い方（Macで実行。楽天APIとIP許可リストが要る）:
 *   node scripts/fix-constructed-images.mjs               # 差し替え案を表示
 *   node scripts/fix-constructed-images.mjs --apply
 *   node scripts/fix-constructed-images.mjs --allow-amazon --apply
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { sanitizeKeyword } from "../src/lib/product-match.mjs";
import { getItems, hasCredentials, asinOf } from "../src/lib/amazon-creators-api.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const ALLOW_AMAZON = argv.includes("--allow-amazon");

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

const CONSTRUCTED = /m\.media-amazon\.com\/images\/P\//;
/** バッジやセール文言が乗りやすい出品者画像。無いよりはましだが優先度は下げる */
const LOW_QUALITY = /thumbnail\.image\.rakuten\.co\.jp/;

function rakutenRef(url) {
  const m = decode(url || "").match(/item\.rakuten\.co\.jp\/([^/]+)\/([^/?&]+)/);
  return m ? { shopCode: m[1], urlCode: m[2] } : null;
}

let rakutenAuthFailures = 0;
let rakutenItemErrors = 0;

/** その商品ページの画像を引く。店舗内検索して itemUrl 一致で拾う */
async function rakutenImage(ref, productName) {
  if (!appId || rakutenAuthFailures >= 3) return null;
  const params = new URLSearchParams({
    applicationId: appId,
    ...(accessKey ? { accessKey } : {}),
    shopCode: ref.shopCode,
    keyword: sanitizeKeyword(productName).slice(0, 100),
    hits: "30",
    format: "json",
    formatVersion: "2",
  });
  let res;
  try {
    res = await fetch(`${RAKUTEN_API}?${params}`, {
      headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
    });
  } catch {
    return null;
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    // 設定の問題は店舗をまたいで全部落ちる。商品固有のエラーと混ぜない
    // （2026-08-16 に "API Configuration not found" を520件握り潰した）
    const isConfig =
      /CLIENT_IP_NOT_ALLOWED|API Configuration not found|invalid.*applicationId/i.test(body) ||
      res.status === 401 ||
      res.status === 403;
    if (isConfig) {
      if (++rakutenAuthFailures === 1)
        console.warn(`\n  ⚠ 楽天APIの設定エラー: ${body.slice(0, 120)}`);
      if (rakutenAuthFailures >= 3)
        console.warn("  楽天は使えません。アプリ設定とIP許可リストを確認してください\n");
    } else if (++rakutenItemErrors <= 3) {
      console.warn(`\n  楽天API ${res.status}（${ref.shopCode}）: ${body.slice(0, 90)}  ← この商品のみスキップ`);
    }
    return null;
  }
  const data = await res.json().catch(() => null);
  const hit = (data?.Items || []).find((it) => decode(it.itemUrl || "").includes(`/${ref.urlCode}`));
  if (!hit) return null;
  const urls = [
    ...(hit.mediumImageUrls || []),
    ...(hit.smallImageUrls || []),
  ].map((u) => (typeof u === "string" ? u : u?.imageUrl)).filter(Boolean);
  if (!urls.length) return null;
  // クリーンな画像を優先し、無ければ出品者画像で妥協する
  const clean = urls.find((u) => !LOW_QUALITY.test(u));
  return (clean || urls[0]).replace(/\?_ex=\d+x\d+$/, "");
}

/**
 * Creators API が提供する画像URL。組み立てではなくAPIの応答をそのまま使う。
 * 1件ずつ引くので遅いが、ここに来るのは数件のはず
 */
const amazonImageCache = new Map();
async function amazonImage(asin) {
  if (amazonImageCache.has(asin)) return amazonImageCache.get(asin);
  let url = null;
  try {
    const { items } = await getItems([asin], { resources: ["images.primary.large"] });
    url = items[0]?.images?.primary?.large?.url || null;
  } catch (e) {
    console.warn(`  Creators API 失敗（${asin}）: ${String(e.message).slice(0, 60)}`);
  }
  amazonImageCache.set(asin, url);
  await sleep(1100);
  return url;
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const targets = products.filter((p) => CONSTRUCTED.test(p.imageUrl || ""));
const norm = (s) => (s || "").normalize("NFKC").toLowerCase().replace(/[\s　・]/g, "");

console.log(`ASINから組み立てた画像: ${targets.length}件`);
console.log(`  楽天リンクあり: ${targets.filter((p) => rakutenRef(p.affiliateUrl)).length}件\n`);

const results = [];
for (const p of targets) {
  // ① 同じ商品が別IDで登録されていて、そちらが正規の画像を持っていれば流用
  const twin = products.find(
    (q) => q.id !== p.id && norm(q.name) === norm(p.name) && q.imageUrl && !CONSTRUCTED.test(q.imageUrl)
  );
  if (twin) {
    results.push({ p, url: twin.imageUrl, source: `同一商品 ${twin.id} から流用` });
    continue;
  }

  // ② 楽天APIで商品ページの画像を引く
  const ref = rakutenRef(p.affiliateUrl);
  if (ref) {
    const url = await rakutenImage(ref, p.name);
    await sleep(1100); // 楽天は毎秒1リクエストが目安
    if (url) {
      results.push({
        p,
        url,
        source: LOW_QUALITY.test(url) ? "楽天（出品者画像・画質注意）" : "楽天",
      });
      continue;
    }
  }

  // ③ 最後の手段として Creators API の画像。規約上は正しい経路だが、
  //    Amazon依存を減らす方針なので明示的に許可されたときだけ使う
  if (ALLOW_AMAZON && hasCredentials() && asinOf(p.amazonUrl)) {
    const url = await amazonImage(asinOf(p.amazonUrl));
    if (url) {
      results.push({ p, url, source: "Creators API（--allow-amazon）" });
      continue;
    }
  }

  // ④ 取れなければ空にする。誤った画像を出すより無い方がまし
  results.push({ p, url: "", source: "取得できず → 空にする" });
}

// 差し替え元ごとにまとめて出す。
// 件数が多い変換は種類ごとに実物を見ないと、壊れ方に気づけない
const bySource = new Map();
for (const r of results) {
  const key = r.source.replace(/同一商品 \S+ から流用/, "同一商品から流用");
  if (!bySource.has(key)) bySource.set(key, []);
  bySource.get(key).push(r);
}
for (const [source, list] of bySource) {
  console.log(`\n──── ${source}（${list.length}件）────`);
  for (const r of list) {
    console.log(`  ${r.p.id.padEnd(30)} ${r.p.name.slice(0, 26)}`);
    console.log(`    − ${r.p.imageUrl.slice(0, 86)}`);
    console.log(`    ＋ ${r.url ? r.url.slice(0, 86) : "（画像なし）"}`);
  }
}

const filled = results.filter((r) => r.url).length;
console.log(`\n── まとめ ──`);
console.log(`  差し替え: ${filled}件 / 空にする: ${results.length - filled}件`);
if (rakutenAuthFailures >= 3) {
  console.log(`\n  🛑 楽天APIが使えていません。この結果で --apply すると、`);
  console.log(`     本来は画像を引けたはずの商品まで空になります。復旧後に流し直してください。`);
}

if (!APPLY) {
  console.log("\n書き込むには --apply");
  process.exit(0);
}
if (rakutenAuthFailures >= 3) {
  console.error("\n楽天APIが使えていないので中止します（--apply は復旧後に）");
  process.exit(1);
}

const ts = new Date().toISOString();
for (const r of results) {
  r.p.imageUrl = r.url;
  r.p.updatedAt = ts; // pull時のマージ巻き戻し防止
}
fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
console.log(`\ndata/products.json を更新しました（${results.length}件）`);
console.log("反映: npm run db:sync -- --no-pull");
