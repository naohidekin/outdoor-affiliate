"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STYLES: { key: string; label: string; emoji: string }[] = [
  { key: "manga",    label: "漫画",   emoji: "✏️" },
  { key: "painting", label: "絵画",   emoji: "🎨" },
  { key: "flat",     label: "フラット", emoji: "🟩" },
  { key: "sketch",   label: "スケッチ", emoji: "📐" },
  { key: "chibi",    label: "ちびキャラ", emoji: "🧸" },
  { key: "retro",    label: "レトロ",  emoji: "📺" },
  { key: "webtoon",  label: "webtoon", emoji: "📱" },
];

const DEFAULT_THEMES = [
  { label: "焚き火で失敗",     emoji: "🔥" },
  { label: "テント設営に手こずる", emoji: "⛺" },
  { label: "キャンプ飯が絶品",   emoji: "🍳" },
  { label: "虫に驚く",        emoji: "🐛" },
  { label: "雨に降られる",     emoji: "🌧️" },
  { label: "朝の目覚め",      emoji: "☀️" },
  { label: "ギアを買いすぎる",   emoji: "💸" },
];

type HistoryItem = { name: string; path: string; createdAt: string };

function parsePanel(log: string): number {
  const m = log.match(/Generating panel (\d)\/4/);
  return m ? parseInt(m[1]) : 0;
}

export default function FourKomaPage() {
  const [style, setStyle] = useState("manga");
  const [customTheme, setCustomTheme] = useState("");
  const [running, setRunning] = useState(false);
  const [currentTheme, setCurrentTheme] = useState("");
  const [panelProgress, setPanelProgress] = useState(0); // 0-4
  const [phase, setPhase] = useState<"story" | "panels" | "compose" | "">("");
  const [imagePath, setImagePath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  const loadHistory = useCallback(async () => {
    const res = await fetch("/api/4koma/list");
    if (res.ok) {
      const data = await res.json();
      setHistory(data.files ?? []);
    }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  async function generate(theme: string) {
    if (!theme.trim() || running) return;
    setRunning(true);
    setCurrentTheme(theme.trim());
    setLogs([]);
    setImagePath(null);
    setError(null);
    setPanelProgress(0);
    setPhase("story");

    try {
      const res = await fetch("/api/4koma/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: theme.trim(), style }),
      });

      if (!res.ok || !res.body) {
        setError("APIエラー: " + res.status);
        setRunning(false);
        return;
      }

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const msg = JSON.parse(line.slice(6));
            if (msg.log) {
              const text: string = msg.log;
              setLogs((prev) => [...prev, text]);
              setTimeout(() => logRef.current?.scrollTo({ top: 99999, behavior: "smooth" }), 0);
              const p = parsePanel(text);
              if (p > 0) { setPanelProgress(p); setPhase("panels"); }
              if (text.includes("Composing")) setPhase("compose");
            }
            if (msg.done) {
              if (msg.code === 0 && msg.imagePath) {
                setImagePath(msg.imagePath);
                setPanelProgress(4);
                loadHistory();
              } else if (msg.code !== 0) {
                setError("生成失敗（コード: " + msg.code + "）");
              }
              setRunning(false);
              setPhase("");
            }
          } catch { /* skip incomplete chunks */ }
        }
      }
    } catch (e) {
      setError(String(e));
      setRunning(false);
      setPhase("");
    }
  }

  const phaseLabel = phase === "story" ? "ストーリー生成中…" : phase === "panels" ? `パネル ${panelProgress}/4 生成中…` : phase === "compose" ? "コマ割り合成中…" : "";

  return (
    <div className="max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">4コマ漫画生成</h1>
          <p className="text-sm text-gray-500 mt-0.5">テーマを選んでクリックするだけ！</p>
        </div>
      </div>

      {/* Style picker */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 mb-4">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">スタイル</p>
        <div className="flex flex-wrap gap-2">
          {STYLES.map((s) => (
            <button
              key={s.key}
              onClick={() => setStyle(s.key)}
              disabled={running}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition border disabled:opacity-40 ${
                style === s.key
                  ? "bg-green-600 text-white border-green-600"
                  : "bg-white text-gray-600 border-gray-200 hover:border-green-400 hover:text-green-600"
              }`}
            >
              <span>{s.emoji}</span>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Theme quick-pick */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 mb-4">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">テーマを選ぶ（クリックで即生成）</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-4">
          {DEFAULT_THEMES.map((t) => (
            <button
              key={t.label}
              onClick={() => generate(t.label)}
              disabled={running}
              className={`flex items-center gap-2 px-4 py-3 rounded-xl border text-sm font-medium text-left transition disabled:opacity-40 ${
                running && currentTheme === t.label
                  ? "bg-green-600 text-white border-green-600"
                  : "bg-gray-50 text-gray-700 border-gray-200 hover:bg-green-50 hover:border-green-400 hover:text-green-700"
              }`}
            >
              <span className="text-xl">{t.emoji}</span>
              <span>{t.label}</span>
            </button>
          ))}
        </div>

        {/* Custom theme */}
        <div className="flex gap-2">
          <input
            type="text"
            value={customTheme}
            onChange={(e) => setCustomTheme(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !running && generate(customTheme)}
            placeholder="カスタムテーマを入力…"
            disabled={running}
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 disabled:opacity-50"
          />
          <button
            onClick={() => generate(customTheme)}
            disabled={running || !customTheme.trim()}
            className="bg-green-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            生成
          </button>
        </div>
      </div>

      {/* Progress */}
      {running && (
        <div className="bg-white rounded-xl shadow-sm border border-green-100 p-5 mb-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-4 h-4 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm font-medium text-gray-700">
              {phaseLabel || "生成中…"}
            </span>
          </div>
          {phase === "panels" && (
            <div className="flex gap-2">
              {[1, 2, 3, 4].map((n) => (
                <div
                  key={n}
                  className={`flex-1 h-2 rounded-full transition-all duration-500 ${
                    n <= panelProgress ? "bg-green-500" : "bg-gray-200"
                  }`}
                />
              ))}
            </div>
          )}
          <button
            onClick={() => setShowLogs((v) => !v)}
            className="mt-3 text-xs text-gray-400 hover:text-gray-600 transition"
          >
            {showLogs ? "ログを隠す ▲" : "ログを見る ▼"}
          </button>
          {showLogs && (
            <div
              ref={logRef}
              className="mt-2 bg-gray-900 rounded-lg p-3 h-36 overflow-y-auto font-mono text-xs text-green-400 whitespace-pre-wrap"
            >
              {logs.join("")}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Result */}
      {imagePath && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">生成完了 🎉</h2>
            <a href={imagePath} download className="text-sm text-green-600 hover:text-green-700 font-medium">
              ⬇ ダウンロード
            </a>
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imagePath} alt="生成された4コマ漫画" className="w-full max-w-sm rounded-xl border border-gray-100 shadow" />
          {!imagePath.startsWith("data:") && (
            <p className="text-xs text-gray-400 mt-2">{imagePath}</p>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">過去の生成履歴</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {history.map((item) => (
              <a key={item.name} href={item.path} target="_blank" rel="noreferrer" className="block group">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={item.path}
                  alt={item.name}
                  className="w-full rounded-lg border border-gray-100 shadow-sm group-hover:shadow-md transition"
                />
                <p className="text-xs text-gray-400 mt-1 truncate">
                  {new Date(item.createdAt).toLocaleDateString("ja-JP", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </p>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
