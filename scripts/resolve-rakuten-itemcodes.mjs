#!/usr/bin/env node
/**
 * 楽天の itemCode を一度だけ解決して products.json に保存する
 *
 * 背景（2026-08-23）: 楽天APIを叩くたびに shopCode + キーワード検索で
 * 商品を探し直している。392件を1秒制限で舐めると約6分半かかり、しかも
 * キーワード検索なので毎回取り違えの可能性を抱える。
 *
 * 2026-08-11 に itemCode 直引きが全件 400 になったので「itemCode は使えない」
 * と記録したが、これは一般化しすぎだった。落ちた原因は
 *   item.rakuten.co.jp/{shopCode}/{urlCode}/ の urlCode を itemCode として
 *   渡していた
 * ことで、両者は別物である。**正しい itemCode を持っていれば直引きは有効**。
 *
 * そこで、キーワード検索で一度解決したときにAPIが返す本物の itemCode を
 * products.json に保存する。以降は直引きに切り替えられる。
 *
 * ただし「保存すれば直引きが動く」も未検証の仮定なので、--verify で
 * 実際に itemCode 引きが通るかを数件試せるようにしてある。
 * 通ることを確認してから、他スクリプトを直引きに移す。
 *
 * 使い方（Macで実行。楽天APIとIP許可リストが要る）:
 *   node scripts/resolve-rakuten-itemcodes.mjs              # 解決して表示
 *   node scripts/resolve-rakuten-itemcodes.mjs --apply      # products.json に保存
 *   node scripts/resolve-rakuten-itemcodes.mjs --verify     # 直引きが通るか5件で確認
 *   node scripts/resolve-rakuten-itemcodes.mjs --limit 20
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { sanitizeKeyword } from "../src/lib/product-match.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const VERIFY = argv.includes("--verify");
const li = argv.indexOf("--limit");
const LIMIT = li !== -1 ? parseInt(argv[li + 1], 10) || Infinity : Infinity;

const API = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701";
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

if (!appId) {
  console.error("RAKUTEN_APP_ID がありません（.env.local を確認）");
  process.exit(1);
}

function rakutenRef(url) {
  const m = decode(url || "").match(/item\.rakuten\.co\.jp\/([^/]+)\/([^/?&]+)/);
  return m ? { shopCode: m[1], urlCode: m[2] } : null;
}

let configErrors = 0;
let itemErrors = 0;

/** 設定の問題（IP制限・アプリID不正）は店舗をまたいで全部落ちる。商品固有と混ぜない */
function classify(status, body) {
  return /CLIENT_IP_NOT_ALLOWED|API Configuration not found|invalid.*applicationId/i.test(body) ||
    status === 401 ||
    status === 403
    ? "config"
    : "item";
}

async function call(params) {
  const res = await fetch(`${API}?${params}`, {
    headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
  });
  if (res.status === 429) {
    await sleep(1600);
    return call(params);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    const kind = classify(res.status, body);
    if (kind === "config") {
      if (++configErrors === 1) console.warn(`\n  ⚠ 楽天APIの設定エラー: ${body.slice(0, 130)}`);
    } else if (++itemErrors <= 3) {
      console.warn(`\n  楽天API ${res.status}: ${body.slice(0, 90)}  ← この商品のみスキップ`);
    }
    return null;
  }
  return res.json().catch(() => null);
}

/** キーワード検索で解決し、APIが返す本物の itemCode を取る */
async function resolveItemCode(ref, productName) {
  const params = new URLSearchParams({
    applicationId: appId,
    ...(accessKey ? { accessKey } : {}),
    shopCode: ref.shopCode,
    keyword: sanitizeKeyword(productName).slice(0, 100),
    hits: "30",
    format: "json",
    formatVersion: "2",
    // itemCode を確実に受け取る。elements で絞ると転送量も減る
    elements: "itemCode,itemName,itemUrl,itemPrice",
  });
  const data = await call(params);
  if (!data) return null;
  const hit = (data.Items || []).find((it) => decode(it.itemUrl || "").includes(`/${ref.urlCode}`));
  return hit ? { itemCode: hit.itemCode, name: hit.itemName, price: hit.itemPrice } : null;
}

