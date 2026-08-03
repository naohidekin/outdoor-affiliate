#!/usr/bin/env node
/**
 * 商品データ健全性監査
 *
 * 背景（2026-08-01）: シェラカップ記事に実在しない商品
 * 「BUNDOK シェラカップ 600ml BD-190」が5位で紹介されていた
 * （BD-190はピクニックテーブルセットの型番。容量も重量も架空）。
 * 記事生成時のスペック捏造とみられ、同種の問題が他にもある可能性があるため、
 * 外部APIに頼らず検出できる矛盾を機械的に洗い出す。
 *
 * 使い方:
 *   node scripts/audit-product-data.mjs          # 全チェック
 *   node scripts/audit-product-data.mjs --json   # JSON出力（他ツール連携用）
 *
 * 検出する問題:
 *  1. 重複登録   同一商品が複数IDで登録されている（記事ごとに価格が食い違う原因）
 *  2. 価格矛盾   重複商品間で価格が10%以上ずれている
 *  3. 型番衝突   同じ型番が別商品に割り当てられている
 *  4. 記事矛盾   記事本文の価格表記とproducts.jsonの価格がずれている
 *               （合計額・差額・ふるさと納税の自己負担などは除外するが、
 *                文脈依存のため最終判断は目視で行うこと）
 *  5. 欠損       価格0 / 画像なし / カテゴリなし
 *  6. 孤立       どの公開記事からも参照されていない
 */
import fs from "node:fs";

const JSON_OUT = process.argv.includes("--json");
const products = JSON.parse(fs.readFileSync("data/products.json", "utf8"));
const articles = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
const published = articles.filter((a) => a.status === "published");
const byId = new Map(products.map((p) => [p.id, p]));

const findings = [];
const add = (type, severity, detail) => findings.push({ type, severity, ...detail });

// 商品名の正規化。表記ゆれ（空白・記号・全角）を吸収して同一商品を見つける
const norm = (s) =>
  (s || "")
    .replace(/[\s　・（）()【】[\]/｜|]/g, "")
    .replace(/株式会社/g, "")
    .toLowerCase();

const usedIn = (pid) =>
  published
    .filter((a) => (a.productIds || []).includes(pid) || a.content.includes(pid))
    .map((a) => a.slug);

// ── 1-2. 重複登録と価格矛盾 ───────────────────────────
const groups = new Map();
for (const p of products) {
  const key = norm(p.name).slice(0, 24);
  if (!key) continue;
  if (!groups.has(key)) groups.set(key, []);
  groups.get(key).push(p);
}
for (const [, list] of groups) {
  if (list.length < 2) continue;
  const prices = list.map((p) => p.price || 0).filter((v) => v > 0);
  const spread =
    prices.length > 1 ? (Math.max(...prices) - Math.min(...prices)) / Math.max(...prices) : 0;
  const entries = list.map((p) => ({
    id: p.id,
    price: p.price || 0,
    categoryId: p.categoryId || "",
    articles: usedIn(p.id),
  }));
  const liveCount = entries.filter((e) => e.articles.length > 0).length;
  add("重複登録", liveCount > 1 ? "high" : "medium", {
    name: list[0].name,
    entries,
    note:
      liveCount > 1
        ? "両方が公開記事で使われています。記事ごとに別価格が表示されます"
        : "片方は未使用。統合して削除できます",
  });
  if (spread >= 0.1) {
    add("価格矛盾", "high", {
      name: list[0].name,
      detail: entries.map((e) => `${e.id}=¥${e.price.toLocaleString()}`).join(" / "),
      note: `価格差 ${Math.round(spread * 100)}%`,
    });
  }
}

// ── 3. 型番衝突 ───────────────────────────────────
const modelsOf = (name) =>
  new Set(
    (name.match(/[A-Za-z]{1,6}-[A-Za-z0-9]{2,10}/g) || []).map((m) =>
      m.toUpperCase().replace(/-/g, "")
    )
  );
