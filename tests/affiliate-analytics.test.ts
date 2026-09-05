import test from "node:test";
import assert from "node:assert/strict";
import { collectAffiliateClicks, aggregateAffiliateClicks, type AffiliateClickRow } from "../src/lib/affiliateAnalytics.ts";

const row = (id: number, changes: Partial<AffiliateClickRow> = {}): AffiliateClickRow => ({
  id, product_id: "test-mat", store: "amazon", page_path: "/articles/test-guide",
  clicked_at: "2026-09-05T00:00:00Z", placement: "product_card", ...changes,
});

test("取得上限より多いクリックを欠落なく集計し、短いページも末尾と決めつけない", async () => {
  const source = Array.from({ length: 1107 }, (_, i) => row(i * 2 + 1));
  const actual = await collectAffiliateClicks(async (cursor) => source.filter((r) => r.id > cursor).slice(0, 97));
  assert.deepEqual(actual, source);
});

test("ページ取得失敗やカーソル重複をゼロ件・一部成功として返さない", async () => {
  await assert.rejects(collectAffiliateClicks(async (cursor) => {
    if (cursor) throw new Error("database unavailable");
    return [row(1)];
  }), /database unavailable/);
  await assert.rejects(collectAffiliateClicks(async () => [row(1)]), /cursor/);
});

test("記事・商品・位置の組み合わせを分け、販売店別の合計を保持する", () => {
  const result = aggregateAffiliateClicks([
    row(1), row(2, { store: "rakuten" }), row(3, { placement: "article_end" }),
    row(4, { product_id: "test-pillow" }), row(5, { page_path: "/articles/other" }),
  ], new Map([["test-guide", "テスト用記事"]]), new Map([["test-mat", "テスト用マット"]]));
  assert.equal(result.total, 5);
  assert.equal(result.journeyRanking.length, 4);
  assert.equal(result.journeyRanking[0].clicks, 2);
  assert.equal(result.journeyRanking[0].name, "テスト用マット");
  assert.equal(result.journeyRanking[0].stores.rakuten, 1);
  assert.equal(result.articleRanking[0].clicks, 4);
  assert.equal(result.productRanking[0].clicks, 4);
});

test("不正な保存済みURLを管理画面の外部リンクにしない", () => {
  const result = aggregateAffiliateClicks([
    row(1, { page_path: "//example.com" }), row(2, { page_path: "javascript:alert(1)" }),
    row(3, { page_path: "/articles/test-guide?private=value", store: "__proto__", placement: "__proto__" }),
  ], new Map(), new Map());
  assert.ok(result.articleRanking.every((r) => !r.path.startsWith("//") && !r.path.includes("?") && !r.path.includes("javascript:")));
  assert.equal(result.byStore["__proto__"], 1);
  assert.equal(result.byPlacement["__proto__"], 1);
});
