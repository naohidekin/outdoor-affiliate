"use client";

import { useEffect, useState } from "react";

type LaunchdJob = {
  label: string;
  pid: number | null;
  lastExitStatus: number | null;
};

export default function LaunchdPage() {
  const [jobs, setJobs] = useState<LaunchdJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actingLabel, setActingLabel] = useState<string | null>(null);

  async function loadJobs() {
    setLoading(true);
    try {
      const response = await fetch("/api/launchd");
      const payload = (await response.json()) as LaunchdJob[] & { error?: string };
      if (!response.ok || !Array.isArray(payload)) {
        throw new Error(payload?.error || "ジョブ一覧の取得に失敗しました");
      }
      setJobs(payload);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "ジョブ一覧の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadJobs();
  }, []);

  async function runAction(label: string, action: "start" | "stop") {
    setActingLabel(label);
    try {
      const response = await fetch("/api/launchd", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label, action }),
      });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) {
        throw new Error(payload.error || "launchctl操作に失敗しました");
      }
      await loadJobs();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "launchctl操作に失敗しました");
    } finally {
      setActingLabel(null);
    }
  }

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      <div className="mb-6">
        <p className="text-sm uppercase tracking-[0.3em] text-green-400">管理</p>
        <h1 className="mt-2 text-3xl font-semibold">launchdジョブ</h1>
        <p className="mt-2 text-sm text-gray-400">関連ジョブの実行状態を確認し、手動で start / stop できます。</p>
      </div>

      {error ? (
        <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="overflow-hidden rounded-3xl border border-white/10 bg-white/5">
        <table className="min-w-full divide-y divide-white/10 text-sm">
          <thead className="bg-black/20 text-left text-gray-400">
            <tr>
              <th className="px-4 py-3 font-medium">Label</th>
              <th className="px-4 py-3 font-medium">PID</th>
              <th className="px-4 py-3 font-medium">ExitStatus</th>
              <th className="px-4 py-3 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {loading ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-gray-400">読み込み中...</td>
              </tr>
            ) : jobs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-gray-400">対象ジョブはありません。</td>
              </tr>
            ) : (
              jobs.map((job) => (
                <tr key={job.label} className="bg-black/10">
                  <td className="px-4 py-4 font-mono text-xs text-gray-200">{job.label}</td>
                  <td className="px-4 py-4 text-gray-300">{job.pid ?? "-"}</td>
                  <td className="px-4 py-4 text-gray-300">{job.lastExitStatus ?? "-"}</td>
                  <td className="px-4 py-4">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => runAction(job.label, "start")}
                        disabled={actingLabel === job.label}
                        className="rounded-full bg-emerald-500 px-3 py-1.5 text-xs font-medium text-gray-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        Start
                      </button>
                      <button
                        type="button"
                        onClick={() => runAction(job.label, "stop")}
                        disabled={actingLabel === job.label}
                        className="rounded-full bg-rose-500/80 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-rose-400 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        Stop
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
