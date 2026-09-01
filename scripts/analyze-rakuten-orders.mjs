#!/usr/bin/env node
/**
 * 楽天アフィリエイト「注文明細」CSVを読んで、サイトの実力を切り分ける
 *
 * 背景（2026-09-01）: 8月の楽天成果報酬は ¥14,205 で7月比 +31% だった。
 * 好調に見えたが、注文明細をジャンル別に割ったら中身が違った。
 *
 *   スポーツ・アウトドア  ¥3,801（26.8%）… 7月比 −25%
 *   楽天トラベル・GORA    ¥3,591（25.3%）
 *   家電・楽器・美容ほか  ¥6,813（47.9%）
 *
 * 楽天は、読者が記事のリンクを踏んだ後にした**自分の買い物**も計上する。
 * 中古エフェクター・業務用洗剤・ゴルフ場予約が収益の半分を占めていた。
 * 総額だけ見ていると、キャンプ記事が効いているかどうかを取り違える。
 *
 * このスクリプトで分かること:
 *
 *   1. ジャンル別の内訳（サイト由来かどうかの代理指標）
 *   2. products.json のブランド・商品名と一致する注文（より確からしい代理指標）
 *   3. **成果報酬の上限に当たった注文** ← 一番重要
 *   4. 計測IDの有無
 *
 * 3について。料率4%の楽天市場商品は1件 ¥1,000 で頭打ちになる。
 * 7月のコールマン タフスクリーン2ルームエアーは売上 ¥82,665 で、
 * 4%なら ¥3,306 のところ ¥1,000 しか付いていない（実効1.2%）。
 * 高額テントを売っても報酬は増えないので、記事のCTA構成に直結する。
 * ショップ独自料率（10%等）と楽天トラベル（1%）は対象外で満額付く。
 *
 * 4について。69件の注文のうち計測IDが入っていたのは楽天ROOMの1件だけで、
 * サイトのリンクには付いていなかった。付くまでは1と2の推測に頼るしかない。
 * 計測IDが観測できたらこの警告は消える。
 *
 * CSVの取り方:
 *   楽天アフィリエイト → レポート → 注文明細 → 表示期間を選ぶ → ダウンロード
 *
 * 使い方:
 *   npm run report:rakuten -- ~/Downloads/order_1.csv
 *   npm run report:rakuten -- ~/Downloads/order_*.csv   # 複数月。推移も出る
 *   npm run report:rakuten -- order.csv --no-match      # 商品照合を省く
 *   npm run report:rakuten -- --cap-check               # CSV不要。掲載商品を見る
 *
 * --cap-check は注文ではなく products.json を見て、公開記事に載っている
 * 商品のうち何件が天井にかかるかを出す。2026-09-01 時点で 328件中72件。
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();

/** 料率4%の楽天市場商品にかかる、1注文あたりの成果報酬上限 */
const REWARD_CAP = 1000;
/** 上限がかかる料率。ショップ独自料率（4%超）は対象外 */
const CAPPED_RATE = 4;

const args = process.argv.slice(2);
const files = args.filter((a) => !a.startsWith("--"));
const noMatch = args.includes("--no-match");
const capCheck = args.includes("--cap-check");

if (files.length === 0 && !capCheck) {
  console.error(
    "使い方: npm run report:rakuten -- <注文明細CSV...>\n" +
      "        npm run report:rakuten -- --cap-check"
  );
  process.exit(1);
}

// ─── CSV ────────────────────────────────────────────────────────────
//
// 楽天のCSVは先頭にステータス・リンクタイプの凡例が入っていて、
// 本体のヘッダは英語行 `date,rewards,rate,...` から始まる。行数は
// 固定ではないので、この英語行を探す。

