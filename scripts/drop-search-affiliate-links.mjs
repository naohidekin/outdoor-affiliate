#!/usr/bin/env node
/**
 * 検索結果ページに飛ぶ楽天アフィリエイトリンクを外す
 *
 * 背景（2026-09-02）: 公開記事に載る商品45件の「楽天で見る」が、商品ページ
 * ではなく楽天の検索結果ページに着地していた。読者は自分で探し直すことに
 * なる。楽天アフィリエイトパートナー規約 第8条2項は、リンク切れまたは
 * リンク先の過誤を見つけたら「直ちにアフィリエイトリンクの更新あるいは
 * 削除を行わなければならない」と定めている。放置は規約違反にあたる。
 *
 * 本来の直し方は scripts/fix-search-affiliate-links.mjs で、楽天Ichiba APIから
 * 実商品ページを引いて張り替える。ただし 2026-09-02 時点でAPIが
 * `API Configuration not found` を返して使えない（アプリのAPIアクセス
 * スコープに楽天市場APIのチェックは入っている。エンドポイント側の問題と
 * みられる）。復旧を待つ間、規約違反の状態を残さないための退避手段。
 *
 * 規約は「更新**あるいは削除**」なので、削除でも義務は果たせる。
 * 対象45件はすべて Amazon か Yahoo のリンクを持っているため、楽天リンクを
 * 外しても読者は買える。むしろ ¥25,000超の商品は楽天だと成果報酬が
 * ¥1,000で頭打ちになるので、Amazonへ寄るぶんには不利にならない。
 *
 * 外したURLは git の履歴に残る。検索キーワードは商品名から再構成できるので、
 * API復旧後に fix-search-affiliate-links.mjs で張り直せる。
 *
 * 使い方:
 *   node scripts/drop-search-affiliate-links.mjs            # dry-run
 *   node scripts/drop-search-affiliate-links.mjs --apply
 *   node scripts/drop-search-affiliate-links.mjs --all      # 下書き掲載分も含める
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const APPLY = process.argv.includes("--apply");
const ALL = process.argv.includes("--all");

const read = (f) => {
  const raw = JSON.parse(fs.readFileSync(path.join(ROOT, "data", f), "utf8"));
  return Array.isArray(raw) ? raw : raw[Object.keys(raw)[0]];
};

const products = read("products.json");
const articles = read("articles.json");

/** 公開記事に実際に載る商品ID */
const shown = new Set();
for (const a of articles) {
  if (!ALL && a.status !== "published") continue;
  for (const id of a.productIds ?? []) shown.add(id);
  for (const m of (a.content ?? "").matchAll(
    /\{\{(?:product|comparison|ranking):([a-z0-9,\-]+)\}\}/g
  )) {
    for (const id of m[1].split(",")) shown.add(id);
  }
}

/**
 * 遷移先が検索結果ページか、URLとして壊れているか。
 * `pc` パラメータに元の商品URLが入っている
 */
function isBroken(url) {
  try {
    const pc = new URL(url).searchParams.get("pc");
    if (!pc) return true;
    return /search\.rakuten\.co\.jp/.test(decodeURIComponent(pc));
  } catch {
    return true; // URLとして壊れている
  }
}

const targets = products.filter(
  (p) => shown.has(p.id) && p.affiliateUrl && isBroken(p.affiliateUrl)
);

console.log(`${ALL ? "全記事" : "公開記事"}に載る商品のうち、検索ページ行き: ${targets.length}件\n`);

const stranded = [];
for (const p of targets) {
  const alt = p.amazonUrl ? "Amazon" : p.yahooUrl ? "Yahoo" : null;
  if (!alt) stranded.push(p.id);
  console.log(
    `  ¥${String(p.price ?? 0).padStart(7)}  ${(alt ?? "★代替なし").padEnd(8)} ` +
      `${p.id.padEnd(30)} ${(p.name ?? "").slice(0, 30)}`
  );
}

if (stranded.length > 0) {
  // 楽天リンクを外すと買えなくなる商品。ProductCard は specs の「入手方法」に
  // 逃がせるが、無いなら外してはいけない
  const noEscape = stranded.filter((id) => {
    const p = products.find((x) => x.id === id);
    return !p.specs?.["入手方法"];
  });
  if (noEscape.length > 0) {
    console.error(
      `\n中止: 外すと購入手段が無くなる商品があります: ${noEscape.join(", ")}\n` +
        `Amazon/Yahooのリンクを入れるか、specs に「入手方法」を書いてから再実行してください`
    );
    process.exit(1);
  }
}

if (!APPLY) {
  console.log("\ndry-run です。--apply で外します");
  process.exit(0);
}

const now = new Date().toISOString();
for (const p of targets) {
  delete p.affiliateUrl;
  // updatedAt を進めないと db:sync で反映されない
  p.updatedAt = now;
}
fs.writeFileSync(
  path.join(ROOT, "data", "products.json"),
  JSON.stringify(products, null, 2) + "\n"
);
console.log(`\n${targets.length}件の楽天リンクを外しました`);
