"use client";

import { useEffect, useState } from "react";

type DashboardData = {
  gearman: { ready: number };
  amble: { draft: number; approved: number };
  kodomo: { reviewed: number };
  killSwitch: { enabled: boolean };
};

const INITIAL_DATA: DashboardData = {
  gearman: { ready: 0 },
  amble: { draft: 0, approved: 0 },
  kodomo: { reviewed: 0 },
  killSwitch: { enabled: false },
};

export default function AdminDashboardPage() {
  const [data, setData] = useState<DashboardData>(INITIAL_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/dashboard")
      .then(async (response) => {
        const payload = (await response.json()) as DashboardData & { error?: string };
        if (!response.ok) {
          throw new Error(payload.error || "ダッシュボードの取得に失敗しました");
        }
        setData(payload);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "ダッシュボードの取得に失敗しました");
      })
      .finally(() => setLoading(false));
  }, []);

  const cards = [
    {
      label: "ギア男",
      value: data.gearman.ready,
      detail: "投稿待ち",
      tone: "from-emerald-500/20 to-emerald-700/5 border-emerald-500/30",
    },
    {
      label: "アンブロ",
      value: data.amble.draft,
      detail: `承認待ち / キュー ${data.amble.approved}`,
      tone: "from-cyan-500/20 to-cyan-700/5 border-cyan-500/30",
    },
    {
      label: "こどもケアラボ",
      value: data.kodomo.reviewed,
      detail: "レビュー待ち",
      tone: "from-amber-500/20 to-amber-700/5 border-amber-500/30",
    },
    {
      label: "システム状態",
      value: data.killSwitch.enabled ? 1 : 0,
      detail: "KILL_SWITCH",
      tone: "from-rose-500/20 to-rose-700/5 border-rose-500/30",
    },
  ];

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-green-400">Unified Admin</p>
          <h1 className="mt-2 text-3xl font-semibold">マルチ事業ダッシュボード</h1>
          <p className="mt-2 text-sm text-gray-400">横断の承認待ち件数とシステム状態をまとめて確認します。</p>
        </div>
        <div
          className={`rounded-full px-4 py-2 text-sm font-medium ${
            data.killSwitch.enabled
              ? "bg-red-500/15 text-red-300 ring-1 ring-red-500/30"
              : "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30"
          }`}
        >
          KILL_SWITCH {data.killSwitch.enabled ? "ON" : "OFF"}
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className={`rounded-3xl border bg-gradient-to-br p-5 ${card.tone} shadow-[0_20px_60px_rgba(0,0,0,0.25)]`}
          >
            <p className="text-sm text-gray-300">{card.label}</p>
            <div className="mt-4 flex items-end justify-between gap-3">
              <p className="text-4xl font-semibold tabular-nums">{loading ? "..." : card.value}</p>
              <span className="rounded-full bg-black/30 px-3 py-1 text-xs text-gray-200">{card.detail}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <h2 className="text-lg font-semibold">承認フロー概要</h2>
          <div className="mt-5 grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <p className="text-sm text-gray-400">ギア男</p>
              <p className="mt-2 text-2xl font-semibold text-emerald-300">{loading ? "..." : data.gearman.ready}</p>
              <p className="mt-1 text-sm text-gray-500">ready キュー</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <p className="text-sm text-gray-400">アンブロ</p>
              <p className="mt-2 text-2xl font-semibold text-cyan-300">{loading ? "..." : data.amble.draft}</p>
              <p className="mt-1 text-sm text-gray-500">draft / approved {loading ? "..." : data.amble.approved}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <p className="text-sm text-gray-400">こどもケアラボ</p>
              <p className="mt-2 text-2xl font-semibold text-amber-300">{loading ? "..." : data.kodomo.reviewed}</p>
              <p className="mt-1 text-sm text-gray-500">reviewed 投稿</p>
            </div>
          </div>
        </section>

        <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <h2 className="text-lg font-semibold">システム状態</h2>
          <div className="mt-5 rounded-2xl border border-white/10 bg-black/20 p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm text-gray-400">自動投稿</p>
                <p className="mt-1 text-sm text-gray-500">ギア男の kill-switch 状態を表示</p>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-sm font-medium ${
                  data.killSwitch.enabled
                    ? "bg-red-500/15 text-red-300 ring-1 ring-red-500/30"
                    : "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30"
                }`}
              >
                {data.killSwitch.enabled ? "停止中" : "稼働中"}
              </span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
