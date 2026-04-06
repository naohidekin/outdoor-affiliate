"use client";

import { useEffect, useState } from "react";

type XPostType =
  | "article_promo"
  | "outdoor_tip"
  | "article_repost"
  | "seasonal"
  | "rakuten_sale"
  | "amazon_deal"
  | "news_comment"
  | "gear_story";

interface XPost {
  id: string;
  type: XPostType;
  text: string;
  articleSlug: string | null;
  url: string | null;
  hashtags: string;
  status: "draft" | "approved" | "queued" | "posted";
  scheduledDate: string;
  generatedAt: string;
  postedAt: string | null;
  scheduledTime?: string;
  imageUrl?: string;
  prLabel?: boolean;
  validationErrors?: string;
}

const TYPE_LABELS: Record<XPostType, string> = {
  article_promo: "記事紹介",
  outdoor_tip: "豆知識",
  article_repost: "記事リポスト",
  seasonal: "季節",
  rakuten_sale: "楽天セール",
  amazon_deal: "Amazonセール",
  news_comment: "ニュース",
  gear_story: "ギア小話",
};

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "下書き", color: "bg-gray-100 text-gray-600" },
  approved: { label: "承認済", color: "bg-green-100 text-green-700" },
  queued: { label: "投稿待ち", color: "bg-yellow-100 text-yellow-700" },
  posted: { label: "投稿済", color: "bg-blue-100 text-blue-700" },
};

