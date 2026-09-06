import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { getAvailableGearGuides, GEAR_GUIDES } from "../src/lib/gearGuides.ts";
import { getProductMerchants } from "../src/lib/productMerchants.ts";
import type { Article, Product } from "../src/lib/types.ts";

const articles: Article[] = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
const products: Product[] = JSON.parse(fs.readFileSync("data/products.json", "utf8"));

test("目的別ガイドは実在する公開記事につながる", () => {
  const guides = getAvailableGearGuides(articles);
  assert.equal(guides.length, GEAR_GUIDES.length);
  for (const guide of GEAR_GUIDES) {
    for (const link of guide.links) assert.ok(articles.some((a) => a.slug === link.slug && a.status === "published"), link.slug);
  }
});

test("記事が非公開・削除されたら、そのリンクと空のガイドを除外する", () => {
  const article = articles.find((a) => a.slug === "kids-sleeping-bag-ranking")!;
  assert.deepEqual(getAvailableGearGuides([]), []);
  assert.deepEqual(getAvailableGearGuides([{ ...article, status: "draft" }]), []);
  const guides = getAvailableGearGuides([article]);
  assert.equal(guides.length, 1);
  assert.equal(guides[0].id, "sleep");
  assert.deepEqual(guides[0].links.map((link) => link.slug), [article.slug]);
});

test("販売店の順序を保ち、欠けた販売店を除いた実際の順番を計測する", () => {
  const product = { ...products[0], price: 50000, amazonUrl: "https://www.amazon.co.jp/dp/B000000001/?tag=example-22", affiliateUrl: "https://hb.afl.rakuten.co.jp/example?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fshop%2Fitem", yahooUrl: "https://shopping.yahoo.co.jp/example" };
  const high = getProductMerchants(product);
  assert.deepEqual(high.map((x) => [x.store, x.rank]), [["amazon", 1], ["rakuten", 2], ["yahoo", 3]]);
  assert.equal(high[0].href, product.amazonUrl);
  assert.equal(high[1].href, product.affiliateUrl);
  assert.deepEqual(getProductMerchants({ ...product, price: 1000, affiliateUrl: "", yahooUrl: "" }).map((x) => [x.store, x.rank]), [["amazon", 1]]);
  assert.deepEqual(getProductMerchants({ ...product, amazonUrl: "javascript:alert(1)", affiliateUrl: "", yahooUrl: "https://user:pass@example.com" }), []);
});
