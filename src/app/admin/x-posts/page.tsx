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
  const [typeFilter, setTypeFilter] = useState<XPostType | "all">("all");
  const [copied, setCopied] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [editImageUrl, setEditImageUrl] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Phase1-B: 0件表示バグ診断用
  const [debug, setDebug] = useState<{
    fetchedAt: string;
    rawType: string;
    count: number | null;
    sampleId: string | null;
  } | null>(null);

  useEffect(() => {
    const startedAt = new Date().toISOString();
    fetch("/api/x-posts")
      .then(async (r) => {
        const data = await r.json();
        // 診断: 取れたものの shape を必ず記録
        const rawType = Array.isArray(data)
          ? "array"
          : typeof data === "object" && data
            ? "object"
            : typeof data;
        setDebug({
          fetchedAt: startedAt,
          rawType,
          count: Array.isArray(data) ? data.length : null,
          sampleId: Array.isArray(data) && data[0] ? data[0].id : null,
        });
        if (Array.isArray(data)) {
          setPosts(data);
        } else {
          setError(data?.error || `想定外レスポンス (${rawType})`);
        }
      })
      .catch((e) => setError(`APIに接続できません: ${e.message || e}`))
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
      body: JSON.stringify({
        id,
        text: editText,
        imageUrl: editImageUrl || undefined,
      }),
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
    setEditImageUrl(post.imageUrl || "");
  }

  const todayStr = new Date().toISOString().slice(0, 10);

  const filtered = posts.filter((p) => {
    if (filter !== "all" && p.status !== filter) return false;
    if (typeFilter !== "all" && p.type !== typeFilter) return false;
    return true;
  });

  const counts = {
    all: posts.length,
    draft: posts.filter((p) => p.status === "draft").length,
    approved: posts.filter((p) => p.status === "approved").length,
    queued: posts.filter((p) => p.status === "queued").length,
    posted: posts.filter((p) => p.status === "posted").length,
  };

  // Phase1-B: 失敗検知 — 予定日を過ぎたのに posted/queued になっていない投稿
  const overdue = posts.filter(
    (p) =>
      p.scheduledDate &&
      p.scheduledDate < todayStr &&
      p.status !== "posted"
  );

  const typeCounts = posts.reduce<Record<string, number>>((acc, p) => {
    acc[p.type] = (acc[p.type] || 0) + 1;
    return acc;
  }, {});

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

      {/* 失敗検知バナー */}
      {overdue.length > 0 && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
          ⚠ 予定日を過ぎても投稿されていない投稿が {overdue.length} 件あります。
          IFTTTの動作 / queue状態 / Sheets「X投稿管理」シートを確認してください。
        </div>
      )}

      {/* 0件診断パネル */}
      {!loading && posts.length === 0 && debug && (
        <div className="mb-4 p-3 rounded-lg bg-yellow-50 border border-yellow-200 text-xs text-yellow-800 font-mono">
          診断: API応答 type={debug.rawType} / count={debug.count ?? "n/a"} /
          fetchedAt={debug.fetchedAt}
          <br />
          ⇒ Sheets「下書き管理」が空、もしくは認証/権限エラーの可能性。
          <br />
          確認: GOOGLE_CREDENTIALS / X_SHEET_ID / シート名「下書き管理」存在 /
          サービスアカウントの編集者権限
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex gap-2 mb-3">
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

      {/* Type filter tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        <button
          onClick={() => setTypeFilter("all")}
          className={`px-3 py-1 rounded-full text-xs ${
            typeFilter === "all"
              ? "bg-sky-600 text-white"
              : "bg-gray-50 text-gray-500 hover:bg-gray-100"
          }`}
        >
          全タイプ ({posts.length})
        </button>
        {(Object.keys(TYPE_LABELS) as XPostType[]).map((t) => {
          const c = typeCounts[t] || 0;
          if (c === 0 && typeFilter !== t) return null;
          return (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-3 py-1 rounded-full text-xs ${
                typeFilter === t
                  ? "bg-sky-600 text-white"
                  : "bg-gray-50 text-gray-500 hover:bg-gray-100"
              }`}
            >
              {TYPE_LABELS[t]} ({c})
            </button>
          );
        })}
      </div>

      {/* Posts list */}
      <div className="space-y-4">
        {filtered.map((post) => {
          const statusInfo = STATUS_LABELS[post.status];
          const isEditing = editing === post.id;
          const isOverdue =
            post.scheduledDate &&
            post.scheduledDate < todayStr &&
            post.status !== "posted";

          return (
            <div
              key={post.id}
              className={`rounded-xl border p-5 transition ${
                isOverdue
                  ? "bg-red-50/30 border-red-200"
                  : "bg-white border-gray-200 hover:border-gray-300"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  {/* Header */}
                  <div className="flex items-center gap-2 mb-3 flex-wrap">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusInfo.color}`}
                    >
                      {statusInfo.label}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-sky-50 text-sky-700">
                      {TYPE_LABELS[post.type] || post.type}
                    </span>
                    <span className="text-xs text-gray-400">
                      {post.scheduledDate}
                      {post.scheduledTime ? ` ${post.scheduledTime}` : ""}
                    </span>
                    {isOverdue && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
                        ⚠ 予定超過
                      </span>
                    )}
                    {post.prLabel && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-orange-50 text-orange-700">
                        PR
                      </span>
                    )}
                    {post.url && (
                      <a
                        href={post.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-green-600 hover:underline"
                      >
                        記事リンク
                      </a>
                    )}
                  </div>

                  {/* validationErrors バナー */}
                  {post.validationErrors && (
                    <div className="mb-2 px-2 py-1 rounded bg-yellow-50 border border-yellow-200 text-xs text-yellow-800">
                      ⚠ {post.validationErrors}
                    </div>
                  )}

                  {/* Content */}
                  {isEditing ? (
                    <div>
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="w-full border border-gray-300 rounded-lg p-3 text-sm leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-sky-500"
                        rows={6}
                      />
                      <input
                        type="url"
                        value={editImageUrl}
                        onChange={(e) => setEditImageUrl(e.target.value)}
                        placeholder="画像URL (任意): https://..."
                        className="mt-2 w-full border border-gray-300 rounded-lg p-2 text-xs focus:outline-none focus:ring-2 focus:ring-sky-500"
                      />
                      <div className="flex gap-2 mt-2 items-center">
                        <button
                          onClick={() => saveEdit(post.id)}
                          className="px-3 py-1.5 bg-sky-600 text-white rounded-lg text-sm hover:bg-sky-700"
                        >
                          保存
                        </button>
                        <button
                          onClick={() => setEditing(null)}
                          className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-sm hover:bg-gray-200"
                        >
                          キャンセル
                        </button>
                        <span
                          className={`text-xs self-center ml-2 ${
                            [...editText].length > 280
                              ? "text-red-500 font-medium"
                              : "text-gray-400"
                          }`}
                        >
                          {[...editText].length}/280文字
                        </span>
                      </div>
                    </div>
                  ) : (
                    <>
                      {/* X風プレビューカード */}
                      <div className="border border-gray-100 rounded-lg p-3 bg-white">
                        <div className="flex items-center gap-2 mb-1">
                          <div className="w-7 h-7 rounded-full bg-sky-100 text-sky-700 flex items-center justify-center text-xs font-bold">
                            G
                          </div>
                          <span className="text-sm font-semibold text-gray-800">
                            ギア男
                          </span>
                          <span className="text-xs text-gray-400">
                            @camp_gear_lab
                          </span>
                        </div>
                        <p className="text-sm text-gray-800 whitespace-pre-line leading-relaxed">
                          {post.text}
                        </p>
                        {post.imageUrl && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={post.imageUrl}
                            alt=""
                            className="mt-2 rounded-lg max-h-60 object-cover"
                          />
                        )}
                      </div>
                      <div className="text-xs text-gray-400 mt-1">
                        {[...post.text].length}/280文字
                      </div>
                    </>
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
