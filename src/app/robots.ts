import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // opengraph-image は Twitterbot 等がカード画像取得時に robots.txt を
      // 尊重するため、ブロックすると SNS カードが壊れる。除外しない。
      disallow: ["/admin/", "/api/", "/_next/"],
    },
    sitemap: "https://camp-gear-lab.com/sitemap.xml",
  };
}
