import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getCategories,
  getArticleBySlug,
  getProductsByIds,
  getCategoryById,
  getArticlesByCategory,
} from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleContent from "@/components/ArticleContent";

export const dynamic = "force-dynamic";

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = getArticleBySlug(slug);
  if (!article || article.status !== "published") notFound();

  const categories = getCategories();
  const category = getCategoryById(article.categoryId);
  const products = getProductsByIds(article.productIds);
  const relatedArticles = category
    ? getArticlesByCategory(category.id)
        .filter((a) => a.id !== article.id)
        .slice(0, 3)
    : [];

  return (
    <>
      <Header categories={categories} />
      <main className="flex-1">
        <article className="max-w-4xl mx-auto px-4 py-12">
          {/* Breadcrumb */}
          <nav className="text-sm text-gray-400 mb-6">
            <Link href="/" className="hover:text-green-600">
              ホーム
            </Link>
            {category && (
              <>
                {" / "}
                <Link
                  href={`/category/${category.slug}`}
                  className="hover:text-green-600"
                >
                  {category.name}
                </Link>
              </>
            )}
          </nav>

          <h1 className="text-3xl md:text-4xl font-bold text-gray-800 mb-4">
            {article.title}
          </h1>

          <div className="flex items-center gap-4 text-sm text-gray-400 mb-8">
            {article.publishedAt && (
              <time>
                {new Date(article.publishedAt).toLocaleDateString("ja-JP", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </time>
            )}
            {category && (
              <Link
                href={`/category/${category.slug}`}
                className="bg-green-100 text-green-700 px-3 py-1 rounded-full text-xs"
              >
                {category.name}
              </Link>
            )}
          </div>

          {/* Article body */}
          <ArticleContent content={article.content} products={products} />
        </article>

        {/* Related articles */}
        {relatedArticles.length > 0 && (
          <section className="max-w-4xl mx-auto px-4 pb-12">
            <h2 className="text-xl font-bold text-gray-800 mb-6">
              関連する記事
            </h2>
            <div className="grid sm:grid-cols-3 gap-4">
              {relatedArticles.map((a) => (
                <Link
                  key={a.id}
                  href={`/articles/${a.slug}`}
                  className="bg-white rounded-lg shadow-sm hover:shadow-md transition p-4 border border-gray-100"
                >
                  <h3 className="font-semibold text-gray-800 text-sm mb-1 line-clamp-2">
                    {a.title}
                  </h3>
                  <p className="text-xs text-gray-500 line-clamp-2">
                    {a.excerpt}
                  </p>
                </Link>
              ))}
            </div>
          </section>
        )}
      </main>
      <Footer />
    </>
  );
}
