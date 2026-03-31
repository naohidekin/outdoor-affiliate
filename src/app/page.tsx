import Link from "next/link";
import { getCategories, getPublishedArticles } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export const dynamic = "force-dynamic";

export default function Home() {
  const categories = getCategories();
  const articles = getPublishedArticles();

  return (
    <>
      <Header categories={categories} />
      <main className="flex-1">
        {/* Hero */}
        <section className="bg-gradient-to-br from-green-700 to-green-900 text-white py-20">
          <div className="max-w-6xl mx-auto px-4 text-center">
            <h1 className="text-4xl md:text-5xl font-bold mb-4">
              Outdoor Gear Lab
            </h1>
            <p className="text-lg text-green-200 mb-8">
              アウトドア用品を徹底比較。あなたにぴったりのギアが見つかる。
            </p>
            <div className="flex flex-wrap justify-center gap-3">
              {categories.map((c) => (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="bg-white/15 hover:bg-white/25 text-white px-5 py-2 rounded-full text-sm transition backdrop-blur"
                >
                  {c.name}
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* Categories */}
        <section className="max-w-6xl mx-auto px-4 py-16">
          <h2 className="text-2xl font-bold text-gray-800 mb-8">
            カテゴリから探す
          </h2>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-6">
            {categories.map((c) => {
              const articleCount = articles.filter(
                (a) => a.categoryId === c.id
              ).length;
              return (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="bg-white rounded-xl shadow-sm hover:shadow-md transition p-6 border border-gray-100"
                >
                  <h3 className="font-bold text-gray-800 text-lg mb-2">
                    {c.name}
                  </h3>
                  <p className="text-sm text-gray-500 mb-3">{c.description}</p>
                  <span className="text-xs text-green-600">
                    {articleCount}件の記事 →
                  </span>
                </Link>
              );
            })}
          </div>
        </section>

        {/* Latest Articles */}
        {articles.length > 0 && (
          <section className="max-w-6xl mx-auto px-4 pb-16">
            <h2 className="text-2xl font-bold text-gray-800 mb-8">
              最新の記事
            </h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {articles.slice(0, 6).map((article) => {
                const cat = categories.find(
                  (c) => c.id === article.categoryId
                );
                return (
                  <Link
                    key={article.id}
                    href={`/articles/${article.slug}`}
                    className="bg-white rounded-xl shadow-sm hover:shadow-md transition overflow-hidden border border-gray-100"
                  >
                    <div className="p-6">
                      {cat && (
                        <span className="text-xs text-green-600 font-medium">
                          {cat.name}
                        </span>
                      )}
                      <h3 className="font-bold text-gray-800 mt-1 mb-2 line-clamp-2">
                        {article.title}
                      </h3>
                      <p className="text-sm text-gray-500 line-clamp-3">
                        {article.excerpt}
                      </p>
                      <p className="text-xs text-gray-400 mt-3">
                        {article.publishedAt &&
                          new Date(article.publishedAt).toLocaleDateString(
                            "ja-JP"
                          )}
                      </p>
                    </div>
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        {/* Empty state */}
        {articles.length === 0 && (
          <section className="max-w-6xl mx-auto px-4 pb-16 text-center">
            <div className="bg-gray-50 rounded-xl p-12">
              <p className="text-gray-400 text-lg mb-4">
                まだ記事が公開されていません
              </p>
              <Link
                href="/admin"
                className="text-green-600 hover:text-green-700 font-medium"
              >
                管理画面から記事を作成 →
              </Link>
            </div>
          </section>
        )}
      </main>
      <Footer />
    </>
  );
}
