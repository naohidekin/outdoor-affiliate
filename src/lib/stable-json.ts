// data/*.json を「同じ内容なら必ず同じバイト列」で書くための正規化。
//
// 背景: Supabase から書き戻すたびに data/articles.json と data/products.json に
// 未コミット変更が出ていた。中身を1文字も変えていないのに差分になるので、
// git stash pop のたびに衝突し、そのたびに「本当に捨てていいのか」を
// 人が確認していた。1日に3回やった日もある。
//
// 原因は3つ、すべて表記の揺れだった。
//   1. ネストしたオブジェクトのキー順（specs や faqs）が往復で変わる
//      例: {形式, 機能, サイズ, ...} ↔ {形式, サイズ, 消費電力, ...}
//   2. 時刻の表記が変わる
//      例: 2026-08-26T13:28:56.126Z ↔ 2026-08-26T13:28:56.126+00:00
//   3. 末尾改行の有無が書き手ごとに違う
//      （data/categories.json だけ改行が無かった）
//
// 内容が同じなら同じ文字列になるように揃える。意味は一切変えない。

/** 厳密なISO-8601。"2026" のような曖昧な文字列を日付と誤認しないため */
const ISO_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

/**
 * オブジェクトのキーを再帰的に辞書順へ、ISO時刻を Z 表記へ揃える。
 * 配列の順序は意味を持つので保つ。
 */
export function normalizeJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalizeJsonValue);

  if (value !== null && typeof value === "object") {
    const src = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(src).sort()) {
      out[key] = normalizeJsonValue(src[key]);
    }
    return out;
  }

  if (typeof value === "string" && ISO_TIMESTAMP.test(value)) {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return d.toISOString();
  }

  return value;
}

/** data/*.json に書く正規の文字列。末尾改行つき */
export function stableJsonString(data: unknown): string {
  return JSON.stringify(normalizeJsonValue(data), null, 2) + "\n";
}
