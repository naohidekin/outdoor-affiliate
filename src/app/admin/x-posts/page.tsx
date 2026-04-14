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
  | "gear_story"
  | "poll_question"
  | "failure_story"
  | "gear_thread"
  | "ai_dev_log"
  | "parenting_outdoor"
  | "doc_health_tip"
  | "seasonal_hook"
  | "repost_rewrite";

type XPostStatus = "draft" | "approved" | "queued" | "posted" | "discarded";

interface XPost {
  id: string;
  type: XPostType;
  text: string;
  articleSlug: string | null;
  url: string | null;
  hashtags: string;
  status: XPostStatus;
  scheduledDate: string;
  generatedAt: string;
  postedAt: string | null;
  axis?: string;
  seedId?: string;
  validationErrors?: string;
  autoApproved?: string;
  selfScore?: number;
  firstLinePattern?: string;
  similarityScore?: number;
  retryCount?: number;
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
  poll_question: "アンケート",
  failure_story: "失敗談",
  gear_thread: "ギアスレッド",
  ai_dev_log: "AI開発日記",
  parenting_outdoor: "子育て×アウトドア",
  doc_health_tip: "医師健康Tips",
  seasonal_hook: "季節フック",
  repost_rewrite: "リライト",
};

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "下書き", color: "bg-gray-100 text-gray-600" },
  approved: { label: "承認済", color: "bg-green-100 text-green-700" },
  queued: { label: "投稿待ち", color: "bg-yellow-100 text-yellow-700" },
  posted: { label: "投稿済", color: "bg-blue-100 text-blue-700" },
  discarded: { label: "破棄", color: "bg-red-100 text-red-600" },
};

const AXIS_LABELS: Record<string, { label: string; color: string }> = {
  camp: { label: "Camp", color: "bg-emerald-50 text-emerald-700" },
  ai: { label: "AI", color: "bg-violet-50 text-violet-700" },
  parenting: { label: "子育て", color: "bg-pink-50 text-pink-700" },
  doctor: { label: "医師", color: "bg-amber-50 text-amber-700" },
};

interface AgentStatus {
  killSwitch: { enabled: boolean; reason: string; enabledAt: string | null };
  lastWeeklyReport: {
    week: string;
    generatedAt: string;
    summary: {
      totalGenerated: number;
      approved: number;
      posted: number;
      discarded: number;
      avgSelfScore: number | null;
      ngRate: number;
    };
    warnings: string[];
  } | null;
  analystFeedback: {
    updatedAt: string;
    topPerformingTypes: string[];
    writerHints: string[];
  } | null;
  postHistoryCount: number;
  recentErrors: Array<{ timestamp: string; label: string; exitCode: number }>;
}

