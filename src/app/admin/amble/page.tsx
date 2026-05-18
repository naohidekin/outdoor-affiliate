"use client";

import { useEffect, useMemo, useState } from "react";

type AmbleStatus = "draft" | "approved" | "posted" | "skip" | "rejected";

type AmblePost = {
  id: string;
  text: string;
  status: AmbleStatus;
  score_a?: number | null;
  score_b?: number | null;
  score_c?: number | null;
  score_d?: number | null;
  score_ai?: number | null;
};

const TABS: Array<{ key: AmbleStatus; label: string }> = [
  { key: "draft", label: "承認待ち" },
  { key: "approved", label: "キュー" },
  { key: "posted", label: "投稿済み" },
];

function scoreTone(value: number | null | undefined) {
  if (value == null) return "bg-gray-800 text-gray-300 ring-1 ring-white/10";
  if (value >= 8) return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30";
  if (value >= 6) return "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30";
  return "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30";
}

export default function AmblePage() {
  const [posts, setPosts] = useState<AmblePost[]>([]);
  const [activeTab, setActiveTab] = useState<AmbleStatus>("draft");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/amble/posts")
      .then(async (response) => {
        const payload = (await response.json()) as AmblePost[] & { error?: string };
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

  async function updateStatus(id: string, status: AmbleStatus) {
    setUpdatingId(id);
    try {
      const response = await fetch("/api/amble/posts", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, status }),
      });
      const payload = (await response.json()) as AmblePost & { error?: string };
      if (!response.ok) {
        throw new Error(payload.error || "更新に失敗しました");
      }
      setPosts((current) => current.map((post) => (post.id === id ? payload : post)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally {
      setUpdatingId(null);
    }
  }

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      <div className="mb-6">
        <p className="text-sm uppercase tracking-[0.3em] text-cyan-400">SNS管理</p>
        <h1 className="mt-2 text-3xl font-semibold">アンブロ</h1>
        <p className="mt-2 text-sm text-gray-400">X投稿候補の承認フローをここから操作します。</p>
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-full px-4 py-2 text-sm transition ${
              activeTab === tab.key
                ? "bg-cyan-500 text-gray-950"
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
                  <p className="mt-3 line-clamp-4 max-w-4xl text-sm leading-7 text-gray-200">{post.text}</p>
                </div>
                {post.status === "draft" ? (
                  <button
                    type="button"
                    onClick={() => updateStatus(post.id, "approved")}
                    disabled={updatingId === post.id}
                    className="rounded-full bg-emerald-500 px-4 py-2 text-sm font-medium text-gray-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {updatingId === post.id ? "承認中..." : "承認する"}
                  </button>
                ) : null}
              </div>

              <div className="mt-4 flex flex-wrap gap-1.5 text-[11px]">
                {post.score_a != null && (
                  <span className={`rounded px-2 py-1 font-mono ${post.score_a >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    W:{post.score_a}
                  </span>
                )}
                {post.score_b != null && (
                  <span className={`rounded px-2 py-1 font-mono ${post.score_b >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    I:{post.score_b}
                  </span>
                )}
                {post.score_c != null && (
                  <span className={`rounded px-2 py-1 font-mono ${post.score_c >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    S:{post.score_c}
                  </span>
                )}
                {post.score_d != null && (
                  <span className={`rounded px-2 py-1 font-mono ${post.score_d >= 2 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    E:{post.score_d}
                  </span>
                )}
                {post.score_ai != null && (
                  <span className={`rounded px-2 py-1 font-mono ${post.score_ai >= 3 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"}`}>
                    AI:{post.score_ai}
                  </span>
                )}
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