const byModel = new Map();
for (const p of products) {
  for (const m of modelsOf(p.name)) {
    if (!byModel.has(m)) byModel.set(m, []);
    byModel.get(m).push(p);
  }
}
for (const [model, list] of byModel) {
  if (list.length < 2) continue;
  // 同一商品の重複は 1. で報告済み。別商品に同じ型番が付いている場合だけ出す
  const distinct = new Set(list.map((p) => norm(p.name).slice(0, 24)));
  if (distinct.size > 1) {
    add("型番衝突", "high", {
      name: model,
      detail: list.map((p) => `${p.id}(${p.name.slice(0, 24)})`).join(" / "),
      note: "同じ型番が別商品に付いています。どちらかが誤りです",
    });
  }
}

// ── 4. 記事本文の価格表記との矛盾 ─────────────────────
// 商品名の先頭語（ブランド名）で探すと、同じブランドの別商品が並ぶ記事で
// 隣のセクションの価格を拾ってしまう（2026-08-01: ペグハンマーPRO.Cの
// 検査でPRO.Sの5,280円を拾い、正しい記事を誤検出した）。
// {{product:ID}} タグから次の見出しまでを「その商品の記述範囲」とみなし、
// その中の価格表記だけを突き合わせる
for (const a of published) {
  for (const m of a.content.matchAll(/\{\{product:([^}]+)\}\}/g)) {
    const p = byId.get(m[1].trim());
    if (!p || !p.price) continue;
    // タグ位置から次の見出し（##/###）までがこの商品のセクション
    const rest = a.content.slice(m.index + m[0].length);
    const nextHeading = rest.search(/\n#{2,3} /);
    const section = nextHeading === -1 ? rest : rest.slice(0, nextHeading);

    // 「約9,700〜11,880円」のような幅表記が本文では主流なので、レンジとして扱う。
    // 単一値だけ見ると幅の下限を拾って毎回誤検出になる（2026-08-03に7件発生）
    const candidates = [];
    for (const pm of section.matchAll(
      /(?:約)?([0-9,]{3,9})\s*(?:[〜~～]\s*([0-9,]{3,9})\s*)?円/g
    )) {
      const lo = parseInt(pm[1].replace(/,/g, ""), 10);
      const hi = pm[2] ? parseInt(pm[2].replace(/,/g, ""), 10) : lo;
      if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo < 100) continue;
      // レンジ内なら一致とみなす。外れている場合だけ近い側の端との差で判定する
      const gap = p.price < lo ? lo - p.price : p.price > hi ? p.price - hi : 0;
      // 単価ではない金額（合計・差額・年間コスト・定価など）を除外する。
      // 前後どちらに現れるかで語が違うので窓を分ける。まとめて広く見ると
      // 「249,700円は10年で1泊あたり…」の本体価格まで落ちてしまう
      const before = section.slice(Math.max(0, pm.index - 40), pm.index);
      const after = section.slice(pm.index + pm[0].length, pm.index + pm[0].length + 14);
      const excluded =
        /台分|合計|総額|自己負担|納税|控除|セット価格|セットで|希望小売|定価|年間|追加で|別売り?で|込みで/.test(
          before
        ) || /の差額|の差|ほど高|ほど安|程度高|程度安|上乗せ|割引|値上|分安|分高|で割る|お得|節約/.test(after);
      candidates.push({
        diff: gap / p.price,
        excluded,
        written: pm[2] ? `${pm[1]}〜${pm[2]}円` : `${pm[1]}円`,
      });
    }
    // セクション内のどれか1つでもデータ価格と整合していれば矛盾なしとみなす。
    // 除外語で先頭をスキップしたあと遠くの無関係な金額を拾う事故を防ぐため、
    // 「最初の1件だけ見る」ではなく「全候補中の最良一致」で判定する
    const usable = candidates.filter((c) => !c.excluded);
    if (usable.length > 0) {
      const best = usable.reduce((a, b) => (a.diff <= b.diff ? a : b));
      if (best.diff >= 0.2) {
        add("記事矛盾", "medium", {
          name: p.name,
          detail: `${a.slug}: 本文「${best.written}」 vs データ ¥${p.price.toLocaleString()}`,
          note: `差 ${Math.round(best.diff * 100)}%`,
        });
      }
    }
  }
}

