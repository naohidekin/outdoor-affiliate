import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// 本文のタグは、解決できないと**黙って消える**（2026-09-03に発覚）。
//
// ArticleContent.tsx は productMap.get(id) が空なら null を返す。記号が
// 露出しないための親切な作りだが、代わりに商品カードごと消える。読者には
// 何も出ず、こちらもHTMLを見に行くまで気づけない。
//
// productMap の中身は getProductsByIds(article.productIds) なので、
// 本文にタグを足しただけでは出ない。**productIds にも足す必要がある。**
// 天井対策で6記事にCTAを足したとき、実際にこれで12枚のカードが消えていた。
//
// {{price:ID}} も同じ穴で、解決できないと空文字になる。カードと違って
// 文の途中から数字だけが消えるので、なお気づきにくい。
// price は `p?.price ? ... : ""` なので、**価格0の商品でも空になる**。
//
// このテストは3つを見る。
//   1. タグのIDが products.json に存在すること（打ち間違い・プレースホルダ）
//   2. そのIDが記事の productIds に入っていること（実際に出ること）
//   3. {{price:}} の参照先に価格が入っていること

type Article = { slug: string; content: string; productIds?: string[] };
type Product = { id: string; price?: number };

const ROOT = path.join(import.meta.dirname, "..");
const read = <T,>(f: string): T[] =>
  JSON.parse(fs.readFileSync(path.join(ROOT, "data", f), "utf8"));

// 既知の壊れ。空であること。増やさないこと。
// 2026-09-04: shimano-002（シマノ スペーザ ベイシス 350）を登録して解消した
const KNOWN_MISSING: string[] = [];

// 下書きの構成メモには `{{comparison:tarp-XXX,...}}` のように
// **コードスパンの中に**書かれたタグがある。あれは説明であって出力ではない
// ので、コードブロックとコードスパンを外してから拾う（2026-09-04）
const stripCode = (s: string): string =>
  s.replace(/```[\s\S]*?```/g, "").replace(/`[^`\n]*`/g, "");

const idsFor = (content: string, kinds: string): string[] => {
  const out: string[] = [];
  const re = new RegExp(`\\{\\{(?:${kinds}):([^}]+)\\}\\}`, "g");
  for (const m of stripCode(content).matchAll(re))
    out.push(...m[1].split(",").map((s) => s.trim()).filter(Boolean));
  return [...new Set(out)];
};

const allTagIds = (content: string) => idsFor(content, "product|comparison|price");
const priceTagIds = (content: string) => idsFor(content, "price");

const articles = () => read<Article>("articles.json").filter((a) => !KNOWN_MISSING.includes(a.slug));

test("本文のタグのIDが products.json に存在する", () => {
  const products = new Set(read<Product>("products.json").map((p) => p.id));
  const bad: string[] = [];
  for (const a of articles())
    for (const id of allTagIds(a.content)) if (!products.has(id)) bad.push(`${a.slug}: ${id}`);
  assert.deepEqual(
    bad,
    [],
    `商品が見つからないタグです。カードや価格は黙って消えます:\n${bad.join("\n")}`
  );
});

test("本文のタグが productIds に登録されている", () => {
  const bad: string[] = [];
  for (const a of articles()) {
    const registered = new Set(a.productIds ?? []);
    for (const id of allTagIds(a.content)) if (!registered.has(id)) bad.push(`${a.slug}: ${id}`);
  }
  assert.deepEqual(
    bad,
    [],
    `productIds に無いので出ません。articles.json の productIds に足してください:\n${bad.join("\n")}`
  );
});

test("{{price:}} の参照先に価格が入っている", () => {
  const price = new Map(read<Product>("products.json").map((p) => [p.id, p.price ?? 0]));
  const bad: string[] = [];
  for (const a of articles())
    for (const id of priceTagIds(a.content))
      if (!price.get(id)) bad.push(`${a.slug}: ${id}（価格 ${price.get(id) ?? "未登録"}）`);
  assert.deepEqual(bad, [], `価格が0か未登録です。本文から金額だけが消えます:\n${bad.join("\n")}`);
});
