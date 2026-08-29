// src/lib/stable-json.ts と同じ正規化を、スクリプト側（ESM）から使うための版。
//
// 実装を2箇所に持つのは本意ではないが、Next.js 側は TypeScript、scripts 側は
// .mjs を直接 node で実行するため分けている（src/lib/x-agent-utils.mjs 等と
// 同じ構成）。ズレると「アプリが書いた形」と「スクリプトが書いた形」が
// 食い違い、消したはずの差分ノイズが復活する。
// tests/stable-json.test.ts が両者の出力の一致を検証しているので、
// 片方だけ直すとテストが落ちる。

/** 厳密なISO-8601。"2026" のような曖昧な文字列を日付と誤認しないため */
const ISO_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export function normalizeJsonValue(value) {
  if (Array.isArray(value)) return value.map(normalizeJsonValue);

  if (value !== null && typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value).sort()) {
      out[key] = normalizeJsonValue(value[key]);
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
export function stableJsonString(data) {
  return JSON.stringify(normalizeJsonValue(data), null, 2) + "\n";
}

// ─── トップレベルの並び順 ─────────────────────────────
// 詳細は stable-json.ts の同じ箇所のコメントを参照。
// レコード集合の3ファイルだけ、安定したキーで並べる。
// affiliate-clicks.json のようなログはソートすると読めなくなるので除外する。
const SORTED_DATA_FILES = new Set([
  "articles.json",
  "products.json",
  "categories.json",
]);

function sortKeyOf(record) {
  if (record === null || typeof record !== "object") return null;
  for (const key of ["id", "slug"]) {
    if (typeof record[key] === "string" && record[key]) return record[key];
  }
  return null;
}

export function sortTopLevelRecords(filename, data) {
  if (!SORTED_DATA_FILES.has(filename)) return data;
  if (!Array.isArray(data)) return data;
  const keys = data.map(sortKeyOf);
  if (keys.some((k) => k === null)) return data;
  if (new Set(keys).size !== keys.length) return data;
  return data
    .map((record, i) => ({ record, key: keys[i] }))
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
    .map((x) => x.record);
}

/** data/<filename> に書く正規の文字列。並び順まで含めて安定させる */
export function stableDataFileString(filename, data) {
  return stableJsonString(sortTopLevelRecords(filename, data));
}
