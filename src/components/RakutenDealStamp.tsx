"use client";

import { useEffect, useState } from "react";
import { getActiveRakutenDeal, RakutenDeal } from "@/lib/rakutenDeals";

// 商品写真や商品名に重ならない、インラインのセール案内。対象日だけ
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
    <div className="rakuten-deal-note">
      <span className="font-medium">楽天</span>
      <span>{main} · {sub}</span>
    </div>
  );
}
