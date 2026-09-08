"use client";
import { useSyncExternalStore, useState } from "react";
import { hasAnalyticsExclusion, setAnalyticsExclusion } from "@/lib/analyticsExclusion";
function subscribe(callback: () => void) {
  window.addEventListener("camp-analytics-preference", callback);
  window.addEventListener("focus", callback);
  return () => { window.removeEventListener("camp-analytics-preference", callback); window.removeEventListener("focus", callback); };
}
export default function AnalyticsPreference() {
  const excluded = useSyncExternalStore(subscribe, () => hasAnalyticsExclusion(document.cookie), () => false);
  const [message, setMessage] = useState("");
  function change(value: boolean) {
    setMessage(setAnalyticsExclusion(value) ? "設定を保存しました。開いている記事は再読み込みしてください。" : "設定を保存できませんでした。ブラウザのCookie設定を確認してください。");
  }
  return <main className="mx-auto w-full max-w-xl px-5 py-12 space-y-6">
    <h1 className="text-2xl font-bold">アクセス計測の設定</h1>
    <p>記事の編集・動作確認に使うブラウザを、PostHog・Google Analytics・購入先クリックの集計から除外できます。購入リンクは通常どおり使えます。</p>
    <p aria-live="polite" className="font-bold">このブラウザ：{excluded ? "計測から除外中" : "通常の計測対象"}</p>
    <button className="min-h-12 w-full rounded-lg bg-green-800 px-4 py-3 text-white" onClick={() => change(true)}>このブラウザを計測から除外する</button>
    <button className="min-h-12 w-full rounded-lg border border-gray-400 px-4 py-3" onClick={() => change(false)}>除外を解除する</button>
    <p role="status">{message}</p>
    <p className="text-sm">設定はこのブラウザだけに保存され、最長1年間有効です。別の端末・ブラウザやCookie削除後は再設定してください。管理画面へのログイン・アクセス時にも除外され、ログアウト後も継続します。計測テストには別のブラウザを使ってください。過去のデータは変更しません。</p>
    {/* A full reload reinitializes analytics after changing this preference. */}
    {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
    <a className="underline" href="/">サイトへ戻る</a>
  </main>;
}
