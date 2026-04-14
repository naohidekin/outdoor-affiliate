import type { MetadataRoute } from "next";
import { getArticles, getCategories } from "@/lib/db";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const baseUrl = "https://camp-gear-lab.com";
  const [allArticles, categories] = await Promise.all([
    getArticles(),
    getCategories(),
  ]);
  const articles = allArticles.filter((a) => a.status === "published");

  const staticPages: MetadataRoute.Sitemap = [
    {
      url: baseUrl,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1,
    },
  ];

  const categoryPages: MetadataRoute.Sitemap = categories.map((cat) => ({
    url: `${baseUrl}/category/${cat.slug}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));

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
