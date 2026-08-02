#!/usr/bin/env node
/**
 * 商品データ健全性監査
 *
 * 背景（2026-08-01）: シェラカップ記事に実在しない商品
 * 「BUNDOK シェラカップ 600ml BD-190」が5位で紹介されていた
 * （BD-190はピクニックテーブルセットの型番。容量も重量も架空）。
 * 記事生成時のスペック捏造とみられ、同種の問題が他にもある可能性があるため、
 * 外部APIに頼らず検出できる矛盾を機械的に洗い出す。
 *
 * 使い方:
 *   node scripts/audit-product-data.mjs          # 全チェック
 *   node scripts/audit-product-data.mjs --json   # JSON出力（他ツール連携用）
 *
 * 検出する問題:
 *  1. 重複登録   同一商品が複数IDで登録されている（記事ごとに価格が食い違う原因）
 *  2. 価格矛盾   重複商品間で価格が10%以上ずれている
 *  3. 型番衝突   同じ型番が別商品に割り当てられている
 *  4. 記事矛盾   記事本文の価格表記とproducts.jsonの価格がずれている
 *               （合計額・差額・ふるさと納税の自己負担などは除外するが、
 *                文脈依存のため最終判断は目視で行うこと）
 *  5. 欠損       価格0 / 画像なし / カテゴリなし
 *  6. 孤立       どの公開記事からも参照されていない
 */
import fs from "node:fs";

const JSON_OUT = process.argv.includes("--json");
const products = JSON.parse(fs.readFileSync("data/products.json", "utf8"));
const articles = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
const published = articles.filter((a) => a.status === "published");
const byId = new Map(products.map((p) => [p.id, p]));

const findings = [];
const add = (type, severity, detail) => findings.push({ type, severity, ...detail });

// 商品名の正規化。表記ゆれ（空白・記号・全角）を吸収して同一商品を見つける
const norm = (s) =>
  (s || "")
    .replace(/[\s　・（）()【】[\]/｜|]/g, "")
    .replace(/株式会社/g, "")
    .toLowerCase();

const usedIn = (pid) =>
  published
    .filter((a) => (a.productIds || []).includes(pid) || a.content.includes(pid))
    .map((a) => a.slug);

// ── 1-2. 重複登録と価格矛盾 ───────────────────────────
const groups = new Map();
for (const p of products) {
  const key = norm(p.name).slice(0, 24);
  if (!key) continue;
  if (!groups.has(key)) groups.set(key, []);
  groups.get(key).push(p);
}
for (const [, list] of groups) {
  if (list.length < 2) continue;
  const prices = list.map((p) => p.price || 0).filter((v) => v > 0);
  const spread =
    prices.length > 1 ? (Math.max(...prices) - Math.min(...prices)) / Math.max(...prices) : 0;
  const entries = list.map((p) => ({
    id: p.id,
    price: p.price || 0,
    categoryId: p.categoryId || "",
    articles: usedIn(p.id),
  }));
  const liveCount = entries.filter((e) => e.articles.length > 0).length;
  add("重複登録", liveCount > 1 ? "high" : "medium", {
    name: list[0].name,
    entries,
    note:
      liveCount > 1
        ? "両方が公開記事で使われています。記事ごとに別価格が表示されます"
        : "片方は未使用。統合して削除できます",
  });
  if (spread >= 0.1) {
    add("価格矛盾", "high", {
      name: list[0].name,
      detail: entries.map((e) => `${e.id}=¥${e.price.toLocaleString()}`).join(" / "),
      note: `価格差 ${Math.round(spread * 100)}%`,
    });
  }
}

// ── 3. 型番衝突 ───────────────────────────────────
const modelsOf = (name) =>
  new Set(
    (name.match(/[A-Za-z]{1,6}-[A-Za-z0-9]{2,10}/g) || []).map((m) =>
      m.toUpperCase().replace(/-/g, "")
    )
  );
