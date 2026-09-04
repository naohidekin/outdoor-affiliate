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

// 2026-08-31、ネットワークポリシーが広がってメーカー公式に到達できるように
// なった。上の「未確認」だった3件は公式で確認して解消したので、その記録が
// 台帳に残っていることを確認する。
test("公式で確認した記録が台帳に残っている", () => {
  const doc = fs.readFileSync(
    path.join(ROOT, "docs", "product-duplicates-2026-08-28.md"),
    "utf8"
  );
  for (const key of ["2026-08-31", "ツーリングドームST", "SDE-001RH"]) {
    assert.ok(doc.includes(key), `${key} の記録が消えている`);
  }
});

// ─── 2026-08-31 にメーカー公式で確認した値 ─────────────
//
// 出典は各社の公式サイトと取扱説明書PDF。
//   アメニティドーム S/M/L  SDE-002 / SDE-001RH / SDE-003RD 取説のスペック図
//   ランドネストドームM     SDE-260 取説のスペック図
//   ツーリングドームST      コールマン公式 商品ページ（型番2000038141）
//   ファイアグリル          ユニフレーム公式 No.683040
//   54QTスチールベルトクーラー / タフスクリーン2ルームエアー MDX+  コールマン公式
//
// 誤っていた値の多くは「別サイズの製品の数値」が混ざったもので、
// とくに室内高120cm（本当はSの値）はMの記事3本に広がっていた。

test("アメニティドームのサイズが公式と一致する", () => {
  // M（SDE-001RH）室内265×265×150(h) / フライ全長505・全幅280
  assert.match(spec("tent-002", "サイズ（展開時）"), /505×280×150/);
  assert.match(spec("tent-002", "インナーサイズ"), /265×265×150/);
  // S（SDE-002）室内220×150×120(h)
  assert.match(spec("tent-duo-002", "インナーサイズ"), /220×150×120/);
  assert.match(spec("tent-duo-002", "収容人数"), /2〜3名/);
  // L（SDE-003RD）室内295×295×165(h) / 重量9.8kg / 4〜5名
  assert.match(spec("tent-sp-amenity-dome-l", "定員"), /4〜5名/);
  assert.match(spec("tent-sp-amenity-dome-l", "重量"), /9\.8\s*kg/);
  assert.match(spec("tent-sp-amenity-dome-l", "インナーサイズ"), /295×295×165/);
});

test("ツーリングドームSTのスペックが公式と一致する", () => {
  for (const id of ["tent-001", "tent-solo-003"]) {
    const all = JSON.stringify(products.find((p) => p.id === id)?.specs ?? {});
    assert.match(all, /210×120×100/, `${id} の展開サイズが公式と違う`);
    assert.match(all, /φ19×49/, `${id} の収納サイズが公式と違う`);
    assert.match(all, /約4\s*kg/, `${id} の重量が公式（約4kg）と違う`);
    // フロアは2,000mmではなく約1,500mm
    assert.doesNotMatch(all, /フロア[^」]{0,6}2[,]?000/, `${id} のフロア耐水圧が違う`);
  }
});

test("ランドネストドームMのスペックが公式と一致する", () => {
  assert.match(spec("tent-sp-landnest-dome-m", "室内高"), /170\s*cm/);
  assert.match(spec("tent-sp-landnest-dome-m", "重量"), /8\.7\s*kg/);
});

