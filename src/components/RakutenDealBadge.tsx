import { getActiveRakutenDeal } from "@/lib/rakutenDeals";

// 楽天の「買い時」バナー。日付から自動判定し、該当日だけ表示される。
// サーバーコンポーネント（記事ページのISR=1hごとに再評価される）。
// Date.now() はサーバーレンダリング時に評価。ISRのため最大1時間のズレは許容範囲。
export default function RakutenDealBadge() {
  // eslint-disable-next-line react-hooks/purity
  const deal = getActiveRakutenDeal(new Date(Date.now()));
  if (!deal) return null;

  return (
    <div className="my-4 flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-4 py-3">
      <span className="text-lg leading-none" aria-hidden>
        🉐
      </span>
      <div className="min-w-0">
        <p className="text-sm font-bold text-red-700">
          {deal.label}
          <span className="ml-1.5 font-normal text-red-600/80">
            — 楽天市場でチェック
          </span>
        </p>
        <p className="mt-0.5 text-xs text-red-800/70">{deal.detail}</p>
      </div>
    </div>
  );
}
