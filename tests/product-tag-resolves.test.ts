import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// 本文の {{product:ID}} は、解決できないと**黙って消える**（2026-09-03に発覚）。
//
// ArticleContent.tsx は productMap.get(id) が空なら null を返す。記号が
// 露出しないための親切な作りだが、代わりに商品カードごと消える。読者には
// 何も出ず、こちらもHTMLを見に行くまで気づけない。
//
// productMap の中身は getProductsByIds(article.productIds) なので、
// 本文にタグを足しただけでは出ない。**productIds にも足す必要がある。**
// 天井対策で6記事にCTAを足したとき、実際にこれで12枚のカードが消えていた。
//
// このテストは2つを見る。
//   1. タグのIDが products.json に存在すること（打ち間違い・プレースホルダ）
//   2. そのIDが記事の productIds に入っていること（カードが実際に出る）

type Article = { slug: string; content: string; productIds?: string[] };
type Product = { id: string };

const ROOT = path.join(import.meta.dirname, "..");
const read = <T,>(f: string): T[] =>
  JSON.parse(fs.readFileSync(path.join(ROOT, "data", f), "utf8"));

// 既知の壊れ。直したらここから消す。増やさないこと。
// 既知の壊れ。空であること。増やさないこと。
// 2026-09-04: shimano-002（シマノ スペーザ ベイシス 350）を登録して解消した
const KNOWN_MISSING: string[] = [];

// 下書きの構成メモには `{{comparison:tarp-XXX,...}}` のように
// **コードスパンの中に**書かれたタグがある。あれは説明であって出力ではない
// ので、コードブロックとコードスパンを外してから拾う（2026-09-04）
const stripCode = (s: string): string =>
  s.replace(/```[\s\S]*?```/g, "").replace(/`[^`\n]*`/g, "");

const tagIds = (content: string): string[] => {
  const out: string[] = [];
  for (const m of stripCode(content).matchAll(/\{\{(?:product|comparison):([^}]+)\}\}/g))
    out.push(...m[1].split(",").map((s) => s.trim()).filter(Boolean));
  return [...new Set(out)];
};

test("本文の商品タグのIDが products.json に存在する", () => {
  const products = new Set(read<Product>("products.json").map((p) => p.id));
  const bad: string[] = [];
  for (const a of read<Article>("articles.json")) {
    if (KNOWN_MISSING.includes(a.slug)) continue;
    for (const id of tagIds(a.content))
      if (!products.has(id)) bad.push(`${a.slug}: ${id}`);
  }
  assert.deepEqual(bad, [], `商品が見つからないタグです。カードは黙って消えます:\n${bad.join("\n")}`);
});

test("本文の商品タグが productIds に登録されている", () => {
  const bad: string[] = [];
  for (const a of read<Article>("articles.json")) {
    if (KNOWN_MISSING.includes(a.slug)) continue;
    const registered = new Set(a.productIds ?? []);
    for (const id of tagIds(a.content))
      if (!registered.has(id)) bad.push(`${a.slug}: ${id}`);
  }
  assert.deepEqual(
    bad,
    [],
    `productIds に無いので商品カードが出ません。articles.json の productIds に足してください:\n${bad.join("\n")}`
  );
});
