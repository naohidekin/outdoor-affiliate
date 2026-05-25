"use client";

import { useCallback, useEffect, useState } from "react";

type PostType = "リプライ" | "引用";

type NotionQueueItem = {
  pageId: string;
  dbId: string;
  dbName: string;
  account: string;
  text: string;
  sourceUrl: string | null;
  postType: PostType;
  author: string;
};

const ACCOUNT_COLORS: Record<string, string> = {
  "ギア男": "bg-green-100 text-green-800",
  "アンブロ": "bg-cyan-100 text-cyan-800",
  "こどもケアラボ": "bg-pink-100 text-pink-800",
};

const POST_TYPE_COLORS: Record<string, string> = {
  "リプライ": "bg-sky-100 text-sky-700",
  "引用": "bg-purple-100 text-purple-700",
};

export default function NotionQueuePage() {
  const [items, setItems] = useState<NotionQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [markingId, setMarkingId] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch("/api/notion-queue")
      .then((r) => r.json())
      .then((data: { items?: NotionQueueItem[]; error?: string }) => {
        if (data.error) throw new Error(data.error);
        setItems(data.items ?? []);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "取得失敗"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  function copyText(pageId: string, text: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopiedId(pageId);
      setTimeout(() => setCopiedId(null), 2000);
    });
  }

  function copyAndOpen(pageId: string, text: string, sourceUrl: string | null) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopiedId(pageId);
      setTimeout(() => setCopiedId(null), 2000);
    });
    if (sourceUrl) window.open(sourceUrl, "_blank", "noopener,noreferrer");
  }

  async function markPosted(pageId: string) {
    setMarkingId(pageId);
    try {
      const res = await fetch("/api/notion-queue", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pageId, action: "mark_posted" }),
      });
      const data = await res.json() as { ok?: boolean; error?: string };
      if (!res.ok || !data.ok) throw new Error(data.error ?? "更新失敗");
      setItems((prev) => prev.filter((i) => i.pageId !== pageId));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "更新失敗");
    } finally {
      setMarkingId(null);
    }
  }

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      {/* ヘッダー */}
      <div className="mb-6 flex items-start justify-between gap-3">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-emerald-400">Notion承認済み</p>
          <h1 className="mt-2 text-3xl font-semibold">投稿キュー</h1>
          <p className="mt-1 text-sm text-gray-400">
            Notionで承認済みのリプライ・引用を手動投稿する
          </p>
        </div>
        <button
          onClick={load}
          className="shrink-0 mt-2 rounded-xl bg-white/10 px-4 min-h-[44px] text-sm font-medium text-gray-200 transition hover:bg-white/20"
        >
          更新
        </button>
      </div>

      {/* 投稿タイプ説明 */}
      <div className="mb-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-gray-400 space-y-1">
        <p><span className="text-sky-400 font-medium">リプライ</span> → コピー＋Xで開く → 元ポストにリプライ</p>
        <p><span className="text-purple-400 font-medium">引用</span> → コピー＋Xで開く → 引用RTとして投稿</p>
        <p className="text-gray-500 text-xs mt-2">投稿後に「投稿済みにする」を押すとNotionのステータスが更新されます</p>
      </div>

      {error && (
        <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="space-y-4">
        {loading ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-sm text-gray-400 text-center">読み込み中...</div>
        ) : items.length === 0 ? (
          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-sm text-gray-400 text-center">承認済みの投稿はありません</div>
        ) : (
          items.map((item) => (
            <article key={item.pageId} className="rounded-3xl border border-white/10 bg-white/5 p-5 space-y-4">
              {/* メタ情報 */}
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${ACCOUNT_COLORS[item.account] ?? "bg-gray-700 text-gray-200"}`}>
                  {item.account}
                </span>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${POST_TYPE_COLORS[item.postType] ?? "bg-gray-700 text-gray-200"}`}>
                  {item.postType}
                </span>
                <span className="text-xs text-gray-500">{item.dbName}</span>
                {item.author && (
                  <span className="text-xs text-gray-500">@{item.author}</span>
                )}
              </div>

              {/* 投稿テキスト */}
              <p className="whitespace-pre-wrap text-[15px] leading-7 text-gray-100">{item.text}</p>

              {/* 元ポスト URL */}
              {item.sourceUrl && (
                <a
                  href={item.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-xs text-gray-500 hover:text-gray-300 truncate transition"
                >
                  元ポスト: {item.sourceUrl}
                </a>
              )}

              {/* アクション */}
              <div className="space-y-2">
                {/* 主アクション: コピー＋Xで開く */}
                <button
                  onClick={() => copyAndOpen(item.pageId, item.text, item.sourceUrl)}
                  className="w-full flex items-center justify-center gap-2 min-h-[52px] bg-sky-500 hover:bg-sky-600 active:bg-sky-700 text-white font-semibold rounded-2xl text-base transition"
                >
                  {copiedId === item.pageId ? "コピー完了 ✓" : "📋 コピー＋Xで開く"}
                </button>

                <div className="flex gap-2">
                  {/* コピーのみ */}
                  <button
                    onClick={() => copyText(item.pageId, item.text)}
                    className="flex-1 min-h-[44px] rounded-xl bg-white/10 text-sm font-medium text-gray-200 transition hover:bg-white/20"
                  >
                    コピーのみ
                  </button>

                  {/* 投稿済みにする */}
                  <button
                    onClick={() => void markPosted(item.pageId)}
                    disabled={markingId === item.pageId}
                    className="flex-1 min-h-[44px] rounded-xl bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 text-white font-semibold text-sm transition disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {markingId === item.pageId ? "更新中..." : "✓ 投稿済みにする"}
                  </button>
                </div>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
