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
  onCopy,
  onSetStatus,
}: {
  label: string;
  item: GeneratedItemType;
  copyKey: string;
  copiedId: string | null;
  onCopy: (text: string, id: string) => void;
  onSetStatus: (status: string) => void;
}) {
  const isPosted = item.status === "posted";
  const isSkipped = item.status === "skipped";
  const muted = isPosted || isSkipped;
  return (
    <div className={`px-4 py-3 transition-opacity ${muted ? "opacity-60" : ""}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-gray-500">{label}</span>
        <div className="flex items-center gap-2">
          {item.postedAt && (
            <span className="text-[10px] text-gray-400" title={new Date(item.postedAt).toLocaleString("ja-JP")}>
              {timeAgo(item.postedAt)}
            </span>
          )}
          <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[item.status] || ""}`}>
            {STATUS_LABELS[item.status] || item.status}
          </span>
        </div>
      </div>
      <p className={`text-sm whitespace-pre-wrap mb-2 ${isPosted ? "line-through decoration-gray-300" : ""}`}>
        {item.text}
      </p>
      {item.validationErrors && (
        <p className="text-xs text-red-500 mb-2">{item.validationErrors}</p>
      )}
      <div className="flex gap-1 flex-wrap items-center">
        <button
          onClick={() => onCopy(item.text, copyKey)}
          className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200"
        >
          {copiedId === copyKey ? "コピー完了" : "📋 コピー"}
        </button>
        {!isPosted ? (
          <>
            <button
              onClick={() => onSetStatus("posted")}
              className="text-xs px-3 py-1 bg-green-600 text-white font-medium rounded hover:bg-green-700"
              title="Xで投稿した後、このボタンで完了マーク"
            >
              ✓ 投稿済みにする
            </button>
            {!isSkipped && (
              <button
                onClick={() => onSetStatus("skipped")}
                className="text-xs px-2 py-1 text-gray-500 rounded hover:bg-gray-100"
              >
                スキップ
              </button>
            )}
            {isSkipped && (
              <button
                onClick={() => onSetStatus("draft")}
                className="text-xs px-2 py-1 text-gray-500 underline hover:text-gray-700"
              >
                未対応に戻す
              </button>
            )}
          </>
        ) : (
          <button
            onClick={() => onSetStatus("draft")}
            className="text-xs px-2 py-1 text-gray-500 underline hover:text-gray-700"
          >
            元に戻す
          </button>
        )}
      </div>
    </div>
  );
}

