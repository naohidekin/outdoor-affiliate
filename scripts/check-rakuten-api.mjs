#!/usr/bin/env node
/**
 * 楽天APIの疎通を最小構成で確かめる（切り分け専用）
 *
 * 背景（2026-08-23）: 楽天APIが `API Configuration not found` を返し続ける。
 * 仮説を5つ立てて5つとも説明しきれていない。
 *   ① .env.local の RAKUTEN_APP_ID 重複でIDとキーがズレている
 *      → 2組とも完結していた。外れ
 *   ② IP制限。回線の動的IPが変わった
 *      → 現在のIPも /24 レンジも登録済みだった。外れ
 *   ③ エンドポイント違い / ④ Origin・Referer ヘッダ
 *      → 2×2×ヘッダ有無の全通りで失敗。外れ
 *   ⑤ レート制限違反による application_id の利用停止
 *      → 自分のコードに実際の違反はあった（1秒未満の間隔が3箇所）。
 *        ただし楽天のFAQは「継続的に制限値を超えた場合」と書いており、
 *        **数回しか叩いていない2つ目のアプリも同じエラーを返す**。
 *        停止なら使っていないアプリは生きているはずで、説明がつかない。
 *
 * 残る筋は「アプリ個別ではなくアカウント側、またはアプリ設定側」。
 * それを確かめるには**複数のアプリIDを同条件で比べる**必要がある。
 * 以前の版は「いま採用されている1つ」しか試せず、そこが切り分けを止めていた。
 *
 * このスクリプトは .env.local にある RAKUTEN_APP_ID を**コメントアウト
 * された行も含めて全部拾い**、それぞれで疎通を試す。
 * 新しく作ったアプリを足すときは、.env.local に次を書く（loadEnv は
 * この名前を読まないので、既存の設定を壊さない）:
 *
 *   RAKUTEN_APP_ID_TEST=<新しいアプリのID>
 *   RAKUTEN_ACCESS_KEY_TEST=<そのアクセスキー>
 *
 * 読み方:
 *   新アプリだけ通る   → 既存アプリ固有の問題。載せ替えれば復旧
 *   新アプリも落ちる   → アカウント全体の問題。問い合わせるしかない
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
// 楽天の規定は「1つのapplication_idにつき1秒に1回以下」。
// 切り分け中に新たな違反を積み増さないよう、間隔は広めに取る
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const GAP = 1500;

/**
 * .env.local からアプリIDとアクセスキーの組を全部拾う。
 *
 * コメントアウト行（先頭 #）も対象にする。切り分けでは「いま無効に
 * してあるほうのアプリ」こそ比較対象になるため。
 * 組み合わせは「あるAPP_ID行の次に現れたACCESS_KEY行」で作る。
 * .env.local は2行1組で並んでいるので、順番で数えるより崩れにくい。
 */
