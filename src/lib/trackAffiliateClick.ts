// アフィリエイトクリック計測（GA4 + /api/track-click ビーコン）
// AffiliateLink コンポーネントと記事本文内のインラインリンクで共用する

export type AffiliateStore = "amazon" | "rakuten" | "yahoo" | "valuecommerce";

const AFFILIATE_HOSTS: [RegExp, AffiliateStore][] = [
  [/hb\.afl\.rakuten\.co\.jp/, "rakuten"],
  [/a\.r10\.to/, "rakuten"],
  [/room\.rakuten\.co\.jp/, "rakuten"],
  [/amazon\.co\.jp/, "amazon"],
  [/amzn\.to/, "amazon"],
  [/amzn\.asia/, "amazon"],
  [/ck\.jp\.ap\.valuecommerce\.com/, "yahoo"],
  [/shopping\.yahoo\.co\.jp/, "yahoo"],
  // ゼビオ・エルブレス（LinkSwitchがクリック時に変換）
  [/supersports\.com/, "valuecommerce"],
  // アルペン（スポーツデポ／ゴルフ5／アルペンアウトドアズ統合ストア。LinkSwitchがクリック時に変換）
  [/store\.alpen-group\.jp/, "valuecommerce"],
];

export function detectAffiliateStore(href: string): AffiliateStore | null {
  for (const [pattern, store] of AFFILIATE_HOSTS) {
    if (pattern.test(href)) return store;
  }
  return null;
}

// ボタンの設置場所（成約分析用）。「商品が弱い」か「位置が弱い」かを切り分ける
export type AffiliatePlacement =
  | "product_card" // 商品カード
  | "ranking" // ランキングリスト
  | "comparison_table" // 比較表
  | "recommended" // おすすめCTA
  | "body_text" // 本文インラインリンク
  | "unknown";

export function trackAffiliateClick(
  href: string,
  productId: string,
  store: AffiliateStore,
  opts?: { placement?: AffiliatePlacement; productName?: string }
) {
  const placement = opts?.placement || "unknown";
  const productName = opts?.productName || "";

  // GA4カスタムイベント（広告ブロッカーで欠落しうる。正はサーバー側ビーコン）
  if (typeof window !== "undefined" && "gtag" in window) {
    (window as unknown as { gtag: (...args: unknown[]) => void }).gtag(
      "event",
      "affiliate_click",
      {
        product_id: productId,
        product_name: productName,
        merchant: store,
        placement,
        page_path: window.location.pathname,
        link_url: href,
      }
    );
  }

  // ファーストパーティのビーコン記録（こちらが正の計測。ブロッカーに強い）
  try {
    const data = JSON.stringify({
      productId,
      productName,
      store,
      placement,
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
