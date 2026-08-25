/**
 * 英語セクションの計測アダプタ
 *
 * 既存のGA4（gtag、ルートレイアウトで読み込み済み）を再利用する。
 * 新しい外部サービスは足さない。
 *
 * 検証したいのはページビューではなく「Finderが使われたか」「未登録型番の
 * リクエストが来たか」「販売先へ遷移したか」なので、そこだけを取る。
 *
 * このファイルは他の .ts をランタイムimportしない（core.ts と同じ理由）。
 */

export const EN_EVENTS = [
  "english_hub_view",
  "finder_view",
  "finder_start",
  "finder_complete",
  "result_found",
  "result_unknown",
  "model_request_submit",
  "affiliate_click",
] as const;

export type EnEventName = (typeof EN_EVENTS)[number];

/**
 * イベントに載せてよいフィールド。**この許可リストが唯一の門番**。
 *
 * 載せてはいけないもの（ユーザーの自由入力・メールアドレス・氏名・
 * 完全なaffiliate URL）は、ここに無いというだけで自動的に落ちる。
 * 「送らないように気をつける」ではなく「送れない」形にしてある。
 */
export const ALLOWED_EVENT_FIELDS = [
  "page",
  "market",
  "model_id",
  "result_status",
  "merchant",
  "placement",
] as const;

export type EnEventField = (typeof ALLOWED_EVENT_FIELDS)[number];

export type EnEventPayload = Partial<Record<EnEventField, string>>;

/** 英語セクション内でのボタン設置場所 */
export type EnPlacement = "hub" | "finder_result" | "guide" | "methodology";

/**
 * payload を許可リストで絞る。
 *
 * 値の型も string に限定する。オブジェクトをそのまま渡されると
 * GA4側で展開されて、意図しない中身（フォームの入力値など）が
 * 混ざる余地ができるため。
 */
export function sanitizeEventPayload(input: unknown): EnEventPayload {
  if (typeof input !== "object" || input === null) return {};
  const source = input as Record<string, unknown>;
  const out: EnEventPayload = {};
  for (const key of ALLOWED_EVENT_FIELDS) {
    const value = source[key];
    if (typeof value === "string" && value.trim() !== "") {
      out[key] = value.trim();
    }
  }
  return out;
}

type GtagWindow = Window & {
  gtag?: (...args: unknown[]) => void;
  dataLayer?: unknown[];
};

/**
 * イベント送信。送信前に必ず sanitize を通す。
 * 呼び出し側が何を渡しても、許可リスト外は外へ出ない。
 *
 * gtag がまだ無いときは dataLayer に積む。これは必須の分岐で、
 * 省くと**表示直後のイベントが黙って消える**。
 *
 * 2026-08-24 に実際に踏んだ。GA4はルートレイアウトで
 * `strategy="afterInteractive"` で読み込まれるため、`window.gtag` が
 * 定義されるのはハイドレーション後。ところが表示イベントは
 * useEffect（マウント時）で発火するので、初回ロードではgtagより先に走る。
 * 結果、`/en/` を開いても `english_hub_view` だけが記録されず、
 * クライアント遷移で開いた `finder_view` は記録される、という
 * 一貫性のない欠落になっていた。
 *
 * dataLayer に積んでおけば gtag.js がロード時にまとめて処理する
 * （GA4の標準的な回避策）。dataLayer は gtag より先に存在しうるし、
 * 無ければここで作ってよい。
 */
export function trackEnEvent(name: EnEventName, payload: EnEventPayload = {}): void {
  const clean = sanitizeEventPayload(payload);
  if (typeof window === "undefined") return;

  const w = window as GtagWindow;
  if (typeof w.gtag === "function") {
    w.gtag("event", name, clean);
    return;
  }

  try {
    w.dataLayer = w.dataLayer || [];
    w.dataLayer.push(["event", name, clean]);
  } catch {
    // dataLayer にも積めない環境。ここまで来たら諦める
  }

  // GA4が本当に来ないケース（ブロッカー等）に気づけるよう開発時は出す
  if (process.env.NODE_ENV !== "production") {
    console.info(`[en-analytics] queued ${name}`, clean);
  }
}
