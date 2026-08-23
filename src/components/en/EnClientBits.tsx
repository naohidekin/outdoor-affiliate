"use client";

import { useEffect, useRef } from "react";
import {
  trackEnEvent,
  type EnEventName,
  type EnEventPayload,
  type EnPlacement,
} from "@/lib/experiments/snow-peak-igt/analytics";
import { EN_LANG } from "@/lib/experiments/snow-peak-igt/seo";

/**
 * `<html lang>` を英語に合わせる。
 *
 * このサイトはルートレイアウトが1つで `<html lang="ja">` 固定。
 * Next.js で出し分けるにはルートレイアウトを複数に割る必要があり、
 * その場合は現行の app/not-found.tsx が合成できなくなって
 * global-not-found（experimental）が要る。MVPに対して重すぎるので、
 * SSR出力ではラッパー要素に lang を付け、ここで documentElement を補正する。
 *
 * 限界: 初期HTMLの `<html lang>` は ja のまま。JSを実行しないクローラーには
 * ラッパー要素の lang しか見えない。正しく直すならルートレイアウト分割。
 */
export function EnHtmlLang() {
  useEffect(() => {
    const previous = document.documentElement.lang;
    document.documentElement.lang = EN_LANG;
    return () => {
      document.documentElement.lang = previous;
    };
  }, []);
  return null;
}

/**
 * 表示イベントを1回だけ送る。
 * StrictModeの二重実行と、クライアント遷移での再発火を防ぐ。
 */
export function EnTrackView({
  event,
  page,
}: {
  event: EnEventName;
  page: string;
}) {
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    trackEnEvent(event, { page });
  }, [event, page]);
  return null;
}

/**
 * 英語セクションの販売リンク。
 *
 * 日本語側の AffiliateLink を流用しない。あちらは link_url（完全な
 * アフィリエイトURL）と商品名をイベントに載せるが、英語側は
 * 「完全なaffiliate URLを載せない」条件があるため。
 */
export function EnPurchaseLink({
  href,
  merchant,
  market,
  modelId,
  placement,
  affiliate,
  children,
  className,
}: {
  href: string;
  merchant: string;
  market: string;
  modelId: string;
  placement: EnPlacement;
  affiliate: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  function handleClick() {
    const payload: EnEventPayload = {
      merchant,
      market,
      model_id: modelId,
      placement,
    };
    trackEnEvent("affiliate_click", payload);
  }

  return (
    <a
      href={href}
      target="_blank"
      // アフィリエイトでないメーカー直リンクにも sponsored を付けない代わり、
      // nofollow noopener は常に付ける
      rel={
        affiliate
          ? "sponsored nofollow noopener noreferrer"
          : "nofollow noopener noreferrer"
      }
      onClick={handleClick}
      className={className}
    >
      {children}
    </a>
  );
}
