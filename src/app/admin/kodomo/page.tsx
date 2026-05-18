"use client";

import { useEffect, useMemo, useState } from "react";

type KodomoStatus = "reviewed" | "approved" | "posted" | "rejected" | "dead_letter";

type KodomoPost = {
  id: string;
  body: string;
  status: KodomoStatus;
  humanApprovedBy?: string | null;
  humanApprovedAt?: string | null;
  _wiseScores?: {
    w: number;
    i: number;
    s: number;
    e: number;
    ai: number;
  } | null;
  // Legacy fields (no longer displayed)
  score?: number | null;
  claimRisk?: "low" | "medium" | "high" | string | null;
  _scores?: Record<string, number | null | undefined>;
};

const TABS: Array<{ key: "reviewed" | "approved" | "posted"; label: string }> = [
  { key: "reviewed", label: "レビュー待ち" },
  { key: "approved", label: "承認済み" },
  { key: "posted", label: "投稿済み" },
];

function scoreTone(value: number | null | undefined) {
  if (value == null) return "bg-gray-800 text-gray-300 ring-1 ring-white/10";
  if (value >= 8) return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30";
  if (value >= 6) return "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30";
  return "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30";
}

function claimRiskTone(value: string | null | undefined) {
  if (value === "high") return "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30";
  if (value === "medium") return "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30";
  return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30";
}

export default function KodomoPage() {
  const [posts, setPosts] = useState<KodomoPost[]>([]);
  const [activeTab, setActiveTab] = useState<"reviewed" | "approved" | "posted">("reviewed");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/kodomo/posts")
      .then(async (response) => {
        const payload = (await response.json()) as KodomoPost[] & { error?: string };
        if (!response.ok || !Array.isArray(payload)) {
          throw new Error(payload?.error || "投稿一覧の取得に失敗しました");
        }
        setPosts(payload);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "投稿一覧の取得に失敗しました");
      })
      .finally(() => setLoading(false));
  }, []);

  const filteredPosts = useMemo(
    () => posts.filter((post) => post.status === activeTab),
    [activeTab, posts]
  );

  async function approvePost(post: KodomoPost) {
    setUpdatingId(post.id);
    try {
      const response = await fetch("/api/kodomo/posts", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: post.id,
          status: "approved",
          humanApprovedBy: "admin",
          humanApprovedAt: new Date().toISOString(),
        }),
      });
      const payload = (await response.json()) as KodomoPost & { error?: string };
      if (!response.ok) {
        throw new Error(payload.error || "更新に失敗しました");
      }
      setPosts((current) => current.map((item) => (item.id === post.id ? payload : item)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally {
      setUpdatingId(null);
    }
  }

  async function deletePost(post: KodomoPost) {
    if (!confirm(`本当に削除しますか？\n\n${post.body.substring(0, 50)}...`)) {
      return;
    }
    setUpdatingId(post.id);
    try {
      const response = await fetch("/api/kodomo/posts", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: post.id }),
      });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) {
        throw new Error(payload.error || "削除に失敗しました");
      }
      setPosts((current) => current.filter((item) => item.id !== post.id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "削除に失敗しました");
    } finally {
      setUpdatingId(null);
    }
  }

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      <div className="mb-6">
        <p className="text-sm uppercase tracking-[0.3em] text-amber-400">SNS管理</p>
        <h1 className="mt-2 text-3xl font-semibold">こどもケアラボ</h1>
        <p className="mt-2 text-sm text-gray-400">レビュー済み投稿を承認し、スコアとリスクを一覧で確認します。</p>
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-full px-4 py-2 text-sm transition ${
              activeTab === tab.key
                ? "bg-amber-400 text-gray-950"
                : "bg-white/5 text-gray-300 ring-1 ring-white/10 hover:bg-white/10"
            }`}
          >
            {tab.label}
            <span className="ml-2 rounded-full bg-black/20 px-2 py-0.5 text-xs">
              {posts.filter((post) => post.status === tab.key).length}
            </span>
          </button>
        ))}
      </div>

      {error ? (
        <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="space-y-4">
        {loading ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-sm text-gray-400">読み込み中...</div>
        ) : filteredPosts.length === 0 ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-sm text-gray-400">対象の投稿はありません。</div>
        ) : (
          filteredPosts.map((post) => (
            <article key={post.id} className="rounded-3xl border border-white/10 bg-white/5 p-5 shadow-[0_20px_50px_rgba(0,0,0,0.25)]">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.25em] text-gray-500">{post.id}</p>
                  <p className="mt-3 max-w-4xl whitespace-pre-wrap text-sm leading-7 text-gray-200">{post.body}</p>
                </div>
                <div className="flex gap-2">
                  {post.status === "reviewed" ? (
                    <button
                      type="button"
                      onClick={() => approvePost(post)}
                      disabled={updatingId === post.id}
                      className="rounded-full bg-emerald-500 px-4 py-2 text-sm font-medium text-gray-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {updatingId === post.id ? "承認中..." : "承認する"}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => deletePost(post)}
                    disabled={updatingId === post.id}
                    className="rounded-full bg-rose-500/20 px-4 py-2 text-sm font-medium text-rose-300 transition hover:bg-rose-500/30 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {updatingId === post.id ? "削除中..." : "削除"}
                  </button>
                </div>
              </div>

              {post._wiseScores && (
                <div className="mt-4 flex flex-wrap gap-1.5 text-[11px]">
                  <span className={`rounded px-2 py-1 font-mono ${post._wiseScores.w >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    W:{post._wiseScores.w}
                  </span>
                  <span className={`rounded px-2 py-1 font-mono ${post._wiseScores.i >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    I:{post._wiseScores.i}
                  </span>
                  <span className={`rounded px-2 py-1 font-mono ${post._wiseScores.s >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    S:{post._wiseScores.s}
                  </span>
                  <span className={`rounded px-2 py-1 font-mono ${post._wiseScores.e >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    E:{post._wiseScores.e}
                  </span>
                  <span className={`rounded px-2 py-1 font-mono ${post._wiseScores.ai >= 3 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    AI:{post._wiseScores.ai}
                  </span>
                </div>
              )}
            </article>
          ))
        )}
      </div>
    </div>
  );
}
