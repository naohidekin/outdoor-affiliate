"use client";

import { useEffect, useState } from "react";

type KillSwitchState = {
  businesses: {
    gearman: {
      x: boolean;
      article: boolean;
      research: boolean;
    };
    amble: {
      x: boolean;
    };
    kodomo: {
      x: boolean;
      note: boolean;
      threads: boolean;
    };
  };
  global: boolean;
  updatedAt: string;
  reason: string;
};

type BusinessName = keyof KillSwitchState["businesses"];
type PlatformName = "x" | "article" | "research" | "note" | "threads";

const DEFAULT_STATE: KillSwitchState = {
  businesses: {
    gearman: { x: false, article: false, research: false },
    amble: { x: false },
    kodomo: { x: false, note: false, threads: false },
  },
  global: false,
  updatedAt: "",
  reason: "",
};

const BUSINESS_SECTIONS = [
  {
    title: "ギア男",
    business: "gearman",
    items: [
      { platform: "x", label: "X投稿" },
      { platform: "article", label: "記事生成" },
      { platform: "research", label: "リサーチ" },
    ],
  },
  {
    title: "アンブロ",
    business: "amble",
    items: [{ platform: "x", label: "X投稿" }],
  },
  {
    title: "こどもケアラボ",
    business: "kodomo",
    items: [
      { platform: "x", label: "X投稿" },
      { platform: "note", label: "note" },
      { platform: "threads", label: "Threads" },
    ],
  },
] as const;

function normalizeState(payload: Partial<KillSwitchState> | undefined): KillSwitchState {
  return {
    ...DEFAULT_STATE,
    ...payload,
    businesses: {
      gearman: {
        ...DEFAULT_STATE.businesses.gearman,
        ...payload?.businesses?.gearman,
      },
      amble: {
        ...DEFAULT_STATE.businesses.amble,
        ...payload?.businesses?.amble,
      },
      kodomo: {
        ...DEFAULT_STATE.businesses.kodomo,
        ...payload?.businesses?.kodomo,
      },
    },
  };
}

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
        setState(normalizeState(payload));
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "設定の取得に失敗しました");
      })
      .finally(() => setLoading(false));
  }, []);

  async function sendUpdate(fieldKey: string, body: Record<string, unknown>, optimisticState: KillSwitchState) {
    const previous = state;
    setState(optimisticState);
    setSavingField(fieldKey);
    setError(null);

    try {
      const response = await fetch("/api/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = (await response.json()) as KillSwitchState & { error?: string };
      if (!response.ok) {
        throw new Error(payload.error || "更新に失敗しました");
      }
      setState(normalizeState(payload));
    } catch (err: unknown) {
      setState(previous);
      setError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally {
      setSavingField(null);
    }
  }

  function updateGlobal(value: boolean) {
    void sendUpdate(
      "global",
      { global: value, reason: "" },
      {
        ...state,
        global: value,
      },
    );
  }

  function updateBusinessPlatform(business: BusinessName, platform: PlatformName, value: boolean) {
    const nextBusinessState = {
      ...(state.businesses[business] as Record<string, boolean>),
      [platform]: value,
    } as KillSwitchState["businesses"][BusinessName];

    void sendUpdate(
      `${business}:${platform}`,
      { business, platform, value },
      {
        ...state,
        businesses: {
          ...state.businesses,
          [business]: nextBusinessState,
        },
      },
    );
  }

  return (
    <div className="-m-4 min-h-full bg-gray-950 px-4 py-6 text-gray-100 lg:-m-8 lg:px-8 lg:py-8">
      <div className="mb-6">
        <p className="text-sm uppercase tracking-[0.3em] text-red-400">管理</p>
        <h1 className="mt-2 text-3xl font-semibold">KILL_SWITCH</h1>
        <p className="mt-2 text-sm text-gray-400">共有 kill-switch を business x platform 単位で即時切り替えします。</p>
      </div>

      {error ? (
        <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}

      <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
        <div className="space-y-6">
          <div className="flex items-center justify-between gap-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4">
            <div>
              <p className="font-medium text-gray-100">グローバル緊急停止</p>
              <p className="mt-1 text-sm text-red-100/70">全ビジネス・全プラットフォームを一括停止します。</p>
            </div>
            <Toggle
              checked={state.global}
              disabled={loading || savingField === "global"}
              onChange={() => updateGlobal(!state.global)}
            />
          </div>

          {BUSINESS_SECTIONS.map((section) => (
            <section key={section.business} className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <h2 className="text-sm font-semibold tracking-[0.2em] text-gray-400">── {section.title} ──</h2>
              <div className="mt-4 space-y-3">
                {section.items.map((item) => {
                  const fieldKey = `${section.business}:${item.platform}`;
                  const checked = Boolean(
                    (state.businesses[section.business] as Record<string, boolean>)[item.platform],
                  );
                  return (
                    <div key={fieldKey} className="flex items-center justify-between gap-4 rounded-2xl border border-white/10 bg-gray-950/60 p-4">
                      <p className="font-medium text-gray-100">{item.label}</p>
                      <Toggle
                        checked={checked}
                        disabled={loading || savingField === fieldKey}
                        onChange={() => updateBusinessPlatform(section.business, item.platform, !checked)}
                      />
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        <div className="mt-6 rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-gray-300">
          <p>最終更新: {state.updatedAt ? new Date(state.updatedAt).toLocaleString("ja-JP") : "-"}</p>
          <p className="mt-2">理由: {state.reason || "-"}</p>
        </div>
      </div>
    </div>
  );
}
