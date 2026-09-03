#!/usr/bin/env node
/**
 * 記事内の「口コミ」引用を洗い出す（Amazonアソシエイト対策）
 *
 * 背景（2026-08-22）: 姉妹サイト japan-shop-helper.com のAmazonアソシエイトが
 * 「Amazonレビューの無許可使用」を理由に閉鎖された。camp-gear-lab は実際に
 * 収益が出ている唯一の口座なので、同じ形を残さない。
 *
 * 直す対象は2つある:
 *   1. 見出し … 「口コミ（楽天・Amazon参考）」のように出典にAmazonを書いているもの
 *   2. 本文  … 「」付きの箇条書きで購入者の声として出しているもの
 *
 * 2 は機械的に言い換えると意味が壊れるので、ここでは**検出と一覧化だけ**行う。
 * 書き換えは記事ごとに人が確認しながら進める。
 *
 * 優先度はクリック実績と記事露出で付ける。同じ違反でも読まれている記事ほど
 * 監査で見つかる確率が高く、消したときの損失も大きい。
 *
 * 使い方:
 *   node scripts/audit-review-quotes.mjs              # 集計
 *   node scripts/audit-review-quotes.mjs --list       # 記事ごとの詳細
 *   node scripts/audit-review-quotes.mjs --slug xxx   # 1記事の全文脈
 *   node scripts/audit-review-quotes.mjs --json       # scratch/review-quotes.json に書き出す
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const argv = process.argv.slice(2);
const argVal = (n) => {
  const i = argv.indexOf(n);
  return i !== -1 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : null;
};
const LIST = argv.includes("--list");
const JSON_OUT = argv.includes("--json");
const SLUG = argVal("--slug");

const articles = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "articles.json"), "utf8"));
let clicks = [];
try {
  clicks = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "affiliate-clicks.json"), "utf8"));
} catch {
  /* クリック実績が無くても動く */
}
const since = new Date(Date.now() - 30 * 86400_000).toISOString();
const clicksByPath = new Map();
for (const c of clicks) {
  if (c.timestamp >= since && c.path)
    clicksByPath.set(c.path, (clicksByPath.get(c.path) || 0) + 1);
}

