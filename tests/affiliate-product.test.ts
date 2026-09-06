import test from "node:test";
import assert from "node:assert/strict";
import { affiliateProductKey, buildAffiliateProductIndex, resolveAffiliateProduct, isInternalArticleLink } from "../src/lib/affiliateProduct.ts";

const target = "https://item.rakuten.co.jp/waqoutdoor/waq-hpa1/";
const affiliate = (url: string) => `https://hb.afl.rakuten.co.jp/ichiba/tracking/?pc=${encodeURIComponent(url)}&link_type=text`;
const product = { id: "pump-1", name: "テスト用ポンプ", affiliateUrl: affiliate(target), amazonUrl: "https://www.amazon.co.jp/dp/B000000001?tag=test" };

test("楽天の広告形式・クエリが変わっても同じ商品になる", () => {
  const key = "rakuten:waqoutdoor/waq-hpa1";
  assert.equal(affiliateProductKey(target), key);
  assert.equal(affiliateProductKey(affiliate(target)), key);
  assert.equal(affiliateProductKey(target + "?utm_source=example#details"), key);
  assert.equal(affiliateProductKey("https://www.amazon.co.jp/gp/product/b000000001/ref=example"), "amazon:B000000001");
});

test("別サイトのクエリ・似たドメイン・検索・コレクションから商品を推測しない", () => {
  for (const url of ["https://example.com/?url=" + target, "https://item.rakuten.co.jp.example.com/waqoutdoor/waq-hpa1/", "https://www.amazon.co.jp/s?k=mat", "https://room.rakuten.co.jp/collection", "https://amzn.to/unknown", affiliate("https://example.com/dp/B000000001"), "javascript:alert(1)"]) {
    assert.equal(affiliateProductKey(url), null, url);
  }
  assert.equal(isInternalArticleLink("https://example.com/?ref=camp-gear-lab.com"), false);
  assert.equal(isInternalArticleLink("//example.com/"), false);
  assert.equal(isInternalArticleLink("/articles/mat"), true);
  assert.equal(isInternalArticleLink("https://camp-gear-lab.com/articles/mat"), true);
});

test("登録商品はモールをまたいでID・名称を統一し、未登録品も商品コードで分ける", () => {
  const index = buildAffiliateProductIndex([product]);
  for (const href of [affiliate(target), product.amazonUrl]) {
    assert.deepEqual(resolveAffiliateProduct(href, index), { id: product.id, name: product.name });
  }
  assert.deepEqual(resolveAffiliateProduct(affiliate(target), new Map()), { id: "rakuten:waqoutdoor/waq-hpa1", name: "" });
  assert.equal(resolveAffiliateProduct("https://amzn.to/unknown", index).id, "inline");
});

test("同一リンクの重複登録は先勝ちにせず、誤った商品へ割り当てない", () => {
  const index = buildAffiliateProductIndex([product, { ...product, id: "different-pump" }, product]);
  assert.deepEqual(resolveAffiliateProduct(affiliate(target), index), { id: "rakuten:waqoutdoor/waq-hpa1", name: "" });
  const short = { ...product, amazonUrl: "https://amzn.to/known" };
  assert.equal(resolveAffiliateProduct(short.amazonUrl, buildAffiliateProductIndex([short])).id, product.id);
});

test("Yahooは確認できる商品URLだけを扱い、識別子の長さを制限する", () => {
  const url = "https://store.shopping.yahoo.co.jp/shop/item-1.html";
  assert.equal(affiliateProductKey(url), "yahoo:shop/item-1");
  assert.equal(affiliateProductKey("https://ck.jp.ap.valuecommerce.com/servlet/referral?vc_url=" + encodeURIComponent(url)), "yahoo:shop/item-1");
  assert.equal(affiliateProductKey("https://item.rakuten.co.jp/shop/" + "x".repeat(150)), null);
});
