#!/usr/bin/env node

/**
 * normalize-data-json.mjs — data/*.json を正規の形に揃える
 *
 * 内容は一切変えず、表記だけを揃える:
 *   - ネストしたオブジェクトのキーを辞書順に
 *   - ISO時刻を Z 表記に
 *   - 末尾に改行を1つ
 *
 * Supabaseとの往復でこれらが揺れ、中身が同じでも毎回 git の差分に
 * なっていた。git stash pop のたびに衝突する原因だった。
 *
 * 使い方:
 *   npm run data:normalize            # 書き換える
 *   npm run data:normalize -- --check # 差分があるかだけ見る（CI向け・書き換えない）
 */

import fs from "node:fs";
import path from "node:path";
import { stableJsonString, normalizeJsonValue } from "../src/lib/stable-json.mjs";

const DATA_DIR = path.join(process.cwd(), "data");
const FILES = ["articles.json", "products.json", "categories.json"];
const checkOnly = process.argv.includes("--check");

let changed = 0;

for (const name of FILES) {
  const p = path.join(DATA_DIR, name);
  if (!fs.existsSync(p)) {
    console.log(`[normalize] － ${name} が無いのでスキップ`);
    continue;
  }

  const before = fs.readFileSync(p, "utf8");

  let data;
  try {
    data = JSON.parse(before);
  } catch (err) {
    // コンフリクトマーカーが残っている等。ここで黙って続けると
    // 壊れたファイルを上書きすることになるので中断する
    console.error(`[normalize] ❌ ${name} がJSONとして読めません: ${err.message}`);
    process.exit(1);
  }

  const after = stableJsonString(data);

  if (before === after) {
    console.log(`[normalize] ✓ ${name} は既に正規化済み`);
    continue;
  }

  // 意味が変わっていないことを確認してから書く
  const same =
    JSON.stringify(normalizeJsonValue(JSON.parse(before))) ===
    JSON.stringify(normalizeJsonValue(JSON.parse(after)));
  if (!same) {
    console.error(`[normalize] ❌ ${name} の内容が変わってしまう。中断します`);
    process.exit(1);
  }

  changed++;
  if (checkOnly) {
    console.log(`[normalize] ▲ ${name} は未正規化（--check のため書き換えません）`);
    continue;
  }

  fs.writeFileSync(p, after);
  console.log(
    `[normalize] ✅ ${name} を正規化 (${before.length} → ${after.length} バイト)`
  );
}

if (checkOnly && changed > 0) {
  console.error(
    `\n[normalize] ${changed}件が未正規化です。npm run data:normalize を実行してください`
  );
  process.exit(1);
}

console.log(`[normalize] 完了（変更 ${changed} ファイル）`);
