import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stableJsonString, normalizeJsonValue } from "../src/lib/stable-json.ts";
import * as mjs from "../src/lib/stable-json.mjs";

// data/*.json は「同じ内容なら必ず同じバイト列」であってほしい。
// Supabaseとの往復でキー順や時刻表記が揺れ、中身を1文字も変えていないのに
// 毎回 git の差分になっていた。git stash pop のたびに衝突し、そのたびに
// 人が「本当に捨てていいのか」を確認していた。1日に3回やった日もある。

test("ネストしたオブジェクトのキーが辞書順に揃う", () => {
  const a = { specs: { 消費電力: "40W", サイズ: "130×80cm", 形式: "敷き" } };
  const b = { specs: { 形式: "敷き", 消費電力: "40W", サイズ: "130×80cm" } };
  assert.equal(stableJsonString(a), stableJsonString(b));
});

test("時刻の表記ゆれが吸収される", () => {
  const a = { updatedAt: "2026-08-26T13:28:56.126Z" };
  const b = { updatedAt: "2026-08-26T13:28:56.126+00:00" };
  assert.equal(stableJsonString(a), stableJsonString(b));
  assert.ok(stableJsonString(a).includes("2026-08-26T13:28:56.126Z"));
});

test("配列の順序は保たれる（順序に意味があるため）", () => {
  const out = normalizeJsonValue({ productIds: ["c", "a", "b"] }) as {
    productIds: string[];
  };
  assert.deepEqual(out.productIds, ["c", "a", "b"]);
});

test("日付に見えるだけの文字列を壊さない", () => {
  for (const s of ["2026", "2026-08", "2026年8月26日", "8/26", "CK-080R"]) {
    assert.deepEqual(normalizeJsonValue({ v: s }), { v: s });
  }
});

test("末尾に改行が付く", () => {
  assert.ok(stableJsonString({ a: 1 }).endsWith("\n"));
});

test("冪等（もう一度かけても変わらない）", () => {
  const data = {
    b: 2,
    a: { z: "2026-08-26T13:28:56.126+00:00", y: [3, 1, 2] },
  };
  const once = stableJsonString(data);
  const twice = stableJsonString(JSON.parse(once));
  assert.equal(once, twice);
});

test("TS版と mjs版の出力が一致する", () => {
  // 実装が2箇所にあるので、ズレたらここで落とす。片方だけ直せない
  const samples: unknown[] = [
    { specs: { 消費電力: "40W", 形式: "敷き" }, updatedAt: "2026-08-26T13:28:56.126+00:00" },
    [{ b: 1, a: [{ d: 4, c: 3 }] }],
    { faqs: [{ answer: "A", question: "Q" }] },
    { nested: { deep: { deeper: { x: null, a: true, m: 1.5 } } } },
  ];
  for (const s of samples) {
    assert.equal(stableJsonString(s), mjs.stableJsonString(s));
  }
});

// ─── 本番データ ───────────────────────────────────────

test("data/*.json が正規化済みの状態で保存されている", () => {
  // 正規化されていない状態でコミットされると、次に Supabase から
  // 書き戻した瞬間に大きな差分が出て、また同じ手間が発生する
  const notNormalized: string[] = [];
  for (const name of ["articles.json", "products.json", "categories.json"]) {
    const p = path.join(process.cwd(), "data", name);
    const raw = fs.readFileSync(p, "utf8");
    if (raw !== stableJsonString(JSON.parse(raw))) notNormalized.push(name);
  }
  assert.deepEqual(
    notNormalized,
    [],
    `正規化されていない: ${notNormalized.join(", ")} — npm run data:normalize で直せます`
  );
});

// ─── 書き手が正規化を通しているか ─────────────────────

test("Supabaseから書き戻す2箇所が、どちらも正規化を通している", () => {
  const files = [
    path.join(process.cwd(), "src", "lib", "local-sync.ts"),
    path.join(process.cwd(), "scripts", "pull-from-supabase.js"),
  ];
  for (const f of files) {
    const src = fs.readFileSync(f, "utf8");
    assert.ok(
      /stableJsonString\(/.test(src),
      `${path.basename(f)} が正規化を通していない`
    );
    assert.ok(
      !/JSON\.stringify\(data, null, 2\)/.test(src),
      `${path.basename(f)} に素の JSON.stringify が残っている`
    );
  }
});
