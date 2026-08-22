#!/usr/bin/env node
/**
 * Amazonのレビュー件数・評価点の記述を外す（個別対応分）
 *
 * fix-review-attribution.mjs は機械的に安全な置換だけを扱った。
 * 残った12箇所は文の意味に食い込むので、1件ずつ置換を書く。
 *
 * とくに picogrill-vs-tokyocamp-bonfire は
 *   | Amazon評価 | 4.3（約3,000件） | 4.5（約7,600件） |
 *   Amazonで7,600件以上のレビューがついて4.5点
 * のように**レビュー件数と評価点をそのまま数字で載せている**。
 * これはAmazonのデータそのもので、見出しの出典表記より踏み込んでいる。
 *
 * 方針:
 *   件数・点数は落とす（「レビュー件数が非常に多く」等の定性表現に）
 *   出典としてのAmazonは書かない
 *   「Amazonで見る」「Amazonで口コミをもっと見る」のCTAリンクは残す（誘導は問題ない）
 *
 * 使い方:
 *   node scripts/fix-review-attribution-manual.mjs           # 置換案を表示
 *   node scripts/fix-review-attribution-manual.mjs --apply
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const APPLY = process.argv.includes("--apply");

/** slug ごとの置換。from は完全一致で1回だけ置換する（曖昧一致で事故らせない） */
const EDITS = [
  {
    slug: "field-rack-ranking",
    why: "見出しにAmazonの評価点を書いている",
    from: "｜Amazonで評価4.4の実力派コスパモデル",
    to: "｜価格と質のバランスがいい実力派",
  },
  {
    slug: "field-rack-ranking",
    why: "購入者の声としてAmazonレビューを名指ししている",
    from: "- 「Amazonのレビューを信じて購入。期待以上の作りだった」",
    to: "- レビュー評価を見て選んだという人が多く、作りの良さへの満足度が高い",
  },
  {
    slug: "picogrill-vs-tokyocamp-bonfire",
    why: "比較表にAmazonの評価点とレビュー件数を載せている",
    from: "| Amazon評価 | 4.3（約3,000件） | 4.5（約7,600件） |\n",
    to: "",
  },
  {
    slug: "picogrill-vs-tokyocamp-bonfire",
    why: "レビュー件数と評価点をそのまま数字で出している",
    from: "Amazonで7,600件以上のレビューがついて4.5点。この数字だけでも信頼度の高さがわかります。",
    to: "レビュー件数が非常に多く、評価も高い水準で安定しています。この積み重ねだけでも信頼度の高さがわかります。",
  },
  {
    slug: "picogrill-vs-tokyocamp-bonfire",
    why: "レビュー件数をAmazon由来として出している",
    from: "7,600件を超えるAmazonレビューが、その満足度を物語っています。",
    to: "レビュー件数の多さが、その満足度を物語っています。",
  },
  {
    slug: "cot-vs-mat-comparison",
    why: "レビュー数・評価の出典をAmazonと明記している",
    from: "Amazonのレビュー数と評価を見ても、",
    to: "レビュー数と評価を見ても、",
  },
  {
    slug: "landlock-vs-landnest-shelter",
    why: "レビューの出典にAmazonを挙げている",
    from: "楽天・Amazonのレビューから、カタログスペックでは見えないリアルな声をまとめました",
    to: "各モールのレビューから、カタログスペックでは見えない傾向をまとめました",
  },
  {
    slug: "autumn-camp-clothing-layering-guide",
    why: "口コミ見出しの出典にAmazonを書いている",
    from: "**ストームクルーザーの口コミ**（楽天・Amazonレビューより要約）:",
    to: "**ストームクルーザーのレビューの傾向**（各モールのレビューを読んだ僕の要約です）",
  },
];

/** 同じ文字列が複数回出る記事は、まとめて全置換する */
const REPLACE_ALL = [
  {
    slug: "tarp-buying-guide",
    why: "引用ブロックの出典にAmazonを書いている",
    from: "> *(Amazon レビュー より要約)*",
    to: "> *(各モールのレビューを読んだ僕の要約です)*",
  },
];

const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));
const byId = new Map(articles.map((a) => [a.slug, a]));

let applied = 0;
let missing = 0;
const touched = new Set();

const show = (slug, why, from, to, n) => {
  console.log(`\n──── ${slug} ────`);
  console.log(`  理由: ${why}${n > 1 ? `（${n}箇所）` : ""}`);
  console.log(`    − ${from.trim().slice(0, 96)}`);
  console.log(`    ＋ ${to.trim() ? to.trim().slice(0, 96) : "（行ごと削除）"}`);
};

for (const e of EDITS) {
  const a = byId.get(e.slug);
  if (!a) {
    console.log(`✗ 記事が見つかりません: ${e.slug}`);
    missing++;
    continue;
  }
  if (!a.content.includes(e.from)) {
    // 既に直っているのか、文面が変わったのかを区別できるようにする
    console.log(`✗ 対象の文が見つかりません: ${e.slug}`);
    console.log(`    探した文: ${e.from.trim().slice(0, 70)}`);
    missing++;
    continue;
  }
  show(e.slug, e.why, e.from, e.to, 1);
  if (APPLY) {
    a.content = a.content.replace(e.from, e.to);
    touched.add(e.slug);
  }
  applied++;
}

for (const e of REPLACE_ALL) {
  const a = byId.get(e.slug);
  if (!a) {
    console.log(`✗ 記事が見つかりません: ${e.slug}`);
    missing++;
    continue;
  }
  const n = a.content.split(e.from).length - 1;
  if (n === 0) {
    console.log(`✗ 対象の文が見つかりません: ${e.slug}`);
    missing++;
    continue;
  }
  show(e.slug, e.why, e.from, e.to, n);
  if (APPLY) {
    a.content = a.content.split(e.from).join(e.to);
    touched.add(e.slug);
  }
  applied += n;
}

console.log(`\n── まとめ ──`);
console.log(`  置換: ${applied}箇所 / ${touched.size || new Set([...EDITS, ...REPLACE_ALL].map((e) => e.slug)).size}記事`);
if (missing) console.log(`  ⚠ 見つからなかった: ${missing}件（先に別の修正が入った可能性あり）`);
console.log(`  ※ 「Amazonで見る」「Amazonで口コミをもっと見る」のリンクは残しています`);

if (!APPLY) {
  console.log("\n書き込むには --apply");
  process.exit(0);
}

const ts = new Date().toISOString();
for (const slug of touched) byId.get(slug).updatedAt = ts; // pull時のマージ巻き戻し防止
fs.writeFileSync(ARTICLES, JSON.stringify(articles, null, 2));
console.log(`\ndata/articles.json を更新しました（${touched.size}記事）`);
console.log("反映: npm run db:sync -- --no-pull");
