"use client";

import { useState, useEffect } from "react";
import { Article, Category, Product } from "@/lib/types";

export default function AdminArticles() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [showEditor, setShowEditor] = useState(false);
  const [editing, setEditing] = useState<Article | null>(null);
  const [form, setForm] = useState({
    title: "",
    slug: "",
    categoryId: "",
    content: "",
    excerpt: "",
    productIds: [] as string[],
    status: "draft" as "draft" | "published",
  });
  const [previewMode, setPreviewMode] = useState(false);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    const [artRes, catRes, prodRes] = await Promise.all([
      fetch("/api/articles"),
      fetch("/api/categories"),
      fetch("/api/products"),
    ]);
    setArticles(await artRes.json());
    setCategories(await catRes.json());
    setProducts(await prodRes.json());
  }

  function openNew() {
    setForm({
      title: "",
      slug: "",
      categoryId: "",
      content: "",
      excerpt: "",
      productIds: [],
      status: "draft",
    });
    setEditing(null);
    setShowEditor(true);
    setPreviewMode(false);
  }

  function openEdit(article: Article) {
    setForm({
      title: article.title,
      slug: article.slug,
      categoryId: article.categoryId,
      content: article.content,
      excerpt: article.excerpt,
      productIds: article.productIds,
      status: article.status,
    });
    setEditing(article);
    setShowEditor(true);
    setPreviewMode(false);
  }

  async function handleSave(status?: "draft" | "published") {
    const data = { ...form, status: status || form.status };

    if (editing) {
      await fetch("/api/articles", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...data, id: editing.id }),
      });
    } else {
      await fetch("/api/articles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    }

    setShowEditor(false);
    fetchData();
  }

  async function handleDelete(id: string) {
    if (!confirm("この記事を削除しますか？")) return;
    await fetch(`/api/articles?id=${id}`, { method: "DELETE" });
    fetchData();
  }

  function insertProductCard(productId: string) {
    const tag = `\n\n{{product:${productId}}}\n\n`;
    setForm({ ...form, content: form.content + tag });
  }

  function insertComparisonTable() {
    if (form.productIds.length < 2) {
      alert("比較表を作成するには2つ以上の商品を選択してください");
      return;
    }
    const tag = `\n\n{{comparison:${form.productIds.join(",")}}}\n\n`;
    setForm({ ...form, content: form.content + tag });
  }

  function insertRanking() {
    if (form.productIds.length === 0) {
      alert("ランキングを作成するには商品を選択してください");
      return;
    }
    const tag = `\n\n{{ranking:${form.productIds.join(",")}}}\n\n`;
    setForm({ ...form, content: form.content + tag });
  }

  function autoSlug(title: string) {
    return title
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60);
  }

  const toggleProduct = (id: string) => {
    setForm({
      ...form,
      productIds: form.productIds.includes(id)
        ? form.productIds.filter((p) => p !== id)
        : [...form.productIds, id],
    });
  };

  const getCategoryName = (id: string) =>
    categories.find((c) => c.id === id)?.name || "未分類";

  const CATEGORY_HASHTAGS: Record<string, string> = {
    tent: "#テント #ファミキャン",
    light: "#ランタン #キャンプギア",
    "sleeping-bag": "#シュラフ #寝袋",
    burner: "#バーナー #キャンプ飯",
    backpack: "#登山 #バックパック",
    wear: "#アウトドアウェア #レインウェア",
    shoes: "#トレッキングシューズ #登山靴",
  };

  async function copyXPostText(article: Article) {
    const cat = categories.find((c) => c.id === article.categoryId);
    const catTags = CATEGORY_HASHTAGS[article.categoryId] || "";
    const excerpt = article.excerpt.length > 100
      ? article.excerpt.slice(0, 100) + "..."
      : article.excerpt;

    const text = `${article.title}

${excerpt}

詳しくはこちら
https://camp-gear-lab.com/articles/${article.slug}

#アウトドア #キャンプ ${catTags}`.trim();

    await navigator.clipboard.writeText(text);
    alert("X投稿テキストをコピーしました！");
  }

  if (showEditor) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-800">
            {editing ? "記事を編集" : "新規記事作成"}
          </h1>
          <button
            onClick={() => setShowEditor(false)}
            className="text-gray-500 hover:text-gray-700"
          >
            ← 一覧に戻る
          </button>
        </div>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Editor */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white rounded-xl shadow p-6 space-y-4">
              <input
                type="text"
                value={form.title}
                onChange={(e) => {
                  const title = e.target.value;
                  setForm({
                    ...form,
                    title,
                    slug: editing ? form.slug : autoSlug(title),
                  });
                }}
                placeholder="記事タイトル"
                className="w-full text-xl font-bold px-0 py-2 border-0 border-b-2 border-gray-200 focus:border-green-500 focus:outline-none text-gray-800"
              />
              <div className="flex gap-4 text-sm">
                <div className="flex-1">
                  <label className="text-gray-500">スラッグ</label>
                  <input
                    type="text"
                    value={form.slug}
                    onChange={(e) => setForm({ ...form, slug: e.target.value })}
                    className="w-full px-3 py-1 border rounded text-gray-800 focus:outline-none focus:ring-1 focus:ring-green-500"
                  />
                </div>
                <div>
                  <label className="text-gray-500">カテゴリ</label>
                  <select
                    value={form.categoryId}
                    onChange={(e) =>
                      setForm({ ...form, categoryId: e.target.value })
                    }
                    className="w-full px-3 py-1 border rounded text-gray-800 focus:outline-none focus:ring-1 focus:ring-green-500"
                  >
                    <option value="">選択</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="text-sm text-gray-500">概要（excerpt）</label>
                <textarea
                  value={form.excerpt}
                  onChange={(e) => setForm({ ...form, excerpt: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-2 border rounded-lg text-gray-800 focus:outline-none focus:ring-1 focus:ring-green-500"
                  placeholder="記事の概要を入力..."
                />
              </div>

              {/* Toolbar */}
              <div className="flex flex-wrap gap-2 bg-gray-50 p-3 rounded-lg">
                <button
                  type="button"
                  onClick={() => setPreviewMode(!previewMode)}
                  className={`px-3 py-1 text-sm rounded ${
                    previewMode
                      ? "bg-green-600 text-white"
                      : "bg-white border text-gray-700"
                  }`}
                >
                  {previewMode ? "編集に戻る" : "プレビュー"}
                </button>
                <span className="border-l mx-1" />
                <button
                  type="button"
                  onClick={insertComparisonTable}
                  className="px-3 py-1 text-sm bg-white border rounded text-gray-700 hover:bg-gray-100"
                >
                  📊 比較表を挿入
                </button>
                <button
                  type="button"
                  onClick={insertRanking}
                  className="px-3 py-1 text-sm bg-white border rounded text-gray-700 hover:bg-gray-100"
                >
                  🏆 ランキングを挿入
                </button>
              </div>

              {previewMode ? (
                <div className="prose max-w-none bg-gray-50 p-6 rounded-lg min-h-[400px]">
                  <div
                    dangerouslySetInnerHTML={{
                      __html: form.content
                        .replace(
                          /\{\{product:([^}]+)\}\}/g,
                          '<div class="bg-blue-50 p-4 rounded border border-blue-200 my-4">[商品カード: $1]</div>'
                        )
                        .replace(
                          /\{\{comparison:([^}]+)\}\}/g,
                          '<div class="bg-green-50 p-4 rounded border border-green-200 my-4">[比較表: $1]</div>'
                        )
                        .replace(
                          /\{\{ranking:([^}]+)\}\}/g,
                          '<div class="bg-yellow-50 p-4 rounded border border-yellow-200 my-4">[ランキング: $1]</div>'
                        )
                        .replace(/\n/g, "<br/>"),
                    }}
                  />
                </div>
              ) : (
                <textarea
                  value={form.content}
                  onChange={(e) => setForm({ ...form, content: e.target.value })}
                  rows={20}
                  className="w-full px-4 py-3 border rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-green-500 text-gray-800"
                  placeholder={`## おすすめテント10選

キャンプに欠かせないテント。今回は2026年版のおすすめテントを紹介します。

### 1. コールマン ツーリングドームST

{{product:商品IDがここに入ります}}

初心者から上級者まで幅広く使えるテントです。

{{comparison:商品ID1,商品ID2,商品ID3}}

### まとめ

{{ranking:商品ID1,商品ID2,商品ID3}}`}
                />
              )}
            </div>
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            {/* Publish */}
            <div className="bg-white rounded-xl shadow p-6">
              <h3 className="font-semibold text-gray-800 mb-4">公開設定</h3>
              <div className="space-y-3">
                <button
                  onClick={() => handleSave("draft")}
                  className="w-full bg-gray-200 text-gray-700 py-2 rounded-lg hover:bg-gray-300 transition"
                >
                  下書き保存
                </button>
                <button
                  onClick={() => handleSave("published")}
                  className="w-full bg-green-600 text-white py-2 rounded-lg hover:bg-green-700 transition"
                >
                  公開する
                </button>
              </div>
            </div>

            {/* Product selector */}
            <div className="bg-white rounded-xl shadow p-6">
              <h3 className="font-semibold text-gray-800 mb-4">
                関連商品を選択
              </h3>
              <p className="text-xs text-gray-400 mb-3">
                記事に掲載する商品にチェックを入れてください
              </p>
              <div className="max-h-64 overflow-y-auto space-y-2">
                {products.length === 0 ? (
                  <p className="text-gray-400 text-sm">
                    商品が登録されていません
                  </p>
                ) : (
                  products.map((p) => (
                    <label
                      key={p.id}
                      className="flex items-start gap-2 cursor-pointer hover:bg-gray-50 p-2 rounded"
                    >
                      <input
                        type="checkbox"
                        checked={form.productIds.includes(p.id)}
                        onChange={() => toggleProduct(p.id)}
                        className="mt-1"
                      />
                      <div>
                        <div className="text-sm text-gray-800">{p.name}</div>
                        <div className="text-xs text-gray-400">
                          {getCategoryName(p.categoryId)}
                        </div>
                      </div>
                    </label>
                  ))
                )}
              </div>
              {form.productIds.length > 0 && (
                <div className="mt-3 pt-3 border-t">
                  <p className="text-xs text-gray-500 mb-2">
                    選択中: {form.productIds.length}件
                  </p>
                  <div className="space-y-1">
                    {form.productIds.map((id) => {
                      const p = products.find((pr) => pr.id === id);
                      return (
                        p && (
                          <button
                            key={id}
                            onClick={() => insertProductCard(id)}
                            className="block w-full text-left text-xs px-2 py-1 bg-blue-50 text-blue-700 rounded hover:bg-blue-100"
                          >
                            + {p.name}のカードを挿入
                          </button>
                        )
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold text-gray-800">記事管理</h1>
        <button
          onClick={openNew}
          className="bg-green-600 text-white px-6 py-2 rounded-lg hover:bg-green-700 transition"
        >
          + 新規作成
        </button>
      </div>

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                タイトル
              </th>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                カテゴリ
              </th>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                ステータス
              </th>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                更新日
              </th>
              <th className="text-right px-6 py-3 text-sm font-medium text-gray-500">
                操作
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {articles.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-gray-400">
                  記事がまだありません
                </td>
              </tr>
            ) : (
              articles.map((a) => (
                <tr key={a.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 text-sm text-gray-800 font-medium">
                    {a.title}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    {getCategoryName(a.categoryId)}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`text-xs px-2 py-1 rounded-full ${
                        a.status === "published"
                          ? "bg-green-100 text-green-700"
                          : "bg-yellow-100 text-yellow-700"
                      }`}
                    >
                      {a.status === "published" ? "公開" : "下書き"}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {new Date(a.updatedAt).toLocaleDateString("ja-JP")}
                  </td>
                  <td className="px-6 py-4 text-right space-x-2">
                    <button
                      onClick={() => openEdit(a)}
                      className="text-green-600 hover:text-green-800 text-sm"
                    >
                      編集
                    </button>
                    {a.status === "published" && (
                      <button
                        onClick={() => copyXPostText(a)}
                        className="text-blue-600 hover:text-blue-800 text-sm"
                      >
                        X投稿
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(a.id)}
                      className="text-red-600 hover:text-red-800 text-sm"
                    >
                      削除
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
