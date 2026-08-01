import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // opengraph-image は Twitterbot 等がカード画像取得時に robots.txt を
      // 尊重するため、ブロックすると SNS カードが壊れる。除外しない。
      // /_next/ はCSS/JSが含まれ、ブロックするとGoogleのレンダリング確認を
      // 妨げるため除外しない。/admin/ はブロックするとX-Robots-Tagのnoindexを
      // クローラーが読めなくなるため、認証+noindexヘッダ側で守る
      disallow: ["/api/"],
    },
    sitemap: "https://camp-gear-lab.com/sitemap.xml",
  };
}
