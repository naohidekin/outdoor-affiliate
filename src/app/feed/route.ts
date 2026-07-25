import { getPublishedArticlesList, getCategories } from "@/lib/db";

export const revalidate = 21600; // ISR: 6時間（Egress削減・2026-07-24）

export async function GET() {
  const baseUrl = "https://camp-gear-lab.com";
  const [articles, categories] = await Promise.all([
    getPublishedArticlesList(),
    getCategories(),
  ]);

  const items = articles
    .sort(
      (a, b) =>
        new Date(b.publishedAt ?? b.createdAt).getTime() -
        new Date(a.publishedAt ?? a.createdAt).getTime()
    )
    .slice(0, 50)
    .map((article) => {
      const category = categories.find((c) => c.id === article.categoryId);
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
    <title>Camp Gear Lab</title>
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
      "Cache-Control": "s-maxage=21600, stale-while-revalidate",
    },
  });
}
