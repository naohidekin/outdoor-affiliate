"use client";

import { useRef, useState } from "react";

const STYLES = [
  { key: "manga",    label: "ザ・漫画（線しっかり）" },
  { key: "painting", label: "絵画タッチ" },
  { key: "flat",     label: "フラット" },
  { key: "sketch",   label: "スケッチ" },
  { key: "chibi",    label: "ちびキャラ" },
  { key: "retro",    label: "レトロ80年代" },
  { key: "webtoon",  label: "webtoon" },
];

const DEFAULT_THEMES = [
  "焚き火で失敗",
  "テント設営に手こずる",
  "キャンプ飯が絶品",
  "虫に驚く",
  "雨に降られる",
  "朝の目覚め",
  "ギアを買いすぎる",
];

export default function FourKomaPage() {
  const [theme, setTheme] = useState("");
  const [style, setStyle] = useState("manga");
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [imagePath, setImagePath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  async function generate() {
    if (!theme.trim()) return;
    setRunning(true);
    setLogs([]);
    setImagePath(null);
    setError(null);

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
              setLogs((prev) => [...prev, msg.log]);
              setTimeout(() => logRef.current?.scrollTo({ top: 99999, behavior: "smooth" }), 0);
            }
            if (msg.done) {
              if (msg.code === 0 && msg.imagePath) {
                setImagePath(msg.imagePath);
              } else if (msg.code !== 0) {
                setError("生成失敗（終了コード: " + msg.code + "）");
              }
              setRunning(false);
            }
          } catch {
            // JSON parse error on incomplete chunk — skip
          }
        }
      }
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-800 mb-6">4コマ漫画生成</h1>

      {/* 入力フォーム */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
        <div className="grid md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">テーマ</label>
            <input
              type="text"
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !running && theme.trim() && generate()}
              placeholder="例: 焚き火で失敗"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
              disabled={running}
            />
            <div className="flex flex-wrap gap-1 mt-2">
              {DEFAULT_THEMES.map((t) => (
                <button
                  key={t}
                  onClick={() => setTheme(t)}
                  disabled={running}
                  className="text-xs px-2 py-1 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50 transition disabled:opacity-40"
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">スタイル</label>
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              disabled={running}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            >
              {STYLES.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
          </div>
        </div>
        <button
          onClick={generate}
          disabled={running || !theme.trim()}
          className="bg-green-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {running ? "生成中…" : "生成する"}
        </button>
      </div>

      {/* ログ */}
      {logs.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 mb-6">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">ログ</h2>
          <div
            ref={logRef}
            className="bg-gray-900 rounded-lg p-4 h-48 overflow-y-auto font-mono text-xs text-green-400 whitespace-pre-wrap"
          >
            {logs.join("")}
          </div>
        </div>
      )}

      {/* エラー */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* 生成結果 */}
      {imagePath && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">生成完了</h2>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imagePath}
            alt="生成された4コマ漫画"
            className="max-w-md rounded-lg border border-gray-100 shadow-sm"
          />
          <p className="text-xs text-gray-400 mt-2">{imagePath}</p>
          <a
            href={imagePath}
            download
            className="mt-3 inline-block text-sm text-green-600 hover:text-green-700 underline"
          >
            ダウンロード
          </a>
        </div>
      )}
    </div>
  );
}