const byModel = new Map();
for (const p of products) {
  for (const m of modelsOf(p.name)) {
    if (!byModel.has(m)) byModel.set(m, []);
    byModel.get(m).push(p);
  }
}
for (const [model, list] of byModel) {
  if (list.length < 2) continue;
  // 同一商品の重複は 1. で報告済み。別商品に同じ型番が付いている場合だけ出す
  const distinct = new Set(list.map((p) => norm(p.name).slice(0, 24)));
  if (distinct.size > 1) {
    add("型番衝突", "high", {
      name: model,
      detail: list.map((p) => `${p.id}(${p.name.slice(0, 24)})`).join(" / "),
      note: "同じ型番が別商品に付いています。どちらかが誤りです",
    });
  }
}

// ── 4. 記事本文の価格表記との矛盾 ─────────────────────
// 「約25,000円」「1,210円」のような表記を拾い、掲載商品の価格と突き合わせる
for (const a of published) {
  for (const pid of a.productIds || []) {
    const p = byId.get(pid);
    if (!p || !p.price) continue;
    // 商品名の主要語が近くにある価格表記だけを対象にする（誤検出を抑える）
    const head = p.name.split(/[\s　]/)[0];
    if (!head || head.length < 2) continue;
    const re = new RegExp(
      `${head.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[^。\\n]{0,25}?(?:約)?([0-9,]{3,9})\\s*円`,
      "g"
    );
    for (const m of a.content.matchAll(re)) {
      const written = parseInt(m[1].replace(/,/g, ""), 10);
      if (!Number.isFinite(written) || written < 100) continue;
      // 単価ではない金額（合計・差額・年間コスト・ふるさと納税の自己負担など）を除外する。
      // 例:「4台分で30,800円」「自己負担は2,000円」「年間930円」は商品価格ではない
      const around = a.content.slice(Math.max(0, m.index - 60), m.index + m[0].length + 20);
      if (/台分|合計|差額|年間|自己負担|納税|控除|総額|込みで|セットで|\d+年で/.test(around)) continue;
      const diff = Math.abs(written - p.price) / p.price;
      if (diff >= 0.2) {
        add("記事矛盾", "medium", {
          name: p.name,
          detail: `${a.slug}: 本文「${m[1]}円」 vs データ ¥${p.price.toLocaleString()}`,
          note: `差 ${Math.round(diff * 100)}%`,
        });
      }
    }
  }
}

// ── 5-6. 欠損と孤立 ──────────────────────────────
const missing = { price: [], image: [], category: [] };
const orphans = [];
for (const p of products) {
  if (!p.price) missing.price.push(p.id);
  if (!p.imageUrl) missing.image.push(p.id);
  if (!p.categoryId) missing.category.push(p.id);
  if (usedIn(p.id).length === 0) orphans.push(p.id);
}

// ── 出力 ────────────────────────────────────────
if (JSON_OUT) {
  console.log(JSON.stringify({ findings, missing, orphans }, null, 2));
  process.exit(0);
}

const order = { high: 0, medium: 1, low: 2 };
findings.sort((a, b) => order[a.severity] - order[b.severity]);
const high = findings.filter((f) => f.severity === "high").length;

console.log(`\n=== 商品データ健全性監査（全${products.length}商品 / 公開${published.length}記事）===`);
console.log(`要対応 ${high}件 / 検出 ${findings.length}件\n`);

let lastType = "";
for (const f of findings) {
  if (f.type !== lastType) {
    console.log(`\n▼ ${f.type}`);
    lastType = f.type;
  }
  const mark = f.severity === "high" ? "!!" : " -";
  console.log(`${mark} ${f.name}`);
  if (f.entries) {
    for (const e of f.entries) {
      console.log(
        `     ${e.id.padEnd(32)} ¥${String(e.price).padStart(7)} ${
          e.articles.length ? `記事: ${e.articles.join(", ")}` : "（未使用）"
        }`
      );
    }
  }
  if (f.detail) console.log(`     ${f.detail}`);
  if (f.note) console.log(`     → ${f.note}`);
}

console.log(`\n▼ 欠損`);
console.log(`   価格なし: ${missing.price.length}件 / 画像なし: ${missing.image.length}件 / カテゴリなし: ${missing.category.length}件`);
console.log(`\n▼ 孤立（どの公開記事からも参照なし）: ${orphans.length}件`);
console.log(`   ※ 孤立自体は問題ではありません（記事化待ちの在庫）。ただし重複の片割れは削除候補です`);
