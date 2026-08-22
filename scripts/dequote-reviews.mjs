#!/usr/bin/env node
/**
 * レビューブロックの引用符を外し、書き手の要約に変える
 *
 * 背景（2026-08-22）: 姉妹サイト japan-shop-helper.com のAmazonアソシエイトが
 * 「Amazonレビューの無許可使用」で閉鎖された。camp-gear-lab は実際に収益が
 * 出ている唯一の口座なので、同じ形を残さない。
 *
 * 見出しは fix-review-attribution.mjs で
 * 「レビューの傾向（各モールのレビューを読んだ僕の要約です）」に変えた。
 * 残るのは本文で、購入者の発言として「」付きで並んでいる。
 *
 *   - 「マットブラックの見た目がかっこよくて選んだ」
 *   > 「収納袋がやや小さめで、畳むのに少しコツが要ります」
 *
 * 引用符を外せば、他人の発言ではなく書き手の要約になる。
 * Amazonの規約（レビューの無許可使用）と景表法（実在しない購入者の声）の
 * 両方に同時に効く。
 *
 * **引用符を無差別に外してはいけない。** 本文には口コミ以外の「」がある。
 *   「あれ、こっち側だったっけ」が起きない   ← 書き手の地の文
 *   「軽さと携帯性は圧倒的」というのが正直なところ ← 書き手の要約
 * なので**レビュー見出しの直後に続くブロックの中だけ**を対象にする。
 *
 * 地の文に埋め込まれた引用（「A」「B」という声が多い、など45箇所）は
 * 文構造に食い込むのでここでは触らない。--report で一覧が出る。
 *
 * 使い方:
 *   node scripts/dequote-reviews.mjs             # 変換案を全件表示
 *   node scripts/dequote-reviews.mjs --report    # 手動対応が要る箇所
 *   node scripts/dequote-reviews.mjs --slug xxx  # 1記事だけ確認
 *   node scripts/dequote-reviews.mjs --apply
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const REPORT = argv.includes("--report");
const SLUG = (() => {
  const i = argv.indexOf("--slug");
  return i !== -1 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : null;
})();

const LABEL = "レビューの傾向（各モールのレビューを読んだ僕の要約です）";

/**
 * レビューブロックの開始を示す見出し。
 *
 * 「口コミ」で始まるものだけを見ていたら「**ユーザーの口コミ：**」が漏れ、
 * water-jug-ranking の15行が丸ごと未処理になっていた。
 * 短いラベル行で、口コミ・レビュー系の語を含むものを広く拾う。
 * 判定を緩めても、実際に書き換わるのは「」だけで構成された行に限られる
 */
