"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type DashboardData = {
  gearman: { ready: number };
  killSwitch: { enabled: boolean; articleStopped: boolean; reason: string };
};

const INITIAL_DATA: DashboardData = {
  gearman: { ready: 0 },
  killSwitch: { enabled: false, articleStopped: false, reason: "" },
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

  const quickLinks = [
    { href: "/admin/articles", label: "記事管理", detail: "執筆・公開予約・公開" },
    { href: "/admin/products", label: "商品管理", detail: "アフィリンク・価格・画像" },
    { href: "/admin/affiliate", label: "アフィリ分析", detail: "記事別・商品別クリック" },
    { href: "/admin/notion-queue", label: "リプ運用", detail: "Notion承認キュー" },
  ];

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-green-400">camp-gear-lab</p>
          <h1 className="mt-2 text-3xl font-semibold">管理ホーム</h1>
          <p className="mt-2 text-sm text-gray-400">
            記事・商品・アフィリ計測・X承認キューの状態をまとめて確認します。
          </p>
        </div>
        <div
          className={`rounded-full px-4 py-2 text-sm font-medium ${
            data.killSwitch.enabled
              ? "bg-red-500/15 text-red-300 ring-1 ring-red-500/30"
              : "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30"
          }`}
        >
          KILL_SWITCH {data.killSwitch.enabled ? "ON（全停止）" : "OFF（稼働中）"}
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-3xl border border-emerald-500/30 bg-gradient-to-br from-emerald-500/20 to-emerald-700/5 p-5 shadow-[0_20px_60px_rgba(0,0,0,0.25)]">
          <p className="text-sm text-gray-300">ギア男 X 投稿キュー</p>
          <div className="mt-4 flex items-end justify-between gap-3">
            <p className="text-4xl font-semibold tabular-nums">{loading ? "..." : data.gearman.ready}</p>
            <span className="rounded-full bg-black/30 px-3 py-1 text-xs text-gray-200">ready</span>
          </div>
        </div>
        <div
          className={`rounded-3xl border bg-gradient-to-br p-5 shadow-[0_20px_60px_rgba(0,0,0,0.25)] ${
            data.killSwitch.articleStopped
              ? "border-rose-500/30 from-rose-500/20 to-rose-700/5"
              : "border-sky-500/30 from-sky-500/20 to-sky-700/5"
          }`}
        >
          <p className="text-sm text-gray-300">記事パイプライン</p>
          <div className="mt-4 flex items-end justify-between gap-3">
            <p className="text-2xl font-semibold">{loading ? "..." : data.killSwitch.articleStopped ? "停止中" : "稼働許可"}</p>
            <span className="rounded-full bg-black/30 px-3 py-1 text-xs text-gray-200">article-daily / weekly</span>
          </div>
        </div>
        <div className="rounded-3xl border border-white/10 bg-gradient-to-br from-white/10 to-white/0 p-5 shadow-[0_20px_60px_rgba(0,0,0,0.25)]">
          <p className="text-sm text-gray-300">停止理由</p>
          <p className="mt-4 text-sm text-gray-300">
            {loading ? "..." : data.killSwitch.reason || "（設定なし）"}
          </p>
        </div>
      </div>

      <div className="mt-6 rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <h2 className="text-lg font-semibold">よく使う画面</h2>
        <div className="mt-5 grid gap-4 md:grid-cols-4">
          {quickLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-2xl border border-white/10 bg-black/20 p-4 transition-colors hover:border-green-400/40 hover:bg-black/30"
            >
              <p className="text-sm font-medium text-gray-100">{link.label}</p>
              <p className="mt-1 text-xs text-gray-500">{link.detail}</p>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
