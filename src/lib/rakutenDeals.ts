// 楽天の「買い時」を日付から自動判定する。
// 個別商品のポイント倍率は変動が激しく誤表示リスクがあるため扱わない。
// 「5と0のつく日」は完全に日付だけで決まるので自動・常時正確。
// スーパーSALE/お買い物マラソンは開催日を SALE_WINDOWS に入れると期間中だけ自動表示。

export type RakutenDeal = {
  kind: "sale" | "marathon" | "day5and0";
  label: string; // ボタン近くに出す短い訴求
  detail: string; // 補足（要エントリー等の注意含む）
};

// 楽天の大型セール期間。楽天公式の告知に合わせて年数回ここを更新するだけ。
// 形式: { start: "YYYY-MM-DD", end: "YYYY-MM-DD", kind, label, detail }
// （日付は日本時間。end はその日いっぱい有効）
export const SALE_WINDOWS: Array<{
  start: string;
  end: string;
  kind: "sale" | "marathon";
  label: string;
  detail: string;
}> = [
  // 例（実際の開催が告知されたらコメントを外して日付を合わせる）:
  // { start: "2026-09-04", end: "2026-09-11", kind: "sale", label: "楽天スーパーSALE開催中", detail: "買い回りでポイント最大+9倍（要エントリー）。詳細は楽天市場でご確認ください。" },
];

// JSTの「今日」を YYYY-MM-DD と日(1-31)で返す。
// 引数 now を受け取れるようにしてテスト・SSRのISR再評価に対応。
function jstParts(now: Date): { ymd: string; day: number } {
  // UTC+9
  const jst = new Date(now.getTime() + 9 * 3600 * 1000);
  const y = jst.getUTCFullYear();
  const m = jst.getUTCMonth() + 1;
  const d = jst.getUTCDate();
  const ymd = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  return { ymd, day: d };
}

/**
 * 今アクティブな楽天の買い時を1つ返す（無ければ null）。
 * 優先度: 大型セール > お買い物マラソン > 5と0のつく日
 */
export function getActiveRakutenDeal(now: Date): RakutenDeal | null {
  const { ymd, day } = jstParts(now);

  // 1. 設定済みのセール期間（大型優先）
  const inWindow = SALE_WINDOWS
    .filter((w) => ymd >= w.start && ymd <= w.end)
    .sort((a, b) => (a.kind === "sale" ? -1 : 1))[0];
  if (inWindow) {
    return { kind: inWindow.kind, label: inWindow.label, detail: inWindow.detail };
  }

  // 2. 5と0のつく日（5,10,15,20,25,30日）＝楽天カードでポイントアップ
  if (day % 5 === 0) {
    return {
      kind: "day5and0",
      label: "今日は5と0のつく日",
      detail:
        "楽天カードのご利用でポイントがお得になる日です（要エントリー）。まとめ買いのタイミングにおすすめ。",
    };
  }

  return null;
}