function isReviewHead(line) {
  const t = line.replace(/^[>\s]*/, "").replace(/^#{1,4}\s*/, "").trim();
  if (!t || t.length > 44) return false;
  if (/\]\(/.test(t)) return false; // CTAリンクは見出しではない
  return /(口コミ|レビュー|ユーザーの声|購入者の声|評判)/.test(t);
}

/**
 * 見出しも要約形に統一する。
 * 引用符を外しても「口コミ」というラベルのままだと購入者の発言に読める
 */
function normalizeHead(line) {
  if (line.includes(LABEL)) return line;
  const m = line.match(/^([>\s]*)((?:#{1,4}\s*)?)(\*{0,2})(.+?)(\*{0,2})([:：]?)\s*$/);
  if (!m) return line;
  const [, pre, hash, b1, , b2, colon] = m;
  return `${pre}${hash}${b1}${LABEL}${b2}${colon}`;
}

/** そこでブロックが終わる行（次の見出し・CTAリンク・商品埋め込み・区切り線） */
const isBlockEnd = (line) =>
  /^[>\s]*#{1,4}\s/.test(line) ||
  /^[>\s]*\[.+\]\(/.test(line) ||
  /^[>\s]*\{\{/.test(line) ||
  /^[>\s]*---\s*$/.test(line) ||
  /^[>\s]*\|/.test(line);

/**
 * 行頭の「…」を外す。レビューブロックの中でだけ使うので、
 * 地の文が「」で始まる行（「アイスキャッチ」という機構が…）は巻き込まない。
 * 末尾に続く文（…という設営評価が目立ちます）はそのまま残す
 */
const DEQUOTE = /^([>\s]*(?:[-*][ \t]*)?)[「"]([^「」"]{4,})[」"]([^\n]*)$/;

/**
 * 「…」（40代男性・登山利用）のような属性付きの証言。
 * 年代・性別まで付けた購入者の声は、実在性を確認できない以上いちばん危ない。
 * 引用符と一緒に属性の括弧ごと落とす
 */
const DEMOGRAPHIC = /（\s*[0-9０-９]{1,2}代[^）]{0,24}）\s*$/;

function dequoteBlock(lines) {
  const out = [];
  let changed = 0;
  for (const line of lines) {
    const m = line.match(DEQUOTE);
    if (!m) {
      out.push(line);
      continue;
    }
    const [, prefix, body] = m;
    const tail = m[3].replace(DEMOGRAPHIC, "");
    out.push(`${prefix}${body}${tail}`);
    changed++;
  }
  return { lines: out, changed };
}

const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));

if (REPORT) {
  let n = 0;
  for (const a of articles) {
    if (a.status !== "published") continue;
    for (const m of (a.content || "").matchAll(
      /[^\n]{0,30}(?:レビュー|口コミ|声|人も|という人|と言い切)[^\n]{0,20}「[^」\n]{6,}」[^\n]{0,30}/g
    )) {
      console.log(`  ${a.slug.padEnd(34)} ${m[0].trim().slice(0, 74)}`);
      n++;
    }
  }
  console.log(`\n地の文に埋め込まれた引用: ${n}箇所`);
  console.log("文構造に食い込むので機械的には外せません。記事ごとに手で直す必要があります。");
  process.exit(0);
}

let totalChanged = 0;
const results = [];

for (const a of articles) {
  if (a.status !== "published") continue;
  if (SLUG && a.slug !== SLUG) continue;
  const lines = (a.content || "").split("\n");
  const out = [];
  let changed = 0;
  const samples = [];

  for (let i = 0; i < lines.length; i++) {
    if (!isReviewHead(lines[i])) {
      out.push(lines[i]);
      continue;
    }
    const headIdx = out.length;
    out.push(lines[i]);

    // 見出しの直後から、ブロックが終わるまでを集める
    let j = i + 1;
    const block = [];
    let blanks = 0;
    while (j < lines.length) {
      const l = lines[j];
      if (isBlockEnd(l)) break;
      if (l.trim() === "") {
        // 空行1つは箇条書きの区切りとして許すが、2つ続いたら別の段落
        if (++blanks >= 2) break;
      } else {
        blanks = 0;
      }
      block.push(l);
      j++;
    }
    const r = dequoteBlock(block);
    if (r.changed) {
      const newHead = normalizeHead(out[headIdx]);
      if (newHead !== out[headIdx]) {
        if (samples.length < 4) samples.push({ from: out[headIdx].trim(), to: newHead.trim() });
        out[headIdx] = newHead;
        changed++;
      }
      for (let k = 0; k < block.length; k++) {
        if (block[k] !== r.lines[k] && samples.length < 4)
          samples.push({ from: block[k].trim(), to: r.lines[k].trim() });
      }
      changed += r.changed;
    }
    out.push(...r.lines);
    i = j - 1;
  }

  if (!changed) continue;
  totalChanged += changed;
  results.push({ article: a, slug: a.slug, changed, samples, content: out.join("\n") });
}

results.sort((x, y) => y.changed - x.changed);

for (const r of results) {
  console.log(`\n──── ${r.slug}（${r.changed}行）────`);
  for (const s of r.samples) {
    console.log(`    − ${s.from.slice(0, 88)}`);
    console.log(`    ＋ ${s.to.slice(0, 88)}`);
  }
  if (r.changed > r.samples.length) console.log(`    … 他${r.changed - r.samples.length}行`);
}

console.log(`\n── まとめ ──`);
console.log(`  ${results.length}記事 / ${totalChanged}行の引用符を外します`);
console.log(`  ※ レビュー見出しの直後のブロックのみ。地の文の「」は触りません（--report）`);

if (!APPLY) {
  console.log("\n書き込むには --apply");
  process.exit(0);
}

const ts = new Date().toISOString();
for (const r of results) {
  r.article.content = r.content;
  r.article.updatedAt = ts; // pull時のマージ巻き戻し防止
}
fs.writeFileSync(ARTICLES, JSON.stringify(articles, null, 2));
console.log(`\ndata/articles.json を更新しました（${results.length}記事）`);
console.log("反映: npm run db:sync -- --no-pull");
