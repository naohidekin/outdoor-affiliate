"use client";

import { useEffect, useMemo, useState } from "react";

const NOTION_DB_URL = "https://www.notion.so/60f5162434c44ada951165a88cf6e6d4";

type AmbleStatus = "draft" | "cross_reviewed" | "evidence_ok" | "reviewed" | "approved" | "posted" | "rejected" | "dead_letter";

type ABCDScores = {
  a?: number | null;
  b?: number | null;
  c?: number | null;
  d?: number | null;
  ai?: number | null;
};

type AmblePost = {
  id: string;
  text: string;
  body?: string;
  type?: string;
  status: AmbleStatus;
  score_a?: number | null;
  score_b?: number | null;
  score_c?: number | null;
  score_d?: number | null;
  score_ai?: number | null;
  wiseScores?: ABCDScores | null;
  gptScores?: ABCDScores | null;
  claimRisk?: string | null;
  _voiceSource?: string;
  _format?: string;
};

// "承認待ち" = reviewed（5段階パイプライン通過済み）→ 承認はNotionで行う
const PENDING_STATUSES: AmbleStatus[] = ["reviewed", "draft"];

const TABS: Array<{ key: string; label: string; filter: (p: AmblePost) => boolean }> = [
  { key: "pending", label: "承認待ち", filter: (p) => PENDING_STATUSES.includes(p.status) },
  { key: "approved", label: "キュー", filter: (p) => p.status === "approved" },
  { key: "posted", label: "投稿済み", filter: (p) => p.status === "posted" },
  { key: "rejected", label: "却下", filter: (p) => p.status === "rejected" },
];

function scoreTone(value: number | null | undefined) {
  if (value == null) return "bg-gray-800 text-gray-300 ring-1 ring-white/10";
  if (value >= 8) return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30";
  if (value >= 6) return "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30";
  return "bg-rose-500/15 text-rose-300 ring-1 ring-rose-500/30";
}

export default function AmblePage() {
  const [posts, setPosts] = useState<AmblePost[]>([]);
  const [activeTab, setActiveTab] = useState<string>("pending");
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

  const filteredPosts = useMemo(() => {
    const tab = TABS.find((t) => t.key === activeTab);
    return tab ? posts.filter(tab.filter) : [];
  }, [activeTab, posts]);

  async function deletePost(post: AmblePost) {
    if (!confirm(`本当に削除しますか？\n\n${post.text.substring(0, 50)}...`)) {
      return;
    }
    setUpdatingId(post.id);
    try {
      const response = await fetch("/api/amble/posts", {
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
        <p className="text-sm uppercase tracking-[0.3em] text-cyan-400">SNS管理</p>
        <h1 className="mt-2 text-3xl font-semibold">アンブロ</h1>
        <p className="mt-2 text-sm text-gray-400">パイプライン生成結果のモニター。承認・却下は Notion で行います。</p>
        <a
          href={NOTION_DB_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex items-center gap-2 rounded-full bg-cyan-500 px-4 py-2 text-sm font-medium text-gray-950 transition hover:bg-cyan-400"
        >
          Notion で承認する →
        </a>
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
              {posts.filter(tab.filter).length}
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
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <p className="text-xs uppercase tracking-[0.25em] text-gray-500">{post.id}</p>
                    {post.type ? <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-gray-400">{post.type}</span> : null}
                    {post._format ? <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-gray-400">{post._format}</span> : null}
                  </div>
                  <p className="mt-3 max-w-4xl whitespace-pre-wrap text-sm leading-7 text-gray-200">{post.text}</p>
                  {(post.score_a != null || post.gptScores) ? (
                    <div className="mt-3 flex flex-wrap gap-4 text-xs">
                      {post.score_a != null ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-gray-500">Claude:</span>
                          {["A","B","C","D","AI"].map((label, i) => {
                            const val = [post.score_a, post.score_b, post.score_c, post.score_d, post.score_ai][i];
                            return <span key={label} className={`rounded px-1.5 py-0.5 ${scoreTone(val)}`}>{label}:{val ?? "-"}</span>;
                          })}
                        </div>
                      ) : null}
                      {post.gptScores ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-gray-500">GPT:</span>
                          {["A","B","C","D","AI"].map((label) => {
                            const key = label === "AI" ? "ai" : label.toLowerCase();
                            const val = (post.gptScores as Record<string, number | null>)?.[key];
                            return <span key={label} className={`rounded px-1.5 py-0.5 ${scoreTone(val)}`}>{label}:{val ?? "-"}</span>;
                          })}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className="flex gap-2">
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
