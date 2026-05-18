"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface TrendResult {
  title: string;
  url: string;
  snippet: string;
  source: string;
  age: string;
  mode: "news" | "web";
  queryLabel: string;
}

interface TrendResponse {
  business: string;
  queryLabel: string;
  queryText: string;
  mode: "news" | "web";
  results: TrendResult[];
  error?: string;
}

interface QueryInfo {
  index: number;
  label: string;
}

interface BusinessConfig {
  label: string;
  queries: QueryInfo[];
}

const BUSINESSES = [
  { value: "jsh", label: "JSH", color: "bg-amber-500/20 text-amber-400" },
  { value: "drAuto", label: "Dr.auto", color: "bg-purple-500/20 text-purple-400" },
  { value: "gearman", label: "ギア男", color: "bg-green-500/20 text-green-400" },
  { value: "amble", label: "アンブロ", color: "bg-blue-500/20 text-blue-400" },
  { value: "kodomo", label: "こどもケアラボ", color: "bg-pink-500/20 text-pink-400" },
];

function ResultCard({ result }: { result: TrendResult }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    const text = `${result.title}\n${result.snippet}\n${result.url}`;
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-2 hover:border-gray-700 transition">
      {/* Source + age */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 font-medium">
            {result.source || "—"}
          </span>
          <span
            className={`text-xs px-1.5 py-0.5 rounded ${
              result.mode === "news"
                ? "bg-blue-500/15 text-blue-400"
                : "bg-gray-600/30 text-gray-400"
            }`}
          >
            {result.mode === "news" ? "ニュース" : "Web"}
          </span>
        </div>
        <span className="text-xs text-gray-600 shrink-0">{result.age}</span>
      </div>

      {/* Title */}
      <a
        href={result.url}
        target="_blank"
        rel="noopener noreferrer"
        className="block text-sm font-semibold text-gray-100 hover:text-white leading-snug hover:underline"
      >
        {result.title}
      </a>

      {/* Snippet */}
      {result.snippet && (
        <p className="text-xs text-gray-400 leading-relaxed line-clamp-3">
          {result.snippet}
        </p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <a
          href={result.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs px-3 py-1 rounded-lg border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 transition"
        >
          開く →
        </a>
        <button
          onClick={handleCopy}
          className="text-xs px-3 py-1 rounded-lg border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 transition"
        >
          {copied ? "✓ コピー済み" : "コピー"}
        </button>
      </div>
    </div>
  );
}

export default function TrendScoutPage() {
  const [activeBusiness, setActiveBusiness] = useState("jsh");
  const [queryIndex, setQueryIndex] = useState(0);
  const [customQ, setCustomQ] = useState("");
  const [configMap, setConfigMap] = useState<Record<string, BusinessConfig>>({});
  const [data, setData] = useState<TrendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load business config
  useEffect(() => {
    fetch("/api/trend-scout", { method: "POST" })
      .then((r) => r.json())
      .then((d) => setConfigMap(d as Record<string, BusinessConfig>))
      .catch(console.error);
  }, []);

  const currentConfig = configMap[activeBusiness];

  const handleSearch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    setData(null);

    const params = new URLSearchParams({
      business: activeBusiness,
      qi: String(queryIndex),
    });
    if (customQ.trim()) params.set("q", customQ.trim());

    try {
      const res = await fetch(`/api/trend-scout?${params}`, {
        signal: controller.signal,
      });
      const json = (await res.json()) as TrendResponse;
      if (!res.ok) throw new Error(json.error ?? `HTTP ${res.status}`);
      setData(json);
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "検索エラー");
    } finally {
      setLoading(false);
    }
  }, [activeBusiness, queryIndex, customQ]);

  // Auto-search when business or query changes
  useEffect(() => {
    void handleSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeBusiness, queryIndex]);

  function handleBusinessChange(biz: string) {
    setActiveBusiness(biz);
    setQueryIndex(0);
    setCustomQ("");
  }

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-bold">トレンドスカウト</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          各事業の直近ニュース・トレンド投稿を検索して、ネタに乗る
        </p>
      </div>

      {/* Business tabs */}
      <div className="flex flex-wrap gap-2 mb-5">
        {BUSINESSES.map((b) => (
          <button
            key={b.value}
            onClick={() => handleBusinessChange(b.value)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              activeBusiness === b.value
                ? b.color + " ring-1 ring-current"
                : "bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700"
            }`}
          >
            {b.label}
          </button>
        ))}
      </div>

      {/* Query selector + custom search */}
      <div className="flex flex-wrap gap-3 mb-5">
        {/* Preset queries */}
        {currentConfig?.queries.map((q) => (
          <button
            key={q.index}
            onClick={() => {
              setQueryIndex(q.index);
              setCustomQ("");
            }}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${
              queryIndex === q.index && !customQ.trim()
                ? "border-gray-400 text-white bg-gray-800"
                : "border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200"
            }`}
          >
            {q.label}
          </button>
        ))}
      </div>

      {/* Custom query input */}
      <div className="flex gap-2 mb-6">
        <input
          type="text"
          value={customQ}
          onChange={(e) => setCustomQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleSearch();
          }}
          placeholder="カスタム検索ワード（任意）"
          className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
        <button
          onClick={() => void handleSearch()}
          disabled={loading}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition ${
            loading
              ? "bg-gray-700 text-gray-500 cursor-not-allowed"
              : "bg-green-700 text-white hover:bg-green-600"
          }`}
        >
          {loading ? (
            <span className="inline-flex items-center gap-2">
              <span className="inline-block w-3.5 h-3.5 border-2 border-gray-500 border-t-gray-200 rounded-full animate-spin" />
              検索中…
            </span>
          ) : (
            "検索"
          )}
        </button>
      </div>

      {/* Current query display */}
      {data && (
        <div className="mb-4 text-xs text-gray-600">
          <span>検索: </span>
          <span className="text-gray-400 font-mono">"{data.queryText}"</span>
          <span className="ml-2">— {data.results.length} 件</span>
        </div>
      )}

      {/* Results */}
      {error ? (
        <div className="bg-rose-900/30 border border-rose-700 rounded-xl p-4 text-rose-300 text-sm">
          エラー: {error}
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-20 text-gray-500">
          <span className="inline-block w-5 h-5 border-2 border-gray-600 border-t-gray-300 rounded-full animate-spin mr-3" />
          Brave Search で検索中…
        </div>
      ) : data && data.results.length === 0 ? (
        <div className="text-center py-20 text-gray-600">
          結果が見つかりませんでした
        </div>
      ) : data ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.results.map((r, i) => (
            <ResultCard key={`${r.url}-${i}`} result={r} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
