"use client";

import { useEffect, useState } from "react";

type StoreMap = Record<string, number>;
interface ArticleRow {
  path: string;
  title: string;
  clicks: number;
  stores: StoreMap;
}
interface ProductRow {
  productId: string;
  name: string;
  clicks: number;
  stores: StoreMap;
}
interface Data {
  period: { days: number; start: string };
  total: number;
  byStore: StoreMap;
  articleRanking: ArticleRow[];
  productRanking: ProductRow[];
}

const STORE_LABEL: Record<string, string> = {
  amazon: "Amazon",
  rakuten: "楽天",
  yahoo: "Yahoo",
  valuecommerce: "VC",
  other: "その他",
};
const STORE_COLOR: Record<string, string> = {
  amazon: "bg-amber-100 text-amber-800",
  rakuten: "bg-red-100 text-red-700",
  yahoo: "bg-purple-100 text-purple-700",
  valuecommerce: "bg-teal-100 text-teal-700",
  other: "bg-gray-100 text-gray-600",
};

function StoreBadges({ stores }: { stores: StoreMap }) {
  const entries = Object.entries(stores).sort((a, b) => b[1] - a[1]);
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([s, n]) => (
        <span key={s} className={`text-xs px-1.5 py-0.5 rounded ${STORE_COLOR[s] || STORE_COLOR.other}`}>
          {STORE_LABEL[s] || s} {n}
        </span>
      ))}
    </div>
  );
}

export default function AffiliateAnalyticsPage() {
  const [data, setData] = useState<Data | null>(null);
  const [days, setDays] = useState(28);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`/api/affiliate-analytics?days=${days}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`API error (${r.status})`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [days]);

  const maxArticle = Math.max(1, ...(data?.articleRanking.map((a) => a.clicks) || [1]));

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">📈 アフィリ分析（記事別）</h1>
          <p className="text-sm text-gray-500 mt-1">
            どの記事・どの商品からアフィリンクがクリックされたか（自前の affiliate_clicks 集計）
          </p>
        </div>
        <div className="flex gap-2">
          {[7, 28, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded text-sm font-medium ${
                days === d ? "bg-gray-900 text-white" : "bg-white text-gray-600 border border-gray-300"
              }`}
            >
              {d}日
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-gray-500">読み込み中…</p>}
      {error && <p className="text-red-600">エラー: {error}</p>}

      {data && (
        <>
          {/* KPI */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <p className="text-xs text-gray-500">総クリック</p>
              <p className="text-2xl font-bold text-gray-900">{data.total.toLocaleString()}</p>
            </div>
            {["amazon", "rakuten", "valuecommerce"].map((s) => (
              <div key={s} className="bg-white rounded-lg border border-gray-200 p-4">
                <p className="text-xs text-gray-500">{STORE_LABEL[s]}</p>
                <p className="text-2xl font-bold text-gray-900">{(data.byStore[s] || 0).toLocaleString()}</p>
              </div>
            ))}
          </div>

          {/* 記事別ランキング */}
          <h2 className="text-lg font-bold text-gray-900 mb-2">記事別クリック</h2>
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden mb-8">
            {data.articleRanking.length === 0 && (
              <p className="p-4 text-sm text-gray-500">この期間のクリックデータはありません。</p>
            )}
            {data.articleRanking.map((a, i) => (
              <div key={a.path} className="p-3 border-b border-gray-100 last:border-b-0">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <span className="text-xs text-gray-400 mr-2">{i + 1}</span>
                    <a href={a.path} target="_blank" className="text-sm text-gray-900 hover:text-green-700 hover:underline">
                      {a.title}
                    </a>
                    <p className="text-xs text-gray-400 truncate">{a.path}</p>
                  </div>
                  <span className="text-sm font-bold text-gray-900 shrink-0">{a.clicks}</span>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <div className="flex-1 h-1.5 bg-gray-100 rounded overflow-hidden">
                    <div className="h-full bg-green-500" style={{ width: `${(a.clicks / maxArticle) * 100}%` }} />
                  </div>
                  <StoreBadges stores={a.stores} />
                </div>
              </div>
            ))}
          </div>

          {/* 商品別ランキング */}
          <h2 className="text-lg font-bold text-gray-900 mb-2">商品別クリック</h2>
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            {data.productRanking.length === 0 && (
              <p className="p-4 text-sm text-gray-500">この期間のクリックデータはありません。</p>
            )}
            {data.productRanking.slice(0, 30).map((p, i) => (
              <div key={p.productId} className="p-3 border-b border-gray-100 last:border-b-0 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <span className="text-xs text-gray-400 mr-2">{i + 1}</span>
                  <span className="text-sm text-gray-900">{p.name}</span>
                  <p className="text-xs text-gray-400 truncate">{p.productId}</p>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <StoreBadges stores={p.stores} />
                  <span className="text-sm font-bold text-gray-900 w-8 text-right">{p.clicks}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
