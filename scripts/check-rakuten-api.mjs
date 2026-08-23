#!/usr/bin/env node
/**
 * 楽天APIの疎通を最小構成で確かめる（切り分け専用）
 *
 * 背景（2026-08-23）: 朝は通っていた楽天APIが途中から
 * `API Configuration not found` を返すようになった。仮説を2つ立てて
 * 2つとも外した。
 *   ① .env.local の RAKUTEN_APP_ID 重複でIDとキーがズレている
 *      → 2組とも完結していた。外れ
 *   ② IP制限。回線の動的IPが変わった
 *      → 現在のIPも /24 レンジも登録済みだった。外れ
 *
 * 残る変数が多いので、1リクエストずつ条件を変えて潰す。
 * 商品検索スクリプトの出力からは「どのアプリIDで叩いたか」が分からず、
 * それが切り分けを止めていた。ここでは必ず表示する（先頭8文字だけ）。
 *
 * 確かめること:
 *   1. いま採用されている applicationId はどれか
 *   2. .env.local に重複があるか（loadEnv は後勝ちで黙って上書きする）
 *   3. エンドポイントの違いで結果が変わるか
 *      openapi.rakuten.co.jp/ichibams/... … このリポジトリが使っている窓口
 *      app.rakuten.co.jp/services/api/...  … 一般的な楽天ウェブサービスの窓口
 *      前者は楽天市場会員サービス系で、アプリがそのAPI向けに設定されて
 *      いないと「設定が見つからない」になりうる
 *   4. accessKey を外すと結果が変わるか（キー不一致の切り分け）
 *
 * 何も書き換えない。アクセスキーの値も表示しない。
 *
 *   node scripts/check-rakuten-api.mjs
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

dns.setDefaultResultOrder("ipv4first");

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ─── .env.local の重複を先に見る ───────────────────────
const envPath = path.join(ROOT, ".env.local");
if (fs.existsSync(envPath)) {
  const lines = fs.readFileSync(envPath, "utf8").split("\n");
  const hits = [];
  lines.forEach((l, i) => {
    const m = l.match(/^(RAKUTEN_APP_ID|RAKUTEN_ACCESS_KEY)=(.*)$/);
    if (m) hits.push({ line: i + 1, key: m[1], head: m[2].trim().slice(0, 8) });
  });
  console.log("── .env.local の楽天まわり ──");
  for (const h of hits) {
    // アプリIDは先頭8文字だけ。アクセスキーは長さだけ
    const shown = h.key === "RAKUTEN_APP_ID" ? `${h.head}…` : "（値は表示しません）";
    console.log(`  ${String(h.line).padStart(3)}行  ${h.key.padEnd(20)} ${shown}`);
  }
  const dupIds = hits.filter((h) => h.key === "RAKUTEN_APP_ID");
  if (dupIds.length > 1) {
    console.log(
      `  ⚠ RAKUTEN_APP_ID が${dupIds.length}行あります。loadEnv は後勝ちなので` +
        `${dupIds[dupIds.length - 1].line}行目が採用されます`
    );
  }
}

loadEnv();
const appId = process.env.RAKUTEN_APP_ID;
const accessKey = process.env.RAKUTEN_ACCESS_KEY;
if (!appId) {
  console.error("\nRAKUTEN_APP_ID がありません");
  process.exit(1);
}
console.log(`\n  実際に使われる applicationId: ${appId.slice(0, 8)}…`);
console.log(`  accessKey: ${accessKey ? `あり（${accessKey.length}文字）` : "なし"}`);

// ─── 疎通テスト ───────────────────────────────────────
const ENDPOINTS = [
  ["ichibams（このリポジトリの窓口）", "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601"],
  ["app.rakuten.co.jp（一般的な窓口）", "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"],
];

async function probe(label, url, withKey) {
  const params = new URLSearchParams({
    applicationId: appId,
    ...(withKey && accessKey ? { accessKey } : {}),
    keyword: "テント",
    hits: "1",
    format: "json",
    formatVersion: "2",
  });
  let res, body;
  try {
    res = await fetch(`${url}?${params}`, {
      headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
    });
    body = await res.text();
  } catch (e) {
    console.log(`  ✗ ${label} … 通信エラー: ${String(e.message).slice(0, 60)}`);
    return false;
  }
  if (res.ok) {
    let n = 0;
    try {
      n = (JSON.parse(body).Items || []).length;
    } catch {
      /* 形が違っても ok なら疎通はしている */
    }
    console.log(`  ✅ ${label} … ${res.status} 商品${n}件`);
    return true;
  }
  console.log(`  ✗ ${label} … ${res.status} ${body.slice(0, 110)}`);
  return false;
}

console.log("\n── 疎通テスト（keyword=テント, hits=1）──");
let anyOk = false;
for (const [label, url] of ENDPOINTS) {
  if (await probe(`${label} + accessKey`, url, true)) anyOk = true;
  await sleep(1200); // 1秒1リクエストの制限を守る
}
// accessKey を外すと通るなら、キーとIDの対応が疑わしい
console.log("\n── accessKey を外して再試行 ──");
for (const [label, url] of ENDPOINTS) {
  if (await probe(`${label} + キーなし`, url, false)) anyOk = true;
  await sleep(1200);
}

console.log("\n── 読み方 ──");
if (anyOk) {
  console.log("  通った組み合わせがあります。スクリプト側をその窓口・条件に合わせれば動きます");
} else {
  console.log("  すべて失敗。アプリID自体か、アカウント全体の問題です");
  console.log("  次に見るところ:");
  console.log("    ・楽天Developersでアプリの「編集」を開き、IP登録が保存されているか");
  console.log("    ・そのアプリで楽天市場商品検索APIが使える設定になっているか");
  console.log("    ・もう一方のアプリID（.env.local の別行）を有効にして再実行");
}
