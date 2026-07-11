"use client";

import { useState, useEffect } from "react";
import { Product, Category } from "@/lib/types";

interface AmazonSearchResult {
  asin: string;
  title: string;
  brand: string;
  price: number | null;
  availability: string;
  imageUrl: string;
  features: string[];
  amazonUrl: string;
  isNew: boolean;
}

// AmazonのURLからASINを抽出してアソシエイトURLを生成
function parseAmazonUrl(input: string): string {
  const m = input.match(/\/dp\/([A-Z0-9]{10})/);
  if (!m) return input;
  return `https://www.amazon.co.jp/dp/${m[1]}/?tag=camp78-22`;
}

export default function AdminProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [editing, setEditing] = useState<Product | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [specsText, setSpecsText] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<"list" | "search">("list");
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [autofilling, setAutofilling] = useState(false);
  const [amazonSearch, setAmazonSearch] = useState("");
  const [amazonResults, setAmazonResults] = useState<AmazonSearchResult[]>([]);
  const [amazonSearching, setAmazonSearching] = useState(false);
  const [amazonSearchError, setAmazonSearchError] = useState<string | null>(null);

  const emptyProduct: Omit<Product, "id" | "createdAt" | "updatedAt"> = {
    name: "", brand: "", price: 0,
    imageUrl: "", affiliateUrl: "", amazonUrl: "",
    categoryId: "", specs: {}, description: "", rating: 0,
  };

  const [form, setForm] = useState(emptyProduct);

  useEffect(() => { fetchData(); }, []);

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
    setSaveError(null);
    setSaveSuccess(false);
    setShowForm(true);
  }

  function openEdit(product: Product) {
    setForm(product);
    setSpecsText(Object.entries(product.specs).map(([k, v]) => `${k}: ${v}`).join("\n"));
    setEditing(product);
    setSaveError(null);
    setSaveSuccess(false);
    setShowForm(true);
  }

  function parseSpecs(text: string): Record<string, string> {
    const specs: Record<string, string> = {};
    text.split("\n").forEach((line) => {
      const [key, ...rest] = line.split(":");
      if (key && rest.length) specs[key.trim()] = rest.join(":").trim();
    });
    return specs;
  }

  // AmazonのURLが貼られたら自動でASIN抽出してフォーマット
  function handleAmazonUrlChange(raw: string) {
    const formatted = raw.includes("/dp/") ? parseAmazonUrl(raw) : raw;
    setForm((prev) => ({ ...prev, amazonUrl: formatted }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      const data = { ...form, specs: parseSpecs(specsText) };
      const res = await fetch("/api/products", {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editing ? { ...data, id: editing.id } : data),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }

      setSaveSuccess(true);
      setTimeout(() => {
        setShowForm(false);
        setSaveSuccess(false);
        fetchData();
      }, 800);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  }

  async function handleAutofill() {
    const asin = form.amazonUrl.match(/\/dp\/([A-Z0-9]{10})/)?.[1];
    if (!asin) {
      setSaveError("有効なAmazon URLを入力してください");
      return;
    }
    setAutofilling(true);
    setSaveError(null);
    try {
      const res = await fetch("/api/products/autofill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asin }),
      });
      if (!res.ok) throw new Error((await res.json()).error);
      const data = await res.json();
      setForm((prev) => ({
        ...prev,
        name: data.name || prev.name,
        brand: data.brand || prev.brand,
        price: data.price ?? prev.price,
        imageUrl: data.imageUrl || prev.imageUrl,
        amazonUrl: data.amazonUrl || prev.amazonUrl,
      }));
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "自動補完に失敗しました");
    } finally {
      setAutofilling(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setSyncResult(null);
    try {
      // Vercel 10秒制限内の10件バッチを、nextOffset が尽きるまでループして全件同期
      let offset: number | null = 0;
      let syncedTotal = 0;
      let grandTotal = 0;
      const allChanges: { name: string; oldPrice: number; newPrice: number }[] = [];
      while (offset !== null) {
        const res: Response = await fetch(`/api/products/sync?offset=${offset}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        syncedTotal += data.synced || 0;
        grandTotal = data.total || grandTotal;
        allChanges.push(...(data.changes || []));
        offset = data.nextOffset ?? null;
        setSyncResult(`同期中… ${offset === null ? grandTotal : offset}/${grandTotal} 件`);
      }
      const changeText = allChanges.length > 0
        ? `（価格変更: ${allChanges.map((c) => `${c.name} ¥${c.oldPrice.toLocaleString()}→¥${c.newPrice.toLocaleString()}`).join(", ")}）`
        : "";
      setSyncResult(`全${grandTotal}件を同期し、${syncedTotal}件を更新しました${changeText}`);
    } catch (err) {
      setSyncResult(
        (err instanceof Error ? err.message : "同期に失敗しました") +
          "（途中のバッチまではサーバに反映済みの可能性があります）"
      );
    } finally {
      // 途中失敗でも反映済み分があるため、一覧は必ず更新する
      fetchData();
      setSyncing(false);
    }
  }

  async function handleAmazonSearch() {
    if (!amazonSearch.trim()) return;
    setAmazonSearching(true);
    setAmazonResults([]);
    setAmazonSearchError(null);
    try {
      const res = await fetch(`/api/products/amazon-search?q=${encodeURIComponent(amazonSearch)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { results } = await res.json();
      setAmazonResults(results);
    } catch (e) {
      setAmazonSearchError(e instanceof Error ? e.message : "検索に失敗しました");
    } finally {
      setAmazonSearching(false);
    }
  }

  async function handleAddFromSearch(item: AmazonSearchResult) {
    const res = await fetch("/api/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: item.title,
        brand: item.brand,
        price: item.price ?? 0,
        imageUrl: item.imageUrl,
        amazonUrl: item.amazonUrl,
        affiliateUrl: "",
        categoryId: "",
        specs: {},
        description: item.features.join("\n"),
        rating: 0,
      }),
    });
    if (res.ok) {
      setAmazonResults((prev) => prev.map((r) => r.asin === item.asin ? { ...r, isNew: false } : r));
      fetchData();
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("この商品を削除しますか？")) return;
    await fetch(`/api/products?id=${id}`, { method: "DELETE" });
    fetchData();
  }

  const getCategoryName = (id: string) =>
    categories.find((c) => c.id === id)?.name || "未分類";

  const filtered = products.filter((p) =>
    !search || p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.brand.toLowerCase().includes(search.toLowerCase())
  );

  const fieldClass = "w-full px-3 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-gray-800 text-sm";

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">商品管理</h1>
        <div className="flex items-center gap-2">
          <button onClick={handleSync} disabled={syncing}
            className="flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm transition">
            {syncing && <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />}
            {syncing ? "同期中…" : "価格・在庫を同期"}
          </button>
          <button onClick={openNew} className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700 transition">
            + 新規登録
          </button>
        </div>
      </div>

      {syncResult && (
        <div className={`mb-4 px-4 py-2.5 rounded-lg text-sm border ${syncing ? "bg-blue-50 border-blue-200 text-blue-700" : "bg-green-50 border-green-200 text-green-700"}`}>
          {syncResult}
        </div>
      )}

      {showForm && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">
            {editing ? "商品を編集" : "新規商品登録"}
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* 基本情報 */}
            <div className="grid md:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">商品名 *</label>
                <input type="text" value={form.name} required
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className={fieldClass} placeholder="例: スノーピーク アメニティドームM" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">ブランド</label>
                <input type="text" value={form.brand}
                  onChange={(e) => setForm({ ...form, brand: e.target.value })}
                  className={fieldClass} placeholder="例: スノーピーク" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">カテゴリ *</label>
                <select value={form.categoryId} required
                  onChange={(e) => setForm({ ...form, categoryId: e.target.value })}
                  className={fieldClass}>
                  <option value="">選択してください</option>
                  {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">価格（税込）</label>
                <input type="number" value={form.price}
                  onChange={(e) => setForm({ ...form, price: parseInt(e.target.value) || 0 })}
                  className={fieldClass} placeholder="例: 29800" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">評価 (0〜5)</label>
                <input type="number" min={0} max={5} step={0.5} value={form.rating}
                  onChange={(e) => setForm({ ...form, rating: parseFloat(e.target.value) || 0 })}
                  className={fieldClass} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">画像URL</label>
                <input type="url" value={form.imageUrl}
                  onChange={(e) => setForm({ ...form, imageUrl: e.target.value })}
                  className={fieldClass} placeholder="https://..." />
              </div>
            </div>

            {/* アフィリエイトリンク */}
            <div className="grid md:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Amazon URL
                  <span className="ml-1 text-blue-500 font-normal">（商品ページURLをそのまま貼ればOK）</span>
                </label>
                <div className="flex gap-2">
                  <input type="text" value={form.amazonUrl}
                    onChange={(e) => handleAmazonUrlChange(e.target.value)}
                    className={`${fieldClass} flex-1`} placeholder="https://www.amazon.co.jp/dp/B0XXXXXXXX/..." />
                  <button type="button" onClick={handleAutofill} disabled={autofilling || !form.amazonUrl.includes("/dp/")}
                    className="shrink-0 px-3 py-1.5 bg-amber-50 border border-amber-300 text-amber-700 rounded-lg text-xs hover:bg-amber-100 disabled:opacity-40 transition whitespace-nowrap">
                    {autofilling ? "取得中…" : "自動補完"}
                  </button>
                </div>
                {form.amazonUrl && form.amazonUrl.includes("tag=camp78-22") && (
                  <p className="text-xs text-green-600 mt-1">✓ アソシエイトタグ付きURLに変換済み</p>
                )}
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">楽天アフィリエイトURL</label>
                <input type="url" value={form.affiliateUrl}
                  onChange={(e) => setForm({ ...form, affiliateUrl: e.target.value })}
                  className={fieldClass} placeholder="https://hb.afl.rakuten.co.jp/..." />
              </div>
            </div>

            {/* 説明・スペック */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">説明</label>
              <textarea value={form.description} rows={2}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className={fieldClass} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                スペック <span className="text-gray-400 font-normal">（1行1項目「項目名: 値」形式）</span>
              </label>
              <textarea value={specsText} rows={4}
                onChange={(e) => setSpecsText(e.target.value)}
                className={`${fieldClass} font-mono`}
                placeholder={"重量: 1.5kg\nサイズ: 210×130×105cm\n耐水圧: 3000mm"} />
            </div>

            {/* エラー / 成功 */}
            {saveError && (
              <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700">
                ⚠ {saveError}
              </div>
            )}
            {saveSuccess && (
              <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700">
                ✓ 保存しました
              </div>
            )}

            <div className="flex gap-2">
              <button type="submit" disabled={saving}
                className="flex items-center gap-2 bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-60 transition">
                {saving && <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                {saving ? "保存中…" : editing ? "更新" : "登録"}
              </button>
              <button type="button" onClick={() => setShowForm(false)} disabled={saving}
                className="bg-gray-100 text-gray-700 px-5 py-2 rounded-lg text-sm hover:bg-gray-200 disabled:opacity-50 transition">
                キャンセル
              </button>
            </div>
          </form>
        </div>
      )}

      {/* タブ */}
      <div className="flex gap-1 mb-4">
        <button onClick={() => setActiveTab("list")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition ${activeTab === "list" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
          商品一覧 ({products.length})
        </button>
        <button onClick={() => setActiveTab("search")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition ${activeTab === "search" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
          Amazon検索・追加
        </button>
      </div>

      {/* Amazon検索タブ */}
      {activeTab === "search" && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
          <div className="flex gap-2 mb-4">
            <input type="text" value={amazonSearch}
              onChange={(e) => setAmazonSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAmazonSearch()}
              placeholder="例: テント ファミリー, タープ ヘキサ"
              className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
            <button onClick={handleAmazonSearch} disabled={amazonSearching || !amazonSearch.trim()}
              className="bg-amber-500 hover:bg-amber-600 disabled:opacity-60 text-white px-5 py-2 rounded-lg text-sm transition">
              {amazonSearching ? "検索中…" : "検索"}
            </button>
          </div>
          {amazonResults.length > 0 && (
            <div className="space-y-3">
              {amazonResults.map((item) => (
                <div key={item.asin} className="flex items-start gap-3 border border-gray-100 rounded-lg p-3">
                  {item.imageUrl && (
                    <img src={item.imageUrl} alt={item.title} className="w-16 h-16 object-contain shrink-0 rounded" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{item.title}</p>
                    <p className="text-xs text-gray-500">{item.brand}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-sm font-semibold text-gray-700">
                        {item.price ? `¥${item.price.toLocaleString()}` : "価格不明"}
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${item.availability === "InStock" ? "bg-green-50 text-green-700" : "bg-gray-50 text-gray-500"}`}>
                        {item.availability === "InStock" ? "在庫あり" : item.availability === "OutOfStock" ? "在庫なし" : "不明"}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => handleAddFromSearch(item)}
                    disabled={!item.isNew}
                    className={`shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium transition ${item.isNew ? "bg-blue-600 text-white hover:bg-blue-700" : "bg-gray-100 text-gray-400 cursor-default"}`}>
                    {item.isNew ? "+ 追加" : "登録済み"}
                  </button>
                </div>
              ))}
            </div>
          )}
          {amazonSearchError && (
            <p className="text-sm text-red-500 text-center py-6">{amazonSearchError}</p>
          )}
          {!amazonSearching && !amazonSearchError && amazonSearch && amazonResults.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-6">検索結果がありません</p>
          )}
        </div>
      )}

      {/* 商品一覧 */}
      {activeTab === "list" && <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
          <span className="text-sm text-gray-500">{products.length}件</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="商品名・ブランドで絞り込み…"
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 w-60"
          />
        </div>
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-5 py-2.5 text-xs font-medium text-gray-500">商品名</th>
              <th className="text-left px-5 py-2.5 text-xs font-medium text-gray-500">ブランド</th>
              <th className="text-left px-5 py-2.5 text-xs font-medium text-gray-500">カテゴリ</th>
              <th className="text-left px-5 py-2.5 text-xs font-medium text-gray-500">価格</th>
              <th className="text-left px-5 py-2.5 text-xs font-medium text-gray-500">リンク</th>
              <th className="text-right px-5 py-2.5 text-xs font-medium text-gray-500">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-sm text-gray-400">
                  {search ? "該当する商品がありません" : "商品がまだ登録されていません"}
                </td>
              </tr>
            ) : (
              filtered.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50 transition">
                  <td className="px-5 py-3 text-sm text-gray-800 font-medium max-w-xs truncate">{p.name}</td>
                  <td className="px-5 py-3 text-sm text-gray-500">{p.brand}</td>
                  <td className="px-5 py-3 text-sm text-gray-500">{getCategoryName(p.categoryId)}</td>
                  <td className="px-5 py-3 text-sm text-gray-600">
                    <div>{p.price > 0 ? `¥${p.price.toLocaleString()}` : <span className="text-gray-300">-</span>}</div>
                    {p.availability === "OutOfStock" && (
                      <span className="text-xs text-red-500">在庫なし</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-xs space-x-2">
                    {p.amazonUrl && <span className="inline-block bg-amber-50 text-amber-700 border border-amber-200 rounded px-1.5 py-0.5">Amazon</span>}
                    {p.affiliateUrl && <span className="inline-block bg-red-50 text-red-700 border border-red-200 rounded px-1.5 py-0.5">楽天</span>}
                  </td>
                  <td className="px-5 py-3 text-right space-x-3">
                    <button onClick={() => openEdit(p)} className="text-blue-600 hover:text-blue-800 text-sm">編集</button>
                    <button onClick={() => handleDelete(p.id)} className="text-red-500 hover:text-red-700 text-sm">削除</button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>}
    </div>
  );
}
