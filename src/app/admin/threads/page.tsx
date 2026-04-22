"use client";

import { useEffect, useState } from "react";

interface ThreadsPost {
  id: string;
  rowIndex: number;
  type: string;
  text: string;
  url: string | null;
  status: string;
  postedAt: string | null;
  threadsStatus: string;
  threadsPostUrl: string | null;
}

const POST_TYPE_LABELS: Record<string, string> = {
  outdoor_tip: "アウトドアTips",
  gear_thread: "ギアスレッド",
  article_promo: "記事プロモ",
  seasonal_hook: "季節フック",
  ai_dev_log: "AI開発ログ",
  parenting_outdoor: "子育て×アウトドア",
  doc_health_tip: "医師×健康",
  repost_rewrite: "リライト",
  article_repost: "記事リポスト",
};

export default function ThreadsPage() {
  const [posts, setPosts] = useState<ThreadsPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"pending" | "posted" | "error">("pending");
  const [posting, setPosting] = useState<string | null>(null);

  useEffect(() => {
    fetchPosts();
  }, []);

  async function fetchPosts() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/threads-posts");
      if (!res.ok) throw new Error("取得に失敗しました");
      const data = await res.json();
      setPosts(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  }

  async function postNow(id: string) {
    if (!confirm("この投稿をThreadsに送信しますか？")) return;
    setPosting(id);
    try {
      const res = await fetch("/api/threads-posts/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      const result = await res.json();
      if (res.ok && result.ok) {
        alert(`投稿しました ✓\n${result.postUrl}`);
        fetchPosts();
      } else {
        alert(`投稿に失敗しました\n${result.error}`);
      }
    } finally {
      setPosting(null);
    }
  }

  const pending = posts.filter((p) => !p.threadsStatus);
  const posted = posts.filter((p) => p.threadsStatus === "posted");
  const errored = posts.filter((p) => p.threadsStatus === "error");

  const tabPosts = tab === "pending" ? pending : tab === "posted" ? posted : errored;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Threads 投稿管理</h1>
          <p className="text-sm text-gray-500 mt-1">X投稿済みコンテンツをThreadsへ展開</p>
        </div>
        <button
          onClick={fetchPosts}
          className="px-4 py-2 text-sm bg-white border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600"
        >
          更新
        </button>
      </div>

      {/* 統計 */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
          <p className="text-2xl font-bold text-amber-600">{pending.length}</p>
          <p className="text-xs text-gray-500 mt-1">未投稿</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
          <p className="text-2xl font-bold text-green-600">{posted.length}</p>
          <p className="text-xs text-gray-500 mt-1">投稿済</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
          <p className="text-2xl font-bold text-red-600">{errored.length}</p>
          <p className="text-xs text-gray-500 mt-1">エラー</p>
        </div>
      </div>

      {/* タブ */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        {(["pending", "posted", "error"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
              tab === t ? "bg-white shadow text-gray-900" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t === "pending" ? `未投稿 (${pending.length})` : t === "posted" ? `投稿済 (${posted.length})` : `エラー (${errored.length})`}
          </button>
        ))}
      </div>

      {/* コンテンツ */}
      {loading ? (
        <div className="text-center py-16 text-gray-400">読み込み中...</div>
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <p className="text-red-600 font-medium">{error}</p>
          {error.includes("THREADS_") && (
            <p className="text-sm text-red-500 mt-2">
              .env.local に THREADS_USER_ID と THREADS_ACCESS_TOKEN を設定してください
            </p>
          )}
        </div>
      ) : tabPosts.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          {tab === "pending" ? "未投稿のコンテンツはありません" : tab === "posted" ? "投稿済みのコンテンツはありません" : "エラーはありません"}
        </div>
      ) : (
        <div className="space-y-3">
          {tabPosts.map((post) => (
            <div key={post.id} className="bg-white rounded-xl border border-gray-200 p-4 hover:border-gray-300 transition">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  {/* バッジ行 */}
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">
                      {POST_TYPE_LABELS[post.type] || post.type}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      post.status === "posted" ? "bg-blue-100 text-blue-700" : "bg-yellow-100 text-yellow-700"
                    }`}>
                      X: {post.status === "posted" ? "投稿済" : "キュー中"}
                    </span>
                    {post.threadsStatus === "posted" && (
                      <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs">
                        Threads: 投稿済
                      </span>
                    )}
                    {post.threadsStatus === "error" && (
                      <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs">
                        Threads: エラー
                      </span>
                    )}
                  </div>

                  {/* テキスト */}
                  <p className="text-sm text-gray-800 whitespace-pre-wrap line-clamp-3">{post.text}</p>

                  {/* URL */}
                  {post.url && (
                    <p className="text-xs text-gray-400 mt-1 truncate">{post.url}</p>
                  )}

                  {/* Threads投稿URL */}
                  {post.threadsPostUrl && (
                    <a
                      href={post.threadsPostUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-purple-600 hover:underline mt-1 block"
                    >
                      Threadsで見る →
                    </a>
                  )}
                </div>

                {/* アクション */}
                <div className="flex flex-col gap-2 shrink-0">
                  {!post.threadsStatus && (
                    <button
                      onClick={() => postNow(post.id)}
                      disabled={posting === post.id}
                      className="px-3 py-1.5 bg-purple-600 text-white rounded-lg text-xs hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                    >
                      {posting === post.id ? "投稿中..." : "すぐに投稿"}
                    </button>
                  )}
                  {post.threadsStatus === "error" && (
                    <button
                      onClick={() => postNow(post.id)}
                      disabled={posting === post.id}
                      className="px-3 py-1.5 bg-red-100 text-red-700 rounded-lg text-xs hover:bg-red-200 disabled:opacity-50 font-medium"
                    >
                      {posting === post.id ? "投稿中..." : "再投稿"}
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