export default function XPostsPage() {
  const [posts, setPosts] = useState<XPost[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [copied, setCopied] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/x-posts")
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setPosts(data);
        } else {
          setError(data.error || "データの取得に失敗しました");
        }
      })
      .catch(() => setError("APIに接続できません"))
      .finally(() => setLoading(false));
  }, []);

  async function handleGenerate() {
    setGenerating(true);
    try {
      const res = await fetch("/api/x-posts/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ autoApprove: false }),
      });
      if (res.ok) {
        const data = await res.json();
        setPosts((prev) => [...data.posts, ...prev]);
      }
    } finally {
      setGenerating(false);
    }
  }

  async function copyToClipboard(post: XPost) {
    await navigator.clipboard.writeText(post.text);
    setCopied(post.id);
    setTimeout(() => setCopied(null), 2000);
    if (post.status !== "posted") {
      setTimeout(() => {
        if (confirm("Xに手動投稿しましたか？\n「投稿済」に変更しますか？")) {
          updateStatus(post.id, "posted");
        }
      }, 500);
    }
  }

  async function queueNow(id: string) {
    if (!confirm("この投稿をすぐにXに送信しますか？\nIFTTTが検知次第（5〜10分）投稿されます。")) return;
    const res = await fetch("/api/x-posts/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    if (res.ok) {
      const updated = await res.json();
      setPosts((prev) => prev.map((p) => (p.id === id ? updated : p)));
    } else {
      const err = await res.json();
      alert(err.error || "エラーが発生しました");
    }
  }

  async function updateStatus(id: string, status: XPost["status"]) {
    const res = await fetch("/api/x-posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id,
        status,
        ...(status === "posted" ? { postedAt: new Date().toISOString() } : {}),
      }),
    });
    const updated = await res.json();
    setPosts((prev) => prev.map((p) => (p.id === id ? updated : p)));
  }

  async function saveEdit(id: string) {
    const res = await fetch("/api/x-posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, text: editText }),
    });
    const updated = await res.json();
    setPosts((prev) => prev.map((p) => (p.id === id ? updated : p)));
    setEditing(null);
  }

  async function deletePost(id: string) {
    await fetch(`/api/x-posts?id=${id}`, { method: "DELETE" });
    setPosts((prev) => prev.filter((p) => p.id !== id));
  }

  function startEdit(post: XPost) {
    setEditing(post.id);
    setEditText(post.text);
  }

  const filtered =
    filter === "all" ? posts : posts.filter((p) => p.status === filter);

  const counts = {
    all: posts.length,
    draft: posts.filter((p) => p.status === "draft").length,
    approved: posts.filter((p) => p.status === "approved").length,
    queued: posts.filter((p) => p.status === "queued").length,
    posted: posts.filter((p) => p.status === "posted").length,
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">X 投稿管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            ギア男 @camp_gear_lab のツイート管理
          </p>
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
        >
          {generating ? "生成中..." : "今すぐ生成"}
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-6">
        {(
          [
            ["all", "すべて"],
            ["draft", "下書き"],
            ["approved", "承認済"],
            ["queued", "投稿待ち"],
            ["posted", "投稿済"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-3 py-1.5 rounded-full text-sm ${
              filter === key
                ? "bg-green-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {label} ({counts[key]})
          </button>
        ))}
      </div>

      {/* Posts list */}
      <div className="space-y-4">
        {filtered.map((post) => {
          const statusInfo = STATUS_LABELS[post.status];
          const isEditing = editing === post.id;

          return (
            <div
              key={post.id}
              className="bg-white rounded-xl border border-gray-200 p-5 hover:border-gray-300 transition"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  {/* Header */}
                  <div className="flex items-center gap-2 mb-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusInfo.color}`}
                    >
                      {statusInfo.label}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                      {TYPE_LABELS[post.type] || post.type}
                    </span>
                    <span className="text-xs text-gray-400">
                      {post.scheduledDate}
                    </span>
                    {post.url && (
                      <a
                        href={post.url}
                        target="_blank"
                        className="text-xs text-green-600 hover:underline"
                      >
                        記事リンク
                      </a>
                    )}
                  </div>

                  {/* Content */}
                  {isEditing ? (
                    <div>
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="w-full border border-gray-300 rounded-lg p-3 text-sm leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-green-500"
                        rows={6}
                      />
                      <div className="flex gap-2 mt-2">
                        <button
                          onClick={() => saveEdit(post.id)}
                          className="px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700"
                        >
                          保存
                        </button>
                        <button
                          onClick={() => setEditing(null)}
                          className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-sm hover:bg-gray-200"
                        >
                          キャンセル
                        </button>
                        <span className="text-xs text-gray-400 self-center ml-2">
                          {editText.length}/280文字
                        </span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-700 whitespace-pre-line leading-relaxed">
                      {post.text}
                    </p>
                  )}
                </div>

                {/* Actions */}
                {!isEditing && (
                  <div className="flex flex-col gap-1.5 shrink-0">
                    <button
                      onClick={() => copyToClipboard(post)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                        copied === post.id
                          ? "bg-green-600 text-white"
                          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {copied === post.id ? "コピー済!" : "コピー"}
                    </button>
                    <button
                      onClick={() => startEdit(post)}
                      className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200"
                    >
                      編集
                    </button>
                    {post.status === "draft" && (
                      <button
                        onClick={() => updateStatus(post.id, "approved")}
                        className="px-3 py-1.5 bg-green-100 text-green-700 rounded-lg text-xs hover:bg-green-200"
                      >
                        承認
                      </button>
                    )}
                    {post.status === "approved" && (
                      <button
                        onClick={() => updateStatus(post.id, "draft")}
                        className="px-3 py-1.5 bg-gray-100 text-gray-500 rounded-lg text-xs hover:bg-gray-200"
                      >
                        取消
                      </button>
                    )}
                    {(post.status === "draft" || post.status === "approved") && (
                      <button
                        onClick={() => queueNow(post.id)}
                        className="px-3 py-1.5 bg-purple-100 text-purple-700 rounded-lg text-xs hover:bg-purple-200 font-medium"
                      >
                        すぐに投稿
                      </button>
                    )}
                    {post.status !== "posted" && (
                      <button
                        onClick={() => updateStatus(post.id, "posted")}
                        className="px-3 py-1.5 bg-blue-100 text-blue-700 rounded-lg text-xs hover:bg-blue-200"
                      >
                        投稿済にする
                      </button>
                    )}
                    {post.status !== "posted" && (
                      <button
                        onClick={() => deletePost(post.id)}
                        className="px-3 py-1.5 bg-red-50 text-red-500 rounded-lg text-xs hover:bg-red-100"
                      >
                        削除
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {loading && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg">読み込み中...</p>
        </div>
      )}

      {error && (
        <div className="text-center py-16">
          <p className="text-lg text-red-500 mb-2">エラー: {error}</p>
          <p className="text-sm text-gray-400">ログイン状態を確認してください</p>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg mb-2">該当する投稿がありません</p>
          <p className="text-sm">「今すぐ生成」でポストを作成してください</p>
        </div>
      )}
    </div>
  );
}
