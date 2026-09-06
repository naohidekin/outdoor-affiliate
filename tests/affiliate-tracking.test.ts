import test from "node:test";
import assert from "node:assert/strict";
import { detectAffiliateStore, trackAffiliateClick } from "../src/lib/trackAffiliateClick.ts";
import { trackEvent } from "../src/lib/trackEvent.ts";
import { observeOffer } from "../src/lib/observeOffer.ts";

function withGlobals(values: Record<string, unknown>, run: () => void) {
  const originals = new Map(Object.keys(values).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  try {
    for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { configurable: true, value });
    run();
  } finally {
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
}

test("販売店判定は実際のホストを確認する", () => {
  assert.equal(detectAffiliateStore("https://www.amazon.co.jp/dp/B000000001"), "amazon");
  assert.equal(detectAffiliateStore("https://room.rakuten.co.jp/example"), "rakuten");
  assert.equal(detectAffiliateStore("https://example.com/?url=amazon.co.jp"), null);
  assert.equal(detectAffiliateStore("https://amazon.co.jp.example.com"), null);
  assert.equal(detectAffiliateStore("https://fakeamazon.co.jp"), null);
});

test("GA4で例外が起きてもビーコンを送信し、二重送信しない", () => {
  let beacons = 0, fetches = 0;
  withGlobals({
    window: { location: { pathname: "/articles/test" }, gtag: () => { throw new Error("blocked"); } },
    navigator: { sendBeacon: () => { beacons++; return true; } },
    fetch: () => { fetches++; return Promise.resolve(); },
  }, () => trackAffiliateClick("https://www.amazon.co.jp", "test", "amazon"));
  assert.equal(beacons, 1); assert.equal(fetches, 0);
});

test("ビーコンが拒否された場合は同じ内容をkeepaliveで送り直す", () => {
  let request: RequestInit | undefined;
  withGlobals({
    window: { location: { pathname: "/articles/test" }, gtag: () => {} },
    navigator: { sendBeacon: () => false },
    fetch: (url: string, options: RequestInit) => { assert.equal(url, "/api/track-click"); request = options; return Promise.resolve(); },
  }, () => trackAffiliateClick("https://www.amazon.co.jp", "test", "amazon", { placement: "article_end", rank: 1 }));
  assert.equal(request?.keepalive, true);
  assert.equal(JSON.parse(request?.body as string).placement, "article_end");
});

test("初期表示イベントは既存GAタグの初期化後に一度送る", () => {
  const events: unknown[][] = [];
  const target = new EventTarget() as EventTarget & { gtag?: (...args: unknown[]) => void };
  withGlobals({ window: target }, () => {
    trackEvent("affiliate_offer_view", { product_id: "test" });
    assert.equal(events.length, 0);
    target.gtag = (...args) => events.push(args);
    target.dispatchEvent(new Event("camp-analytics-ready"));
    target.dispatchEvent(new Event("camp-analytics-ready"));
  });
  assert.equal(events.length, 1); assert.equal(events[0][1], "affiliate_offer_view");
});

test("非表示・画面外ボタンは数えず、半分以上表示されたボタンを一度数える", () => {
  let callback: (entries: Partial<IntersectionObserverEntry>[]) => void = () => {};
  let seen = 0, instances = 0;
  class Observer {
    constructor(fn: typeof callback) { callback = fn; instances++; }
    observe() {} unobserve() {} disconnect() {}
  }
  withGlobals({ IntersectionObserver: Observer }, () => {
    const target = {} as Element, second = {} as Element;
    const stop = observeOffer(target, () => { seen++; });
    const stopSecond = observeOffer(second, () => { seen++; });
    callback([{ target, isIntersecting: false, intersectionRatio: 0 }]);
    callback([{ target, isIntersecting: true, intersectionRatio: 0.3 }]);
    assert.equal(seen, 0);
    callback([{ target, isIntersecting: true, intersectionRatio: 0.5 }]);
    callback([{ target, isIntersecting: true, intersectionRatio: 1 }]);
    assert.equal(seen, 1); assert.equal(instances, 1);
    stop(); stopSecond();
    callback([{ target: second, isIntersecting: true, intersectionRatio: 1 }]);
    assert.equal(seen, 1);
  });
});


test("本文商品IDと名称をGA4・独自ログへ同じ値で送る", () => {
  let ga: Record<string, unknown> = {};
  let payload: Record<string, unknown> = {};
  withGlobals({
    window: { location: { pathname: "/articles/storage" }, gtag: (_cmd: string, event: string, data: Record<string, unknown>) => { assert.equal(event, "affiliate_click"); ga = data; } },
    navigator: { sendBeacon: () => false },
    fetch: (_url: string, options: RequestInit) => { payload = JSON.parse(options.body as string); return Promise.resolve(); },
  }, () => trackAffiliateClick("https://item.rakuten.co.jp/waqoutdoor/waq-hpa1/", "rakuten:waqoutdoor/waq-hpa1", "rakuten", { placement: "body_text", linkText: "ポンプの価格を確認" }));
  assert.equal(ga.product_id, payload.productId);
  assert.equal(ga.product_name, payload.productName);
  assert.equal(ga.placement, payload.placement);
  assert.equal(ga.link_text, "ポンプの価格を確認");
  assert.notEqual(ga.product_id, "inline");
});
