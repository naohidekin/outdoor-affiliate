"use client";

import { useState, useEffect } from "react";
import { Product, Category } from "@/lib/types";

export default function AdminProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [editing, setEditing] = useState<Product | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [specsText, setSpecsText] = useState("");

  const emptyProduct: Omit<Product, "id" | "createdAt" | "updatedAt"> = {
    name: "",
    brand: "",
    price: 0,
    imageUrl: "",
    affiliateUrl: "",
    categoryId: "",
    specs: {},
    description: "",
    rating: 0,
  };

  const [form, setForm] = useState(emptyProduct);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    const [prodRes, catRes] = await Promise.all([
      fetch("/api/products"),
      fetch("/api/categories"),
    ]);
    setProducts(await prodRes.json());
    setCategories(await catRes.json());
  }

  function openNew() {
    setForm(emptyProduct);
    setSpecsText("");
    setEditing(null);
    setShowForm(true);
  }

  function openEdit(product: Product) {
    setForm(product);
    setSpecsText(
      Object.entries(product.specs)
        .map(([k, v]) => `${k}: ${v}`)
        .join("\n")
    );
    setEditing(product);
    setShowForm(true);
  }

  function parseSpecs(text: string): Record<string, string> {
    const specs: Record<string, string> = {};
    text.split("\n").forEach((line) => {
      const [key, ...rest] = line.split(":");
      if (key && rest.length) {
        specs[key.trim()] = rest.join(":").trim();
      }
    });
    return specs;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const data = { ...form, specs: parseSpecs(specsText) };

    if (editing) {
      await fetch("/api/products", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...data, id: editing.id }),
      });
    } else {
      await fetch("/api/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    }

    setShowForm(false);
    fetchData();
  }

  async function handleDelete(id: string) {
    if (!confirm("この商品を削除しますか？")) return;
    await fetch(`/api/products?id=${id}`, { method: "DELETE" });
    fetchData();
  }

  const getCategoryName = (id: string) =>
    categories.find((c) => c.id === id)?.name || "未分類";

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold text-gray-800">商品管理</h1>
        <button
          onClick={openNew}
          className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition"
        >
          + 新規登録
        </button>
      </div>

      {showForm && (
        <div className="bg-white rounded-xl shadow p-6 mb-8">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">
            {editing ? "商品を編集" : "新規商品登録"}
          </h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  商品名 *
                </label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  ブランド
                </label>
                <input
                  type="text"
                  value={form.brand}
                  onChange={(e) => setForm({ ...form, brand: e.target.value })}
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  価格（税込）
                </label>
                <input
                  type="number"
                  value={form.price}
                  onChange={(e) =>
                    setForm({ ...form, price: parseInt(e.target.value) || 0 })
                  }
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  カテゴリ *
                </label>
                <select
                  value={form.categoryId}
                  onChange={(e) => setForm({ ...form, categoryId: e.target.value })}
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
                  required
                >
                  <option value="">選択してください</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  評価 (1-5)
                </label>
                <input
                  type="number"
                  min={0}
                  max={5}
                  step={0.5}
                  value={form.rating}
                  onChange={(e) =>
                    setForm({ ...form, rating: parseFloat(e.target.value) || 0 })
                  }
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  画像URL
                </label>
                <input
                  type="url"
                  value={form.imageUrl}
                  onChange={(e) => setForm({ ...form, imageUrl: e.target.value })}
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
                  placeholder="https://..."
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                アフィリエイトリンク
              </label>
              <input
                type="url"
                value={form.affiliateUrl}
                onChange={(e) => setForm({ ...form, affiliateUrl: e.target.value })}
                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
                placeholder="https://px.a8.net/..."
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                説明
              </label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                スペック（1行1項目「項目名: 値」形式）
              </label>
              <textarea
                value={specsText}
                onChange={(e) => setSpecsText(e.target.value)}
                rows={5}
                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none font-mono text-sm text-gray-800"
                placeholder={`重量: 1.5kg\nサイズ: 210×130×105cm\n耐水圧: 3000mm`}
              />
            </div>
            <div className="flex gap-3">
              <button
                type="submit"
                className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition"
              >
                {editing ? "更新" : "登録"}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="bg-gray-200 text-gray-700 px-6 py-2 rounded-lg hover:bg-gray-300 transition"
              >
                キャンセル
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                商品名
              </th>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                ブランド
              </th>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                カテゴリ
              </th>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                価格
              </th>
              <th className="text-left px-6 py-3 text-sm font-medium text-gray-500">
                評価
              </th>
              <th className="text-right px-6 py-3 text-sm font-medium text-gray-500">
                操作
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {products.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-gray-400">
                  商品がまだ登録されていません
                </td>
              </tr>
            ) : (
              products.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 text-sm text-gray-800 font-medium">
                    {p.name}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">{p.brand}</td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    {getCategoryName(p.categoryId)}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    {p.price > 0 ? `¥${p.price.toLocaleString()}` : "-"}
                  </td>
                  <td className="px-6 py-4 text-sm text-yellow-500">
                    {"★".repeat(Math.floor(p.rating))}
                    {p.rating % 1 >= 0.5 ? "☆" : ""}
                  </td>
                  <td className="px-6 py-4 text-right space-x-2">
                    <button
                      onClick={() => openEdit(p)}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      編集
                    </button>
                    <button
                      onClick={() => handleDelete(p.id)}
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
