import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/admin/",
        "/api/",
        "/_next/",
        "/opengraph-image",
        "**/opengraph-image",
        "/favicon.ico",
      ],
    },
    sitemap: "https://camp-gear-lab.com/sitemap.xml",
  };
}
