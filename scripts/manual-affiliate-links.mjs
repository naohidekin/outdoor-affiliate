#!/usr/bin/env node
/**
 * アフィリリンクの手動補完ヘルパー
 *
 * 背景（2026-08-01）: 検索ページ行きだったアフィリリンク194件のうち111件は
 * `fix-search-affiliate-links.mjs` が自動で商品直リンクに置換できたが、
 * 82件は「型番が無い汎用品」「サイズ違いの誤マッチが怖い」等の理由で
 * 自動判定を見送った。そのうち7月に実クリックがあった25件を手動で埋める。
 *
 * 楽天APIを使わないので、IP許可リストの制約を受けない（外出先でも使える）。
 *
 * ## 使い方
 *
 * 1) 記入用ファイルを作る（対象商品と検索URLの一覧が出力される）
 *      node scripts/manual-affiliate-links.mjs --init
 *
 * 2) scratch/manual-affiliate-links.txt を開き、各行の検索URLをブラウザで開いて
 *    正しい商品ページを見つけ、そのURL（https://item.rakuten.co.jp/... ）を
 *    行末の `= ` の後ろに貼る。分からない商品は空のまま飛ばしてよい
 *
 * 3) 検証（書き込みはしない）
 *      node scripts/manual-affiliate-links.mjs
 *
 * 4) 反映
 *      node scripts/manual-affiliate-links.mjs --apply
 *
 * ## 安全装置
 * - item.rakuten.co.jp 等の商品ページURL以外は受け付けない（検索URLを弾く）
 * - すでにアフィリエイトURL形式で貼られた場合は中の商品URLを取り出して使う
 * - 対象商品リストに無いIDは無視する
 * - --apply しない限り products.json は書き換わらない
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const SHEET = path.join(ROOT, "scratch", "manual-affiliate-links.txt");

// 既存商品で使用中のアフィリエイトID（新規発行はしない運用）
const AFFILIATE_ID =
  process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

// 7月のクリック実績があり、かつ検索ページ行きのまま残っている25件。
// クリック数の多い順。これ以外も直したくなったら --all を付ける
const PRIORITY_IDS = [
  "sb-kids-001", "growler-001", "water-jug-igloo-400s",
  "pillow-sea-to-summit-aeros", "tent-duo-005", "sb-kids-003",
  "sierra-cup-bundok", "tent-solo-002", "water-jug-stanley-7.5l",
  "tent-duo-004", "tent-duo-002", "table-002", "fp-001", "cooler-005",
  "rw-004", "growler-003", "pillow-nemo-fillo-elite", "hammock-unigear",
  "knife-003", "sierra-cup-belmont", "sb-budget-004",
  "fire-blower-tokyocamp", "stanley-water-jug-7.5l", "bp-004", "cooker-001",
];

const APPLY = process.argv.includes("--apply");
const INIT = process.argv.includes("--init");
const ALL = process.argv.includes("--all");

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const byId = new Map(products.map((p) => [p.id, p]));

function isSearchLink(url) {
  if (!url) return false;
  const m = url.match(/[?&]pc=([^&]+)/);
  if (!m) return false;
  let t;
  try {
    t = decodeURIComponent(m[1]);
  } catch {
    t = m[1];
  }
  return t.includes("search.rakuten");
}

function targetIds() {
  if (ALL) return products.filter((p) => isSearchLink(p.affiliateUrl)).map((p) => p.id);
  return PRIORITY_IDS.filter((id) => byId.has(id));
}

// 楽天の商品ページURLか判定。検索URLやトップは弾く
function isItemUrl(url) {
  return /^https:\/\/(item|books|search)?\.?rakuten\.co\.jp\//.test(url)
    ? /^https:\/\/(item|books)\.rakuten\.co\.jp\/[^/]+\/[^/]+/.test(url)
    : false;
}

// アフィリエイトURLが貼られた場合は中の pc= を取り出す
function extractItemUrl(raw) {
  const v = raw.trim();
  if (!v) return null;
  const m = v.match(/[?&]pc=([^&]+)/);
  if (m) {
    try {
      return decodeURIComponent(m[1]);
    } catch {
      return m[1];
    }
  }
  return v;
}

function buildAffiliateUrl(itemUrl) {
  return `https://hb.afl.rakuten.co.jp/ichiba/${AFFILIATE_ID}/?pc=${encodeURIComponent(
    itemUrl
  )}&link_type=text`;
}

// ─── --init: 記入用ファイルを生成 ──────────────────────
if (INIT) {
  const ids = targetIds();
  const lines = [
    "# アフィリリンク手動補完シート",
    "# 各行の検索URLをブラウザで開き、正しい商品ページのURLを `= ` の後ろに貼ってください。",
    "# 分からない商品は空のまま飛ばして構いません（スキップされます）。",
    "# 貼るURL例: https://item.rakuten.co.jp/shopname/itemcode/",
    "",
  ];
  for (const id of ids) {
    const p = byId.get(id);
    // 商品名にブランドが含まれていない場合だけ前置する（二重にしない）
    const needsBrand = p.brand && !p.name.includes(p.brand);
    const q = encodeURIComponent(
      `${needsBrand ? p.brand + " " : ""}${p.name}`.slice(0, 100)
    );
    lines.push(`# ${p.name}（¥${(p.price || 0).toLocaleString()}）`);
    lines.push(`#   検索: https://search.rakuten.co.jp/search/mall/${q}/`);
    lines.push(`${id} = `);
    lines.push("");
  }
  fs.mkdirSync(path.dirname(SHEET), { recursive: true });
  fs.writeFileSync(SHEET, lines.join("\n"));
  console.log(`記入用ファイルを作成: ${SHEET}`);
  console.log(`対象 ${ids.length}件。ファイルを開いてURLを貼ってください。`);
  console.log("貼り終わったら: node scripts/manual-affiliate-links.mjs（検証）");
  process.exit(0);
}

// ─── 検証 / 反映 ────────────────────────────────────
if (!fs.existsSync(SHEET)) {
  console.error(`記入用ファイルがありません。先に --init を実行してください:\n  node scripts/manual-affiliate-links.mjs --init`);
  process.exit(1);
}

const allowed = new Set(targetIds());
const ok = [];
const errors = [];
const skipped = [];

for (const line of fs.readFileSync(SHEET, "utf8").split("\n")) {
  const t = line.trim();
  if (!t || t.startsWith("#")) continue;
  const m = t.match(/^([A-Za-z0-9._-]+)\s*=\s*(.*)$/);
  if (!m) continue;
  const [, id, rawValue] = m;
  const p = byId.get(id);
  if (!p) {
    errors.push(`${id}: products.json に存在しません`);
    continue;
  }
  if (!allowed.has(id)) {
    errors.push(`${id}: 対象リスト外です（--all で全件対象にできます）`);
    continue;
  }
  const itemUrl = extractItemUrl(rawValue);
  if (!itemUrl) {
    skipped.push(`${id} (${p.name.slice(0, 30)})`);
    continue;
  }
  if (itemUrl.includes("search.rakuten")) {
    errors.push(`${id}: 検索URLが貼られています。商品ページのURLにしてください`);
    continue;
  }
  if (!isItemUrl(itemUrl)) {
    errors.push(`${id}: 楽天の商品ページURLではありません → ${itemUrl.slice(0, 60)}`);
    continue;
  }
  ok.push({ id, name: p.name, itemUrl, affiliateUrl: buildAffiliateUrl(itemUrl) });
}

console.log(`\n=== 検証結果 ===`);
console.log(`記入あり: ${ok.length}件 / 未記入: ${skipped.length}件 / エラー: ${errors.length}件\n`);
for (const o of ok) console.log(`✓ ${o.name.slice(0, 38)}\n    ${o.itemUrl}`);
if (errors.length) {
  console.log(`\n▼ エラー（修正してください）`);
  for (const e of errors) console.log(`  ✗ ${e}`);
}
if (skipped.length) {
  console.log(`\n▼ 未記入（スキップ）`);
  for (const s of skipped) console.log(`  - ${s}`);
}

if (!APPLY) {
  console.log(`\n反映するには: node scripts/manual-affiliate-links.mjs --apply`);
  process.exit(errors.length > 0 ? 1 : 0);
}
if (errors.length > 0) {
  console.error(`\nエラーがあるため反映を中止しました。上の行を直してから再実行してください。`);
  process.exit(1);
}
if (ok.length === 0) {
  console.error(`\n記入がありません。`);
  process.exit(1);
}

const now = new Date().toISOString();
for (const o of ok) {
  const p = byId.get(o.id);
  p.affiliateUrl = o.affiliateUrl;
  p.updatedAt = now;
}
fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
console.log(`\nproducts.json に ${ok.length}件を反映しました。`);
console.log("次: git diff data/products.json で確認 → コミット → sync（--no-pull）");
