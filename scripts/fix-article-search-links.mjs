#!/usr/bin/env node
/**
 * 記事本文にベタ書きされた「検索ページ行き」アフィリエイトリンクを商品直リンクへ
 *
 * 背景（2026-08-10）: products.json の affiliateUrl / amazonUrl は
 * 先週すべて商品ページ直リンクに直したが、記事本文にベタ書きされたURLは
 * 手つかずのままだった。走査すると公開記事に108件残っていた。
 * ほとんどが「楽天で口コミをもっと見る →」形式のCTAリンク。
 *
 * products.json のときとは性質が少し違う:
 *  - 口コミ導線としては検索ページも一応機能する（レビュー付き出品が並ぶ）ので、
 *    完全な行き止まりではない。ただし商品ページ直リンクのほうが成約率は上がる
 *  - ふるさと納税記事の「◯◯を探す →」は検索ページのままが正しい
 *
 * 対象商品はURLに埋まった「検索語」を商品名に突き合わせて決める。
 * 当初はリンク直前の {{product:id}} を使ったが、ランキング記事のように
 * マーカーを持たない構成だと総崩れになった（summer-family-tent-ranking では
 * 4件すべてが記事冒頭の別商品に紐づいた）。検索語のほうが根拠として強い。
 *
 * 取り違えを防ぐ3つのガード:
 *  - 候補はその記事が扱う商品に限定（一般語で無関係な商品を掴まない）
 *  - 一致率70%未満は見送り
 *  - 1位と2位の差が15%未満なら見送り（T-230 と T-230A のような同型品）
 *
 * 使い方:
 *   node scripts/fix-article-search-links.mjs            # dry-run
 *   node scripts/fix-article-search-links.mjs --verbose  # 全件の内訳
 *   node scripts/fix-article-search-links.mjs --apply
 *
 * 反映後: npm run db:sync -- --no-pull
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { tokenOverlap } from "../src/lib/product-match.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const REPORT = path.join(ROOT, "scratch", "article-link-fixes.json");

const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const VERBOSE = argv.includes("--verbose");

// 「ふるさと納税◯◯を探す」は検索結果を見せるのが目的。直リンク化すると意味が変わる
const SKIP_SLUGS = new Set(["furusato-tax-camp-gear"]);

const decode = (s) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

const isSearchLink = (url) => {
  const u = decode(url);
  return /search\.rakuten\.co\.jp\/search\/mall/.test(u) || /amazon\.co\.jp\/s\?/.test(u);
};
const storeOf = (url) => (/rakuten/.test(url) ? "楽天" : "Amazon");

/** 検索語を取り出す。商品との照合に使う */
function keywordOf(url) {
  const u = decode(url);
  const m = u.match(/search\/mall\/([^/?&]*)/) || u.match(/[?&]k=([^&]*)/);
  return m ? decode(m[1]).replace(/\+/g, " ").trim() : "";
}

/** 商品ページ直リンクを持っているか（検索URL・空は不可） */
function directLink(product, store) {
  const url = store === "楽天" ? product?.affiliateUrl : product?.amazonUrl;
  if (!url || !String(url).trim()) return null;
  if (isSearchLink(url)) return null;
  return url;
}

const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));
const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const byId = new Map(products.map((p) => [p.id, p]));

const fixes = [];
const skipped = [];