export default function ViralScoutPage() {
  const [posts, setPosts] = useState<ViralPost[]>([]);
  const [aggregate, setAggregate] = useState<AggregateAnalysis | null>(null);
  const [scoutedAt, setScoutedAt] = useState("");
  const [filterAxis, setFilterAxis] = useState("all");
  // デフォルトは「未対応のみ」— 投稿済み・スキップを隠してキューを綺麗に保つ
  const [filterStatus, setFilterStatus] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [scouting, setScouting] = useState(false);
  const [scoutLog, setScoutLog] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  function loadData() {
    fetch("/api/viral-scout")
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
    setScoutLog("スカウト実行中... (数分かかります)");
    try {
      const res = await fetch("/api/viral-scout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: 2, minScore: 20 }),
      });
      const data = await res.json();
      setScoutLog(data.ok ? "完了! データを再読込中..." : `エラー: ${data.output?.slice(-200) || "不明"}`);
      if (data.ok) {
        loadData();
        setTimeout(() => setScoutLog(""), 3000);
      }
    } catch (err) {
      setScoutLog("通信エラー");
    } finally {
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
    setTimeout(() => setCopiedId(null), 1500);
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
        // 全て選択済なら解除
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
      // 未対応 = draft or approved（どちらかが該当すればカード表示）
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
    return <div className="p-8 text-gray-500">読み込み中...</div>;
  }

  if (posts.length === 0) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-bold mb-4">Viral Scout</h1>
        <p className="text-gray-500">
          データがありません。<code>npm run x:viral-scout</code> を実行してください。
        </p>
      </div>
    );
  }

  // Stats — quote+reply両方を個別に数える（各カードで2件の生成コンテンツがある）
  const axisCounts: Record<string, number> = {};
  const statusCounts: Record<string, number> = {
    draft: 0,
    approved: 0,
    posted: 0,
    needs_review: 0,
    skipped: 0,
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
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Viral Scout</h1>
          <p className="text-sm text-gray-500 mt-1">
            {scoutedAt && `最終実行: ${new Date(scoutedAt).toLocaleString("ja-JP")}`} / {posts.length}件
          </p>
        </div>
        <button
          onClick={runScout}
          disabled={scouting}
          className={`px-4 py-2 rounded-lg text-sm font-medium text-white transition ${
            scouting ? "bg-gray-400 cursor-not-allowed" : "bg-blue-600 hover:bg-blue-700"
          }`}
        >
          {scouting ? "スカウト中..." : "再スカウト (直近2日)"}
        </button>
      </div>
      {scoutLog && (
        <div className={`mb-4 px-4 py-2 rounded-lg text-sm ${scouting ? "bg-blue-50 text-blue-700" : "bg-green-50 text-green-700"}`}>
          {scoutLog}
        </div>
      )}

      {/* Progress Stats — 作業状況の見える化 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <div className="bg-white rounded-lg p-4 shadow-sm border">
          <p className="text-xs text-gray-500">未対応</p>
          <p className="text-2xl font-bold text-yellow-600">{pendingCount}</p>
          <p className="text-[10px] text-gray-400 mt-1">これから投稿する分</p>
        </div>
        <div className="bg-white rounded-lg p-4 shadow-sm border">
          <p className="text-xs text-gray-500">投稿済み</p>
          <p className="text-2xl font-bold text-green-600">{statusCounts.posted}</p>
          <p className="text-[10px] text-gray-400 mt-1">手動投稿完了分</p>
        </div>
        <div className="bg-white rounded-lg p-4 shadow-sm border">
          <p className="text-xs text-gray-500">スキップ</p>
          <p className="text-2xl font-bold text-gray-400">{statusCounts.skipped}</p>
        </div>
        <div className="bg-white rounded-lg p-4 shadow-sm border">
          <p className="text-xs text-gray-500">収集全体</p>
          <p className="text-2xl font-bold">{posts.length}</p>
          <p className="text-[10px] text-gray-400 mt-1">投稿 × 2（引用+リプ）</p>
        </div>
      </div>

      {aggregate && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          <div className="bg-white rounded-lg p-3 shadow-sm border">
            <p className="text-xs text-gray-500">適応性「高」</p>
            <p className="text-lg font-bold text-green-600">{aggregate.highAdaptability}</p>
          </div>
          <div className="bg-white rounded-lg p-3 shadow-sm border">
            <p className="text-xs text-gray-500">トップフック</p>
            <p className="text-sm font-medium">{aggregate.topHooks?.[0]?.pattern || "-"}</p>
          </div>
          <div className="bg-white rounded-lg p-3 shadow-sm border">
            <p className="text-xs text-gray-500">トップ感情</p>
            <p className="text-sm font-medium">{aggregate.topEmotionalTriggers?.[0]?.pattern || "-"}</p>
          </div>
          <div className="bg-white rounded-lg p-3 shadow-sm border">
            <p className="text-xs text-gray-500">トップ形式</p>
            <p className="text-sm font-medium">{aggregate.topFormats?.[0]?.pattern || "-"}</p>
          </div>
        </div>
      )}

      {/* Axis breakdown */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {Object.entries(axisCounts).map(([axis, count]) => (
          <span key={axis} className={`text-xs px-2 py-1 rounded-full ${AXIS_COLORS[axis] || "bg-gray-100"}`}>
            {AXIS_LABELS[axis] || axis}: {count}件
          </span>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-6">
        <select
          value={filterAxis}
          onChange={(e) => setFilterAxis(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm"
        >
          <option value="all">全軸</option>
          <option value="ai">AI</option>
          <option value="camp">Camp</option>
          <option value="parenting">子育て</option>
          <option value="doctor">医師</option>
        </select>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm"
        >
          <option value="pending">未対応のみ ({pendingCount})</option>
          <option value="posted">投稿済み ({statusCounts.posted})</option>
          <option value="skipped">スキップ ({statusCounts.skipped})</option>
          <option value="draft">Draft ({statusCounts.draft})</option>
          <option value="approved">承認済み ({statusCounts.approved})</option>
          <option value="needs_review">要レビュー ({statusCounts.needs_review})</option>
          <option value="all">全て ({posts.length * 2}件)</option>
        </select>
        <span className="text-sm text-gray-500 self-center">{filtered.length}件表示</span>
        <button
          onClick={() => selectAllVisible(filtered.map((p) => p.tweetId))}
          className="ml-auto text-sm px-3 py-2 border rounded-lg hover:bg-gray-50"
        >
          {filtered.length > 0 && filtered.every((p) => selectedIds.has(p.tweetId))
            ? "表示中の選択を解除"
            : "表示中を全選択"}
        </button>
      </div>

      {/* 一括操作バー（1件以上選択時のみ表示） */}
      {selectedIds.size > 0 && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-center justify-between">
          <span className="text-sm text-blue-900 font-medium">
            {selectedIds.size}件選択中
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setSelectedIds(new Set())}
              className="text-sm px-3 py-1.5 text-gray-600 hover:bg-white rounded"
            >
              選択解除
            </button>
            <button
              onClick={bulkDelete}
              disabled={bulkBusy}
              className={`text-sm px-4 py-1.5 font-medium rounded text-white ${
                bulkBusy ? "bg-gray-400 cursor-not-allowed" : "bg-red-600 hover:bg-red-700"
              }`}
            >
              {bulkBusy ? "削除中..." : `🗑 一括削除 (${selectedIds.size})`}
            </button>
          </div>
        </div>
      )}

      {/* Post Cards */}
      <div className="space-y-4">
        {filtered.map((post) => (
          <div
            key={post.tweetId}
            className={`bg-white rounded-lg shadow-sm border overflow-hidden ${
              selectedIds.has(post.tweetId) ? "ring-2 ring-blue-400" : ""
            }`}
          >
            {/* Header */}
            <div className="px-4 py-3 border-b bg-gray-50 flex items-center justify-between">
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  type="checkbox"
                  checked={selectedIds.has(post.tweetId)}
                  onChange={() => toggleSelect(post.tweetId)}
                  className="w-4 h-4 mr-1 cursor-pointer"
                  aria-label="この投稿を選択"
                />
                <span className={`text-xs px-2 py-0.5 rounded-full ${AXIS_COLORS[post.axis] || ""}`}>
                  {AXIS_LABELS[post.axis] || post.axis}
                </span>
                <a
                  href={`https://x.com/${post.authorUsername}/status/${post.tweetId}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-sm text-blue-600 hover:underline"
                >
                  @{post.authorUsername}
                </a>
                <span className="text-xs text-gray-400">
                  {post.authorFollowers.toLocaleString()} followers
                </span>
                <span className="text-xs text-gray-400">
                  {post.createdAt ? timeAgo(post.createdAt) : ""}
                </span>
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span>score: {post.metrics.engagementScore}</span>
                <span>♥ {post.metrics.likes}</span>
                <span>RT {post.metrics.retweets}</span>
                <a
                  href={`https://x.com/${post.authorUsername}/status/${post.tweetId}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-500 hover:underline"
                >
                  元ポスト →
                </a>
              </div>
            </div>

            {/* Original tweet */}
            <div className="px-4 py-3 border-b">
              <p className="text-sm whitespace-pre-wrap leading-relaxed">{post.text}</p>
              {post.analysis && (
                <div className="flex gap-2 mt-2 flex-wrap">
                  <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{post.analysis.hook}</span>
                  <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{post.analysis.emotionalTrigger}</span>
                  <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{post.analysis.format}</span>
                  {post.analysis.adaptability === "high" && (
                    <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">適応性:高</span>
                  )}
                </div>
              )}
            </div>

            {/* Generated content */}
            {post.generatedContent && (
              <div className="grid md:grid-cols-2 divide-x">
                <GeneratedItem
                  label="引用投稿"
                  item={post.generatedContent.quoteTweet}
                  copyKey={`qt-${post.tweetId}`}
                  copiedId={copiedId}
                  onCopy={(text, id) => copyText(text, id)}
                  onSetStatus={(status) => updateStatus(post.tweetId, "quoteTweet", status)}
                />
                <GeneratedItem
                  label="リプライ"
                  item={post.generatedContent.reply}
                  copyKey={`rp-${post.tweetId}`}
                  copiedId={copiedId}
                  onCopy={(text, id) => copyText(text, id)}
                  onSetStatus={(status) => updateStatus(post.tweetId, "reply", status)}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
