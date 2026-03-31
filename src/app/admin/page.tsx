import { getArticles, getProducts, getCategories } from "@/lib/db";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default function AdminDashboard() {
  const articles = getArticles();
  const products = getProducts();
  const categories = getCategories();

  const publishedCount = articles.filter((a) => a.status === "published").length;
  const draftCount = articles.filter((a) => a.status === "draft").length;

  const stats = [
    { label: "公開記事", value: publishedCount, color: "bg-green-500", href: "/admin/articles" },
    { label: "下書き", value: draftCount, color: "bg-yellow-500", href: "/admin/articles" },
    { label: "商品", value: products.length, color: "bg-blue-500", href: "/admin/products" },
    { label: "カテゴリ", value: categories.length, color: "bg-purple-500", href: "/admin/categories" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-800 mb-8">ダッシュボード</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-8">
        {stats.map((stat) => (
          <Link
            key={stat.label}
            href={stat.href}
            className="bg-white rounded-xl shadow p-6 hover:shadow-lg transition"
          >
            <div className={`w-3 h-3 rounded-full ${stat.color} mb-3`} />
            <p className="text-3xl font-bold text-gray-800">{stat.value}</p>
            <p className="text-sm text-gray-500">{stat.label}</p>
          </Link>
        ))}
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl shadow p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">最近の記事</h2>
          {articles.length === 0 ? (
            <p className="text-gray-400 text-sm">まだ記事がありません</p>
          ) : (
            <ul className="space-y-3">
              {articles.slice(0, 5).map((a) => (
                <li key={a.id} className="flex items-center justify-between">
                  <Link
                    href={`/admin/articles?edit=${a.id}`}
                    className="text-sm text-gray-700 hover:text-green-600 truncate"
                  >
                    {a.title}
                  </Link>
                  <span
                    className={`text-xs px-2 py-1 rounded-full ${
                      a.status === "published"
                        ? "bg-green-100 text-green-700"
                        : "bg-yellow-100 text-yellow-700"
                    }`}
                  >
                    {a.status === "published" ? "公開" : "下書き"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="bg-white rounded-xl shadow p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">クイックアクション</h2>
          <div className="space-y-3">
            <Link
              href="/admin/articles?new=1"
              className="block w-full text-center bg-green-600 text-white py-3 rounded-lg hover:bg-green-700 transition font-medium"
            >
              + 新しい記事を作成
            </Link>
            <Link
              href="/admin/products?new=1"
              className="block w-full text-center bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 transition font-medium"
            >
              + 新しい商品を登録
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
