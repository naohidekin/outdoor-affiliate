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

test("アメニティドームMのスペックが公式と一致する", () => {
  // スノーピーク公式 SDE-001RH
  assert.match(spec("tent-002", "定員"), /3〜5名/, "定員が公式と違う");
  assert.match(spec("tent-002", "重量"), /8\s*kg/, "重量が公式（8kg）と違う");
  assert.match(spec("tent-002", "収納サイズ"), /74×22×25/, "収納サイズが違う");
});

/**
 * アメニティドームMのスペックを本文に書いている記事。
 * 行単位で「アメニティドーム」を含むかを見る方法では拾えなかった。
 * 表の行が `| 定員 | 4〜5人用 |` の形で、製品名を含まないため
 * （2026-08-30に実際に取りこぼした）。記事単位で見る。
 */
const AMENITY_DOME_M_ARTICLES = [
  "tent-setup-tips-spring",
  "compact-tent-ranking",
  "amenity-dome-vs-tough-wide-dome",
  "amenity-dome-vs-landnest-dome",
];

test("アメニティドームMの記事に古い数値が残っていない", () => {
  const WRONG: Array<[RegExp, string]> = [
    [/4〜5人用|4～5人用/, "定員は3〜5名（快適な目安3〜4名）"],
    [/定員\s*[|｜]?\s*3人|定員3人|Mの3人/, "定員は3〜5名"],
    [/5\.2\s*kg/, "重量は8kg"],
    [/62×22/, "収納サイズは74×22×25(h)cm"],
  ];
  const hits: string[] = [];
  for (const slug of AMENITY_DOME_M_ARTICLES) {
    const a = published.find((x) => x.slug === slug);
    assert.ok(a, `${slug} が公開記事に無い（削除された？）`);
    (a!.content ?? "").split("\n").forEach((line, i) => {
      for (const [re, correct] of WRONG) {
        if (re.test(line))
          hits.push(`${slug} L${i + 1}（${correct}）: ${line.trim().slice(0, 60)}`);
      }
    });
  }
  assert.deepEqual(hits, [], `古い数値が残っています:\n${hits.join("\n")}`);
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

// ─── シリーズ内の大小逆転 ───────────────────────────────
//
// 2026-08-30、スペックの誤りを機械的に洗おうとして失敗した記録。
//
// 最初に試したのは「別製品と重量が同値なら混入を疑う」という検査だった。
// アメニティドームMの 5.2kg が別製品からの混入だったので筋は良さそうに
// 見えたが、実際には小数つき重量を持つ108件が76通りの値に収まるため、
// 一致は起きて当たり前で、20通りが重複していた。32件を「疑わしい」と
// 出したが中身はほぼ雑音。耐水圧の1500/2000mm一致も業界標準値なので同じ。
//
// 一方、シリーズ内の大小逆転（Sのほうが M より高い・重い）は数が少なく、
// 出たものは実際に怪しい。こちらを残す。

test("同シリーズでサイズと価格・重量が逆転していない", () => {
  const RANK: Record<string, number> = { S: 1, M: 2, L: 3, XL: 4 };
  const kg = (v?: string) => {
    const m = (v ?? "").match(/([\d.]+)\s*kg/);
    return m ? parseFloat(m[1]) : null;
  };
  type Item = { p: (typeof products)[number]; rank: number; sz: string };
  const series = new Map<string, Item[]>();
  for (const p of products as Array<{
    id: string; name: string; brand?: string; price?: number;
    specs?: Record<string, string>;
  }>) {
    const m = (p.name ?? "").match(/^(.*?)\s*(S|M|L|XL)$/);
    if (!m || !p.brand) continue;
    const key = `${p.brand}|${m[1].trim()}`;
    if (!series.has(key)) series.set(key, []);
    series.get(key)!.push({ p, rank: RANK[m[2]], sz: m[2] });
  }

  const bad: string[] = [];
  for (const [key, items] of series) {
    for (const s of items)
      for (const l of items) {
        // 同じサイズ記号どうしは重複レコードなので対象外
        if (s.rank >= l.rank) continue;
        const sp = (s.p as { price?: number }).price;
        const lp = (l.p as { price?: number }).price;
        if (sp && lp && sp > lp)
          bad.push(`${key}: ${s.sz}(${s.p.id}) ¥${sp} > ${l.sz}(${l.p.id}) ¥${lp}`);
        const ws = kg(s.p.specs?.["重量"]);
        const wl = kg(l.p.specs?.["重量"]);
        if (ws && wl && ws > wl)
          bad.push(`${key}: ${s.sz}(${s.p.id}) ${ws}kg > ${l.sz}(${l.p.id}) ${wl}kg`);
      }
  }
  // 未確認の逆転。メーカー公式はこの作業環境から到達できないため直せない。
  // 確認できたら値を直してここから消す。減らすためのリスト。
  //
  // アメニティドームS の ¥44,000 は、重複レコード tent-sp-amenity-dome-m の
  // 価格と同じ。S の室内高 120cm も、その重複レコードが持っていた値と同じ。
  // 値が混ざった痕跡がここにも出ている。
  const KNOWN = ["スノーピーク|スノーピーク アメニティドーム: S(tent-duo-002)"];
  const unknown = bad.filter((b) => !KNOWN.some((k) => b.startsWith(k)));
  assert.deepEqual(
    unknown,
    [],
    `小さいモデルのほうが高い/重いのは不自然です。メーカー公式で確認してください:\n${unknown.join("\n")}`
  );

  const fixed = KNOWN.filter((k) => !bad.some((b) => b.startsWith(k)));
  if (fixed.length > 0)
    console.log(`  [注意] 逆転が解消したので KNOWN から消せます: ${fixed.join(", ")}`);
});
