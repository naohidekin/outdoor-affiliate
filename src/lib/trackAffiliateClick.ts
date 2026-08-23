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
  "unknown",
] as const;

export type AffiliatePlacement = (typeof AFFILIATE_PLACEMENTS)[number];

/**
 * 価格帯。EPCを価格帯ごとに見ないと、どのモールをどこで優先すべきか判断できない。
 *
 * 2026-08-23: Amazon EPC 6.62円 / 楽天 EPC 17.03円 という全体平均だけを見ると
 * 「楽天に寄せるべき」に見える。だが楽天は1商品1個につき報酬上限1,000円があり
 * （料率アップショップを除く）、実測で売上¥82,665のテントが報酬¥1,000だった。
 * 平均は高単価の頭打ちを均してしまうので、価格帯で割って見る必要がある。
 */
export function priceBand(price?: number): string {
  if (!price || price <= 0) return "unknown";
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
    /** 表示していた価格（円）。登録価格であって実売とは限らない */
    price?: number;
    /** そのカード内でのボタンの表示順。1が上。どちらのモールを上に出したかの検証用 */
    rank?: number;
  }
) {
  const placement = opts?.placement || "unknown";
  const productName = opts?.productName || "";
  const price = typeof opts?.price === "number" && opts.price > 0 ? Math.round(opts.price) : undefined;
  const rank = typeof opts?.rank === "number" && opts.rank > 0 ? opts.rank : undefined;

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
        // 価格帯別のEPCと、どちらのモールを上に出したかを見るための軸
        ...(price !== undefined ? { price, price_band: priceBand(price) } : {}),
        ...(rank !== undefined ? { rank } : {}),
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
      // Supabase 側に列を足すまで /api/track-click は無視する（entry を明示的に
      // 組み立てているので、知らないフィールドが来ても落ちない）。
      // 先に送っておけば、列を足した日から遡って使える形になる
      price,
      rank,
    });
    navigator.sendBeacon(
      "/api/track-click",
      new Blob([data], { type: "application/json" })
    );
  } catch {
    // ignore
  }
}
