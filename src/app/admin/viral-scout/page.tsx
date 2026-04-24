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
    quoteTweet: { text: string; axis: string; rationale: string; status: string; validationErrors?: string };
    reply: { text: string; axis: string; rationale: string; status: string; validationErrors?: string };
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
  approved: "bg-green-100 text-green-800",
  needs_review: "bg-red-100 text-red-800",
  skipped: "bg-gray-100 text-gray-500",
};

export default function ViralScoutPage() {
  const [posts, setPosts] = useState<ViralPost[]>([]);
  const [aggregate, setAggregate] = useState<AggregateAnalysis | null>(null);
  const [scoutedAt, setScoutedAt] = useState("");
  const [filterAxis, setFilterAxis] = useState("all");
  const [filterStatus, setFilterStatus] = useState("all");
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/viral-scout")
      .then((r) => r.json())
      .then((data) => {
        setPosts(data.viralPosts || []);
        setAggregate(data.aggregateAnalysis || null);
        setScoutedAt(data.scoutedAt || "");
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  async function updateStatus(tweetId: string, field: "quoteTweet" | "reply", status: string) {
    await fetch("/api/viral-scout", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tweetId, field, status }),
    });
    setPosts((prev) =>
      prev.map((p) => {
        if (p.tweetId !== tweetId || !p.generatedContent) return p;
        return {
          ...p,
          generatedContent: {
            ...p.generatedContent,
            [field]: { ...p.generatedContent[field], status },
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

  const filtered = posts.filter((p) => {
    if (filterAxis !== "all" && p.axis !== filterAxis) return false;
    if (filterStatus !== "all") {
      const qs = p.generatedContent?.quoteTweet?.status;
      const rs = p.generatedContent?.reply?.status;
      if (qs !== filterStatus && rs !== filterStatus) return false;
    }
    return true;
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

  // Stats
  const axisCounts: Record<string, number> = {};
  const statusCounts = { draft: 0, approved: 0, needs_review: 0, skipped: 0 };
  for (const p of posts) {
    axisCounts[p.axis] = (axisCounts[p.axis] || 0) + 1;
    const qs = p.generatedContent?.quoteTweet?.status || "draft";
    if (qs in statusCounts) statusCounts[qs as keyof typeof statusCounts]++;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Viral Scout</h1>
          <p className="text-sm text-gray-500 mt-1">
            {scoutedAt && `最終実行: ${new Date(scoutedAt).toLocaleString("ja-JP")}`} / {posts.length}件
          </p>
        </div>
      </div>

      {/* Aggregate Stats */}
      {aggregate && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          <div className="bg-white rounded-lg p-4 shadow-sm border">
            <p className="text-xs text-gray-500">収集数</p>
            <p className="text-2xl font-bold">{aggregate.totalAnalyzed}</p>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-sm border">
            <p className="text-xs text-gray-500">適応性「高」</p>
            <p className="text-2xl font-bold text-green-600">{aggregate.highAdaptability}</p>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-sm border">
            <p className="text-xs text-gray-500">トップフック</p>
            <p className="text-sm font-medium">{aggregate.topHooks?.[0]?.pattern || "-"}</p>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-sm border">
            <p className="text-xs text-gray-500">トップ感情</p>
            <p className="text-sm font-medium">{aggregate.topEmotionalTriggers?.[0]?.pattern || "-"}</p>
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
          <option value="all">全ステータス</option>
          <option value="draft">Draft</option>
          <option value="approved">Approved</option>
          <option value="needs_review">要レビュー</option>
          <option value="skipped">スキップ</option>
        </select>
        <span className="text-sm text-gray-500 self-center">{filtered.length}件表示</span>
      </div>

      {/* Post Cards */}
      <div className="space-y-4">
        {filtered.map((post) => (
          <div key={post.tweetId} className="bg-white rounded-lg shadow-sm border overflow-hidden">
            {/* Header */}
            <div className="px-4 py-3 border-b bg-gray-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded-full ${AXIS_COLORS[post.axis] || ""}`}>
                  {AXIS_LABELS[post.axis] || post.axis}
                </span>
                <span className="font-medium text-sm">@{post.authorUsername}</span>
                <span className="text-xs text-gray-400">
                  {post.authorFollowers.toLocaleString()} followers
                </span>
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span>score: {post.metrics.engagementScore}</span>
                <span>♥ {post.metrics.likes}</span>
                <span>RT {post.metrics.retweets}</span>
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
                {/* Quote Tweet */}
                <div className="px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-gray-500">引用投稿</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[post.generatedContent.quoteTweet.status] || ""}`}>
                      {post.generatedContent.quoteTweet.status}
                    </span>
                  </div>
                  <p className="text-sm whitespace-pre-wrap mb-2">{post.generatedContent.quoteTweet.text}</p>
                  {post.generatedContent.quoteTweet.validationErrors && (
                    <p className="text-xs text-red-500 mb-2">{post.generatedContent.quoteTweet.validationErrors}</p>
                  )}
                  <div className="flex gap-1">
                    <button
                      onClick={() => copyText(post.generatedContent!.quoteTweet.text, `qt-${post.tweetId}`)}
                      className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200"
                    >
                      {copiedId === `qt-${post.tweetId}` ? "Copied!" : "Copy"}
                    </button>
                    <button
                      onClick={() => updateStatus(post.tweetId, "quoteTweet", "approved")}
                      className="text-xs px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => updateStatus(post.tweetId, "quoteTweet", "skipped")}
                      className="text-xs px-2 py-1 bg-gray-100 text-gray-500 rounded hover:bg-gray-200"
                    >
                      Skip
                    </button>
                  </div>
                </div>

                {/* Reply */}
                <div className="px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-gray-500">リプライ</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[post.generatedContent.reply.status] || ""}`}>
                      {post.generatedContent.reply.status}
                    </span>
                  </div>
                  <p className="text-sm whitespace-pre-wrap mb-2">{post.generatedContent.reply.text}</p>
                  {post.generatedContent.reply.validationErrors && (
                    <p className="text-xs text-red-500 mb-2">{post.generatedContent.reply.validationErrors}</p>
                  )}
                  <div className="flex gap-1">
                    <button
                      onClick={() => copyText(post.generatedContent!.reply.text, `rp-${post.tweetId}`)}
                      className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200"
                    >
                      {copiedId === `rp-${post.tweetId}` ? "Copied!" : "Copy"}
                    </button>
                    <button
                      onClick={() => updateStatus(post.tweetId, "reply", "approved")}
                      className="text-xs px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => updateStatus(post.tweetId, "reply", "skipped")}
                      className="text-xs px-2 py-1 bg-gray-100 text-gray-500 rounded hover:bg-gray-200"
                    >
                      Skip
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
