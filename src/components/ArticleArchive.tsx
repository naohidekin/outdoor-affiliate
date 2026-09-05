"use client";

import { useMemo, useState } from "react";
import { Article, Category, Product } from "@/lib/types";
import ArticleCard from "./ArticleCard";

interface Props {
  articles: Article[]; // content は空にして渡す（ペイロード削減）
  categories: Category[];
  thumbs: Record<string, Product | undefined>; // articleId -> サムネ用商品
}

// 記事アーカイブ。108本を1ページに出す代わりに、キーワード検索と
// カテゴリ絞り込みをクライアント側で行う（記事メタは軽いので全件渡してよい）
export default function ArticleArchive({ articles, categories, thumbs }: Props) {
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return articles.filter((a) => {
      if (categoryId && a.categoryId !== categoryId) return false;
      if (!q) return true;
      return (
        a.title.toLowerCase().includes(q) ||
        (a.excerpt ?? "").toLowerCase().includes(q) ||
        (a.tags ?? []).some((t) => t.toLowerCase().includes(q))
      );
    });
  }, [articles, query, categoryId]);

  // 記事が実在するカテゴリだけチップにする（0件カテゴリのチップは邪魔なだけ）
  const usedCategories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const a of articles) {
      counts.set(a.categoryId, (counts.get(a.categoryId) ?? 0) + 1);
    }
    return categories
      .filter((c) => (counts.get(c.id) ?? 0) > 0)
      .map((c) => ({ ...c, count: counts.get(c.id) ?? 0 }))
      .sort((a, b) => b.count - a.count);
  }, [articles, categories]);

  return (
    <div>
      {/* 検索ボックス */}
      <div className="mb-5">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="キーワードで記事を探す"
          className="w-full sm:max-w-md min-h-11 px-4 py-3 rounded-xl border border-line bg-white text-base focus:outline-none focus:border-lake-300 focus:ring-2 focus:ring-lake-100"
          aria-label="記事をキーワードで検索"
        />
      </div>

      <div className="sm:hidden mb-5">
        <label htmlFor="article-category" className="block mb-2 text-sm font-medium text-slate-600">カテゴリで絞り込む</label>
        <select id="article-category" value={categoryId ?? ""} onChange={(event) => setCategoryId(event.target.value || null)} className="w-full min-h-11 rounded-xl border border-line bg-white px-4 py-3 text-base text-ink">
          <option value="">すべて（{articles.length}）</option>
          {usedCategories.map((c) => <option key={c.id} value={c.id}>{c.name}（{c.count}）</option>)}
        </select>
      </div>

      {/* 広い画面ではカテゴリを一覧で選べる */}
      <div className="hidden sm:flex flex-wrap gap-2 mb-6">
        <button
          onClick={() => setCategoryId(null)}
          aria-pressed={categoryId === null}
          className={`min-h-11 px-3 py-2 rounded-full text-sm font-medium border transition ${
            categoryId === null
              ? "bg-lake-600 text-white border-lake-600"
              : "bg-white text-slate-600 border-line hover:border-lake-200"
          }`}
        >
          すべて（{articles.length}）
        </button>
        {usedCategories.map((c) => (
          <button
            key={c.id}
            onClick={() => setCategoryId(categoryId === c.id ? null : c.id)}
            aria-pressed={categoryId === c.id}
            className={`min-h-11 px-3 py-2 rounded-full text-sm font-medium border transition ${
              categoryId === c.id
                ? "bg-lake-600 text-white border-lake-600"
                : "bg-white text-slate-600 border-line hover:border-lake-200"
            }`}
          >
            {c.name}（{c.count}）
          </button>
        ))}
      </div>

      <div className="mb-4 flex items-center justify-between gap-3">
        <p role="status" className="text-sm text-slate-500">{filtered.length}件の記事</p>
        {(query || categoryId) && <button onClick={() => { setQuery(""); setCategoryId(null); }} className="min-h-11 px-2 text-sm text-lake-700 underline underline-offset-4">条件をクリア</button>}
      </div>

      {/* 記事グリッド */}
      {filtered.length > 0 ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-5">
          {filtered.map((a) => (
            <ArticleCard
              key={a.id}
              article={a}
              category={categories.find((c) => c.id === a.categoryId)}
              thumbnailProduct={thumbs[a.id]}
            />
          ))}
        </div>
      ) : (
        <div className="bg-mist rounded-xl p-12 border border-line text-center">
          <p className="text-slate-500">
            「{query}」に一致する記事が見つかりませんでした
          </p>
        </div>
      )}
    </div>
  );
}