export default function XPostsPage() {
  const [posts, setPosts] = useState<XPost[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<XPostType | "all">("all");
  const [copied, setCopied] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [generating, setGenerating] = useState(false);
  const [axisFilter, setAxisFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [showAgentPanel, setShowAgentPanel] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchLoading, setBatchLoading] = useState(false);
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

    fetch("/api/x-posts/agent-status")
      .then((r) => r.json())
      .then((data) => { if (!data.error) setAgentStatus(data); })
      .catch(() => {});
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

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAllFiltered() {
    setSelectedIds(new Set(filtered.map((p) => p.id)));
  }

  function deselectAll() {
    setSelectedIds(new Set());
  }

  async function batchAction(action: "approve" | "discard" | "delete") {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    const labels = { approve: "承認", discard: "破棄", delete: "削除" };
    if (!confirm(`${ids.length}件を一括${labels[action]}しますか？`)) return;

    setBatchLoading(true);
    try {
      const res = await fetch("/api/x-posts/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ids }),
      });
      if (res.ok) {
        if (action === "delete") {
          setPosts((prev) => prev.filter((p) => !selectedIds.has(p.id)));
        } else {
          const newStatus = action === "approve" ? "approved" : "discarded";
          setPosts((prev) =>
            prev.map((p) =>
              selectedIds.has(p.id)
                ? { ...p, status: newStatus as XPostStatus }
                : p
            )
          );
        }
        setSelectedIds(new Set());
      } else {
        const err = await res.json();
        alert(err.error || "バッチ操作に失敗しました");
      }
    } finally {
      setBatchLoading(false);
    }
  }

  const todayStr = new Date().toISOString().slice(0, 10);

  const filtered = posts.filter((p) => {
    if (filter !== "all" && p.status !== filter) return false;
    if (typeFilter !== "all" && p.type !== typeFilter) return false;
    if (axisFilter !== "all" && (p.axis || "unknown") !== axisFilter) return false;
    return true;
  });

  const counts = {
    all: posts.length,
    draft: posts.filter((p) => p.status === "draft").length,
    approved: posts.filter((p) => p.status === "approved").length,
    queued: posts.filter((p) => p.status === "queued").length,
    posted: posts.filter((p) => p.status === "posted").length,
    discarded: posts.filter((p) => p.status === "discarded").length,
  };

  // Phase1-B: 失敗検知 — 予定日を過ぎたのに posted/queued になっていない投稿
  const overdue = posts.filter(
    (p) =>
      p.scheduledDate &&
      p.scheduledDate < todayStr &&
      (p.status === "approved" || p.status === "queued")
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

      {/* KILL SWITCH 警告 */}
      {agentStatus?.killSwitch.enabled && (
        <div className="mb-4 p-3 rounded-lg bg-red-100 border border-red-300 text-sm text-red-800 font-medium">
          KILL SWITCH 有効: {agentStatus.killSwitch.reason}
          <span className="text-xs text-red-500 ml-2">
            ({agentStatus.killSwitch.enabledAt?.slice(0, 16)})
          </span>
        </div>
      )}

      {/* エージェント状態パネル */}
      <div className="mb-4">
        <button
          onClick={() => setShowAgentPanel(!showAgentPanel)}
          className="text-xs text-gray-400 hover:text-gray-600"
        >
          {showAgentPanel ? "- エージェント状態を閉じる" : "+ エージェント状態"}
        </button>
        {showAgentPanel && agentStatus && (
          <div className="mt-2 p-4 rounded-lg bg-gray-50 border border-gray-200 text-xs space-y-3">
            {agentStatus.lastWeeklyReport ? (
              <div>
                <div className="font-medium text-gray-700 mb-1">
                  週次レポート ({agentStatus.lastWeeklyReport.week})
                </div>
                <div className="flex gap-4 text-gray-500">
                  <span>生成: {agentStatus.lastWeeklyReport.summary.totalGenerated}</span>
                  <span>承認: {agentStatus.lastWeeklyReport.summary.approved}</span>
                  <span>投稿済: {agentStatus.lastWeeklyReport.summary.posted}</span>
                  <span>破棄: {agentStatus.lastWeeklyReport.summary.discarded}</span>
                  <span>NG率: {(agentStatus.lastWeeklyReport.summary.ngRate * 100).toFixed(0)}%</span>
                  <span>平均スコア: {agentStatus.lastWeeklyReport.summary.avgSelfScore ?? "N/A"}</span>
                </div>
                {agentStatus.lastWeeklyReport.warnings.length > 0 && (
                  <div className="mt-1 text-yellow-600">
                    {agentStatus.lastWeeklyReport.warnings.join(" / ")}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-gray-400">週次レポート: 未生成</div>
            )}

            {agentStatus.analystFeedback ? (
              <div>
                <div className="font-medium text-gray-700 mb-1">
                  Analyst ({agentStatus.analystFeedback.updatedAt?.slice(0, 10)})
                </div>
                {agentStatus.analystFeedback.topPerformingTypes.length > 0 && (
                  <div className="text-gray-500">
                    高パフォーマンス: {agentStatus.analystFeedback.topPerformingTypes.join(", ")}
                  </div>
                )}
                {agentStatus.analystFeedback.writerHints.length > 0 && (
                  <ul className="text-gray-500 list-disc list-inside">
                    {agentStatus.analystFeedback.writerHints.map((h, i) => (
                      <li key={i}>{h}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <div className="text-gray-400">Analyst: 未実行</div>
            )}

            <div className="text-gray-400">
              Post History: {agentStatus.postHistoryCount}件
            </div>

            {agentStatus.recentErrors && agentStatus.recentErrors.length > 0 && (
              <div className="mt-2 p-2 bg-red-50 rounded border border-red-200">
                <div className="font-semibold text-red-700 text-xs mb-1">直近エラー</div>
                <ul className="text-xs text-red-600 space-y-0.5">
                  {agentStatus.recentErrors.slice(0, 5).map((e, i) => (
                    <li key={i}>
                      {e.timestamp.replace("T", " ").replace("Z", "")} — {e.label} (exit {e.exitCode})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
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
            ["discarded", "破棄"],
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

      {/* Axis filter */}
      <div className="flex gap-2 mb-6">
        {(
          [
            ["all", "���軸"],
            ["camp", "Camp"],
            ["ai", "AI"],
            ["parenting", "子育て"],
            ["doctor", "医師"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setAxisFilter(key)}
            className={`px-3 py-1 rounded-full text-xs ${
              axisFilter === key
                ? "bg-gray-800 text-white"
                : "bg-gray-50 text-gray-500 hover:bg-gray-100"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Batch action bar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 mb-4 p-3 rounded-lg bg-gray-100 border border-gray-200">
          <span className="text-sm font-medium text-gray-700">
            {selectedIds.size}件選択中
          </span>
          <button
            onClick={selectAllFiltered}
            className="px-3 py-1 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50"
          >
            全選択 ({filtered.length})
          </button>
          <button
            onClick={deselectAll}
            className="px-3 py-1 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50"
          >
            選択解除
          </button>
          <div className="flex-1" />
          <button
            onClick={() => batchAction("approve")}
            disabled={batchLoading}
            className="px-3 py-1.5 text-xs font-medium bg-green-100 text-green-700 rounded-lg hover:bg-green-200 disabled:opacity-50"
          >
            一括承認
          </button>
          <button
            onClick={() => batchAction("discard")}
            disabled={batchLoading}
            className="px-3 py-1.5 text-xs font-medium bg-orange-100 text-orange-700 rounded-lg hover:bg-orange-200 disabled:opacity-50"
          >
            一括破棄
          </button>
          <button
            onClick={() => batchAction("delete")}
            disabled={batchLoading}
            className="px-3 py-1.5 text-xs font-medium bg-red-100 text-red-600 rounded-lg hover:bg-red-200 disabled:opacity-50"
          >
            一括削除
          </button>
        </div>
      )}

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
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={selectedIds.has(post.id)}
                  onChange={() => toggleSelect(post.id)}
                  className="mt-1 w-4 h-4 accent-green-600 shrink-0 cursor-pointer"
                />
                <div className="flex items-start justify-between gap-4 flex-1 min-w-0">
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
                    {post.axis && AXIS_LABELS[post.axis] && (
                      <span className={`text-xs px-2 py-0.5 rounded-full ${AXIS_LABELS[post.axis].color}`}>
                        {AXIS_LABELS[post.axis].label}
                      </span>
                    )}
                    <span className="text-xs text-gray-400">
                      {post.scheduledDate}
                    </span>
                    {post.selfScore != null && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-gray-50 text-gray-500 font-mono">
                        {post.selfScore.toFixed(1)}
                      </span>
                    )}
                    {post.autoApproved === "true" && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-teal-50 text-teal-600">
                        自動承認
                      </span>
                    )}
                    {isOverdue && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
                        予定超過
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
