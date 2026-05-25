"use client";

import { useEffect, useState } from "react";

interface ViralPost {
  tweetId: string;
  authorUsername: string;
  authorName: string;
  authorFollowers: number;
  axis: string;
  text: string;
  createdAt: string;
  metrics: {
    likes: number;
    retweets: number;
    replies: number;
    quotes: number;
    bookmarks: number;
    engagementScore: number;
  };
  analysis: {
    hook: string;
    emotionalTrigger: string;
    format: string;
    topic: string;
    timing: string;
    shareability: string;
    keyTechniques: string[];
    adaptability: string;
  } | null;
  generatedContent: {
    quoteTweet: { text: string; axis: string; rationale: string; status: string; postedAt?: string; validationErrors?: string };
    reply: { text: string; axis: string; rationale: string; status: string; postedAt?: string; validationErrors?: string };
  } | null;
}

interface AggregateAnalysis {
  totalAnalyzed: number;
  topHooks: { pattern: string; count: number; pct: number }[];
  topEmotionalTriggers: { pattern: string; count: number; pct: number }[];
  topFormats: { pattern: string; count: number; pct: number }[];
  highAdaptability: number;
}

const AXIS_LABELS: Record<string, string> = {
  ai: "AI",
  camp: "Camp",
  parenting: "子育て",
  doctor: "医師",
};

const AXIS_COLORS: Record<string, string> = {
  ai: "bg-purple-100 text-purple-800",
  camp: "bg-green-100 text-green-800",
  parenting: "bg-pink-100 text-pink-800",
  doctor: "bg-blue-100 text-blue-800",
};

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-yellow-100 text-yellow-800",
  approved: "bg-blue-100 text-blue-800",
  posted: "bg-green-100 text-green-800",
  needs_review: "bg-red-100 text-red-800",
  skipped: "bg-gray-100 text-gray-500",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "未対応",
  approved: "承認済み",
  posted: "✓ 投稿済み",
  needs_review: "要レビュー",
  skipped: "スキップ",
};

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}分前`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}時間前`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 7) return `${diffD}日前`;
  return new Date(dateStr).toLocaleDateString("ja-JP", { month: "short", day: "numeric" });
}

interface GeneratedItemType {
  text: string;
  axis: string;
  rationale: string;
  status: string;
  postedAt?: string;
  validationErrors?: string;
}

