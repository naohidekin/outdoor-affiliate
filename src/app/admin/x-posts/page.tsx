"use client";

import { useEffect, useState } from "react";

interface XPost {
  id: string;
  text: string;
  type: string;
  articleSlug?: string;
  status: "draft" | "approved" | "posted";
  scheduledDay?: string;
  scheduledTime?: string;
  createdAt: string;
  postedAt?: string;
}

const TYPE_LABELS: Record<string, string> = {
  comparison: "比較・結論",
  question: "問いかけ",
  failure: "失敗談",
  summary: "まとめ",
  cospa: "コスパ",
  family: "家族ネタ",
  "site-link": "サイト誘導",
};

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "下書き", color: "bg-gray-100 text-gray-600" },
  approved: { label: "承認済", color: "bg-green-100 text-green-700" },
  posted: { label: "投稿済", color: "bg-blue-100 text-blue-700" },
};

export default function XPostsPage() {
  const [posts, setPosts] = useState<XPost[]>([]);
  const [copied, setCopied] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  useEffect(() => {
    fetch("/api/x-posts")
      .then((r) => r.json())
      .then(setPosts);
  }, []);

  async function copyToClipboard(post: XPost) {
    await navigator.clipboard.writeText(post.text);
    setCopied(post.id);
    setTimeout(() => setCopied(null), 2000);
  }

  async function updateStatus(id: string, status: XPost["status"]) {
    const res = await fetch("/api/x-posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, status, ...(status === "posted" ? { postedAt: new Date().toISOString() } : {}) }),
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

  const drafts = posts.filter((p) => p.status === "draft");
  const approved = posts.filter((p) => p.status === "approved");
  const posted = posts.filter((p) => p.status === "posted");

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">X 投稿管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            ギア男 @camp_gear_lab のツイート下書き・管理
          </p>
        </div>
        <div className="flex gap-3 text-sm">
          <span className="px-3 py-1 bg-gray-100 rounded-full">下書き {drafts.length}</span>
          <span className="px-3 py-1 bg-green-100 rounded-full">承認済 {approved.length}</span>
          <span className="px-3 py-1 bg-blue-100 rounded-full">投稿済 {posted.length}</span>
        </div>
      </div>

      {/* Posts list */}
      <div className="space-y-4">
        {posts.map((post) => {
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
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusInfo.color}`}>
                      {statusInfo.label}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                      {TYPE_LABELS[post.type] || post.type}
                    </span>
                    {post.scheduledDay && (
                      <span className="text-xs text-gray-400">
                        {post.scheduledDay}曜 {post.scheduledTime}
                      </span>
                    )}
                    {post.articleSlug && (
                      <a
                        href={`/articles/${post.articleSlug}`}
                        target="_blank"
                        className="text-xs text-green-600 hover:underline"
                      >
                        記事リンク付き
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
                        onClick={() => updateStatus(post.id, "posted")}
                        className="px-3 py-1.5 bg-blue-100 text-blue-700 rounded-lg text-xs hover:bg-blue-200"
                      >
                        投稿済
                      </button>
                    )}
                    <button
                      onClick={() => deletePost(post.id)}
                      className="px-3 py-1.5 bg-red-50 text-red-500 rounded-lg text-xs hover:bg-red-100"
                    >
                      削除
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {posts.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg mb-2">まだ投稿がありません</p>
          <p className="text-sm">ツイート案を追加してください</p>
        </div>
      )}
    </div>
  );
}
