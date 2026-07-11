"use client";

import { useEffect, useState } from "react";

type BusinessName = "gearman" | "amble" | "labo" | "kodomo" | "jsh" | "drAuto";

type KillSwitchState = {
  enabled: boolean;
  articleEnabled: boolean;
  researchEnabled: boolean;
  business: Record<BusinessName, boolean>;
  reason: string;
  disabledAt: string;
  disabledBy: string;
};

const BUSINESS_LABELS: Record<BusinessName, string> = {
  gearman: "ギア男（キャンプ）",
  amble: "アンブロ（投資）",
  labo: "ラボ（X Posts）",
  kodomo: "こどもケアラボ（医療）",
  jsh: "JSH（訪日）",
  drAuto: "Dr.auto（医師×AI）",
};

const GLOBAL_SWITCHES: { key: "enabled" | "articleEnabled" | "researchEnabled"; label: string; detail: string }[] = [
  { key: "enabled", label: "全システム停止", detail: "全パイプライン（投稿・記事・リサーチ）を止める非常ボタン" },
  { key: "articleEnabled", label: "記事パイプライン停止", detail: "article-daily / article-weekly のみ止める" },
  { key: "researchEnabled", label: "リサーチ系停止", detail: "viral-scout / トレンド収集のみ止める" },
];

function Toggle({ on, disabled, onClick }: { on: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
        on ? "bg-red-500" : "bg-gray-300"
      }`}
      aria-pressed={on}
    >
      <span
        className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

export default function KillSwitchPage() {
  const [state, setState] = useState<KillSwitchState | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    setError(null);
    try {
      const res = await fetch("/api/kill-switch");
      if (!res.ok) throw new Error(`取得失敗 (${res.status})`);
      const data = (await res.json()) as KillSwitchState;
      setState(data);
      setReason(data.reason || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function update(payload: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, reason }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `更新失敗 (${res.status})`);
      setState(data as KillSwitchState);
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新に失敗しました");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-gray-900">🛑 KILL_SWITCH</h1>
      <p className="text-sm text-gray-500 mt-1">
        自動パイプラインの非常停止。<strong className="text-red-600">スイッチON = 停止</strong> です。
      </p>
      <p className="text-xs mt-3 px-3 py-2 rounded-lg bg-amber-50 text-amber-800 border border-amber-200">
        ⚠️ このスイッチは <strong>ローカルMacのdev画面専用</strong> です（保存先: data/kill-switch.json。Vercel本番からは書き込めません）。
        本番サイトの表示には影響せず、Mac上のlaunchdジョブだけを制御します。
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {!state ? (
        <p className="mt-6 text-gray-500">読み込み中…</p>
      ) : (
        <>
          <h2 className="mt-8 text-lg font-semibold text-gray-900">全体スイッチ</h2>
          <div className="mt-3 rounded-xl border border-gray-200 bg-white divide-y divide-gray-100">
            {GLOBAL_SWITCHES.map((sw) => (
              <div key={sw.key} className="flex items-center justify-between gap-4 p-4">
                <div>
                  <p className="text-sm font-medium text-gray-900">{sw.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{sw.detail}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-semibold ${state[sw.key] ? "text-red-600" : "text-emerald-600"}`}>
                    {state[sw.key] ? "停止中" : "稼働許可"}
                  </span>
                  <Toggle on={state[sw.key]} disabled={saving} onClick={() => update({ field: sw.key, value: !state[sw.key] })} />
                </div>
              </div>
            ))}
          </div>

          <h2 className="mt-8 text-lg font-semibold text-gray-900">事業別（SNS投稿の個別停止）</h2>
          <p className="text-xs text-gray-500 mt-1">
            notion-poster がDBごとに参照します。1事業だけ止めたいときはこちら（全体を道連れにしない）。
          </p>
          <div className="mt-3 rounded-xl border border-gray-200 bg-white divide-y divide-gray-100">
            {(Object.keys(BUSINESS_LABELS) as BusinessName[]).map((name) => (
              <div key={name} className="flex items-center justify-between gap-4 p-4">
                <p className="text-sm text-gray-900">{BUSINESS_LABELS[name]}</p>
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-semibold ${state.business[name] ? "text-red-600" : "text-emerald-600"}`}>
                    {state.business[name] ? "停止中" : "稼働許可"}
                  </span>
                  <Toggle on={state.business[name]} disabled={saving} onClick={() => update({ business: name, value: !state.business[name] })} />
                </div>
              </div>
            ))}
          </div>

          <h2 className="mt-8 text-lg font-semibold text-gray-900">停止理由メモ</h2>
          <div className="mt-3 flex gap-2">
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例: 誤投稿の調査中"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <p className="mt-2 text-xs text-gray-400">
            最終更新: {state.disabledAt || "—"} {state.disabledBy ? `(${state.disabledBy})` : ""}
            ※ 理由は次にどれかのスイッチを操作したときに一緒に保存されます
          </p>
        </>
      )}
    </div>
  );
}
