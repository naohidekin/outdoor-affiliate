import test from 'node:test';
import assert from 'node:assert/strict';
import { isMerchantSearch } from '../src/lib/productMerchants.ts';

test('検索先と個別商品ページを区別し、楽天の転送先も確認する', () => {
  assert.equal(isMerchantSearch('https://www.amazon.co.jp/s?k=YMS-16'), true);
  assert.equal(isMerchantSearch('https://www.amazon.co.jp/dp/B016120Q2M'), false);
  assert.equal(isMerchantSearch('https://hb.afl.rakuten.co.jp/hgc/test?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2Ftest'), true);
  assert.equal(isMerchantSearch('https://example.com/s?k=amazon.co.jp'), false);
  assert.equal(isMerchantSearch('invalid'), false);
});
