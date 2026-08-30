import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// 同じ製品の数値が、商品カードと記事本文で食い違っていた（2026-08-30）。
//
//   焚火台L の板厚      記事2本が 1.5mm、記事1本とカードが 2.5mm
//   アメニティドームM   本文が「定員3人」、同じページのカードが「4〜5人用」
//
// 読者は本文とカードを並べて見るので、その場で矛盾に気づく。
// スノーピーク公式で確認した値に統一した。
//
//   焚火台L (ST-030R)   板厚 1.5mm
//   アメニティドームM   対応人数 3〜5名（快適な目安 3〜4名）
//
// 数値は記事を書き足すたびに増えるので、機械で固定する。

const ROOT = process.cwd();
const read = (f: string) => {
  const raw = JSON.parse(fs.readFileSync(path.join(ROOT, "data", f), "utf8"));
  return Array.isArray(raw) ? raw : raw[Object.keys(raw)[0]];
};

const products: Array<{ id: string; specs?: Record<string, string> }> =
  read("products.json");
const articles: Array<{ slug: string; status: string; content: string }> =
  read("articles.json");
const published = articles.filter((a) => a.status === "published");

const spec = (id: string, key: string) =>
  products.find((p) => p.id === id)?.specs?.[key] ?? "";

/** 公開記事の本文を1行ずつ見る */
function scan(match: (line: string) => boolean): string[] {
  const hits: string[] = [];
  for (const a of published) {
    (a.content ?? "").split("\n").forEach((line, i) => {
      if (match(line)) hits.push(`${a.slug} L${i + 1}: ${line.trim().slice(0, 70)}`);
    });
  }
  return hits;
}

test("焚火台Lの板厚は 1.5mm で統一されている", () => {
  assert.match(spec("fp-003", "素材"), /1\.5\s*mm/, "fp-003 の板厚が違う");
  assert.match(spec("fp-006", "素材"), /1\.5\s*mm/, "fp-006 の板厚が違う");
});

test("記事本文に焚火台Lの板厚 2.5mm が残っていない", () => {
  const hits = scan(
    (l) => /2\.5\s*mm/.test(l) && /焚火台|焚き火台|スノーピーク/.test(l)
  );
  assert.deepEqual(hits, [], `公式は1.5mmです:\n${hits.join("\n")}`);
});

test("アメニティドームMの対応人数がカードと本文で食い違っていない", () => {
  // 公式は3〜5名。「4〜5人用」も「3人」も誤り
  assert.match(
    spec("tent-002", "定員"),
    /3〜5名/,
    "tent-002 の定員が公式（3〜5名）と違う"
  );
  const hits = scan(
    (l) =>
      /アメニティドーム|アメドM/.test(l) &&
      /定員\s*[:：]?\s*3人|定員3人|Mの3人|定員\s*4〜5人用/.test(l)
  );
  assert.deepEqual(
    hits,
    [],
    `公式は3〜5名（快適な目安3〜4名）です:\n${hits.join("\n")}`
  );
});

// 未確認のまま残っている食い違い。メーカー公式を見るまで直せないので、
// 「まだ残っている」ことを記録として残す。解消したらこのテストを消す。
test("未確認の食い違いが記録されている", () => {
  const doc = fs.readFileSync(
    path.join(ROOT, "docs", "product-duplicates-2026-08-28.md"),
    "utf8"
  );
  for (const key of ["未確認", "ツーリングドームST"]) {
    assert.ok(doc.includes(key), `${key} の記録が消えている`);
  }
});
