"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

interface QueueItem {
  id: string;
  business: "gearman" | "amble" | "kodomo" | "jsh" | "drAuto";
  type: "x" | "article" | "threads" | "note";
  status: string;
  text: string;
  title?: string;
  scores?: Record<string, number>;
  avgScore?: number;
  qualityIssues?: { level: string; pattern: string; count: number }[];
  createdAt: string;
  sourceFile: string;
}

// --- Config ---

const BUSINESS_LABELS: Record<string, string> = {
  gearman: "ギア男",
  amble: "アンブロ",
  kodomo: "こどもケアラボ",
  jsh: "JSH",
  drAuto: "Dr.auto",
};

const BUSINESS_COLORS: Record<string, string> = {
  gearman: "bg-green-500/20 text-green-400",
  amble: "bg-blue-500/20 text-blue-400",
  kodomo: "bg-pink-500/20 text-pink-400",
  jsh: "bg-amber-500/20 text-amber-400",
  drAuto: "bg-purple-500/20 text-purple-400",
};

const TYPE_LABELS: Record<string, string> = {
  x: "𝕏",
  article: "記事",
  threads: "Threads",
  note: "note",
};

const BUSINESS_FILTER_OPTIONS = [
  { value: "all", label: "全事業" },
  { value: "gearman", label: "ギア男" },
  { value: "amble", label: "アンブロ" },
  { value: "kodomo", label: "こどもケアラボ" },
  { value: "jsh", label: "JSH" },
  { value: "drAuto", label: "Dr.auto" },
];

const SCORE_FILTER_OPTIONS = [
  { value: "all", label: "全て" },
  { value: "unscored", label: "未採点" },
  { value: "scored", label: "採点済み" },
  { value: "low", label: "低スコア(<6)" },
];

const SORT_OPTIONS = [
  { value: "date_desc", label: "日付（新しい順）" },
  { value: "score_asc", label: "スコア（低い順）" },
  { value: "score_desc", label: "スコア（高い順）" },
];

// --- Helpers ---

