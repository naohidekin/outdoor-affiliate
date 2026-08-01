import type { MetadataRoute } from "next";
import { getArticlesList, getCategories } from "@/lib/db";

// クローラー（Google/Bing/GPTBot等）が高頻度で叩くため1時間キャッシュ。
// これが無いとアクセスの度にSupabaseから全記事メタを取得しEgressを消費する。
export const revalidate = 21600; // 6時間（Egress削減・2026-07-24）

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const baseUrl = "https://camp-gear-lab.com";
  const [allArticles, categories] = await Promise.all([
    getArticlesList(),
    getCategories(),
  ]);
  const articles = allArticles.filter((a) => a.status === "published");

  // ホームページ: 最新記事の更新日を使用（毎回現在時刻は誤シグナル）
  const latestArticleDate = articles.reduce(
    (max, a) => (a.updatedAt > max ? a.updatedAt : max),
    articles[0]?.updatedAt ?? new Date().toISOString()
  );

  const staticPages: MetadataRoute.Sitemap = [
    {
      url: baseUrl,
      lastModified: new Date(latestArticleDate),
      changeFrequency: "daily",
      priority: 1,
    },
    {
      url: `${baseUrl}/articles`,
      lastModified: new Date(latestArticleDate),
      changeFrequency: "daily",
      priority: 0.8,
    },
    {
      url: `${baseUrl}/about`,
      changeFrequency: "monthly",
      priority: 0.5,
    },
    {
      url: `${baseUrl}/privacy`,
      changeFrequency: "yearly",
      priority: 0.3,
    },
    {
      url: `${baseUrl}/contact`,
      changeFrequency: "yearly",
      priority: 0.3,
    },
  ];

  // カテゴリページ: そのカテゴリ内の最新記事更新日を使用
  const categoryPages: MetadataRoute.Sitemap = categories.map((cat) => {
    const catArticles = articles.filter((a) => a.categoryId === cat.id);
    const catLatest = catArticles.reduce(
      (max, a) => (a.updatedAt > max ? a.updatedAt : max),
      catArticles[0]?.updatedAt ?? new Date().toISOString()
    );
    return {
      url: `${baseUrl}/category/${cat.slug}`,
      lastModified: new Date(catLatest),
      changeFrequency: "weekly" as const,
      priority: 0.8,
    };
  });

  const isGuideArticle = (title: string) =>
    /ガイド|guide|完全|選び方/.test(title.toLowerCase());

  const articlePages: MetadataRoute.Sitemap = articles.map((article) => ({
    url: `${baseUrl}/articles/${article.slug}`,
    lastModified: new Date(article.updatedAt),
    changeFrequency: "monthly" as const,
    priority: isGuideArticle(article.title) ? 0.9 : 0.7,
  }));

  return [...staticPages, ...categoryPages, ...articlePages];
}