function collectApps() {
  const envPath = path.join(ROOT, ".env.local");
  if (!fs.existsSync(envPath)) return [];
  const lines = fs.readFileSync(envPath, "utf8").split("\n");

  const marks = [];
  lines.forEach((raw, i) => {
    const commented = /^\s*#/.test(raw);
    const l = raw.replace(/^\s*#\s*/, "");
    const m = l.match(/^(RAKUTEN_APP_ID(?:_TEST)?|RAKUTEN_ACCESS_KEY(?:_TEST)?)=(.*)$/);
    if (m) marks.push({ line: i + 1, key: m[1], value: m[2].trim(), commented });
  });

  const apps = [];
  marks.forEach((m, idx) => {
    if (!/^RAKUTEN_APP_ID/.test(m.key) || !m.value) return;
    // このID行より後で最初に出てくるアクセスキー行を相方とする
    const key = marks.slice(idx + 1).find((x) => /^RAKUTEN_ACCESS_KEY/.test(x.key) && x.value);
    apps.push({
      line: m.line,
      appId: m.value,
      accessKey: key?.value || null,
      keyLine: key?.line ?? null,
      commented: m.commented,
      isTest: m.key.endsWith("_TEST"),
    });
  });
  return apps;
}

const apps = collectApps();

console.log("── .env.local にある楽天アプリ ──");
if (apps.length === 0) {
  console.error("  RAKUTEN_APP_ID が1つも見つかりません");
  process.exit(1);
}
for (const a of apps) {
  const state = a.isTest ? "新規テスト用" : a.commented ? "コメントアウト中" : "有効";
  console.log(
    `  ${String(a.line).padStart(3)}行  ${a.appId.slice(0, 8)}…  [${state}]  ` +
      `accessKey: ${a.accessKey ? `${a.accessKey.length}文字（${a.keyLine}行）` : "なし"}`
  );
}

loadEnv();
const active = process.env.RAKUTEN_APP_ID;
if (active) console.log(`\n  スクリプトが実際に使うのは: ${active.slice(0, 8)}…`);
if (!apps.some((a) => a.isTest)) {
  console.log(
    "\n  ヒント: 楽天Developersで**新しいアプリを1つ作り**、\n" +
      "        .env.local に RAKUTEN_APP_ID_TEST / RAKUTEN_ACCESS_KEY_TEST として\n" +
      "        書き足すと、既存アプリと並べて比較できます（既存設定は壊しません）"
  );
}

// ─── 疎通テスト ───────────────────────────────────────
const ENDPOINTS = [
  ["ichibams", "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601"],
  ["app.rakuten", "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"],
];

async function probe(app, url, { withKey = true, withHeaders = true } = {}) {
  const params = new URLSearchParams({
    applicationId: app.appId,
    ...(withKey && app.accessKey ? { accessKey: app.accessKey } : {}),
    keyword: "テント",
    hits: "1",
    format: "json",
    formatVersion: "2",
  });
  let res, body;
  try {
    res = await fetch(
      `${url}?${params}`,
      withHeaders
        ? { headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" } }
        : {}
    );
    body = await res.text();
  } catch (e) {
    return { ok: false, note: `通信エラー: ${String(e.message).slice(0, 50)}` };
  }
  if (res.ok) {
    let n = 0;
    try {
      n = (JSON.parse(body).Items || []).length;
    } catch {
      /* 形が違っても ok なら疎通はしている */
    }
    return { ok: true, note: `${res.status} 商品${n}件` };
  }
  return { ok: false, note: `${res.status} ${body.replace(/\s+/g, " ").slice(0, 90)}` };
}

const results = [];
for (const app of apps) {
  const label = `${app.appId.slice(0, 8)}…${app.isTest ? "（新規）" : app.commented ? "（無効中）" : ""}`;
  console.log(`\n── ${label} ──`);
  for (const [name, url] of ENDPOINTS) {
    const r = await probe(app, url);
    console.log(`  ${r.ok ? "✅" : "✗ "} ${name} + accessKey … ${r.note}`);
    results.push({ app: label, ok: r.ok });
    await sleep(GAP);
  }
  // キーを外して通るなら、IDとキーの対応が疑わしい
  if (app.accessKey) {
    const r = await probe(app, ENDPOINTS[0][1], { withKey: false });
    console.log(`  ${r.ok ? "✅" : "✗ "} ichibams + キーなし  … ${r.note}`);
    results.push({ app: label, ok: r.ok });
    await sleep(GAP);
  }
  // ヘッダを外して通るなら、ヘッダが原因
  const r = await probe(app, ENDPOINTS[0][1], { withHeaders: false });
  console.log(`  ${r.ok ? "✅" : "✗ "} ichibams + ヘッダなし … ${r.note}`);
  results.push({ app: label, ok: r.ok });
  await sleep(GAP);
}

// ─── 読み方 ───────────────────────────────────────────
console.log("\n── 読み方 ──");
const okApps = [...new Set(results.filter((r) => r.ok).map((r) => r.app))];
const ngApps = [...new Set(results.filter((r) => !r.ok).map((r) => r.app))].filter(
  (a) => !okApps.includes(a)
);

if (okApps.length && ngApps.length) {
  console.log(`  通ったアプリ: ${okApps.join(", ")}`);
  console.log(`  落ちたアプリ: ${ngApps.join(", ")}`);
  console.log("  → アプリ個別の問題です。通ったアプリのIDとキーを .env.local の");
  console.log("     RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY に載せ替えれば復旧します");
} else if (okApps.length) {
  console.log("  全アプリで疎通しています。不通は解消しています");
} else {
  console.log("  すべてのアプリ・すべての条件で失敗しました。");
  console.log("  アプリ個別ではなくアカウント側の問題と考えられます。");
  console.log("  新しく作ったアプリでも落ちるなら、設定の作り直しでは直りません。");
  console.log("");
  console.log("  次にやること:");
  console.log("    楽天ウェブサービスのヘルプページから問い合わせる");
  console.log("    （FAQ「利用規約に違反しているか個別に確認をしたい」の窓口）");
  console.log("    https://webservice.faq.rakuten.net/hc/ja/requests/new");
  console.log("    伝えること: アプリID・発生日時・エラー文言・");
  console.log("                全アプリで再現すること・登録済みのIP");
}