test("記事本文に、別サイズから混入した古い数値が残っていない", () => {
  // アメニティドームMの室内高120cm は本当はSの値。定員5〜6人用はLの誤り。
  const WRONG: Array<[string[], RegExp, string]> = [
    [
      ["amenity-dome-vs-tough-wide-dome", "amenity-dome-vs-landnest-dome", "compact-tent-ranking"],
      /室内高[^。|]{0,8}120\s*cm|120\s*cm[^。|]{0,10}座るのがやっと/,
      "アメニティドームMの室内高は150cm（120cmはSの値）",
    ],
    [
      ["snow-peak-amenity-dome-l-10year-review"],
      /5〜6人|5～6人/,
      "アメニティドームLの定員は4〜5名",
    ],
    [
      ["tent-setup-tips-spring", "compact-tent-ranking"],
      /200×120×100|56×14\s*cm/,
      "ツーリングドームSTは210×120×100(h)cm / 収納 約φ19×49cm",
    ],
    [
      ["amenity-dome-vs-tough-wide-dome"],
      /フロア[^|]{0,8}3[,]?000/,
      "アメニティドームMのフロア耐水圧は1,800mm",
    ],
  ];
  const hits: string[] = [];
  for (const [slugs, re, correct] of WRONG) {
    for (const slug of slugs) {
      const a = published.find((x) => x.slug === slug);
      if (!a) continue;
      (a.content ?? "").split("\n").forEach((line, i) => {
        if (re.test(line))
          hits.push(`${slug} L${i + 1}（${correct}）: ${line.trim().slice(0, 60)}`);
      });
    }
  }
  assert.deepEqual(hits, [], `別サイズの数値が混ざっています:\n${hits.join("\n")}`);
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

// ─── 2026-08-31 第2陣：別製品の数値がまるごと入っていた3件 ───────
//
// 公式カタログを丸ごと取得して突き合わせた結果。いちばん重かったのは
// 「別カテゴリの製品の数値が入っている」型で、内部の整合性検査では
// 絶対に見つからない。値を戻さないためにここで固定する。

test("別製品の数値が混ざっていた商品が公式値のままである", () => {
  // ユニフレーム US-D II：CB缶の卓上バーナー。62gのOD缶ULバーナーではない
  assert.match(spec("burner-s-008", "重量"), /880\s*g/, "US-D II は約880g");
  assert.match(spec("burner-s-008", "対応ガス"), /CB缶/, "US-D II は CB缶");
  // ユニフレーム fan5DX：5点セットで総重量約3kg
  assert.match(spec("cooker-003", "重量"), /3\s*kg/, "fan5DX は総重量約3kg");
  // コールマン ロードトリップグリル：最高約5,000kcal/h
  assert.doesNotMatch(spec("burner-m-005", "火力"), /11[,]?000/, "火力は約5,000kcal/h");
  // ユニフレーム ツインバーナーUS-1900
  assert.match(spec("burner-m-004", "重量"), /3\.9\s*kg/, "US-1900 は約3.9kg");
  // スノーピーク エントリーIGT：現行CK-080Rは5.4kg（旧CK-080が6.5kg）
  assert.match(spec("table-003", "重量"), /5\.4\s*kg/, "エントリーIGT は約5.4kg");
  // ユニフレーム 焚き火テーブル
  assert.match(spec("table-001", "重量"), /2\.3\s*kg/, "焚き火テーブルは約2.3kg");
  // スノーピーク ギガパワーランタン天 / チタントレック900
  assert.match(spec("gas-lantern-001", "重量"), /125\s*g/, "天オートは125g");
  assert.match(spec("cooker-004", "重量"), /175\s*g/, "チタントレック900は175g");
});

test("旧ランドロックのフレームをスチールと書いていない", () => {
  // 公式TP-671R の素材欄は「フレーム／A6061」。旧もアルミで、錆の問題は無い
  const hits = scan((l) => /ランドロック/.test(l) && /スチール(ポール|フレーム|製)/.test(l));
  assert.deepEqual(hits, [], `旧ランドロックもA6061アルミです:\n${hits.join("\n")}`);
});

// ─── 2026-09-04 アメニティドームの世代交代 ─────────────────
//
// スノーピークがアメニティドームS/M/Lを終了し、アメニティドーム2（SD-020・
// 2名用）／3（SD-030・3名用）に切り替えた。公式では旧S/M/Lとも在庫切れの
// セール品のみ。旧Lに相当する後継は無い。
// 掲載記事5本の主役を後継モデルに差し替えたので、戻らないよう固定する。

test("アメニティドーム2/3が公式値で登録されている", () => {
  // SD-020 / SD-030 取扱説明書 p.17 のスペック図
  assert.match(spec("tent-sp-amenity-dome-2", "型番"), /SD-020/);
  assert.match(spec("tent-sp-amenity-dome-2", "対応人数"), /2名/);
  assert.match(spec("tent-sp-amenity-dome-2", "サイズ（展開時）"), /390×240×130/);
  assert.match(spec("tent-sp-amenity-dome-3", "型番"), /SD-030/);
  assert.match(spec("tent-sp-amenity-dome-3", "対応人数"), /3名/);
  assert.match(spec("tent-sp-amenity-dome-3", "サイズ（展開時）"), /515×280×165/);
  // 旧Mと同じインナー寸法。ここが「3が旧Mの後継」の根拠
  assert.match(spec("tent-sp-amenity-dome-3", "インナーサイズ"), /265×265/);
  assert.match(spec("tent-002", "インナーサイズ"), /265×265/);
});

test("アメニティドームの記事が旧M（tent-002）を主役に戻していない", () => {
  const SWITCHED = [
    "compact-tent-ranking",
    "tent-setup-tips-spring",
    "amenity-dome-vs-tough-wide-dome",
    "amenity-dome-vs-landnest-dome",
  ];
  const withIds: Array<{ slug: string; status: string; content: string; productIds?: string[] }> =
    read("articles.json");
  const bad: string[] = [];
  for (const slug of SWITCHED) {
    const a = withIds.find((x) => x.slug === slug);
    assert.ok(a, `${slug} が消えている`);
    if ((a!.productIds ?? []).includes("tent-002"))
      bad.push(`${slug}: productIds に tent-002 が戻っている`);
    if (/\{\{(?:product|comparison):[^}]*tent-002[,}]/.test(a!.content ?? ""))
      bad.push(`${slug}: 本文の商品タグが tent-002 を指している`);
  }
  assert.deepEqual(bad, [], `後継（tent-sp-amenity-dome-3）に差し替え済みです:\n${bad.join("\n")}`);
});

test("世代交代の注記が各記事に残っている", () => {
  const NEED = [
    "compact-tent-ranking",
    "amenity-dome-vs-tough-wide-dome",
    "amenity-dome-vs-landnest-dome",
    "snow-peak-amenity-dome-l-10year-review",
  ];
  const missing = NEED.filter((slug) => {
    const a = published.find((x) => x.slug === slug);
    return !a || !/アメニティドーム\s?[23]|世代交代/.test(a.content ?? "");
  });
  assert.deepEqual(missing, [], `後継モデルへの言及が消えています: ${missing.join(", ")}`);
});

// ─── 2026-09-04 実在しない商品を消した ─────────────────────
//
// 「スノーピーク テーブルドライネット UG-370 ¥5,500」は実在しなかった。
// 記事のCTAリンクが item.rakuten.co.jp/styl-us/ug370/ を指していて、その中身は
// UGGのムートンブーツ。ショップの商品コードがたまたま ug370 だったところから
// 品番「UG-370」が拾われ、その周りに商品が組み立てられたとみられる。
//
// 裏取り: スノーピーク公式カタログ2,229件・楽天公式ショップ(404)・楽天全体検索・
// Amazon検索のいずれにも該当なし。品番CS-370は実在するが「ピッツ トング」。
//
// 自動追加のパイプラインが同じ経路でまた作る可能性があるので、機械で止める。

test("実在しなかったドライネットが復活していない", () => {
  const gone = products.find((p) => p.id === "dry-net-snowpeak");
  assert.equal(gone, undefined, "dry-net-snowpeak は実在しない商品です");

  const hits = scan((l) => /テーブルドライネット/.test(l));
  assert.deepEqual(hits, [], `スノーピークにドライネットはありません:\n${hits.join("\n")}`);
});

test("UGGのブーツにリンクしている記事が無い", () => {
  // styl-us/ug370 は「UGG クラシックウルトラミニ」。ドライネットではない
  const hits = scan((l) => /styl-us\/ug370/.test(l));
  assert.deepEqual(hits, [], `リンク先がムートンブーツです:\n${hits.join("\n")}`);
});

test("ドライネット記事の件数表記と実際の掲載数が合っている", () => {
  const withIds: Array<{ slug: string; content: string; productIds?: string[] }> =
    read("articles.json");
  const a = withIds.find((x) => x.slug === "dry-net-ranking");
  assert.ok(a, "dry-net-ranking が消えている");
  const ranked = (a!.content.match(/^### \d+位:/gm) ?? []).length;
  assert.equal(ranked, 4, "ランキングの項目数が変わっています");
  assert.ok(
    a!.content.includes("おすすめドライネット4選"),
    "見出しの件数が実際の掲載数と合っていません"
  );
  assert.equal((a!.productIds ?? []).length, 4, "productIds の数が合っていません");
});
