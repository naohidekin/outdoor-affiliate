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
  | "rakuten_room_pick"
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
  imageUrl?: string;
}

const TYPE_LABELS: Record<XPostType, string> = {
  article_promo: "記事紹介",
  outdoor_tip: "豆知識",
  article_repost: "記事リポスト",
  seasonal: "季節",
  rakuten_sale: "楽天セール",
  amazon_deal: "Amazonセール",
  news_comment: "ニュース",
  rakuten_room_pick: "楽天ROOM",
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
  const [genProgress, setGenProgress] = useState<string>("");
  const [axisFilter, setAxisFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [showAgentPanel, setShowAgentPanel] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchLoading, setBatchLoading] = useState(false);
  const [mangaPicker, setMangaPicker] = useState<string | null>(null);
  const [mangaList, setMangaList] = useState<Array<{ name: string; path: string; createdAt: string }>>([]);
  const [engagePosts, setEngagePosts] = useState<Array<{
    rowIndex: number; status: string; postType: string; text: string;
    sourceUrl: string; targetTweetId: string;
  }>>([]);
  const [engageLoading, setEngageLoading] = useState<Record<number, boolean>>({});
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

    fetch("/api/x-posts/engage")
      .then((r) => r.json())
      .then((data) => { if (Array.isArray(data)) setEngagePosts(data); })
      .catch(() => {});
  }, []);

  async function handleEngageAction(rowIndex: number, status: "ready" | "skipped") {
    setEngageLoading((prev) => ({ ...prev, [rowIndex]: true }));
    try {
      await fetch("/api/x-posts/engage", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rowIndex, status }),
      });
      setEngagePosts((prev) => prev.filter((p) => p.rowIndex !== rowIndex));
    } finally {
      setEngageLoading((prev) => ({ ...prev, [rowIndex]: false }));
    }
  }

  // 軸別の生成グループ定義。各ボタンはこのうちの1セットを順次APIに投げる。
  const GENERATE_GROUPS: Record<string, { label: string; types: string[] }> = {
    doctorAi: {
      label: "🩺 医師系",
      types: ["doc_health_tip"],
    },
    camp: {
      label: "🏕️ キャンプ系",
      types: ["outdoor_tip", "failure_story", "news_comment", "rakuten_room_pick"],
    },
    others: {
      label: "📅 その他",
      types: ["parenting_outdoor", "seasonal_hook", "poll_question", "repost_rewrite"],
    },
  };

  async function handleGenerate(groupKey: keyof typeof GENERATE_GROUPS) {
    const group = GENERATE_GROUPS[groupKey];
    const types = group.types;

    setGenerating(true);
    setGenProgress(`${group.label} 生成開始...`);

    let totalGenerated = 0;
    let totalRetries = 0;
    const errors: string[] = [];

    try {
      for (let i = 0; i < types.length; i++) {
        const type = types[i];
        setGenProgress(`${group.label} ${i + 1}/${types.length} [${type}] 生成中...`);
        try {
          const res = await fetch("/api/x-posts/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ autoApprove: false, type }),
          });
          // エラー・成功とも可能なら JSON 本体を読んでエラーメッセージを取得
          let body: { ok?: boolean; generated?: number; qualityRetries?: number; error?: string } | null = null;
          try {
            body = await res.json();
          } catch {
            /* JSON でないケース (HTML エラーページ等) */
          }
          if (!res.ok) {
            const detail = body?.error ? ` - ${body.error.slice(0, 200)}` : "";
            errors.push(`${type}: HTTP ${res.status}${detail}`);
            continue;
          }
          if (body?.ok !== false) {
            totalGenerated += body?.generated || 0;
            totalRetries += body?.qualityRetries || 0;
          } else {
            errors.push(`${type}: ${body?.error?.slice(0, 200) || "不明"}`);
          }
        } catch (e) {
          errors.push(`${type}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }

      const retryInfo = totalRetries > 0 ? `（品質ゲートで${totalRetries}回の再生成）` : "";
      const errSummary = errors.length > 0
        ? `\n\n⚠️ ${errors.length}タイプで失敗:\n${errors.join("\n")}`
        : "";
      alert(`${group.label}: ${totalGenerated}件生成しました${retryInfo}${errSummary}`);

      try {
        const r = await fetch("/api/x-posts");
        if (r.ok) {
          const d = await r.json();
          if (Array.isArray(d)) setPosts(d);
          else if (Array.isArray(d.posts)) setPosts(d.posts);
        }
      } catch {
        /* 無視：ユーザーが手動リロードで反映できる */
      }
    } finally {
      setGenerating(false);
      setGenProgress("");
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
    if (!confirm("この投稿をすぐにXに送信しますか？")) return;

    // 1. Sheets に ready 行を追加
    const qRes = await fetch("/api/x-posts/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    if (!qRes.ok) {
      const err = await qRes.json();
      alert(err.error || "キュー追加に失敗しました");
      return;
    }
    const updated = await qRes.json();
    setPosts((prev) => prev.map((p) => (p.id === id ? updated : p)));

    // 2. post-to-x.js を起動して即時投稿
    const runRes = await fetch("/api/x-posts/run", { method: "POST" });
    const result = await runRes.json();
    if (result.ok) {
      alert("投稿しました ✓\n\n" + result.output);
      window.location.reload();
    } else {
      alert("投稿に失敗しました\n\n" + result.output);
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
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`更新失敗: ${(err as { error?: string }).error || res.statusText}`);
      return;
    }
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

  async function openMangaPicker(postId: string) {
    if (mangaList.length === 0) {
      const res = await fetch("/api/4koma/list");
      const data = await res.json();
      // /api/4koma/list は { files: [{name, path, createdAt}] } を返す
      const files = Array.isArray(data?.files) ? data.files : Array.isArray(data) ? data : [];
      setMangaList(files);
    }
    setMangaPicker(postId);
  }

  async function attachManga(postId: string, imageUrl: string) {
    // imageUrl は Vercel Blob の絶対URL or ローカル "/images/4koma/xxx.png" のどちらか
    const res = await fetch("/api/x-posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: postId, imageUrl }),
    });
    if (res.ok) {
      const updated = await res.json();
      setPosts((prev) => prev.map((p) => (p.id === postId ? updated : p)));
    }
    setMangaPicker(null);
  }

  async function removeManga(postId: string) {
    const res = await fetch("/api/x-posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: postId, imageUrl: "" }),
    });
    if (res.ok) {
      const updated = await res.json();
      setPosts((prev) => prev.map((p) => (p.id === postId ? updated : p)));
    }
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
          <p className="text-xs mt-2 px-3 py-2 rounded-lg bg-amber-50 text-amber-800 border border-amber-200">
            ⚠️ 投稿の生成・承認は 2026-07-05 に Notion（「ギア男 X Posts」DB）へ移行済みです。この画面は旧Sheets運用の閲覧・エンゲージ管理用で、新規投稿はここには表示されません。承認は Notion で行ってください（承認すると notion-poster が30分毎に自動投稿します）。
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => handleGenerate("doctorAi")}
            disabled={generating}
            title="doc_health_tip (2件) = 約1分"
            className="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            🩺 医師系 生成
          </button>
          <button
            onClick={() => handleGenerate("camp")}
            disabled={generating}
            title="outdoor_tip (2件) + failure_story (1件) + news_comment (1件) + rakuten_room_pick (1件) = 約1-2分"
            className="px-3 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
          >
            🏕️ キャンプ系 生成
          </button>
          <button
            onClick={() => handleGenerate("others")}
            disabled={generating}
            title="parenting + 季節 + poll + repost = 約1-2分"
            className="px-3 py-2 bg-purple-600 text-white rounded-lg text-sm hover:bg-purple-700 disabled:opacity-50"
          >
            📅 その他 生成
          </button>
        </div>
      </div>

      {/* 生成中の進捗表示 */}
      {generating && genProgress && (
        <div className="mb-4 p-3 rounded-lg bg-blue-50 border border-blue-200 text-sm text-blue-900">
          🔄 {genProgress}
          <span className="text-xs text-blue-600 ml-2">
            （1〜3分で完了します。タブを閉じずにお待ちください）
          </span>
        </div>
      )}

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
      <div className="flex flex-wrap gap-2 mb-3">
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
            ["all", "全軸"],
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
        <div className="flex flex-wrap items-center gap-2 mb-4 p-3 rounded-lg bg-gray-100 border border-gray-200">
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
          const statusInfo = STATUS_LABELS[post.status] ?? { label: post.status, color: "bg-gray-100 text-gray-600" };
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
                      {post.imageUrl && (
                        <div className="mt-2 flex items-center gap-2">
                          <img
                            src={post.imageUrl}
                            alt="4コマ漫画"
                            className="w-20 h-20 object-cover rounded border border-gray-200"
                          />
                          <span className="text-xs text-orange-600">🎨 4コマ添付中</span>
                        </div>
                      )}
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
                        onClick={() => openMangaPicker(post.id)}
                        className="px-3 py-1.5 bg-orange-50 text-orange-600 rounded-lg text-xs hover:bg-orange-100"
                        title="4コマ漫画を添付"
                      >
                        {post.imageUrl ? "🎨 変更" : "🎨 漫画"}
                      </button>
                    )}
                    {post.imageUrl && post.status !== "posted" && (
                      <button
                        onClick={() => removeManga(post.id)}
                        className="px-3 py-1.5 bg-gray-50 text-gray-400 rounded-lg text-xs hover:bg-gray-100"
                        title="漫画を外す"
                      >
                        🎨✕
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

      {/* エンゲージ管理セクション */}
      {engagePosts.length > 0 && (
        <div className="mt-10 border-t pt-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">
            エンゲージ管理 — 承認待ち ({engagePosts.length}件)
          </h2>
          <p className="text-xs text-gray-400 mb-4">
            承認 → status=ready → post-to-x.js が次回実行時に引用RT/リプライとして投稿します。
          </p>
          <div className="space-y-3">
            {engagePosts.map((ep) => (
              <div key={ep.rowIndex} className="bg-gray-50 rounded-lg p-4 border border-gray-100">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    ep.postType === "quote"
                      ? "bg-blue-100 text-blue-700"
                      : "bg-purple-100 text-purple-700"
                  }`}>
                    {ep.postType === "quote" ? "引用RT" : "リプライ"}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    ep.status === "ready" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
                  }`}>
                    {ep.status}
                  </span>
                  {ep.sourceUrl && (
                    <a
                      href={ep.sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-sky-500 hover:underline ml-auto"
                    >
                      引用元 →
                    </a>
                  )}
                </div>
                <p className="text-sm text-gray-800 whitespace-pre-wrap mb-3">{ep.text}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleEngageAction(ep.rowIndex, "ready")}
                    disabled={engageLoading[ep.rowIndex] || ep.status === "ready"}
                    className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                  >
                    {engageLoading[ep.rowIndex] ? "処理中..." : "承認（ready）"}
                  </button>
                  <button
                    onClick={() => handleEngageAction(ep.rowIndex, "skipped")}
                    disabled={engageLoading[ep.rowIndex]}
                    className="px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50"
                  >
                    却下
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4コマ漫画ピッカーモーダル */}
      {mangaPicker && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setMangaPicker(null)}
        >
          <div
            className="bg-white rounded-xl shadow-xl p-6 max-w-lg w-full max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-gray-800">4コマ漫画を選択</h3>
              <button
                onClick={() => setMangaPicker(null)}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none"
              >
                ✕
              </button>
            </div>
            {mangaList.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-8">
                4コマ漫画がありません。先に生成してください。
              </p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {mangaList.map((item) => (
                  <button
                    key={item.name}
                    onClick={() => attachManga(mangaPicker, item.path)}
                    className="rounded-lg overflow-hidden border-2 border-transparent hover:border-orange-400 transition"
                  >
                    <img
                      src={item.path}
                      alt={item.name}
                      className="w-full aspect-square object-cover"
                    />
                    <p className="text-xs text-gray-500 p-1 truncate">{item.name}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
