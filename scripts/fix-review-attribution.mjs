#!/usr/bin/env node
/**
 * 記事から「Amazonレビュー」という出典表記を外す（Amazonアソシエイト対策）
 *
 * 背景（2026-08-22）: 姉妹サイト japan-shop-helper.com のAmazonアソシエイトが
 * 「Amazonレビューの無許可使用」で閉鎖された。camp-gear-lab は実際に収益が
 * 出ている唯一の口座なので、同じ形を残さない。
 *
 * ここで直すのは**出典表記だけ**。機械的に安全に置換できる範囲に限る。
 *   見出し   「口コミ（楽天・Amazon参考）」→「レビューの傾向（各モールの…僕の要約です）」
 *   引用の尾 「（Amazonレビュー・★4）」→ 削除
 *   文中     「Amazonのレビューでは」等の出典指定 → 「各モールのレビューでは」
 *
 * **引用符付きの購入者の声そのもの（258行）はここでは触らない。**
 * 言い換えは意味を壊すので、記事ごとに人が確認しながら進める。
 * つまりこのスクリプトを流しても違反が完全に消えるわけではない。
 * 「Amazonのレビューだ」と自ら書いている部分を先に消すだけ。
 *
 * レビュー件数・星評価の記述（「Amazonで7,600件のレビューで4.5点」など）は
 * 文の意味に食い込むので自動では直さない。--report で一覧を出す。
 *
 * 使い方:
 *   node scripts/fix-review-attribution.mjs            # 置換案を全部表示
 *   node scripts/fix-review-attribution.mjs --report   # 手動対応が要る箇所の一覧
 *   node scripts/fix-review-attribution.mjs --apply
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const REPORT = argv.includes("--report");

const LABEL = "レビューの傾向（各モールのレビューを読んだ僕の要約です）";

/**
 * 置換ルール。順番に効かせる。
 * 見出しの装飾（> や #### や **）は保ったまま、ラベルだけ差し替える
 */
const RULES = [
  {
    name: "見出しの出典表記",
    // 「口コミ…（…Amazon…）」形式の見出し。装飾を $1 $2 $4 で保つ
    re: /^([>\s]*)((?:#{2,4}\s*)?\*{0,2})((?:口コミ|レビュー|ユーザーの声)[^\n*：:]{0,26})(\*{0,2})([:：]?)[ \t]*$/gm,
    fn: (m, pre, deco, label, deco2, colon) =>
      /amazon/i.test(label) ? `${pre}${deco}${LABEL}${deco2}${colon}` : m,
  },
  {
    name: "「**口コミ**（楽天・Amazonレビューより要約）:」形式",
    re: /\*\*口コミ\*\*（[^）\n]*Amazon[^）\n]*）[:：]?/gi,
    fn: () => `**${LABEL}**`,
  },
  {
    name: "引用末尾の出典（Amazonレビュー・★4）",
    // 「…」（Amazonレビュー・★4） の括弧部分だけ落とす
    re: /（\s*Amazon\s*(?:レビュー|口コミ)[^）\n]*）/gi,
    fn: () => "",
  },
  {
    name: "文中の出典指定",
    re: /Amazon(?:\.co\.jp)?(?:の|での)(レビュー|口コミ)(では|を見ると|によると|には)/gi,
    fn: (m, kind, tail) => `各モールの${kind}${tail}`,
  },
  {
    name: "「楽天・Amazon・個人ブログの公開レビュー」等の列挙",
    re: /楽天・Amazon(?:・([^\s。、]{1,12}))?の公開レビュー/gi,
    fn: (m, extra) => (extra ? `各モールや${extra}の公開レビュー` : "各モールの公開レビュー"),
  },
];

// 自動では直さないが、人が見る必要があるもの
const MANUAL_RE = [
  { name: "レビュー件数・評価点の引用", re: /Amazon[^\n。]{0,20}(?:[0-9,]+件|[0-9.]+点|評価[0-9.]+)/gi },
  { name: "比較表の「Amazon評価」行", re: /^\|[^\n|]*Amazon\s*(?:評価|レビュー)[^\n]*$/gim },
  { name: "見出しに評価点", re: /^#{2,4}[^\n]*Amazon[^\n]*[0-9.]+[^\n]*$/gim },
];

const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));

if (REPORT) {
  let n = 0;
  for (const a of articles) {
    if (a.status !== "published") continue;
    for (const { name, re } of MANUAL_RE) {
      for (const m of (a.content || "").matchAll(re)) {
        console.log(`  ${a.slug.padEnd(32)} [${name}]`);
        console.log(`      ${m[0].trim().slice(0, 92)}`);
        n++;
      }
    }
  }
  console.log(`\n手動で判断が要る箇所: ${n}件`);
  console.log("レビュー件数・評価点はAmazonのデータそのものです。文ごと落とすか、");
  console.log("出典を書かない一般的な言い方に直すかを、記事を読んで決めてください。");
  process.exit(0);
}

let totalHits = 0;
const changed = [];
for (const a of articles) {
  if (a.status !== "published") continue;
  const before = a.content || "";
  let after = before;
  const hits = [];
  for (const { name, re, fn } of RULES) {
    after = after.replace(re, (...args) => {
      const out = fn(...args);
      if (out !== args[0]) hits.push({ name, from: args[0].trim(), to: out.trim() });
      return out;
    });
  }
  if (!hits.length) continue;
  totalHits += hits.length;
  changed.push({ slug: a.slug, hits, after, article: a });
}

for (const c of changed) {
  console.log(`\n──── ${c.slug}（${c.hits.length}箇所）────`);
  const seen = new Set();
  for (const h of c.hits) {
    const key = h.from + "→" + h.to;
    if (seen.has(key)) continue;
    seen.add(key);
    const n = c.hits.filter((x) => x.from === h.from).length;
    console.log(`  [${h.name}]${n > 1 ? ` ×${n}` : ""}`);
    console.log(`    − ${h.from.slice(0, 84)}`);
    console.log(`    ＋ ${h.to ? h.to.slice(0, 84) : "（削除）"}`);
  }
}

console.log(`\n── まとめ ──`);
console.log(`  ${changed.length}記事 / ${totalHits}箇所を置換`);
console.log(`  ※ 「」付きの購入者の声そのものは触っていません（別途、記事ごとに対応）`);

if (!APPLY) {
  console.log("\n書き込むには --apply");
  console.log("手動対応が要る箇所: --report");
  process.exit(0);
}

const ts = new Date().toISOString();
for (const c of changed) {
  c.article.content = c.after;
  c.article.updatedAt = ts; // 進めないと同期のauto-pullで巻き戻る
}
fs.writeFileSync(ARTICLES, JSON.stringify(articles, null, 2));
console.log(`\ndata/articles.json を更新しました（${changed.length}記事）`);
console.log("反映: npm run db:sync -- --no-pull");
