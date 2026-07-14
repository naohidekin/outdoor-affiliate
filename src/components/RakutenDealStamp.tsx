"use client";

import { useEffect, useState } from "react";
import { getActiveRakutenDeal, RakutenDeal } from "@/lib/rakutenDeals";

// 商品カードに押す「ハンコ」風スタンプ。楽天の買い時（5と0のつく日・セール期間）だけ
// 自動で現れる。日付判定はクライアント側マウント後に行う（SSRとのズレ・hydration差分を回避）。
export default function RakutenDealStamp() {
  const [deal, setDeal] = useState<RakutenDeal | null>(null);

  useEffect(() => {
    setDeal(getActiveRakutenDeal(new Date()));
  }, []);

  if (!deal) return null;

  const [main, sub] =
    deal.kind === "sale"
      ? ["SALE", "開催中"]
      : deal.kind === "marathon"
        ? ["マラソン", "開催中"]
        : ["5と0の日", "ポイントUP"];

  return (
    <div className="rakuten-stamp" aria-hidden>
      <span className="rakuten-stamp-top">楽天</span>
      <span className="rakuten-stamp-main">{main}</span>
      <span className="rakuten-stamp-sub">{sub}</span>
    </div>
  );
}
