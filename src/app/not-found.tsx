import Link from "next/link";
import { getPublicCategories } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export default async function NotFound() {
  const categories = await getPublicCategories();

  return (
    <>
      <Header categories={categories} />
      <main className="flex-1">
        <div className="max-w-2xl mx-auto px-4 py-20 text-center">
          <p className="text-7xl font-bold text-lake-200 mb-4 select-none">404</p>
          <h1 className="text-2xl font-semibold text-ink-strong mb-3">
            ページが見つかりません
          </h1>
          <p className="text-slate-500 mb-10">
            お探しのページは削除されたか、URLが変更されている可能性があります。
          </p>

          <Link
            href="/"
            className="inline-block bg-lake-600 hover:bg-lake-700 text-white px-6 py-3 rounded-lg font-medium transition mb-12"
          >
            トップページへ戻る
          </Link>

          <div className="border-t border-line pt-10">
            <p className="text-sm font-medium text-slate-400 mb-5">カテゴリから探す</p>
            <div className="flex flex-wrap justify-center gap-2">
              {categories.map((cat) => (
                <Link
                  key={cat.id}
                  href={`/category/${cat.slug}`}
                  className="text-sm text-lake-600 hover:text-lake-700 border border-lake-200 hover:border-lake-400 px-3 py-1.5 rounded-full transition"
                >
                  {cat.name}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </main>
      <Footer categories={categories} />
    </>
  );
}