for (const a of articles) {
  const content = a.content || "";
  if (!content) continue;

  // 対象商品は「検索語」を商品名に突き合わせて決める。
  // 当初は直前の {{product:id}} を使ったが、ランキング記事のように
  // マーカーを使わない構成だと総崩れになった（summer-family-tent-ranking では
  // 4件すべてが記事冒頭の別商品に紐づいた）。検索語のほうが根拠として強い。
  //
  // 候補はこの記事が扱う商品に限定する。全商品から探すと
  // 「シェラカップ」のような一般語で無関係な商品を掴む
  const scoped = new Set(a.productIds || []);
  for (const mm of content.matchAll(/\{\{(?:product|comparison|ranking):([^}|]+)\}\}/g)) {
    for (const id of mm[1].split(",")) scoped.add(id.trim());
  }
  const candidates = [...scoped].map((id) => byId.get(id)).filter(Boolean);

  /** 検索語に最も近い商品。2位と差がつかないものは採用しない */
  function resolveByKeyword(keyword) {
    if (!keyword) return { best: null, score: 0, runnerUp: 0 };
    const ranked = candidates
      .map((p) => ({ p, s: tokenOverlap(keyword, p.name) }))
      .sort((x, y) => y.s - x.s);
    return {
      best: ranked[0]?.p ?? null,
      score: ranked[0]?.s ?? 0,
      runnerUp: ranked[1]?.s ?? 0,
    };
  }

  for (const m of content.matchAll(/\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)/g)) {
    const [full, label, url] = m;
    if (!isSearchLink(url)) continue;

    const store = storeOf(url);
    const keyword = keywordOf(url);
    const base = {
      slug: a.slug,
      status: a.status,
      label,
      store,
      keyword,
      oldUrl: url,
    };

    if (SKIP_SLUGS.has(a.slug)) {
      skipped.push({ ...base, reason: "検索ページのままが正しい記事" });
      continue;
    }

    const { best: product, score, runnerUp } = resolveByKeyword(keyword);
    const overlap = score;

    if (!product || score < 0.7) {
      skipped.push({
        ...base,
        overlap: Math.round(score * 100),
        candidate: product?.name ?? null,
        reason: `検索語に一致する商品が無い（最高${Math.round(score * 100)}%）`,
      });
      continue;
    }
    // 同率首位が並ぶのは同型商品の取り違えが起きやすい場面。人間に回す
    if (score - runnerUp < 0.15 && runnerUp >= 0.7) {
      skipped.push({
        ...base,
        overlap: Math.round(score * 100),
        candidate: product.name,
        reason: `候補が競合（${Math.round(score * 100)}% vs ${Math.round(runnerUp * 100)}%）。取り違えの疑い`,
      });
      continue;
    }

    const newUrl = directLink(product, store);
    if (!newUrl) {
      skipped.push({
        ...base,
        id: product.id,
        productName: product.name,
        reason: `${store}に商品ページ直リンクが無い（この商品は${store}で買えない可能性）`,
      });
      continue;
    }

    fixes.push({
      ...base,
      id: product.id,
      productName: product.name,
      overlap: Math.round(overlap * 100),
      newUrl,
      markdown: full,
    });
  }
}

// ─── 出力 ───────────────────────────────────────────
console.log(`記事内の検索ページ行きリンク: ${fixes.length + skipped.length}件（${APPLY ? "APPLY" : "dry-run"}）\n`);

const byArticle = new Map();
for (const f of fixes) {
  if (!byArticle.has(f.slug)) byArticle.set(f.slug, []);
  byArticle.get(f.slug).push(f);
}

console.log(`── 差し替え対象 ${fixes.length}件 ──`);
for (const [slug, list] of byArticle) {
  console.log(`\n  ${slug}（${list.length}件）`);
  for (const f of list) {
    console.log(`    ${f.store} 「${f.label}」`);
    console.log(`      ${f.productName.slice(0, 38)}  一致率${f.overlap}%`);
    if (VERBOSE) console.log(`      → ${f.newUrl.slice(0, 90)}`);
  }
}

const reasons = {};
for (const s of skipped) reasons[s.reason] = (reasons[s.reason] || 0) + 1;
console.log(`\n── 見送り ${skipped.length}件 ──`);
for (const [r, n] of Object.entries(reasons).sort((a, b) => b[1] - a[1])) {
  console.log(`  ${String(n).padStart(3)}件  ${r}`);
}

const suspicious = skipped.filter((s) => /取り違えの疑い|一致する商品が無い/.test(s.reason));
if (suspicious.length > 0) {
  console.log("\n【要確認】自動では触らないもの");
  for (const s of suspicious) {
    console.log(`  ${s.slug}  「${s.keyword.slice(0, 32)}」 → ${(s.candidate || "候補なし").slice(0, 30)}（${s.overlap}%）`);
  }
}

if (APPLY) {
  let applied = 0;
  for (const a of articles) {
    const list = fixes.filter((f) => f.slug === a.slug);
    if (list.length === 0) continue;
    let c = a.content;
    for (const f of list) {
      const replacement = `[${f.label}](${f.newUrl})`;
      if (!c.includes(f.markdown)) {
        console.log(`  ⚠ 該当箇所が見つからず: ${f.slug} 「${f.label}」`);
        continue;
      }
      c = c.replace(f.markdown, replacement);
      applied++;
    }
    a.content = c;
    a.updatedAt = new Date().toISOString(); // 進めないと同期のauto-pullで巻き戻る
  }
  fs.writeFileSync(ARTICLES, JSON.stringify(articles, null, 2));
  console.log(`\narticles.json 反映: ${applied}件 / ${byArticle.size}記事`);
  console.log("次: git diff で確認 → npm run db:sync -- --no-pull");
} else {
  console.log(`\ndry-run完了: 差し替え${fixes.length}件 / 見送り${skipped.length}件`);
  console.log("適用: --apply");
}

fs.mkdirSync(path.dirname(REPORT), { recursive: true });
fs.writeFileSync(REPORT, JSON.stringify({ ranAt: new Date().toISOString(), fixes, skipped }, null, 2));
console.log(`レポート: ${REPORT}`);
