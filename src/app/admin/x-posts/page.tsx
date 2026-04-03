"use client";

import { useState, useEffect } from "react";
import { XPost } from "@/lib/types";

type FilterStatus = "all" | XPost["status"];

export default function AdminXPosts() {
  const [posts, setPosts] = useState<XPost[]>([]);
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [autoApprove, setAutoApprove] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    fetchPosts();
  }, []);

  async function fetchPosts() {
    const res = await fetch("/api/x-posts");
    setPosts(await res.json());
  }

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(""), 3000);
  }

  async function handleGenerate() {
    setGenerating(true);
    try {
      const res = await fetch("/api/x-posts/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ autoApprove }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`${data.generated}件のポストを生成しました`);
        fetchPosts();
      } else {
        showToast(`エラー: ${data.error}`);
      }
    } catch {
      showToast("生成に失敗しました");
    } finally {
      setGenerating(false);
    }
  }

  async function handleStatusChange(id: string, status: XPost["status"]) {
    await fetch("/api/x-posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, status }),
    });
    fetchPosts();
  }

  async function handleDelete(id: string) {
    if (!confirm("このポストを削除しますか？")) return;
    await fetch(`/api/x-posts?id=${id}`, { method: "DELETE" });
    fetchPosts();
  }

  async function handleEditSave(id: string) {
    await fetch("/api/x-posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, text: editText }),
    });
    setEditingId(null);
    fetchPosts();
  }

  function startEdit(post: XPost) {
    setEditingId(post.id);
    setEditText(post.text);
  }

  async function handleCopy(text: string) {
    await navigator.clipboard.writeText(text);
    showToast("クリップボードにコピーしました");
  }

  const filtered =
    filter === "all" ? posts : posts.filter((p) => p.status === filter);

  const statusConfig: Record<
    XPost["status"],
    { label: string; bg: string; text: string }
  > = {
    draft: { label: "下書き", bg: "bg-gray-100", text: "text-gray-700" },
    approved: {
      label: "承認済み",
      bg: "bg-green-100",
      text: "text-green-700",
    },
    queued: { label: "投稿待ち", bg: "bg-blue-100", text: "text-blue-700" },
    posted: { label: "投稿済み", bg: "bg-purple-100", text: "text-purple-700" },
  };

  const typeLabel: Record<XPost["type"], string> = {
    article_promo: "記事紹介",
    outdoor_tip: "Tips",
  };

  const counts = {
    all: posts.length,
    draft: posts.filter((p) => p.status === "draft").length,
    approved: posts.filter((p) => p.status === "approved").length,
    queued: posts.filter((p) => p.status === "queued").length,
    posted: posts.filter((p) => p.status === "posted").length,
  };

  return (
    <div>
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 bg-gray-900 text-white px-4 py-2 rounded-lg shadow-lg z-50 text-sm">
          {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">X投稿管理</h1>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={autoApprove}
              onChange={(e) => setAutoApprove(e.target.checked)}
              className="rounded"
            />
            自動承認
          </label>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="bg-green-600 text-white px-5 py-2 rounded-lg hover:bg-green-700 transition disabled:opacity-50"
          >
            {generating ? "生成中..." : "今すぐ生成"}
          </button>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-6">
        {(
          ["all", "draft", "approved", "queued", "posted"] as FilterStatus[]
        ).map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-4 py-2 rounded-lg text-sm transition ${
              filter === s
                ? "bg-green-600 text-white"
                : "bg-white text-gray-600 hover:bg-gray-100 border"
            }`}
          >
            {s === "all"
              ? "すべて"
              : statusConfig[s as XPost["status"]].label}
            <span className="ml-1 opacity-60">
              ({counts[s as keyof typeof counts]})
            </span>
          </button>
        ))}
      </div>

      {/* Posts list */}
      <div className="space-y-4">
        {filtered.length === 0 ? (
          <div className="bg-white rounded-xl shadow p-8 text-center text-gray-400">
            {filter === "all"
              ? 'ポストがありません。「今すぐ生成」で作成してください。'
              : "該当するポストがありません"}
          </div>
        ) : (
          filtered.map((post) => (
            <div
              key={post.id}
              className="bg-white rounded-xl shadow p-5 flex gap-4"
            >
              {/* Left: status & type */}
              <div className="flex flex-col items-center gap-2 min-w-[80px]">
                <span
                  className={`text-xs px-2 py-1 rounded-full ${statusConfig[post.status].bg} ${statusConfig[post.status].text}`}
                >
                  {statusConfig[post.status].label}
                </span>
                <span className="text-xs text-gray-400">
                  {typeLabel[post.type]}
                </span>
                <span className="text-xs text-gray-400">
                  {post.scheduledDate}
                </span>
              </div>

              {/* Center: content */}
              <div className="flex-1 min-w-0">
                {editingId === post.id ? (
                  <div>
                    <textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={5}
                      className="w-full px-3 py-2 border rounded-lg text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-green-500"
                    />
                    <div className="flex items-center justify-between mt-2">
                      <span
                        className={`text-xs ${editText.length > 280 ? "text-red-500 font-bold" : "text-gray-400"}`}
                      >
                        {editText.length}/280
                      </span>
                      <div className="flex gap-2">
                        <button
                          onClick={() => setEditingId(null)}
                          className="text-sm text-gray-500 hover:text-gray-700"
                        >
                          キャンセル
                        </button>
                        <button
                          onClick={() => handleEditSave(post.id)}
                          className="text-sm bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700"
                        >
                          保存
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm text-gray-800 whitespace-pre-wrap">
                      {post.text}
                    </p>
                    {post.url && (
                      <p className="text-xs text-blue-500 mt-1 truncate">
                        {post.url}
                      </p>
                    )}
                    <p className="text-xs text-gray-400 mt-1">
                      {post.text.length}/280文字
                    </p>
                  </div>
                )}
              </div>

              {/* Right: actions */}
              <div className="flex flex-col gap-1 min-w-[60px]">
                {post.status === "draft" && (
                  <>
                    <button
                      onClick={() => handleStatusChange(post.id, "approved")}
                      className="text-xs text-green-600 hover:text-green-800"
                    >
                      承認
                    </button>
                    <button
                      onClick={() => startEdit(post)}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      編集
                    </button>
                    <button
                      onClick={() => handleDelete(post.id)}
                      className="text-xs text-red-600 hover:text-red-800"
                    >
                      削除
                    </button>
                  </>
                )}
                {post.status === "approved" && (
                  <>
                    <button
                      onClick={() => startEdit(post)}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      編集
                    </button>
                    <button
                      onClick={() => handleStatusChange(post.id, "draft")}
                      className="text-xs text-gray-600 hover:text-gray-800"
                    >
                      取消
                    </button>
                  </>
                )}
                {(post.status === "queued" || post.status === "posted") && (
                  <span className="text-xs text-gray-400">-</span>
                )}
                <button
                  onClick={() => handleCopy(post.text)}
                  className="text-xs text-gray-500 hover:text-gray-700 mt-1"
                >
                  コピー
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
