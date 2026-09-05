import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { FEATURED_SLUGS, EDITORIAL_PICKS, getEditorialPicks, getPrimaryProducts, getSeasonalFeature } from "../src/lib/articleEditorial.ts";
import { getProductSpecs } from "../src/lib/productSpecs.ts";
import type { Article, Product } from "../src/lib/types.ts";

const articles: Article[] = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
const products: Product[] = JSON.parse(fs.readFileSync("data/products.json", "utf8"));

test("おすすめ理由と表示順は商品取得順に依存しない", () => {
  const slug = "landlock-vs-landnest-shelter";
  const expected = EDITORIAL_PICKS[slug].map((pick) => pick.productId);
  assert.deepEqual(getEditorialPicks(slug, [...products].reverse()).map((pick) => pick.productId), expected);
  assert.equal(getEditorialPicks(slug, []).length, 0);
  assert.deepEqual(getEditorialPicks("no-editorial-decision", products), []);
  for (const picks of Object.values(EDITORIAL_PICKS)) {
    for (const pick of picks) {
      assert.ok(products.some((product) => product.id === pick.productId));
      assert.ok(pick.audience && pick.reason && pick.caution && pick.evidence);
    }
  }
});

test("クーラーの比較に保冷ボトルを混ぜない", () => {
  const article = articles.find((a) => a.slug === "cooler-box-brand-comparison-2026")!;
  const linked = article.productIds.flatMap((id) => products.filter((p) => p.id === id));
  const primary = getPrimaryProducts(article, linked);
  assert.ok(primary.length > 0);
  assert.ok(primary.every((product) => product.categoryId === "cooler"));
  assert.ok(!primary.some((product) => product.id === "growler-002"));
});

test("特集のリンクは公開記事に限り、四季すべてで有効", () => {
  const slugs = [...FEATURED_SLUGS, ...Array.from({ length: 12 }, (_, i) => getSeasonalFeature(i + 1).slugs).flat()];
  for (const slug of new Set(slugs)) assert.ok(articles.some((a) => a.slug === slug && a.status === "published"), slug);
  assert.equal(getSeasonalFeature(8).label, "夏のキャンプ支度");
  assert.equal(getSeasonalFeature(9).label, "秋のキャンプ支度");
  assert.equal(getSeasonalFeature(12).label, "冬のキャンプ支度");
  assert.equal(getSeasonalFeature(3).label, "春のキャンプ支度");
});

test("空欄・内部キーを除外し、日本語仕様を優先して重複を除く", () => {
  const specs = getProductSpecs({ categoryId: "cooler", specs: {
    weight: "10kg", 容量: "25L", 重量: "9kg", size: "50×30cm", capacity: "20L",
    保冷力: "  ", その他: "—", opening: "広口", api_key: "internal", runtime: "N/A",
  } });
  assert.deepEqual(specs, [["容量", "25L"], ["重量", "9kg"], ["サイズ", "50×30cm"], ["口径", "広口"]]);
  assert.deepEqual(getProductSpecs({ categoryId: "tent", specs: { 素材: "ナイロン", 重量: "10kg", 定員: "4人" } }, 2), [["定員", "4人"], ["重量", "10kg"]]);
});
