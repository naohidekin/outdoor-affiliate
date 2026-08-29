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

// ─── トップレベルの並び順 ─────────────────────────────
//
// キー順と時刻を揃えたあとも、data/articles.json に3,300行の差分が出続けた。
// 調べたら配列の並び順だった。Supabaseから読み直すたびに、記事127本のうち
// 88本、商品392件のうち366件が位置を変えていた。行数は動くのに中身は同じ。
//
// 記事や商品の一覧は「レコードの集合」で、並び順に意味がない。一方
// productIds や faqs は順序に意味があるので、配列を一律にソートはできない。
// トップレベルの一覧だけを、安定したキーで並べる。
//
// 対象はレコード集合の3ファイルに限る。affiliate-clicks.json のような
// ログはソートすると読めなくなるため、明示的に列挙する。
const SORTED_DATA_FILES = new Set([
  "articles.json",
  "products.json",
  "categories.json",
]);

function sortKeyOf(record: unknown): string | null {
  if (record === null || typeof record !== "object") return null;
  const r = record as Record<string, unknown>;
  for (const key of ["id", "slug"]) {
    if (typeof r[key] === "string" && r[key]) return r[key] as string;
  }
  return null;
}

/**
 * ファイル名に応じて、トップレベルのレコード一覧を安定した順に並べる。
 * 並べ替えられない形（キーが無い・配列でない）なら、そのまま返す。
 */
export function sortTopLevelRecords(filename: string, data: unknown): unknown {
  if (!SORTED_DATA_FILES.has(filename)) return data;
  if (!Array.isArray(data)) return data;
  const keys = data.map(sortKeyOf);
  if (keys.some((k) => k === null)) return data; // 1件でも欠けたら触らない
  if (new Set(keys).size !== keys.length) return data; // 重複キーがあれば触らない
  return data
    .map((record, i) => ({ record, key: keys[i] as string }))
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
    .map((x) => x.record);
}

/** data/<filename> に書く正規の文字列。並び順まで含めて安定させる */
export function stableDataFileString(filename: string, data: unknown): string {
  return stableJsonString(sortTopLevelRecords(filename, data));
}
