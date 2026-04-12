"use client";

import { useEffect, useState } from "react";

interface XAnalyticsData {
  period: { start: string; end: string; days: number };
  xTraffic: {
    totalSessions: number;
    totalPageViews: number;
    byDay: Array<{ date: string; sessions: number; pageViews: number }>;
    topPages: Array<{
      path: string;
      pageViews: number;
      sessions: number;
      affiliateClicks: number;
    }>;
  } | null;
  affiliateClicks: {
    total: number;
    byStore: { amazon: number; rakuten: number };
    byPage: Array<{ path: string; clicks: number }>;
    topProducts: Array<{ productId: string; store: string; count: number }>;
  };
  trafficSources: Array<{ source: string; sessions: number }>;
}

export default function XAnalyticsPage() {
  const [data, setData] = useState<XAnalyticsData | null>(null);
  const [days, setDays] = useState(28);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`/api/x-analytics?days=${days}`)
      .then(async (r) => {
        if (!r.ok) throw new Error("API error");
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [days]);

  const xSessions = data?.xTraffic?.totalSessions || 0;
  const totalSessions =
    data?.trafficSources?.reduce((s, t) => s + t.sessions, 0) || 0;
  const xShare = totalSessions > 0 ? (xSessions / totalSessions) * 100 : 0;
  const xPV = data?.xTraffic?.totalPageViews || 0;
  const affClicks = data?.affiliateClicks?.total || 0;
  const clickRate = xPV > 0 ? (affClicks / xPV) * 100 : 0;

  const maxDayPV = Math.max(
    ...(data?.xTraffic?.byDay?.map((d) => d.pageViews) || [1])
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">X Analytics</h1>
          <p className="text-sm text-gray-500 mt-1">
            X 経由トラフィック + アフィリエイトクリック
          </p>
        </div>
        <div className="flex gap-2">
          {[7, 14, 28].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded-full text-sm ${
                days === d
                  ? "bg-green-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {d}日
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="text-center py-16 text-gray-400">読み込み中...</div>
      )}
      {error && (
        <div className="text-center py-16 text-red-500">エラー: {error}</div>
      )}

      {data && !loading && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <SummaryCard
              label="X経由セッション"
              value={xSessions.toLocaleString()}
              sub={`全体の ${xShare.toFixed(1)}%`}
            />
            <SummaryCard
              label="X経由PV"
              value={xPV.toLocaleString()}
            />
            <SummaryCard
              label="アフィリエイトクリック"
              value={affClicks.toLocaleString()}
              sub={`Amazon ${data.affiliateClicks.byStore.amazon} / 楽天 ${data.affiliateClicks.byStore.rakuten}`}
            />
            <SummaryCard
              label="クリック率"
              value={`${clickRate.toFixed(2)}%`}
              sub="クリック / PV"
            />
          </div>

          {/* Daily chart */}
          {data.xTraffic && data.xTraffic.byDay.length > 0 && (
            <div className="mb-8">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                日別 X 経由 PV
              </h2>
              <div className="space-y-1">
                {data.xTraffic.byDay.map((d) => (
                  <div key={d.date} className="flex items-center gap-2 text-xs">
                    <span className="w-20 text-gray-400 shrink-0">
                      {d.date.slice(4, 6)}/{d.date.slice(6)}
                    </span>
                    <div className="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
                      <div
                        className="bg-green-500 h-full rounded-full transition-all"
                        style={{
                          width: `${(d.pageViews / maxDayPV) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="w-12 text-right text-gray-600">
                      {d.pageViews}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top pages from X */}
          {data.xTraffic &&
            data.xTraffic.topPages.length > 0 && (
              <div className="mb-8">
                <h2 className="text-sm font-semibold text-gray-700 mb-3">
                  X 経由 Top 記事
                </h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-gray-500">
                        <th className="pb-2 font-medium">記事</th>
                        <th className="pb-2 font-medium text-right">PV</th>
                        <th className="pb-2 font-medium text-right">
                          セッション
                        </th>
                        <th className="pb-2 font-medium text-right">
                          クリック
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.xTraffic.topPages.map((p) => (
                        <tr
                          key={p.path}
                          className="border-b border-gray-50 hover:bg-gray-50"
                        >
                          <td className="py-2 text-gray-700">
                            {p.path.replace("/articles/", "").replace(/\/$/, "")}
                          </td>
                          <td className="py-2 text-right text-gray-600">
                            {p.pageViews}
                          </td>
                          <td className="py-2 text-right text-gray-600">
                            {p.sessions}
                          </td>
                          <td className="py-2 text-right text-gray-600">
                            {p.affiliateClicks}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

          {/* Traffic sources */}
          {data.trafficSources.length > 0 && (
            <div className="mb-8">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                流入元 Top 10
              </h2>
              <div className="space-y-1.5">
                {data.trafficSources.map((s) => {
                  const pct =
                    totalSessions > 0
                      ? (s.sessions / totalSessions) * 100
                      : 0;
                  return (
                    <div
                      key={s.source}
                      className="flex items-center gap-2 text-xs"
                    >
                      <span
                        className={`w-24 shrink-0 font-medium ${
                          s.source === "x" || s.source === "twitter"
                            ? "text-green-700"
                            : "text-gray-500"
                        }`}
                      >
                        {s.source || "(direct)"}
                      </span>
                      <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            s.source === "x" || s.source === "twitter"
                              ? "bg-green-500"
                              : "bg-gray-300"
                          }`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-16 text-right text-gray-600">
                        {s.sessions} ({pct.toFixed(1)}%)
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Top affiliate products */}
          {data.affiliateClicks.topProducts.length > 0 && (
            <div className="mb-8">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                アフィリエイト クリック Top 商品
              </h2>
              <div className="space-y-1">
                {data.affiliateClicks.topProducts.map((p, i) => (
                  <div
                    key={`${p.productId}-${p.store}`}
                    className="flex items-center gap-3 text-xs py-1"
                  >
                    <span className="w-6 text-gray-400 text-right">
                      {i + 1}.
                    </span>
                    <span className="flex-1 text-gray-700">{p.productId}</span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs ${
                        p.store === "amazon"
                          ? "bg-orange-50 text-orange-600"
                          : "bg-red-50 text-red-600"
                      }`}
                    >
                      {p.store === "amazon" ? "Amazon" : "楽天"}
                    </span>
                    <span className="w-10 text-right font-medium text-gray-600">
                      {p.count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* No GA4 data notice */}
          {!data.xTraffic && (
            <div className="text-center py-8 text-gray-400 text-sm">
              GA4 データを取得できませんでした。GA4_PROPERTY_ID /
              GOOGLE_CREDENTIALS を確認してください。
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className="text-2xl font-bold text-gray-800">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}
