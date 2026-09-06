// アフィリエイトクリック計測（GA4 + /api/track-click ビーコン）
// AffiliateLink コンポーネントと記事本文内のインラインリンクで共用する
import { trackEvent } from "./trackEvent.ts";

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
  let hostname: string;
  try {
    const url = new URL(href);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    hostname = url.hostname;
  } catch { return null; }
  for (const [pattern, store] of AFFILIATE_HOSTS) {
    // Check the actual host, not a merchant name in an unrelated URL's query.
    if (new RegExp(`(?:^|\\.)${pattern.source}$`).test(hostname)) return store;
  }
  return null;
}

// ボタンの設置場所（成約分析用）。「商品が弱い」か「位置が弱い」かを切り分ける。
// サーバー側（/api/track-click）の許可リストもこの配列から導出する。
// 別々に持つと追加漏れで新placementがunknownに丸められる事故が起きる
// （2026-08-01にarticle_end/reviews_linkで実際に発生）
export const AFFILIATE_PLACEMENTS = [
  "product_card", // 商品カード
  "ranking", // ランキングリスト
  "comparison_table", // 比較表
  "recommended", // おすすめCTA（記事冒頭）
  "article_end", // おすすめCTA（記事末尾・読了直後）
  "reviews_link", // 「楽天で口コミをもっと見る」リンク
  "body_text", // 本文インラインリンク
  "room_collection", // トップページの楽天ROOMコレクション
  "footer_room", // フッターの楽天ROOM
  "unknown",
] as const;

export type AffiliatePlacement = (typeof AFFILIATE_PLACEMENTS)[number];

/** Display-price bands for comparisons within matching pages and periods. */
export function priceBand(price?: number): string {
  if (!price || !Number.isFinite(price) || price <= 0) return "unknown";
  if (price < 5000) return "under_5k";
  if (price < 15000) return "5k_15k";
  if (price < 50000) return "15k_50k";
  return "over_50k";
}

export function trackAffiliateClick(
  href: string,
  productId: string,
  store: AffiliateStore,
  opts?: {
    placement?: AffiliatePlacement;
    productName?: string;
    /** Visible anchor label, distinct from a verified catalogue product name. */
    linkText?: string;
    /** 表示していた価格（円）。登録価格であって実売とは限らない */
    price?: number;
    /** そのカード内でのボタンの表示順。1が上。どちらのモールを上に出したかの検証用 */
    rank?: number;
  }
) {
  const placement = opts?.placement || "unknown";
  const productName = opts?.productName || "";
  const price = typeof opts?.price === "number" && Number.isFinite(opts.price) && opts.price > 0 ? Math.round(opts.price) : undefined;
  const rank = typeof opts?.rank === "number" && Number.isInteger(opts.rank) && opts.rank > 0 ? opts.rank : undefined;

  if (typeof window === "undefined") return;
  // Both transports can be blocked. A GA4 error must not prevent the beacon.
  trackEvent("affiliate_click", {
    product_id: productId,
    product_name: productName,
    merchant: store,
    placement,
    page_path: window.location.pathname,
    link_url: href,
    ...(opts?.linkText ? { link_text: opts.linkText.trim().slice(0, 100) } : {}),
    // 価格帯別のEPCと、どちらのモールを上に出したかを見るための軸
    ...(price !== undefined ? { price, price_band: priceBand(price) } : {}),
    ...(rank !== undefined ? { rank } : {}),
  });

  // Independent same-origin click log. Delivery can still fail; this is not purchase data.
  try {
    const data = JSON.stringify({
      productId,
      productName,
      store,
      placement,
      path: window.location.pathname,
      link_url: href,
      timestamp: new Date().toISOString(),
      // These dimensions currently persist in GA4 only. The server intentionally
      // ignores them until its schema changes; historical values cannot be recovered.
      price,
      rank,
    });
    let queued = false;
    try {
      queued = typeof navigator.sendBeacon === "function" && navigator.sendBeacon(
        "/api/track-click", new Blob([data], { type: "application/json" })
      );
    } catch { /* Try the same-origin keepalive fallback below. */ }
    if (!queued) void fetch("/api/track-click", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: data, keepalive: true, credentials: "same-origin",
    }).catch(() => { /* Navigation must not wait for analytics. */ });
  } catch {
    // ignore
  }
}
