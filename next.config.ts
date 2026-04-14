import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
    ],
  },
};

export default nextConfig;
