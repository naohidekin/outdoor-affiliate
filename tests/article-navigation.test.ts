import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { getNextReads, NEXT_READS } from "../src/lib/articleNextReads.ts";
import { hasProductComparison, trackArticleNavigation } from "../src/lib/articleNavigation.ts";
import type { Article } from "../src/lib/types.ts";

const articles: Article[] = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
const make = (id: string, changes: Partial<Article> = {}): Article => ({
  id, slug: id, title: id, categoryId: "tent", content: "", excerpt: "", productIds: [], status: "published", createdAt: "2026-01-01", updatedAt: "2026-01-01", publishedAt: "2026-01-01", ...changes,
});

test("編集した導線は公開記事に到達し、取得順・公開日の新しさに依存しない", () => {
  for (const [slug, links] of Object.entries(NEXT_READS)) {
    const current = articles.find((article) => article.slug === slug)!;
    assert.ok(current);
    for (const link of links) assert.ok(articles.some((article) => article.slug === link.slug && article.status === "published"), link.slug);
    const result = getNextReads(current, [...articles].reverse());
    assert.deepEqual(result.slice(0, links.length).map(({ article }) => article.slug), links.map((link) => link.slug));
  }
});

test("古い共通商品の記事を無関係な新着より優先し、タグ・カテゴリで補完する", () => {
  const current = make("current", { productIds: ["a"], tags: ["NANGA", "キャンプ"] });
  const candidates = [
    make("new-unrelated", { categoryId: "knife", tags: ["キャンプ"], publishedAt: "2026-09-05" }),
    make("same-category", { publishedAt: "2026-09-05" }),
    make("same-topic", { categoryId: "sleep", tags: [" nanga "] }),
    make("same-product", { categoryId: "sleep", productIds: ["a"], publishedAt: "2020-01-01" }),
  ];
  assert.deepEqual(getNextReads(current, candidates).map(({ article }) => article.id), ["same-product", "same-topic", "same-category"]);
});

test("現在の記事・下書き・重複・無関係な記事を除外し、不足を無理に埋めない", () => {
  const current = make("current");
  const candidates = [current, make("draft", { status: "draft" }), make("same"), make("same"), make("alias", { slug: "same" }), make("unrelated", { categoryId: "knife", tags: ["2026年版", "比較"] })];
  assert.deepEqual(getNextReads(current, candidates).map(({ article }) => article.id), ["same"]);
  assert.deepEqual(getNextReads(current, candidates, 0), []);
  const curatedCurrent = make("curated", { slug: "landlock-vs-landnest-shelter" });
  assert.equal(getNextReads(curatedCurrent, [make("fallback")])[0].article.slug, "fallback");
});

test("表示できる商品がある比較タグだけ移動先を持つ", () => {
  const products = [{ id: "a" }];
  assert.equal(hasProductComparison("{{comparison:missing}}", products), false);
  assert.equal(hasProductComparison("{{comparison:missing}}\n{{comparison: a, b }}", products), true);
  assert.equal(hasProductComparison("{{product:a}}", products), false);
  assert.equal(hasProductComparison("{{comparison:a}}", []), false);
});

test("計測は記事と移動先だけを送り、ブラウザ・GA4がなくても失敗しない", () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "window");
  try {
    Reflect.deleteProperty(globalThis, "window");
    assert.doesNotThrow(() => trackArticleNavigation("source", "toc", "reading_nav"));
    Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
    assert.doesNotThrow(() => trackArticleNavigation("source", "toc", "reading_nav"));
    const events: unknown[][] = [];
    Object.defineProperty(globalThis, "window", { configurable: true, value: { gtag: (...args: unknown[]) => events.push(args) } });
    trackArticleNavigation("source", "article", "next_reads", "target");
    assert.deepEqual(events, [["event", "article_navigation", { article_slug: "source", navigation_area: "next_reads", destination: "article", target_slug: "target" }]]);
    Object.defineProperty(globalThis, "window", { configurable: true, value: { gtag: () => { throw new Error("blocked"); } } });
    assert.doesNotThrow(() => trackArticleNavigation("source", "products", "reading_nav"));
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "window", descriptor);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
