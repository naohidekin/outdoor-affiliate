#!/usr/bin/env node
/**
 * Snow Peak IGT データの検証（本番投入時のお供）
 *
 * `npm run build` でも検証は走るが、1回2〜3分かかる。データを1件足すたびに
 * ビルドを回すのは現実的でないので、即座に返る窓口を用意する。
 *
 * 検証は本番と同じ core.ts の validateDataset を使う。二重定義にすると
 * 「スクリプトは通るのにビルドで落ちる」が起きるため。
 *
 * さらに、機械的には正しいが人間が間違えやすい点を警告として出す:
 *   - 日本型番と米国型番が同一（取り違えの可能性）
 *   - 後継品があるのに互換性が未確認のまま（意図的ならOK。確認を促すだけ）
 *   - affiliate: true（契約の実在確認を促す）
 *   - 確認日が古い
 *
 *   node scripts/igt-validate.ts
 */
import fs from "node:fs";
import path from "node:path";
import {
  validateDataset,
  type ProductRecord,
  type SourceRecord,
} from "../src/lib/experiments/snow-peak-igt/core.ts";

const DATA_DIR = path.join(process.cwd(), "data", "experiments", "snow-peak-igt");
const STALE_DAYS = 180;

function readArray(file: string): unknown[] {
  const full = path.join(DATA_DIR, file);
  if (!fs.existsSync(full)) {
    console.error(`✗ ${file} がありません（${DATA_DIR}）`);
    process.exit(1);
  }
  const raw = fs.readFileSync(full, "utf8").trim();
  try {
    const parsed = JSON.parse(raw === "" ? "[]" : raw);
    if (!Array.isArray(parsed)) throw new Error("配列ではありません");
    return parsed;
  } catch (e) {
    console.error(`✗ ${file} を読めません: ${e instanceof Error ? e.message : e}`);
    process.exit(1);
  }
}

const products = readArray("products.json");
const sources = readArray("sources.json");

console.log(`商品 ${products.length}件 / 出典 ${sources.length}件\n`);

// ─── 必須条件（ビルドと同じ判定） ─────────────────────
const errors = validateDataset(products, sources);
if (errors.length > 0) {
  console.error(`✗ ${errors.length}件の問題があります。ビルドも落ちます:\n`);
  for (const e of errors) console.error(`   ${e}`);
  console.error("\n  直し方は data/experiments/snow-peak-igt/README.md を参照");
  process.exit(1);
}
console.log("✅ 必須条件（出典・確認日・整合性）はすべて満たしています");

// ─── 人が間違えやすい点（警告。落とさない） ───────────
const typed = products as ProductRecord[];
const typedSources = sources as SourceRecord[];
const warnings: string[] = [];

for (const p of typed) {
  if (
    p.japaneseModelNumber &&
    p.usModelNumber &&
    p.japaneseModelNumber.trim() === p.usModelNumber.trim()
  ) {
    warnings.push(
      `${p.id}: 日本型番と米国型番が同一（${p.japaneseModelNumber}）。` +
        `本当に同じなら問題ないが、片方のコピー漏れでないか確認を`
    );
  }
  if (p.confirmedSuccessorId && p.compatibility.length === 0) {
    warnings.push(
      `${p.id}: 後継品はあるが互換性の記録が0件。` +
        `後継品＝互換ではないので、これは正しい状態でもある（確認だけ）`
    );
  }
  for (const o of p.purchaseOptions) {
    if (o.affiliate) {
      warnings.push(
        `${p.id}: ${o.merchant}（${o.market}）を affiliate: true にしている。` +
          `その提携が実在し、有効か確認を`
      );
    }
  }
  const age = Math.floor(
    (Date.now() - new Date(p.lastVerifiedAt).getTime()) / 86_400_000
  );
  if (Number.isFinite(age) && age > STALE_DAYS) {
    warnings.push(`${p.id}: 確認日が${age}日前（${p.lastVerifiedAt}）。再確認を`);
  }
}

// 使われていない出典は消し忘れのことが多い
const used = new Set<string>();
for (const p of typed) {
  p.sourceIds.forEach((s) => used.add(s));
  p.compatibility.forEach((c) => c.sourceIds.forEach((s) => used.add(s)));
}
for (const s of typedSources) {
  if (!used.has(s.id)) warnings.push(`出典 ${s.id} はどの商品からも参照されていません`);
}

if (warnings.length > 0) {
  console.log(`\n⚠ 確認してほしい点 ${warnings.length}件（落としません）:\n`);
  for (const w of warnings) console.log(`   ${w}`);
}

// ─── まとめ ───────────────────────────────────────────
if (typed.length === 0) {
  console.log(
    "\n本番データは空です。Finderは「まだ公開している記録がない」と表示し、" +
      "リクエスト導線だけを出します。"
  );
  console.log("投入手順: docs/experiments/snow-peak-igt/GO-LIVE.md");
} else {
  const oldest = typed
    .map((p) => p.lastVerifiedAt)
    .sort()[0];
  console.log(`\n最も古い確認日: ${oldest}`);
  console.log("次: npm test && npm run build");
}
