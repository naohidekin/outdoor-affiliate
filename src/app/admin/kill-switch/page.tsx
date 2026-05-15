"use client";

import { useEffect, useState } from "react";

type KillSwitchState = {
  enabled: boolean;
  articleEnabled: boolean;
  researchEnabled: boolean;
  lastUpdated?: string;
  lastReason?: string;
  reason?: string;
};

const DEFAULT_STATE: KillSwitchState = {
  enabled: false,
  articleEnabled: false,
  researchEnabled: false,
  lastUpdated: "",
  lastReason: "",
  reason: "",
};

function Toggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={onChange}
      className={`relative inline-flex h-7 w-12 items-center rounded-full transition ${
        checked ? "bg-emerald-500" : "bg-gray-700"
      } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    >
      <span
        className={`inline-block h-5 w-5 rounded-full bg-white transition ${
          checked ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

export default function KillSwitchPage() {
  const [state, setState] = useState<KillSwitchState>(DEFAULT_STATE);
  const [loading, setLoading] = useState(true);
  const [savingField, setSavingField] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/kill-switch")
      .then(async (response) => {
        const payload = (await response.json()) as KillSwitchState & { error?: string };
        if (!response.ok) {
          throw new Error(payload.error || "設定の取得に失敗しました");
        }
        setState({
          enabled: Boolean(payload.enabled),
          articleEnabled: Boolean(payload.articleEnabled),
          researchEnabled: Boolean(payload.researchEnabled),
          lastUpdated: payload.lastUpdated || "",
          lastReason: payload.lastReason || payload.reason || "",
          reason: payload.reason || "",
        });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "設定の取得に失敗しました");
      })
      .finally(() => setLoading(false));
  }, []);

  async function updateField(field: "enabled" | "articleEnabled" | "researchEnabled", value: boolean) {
    const previous = state;
    const nextState = {
      ...state,
      [field]: value,
      lastUpdated: new Date().toISOString(),
    };

    setState(nextState);
    setSavingField(field);
    setError(null);

    try {
      const response = await fetch("/api/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field, value, reason: state.lastReason || state.reason || "" }),
      });
      const payload = (await response.json()) as KillSwitchState & { error?: string };
      if (!response.ok) {
        throw new Error(payload.error || "更新に失敗しました");
      }
      setState({
        enabled: Boolean(payload.enabled),
        articleEnabled: Boolean(payload.articleEnabled),
        researchEnabled: Boolean(payload.researchEnabled),
        lastUpdated: payload.lastUpdated || "",
        lastReason: payload.lastReason || payload.reason || "",
        reason: payload.reason || "",
      });
    } catch (err: unknown) {
      setState(previous);
      setError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally {
      setSavingField(null);
    }
  }

  const rows: Array<{ field: "enabled" | "articleEnabled" | "researchEnabled"; label: string; description: string }> = [
    { field: "enabled", label: "全体", description: "ギア男の自動投稿全体を制御します。" },
    { field: "articleEnabled", label: "記事", description: "記事生成系の動作を制御します。" },
    { field: "researchEnabled", label: "リサーチ", description: "調査系ジョブの動作を制御します。" },
  ];

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      <div className="mb-6">
        <p className="text-sm uppercase tracking-[0.3em] text-red-400">管理</p>
        <h1 className="mt-2 text-3xl font-semibold">KILL_SWITCH</h1>
        <p className="mt-2 text-sm text-gray-400">主要フラグを即時に切り替えます。UIは楽観更新で反映します。</p>
      </div>

      {error ? (
        <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
        <div className="space-y-4">
          {rows.map((row) => (
            <div key={row.field} className="flex items-center justify-between gap-4 rounded-2xl border border-white/10 bg-black/20 p-4">
              <div>
                <p className="font-medium text-gray-100">{row.label}</p>
                <p className="mt-1 text-sm text-gray-500">{row.description}</p>
              </div>
              <Toggle
                checked={Boolean(state[row.field])}
                disabled={loading || savingField === row.field}
                onChange={() => updateField(row.field, !state[row.field])}
              />
            </div>
          ))}
        </div>

        <div className="mt-6 rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-gray-300">
          <p>最終更新: {state.lastUpdated ? new Date(state.lastUpdated).toLocaleString("ja-JP") : "-"}</p>
          <p className="mt-2">理由: {state.lastReason || state.reason || "-"}</p>
        </div>
      </div>
    </div>
  );
}
