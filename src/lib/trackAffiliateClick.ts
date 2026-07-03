// アフィリエイトクリック計測（GA4 + /api/track-click ビーコン）
// AffiliateLink コンポーネントと記事本文内のインラインリンクで共用する

export type AffiliateStore = "amazon" | "rakuten";

const AFFILIATE_HOSTS: [RegExp, AffiliateStore][] = [
  [/hb\.afl\.rakuten\.co\.jp/, "rakuten"],
  [/a\.r10\.to/, "rakuten"],
  [/room\.rakuten\.co\.jp/, "rakuten"],
  [/amazon\.co\.jp/, "amazon"],
  [/amzn\.to/, "amazon"],
  [/amzn\.asia/, "amazon"],
];

export function detectAffiliateStore(href: string): AffiliateStore | null {
  for (const [pattern, store] of AFFILIATE_HOSTS) {
    if (pattern.test(href)) return store;
  }
  return null;
}

export function trackAffiliateClick(
  href: string,
  productId: string,
  store: AffiliateStore
) {
  // GA4カスタムイベントで計測
  if (typeof window !== "undefined" && "gtag" in window) {
    (window as unknown as { gtag: (...args: unknown[]) => void }).gtag(
      "event",
      "affiliate_click",
      {
        product_id: productId,
        store,
        page_path: window.location.pathname,
        link_url: href,
      }
    );
  }

  // ビーコンAPIでサーバーサイド記録（GA4が入っていない場合のフォールバック）
  try {
    const data = JSON.stringify({
      productId,
      store,
      path: window.location.pathname,
      link_url: href,
      timestamp: new Date().toISOString(),
    });
    navigator.sendBeacon(
      "/api/track-click",
      new Blob([data], { type: "application/json" })
    );
  } catch {
    // ignore
  }
}
