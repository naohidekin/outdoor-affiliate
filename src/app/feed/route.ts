import { getPublishedArticles, getCategoryById } from "@/lib/db";

export const dynamic = "force-dynamic";

export function GET() {
  const baseUrl = "https://camp-gear-lab.com";
  const articles = getPublishedArticles();

  const items = articles
    .sort(
      (a, b) =>
        new Date(b.publishedAt ?? b.createdAt).getTime() -
        new Date(a.publishedAt ?? a.createdAt).getTime()
    )
    .slice(0, 20)
    .map((article) => {
      const category = getCategoryById(article.categoryId);
      const pubDate = new Date(
        article.publishedAt ?? article.createdAt
      ).toUTCString();

      return `    <item>
      <title><![CDATA[${article.title}]]></title>
      <link>${baseUrl}/articles/${article.slug}</link>
      <guid>${baseUrl}/articles/${article.slug}</guid>
      <description><![CDATA[${article.excerpt}]]></description>
      <pubDate>${pubDate}</pubDate>${category ? `\n      <category>${category.name}</category>` : ""}
    </item>`;
    })
    .join("\n");

  const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Outdoor Gear Lab</title>
    <link>${baseUrl}</link>
    <description>テント・シュラフ・バーナーなど、キャンプ・登山ギアの比較・レビュー</description>
    <language>ja</language>
    <atom:link href="${baseUrl}/feed" rel="self" type="application/rss+xml" />
${items}
  </channel>
</rss>`;

  return new Response(rss, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "s-maxage=3600, stale-while-revalidate",
    },
  });
}
