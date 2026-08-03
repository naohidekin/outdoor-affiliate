#!/usr/bin/env node
/**
 * 記事本文とproducts.jsonの価格が食い違っている商品について、
 * 「リンク先の楽天商品ページの現在価格」を1件ずつ引いて確認する（読み取り専用）
 *
 * 背景（2026-08-03）: 最初はキーワード検索で相場の中央値を出す設計にしたが、
 * 型番の世代違い（Jackery 1000/2000、WAVE 2/3、RIVER 2 Pro/RIVER Pro）や
 * 保護フィルム・ケーブル・中古出品が混ざり、中央値が完全に壊れた。
 * products.json の affiliateUrl には楽天の商品ページURLが入っているので、
 * そこから itemCode を組み立てて直接引く。推定ではなく、
 * 「読者がリンクを踏んで実際に見る価格」が取れる。
 *
 * products.json / articles.json は一切変更しない。
 *
 * 使い方（自宅Wi-Fiから。アクセスキーのIP許可リスト登録が必要）:
 *   node scripts/check-market-prices.mjs
 *   node scripts/check-market-prices.mjs --ids=jackery-1000-new,mat-waq-8cm
 *   node scripts/check-market-prices.mjs --all   # 全商品を点検
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

// affiliateUrl から楽天の商品ページURLを取り出す。
// hb.afl.rakuten.co.jp/.../?pc=<エンコード済み商品URL> の形式
function itemUrlOf(p) {
  const raw = p.affiliateUrl || "";
  if (!raw) return "";
  if (raw.includes("item.rakuten.co.jp") && !raw.includes("hb.afl.")) return raw;
  try {
    const pc = new URL(raw).searchParams.get("pc");
    if (!pc) return "";
    try {
      return decodeURIComponent(pc);
    } catch {
      return pc; // 壊れたエンコードの商品が7件ある。生のまま返す
    }
  } catch {
    return "";
  }
}

// https://item.rakuten.co.jp/{shop}/{itemNumber}/ → { shop, slug }
function shopAndSlug(url) {
  const m = /item\.rakuten\.co\.jp\/([^/?#]+)\/([^/?#]+)/.exec(url || "");
  return m ? { shop: m[1], slug: m[2] } : null;
}
const slugOf = (u) => shopAndSlug(u)?.slug || "";

function sanitize(s) {
  return s
    .replace(/[×/＋+|｜（）()]/g, " ")
    .split(/\s+/)
    .filter((t) => [...t].length >= 2)
    .join(" ")
    .slice(0, 120);
}

async function call(extra) {
  const params = new URLSearchParams({
    applicationId: appId,
    accessKey,
    affiliateId: AFFILIATE_ID,
    format: "json",
    formatVersion: "2",
    ...extra,
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
    return { error: `${res.status} ${body.slice(0, 90)}`, items: [] };
  }
  const data = await res.json();
  return { items: data.Items || [] };
}

// 2026-08-03: itemCode パラメータは ichibams エンドポイントが受け付けない
// （全件 wrong_parameter で弾かれる）。店舗コードで絞り、返ってきた
// itemUrl の末尾スラッグが一致するものを拾う方式に変更した
async function fetchLinkedItem({ shop, slug }, name) {
  const attempts = [
    { label: "shopCode+keyword", q: { shopCode: shop, keyword: sanitize(name), hits: "30" } },
    { label: "shopCode", q: { shopCode: shop, hits: "30" } },
    { label: "keyword", q: { keyword: sanitize(name), hits: "30" } },
  ];
  let lastError = "";
  let nearby = [];
  for (const a of attempts) {
    await sleep(1200);
    const { items, error } = await call(a.q);
    if (error) {
      lastError = error;
      continue;
    }
    const hit = items.find((i) => slugOf(i.itemUrl) === slug);
    if (hit) return { item: hit, via: a.label };
    if (items.length && !nearby.length) nearby = items.slice(0, 5);
  }
  return {
    error:
      lastError ||
      "リンク先の商品が店舗の出品一覧に見つかりません（販売終了・ページ削除の可能性）",
    nearby,
  };
}

// 商品名の世代・型番が一致しているかの目視補助。
// 「WAVE 2」の商品に「WAVE 3」のページが紐づいている事故が実在した
function modelTokens(s) {
  return (s || "").toUpperCase().match(/[A-Z]{2,}[-\s]?\d{2,4}|\b\d{3,4}\b/g) || [];
}

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
    out.push({
      id: p.id,
      slug: (f.detail || "").split(":")[0],
      written: /本文「([0-9,〜~～]+)円」/.exec(f.detail || "")?.[1] || "",
    });
  }
  return out;
}

const idsArg = process.argv.find((a) => a.startsWith("--ids="));
const targets = process.argv.includes("--all")
  ? products.map((p) => ({ id: p.id, slug: "", written: "" }))
  : idsArg
    ? idsArg
        .slice(6)
        .split(",")
        .map((id) => ({ id: id.trim(), slug: "", written: "" }))
    : targetsFromAudit();

console.log(
  `\n=== リンク先の現在価格を確認（${targets.length}件 / データは変更しません）===\n`
);

const mismatched = [];

for (const t of targets) {
  const p = byId.get(t.id);
  if (!p) {
    console.log(`■ ${t.id}: products.jsonに見つかりません\n`);
    continue;
  }
  const url = itemUrlOf(p);
  const loc = shopAndSlug(url);

  console.log(`■ ${p.name}${t.slug ? `（${t.slug}）` : ""}`);
  console.log(
    `   データ ¥${(p.price || 0).toLocaleString()}${t.written ? ` / 本文 ${t.written}円` : ""}`
  );

  if (!loc) {
    console.log(
      url
        ? `   リンク先が商品ページではありません: ${url.slice(0, 70)}\n`
        : `   affiliateUrl が未設定です\n`
    );
    continue;
  }

  const { item, via, error, nearby } = await fetchLinkedItem(loc, p.name);
  if (error) {
    console.log(`   ${loc.shop}/${loc.slug}: ${error}`);
    for (const c of nearby || []) {
      console.log(`      同店舗の候補: ¥${c.itemPrice.toLocaleString()} ${c.itemName.slice(0, 44)}`);
    }
    console.log();
    continue;
  }

  const live = item.itemPrice;
  const gap = p.price ? Math.abs(live - p.price) / p.price : 1;
  console.log(
    `   リンク先: ¥${live.toLocaleString()}  ${item.itemName.slice(0, 46)}  [${via}]`
  );

  // リンク先が別モデルを指していないか（WAVE 2 → wave3 の事故が実在）
  const want = modelTokens(p.name);
  const got = modelTokens(item.itemName);
  if (want.length && !want.some((w) => got.includes(w))) {
    console.log(`   !! 型番が一致しません（期待 ${want.join(",")} / 実際 ${got.join(",") || "なし"}）`);
    console.log(`      リンク先が別商品の可能性があります: ${url}`);
  }

  if (gap >= 0.1) {
    console.log(`   → データを ¥${live.toLocaleString()} に直す（差 ${Math.round(gap * 100)}%）`);
    mismatched.push({ id: p.id, from: p.price, to: live });
  } else {
    console.log(`   → データは正しい。本文の価格表記を直す`);
  }
  console.log();
}

if (mismatched.length) {
  console.log(`\n価格を直すべき商品 ${mismatched.length}件:`);
  for (const m of mismatched) {
    console.log(`  ${m.id.padEnd(32)} ¥${m.from.toLocaleString()} → ¥${m.to.toLocaleString()}`);
  }
}
console.log("\n※ このスクリプトはデータを変更しません。反映は別途承認のうえで行います。");
