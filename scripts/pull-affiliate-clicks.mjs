#!/usr/bin/env node
/**
 * Supabase の affiliate_clicks を data/affiliate-clicks.json に書き出す
 *
 * 背景（2026-08-13）: 記事分析が「クリック0件」を出し続けていた。
 * 週1,000PVあってクリック0は不自然なので追ったところ、計測ではなく
 * 集計側が壊れていた。
 *   実際のクリック … /api/track-click → Supabase の affiliate_clicks テーブル
 *   読んでいる側   … data/affiliate-clicks.json（3スクリプトが参照）
 * そしてこのJSONを**書いているスクリプトが1つも無かった**。
 * 中身は空配列のままで、誰も埋めていない。
 *
 * 結果、以下が全部ゼロ前提で動いていた:
 *   article-analyst-agent.js … 記事評価がPVだけになりCTRが常に0
 *   weekly-report.js         … 週次レポートのクリック数が常に0
 *   supervisor-agent.js      … X経由のクリック集計が機能しない
 *
 * 読み側3つを Supabase 直読みに書き換えるより、この1本で橋渡しする方が
 * 影響が小さい。日次パイプラインの先頭で回す想定。
 *
 * カラム名が違うので変換する:
 *   clicked_at → timestamp   page_path → path   product_id → productId
 * 元のカラム名も残す（supervisor-agent が clicked_at / page_path も見るため）。
 *
 * 使い方:
 *   node scripts/pull-affiliate-clicks.mjs            # 件数を表示するだけ
 *   node scripts/pull-affiliate-clicks.mjs --write    # JSONに書き出す
 *   node scripts/pull-affiliate-clicks.mjs --days 30  # 取得期間（既定90日）
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { createClient } from "@supabase/supabase-js";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const OUT = path.join(ROOT, "data", "affiliate-clicks.json");

const argv = process.argv.slice(2);
const WRITE = argv.includes("--write");
const daysIdx = argv.indexOf("--days");
const DAYS = daysIdx !== -1 ? parseInt(argv[daysIdx + 1], 10) || 90 : 90;

const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!url || !key) {
  console.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が未設定です（.env.local を確認）");
  process.exit(1);
}

const supabase = createClient(url, key);
const since = new Date(Date.now() - DAYS * 86400_000).toISOString();

// 1000件で頭打ちになるので分割して全部取る
const rows = [];
const PAGE = 1000;
for (let from = 0; ; from += PAGE) {
  const { data, error } = await supabase
    .from("affiliate_clicks")
    .select("product_id, product_name, store, placement, page_path, clicked_at")
    .gte("clicked_at", since)
    .order("clicked_at", { ascending: true })
    .range(from, from + PAGE - 1);
  if (error) {
    console.error("Supabase エラー:", error.message);
    process.exit(1);
  }
  rows.push(...data);
  if (data.length < PAGE) break;
}

const clicks = rows.map((r) => ({
  timestamp: r.clicked_at,
  path: r.page_path,
  productId: r.product_id,
  productName: r.product_name,
  store: r.store,
  placement: r.placement,
  // supervisor-agent は元のカラム名でも参照するので両方残す
  clicked_at: r.clicked_at,
  page_path: r.page_path,
  product_id: r.product_id,
}));

console.log(`affiliate_clicks: 直近${DAYS}日で ${clicks.length}件`);

if (clicks.length === 0) {
  console.log("\n⚠ 0件です。集計側ではなく計測そのものが止まっている可能性があります。");
  console.log("  /api/track-click が呼ばれているか、ブラウザの Network タブで確認してください。");
} else {
  const first = clicks[0].timestamp?.slice(0, 10);
  const last = clicks[clicks.length - 1].timestamp?.slice(0, 10);
  console.log(`期間: ${first} 〜 ${last}`);

  const count = (arr, keyFn) => {
    const m = {};
    for (const c of arr) m[keyFn(c)] = (m[keyFn(c)] || 0) + 1;
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  };
  const week = clicks.filter((c) => c.timestamp >= new Date(Date.now() - 7 * 86400_000).toISOString());

  console.log(`\n直近7日: ${week.length}件`);
  console.log("  ストア別:", count(week, (c) => c.store).map(([k, v]) => `${k}=${v}`).join(" ") || "なし");
  console.log("\n  クリックの多い商品（7日）:");
  for (const [id, n] of count(week, (c) => c.productId).slice(0, 10)) {
    console.log(`    ${String(n).padStart(4)}回  ${id}`);
  }
  console.log("\n  クリックの多いページ（7日）:");
  for (const [p, n] of count(week, (c) => c.path || "(不明)").slice(0, 10)) {
    console.log(`    ${String(n).padStart(4)}回  ${p}`);
  }
}

if (WRITE) {
  fs.writeFileSync(OUT, JSON.stringify(clicks, null, 2));
  console.log(`\ndata/affiliate-clicks.json に ${clicks.length}件を書き出しました`);
} else {
  console.log("\n書き出すには --write");
}