/** 保存した itemCode で直引きできるかを確かめる */
async function verifyItemCode(itemCode) {
  const params = new URLSearchParams({
    applicationId: appId,
    ...(accessKey ? { accessKey } : {}),
    itemCode,
    format: "json",
    formatVersion: "2",
    elements: "itemCode,itemName,itemPrice",
  });
  const data = await call(params);
  const hit = (data?.Items || [])[0];
  return hit ? { name: hit.itemName, price: hit.itemPrice } : null;
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));

// ─── --verify: 保存済みの itemCode で直引きを試す ───
if (VERIFY) {
  const saved = products.filter((p) => p.rakutenItemCode).slice(0, 5);
  if (!saved.length) {
    console.error("保存済みの itemCode がありません。先に --apply してください");
    process.exit(1);
  }
  console.log(`itemCode 直引きの検証（${saved.length}件）\n`);
  let ok = 0;
  for (const p of saved) {
    const r = await verifyItemCode(p.rakutenItemCode);
    console.log(`  ${r ? "✅" : "✗ "} ${p.id.padEnd(28)} ${p.rakutenItemCode}`);
    if (r) {
      ok++;
      console.log(`       → ¥${r.price}  ${String(r.name).slice(0, 52)}`);
    }
    await sleep(1100);
  }
  console.log(`\n  ${ok}/${saved.length}件 成功`);
  console.log(
    ok === saved.length
      ? "  直引きが使えます。他スクリプトをキーワード検索から切り替えられます"
      : "  直引きは信頼できません。キーワード検索方式を維持してください"
  );
  process.exit(0);
}

// ─── 解決 ───
const targets = products
  .filter((p) => rakutenRef(p.affiliateUrl) && !p.rakutenItemCode)
  .slice(0, LIMIT);

console.log(`楽天 itemCode の解決: ${targets.length}件`);
console.log(`  （保存済みで対象外: ${products.filter((p) => p.rakutenItemCode).length}件）\n`);

const resolved = [];
let done = 0;
for (const p of targets) {
  if (configErrors > 0) break; // 設定エラーなら以降も全部落ちる。空振りを続けない
  const ref = rakutenRef(p.affiliateUrl);
  const r = await resolveItemCode(ref, p.name);
  done++;
  process.stdout.write(`\r  ${done}/${targets.length}`);
  if (r) resolved.push({ p, ...r });
  await sleep(1100);
}
console.log("\n");

for (const r of resolved.slice(0, 20)) {
  console.log(`  ${r.p.id.padEnd(28)} ${r.itemCode}`);
  console.log(`     ${String(r.name).slice(0, 62)}`);
}
if (resolved.length > 20) console.log(`  … 他${resolved.length - 20}件`);

console.log(`\n── まとめ ──`);
console.log(`  解決: ${resolved.length}件 / 対象 ${targets.length}件`);
if (configErrors > 0) {
  console.log(`\n  🛑 楽天APIの設定エラーで中断しました。`);
  console.log(`     現在のIP（curl -4 -s ifconfig.me）が許可リストにあるか確認してください。`);
  process.exit(1);
}

if (!APPLY) {
  console.log("\n保存するには --apply");
  console.log("保存後、直引きが本当に通るかを --verify で確かめてください");
  process.exit(0);
}

const ts = new Date().toISOString();
for (const r of resolved) {
  r.p.rakutenItemCode = r.itemCode;
  r.p.updatedAt = ts; // pull時のマージ巻き戻し防止
}
fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
console.log(`\ndata/products.json に ${resolved.length}件の itemCode を保存しました`);
console.log("次: node scripts/resolve-rakuten-itemcodes.mjs --verify");
console.log("反映: npm run db:sync -- --no-pull");
