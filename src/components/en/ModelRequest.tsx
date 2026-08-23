"use client";

import { useState } from "react";
import { trackEnEvent } from "@/lib/experiments/snow-peak-igt/analytics";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600";

const MARKETS = [
  { value: "", label: "Select…" },
  { value: "us", label: "United States" },
  { value: "jp", label: "Japan" },
  { value: "other", label: "Other" },
];

type State = "idle" | "sending" | "sent" | "error";

/**
 * 未登録型番のリクエスト。
 *
 * 送信先は `MODEL_REQUEST_FORM_URL`（サーバー側の環境変数）。
 * このコンポーネントは自前の /api/en/model-request に投げ、
 * サーバーがその先へ中継する。送信先URLをブラウザに出さないため。
 *
 * 未設定のときは `enabled=false` で降ってきて、フォームを描かない。
 * 送信できないフォームを見せるのは、書かせておいて捨てるのと同じ。
 *
 * **入力内容とメールアドレスは analytics に送らない。**
 * 送るのは「送信された」という事実と market だけ。
 */
export default function ModelRequest({ enabled }: { enabled: boolean }) {
  const [state, setState] = useState<State>("idle");
  const [market, setMarket] = useState("");

  if (!enabled) {
    return (
      <div className="bg-mist border border-line rounded-xl p-5 text-sm text-slate-600 leading-relaxed">
        <p className="font-medium text-ink-strong mb-1">
          Model requests are not open yet
        </p>
        <p>
          The request form is not configured on this deployment, so we are not
          showing a form that would silently discard what you write. In the
          meantime you can reach Camp Gear Lab through the contact details on
          the Japanese site.
        </p>
      </div>
    );
  }

  if (state === "sent") {
    return (
      <div
        className="bg-lake-50 border border-lake-200 rounded-xl p-5 text-sm text-ink"
        role="status"
      >
        <p className="font-medium text-ink-strong mb-1">Request received</p>
        <p className="text-slate-600">
          Thank you. We only publish a record once it has been checked against
          official Snow Peak documentation, so this may take a while — and if we
          cannot confirm it, we will not publish a guess.
        </p>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    setState("sending");

    try {
      const res = await fetch("/api/en/model-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          modelNumber: String(data.get("modelNumber") ?? ""),
          productName: String(data.get("productName") ?? ""),
          market: String(data.get("market") ?? ""),
          purpose: String(data.get("purpose") ?? ""),
          email: String(data.get("email") ?? ""),
        }),
      });
      if (!res.ok) throw new Error(String(res.status));

      // 送るのは「送信された」ことと market だけ。
      // 型番も自由入力なので送らない（登録済みIDとは違う）
      trackEnEvent("model_request_submit", {
        page: "finder",
        ...(market ? { market } : {}),
      });
      setState("sent");
    } catch {
      setState("error");
    }
  }

  const field =
    `w-full border border-line rounded-lg px-3 py-2.5 text-base text-ink bg-white placeholder:text-slate-400 ${FOCUS}`;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="req-model" className="block text-sm font-medium text-ink-strong mb-1">
          Model number
        </label>
        <input
          id="req-model"
          name="modelNumber"
          type="text"
          required
          maxLength={80}
          autoComplete="off"
          className={field}
        />
      </div>

      <div>
        <label htmlFor="req-name" className="block text-sm font-medium text-ink-strong mb-1">
          Product name, if known
        </label>
        <input
          id="req-name"
          name="productName"
          type="text"
          maxLength={160}
          autoComplete="off"
          className={field}
        />
      </div>

      <div>
        <label htmlFor="req-market" className="block text-sm font-medium text-ink-strong mb-1">
          Country or market
        </label>
        <select
          id="req-market"
          name="market"
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className={field}
        >
          {MARKETS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="req-purpose" className="block text-sm font-medium text-ink-strong mb-1">
          What are you trying to connect, replace or identify?
        </label>
        <textarea
          id="req-purpose"
          name="purpose"
          rows={3}
          maxLength={1000}
          className={field}
        />
      </div>

      <div>
        <label htmlFor="req-email" className="block text-sm font-medium text-ink-strong mb-1">
          Email address{" "}
          <span className="font-normal text-slate-500">(optional)</span>
        </label>
        <input
          id="req-email"
          name="email"
          type="email"
          maxLength={200}
          autoComplete="email"
          className={field}
        />
        <p className="text-xs text-slate-500 mt-1">
          Only used to reply to this request. It is never sent to analytics.
        </p>
      </div>

      {state === "error" ? (
        <p className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2" role="alert">
          We could not send that request. Please try again in a moment.
        </p>
      ) : null}

      <button
        type="submit"
        disabled={state === "sending"}
        className={`bg-lake-600 hover:bg-lake-700 disabled:opacity-60 text-white px-6 py-3 rounded-lg text-sm font-medium transition ${FOCUS}`}
      >
        {state === "sending" ? "Sending…" : "Request a model check"}
      </button>
    </form>
  );
}