// ── 7. リンク先の不整合 ──────────────────────────
// 2026-08-03: EcoFlow WAVE 2 のアフィリエイトリンクが WAVE 3 の商品ページを
// 指していた（WAVE 3 の商品と同一URL）。記事はWAVE 2を紹介しているのに
// クリックすると別モデルに飛ぶ。世代違いは名前だけでは気づけないので機械で拾う
function itemUrlOf(p) {
  const raw = p.affiliateUrl || "";
  if (!raw) return "";
  if (raw.includes("item.rakuten.co.jp") && !raw.includes("hb.afl.")) return raw;
  try {
    const pc = new URL(raw).searchParams.get("pc");
    if (!pc) return "";
    try {
      return decodeURIComponent(pc);
    } catch {
      return pc; // エンコードが壊れている商品が数件ある
    }
  } catch {
    return "";
  }
}
const urlOwners = new Map();
for (const p of products) {
  const url = itemUrlOf(p);
  const m = /item\.rakuten\.co\.jp\/([^/?#]+)\/([^/?#]+)/.exec(url);
  if (!m) continue;
  const path = `${m[1]}/${m[2]}`.toLowerCase();

  // 商品名の「英字＋世代番号」（WAVE 2 / RIVER 2 / DELTA 3）とURLの世代を比べる
  for (const g of p.name.matchAll(/([A-Za-z]{3,10})\s*([0-9])\b/g)) {
    const hit = new RegExp(`${g[1].toLowerCase()}[-_ ]?([0-9])`).exec(path);
    if (hit && hit[1] !== g[2]) {
      add("リンク先不整合", "high", {
        name: p.name,
        detail: `${p.id}: 商品名は「${g[1]} ${g[2]}」だがリンク先は「${g[1]} ${hit[1]}」`,
        note: `別モデルに誘導しています: ${url}`,
      });
    }
  }
  // 別々の商品が同じ商品ページを指していないか
  if (!urlOwners.has(path)) urlOwners.set(path, []);
  urlOwners.get(path).push(p);
}
for (const [path, list] of urlOwners) {
  if (list.length < 2) continue;
  if (new Set(list.map((p) => norm(p.name).slice(0, 24))).size < 2) continue; // 重複登録は 1. で報告済み
  add("リンク先不整合", "high", {
    name: path,
    detail: list.map((p) => `${p.id}(${p.name.slice(0, 24)})`).join(" / "),
    note: "別商品が同じ楽天ページを指しています。どちらかのリンクが誤りです",
  });
}

// ── 5-6. 欠損と孤立 ──────────────────────────────
const missing = { price: [], image: [], category: [] };
const orphans = [];
for (const p of products) {
  if (!p.price) missing.price.push(p.id);
  if (!p.imageUrl) missing.image.push(p.id);
  if (!p.categoryId) missing.category.push(p.id);
  if (usedIn(p.id).length === 0) orphans.push(p.id);
}

// ── 出力 ────────────────────────────────────────
if (JSON_OUT) {
  console.log(JSON.stringify({ findings, missing, orphans }, null, 2));
  process.exit(0);
}

const order = { high: 0, medium: 1, low: 2 };
findings.sort((a, b) => order[a.severity] - order[b.severity]);
const high = findings.filter((f) => f.severity === "high").length;

console.log(`\n=== 商品データ健全性監査（全${products.length}商品 / 公開${published.length}記事）===`);
console.log(`要対応 ${high}件 / 検出 ${findings.length}件\n`);

let lastType = "";
for (const f of findings) {
  if (f.type !== lastType) {
    console.log(`\n▼ ${f.type}`);
    lastType = f.type;
  }
  const mark = f.severity === "high" ? "!!" : " -";
  console.log(`${mark} ${f.name}`);
  if (f.entries) {
    for (const e of f.entries) {
      console.log(
        `     ${e.id.padEnd(32)} ¥${String(e.price).padStart(7)} ${
          e.articles.length ? `記事: ${e.articles.join(", ")}` : "（未使用）"
        }`
      );
    }
  }
  if (f.detail) console.log(`     ${f.detail}`);
  if (f.note) console.log(`     → ${f.note}`);
}

console.log(`\n▼ 欠損`);
console.log(`   価格なし: ${missing.price.length}件 / 画像なし: ${missing.image.length}件 / カテゴリなし: ${missing.category.length}件`);
console.log(`\n▼ 孤立（どの公開記事からも参照なし）: ${orphans.length}件`);
console.log(`   ※ 孤立自体は問題ではありません（記事化待ちの在庫）。ただし重複の片割れは削除候補です`);