function GeneratedItem({
  label,
  item,
  copyKey,
  copiedId,
  tweetUrl,
  onCopy,
  onSetStatus,
}: {
  label: string;
  item: GeneratedItemType;
  copyKey: string;
  copiedId: string | null;
  tweetUrl: string;
  onCopy: (text: string, id: string) => void;
  onSetStatus: (status: string) => void;
}) {
  const isPosted = item.status === "posted";
  const isSkipped = item.status === "skipped";
  const muted = isPosted || isSkipped;
  const isCopied = copiedId === copyKey;

  function handleCopyAndOpen() {
    onCopy(item.text, copyKey);
    // モバイルでは X アプリが開く。PCでは新タブ
    window.open(tweetUrl, "_blank", "noopener,noreferrer");
  }

  return (
    <div className={`p-4 transition-opacity ${muted ? "opacity-60" : ""}`}>
      {/* ラベル + ステータス */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</span>
        <div className="flex items-center gap-2">
          {item.postedAt && (
            <span className="text-[10px] text-gray-400">
              {timeAgo(item.postedAt)}
            </span>
          )}
          <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[item.status] || ""}`}>
            {STATUS_LABELS[item.status] || item.status}
          </span>
        </div>
      </div>

      {/* 生成テキスト */}
      <p className={`text-[15px] leading-relaxed whitespace-pre-wrap mb-4 ${isPosted ? "line-through decoration-gray-300 text-gray-400" : "text-gray-900"}`}>
        {item.text}
      </p>

      {item.validationErrors && (
        <p className="text-xs text-red-500 mb-3">{item.validationErrors}</p>
      )}

      {/* アクションボタン */}
      {!isPosted ? (
        <div className="space-y-2">
          {/* 主アクション: コピー＋Xを開く（スマホ最重要） */}
          <button
            onClick={handleCopyAndOpen}
            className="w-full flex items-center justify-center gap-2 min-h-[52px] bg-sky-500 hover:bg-sky-600 active:bg-sky-700 text-white font-semibold rounded-xl text-base transition"
          >
            {isCopied ? "コピー完了 ✓" : "📋 コピー＋Xで開く"}
          </button>

          <div className="flex gap-2">
            {/* コピーのみ */}
            <button
              onClick={() => onCopy(item.text, copyKey)}
              className="flex-1 min-h-[44px] border border-gray-300 text-gray-600 font-medium rounded-xl text-sm hover:bg-gray-50 active:bg-gray-100 transition"
            >
              {isCopied ? "コピー済み ✓" : "コピーのみ"}
            </button>

            {/* スキップ / 未対応に戻す */}
            {!isSkipped ? (
              <button
                onClick={() => onSetStatus("skipped")}
                className="flex-1 min-h-[44px] border border-gray-300 text-gray-400 font-medium rounded-xl text-sm hover:bg-gray-50 active:bg-gray-100 transition"
              >
                スキップ
              </button>
            ) : (
              <button
                onClick={() => onSetStatus("draft")}
                className="flex-1 min-h-[44px] border border-gray-300 text-gray-500 font-medium rounded-xl text-sm hover:bg-gray-50 active:bg-gray-100 transition"
              >
                未対応に戻す
              </button>
            )}
          </div>

          {/* 投稿済みにする（Xで投稿後に押す） */}
          <button
            onClick={() => onSetStatus("posted")}
            className="w-full min-h-[48px] bg-green-600 hover:bg-green-700 active:bg-green-800 text-white font-semibold rounded-xl text-base transition"
          >
            ✓ 投稿済みにする
          </button>
        </div>
      ) : (
        <button
          onClick={() => onSetStatus("draft")}
          className="w-full min-h-[44px] border border-gray-300 text-gray-500 font-medium rounded-xl text-sm hover:bg-gray-50 transition"
        >
          未対応に戻す
        </button>
      )}
    </div>
  );
}

export default function ViralScoutPage() {
  const [posts, setPosts] = useState<ViralPost[]>([]);
  const [aggregate, setAggregate] = useState<AggregateAnalysis | null>(null);
  const [scoutedAt, setScoutedAt] = useState("");
  const [filterAxis, setFilterAxis] = useState("all");
  const [filterStatus, setFilterStatus] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [scouting, setScouting] = useState(false);
  const [scoutLog, setScoutLog] = useState("");
  const [scoutError, setScoutError] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  // スマホ向け: 分析データは折りたたみ
  const [showAnalytics, setShowAnalytics] = useState(false);

  function loadData() {
    fetch("/api/viral-scout", { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => {
        setPosts(data.viralPosts || []);
        setAggregate(data.aggregateAnalysis || null);
        setScoutedAt(data.scoutedAt || "");
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }

  useEffect(() => { loadData(); }, []);

  async function runScout() {
    if (scouting) return;
    setScouting(true);
    setScoutError(false);
    setScoutLog("スカウト実行中... (数分かかります)");
    try {
      const res = await fetch("/api/viral-scout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: 1, minScore: 20 }),
      });
      const data = await res.json();
      if (!data.ok) {
        setScoutError(true);
        setScoutLog(data.error || "不明なエラー");
        setScouting(false);
        return;
      }
      if (data.data?.viralPosts) {
        setPosts(data.data.viralPosts || []);
        setAggregate(data.data.aggregateAnalysis || null);
        setScoutedAt(data.data.scoutedAt || "");
      } else {
        loadData();
      }
      setScoutLog("完了!");
      setScouting(false);
      setTimeout(() => setScoutLog(""), 3000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setScoutError(true);
      setScoutLog(msg);
      setScouting(false);
    }
  }

  async function updateStatus(tweetId: string, field: "quoteTweet" | "reply", status: string) {
    const res = await fetch("/api/viral-scout", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tweetId, field, status }),
    });
    const body = (await res.json().catch(() => ({}))) as { postedAt?: string | null };
    const postedAt = body.postedAt || undefined;
    setPosts((prev) =>
      prev.map((p) => {
        if (p.tweetId !== tweetId || !p.generatedContent) return p;
        const updated = { ...p.generatedContent[field], status, postedAt };
        if (!postedAt) delete updated.postedAt;
        return {
          ...p,
          generatedContent: {
            ...p.generatedContent,
            [field]: updated,
          },
        };
      })
    );
  }

  function copyText(text: string, id: string) {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  function toggleSelect(tweetId: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(tweetId)) next.delete(tweetId);
      else next.add(tweetId);
      return next;
    });
  }

  function selectAllVisible(visibleIds: string[]) {
    setSelectedIds((prev) => {
      const allSelected = visibleIds.every((id) => prev.has(id));
      if (allSelected) {
        const next = new Set(prev);
        for (const id of visibleIds) next.delete(id);
        return next;
      }
      const next = new Set(prev);
      for (const id of visibleIds) next.add(id);
      return next;
    });
  }

  async function bulkDelete() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!confirm(`${ids.length}件を削除します。元に戻せません。よろしいですか？`)) return;
    setBulkBusy(true);
    try {
      const res = await fetch("/api/viral-scout", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tweetIds: ids }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setPosts((prev) => prev.filter((p) => !selectedIds.has(p.tweetId)));
        setSelectedIds(new Set());
      } else {
        alert(`削除失敗: ${data.error || res.statusText}`);
      }
    } catch (err) {
      alert(`削除エラー: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBulkBusy(false);
    }
  }

  function matchStatusFilter(qs: string | undefined, rs: string | undefined): boolean {
    if (filterStatus === "all") return true;
    if (filterStatus === "pending") {
      return qs === "draft" || qs === "approved" || rs === "draft" || rs === "approved";
    }
    return qs === filterStatus || rs === filterStatus;
  }

  const filtered = posts.filter((p) => {
    if (filterAxis !== "all" && p.axis !== filterAxis) return false;
    return matchStatusFilter(
      p.generatedContent?.quoteTweet?.status,
      p.generatedContent?.reply?.status
    );
  });

  if (loading) {
    return <div className="p-6 text-gray-500 text-center">読み込み中...</div>;
  }

  if (posts.length === 0) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">Viral Scout</h1>
        <p className="text-gray-500">
          データがありません。<code>npm run x:viral-scout</code> を実行してください。
        </p>
      </div>
    );
  }

  // ステータス集計
  const axisCounts: Record<string, number> = {};
  const statusCounts: Record<string, number> = {
    draft: 0, approved: 0, posted: 0, needs_review: 0, skipped: 0,
  };
  for (const p of posts) {
    axisCounts[p.axis] = (axisCounts[p.axis] || 0) + 1;
    const qs = p.generatedContent?.quoteTweet?.status || "draft";
    const rs = p.generatedContent?.reply?.status || "draft";
    if (qs in statusCounts) statusCounts[qs]++;
    if (rs in statusCounts) statusCounts[rs]++;
  }
  const pendingCount = statusCounts.draft + statusCounts.approved;

  return (
    <div className="max-w-2xl mx-auto">

      {/* ─── ヘッダー ─── */}
      <div className="flex items-center justify-between mb-4 gap-3">
        <div>
          <h1 className="text-xl font-bold">Viral Scout</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {scoutedAt && `${new Date(scoutedAt).toLocaleString("ja-JP")} 実行`} · {posts.length}件
          </p>
        </div>
        <button
          onClick={runScout}
          disabled={scouting}
          className={`shrink-0 min-h-[44px] px-4 rounded-xl text-sm font-medium text-white transition ${
            scouting ? "bg-gray-400 cursor-not-allowed" : "bg-blue-600 hover:bg-blue-700 active:bg-blue-800"
          }`}
        >
          {scouting ? "実行中..." : "再スカウト"}
        </button>
      </div>

      {scoutLog && (
        <div className={`mb-4 px-4 py-3 rounded-xl text-sm ${
          scoutError ? "bg-red-50 text-red-700" :
          scouting ? "bg-blue-50 text-blue-700" : "bg-green-50 text-green-700"
        }`}>
          {scoutLog}
        </div>
      )}

      {/* ─── 進捗サマリー（スマホ向け: 2列） ─── */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-3 text-center">
          <p className="text-xs text-yellow-700 font-medium">未対応</p>
          <p className="text-3xl font-bold text-yellow-600 mt-1">{pendingCount}</p>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-xl p-3 text-center">
          <p className="text-xs text-green-700 font-medium">投稿済み</p>
          <p className="text-3xl font-bold text-green-600 mt-1">{statusCounts.posted}</p>
        </div>
      </div>

      {/* ─── 分析データ（折りたたみ、スマホでは隠す） ─── */}
      {aggregate && (
        <div className="mb-4">
          <button
            onClick={() => setShowAnalytics((v) => !v)}
            className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
          >
            分析データ {showAnalytics ? "▲" : "▼"}
          </button>
          {showAnalytics && (
            <div className="mt-2 grid grid-cols-2 gap-2">
              <div className="bg-white rounded-lg p-3 shadow-sm border text-center">
                <p className="text-xs text-gray-500">適応性「高」</p>
                <p className="text-lg font-bold text-green-600">{aggregate.highAdaptability}</p>
              </div>
              <div className="bg-white rounded-lg p-3 shadow-sm border text-center">
                <p className="text-xs text-gray-500">トップフック</p>
                <p className="text-sm font-medium">{aggregate.topHooks?.[0]?.pattern || "-"}</p>
              </div>
              <div className="bg-white rounded-lg p-3 shadow-sm border text-center">
                <p className="text-xs text-gray-500">トップ感情</p>
                <p className="text-sm font-medium">{aggregate.topEmotionalTriggers?.[0]?.pattern || "-"}</p>
              </div>
              <div className="bg-white rounded-lg p-3 shadow-sm border text-center">
                <p className="text-xs text-gray-500">トップ形式</p>
                <p className="text-sm font-medium">{aggregate.topFormats?.[0]?.pattern || "-"}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ─── フィルター（スマホ: 縦並び） ─── */}
      <div className="flex flex-col sm:flex-row gap-2 mb-4">
        <select
          value={filterAxis}
          onChange={(e) => setFilterAxis(e.target.value)}
          className="w-full sm:w-auto border rounded-xl px-3 py-3 text-sm bg-white"
        >
          <option value="all">全軸</option>
          {Object.entries(axisCounts).map(([axis, count]) => (
            <option key={axis} value={axis}>
              {AXIS_LABELS[axis] || axis} ({count}件)
            </option>
          ))}
        </select>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="w-full sm:w-auto border rounded-xl px-3 py-3 text-sm bg-white"
        >
          <option value="pending">未対応のみ ({pendingCount})</option>
          <option value="posted">投稿済み ({statusCounts.posted})</option>
          <option value="skipped">スキップ ({statusCounts.skipped})</option>
          <option value="needs_review">要レビュー ({statusCounts.needs_review})</option>
          <option value="all">全て</option>
        </select>
        <div className="flex items-center justify-between sm:ml-auto gap-2">
          <span className="text-sm text-gray-500">{filtered.length}件</span>
          <button
            onClick={() => selectAllVisible(filtered.map((p) => p.tweetId))}
            className="text-sm px-3 py-2 border rounded-xl hover:bg-gray-50"
          >
            {filtered.length > 0 && filtered.every((p) => selectedIds.has(p.tweetId))
              ? "選択解除"
              : "全選択"}
          </button>
        </div>
      </div>

      {/* ─── 一括削除バー ─── */}
      {selectedIds.size > 0 && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-xl flex items-center justify-between gap-3">
          <span className="text-sm text-blue-900 font-medium">{selectedIds.size}件選択中</span>
          <div className="flex gap-2">
            <button
              onClick={() => setSelectedIds(new Set())}
              className="text-sm px-3 py-2 text-gray-600 hover:bg-white rounded-lg"
            >
              解除
            </button>
            <button
              onClick={bulkDelete}
              disabled={bulkBusy}
              className={`text-sm px-4 py-2 font-medium rounded-lg text-white ${
                bulkBusy ? "bg-gray-400 cursor-not-allowed" : "bg-red-600 hover:bg-red-700"
              }`}
            >
              {bulkBusy ? "削除中..." : `🗑 削除 (${selectedIds.size})`}
            </button>
          </div>
        </div>
      )}

      {/* ─── 投稿カード ─── */}
      <div className="space-y-4">
        {filtered.map((post) => {
          const tweetUrl = `https://x.com/${post.authorUsername}/status/${post.tweetId}`;
          return (
            <div
              key={post.tweetId}
              className={`bg-white rounded-2xl shadow-sm border overflow-hidden ${
                selectedIds.has(post.tweetId) ? "ring-2 ring-blue-400" : ""
              }`}
            >
              {/* カードヘッダー */}
              <div className="px-4 py-3 border-b bg-gray-50">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(post.tweetId)}
                      onChange={() => toggleSelect(post.tweetId)}
                      className="w-5 h-5 shrink-0 cursor-pointer"
                      aria-label="この投稿を選択"
                    />
                    <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${AXIS_COLORS[post.axis] || ""}`}>
                      {AXIS_LABELS[post.axis] || post.axis}
                    </span>
                    <a
                      href={tweetUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-sm text-blue-600 hover:underline truncate"
                    >
                      @{post.authorUsername}
                    </a>
                  </div>
                  <a
                    href={tweetUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 text-xs text-blue-500 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-lg font-medium transition"
                  >
                    元ポスト →
                  </a>
                </div>
                {/* メトリクス（スマホでも1行で収まるよう簡略化） */}
                <div className="flex gap-3 mt-1.5 text-xs text-gray-400">
                  <span>{post.authorFollowers.toLocaleString()} F</span>
                  <span>score {post.metrics.engagementScore}</span>
                  <span>♥{post.metrics.likes}</span>
                  <span>RT{post.metrics.retweets}</span>
                  {post.createdAt && <span>{timeAgo(post.createdAt)}</span>}
                </div>
              </div>

              {/* 元ツイート本文 */}
              <div className="px-4 py-3 border-b bg-gray-50/50">
                <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-wrap line-clamp-4">
                  {post.text}
                </p>
                {post.analysis && post.analysis.adaptability === "high" && (
                  <span className="inline-block mt-2 text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                    適応性:高
                  </span>
                )}
              </div>

              {/* 生成コンテンツ（縦並び） */}
              {post.generatedContent ? (
                <div className="divide-y">
                  <GeneratedItem
                    label="リプライ"
                    item={post.generatedContent.reply}
                    copyKey={`rp-${post.tweetId}`}
                    copiedId={copiedId}
                    tweetUrl={tweetUrl}
                    onCopy={(text, id) => copyText(text, id)}
                    onSetStatus={(status) => updateStatus(post.tweetId, "reply", status)}
                  />
                  <GeneratedItem
                    label="引用投稿"
                    item={post.generatedContent.quoteTweet}
                    copyKey={`qt-${post.tweetId}`}
                    copiedId={copiedId}
                    tweetUrl={tweetUrl}
                    onCopy={(text, id) => copyText(text, id)}
                    onSetStatus={(status) => updateStatus(post.tweetId, "quoteTweet", status)}
                  />
                </div>
              ) : (
                <div className="px-4 py-4 text-sm text-gray-400">
                  生成コンテンツなし
                </div>
              )}
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div className="text-center py-12 text-gray-400">
            <p className="text-lg">✓ 対応済み</p>
            <p className="text-sm mt-1">未対応のリプライはありません</p>
          </div>
        )}
      </div>
    </div>
  );
}