function scoreBadgeClass(avg: number | undefined): string {
  if (avg === undefined) return "bg-gray-500/20 text-gray-400";
  if (avg >= 8) return "bg-emerald-500/20 text-emerald-400";
  if (avg >= 6) return "bg-amber-500/20 text-amber-400";
  return "bg-rose-500/20 text-rose-400";
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime()) || d.getFullYear() < 2000) return "—";
  return d.toLocaleDateString("ja-JP", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// --- Score detail panel ---
function ScoreDetail({ scores }: { scores: Record<string, number> }) {
  return (
    <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-1 text-xs">
      {Object.entries(scores).map(([dim, val]) => (
        <div
          key={dim}
          className="flex items-center justify-between bg-gray-800 rounded px-2 py-1"
        >
          <span className="text-gray-400 truncate mr-1">{dim}</span>
          <span
            className={`font-mono font-semibold ${
              val >= 8
                ? "text-emerald-400"
                : val >= 6
                  ? "text-amber-400"
                  : "text-rose-400"
            }`}
          >
            {val}
          </span>
        </div>
      ))}
    </div>
  );
}

// --- Quality issues badge ---
function QualityBadge({
  issues,
}: {
  issues: { level: string; pattern: string; count: number }[];
}) {
  const high = issues.filter((i) => i.level === "HIGH").length;
  const med = issues.filter((i) => i.level === "MEDIUM").length;
  if (high === 0 && med === 0) return null;
  return (
    <span className="text-xs bg-orange-500/20 text-orange-400 rounded px-1.5 py-0.5">
      AI臭 {high > 0 ? `H:${high} ` : ""}
      {med > 0 ? `M:${med}` : ""}
    </span>
  );
}

// --- Card ---
function QueueCard({
  item,
  onScore,
  scoring,
  onMarkPosted,
  markingPosted,
}: {
  item: QueueItem;
  onScore: (id: string) => void;
  scoring: boolean;
  onMarkPosted?: (id: string) => void;
  markingPosted?: boolean;
}) {
  const [scoreExpanded, setScoreExpanded] = useState(false);
  const [textExpanded, setTextExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const canScore = RUBRIC_KEYS.has(`${item.business}-${item.type}`);
  const canMarkPosted = item.status !== "posted" && item.status !== "rejected";
  const isLong = item.text.length > 80 || item.text.includes("\n");

  function handleCopy() {
    void navigator.clipboard.writeText(item.text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-2">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full ${BUSINESS_COLORS[item.business] ?? "bg-gray-500/20 text-gray-400"}`}
          >
            {BUSINESS_LABELS[item.business] ?? item.business}
          </span>
          <span className="text-xs text-gray-500">
            {TYPE_LABELS[item.type] ?? item.type}
          </span>
          <span className={`text-xs border rounded px-1.5 ${item.status === "posted" ? "border-emerald-700 text-emerald-500" : "border-gray-700 text-gray-600"}`}>
            {item.status}
          </span>
          {item.qualityIssues && item.qualityIssues.length > 0 && (
            <QualityBadge issues={item.qualityIssues} />
          )}
        </div>
        <span className="text-xs text-gray-600 whitespace-nowrap shrink-0">
          {formatDate(item.createdAt)}
        </span>
      </div>

      {/* Title (if article/note) */}
      {item.title && (
        <p className="text-sm font-medium text-gray-200 leading-snug">
          {item.title}
        </p>
      )}

      {/* Body text — クリックで全文展開 */}
      <div>
        <p
          className={`text-sm text-gray-400 leading-relaxed whitespace-pre-line ${textExpanded ? "" : "line-clamp-2"}`}
        >
          {item.text}
        </p>
        {isLong && (
          <button
            onClick={() => setTextExpanded((v) => !v)}
            className="text-xs text-gray-600 hover:text-gray-400 transition mt-0.5"
          >
            {textExpanded ? "▲ 折りたたむ" : "▼ 全文を表示"}
          </button>
        )}
      </div>

      {/* Score expand area */}
      {item.scores && scoreExpanded && <ScoreDetail scores={item.scores} />}

      {/* Action row */}
      <div className="flex items-center gap-2 pt-1 flex-wrap">
        {/* Score badge */}
        {item.avgScore !== undefined ? (
          <button
            onClick={() => setScoreExpanded((v) => !v)}
            className={`text-xs font-mono font-semibold px-2 py-0.5 rounded ${scoreBadgeClass(item.avgScore)} hover:opacity-80 transition`}
          >
            {item.avgScore.toFixed(1)} {scoreExpanded ? "▲" : "▼"}
          </button>
        ) : (
          <span className="text-xs px-2 py-0.5 rounded bg-gray-500/20 text-gray-400">
            未採点
          </span>
        )}

        {/* Copy button */}
        <button
          onClick={handleCopy}
          className="text-xs px-3 py-1 rounded-lg border transition border-gray-600 text-gray-300 hover:border-gray-400 hover:text-white"
        >
          {copied ? "コピー完了 ✓" : "コピー"}
        </button>

        {/* Score button */}
        {canScore && (
          <button
            onClick={() => onScore(item.id)}
            disabled={scoring}
            className={`text-xs px-3 py-1 rounded-lg border transition ${
              scoring
                ? "border-gray-700 text-gray-600 cursor-not-allowed"
                : "border-gray-600 text-gray-300 hover:border-gray-400 hover:text-white"
            }`}
          >
            {scoring ? (
              <span className="inline-flex items-center gap-1">
                <span className="inline-block w-3 h-3 border-2 border-gray-500 border-t-gray-300 rounded-full animate-spin" />
                採点中…
              </span>
            ) : (
              "採点する"
            )}
          </button>
        )}

        {/* Mark as posted (drAuto only) */}
        {canMarkPosted && onMarkPosted && (
          <button
            onClick={() => onMarkPosted(item.id)}
            disabled={markingPosted}
            className={`text-xs px-3 py-1 rounded-lg border transition ml-auto ${
              markingPosted
                ? "border-gray-700 text-gray-600 cursor-not-allowed"
                : "border-emerald-700 text-emerald-400 hover:border-emerald-500 hover:text-emerald-300"
            }`}
          >
            {markingPosted ? "更新中…" : "投稿済みにする"}
          </button>
        )}
      </div>
    </div>
  );
}

// Valid rubric keys (must match score API)
const RUBRIC_KEYS = new Set([
  "jsh-threads",
  "drAuto-note",
  "gearman-x",
  "gearman-article",
  "amble-x",
  "kodomo-x",
]);

// --- Main Page ---
export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [businessFilter, setBusinessFilter] = useState("all");
  const [scoreFilter, setScoreFilter] = useState("all");
  const [sort, setSort] = useState("date_desc");
  const [scoringIds, setScoringIds] = useState<Set<string>>(new Set());
  const [markingPostedIds, setMarkingPostedIds] = useState<Set<string>>(new Set());

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/queue");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as QueueItem[];
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得エラー");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchItems();
  }, [fetchItems]);

  const handleScore = useCallback(
    async (id: string) => {
      const item = items.find((i) => i.id === id);
      if (!item) return;
      setScoringIds((prev) => new Set(prev).add(id));
      try {
        const res = await fetch("/api/score", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            business: item.business,
            type: item.type,
            id: item.id,
            text: item.text,
            writeBack: true,
          }),
        });
        if (!res.ok) {
          const err = (await res.json()) as { error?: string };
          throw new Error(err.error ?? `HTTP ${res.status}`);
        }
        const { scores, avgScore } = (await res.json()) as {
          scores: Record<string, number>;
          avgScore: number;
        };
        setItems((prev) =>
          prev.map((i) => (i.id === id ? { ...i, scores, avgScore } : i)),
        );
      } catch (e) {
        alert(
          `採点エラー: ${e instanceof Error ? e.message : String(e)}`,
        );
      } finally {
        setScoringIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [items],
  );

  const handleMarkPosted = useCallback(async (id: string) => {
    setMarkingPostedIds((prev) => new Set(prev).add(id));
    try {
      const res = await fetch("/api/queue", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, status: "posted" }),
      });
      if (!res.ok) {
        const err = (await res.json()) as { error?: string };
        throw new Error(err.error ?? `HTTP ${res.status}`);
      }
      setItems((prev) =>
        prev.map((i) => (i.id === id ? { ...i, status: "posted" } : i)),
      );
    } catch (e) {
      alert(`更新エラー: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setMarkingPostedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }, []);

  const filtered = useMemo(() => {
    let result = [...items];

    if (businessFilter !== "all") {
      result = result.filter((i) => i.business === businessFilter);
    }

    if (scoreFilter === "unscored") {
      result = result.filter((i) => i.avgScore === undefined);
    } else if (scoreFilter === "scored") {
      result = result.filter((i) => i.avgScore !== undefined);
    } else if (scoreFilter === "low") {
      result = result.filter(
        (i) => i.avgScore !== undefined && i.avgScore < 6,
      );
    }

    if (sort === "date_desc") {
      result.sort(
        (a, b) =>
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
      );
    } else if (sort === "score_asc") {
      result.sort((a, b) => {
        const sa = a.avgScore ?? 99;
        const sb = b.avgScore ?? 99;
        return sa - sb;
      });
    } else if (sort === "score_desc") {
      result.sort((a, b) => {
        const sa = a.avgScore ?? -1;
        const sb = b.avgScore ?? -1;
        return sb - sa;
      });
    }

    return result;
  }, [items, businessFilter, scoreFilter, sort]);

  // Summary counts
  const summary = useMemo(() => {
    const byBusiness: Record<string, number> = {};
    let unscored = 0;
    for (const item of items) {
      byBusiness[item.business] = (byBusiness[item.business] ?? 0) + 1;
      if (item.avgScore === undefined) unscored++;
    }
    return { byBusiness, unscored, total: items.length };
  }, [items]);

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">コンテンツキュー</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            全事業の自動生成コンテンツ一覧・採点管理
          </p>
        </div>
        <button
          onClick={() => void fetchItems()}
          className="text-sm px-3 py-1.5 rounded-lg border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 transition"
        >
          更新
        </button>
      </div>

      {/* Summary strip */}
      {!loading && !error && (
        <div className="mb-5 flex flex-wrap gap-3">
          <div className="bg-gray-900 rounded-lg px-3 py-2 text-sm">
            <span className="text-gray-400">総件数</span>
            <span className="ml-2 font-semibold text-white">
              {summary.total}
            </span>
          </div>
          <div className="bg-gray-900 rounded-lg px-3 py-2 text-sm">
            <span className="text-gray-400">未採点</span>
            <span
              className={`ml-2 font-semibold ${summary.unscored > 0 ? "text-amber-400" : "text-emerald-400"}`}
            >
              {summary.unscored}
            </span>
          </div>
          {Object.entries(summary.byBusiness).map(([biz, count]) => (
            <div
              key={biz}
              className="bg-gray-900 rounded-lg px-3 py-2 text-sm flex items-center gap-2"
            >
              <span
                className={`text-xs font-semibold px-1.5 py-0.5 rounded-full ${BUSINESS_COLORS[biz] ?? "bg-gray-500/20 text-gray-400"}`}
              >
                {BUSINESS_LABELS[biz] ?? biz}
              </span>
              <span className="text-white font-semibold">{count}</span>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          value={businessFilter}
          onChange={(e) => setBusinessFilter(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-gray-500"
        >
          {BUSINESS_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={scoreFilter}
          onChange={(e) => setScoreFilter(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-gray-500"
        >
          {SCORE_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-gray-500"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-sm text-gray-500 self-center">
          {filtered.length} 件
        </span>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-gray-500">
          <span className="inline-block w-5 h-5 border-2 border-gray-600 border-t-gray-300 rounded-full animate-spin mr-3" />
          読み込み中…
        </div>
      ) : error ? (
        <div className="bg-rose-900/30 border border-rose-700 rounded-xl p-4 text-rose-300 text-sm">
          エラー: {error}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 text-gray-600">
          該当するコンテンツがありません
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((item) => (
            <QueueCard
              key={item.id}
              item={item}
              onScore={handleScore}
              scoring={scoringIds.has(item.id)}
              onMarkPosted={handleMarkPosted}
              markingPosted={markingPostedIds.has(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
