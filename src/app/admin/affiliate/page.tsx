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
  period: { days: number; start: string; end: string };
  total: number;
  byStore: StoreMap;
  byPlacement?: Record<string, number>;
  articleRanking: ArticleRow[];
  productRanking: ProductRow[];
  journeyRanking: (ArticleRow & { productId: string; name: string; placement: string })[];
}

const PLACEMENT_LABEL: Record<string, string> = {
  product_card: "商品カード",
  ranking: "ランキング",
  comparison_table: "比較表",
  recommended: "おすすめCTA",
  body_text: "本文リンク",
  article_end: "記事末尾",
  reviews_link: "口コミリンク",
  room_collection: "ROOMコレクション",
  footer_room: "フッターのROOM",
  unknown: "不明",
  "(計測前)": "計測前(旧データ)",
};

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
    const controller = new AbortController();
    setData(null);
    setLoading(true);
    setError(null);
    fetch(`/api/affiliate-analytics?days=${days}`, { signal: controller.signal })
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.error || `API error (${r.status})`);
        return body;
      })
      .then((body) => { if (!controller.signal.aborted) setData(body); })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [days]);

  const maxArticle = Math.max(1, ...(data?.articleRanking.map((a) => a.clicks) || [1]));

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">アフィリエイトの送客分析</h1>
          <p className="text-sm text-gray-500 mt-1">
            記事・商品・ボタン位置ごとの販売店へのクリック。注文数・購入者数・確定報酬とは異なります。
          </p>
        </div>
        <div className="flex gap-2">
          {[7, 28, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              aria-pressed={days === d}
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
          <p className="text-sm text-gray-500 mb-4">
            {new Date(data.period.start).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })} 〜 {new Date(data.period.end).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}（日本時間）
          </p>
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

          {/* ボタン位置別（placement）— 「商品が弱い」か「位置が弱い」かの切り分け */}
          {data.byPlacement && Object.keys(data.byPlacement).length > 0 && (
            <>
              <h2 className="text-lg font-bold text-gray-900 mb-2">ボタン位置別クリック</h2>
              <p className="text-sm text-gray-500 mb-2">
                どの位置のボタンが押されているか。表示回数が異なるので、クリック数だけで位置の優劣は判断できません。表示回数との比較はGA4で確認します。
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-8">
                {Object.entries(data.byPlacement)
                  .sort((a, b) => b[1] - a[1])
                  .map(([p, n]) => (
                    <div key={p} className="bg-white rounded-lg border border-gray-200 p-3">
                      <p className="text-xs text-gray-500">{PLACEMENT_LABEL[p] || p}</p>
                      <p className="text-xl font-bold text-gray-900">{n.toLocaleString()}</p>
                    </div>
                  ))}
              </div>
            </>
          )}

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
                    <a href={a.path || undefined} target="_blank" rel="noopener noreferrer" className="text-sm text-gray-900 hover:text-green-700 hover:underline">
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

          <h2 className="text-lg font-bold text-gray-900 mb-2">記事 × 商品 × ボタン位置</h2>
          <p className="text-sm text-gray-500 mb-3">改善する商品案内を具体的に探せます。クリックの多い順に表示します。</p>
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100 mb-8">
            {data.journeyRanking.length === 0 && <p className="p-4 text-sm text-gray-500">この期間のクリックデータはありません。</p>}
            {data.journeyRanking.slice(0, 50).map((row) => <div key={JSON.stringify([row.path, row.productId, row.placement])} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-gray-500 break-words">{row.title}</p>
                  <p className="mt-1 text-base font-medium text-gray-900 break-words">{row.name}</p>
                  <p className="mt-1 text-sm text-gray-500">{PLACEMENT_LABEL[row.placement] || row.placement}</p>
                </div>
                <span className="text-lg font-bold text-gray-900 shrink-0">{row.clicks}</span>
              </div>
              <div className="mt-2"><StoreBadges stores={row.stores} /></div>
            </div>)}
            {data.journeyRanking.length > 50 && <p className="p-4 text-sm text-gray-500">上位50件を表示しています。総クリック数は全件を集計しています。</p>}
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