/** ダブルクォート内のカンマを壊さずに1行を分解する */
function splitCsvLine(line) {
  const out = [];
  let cur = "";
  let quoted = false;
  for (const ch of line) {
    if (ch === '"') {
      quoted = !quoted;
      continue;
    }
    if (ch === "," && !quoted) {
      out.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  out.push(cur);
  return out;
}

function parse(file) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  const head = lines.findIndex((l) => l.startsWith("date,rewards"));
  if (head < 0) {
    throw new Error(
      `${file} は楽天の注文明細CSVに見えません（date,rewards... の行が無い）`
    );
  }
  // 1行目の `"注文別成果: 2026.08"` を月ラベルに使う
  const label = (lines[0].match(/(\d{4})[.\-/](\d{2})/) ?? []).slice(1).join("-");
  const rows = [];
  for (const line of lines.slice(head + 1)) {
    if (!line.trim()) continue;
    const f = splitCsvLine(line);
    rows.push({
      date: f[0],
      rewards: Number(f[1]) || 0,
      rate: Number(f[2]) || 0,
      amount: Number(f[3]) || 0,
      genre: f[4] ?? "",
      shop: f[5] ?? "",
      item: f[6] ?? "",
      status: f[7] ?? "",
      device: f[9] ?? "",
      measurementId: (f[10] ?? "").trim(),
    });
  }
  return { label: label || path.basename(file), rows };
}

// ─── 掲載商品との照合 ────────────────────────────────────────────────
//
// 計測IDが無い間の代理指標。products.json のブランド名と、商品名から
// 抜いた型番らしい語で突き合わせる。あくまで「サイト由来かもしれない」
// までしか言えない。読者が同じブランドを別記事で見て買った可能性も、
// 逆に取りこぼす可能性もある。

function buildMatcher() {
  const raw = JSON.parse(
    fs.readFileSync(path.join(ROOT, "data", "products.json"), "utf8")
  );
  const products = Array.isArray(raw) ? raw : raw.products;

  const brands = new Set();
  for (const p of products) {
    const b = (p.brand ?? "").trim();
    // 「汎用」は実在ブランドではなく、1〜2文字は誤爆する
    if (b.length >= 3 && b !== "汎用") brands.add(b);
  }
  // 商品名の先頭語（＝ほぼブランド表記ゆれ）も拾う。
  // 「snow peak」「Stanley」のような英語表記がCSV側に出るため
  for (const p of products) {
    const first = (p.name ?? "").split(/[\s　]+/)[0];
    if (first && first.length >= 4 && /^[A-Za-z]/.test(first)) brands.add(first);
  }

  const list = [...brands].sort((a, b) => b.length - a.length);
  return (itemName) => list.find((b) => itemName.toLowerCase().includes(b.toLowerCase())) ?? null;
}

const matchBrand = noMatch || capCheck ? () => null : buildMatcher();

// ─── --cap-check ────────────────────────────────────────────────────
//
// 注文ではなく掲載商品の側を見る。売上が上限÷料率（= ¥25,000）を超える
// 商品は、いくら高くても報酬が ¥1,000 で止まる。高額テントが主力の
// サイトでは、記事のCTA構成そのものの問題になる。

/** 上限に達する売上額。¥1,000 ÷ 4% = ¥25,000 */
const CAP_THRESHOLD = Math.ceil((REWARD_CAP * 100) / CAPPED_RATE);

function capCheckProducts() {
  const readJson = (f) => {
    const raw = JSON.parse(fs.readFileSync(path.join(ROOT, "data", f), "utf8"));
    return Array.isArray(raw) ? raw : raw[Object.keys(raw)[0]];
  };
  const products = readJson("products.json");
  const articles = readJson("articles.json");

  // 下書きは対象外。実際に読者の目に触れる商品だけを見る
  const shown = new Set();
  for (const a of articles) {
    if (a.status !== "published") continue;
    for (const id of a.productIds ?? []) shown.add(id);
    for (const m of (a.content ?? "").matchAll(
      /\{\{(?:product|comparison|ranking):([a-z0-9,\-]+)\}\}/g
    )) {
      for (const id of m[1].split(",")) shown.add(id);
    }
  }
  const published = products.filter((p) => shown.has(p.id));

  console.log(`\n公開記事に載る商品: ${published.length}件`);
  const bands = [
    [0, 5000],
    [5000, 10000],
    [10000, CAP_THRESHOLD],
    [CAP_THRESHOLD, Infinity],
  ];
  for (const [lo, hi] of bands) {
    const n = published.filter((p) => p.price >= lo && p.price < hi).length;
    const label = hi === Infinity ? `${yen(lo)}〜（天井にかかる）` : `${yen(lo)}〜${yen(hi)}`;
    const share = ((n / published.length) * 100).toFixed(1);
    console.log(`  ${label.padEnd(28)} ${String(n).padStart(3)}件  ${share.padStart(5)}%`);
  }

  const over = published
    .filter((p) => p.price >= CAP_THRESHOLD)
    .sort((a, b) => b.price - a.price);
  const lost = (p) => Math.floor((p.price * CAPPED_RATE) / 100) - REWARD_CAP;

  console.log(`\n天井にかかる商品 ${over.length}件（取りこぼしが大きい順）:`);
  for (const p of over) {
    const effective = ((REWARD_CAP / p.price) * 100).toFixed(1);
    console.log(
      `  ${yen(p.price).padStart(10)}  理論${yen(Math.floor((p.price * CAPPED_RATE) / 100)).padStart(8)}` +
        `  差${yen(lost(p)).padStart(8)}  実効${effective.padStart(4)}%` +
        `  ${p.amazonUrl ? "Amazon有" : "Amazon無"}  ${(p.name ?? "").slice(0, 32)}`
    );
  }
  console.log(
    `\n1件ずつ売れたと仮定した取りこぼし合計: ${yen(over.reduce((a, p) => a + Math.max(0, lost(p)), 0))}`
  );
  const noAmazon = over.filter((p) => !p.amazonUrl);
  console.log(
    `Amazonリンクが無いもの: ${noAmazon.length}件` +
      (noAmazon.length ? `\n  ${noAmazon.map((p) => p.id).join("\n  ")}` : "")
  );
  console.log(
    "\n※ Amazon側の上限は未確認。高額品をAmazonへ寄せる前に紹介料率ページで確認すること"
  );
}

// ─── 集計 ────────────────────────────────────────────────────────────

const yen = (n) => `¥${n.toLocaleString()}`;
const sum = (rs) => rs.reduce((a, r) => a + r.rewards, 0);
const amount = (rs) => rs.reduce((a, r) => a + r.amount, 0);

const STATUS = { 0: "未確定", 1: "確定", 2: "破棄" };

if (capCheck) {
  capCheckProducts();
  console.log();
  if (files.length === 0) process.exit(0);
}

let months;
try {
  months = files.map(parse);
} catch (e) {
  console.error(e.message);
  process.exit(1);
}

for (const { label, rows } of months) {
  const total = sum(rows);
  console.log(`\n${"═".repeat(72)}`);
  console.log(
    `${label}   ${rows.length}件 / 成果報酬 ${yen(total)} / 売上 ${yen(amount(rows))}`
  );
  console.log("═".repeat(72));

  const byStatus = {};
  for (const r of rows) {
    const k = STATUS[r.status] ?? r.status;
    byStatus[k] = (byStatus[k] ?? 0) + 1;
  }
  const statusLine = Object.entries(byStatus)
    .map(([k, v]) => `${k} ${v}件`)
    .join(" / ");
  console.log(`\nステータス: ${statusLine}`);
  if (byStatus["未確定"] === rows.length) {
    console.log("  ※ 全件未確定。楽天の確定は約2ヶ月遅れる。承認率はまだ測れない");
  }

  // ジャンル別。楽天トラベル等はジャンル名が空なのでショップ名で立てる
  const genres = new Map();
  for (const r of rows) {
    const key = r.genre || `【${r.shop}】`;
    if (!genres.has(key)) genres.set(key, []);
    genres.get(key).push(r);
  }
  console.log("\nジャンル別:");
  for (const [key, rs] of [...genres].sort((a, b) => sum(b[1]) - sum(a[1]))) {
    const share = total ? ((sum(rs) / total) * 100).toFixed(1) : "0.0";
    console.log(
      `  ${key.padEnd(24)} ${String(rs.length).padStart(3)}件  ` +
        `${yen(sum(rs)).padStart(9)}  ${share.padStart(5)}%`
    );
  }

  if (!noMatch) {
    const hits = rows
      .map((r) => ({ r, brand: matchBrand(r.item) }))
      .filter((x) => x.brand);
    const share = total ? ((sum(hits.map((x) => x.r)) / total) * 100).toFixed(1) : "0.0";
    console.log(
      `\n掲載ブランドと一致した注文: ${hits.length}件 / ` +
        `${yen(sum(hits.map((x) => x.r)))}（全体の${share}%）`
    );
    for (const { r, brand } of hits.sort((a, b) => b.r.rewards - a.r.rewards)) {
      console.log(`  ${yen(r.rewards).padStart(8)}  [${brand}] ${r.item.slice(0, 44)}`);
    }
    console.log("  ※ 計測IDが無いための代理指標。サイト由来と断定はできない");
  }

  // ここが本題
  const capped = rows.filter(
    (r) => r.rewards === REWARD_CAP && Math.floor((r.amount * r.rate) / 100) > REWARD_CAP
  );
  if (capped.length > 0) {
    const lost = capped.reduce(
      (a, r) => a + Math.floor((r.amount * r.rate) / 100) - REWARD_CAP,
      0
    );
    console.log(`\n成果報酬の上限に当たった注文: ${capped.length}件 / 取りこぼし ${yen(lost)}`);
    for (const r of capped.sort((a, b) => b.amount - a.amount)) {
      const theory = Math.floor((r.amount * r.rate) / 100);
      const effective = ((REWARD_CAP / r.amount) * 100).toFixed(1);
      console.log(
        `  売上${yen(r.amount).padStart(10)} @${r.rate}%  ` +
          `理論${yen(theory).padStart(7)} → 実際${yen(REWARD_CAP)}  ` +
          `実効${effective}%  ${r.item.slice(0, 34)}`
      );
    }
  } else {
    console.log(`\n成果報酬の上限に当たった注文: なし`);
  }

  const over = rows.filter((r) => r.rewards > REWARD_CAP);
  if (over.length > 0) {
    console.log(`\n上限を超えて付いた注文（＝対象外の料率）: ${over.length}件`);
    for (const r of over.sort((a, b) => b.rewards - a.rewards)) {
      console.log(
        `  ${yen(r.rewards).padStart(8)} @${r.rate}%  ` +
          `${(r.genre || r.shop).slice(0, 14).padEnd(14)} ${r.item.slice(0, 34)}`
      );
    }
    // 上限がかかるのは料率4%の楽天市場商品だけ、というのが今の理解。
    // 4%ちょうどで¥1,000を超えたものが出たら、その理解が間違っている。
    // 楽天トラベル（1%）等が超えるのは想定どおりなので警告しない
    const contradiction = over.filter((r) => r.rate === CAPPED_RATE);
    if (contradiction.length > 0) {
      console.log(
        `  ※ 料率${CAPPED_RATE}%ちょうどで上限を超えたものが${contradiction.length}件ある。` +
          `上限の条件が想定と違う`
      );
    }
  }

  const withId = rows.filter((r) => r.measurementId);
  console.log(`\n計測IDが入っている注文: ${withId.length}件 / ${rows.length}件`);
  if (withId.length > 0) {
    const ids = new Map();
    for (const r of withId) ids.set(r.measurementId, (ids.get(r.measurementId) ?? 0) + 1);
    for (const [id, n] of ids) console.log(`  ${id}: ${n}件`);
  }
  if (withId.length < rows.length) {
    console.log(
      "  ※ サイトのリンクに計測IDが付いていない。付ければ「サイト由来」と\n" +
        "     「ついで買い」を推測でなく実測で分けられる"
    );
  }
}

// ─── 月をまたいだ推移 ────────────────────────────────────────────────

if (months.length > 1) {
  console.log(`\n${"═".repeat(72)}`);
  console.log("推移");
  console.log("═".repeat(72));
  const key = (r) => r.genre || `【${r.shop}】`;
  const allGenres = new Set();
  for (const { rows } of months) for (const r of rows) allGenres.add(key(r));

  const header = months.map((m) => m.label.padStart(12)).join("");
  console.log(`  ${"ジャンル".padEnd(24)}${header}`);
  const scored = [...allGenres].map((g) => ({
    g,
    rows: months.map(({ rows }) => rows.filter((r) => key(r) === g)),
  }));
  scored.sort((a, b) => sum(b.rows.at(-1)) - sum(a.rows.at(-1)));
  for (const { g, rows } of scored) {
    console.log(`  ${g.padEnd(24)}${rows.map((rs) => yen(sum(rs)).padStart(12)).join("")}`);
  }
  console.log(
    `  ${"合計".padEnd(24)}${months.map((m) => yen(sum(m.rows)).padStart(12)).join("")}`
  );
}

console.log();