// 見出しに出典としてAmazonを書いているもの。ここは機械的に直せる
const HEAD_RE =
  /^([>\s]*)((?:#{2,4}\s*)?\*{0,2})(口コミ[^\n*：:]{0,26}|レビュー[^\n*：:]{0,26}|ユーザーの声[^\n*：:]{0,18})(\*{0,2})([:：]?)[ \t]*$/gm;
// 「」または "" で囲った箇条書き。購入者の声として読める形
const QUOTE_RE = /^[>\s]*[-*][ \t]*[「"][^\n]{4,}[」"][ \t]*$/gm;

// 見出しの直後に置かれた「購入者の声」。2026-09-03 追加。
// 引用ブロック（>）で書かれ「」も箇条書き記号も無い形が QUOTE_RE を素通りしていた。
// 星評価の削除作業で、compact-tent-ranking / winter-sleeping-bag-ranking /
// spring-sleeping-bag-guide の3記事が「引用0行」と報告されていたのが発覚のきっかけ。
// 見出しからの距離で判定するので、結論ボックスや内部リンクの引用は拾わない。
const HEAD_LINE_RE = /^[>\s]*(?:#{2,4}\s*)?\*{0,2}\s*(?:口コミ|レビュー|ユーザーの声)/;
const SKIP_RE = /^[>\s]*(?:\*\*(?:結論|向いている人|向いていない人))|https?:\/\//;
function voicesUnderHeads(content) {
  const lines = content.split("\n");
  const found = [];
  for (let i = 0; i < lines.length; i++) {
    if (!HEAD_LINE_RE.test(lines[i])) continue;
    for (let j = i + 1; j < Math.min(i + 12, lines.length); j++) {
      const t = lines[j].trim();
      if (!t) continue;
      if (/^#{1,4}\s/.test(t)) break;                       // 次の見出しで打ち切り
      if (j > i + 1 && HEAD_LINE_RE.test(lines[j])) break;   // 次のレビュー見出し
      if (SKIP_RE.test(t)) continue;                         // 結論ボックス・リンク行
      const isQuote = t.startsWith(">") && t.replace(/^>+\s*/, "").length > 14;
      const isKagi = /^-?\s*[「"].+[」"]/.test(t);
      if (isQuote || isKagi) found.push(t.slice(0, 120));
    }
  }
  return found;
}

const rows = [];
for (const a of articles) {
  if (a.status !== "published") continue;
  if (SLUG && a.slug !== SLUG) continue;
  const c = a.content || "";
  const heads = [...c.matchAll(HEAD_RE)].map((m) => m[3].trim());
  const amazonHeads = heads.filter((h) => /amazon/i.test(h));
  const quotes = [...c.matchAll(QUOTE_RE)].map((m) => m[0].trim());
  // 見出し直下の声。quotes と重複する行は落とす
  const voices = voicesUnderHeads(c).filter((v) => !quotes.includes(v));
  // 見出し以外でAmazonをレビューの出典として書いている文
  const inline = [...c.matchAll(/[^\n。]{0,40}Amazon[^\n。]{0,12}(?:レビュー|口コミ|評価)[^\n。]{0,40}/gi)]
    .map((m) => m[0].trim())
    .filter((t) => !/で(口コミ|レビュー)を(もっと)?(見る|確認)/.test(t)); // CTAリンクは対象外
  if (!heads.length && !quotes.length && !voices.length && !inline.length) continue;
  rows.push({
    slug: a.slug,
    title: a.title,
    clicks30d: clicksByPath.get(`/articles/${a.slug}`) || 0,
    heads,
    amazonHeads,
    quotes,
    voices,
    inline,
  });
}

rows.sort(
  (x, y) =>
    y.clicks30d - x.clicks30d ||
    y.quotes.length + y.voices.length - (x.quotes.length + x.voices.length)
);

const sum = (f) => rows.reduce((n, r) => n + f(r), 0);
console.log(`口コミ引用の監査: ${rows.length}記事`);
console.log(`  「」付きの箇条書き        : ${sum((r) => r.quotes.length)}行`);
console.log(`  見出し直下の声（引用ブロック含む）: ${sum((r) => r.voices.length)}行`);
console.log(`  見出し（全体）            : ${sum((r) => r.heads.length)}個`);
console.log(`  うち出典にAmazonを書くもの: ${sum((r) => r.amazonHeads.length)}個 ← 機械的に直せる`);
console.log(`  本文でAmazonレビューに言及: ${sum((r) => r.inline.length)}箇所`);

if (SLUG || LIST) {
  for (const r of rows) {
    if (!SLUG && r.quotes.length === 0 && r.voices.length === 0 && r.amazonHeads.length === 0 && r.inline.length === 0)
      continue;
    console.log(`\n──── ${r.slug}（30日 ${r.clicks30d}クリック）────`);
    console.log(`  ${r.title.slice(0, 56)}`);
    if (r.amazonHeads.length) console.log(`  出典Amazonの見出し: ${[...new Set(r.amazonHeads)].join(" / ")}`);
    if (r.inline.length) for (const t of r.inline.slice(0, 3)) console.log(`  本文: ${t.slice(0, 70)}`);
    const all = [...r.quotes, ...r.voices];
    for (const q of all.slice(0, SLUG ? 999 : 4)) console.log(`  ${q.slice(0, 76)}`);
    if (!SLUG && all.length > 4) console.log(`  … 他${all.length - 4}行`);
  }
} else {
  console.log(`\n── 優先度順（上位15記事）──`);
  for (const r of rows.slice(0, 15)) {
    console.log(
      `  ${String(r.clicks30d).padStart(3)}クリック  ${r.slug.padEnd(38)} ` +
        `引用${String(r.quotes.length + r.voices.length).padStart(2)}行 / Amazon見出し${r.amazonHeads.length}`
    );
  }
  console.log(`\n詳細: --list ／ 1記事: --slug <slug>`);
}

if (JSON_OUT) {
  const out = path.join(ROOT, "scratch", "review-quotes.json");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify({ ranAt: new Date().toISOString(), rows }, null, 2));
  console.log(`\nレポート: ${out}`);
}
