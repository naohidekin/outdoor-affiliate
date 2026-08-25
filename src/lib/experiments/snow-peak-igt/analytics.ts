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

type GtagWindow = Window & { gtag?: (...args: unknown[]) => void };

// gtag が現れるまで待つ間隔と上限。
// GA4は afterInteractive で読み込まれるので、初回ロードでは
// 数百ms〜数秒あとに現れる。10秒待って来なければ、
// ブロッカー等で本当に来ないと判断して諦める
const RETRY_MS = 300;
const MAX_WAIT_MS = 10_000;

/**
 * gtag が使えるようになってから送る。
 *
 * 2026-08-24、この関数で2回失敗している。記録しておく。
 *
 * ① 最初の実装は `typeof gtag !== "function"` なら**捨てていた**。
 *    GA4は afterInteractive で読み込まれるのに対し、表示イベントは
 *    useEffect（マウント時）で発火するため、初回ロードでは必ず
 *    gtag より先に走る。結果 english_hub_view だけが記録されず、
 *    クライアント遷移で開いた finder_view は記録される、という
 *    一貫性のない欠落になった。
 *
 * ② 次に dataLayer へ積む方式にしたが、これも届かなかった。
 *    積んだイベントはルートレイアウトの `gtag('config', ...)` より
 *    **前**にキューへ入る。GA4は config より前のイベントコマンドを
 *    処理しないので、積んでも捨てられる。順序の問題だった。
 *
 * どちらも「送った気になっていたが届いていない」形の失敗で、
 * 画面上は何も起きないため気づきにくい。実データを見て初めて分かった。
 *
 * そこで順序に依存しない形にする。gtag が現れるまで待ってから送る。
 * gtag が定義されている時点で config は済んでいるので、
 * この経路なら順序を気にする必要がない。
 */
function deliver(name: EnEventName, clean: EnEventPayload, waited: number): void {
  const w = window as GtagWindow;
  if (typeof w.gtag === "function") {
    w.gtag("event", name, clean);
    return;
  }
  if (waited >= MAX_WAIT_MS) {
    // 本当に来ない場合。握り潰すと実装ミスと区別がつかない
    if (process.env.NODE_ENV !== "production") {
      console.warn(`[en-analytics] dropped ${name}: gtag never became available`);
    }
    return;
  }
  setTimeout(() => deliver(name, clean, waited + RETRY_MS), RETRY_MS);
}

/**
 * イベント送信。送信前に必ず sanitize を通す。
 * 呼び出し側が何を渡しても、許可リスト外は外へ出ない。
 */
export function trackEnEvent(name: EnEventName, payload: EnEventPayload = {}): void {
  const clean = sanitizeEventPayload(payload);
  if (typeof window === "undefined") return;
  deliver(name, clean, 0);
}
