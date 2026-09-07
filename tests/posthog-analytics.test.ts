import test from "node:test";
import assert from "node:assert/strict";
import { isAnalyticsPath, posthogProperties } from "../src/lib/posthogAnalytics.ts";

test("PostHogは公開コンテンツのみ対象にし管理・API・問い合わせを除外する", () => {
  for (const path of ["/", "/articles/test", "/category/lantern", "/gear-guides"]) assert.equal(isAnalyticsPath(path), true);
  for (const path of ["/admin", "/admin/products", "/api/auth", "/contact", "/privacy", "/articles-private", "/en/tools/test"]) assert.equal(isAnalyticsPath(path), false);
});

test("PostHogに購入先URLや入力内容を転送せず商品と位置だけを残す", () => {
  assert.deepEqual(posthogProperties({ product_id: "led-1", merchant: "amazon", placement: "comparison_table", link_url: "https://example.com/?secret=x", link_text: "private", email: "private", price: 5000 }), {
    product_id: "led-1", merchant: "amazon", placement: "comparison_table", price: 5000,
  });
});
