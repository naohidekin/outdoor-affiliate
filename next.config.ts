import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      // /category は page.tsx が存在せず 404 になるため恒久リダイレクト
      // （/articles は 2026-08-01 に記事アーカイブページを新設したため解除）
      { source: "/category", destination: "/", permanent: true },
      // 重複記事の統合（2026-06-11）: 6/8公開の刷新版を、GSC順位資産のある
      // 旧スラッグへ移植したため、新スラッグ側を301で正規URLへ集約する
      {
        source: "/articles/landrock-vs-landnest-shelter",
        destination: "/articles/landlock-vs-landnest-shelter",
        permanent: true,
      },
      // ─── 孤立URL救済（2026-06-15）: draft/削除済み記事 → 最も近い公開記事へ301 ───
      // draft記事
      { source: "/articles/insect-repellent-bracelet-ranking", destination: "/articles/insect-repellent-gear-roundup", permanent: true },
      { source: "/articles/led-lantern-ranking", destination: "/articles/gas-lantern-ranking", permanent: true },
      { source: "/articles/hiking-backpack-30l-ranking", destination: "/articles/backpack-ranking", permanent: true },
      // 削除済み記事
      { source: "/articles/camp-insect-repellent-roadmap", destination: "/articles/camp-insect-repellent-guide", permanent: true },
      { source: "/articles/camp-night-toilet-light-guide", destination: "/articles/led-tent-light-ranking", permanent: true },
      { source: "/articles/family-camp-budget-guide", destination: "/articles/family-camp-first-time-guide", permanent: true },
      { source: "/articles/family-camp-chair-ranking", destination: "/articles/camp-chair-ranking", permanent: true },
      { source: "/articles/kids-insect-repellent-guide", destination: "/articles/insect-repellent-gear-roundup", permanent: true },
      { source: "/articles/kids-insect-repellent-ranking", destination: "/articles/insect-repellent-spray-ranking", permanent: true },
      { source: "/articles/quick-dry-tshirt-ranking", destination: "/category/wear", permanent: true },
      { source: "/articles/rain-proof-tent-ranking", destination: "/articles/rain-camp-gear-essentials", permanent: true },
      { source: "/articles/solo-camp-chair-ranking", destination: "/articles/solo-low-chair-ranking", permanent: true },
      { source: "/articles/spring-camp-cold-kids-guide", destination: "/articles/spring-camp-clothing-guide", permanent: true },
      { source: "/articles/spring-camp-tent-guide", destination: "/articles/tent-setup-tips-spring", permanent: true },
      { source: "/articles/summer-camp-heat-food-safety", destination: "/articles/summer-camp-heat-gear-guide", permanent: true },
      { source: "/articles/tarp-setup-patterns-guide", destination: "/articles/tarp-setup-guide-for-beginners", permanent: true },
      { source: "/articles/tarp-tent-connection-setup-guide", destination: "/articles/tarp-tent-layout-site-guide", permanent: true },
      { source: "/articles/tent-without-vestibule-guide", destination: "/articles/tent-vestibule-size-ranking", permanent: true },
      { source: "/articles/winter-camp-co-safety-guide", destination: "/articles/winter-camp-beginners-checklist", permanent: true },
      { source: "/articles/2-person-tent-ranking", destination: "/articles/duo-tent-ranking", permanent: true },
      // 存在しないカテゴリページ（GSC 404検出 2026-06-21）
      { source: "/category/cold-safety", destination: "/articles/winter-camp-beginners-checklist", permanent: true },
      { source: "/category/rain-safety", destination: "/articles/rain-camp-gear-essentials", permanent: true },
    ];
  },
  async headers() {
    return [
      {
        // 管理画面はビルド時に静的HTMLとしてプリレンダーされるため、robots.txt の
        // Disallow だけではインデックスを防げない（Disallowはクロール抑止であって
        // インデックス抑止ではなく、外部リンク経由でURLが載りうる）。
        // X-Robots-Tag ヘッダで確実にインデックスを拒否する。
        source: "/admin/:path*",
        headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }],
      },
      {
        source: "/admin",
        headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }],
      },
      {
        // 全ページ共通のセキュリティヘッダ（保険）
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
        ],
      },
    ];
  },
  // X 投稿生成・viral-scout・記事系API は data/ 配下のJSON群を動的に読み込む。
  // Vercel の自動 file tracing は動的読み込みを検出できないため、明示的に
  // bundle に含める。これがないと本番で ENOENT エラーになる。
  outputFileTracingIncludes: {
    "/api/x-posts/generate": ["./data/**/*"],
    "/api/x-posts": ["./data/**/*"],
    "/api/viral-scout": ["./data/**/*"],
  },
  images: {
    // 2026-06-12: Vercel無料枠の画像最適化クォータ超過で全画像が402になったため、
    // 最適化を無効化して元画像を直接配信する（楽天/Amazon/Unsplash側のCDNが
    // 適切なサイズで返すため実用上の影響は小さい）。Proプラン移行時はこの行を
    // 削除すれば最適化が復活する。
    unoptimized: true,
    remotePatterns: [
      { protocol: "https", hostname: "**.r10s.jp" },
      { protocol: "https", hostname: "**.rakuten.co.jp" },
      { protocol: "https", hostname: "ec.coleman.co.jp" },
      { protocol: "https", hostname: "lumena.co.jp" },
      { protocol: "https", hostname: "img.snowpeak.co.jp" },
      { protocol: "https", hostname: "www.dod.camp" },
      { protocol: "https", hostname: "japan.nordisk.eu" },
      { protocol: "https", hostname: "www.iwatani-primus.co.jp" },
      { protocol: "https", hostname: "soto.shinfuji.co.jp" },
      { protocol: "https", hostname: "www.uniflame.co.jp" },
      { protocol: "https", hostname: "www.forewinds.iwatani.co.jp" },
      { protocol: "https", hostname: "ec.treasure-f.com" },
      { protocol: "https", hostname: "www.lostarrow.co.jp" },
      { protocol: "https", hostname: "www.captainstag.net" },
      { protocol: "https", hostname: "store.captainstag.net" },
      { protocol: "https", hostname: "www.iwatani.co.jp" },
      { protocol: "https", hostname: "store.nanga.jp" },
      { protocol: "https", hostname: "nanga.jp" },
      { protocol: "https", hostname: "www.logos.ne.jp" },
      { protocol: "https", hostname: "ratelworks.jp" },
      { protocol: "https", hostname: "m.media-amazon.com" },
      { protocol: "https", hostname: "images.unsplash.com" },
      { protocol: "https", hostname: "plus.unsplash.com" },
      { protocol: "https", hostname: "**.imageflux.jp" },
      { protocol: "https", hostname: "claymore.jp" },
      { protocol: "https", hostname: "www.ecoflow.com" },
      { protocol: "https", hostname: "jp.ecoflow.com" },
      { protocol: "https", hostname: "imagedelivery.net" },
      { protocol: "https", hostname: "i.ytimg.com" },
      { protocol: "https", hostname: "www.jackery.jp" },
      { protocol: "https", hostname: "www.bluetti.jp" },
      { protocol: "https", hostname: "www.thanko.jp" },
      { protocol: "https", hostname: "fieldoor.com" },
      { protocol: "https", hostname: "www.sony.jp" },
      { protocol: "https", hostname: "s3-ap-northeast-1.amazonaws.com" },
      { protocol: "https", hostname: "makeshop-multi-images.akamaized.net" },
      { protocol: "https", hostname: "www.snowpeak.co.jp" },
      { protocol: "https", hostname: "www.firesidestove.com" },
      { protocol: "https", hostname: "jp.stanley1913.com" },
      { protocol: "https", hostname: "quickcamp.jp" },
      { protocol: "https", hostname: "www.yamac.co.jp" },
    ],
  },
};

export default nextConfig;
