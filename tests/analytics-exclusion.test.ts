import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { hasAnalyticsExclusion, isExcludedAnalyticsPath, analyticsGuardScript, GA_MEASUREMENT_ID } from "../src/lib/analyticsExclusion.ts";
import { trackAffiliateClick } from "../src/lib/trackAffiliateClick.ts";

test("only the exact preference excludes traffic", () => {
  assert.equal(hasAnalyticsExclusion("other=1; camp_analytics_excluded=1"), true);
  for (const value of ["", "camp_analytics_excluded=0", "not_camp_analytics_excluded=1", "camp_analytics_excluded=10"]) assert.equal(hasAnalyticsExclusion(value), false);
  for (const path of ["/admin", "/admin/login", "/api/auth", "/analytics-settings"]) assert.equal(isExcludedAnalyticsPath(path), true);
  for (const path of ["/", "/articles/test", "/administrator", "/category/light"]) assert.equal(isExcludedAnalyticsPath(path), false);
});

test("GA guard runs before initialization and responds to preference changes", () => {
  const handlers = new Map<string, () => void>();
  const context = { window: { addEventListener: (name: string, fn: () => void) => handlers.set(name, fn) } as Record<string, unknown>, location: { pathname: "/articles/test" }, document: { cookie: "" } };
  vm.runInNewContext(analyticsGuardScript, context);
  const key = `ga-disable-${GA_MEASUREMENT_ID}`;
  assert.equal(context.window[key], false);
  context.document.cookie = "camp_analytics_excluded=1";
  handlers.get("camp-analytics-preference")!();
  assert.equal(context.window[key], true);
  context.document.cookie = "";
  handlers.get("focus")!();
  assert.equal(context.window[key], false);
  context.location.pathname = "/admin/products";
  handlers.get("pageshow")!();
  assert.equal(context.window[key], true);
});

test("excluded clicks send neither GA events nor purchase beacons while normal clicks still do", () => {
  const originals = new Map(["window", "document", "navigator"].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  let ga = 0, beacons = 0;
  const documentMock = { cookie: "camp_analytics_excluded=1" };
  Object.defineProperty(globalThis, "document", { configurable: true, value: documentMock });
  Object.defineProperty(globalThis, "window", { configurable: true, value: { location: { pathname: "/articles/test", hostname: "localhost" }, gtag: () => ga++ } });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { sendBeacon: () => { beacons++; return true; } } });
  try {
    trackAffiliateClick("https://www.amazon.co.jp/dp/TEST", "test", "amazon");
    assert.equal(ga, 0); assert.equal(beacons, 0);
    documentMock.cookie = "";
    trackAffiliateClick("https://www.amazon.co.jp/dp/TEST", "test", "amazon");
    assert.equal(ga, 1); assert.equal(beacons, 1);
  } finally {
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});
