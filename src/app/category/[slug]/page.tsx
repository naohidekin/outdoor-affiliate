import Link from "next/link";
import { notFound } from "next/navigation";
import { getCategories, getCategoryBySlug, getArticlesByCategory } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export const dynamic = "force-dynamic";

export default async function CategoryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const category = getCategoryBySlug(slug);
  if (!category) notFound();

  const categories = getCategories();
  const articles = getArticlesByCategory(category.id);

  return (
    <>
      <Header categories={categories} />
      <main className="flex-1">
        <section className="bg-green-700 text-white py-12">
          <div className="max-w-6xl mx-auto px-4">
            <p className="text-green-200 text-sm mb-2">
              <Link href="/" className="hover:text-white">
                ホーム
              </Link>{" "}
              / カテゴリ
            </p>
            <h1 className="text-3xl font-bold">{category.name}</h1>
            <p className="text-green-200 mt-2">{category.description}</p>
          </div>
        </section>

        <section className="max-w-6xl mx-auto px-4 py-12">
          {articles.length > 0 ? (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {articles.map((article) => (
                <Link
                  key={article.id}
                  href={`/articles/${article.slug}`}
                  className="bg-white rounded-xl shadow-sm hover:shadow-md transition p-6 border border-gray-100"
                >
                  <h3 className="font-bold text-gray-800 mb-2 line-clamp-2">
                    {article.title}
                  </h3>
                  <p className="text-sm text-gray-500 line-clamp-3">
                    {article.excerpt}
                  </p>
                  <p className="text-xs text-gray-400 mt-3">
                    {article.publishedAt &&
                      new Date(article.publishedAt).toLocaleDateString("ja-JP")}
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <div className="text-center py-16">
              <p className="text-gray-400 text-lg">
                このカテゴリにはまだ記事がありません
              </p>
            </div>
          )}
        </section>
      </main>
      <Footer />
    </>
  );
}
