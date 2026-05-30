import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // X 投稿生成・viral-scout・記事系API は data/ 配下のJSON群を動的に読み込む。
  // Vercel の自動 file tracing は動的読み込みを検出できないため、明示的に
  // bundle に含める。これがないと本番で ENOENT エラーになる。
  outputFileTracingIncludes: {
    "/api/x-posts/generate": ["./data/**/*"],
    "/api/x-posts": ["./data/**/*"],
    "/api/viral-scout": ["./data/**/*"],
  },
  images: {
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
      { protocol: "https", hostname: "m.media-amazon.com" },
      { protocol: "https", hostname: "images.unsplash.com" },
      { protocol: "https", hostname: "plus.unsplash.com" },
      { protocol: "https", hostname: "**.imageflux.jp" },
    ],
  },
};

export default nextConfig;
