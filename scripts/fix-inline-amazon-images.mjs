#!/usr/bin/env node
/**
 * 記事本文に直貼りされたAmazon画像を商品カードに置き換える
 *
 * 背景（2026-08-22）: 姉妹サイトが「Amazon画像の無許可使用」を理由の1つとして
 * アソシエイトを閉鎖された。camp-gear-lab の記事本文には
 *   ![スタンレー クラシック真空グロウラー 1.9L](https://m.media-amazon.com/images/I/...)
 * の形で画像を直貼りしている箇所が9つある（4記事）。
 *
 * 単に消すのではなく `{{product:id}}` に置き換える。理由は3つ:
 *   見た目が保たれる（商品カードとして画像・価格・購入ボタンが出る）
 *   画像URLが products.json の管理下に入り、あとから一括で差し替えられる
 *   購入導線がむしろ強くなる（直貼り画像はリンクですらなかった）
 *
 * 9件すべて、直後の見出しがその商品の紹介になっている。置き換えても
 * 文脈が壊れないことを1件ずつ確認済み。
 *
 * なお 2件（solo-tarp-ranking）は ASIN から組み立てた /images/P/ 形式で、
 * 二重に問題がある形だった。
 *
 * 使い方:
 *   node scripts/fix-inline-amazon-images.mjs           # 置き換え案を表示
 *   node scripts/fix-inline-amazon-images.mjs --apply
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const APPLY = process.argv.includes("--apply");

/** alt テキスト → 商品ID。名前一致で機械的に引いた結果を固定してある */
const MAP = {
  "スタンレー クラシック真空グロウラー 1.9L": "growler-001",
  "テンマクデザイン ムササビウイング 13ft TC": "tarp-004",
  "ユニフレーム REVOタープ II M": "tarp-005",
  "モーラナイフ Companion MG Stainless": "knife-001",
  "モーラナイフ Garberg Full Tang": "knife-002",
  "ベアー＆サン ブッシュクラフトナイフ": "knife-003",
  "オピネル フォールディングナイフ No.8": "knife-004",
  "バークリバー ブラボー1": "knife-005",
  "スタンレー ウォータージャグ 7.5L": "water-jug-stanley-7.5l",
};

const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));
const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const productIds = new Set(products.map((p) => p.id));

const IMG = /!\[([^\]]*)\]\((https?:\/\/[^)\s]*amazon[^)\s]*)\)/gi;

let total = 0;
let unmapped = 0;
const touched = new Set();

for (const a of articles) {
  if (a.status !== "published") continue;
  const found = [...(a.content || "").matchAll(IMG)];
  if (!found.length) continue;

  let next = a.content;
  const lines = [];
  for (const m of found) {
    const alt = m[1].trim();
    const id = MAP[alt];
    if (!id) {
      console.log(`  ⚠ ${a.slug}: 対応する商品が分かりません alt=${JSON.stringify(alt.slice(0, 40))}`);
      unmapped++;
      continue;
    }
    if (!productIds.has(id)) {
      console.log(`  ⚠ ${a.slug}: 商品IDが存在しません ${id}`);
      unmapped++;
      continue;
    }
    // 記事のどこかに既に同じ商品カードがあるなら、画像を消すだけにする。
    // 直後120字しか見ていなかったせいで、growler-001 が2回、
    // water-jug-stanley-7.5l が3回出る状態を作りかけた
    const dup = next.includes(`{{product:${id}}}`);
    const to = dup ? "" : `{{product:${id}}}`;
    const at = next.indexOf(m[0]);
    next = next.slice(0, at) + to + next.slice(at + m[0].length);
    // 消した跡で空行が続いたらそこだけ詰める。記事全体に正規化をかけると
    // 無関係な箇所の整形まで変わる
    if (!to) {
      const head = next.slice(0, at).replace(/\n{2,}$/, "\n\n");
      const tail = next.slice(at).replace(/^\n+/, "");
      next = head + tail;
    }
    lines.push({ alt, id, url: m[2], dup });
    total++;
  }

  if (next === a.content) continue;
  a.__next = next;
  touched.add(a.slug);

  console.log(`\n──── ${a.slug}（${lines.length}箇所）────`);
  for (const l of lines) {
    console.log(`  − ![${l.alt.slice(0, 34)}](${l.url.slice(0, 56)}…)`);
    console.log(`  ＋ ${l.dup ? "（削除。直後に同じ商品カードが既にある）" : `{{product:${l.id}}}`}`);
  }
}

console.log(`\n── まとめ ──`);
console.log(`  ${touched.size}記事 / ${total}箇所を置き換え`);
if (unmapped) console.log(`  ⚠ 対応が取れなかった: ${unmapped}箇所（手で確認してください）`);

if (!APPLY) {
  console.log("\n書き込むには --apply");
  process.exit(0);
}

const ts = new Date().toISOString();
let n = 0;
for (const a of articles) {
  if (!a.__next) continue;
  a.content = a.__next;
  delete a.__next;
  a.updatedAt = ts; // pull時のマージ巻き戻し防止
  n++;
}
for (const a of articles) delete a.__next;
fs.writeFileSync(ARTICLES, JSON.stringify(articles, null, 2));
console.log(`\ndata/articles.json を更新しました（${n}記事）`);
console.log("反映: npm run db:sync -- --no-pull");
