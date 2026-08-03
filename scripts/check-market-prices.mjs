#!/usr/bin/env node
/**
 * 記事本文とproducts.jsonの価格が食い違っている商品について、
 * 楽天の実勢価格を調べて「どちらが正しいか」を判定する（読み取り専用）
 *
 * 背景（2026-08-03）: 監査の「記事矛盾」10件は、本文が正しい場合と
 * データが正しい場合の両方が混ざっている。人力で1件ずつ楽天を見るのは
 * 時間がかかるので、中央値との距離で機械的に当たりを付ける。
 *
 * products.json / articles.json は一切変更しない。
 *
 * 使い方（自宅Wi-Fiから。アクセスキーのIP許可リスト登録が必要）:
 *   node scripts/check-market-prices.mjs
 *   node scripts/check-market-prices.mjs --ids=jackery-1000-new,fan-hagoogi-ot-f12
 */
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const RAKUTEN_API_URL =
  "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
const AFFILIATE_ID =
  process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";
const appId = process.env.RAKUTEN_APP_ID;
const accessKey = process.env.RAKUTEN_ACCESS_KEY;
if (!appId || !accessKey) {
  console.error("RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が未設定です");
  process.exit(1);
}

const products = JSON.parse(fs.readFileSync("data/products.json", "utf8"));
const byId = new Map(products.map((p) => [p.id, p]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const USED_SHOP = /2nd STREET|セカンドストリート|ワットマン|リサイクル|中古|質屋/i;
// 本体ではない出品を弾く。付属品・別売バッテリー・セット品が混じると中央値が壊れる
const NOT_MAIN =
  /レンタル|ベースプレート|グランドシート|インナーシート|ゴトク|ロストル|焼網|焼き網|オプション|パーツ|部品|替え|交換用|収納袋|ケース単品|カバーのみ|専用ケース|マット単品|ポールのみ|ペグのみ|補修|延長保証|バッテリーのみ|拡張バッテリー|ソーラーパネル単品/;

function coreTokens(name) {
  return name
    .replace(/[（(].*?[)）]/g, " ")
    .split(/[\s　/／・]+/)
    .filter((t) => [...t].length >= 2)
    .slice(0, 4);
}
function looksSameProduct(productName, itemName) {
  const toks = coreTokens(productName);
  if (toks.length === 0) return true;
  const hit = toks.filter((t) => itemName.includes(t)).length;
  return hit >= Math.min(2, toks.length);
}
function sanitize(s) {
  return s
    .replace(/[×/＋+|｜]/g, " ")
    .split(/\s+/)
    .filter((t) => [...t].length >= 2)
    .join(" ")
    .slice(0, 120);
}

async function search(keyword) {
  const params = new URLSearchParams({
    applicationId: appId,
    accessKey,
    affiliateId: AFFILIATE_ID,
    keyword: sanitize(keyword),
    hits: "20",
    sort: "standard", // 安い順にすると付属品が上位に来て相場を誤る
    format: "json",
    formatVersion: "2",
  });
  const res = await fetch(`${RAKUTEN_API_URL}?${params}`, {
    headers: {
      Origin: "https://camp-gear-lab.com",
      Referer: "https://camp-gear-lab.com/",
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    if (body.includes("CLIENT_IP_NOT_ALLOWED")) {
      console.error(
        "\nアクセスキーがIP制限で拒否されました。\n" +
          "https://webservice.rakuten.co.jp/ で現在のIP（curl -s ifconfig.me）を許可リストに追加してください。\n" +
          "※カフェ・テザリングのIPは登録しないこと（他人と共有される回線のため）"
      );
      process.exit(1);
    }
    console.warn(`  API ${res.status}: ${body.slice(0, 120)}`);
    return [];
  }
  const data = await res.json();
  return (data.Items || []).filter(
    (i) => !USED_SHOP.test(i.shopName || "") && !NOT_MAIN.test(i.itemName || "")
  );
}

// 監査の「記事矛盾」からIDを引く。--ids= で明示指定もできる
function targetsFromAudit() {
  const raw = execFileSync("node", ["scripts/audit-product-data.mjs", "--json"], {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
  const { findings } = JSON.parse(raw);
  const out = [];
  for (const f of findings) {
    if (f.type !== "記事矛盾") continue;
    const p = products.find((x) => x.name === f.name);
    if (!p) continue;
    const written = /本文「([0-9,〜~～]+)円」/.exec(f.detail || "")?.[1] || "";
    const slug = (f.detail || "").split(":")[0];
    out.push({ id: p.id, slug, written });
  }
  return out;
}

const idsArg = process.argv.find((a) => a.startsWith("--ids="));
const targets = idsArg
  ? idsArg
      .slice(6)
      .split(",")
      .map((id) => ({ id: id.trim(), slug: "", written: "" }))
  : targetsFromAudit();

console.log(
  `\n=== 価格矛盾${targets.length}件の実勢確認（データは変更しません）===\n`
);

for (const t of targets) {
  const p = byId.get(t.id);
  if (!p) {
    console.log(`■ ${t.id}: products.jsonに見つかりません\n`);
    continue;
  }
  await sleep(1500);
  const items = (await search(p.name)).filter((i) =>
    looksSameProduct(p.name, i.itemName || "")
  );
  const prices = items.map((i) => i.itemPrice).filter((v) => v > 0);

  console.log(`■ ${p.name}${t.slug ? `（${t.slug}）` : ""}`);
  console.log(
    `   データ ¥${(p.price || 0).toLocaleString()}${t.written ? ` / 本文 ${t.written}円` : ""}`
  );
  if (prices.length === 0) {
    console.log(`   楽天: 本体と判定できる出品なし（候補なし）。手動確認が必要です\n`);
    continue;
  }
  const sorted = [...prices].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  console.log(
    `   楽天: ${prices.length}件 最安¥${sorted[0].toLocaleString()} 中央値¥${median.toLocaleString()} 最高¥${sorted[sorted.length - 1].toLocaleString()}`
  );

  const dataGap = Math.abs((p.price || 0) - median) / median;
  const verdict =
    dataGap <= 0.1
      ? "データが実勢。本文の価格表記を直す"
      : dataGap >= 0.25
        ? "データが実勢から外れている。products.jsonの価格を直す"
        : "どちらとも言えない。目視で確認する";
  console.log(`   → ${verdict}（データと中央値の差 ${Math.round(dataGap * 100)}%）`);
  console.log(`   参考: ${items[Math.floor(items.length / 2)]?.itemName?.slice(0, 52) || ""}\n`);
}

console.log("結果を見て、本文とデータのどちらを直すか決めてください。");
