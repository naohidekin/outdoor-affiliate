#!/usr/bin/env node
/**
 * アフィリリンクの手動補完ヘルパー
 *
 * 背景（2026-08-01）: 検索ページ行きだったアフィリリンク194件のうち111件は
 * `fix-search-affiliate-links.mjs` が自動で商品直リンクに置換できたが、
 * 82件は「型番が無い汎用品」「サイズ違いの誤マッチが怖い」等の理由で
 * 自動判定を見送った。そのうち7月に実クリックがあった25件を手動で埋める。
 *
 * 楽天APIを使わないので、IP許可リストの制約を受けない（外出先でも使える）。
 *
 * ## 使い方
 *
 * 1) 記入用ファイルを作る（対象商品と検索URLの一覧が出力される）
 *      node scripts/manual-affiliate-links.mjs --init
 *
 *    対象の切り替え:
 *      --broken     リンク先が中古出品・削除済み・別モデルだった商品（2026-08-03検出）
 *      --ids=a,b    任意の商品IDを指定
 *      --all        検索ページ行きのアフィリリンク全件
 *    ※ 2)以降も同じ引数を付けること。付け忘れると対象リストが既定に戻り、
 *      記入した行が「対象リスト外」で弾かれる
 *
 * 2) scratch/manual-affiliate-links.txt を開き、各行の検索URLをブラウザで開いて
 *    正しい商品ページを見つけ、そのURL（https://item.rakuten.co.jp/... ）を
 *    行末の `= ` の後ろに貼る。分からない商品は空のまま飛ばしてよい
 *
 * 3) 検証（書き込みはしない）
 *      node scripts/manual-affiliate-links.mjs
 *
 * 4) 反映
 *      node scripts/manual-affiliate-links.mjs --apply
 *
 * ## 安全装置
 * - item.rakuten.co.jp 等の商品ページURL以外は受け付けない（検索URLを弾く）
 * - すでにアフィリエイトURL形式で貼られた場合は中の商品URLを取り出して使う
 * - 対象商品リストに無いIDは無視する
 * - --apply しない限り products.json は書き換わらない
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const SHEET = path.join(ROOT, "scratch", "manual-affiliate-links.txt");

// 既存商品で使用中のアフィリエイトID（新規発行はしない運用）
const AFFILIATE_ID =
  process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

// 7月のクリック実績があり、かつ検索ページ行きのまま残っている25件。
// クリック数の多い順。これ以外も直したくなったら --all を付ける
const PRIORITY_IDS = [
  "sb-kids-001", "growler-001", "water-jug-igloo-400s",
  "pillow-sea-to-summit-aeros", "tent-duo-005", "sb-kids-003",
  "sierra-cup-bundok", "tent-solo-002", "water-jug-stanley-7.5l",
  "tent-duo-004", "tent-duo-002", "table-002", "fp-001", "cooler-005",
  "rw-004", "growler-003", "pillow-nemo-fillo-elite", "hammock-unigear",
  "knife-003", "sierra-cup-belmont", "sb-budget-004",
  "fire-blower-tokyocamp", "bp-004", "cooker-001",
];

const APPLY = process.argv.includes("--apply");
const INIT = process.argv.includes("--init");
const ALL = process.argv.includes("--all");

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const byId = new Map(products.map((p) => [p.id, p]));

function isSearchLink(url) {
  if (!url) return false;
  const m = url.match(/[?&]pc=([^&]+)/);
  if (!m) return false;
  let t;
  try {
    t = decodeURIComponent(m[1]);
  } catch {
    t = m[1];
  }
  return t.includes("search.rakuten");
}

// 2026-08-03: リンク先が中古出品・削除済み・別モデルだった商品。
// 検索ページ行きではないので isSearchLink では拾えず、明示的に列挙する
const BROKEN_LINK_IDS = {
  "cooler-yamazen-yec-m03": "リンク先が中古出品。新品の商品ページに差し替える",
  "rakuten-brave-6-4953571093208": "リンク先ページが削除済み（店舗在庫は工具のみ）",
  "kettle-gsi-glacier": "検索ページ行きのまま",
  "fan-hagoogi-ot-f12": "登録ページが店舗の出品一覧に出てこない。要確認",
  "sb-nanga-003": "600DXと同じ商品ページを指している。750DXのページに分離する",
};

const idsArg = process.argv.find((a) => a.startsWith("--ids="));

// 案内文にモード引数を引き継ぐ。--broken を落とすと対象リストが
// PRIORITY_IDS に戻り、記入した5件が「対象外」で弾かれる
const MODE_ARGS = [
  idsArg,
  process.argv.includes("--broken") ? "--broken" : null,
  process.argv.includes("--all") ? "--all" : null,
].filter(Boolean).join(" ");
const CMD = `node scripts/manual-affiliate-links.mjs${MODE_ARGS ? " " + MODE_ARGS : ""}`;

function targetIds() {
  if (idsArg) return idsArg.slice(6).split(",").map((s) => s.trim()).filter((id) => byId.has(id));
  if (process.argv.includes("--broken")) return Object.keys(BROKEN_LINK_IDS).filter((id) => byId.has(id));
  if (ALL) return products.filter((p) => isSearchLink(p.affiliateUrl)).map((p) => p.id);
  return PRIORITY_IDS.filter((id) => byId.has(id));
}

// 楽天の商品ページURLか判定。検索URLやトップは弾く
function isItemUrl(url) {
  return /^https:\/\/(item|books|search)?\.?rakuten\.co\.jp\//.test(url)
    ? /^https:\/\/(item|books)\.rakuten\.co\.jp\/[^/]+\/[^/]+/.test(url)
    : false;
}

// 商品ページURLから広告・計測パラメータを取り除く。
// ブラウザからコピーしたURLには gclid / scid=af_pc_etc / icm_cid などの
// 他社アフィリエイト・広告の識別子が付いていることがあり、そのまま
// アフィリリンクに埋めると成果が他社に帰属したり無効化される恐れがある。
// 楽天の商品ページはパス（/shop/itemcode/）だけで一意に開けるのでクエリは全て捨てる
function stripTracking(url) {
  try {
    const u = new URL(url);
    if (/(^|\.)rakuten\.co\.jp$/.test(u.hostname)) {
      u.search = "";
      u.hash = "";
      return u.toString();
    }
    return url;
  } catch {
    return url;
  }
}

// アフィリエイトURLが貼られた場合は中の pc= を取り出す
function extractItemUrl(raw) {
  const v = raw.trim();
  if (!v) return null;
  const m = v.match(/[?&]pc=([^&]+)/);
  if (m) {
    try {
      return stripTracking(decodeURIComponent(m[1]));
    } catch {
      return m[1];
    }
  }
  return stripTracking(v);
}

function buildAffiliateUrl(itemUrl) {
  return `https://hb.afl.rakuten.co.jp/ichiba/${AFFILIATE_ID}/?pc=${encodeURIComponent(
    itemUrl
  )}&link_type=text`;
}

// ─── --init: 記入用ファイルを生成 ──────────────────────
if (INIT) {
  const ids = targetIds();
  const lines = [
    "# アフィリリンク手動補完シート",
    "# 各行の検索URLをブラウザで開き、正しい商品ページのURLを `= ` の後ろに貼ってください。",
    "# 分からない商品は空のまま飛ばして構いません（スキップされます）。",
    "# 貼るURL例: https://item.rakuten.co.jp/shopname/itemcode/",
    "# 楽天で見つからなかった商品は `none` と書いてください（死んだ検索リンクを削除します）。",
    "# 価格も更新する場合: URL のあとに ` | 12800` のように書きます（任意）。",
    "# 注意: 登録価格と大きく違う商品は別モデルか並行輸入の可能性があります。",
    "#       モデル名を最後まで照合し、「日本未発売」「関税負担」表記の店は避けてください。",
    "",
  ];
  for (const id of ids) {
    const p = byId.get(id);
    // 商品名にブランドが含まれていない場合だけ前置する（二重にしない）
    const needsBrand = p.brand && !p.name.includes(p.brand);
    const q = encodeURIComponent(
      `${needsBrand ? p.brand + " " : ""}${p.name}`.slice(0, 100)
    );
    lines.push(`# ${p.name}（¥${(p.price || 0).toLocaleString()}）`);
    if (BROKEN_LINK_IDS[id]) lines.push(`#   理由: ${BROKEN_LINK_IDS[id]}`);
    const current = extractItemUrl(p.affiliateUrl || "");
    if (current) lines.push(`#   現在: ${current}`);
    lines.push(`#   検索: https://search.rakuten.co.jp/search/mall/${q}/`);
    lines.push(`${id} = `);
    lines.push("");
  }
  fs.mkdirSync(path.dirname(SHEET), { recursive: true });
  fs.writeFileSync(SHEET, lines.join("\n"));
  console.log(`記入用ファイルを作成: ${SHEET}`);
  console.log(`対象 ${ids.length}件。ファイルを開いてURLを貼ってください。`);
  console.log(`貼り終わったら: ${CMD}（検証）`);
  process.exit(0);
}

// ─── 検証 / 反映 ────────────────────────────────────
if (!fs.existsSync(SHEET)) {
  console.error(`記入用ファイルがありません。先に --init を実行してください:\n  ${CMD} --init`);
  process.exit(1);
}

const allowed = new Set(targetIds());
const ok = [];
const errors = [];
const skipped = [];
const notFound = []; // 楽天に商品が存在しなかったもの（死にリンクを消す）

for (const line of fs.readFileSync(SHEET, "utf8").split("\n")) {
  const t = line.trim();
  if (!t || t.startsWith("#")) continue;
  const m = t.match(/^([A-Za-z0-9._-]+)\s*=\s*(.*)$/);
  if (!m) continue;
  const [, id, rawValue] = m;
  const p = byId.get(id);
  if (!p) {
    errors.push(`${id}: products.json に存在しません`);
    continue;
  }
  // 「URL | 価格」の書式を許可（商品ページを見ている間に価格も更新できる）
  const [rawUrl, rawPrice] = rawValue.split("|").map((v) => (v || "").trim());
  const newPrice = rawPrice ? parseInt(rawPrice.replace(/[^\d]/g, ""), 10) : null;
  if (rawPrice && !Number.isFinite(newPrice)) {
    errors.push(`${id}: 価格が数値として読めません → ${rawPrice}`);
    continue;
  }
  const itemUrl = extractItemUrl(rawUrl);
  if (!itemUrl) {
    // 未記入は対象リスト外でも黙って飛ばす（古いシートを使い回しても止まらない）
    skipped.push(`${id} (${p.name.slice(0, 30)})`);
    continue;
  }
  if (!allowed.has(id)) {
    errors.push(`${id}: 対象リスト外です（--broken / --ids= / --all で対象を切り替えられます）`);
    continue;
  }
  // 「楽天に無かった」を記録する書き方。死んだ検索リンクを消す
  if (/^(none|なし|no|-|x)$/i.test(itemUrl)) {
    const yahooIsSearch = (p.yahooUrl || "").includes("/search");
    notFound.push({
      id,
      name: p.name,
      // 楽天を消したあとに確実な購入導線が残るか
      hasRoute: !!p.amazonUrl || (!!p.yahooUrl && !yahooIsSearch),
    });
    continue;
  }
  if (itemUrl.includes("search.rakuten")) {
    errors.push(`${id}: 検索URLが貼られています。商品ページのURLにしてください`);
    continue;
  }
  if (!isItemUrl(itemUrl)) {
    errors.push(`${id}: 楽天の商品ページURLではありません → ${itemUrl.slice(0, 60)}`);
    continue;
  }
  // 登録価格と大きく乖離していたら、別モデルや並行輸入品の可能性を警告する
  // （2026-08-01: スタンレーのクラシックを探して別モデルのアドベンチャーを
  //   並行輸入店で見つけかけた。価格差は誤選択の一番わかりやすいサイン）
  let priceWarn = null;
  const ref = newPrice || p.price;
  if (p.price > 0 && ref > 0 && (ref > p.price * 1.5 || ref < p.price * 0.5)) {
    priceWarn = `登録¥${p.price.toLocaleString()} → ¥${ref.toLocaleString()}（別モデル・並行輸入の可能性）`;
  }
  ok.push({
    id,
    name: p.name,
    itemUrl,
    newPrice,
    priceWarn,
    affiliateUrl: buildAffiliateUrl(itemUrl),
  });
}

console.log(`\n=== 検証結果 ===`);
console.log(
  `直リンク化: ${ok.length}件 / 楽天に無し: ${notFound.length}件 / 未記入: ${skipped.length}件 / エラー: ${errors.length}件\n`
);
for (const o of ok) {
  console.log(`✓ ${o.name.slice(0, 38)}`);
  console.log(`    ${o.itemUrl}`);
  if (o.newPrice) console.log(`    価格を ¥${o.newPrice.toLocaleString()} に更新します`);
  if (o.priceWarn) console.log(`    ⚠ ${o.priceWarn}`);
}
if (notFound.length) {
  console.log(`\n▼ 楽天に無し → 死んだ検索リンクを削除します`);
  for (const n of notFound) {
    console.log(`  − ${n.name.slice(0, 38)}${n.hasRoute ? "" : "  ← 購入導線が無くなります（記事側の対応が必要）"}`);
  }
  const orphan = notFound.filter((n) => !n.hasRoute);
  if (orphan.length) {
    console.log(
      `\n  ※ ${orphan.length}件は楽天・Amazon・Yahoo!のどれにも確実な購入先がありません。\n` +
        `     コロナ PA-F85A と同じく「入手方法」を記事に書くか、掲載商品の差し替えを検討してください。`
    );
  }
}
if (errors.length) {
  console.log(`\n▼ エラー（修正してください）`);
  for (const e of errors) console.log(`  ✗ ${e}`);
}
if (skipped.length) {
  console.log(`\n▼ 未記入（スキップ）`);
  for (const s of skipped) console.log(`  - ${s}`);
}

if (!APPLY) {
  console.log(`\n反映するには: ${CMD} --apply`);
  process.exit(errors.length > 0 ? 1 : 0);
}
if (errors.length > 0) {
  console.error(`\nエラーがあるため反映を中止しました。上の行を直してから再実行してください。`);
  process.exit(1);
}
if (ok.length === 0 && notFound.length === 0) {
  console.error(`\n記入がありません。`);
  process.exit(1);
}

const now = new Date().toISOString();
for (const o of ok) {
  const p = byId.get(o.id);
  p.affiliateUrl = o.affiliateUrl;
  if (o.newPrice) {
    p.price = o.newPrice;
    p.priceUpdatedAt = now;
  }
  p.updatedAt = now;
}
for (const n of notFound) {
  const p = byId.get(n.id);
  p.affiliateUrl = ""; // 検索ページ行きの死にリンクを消す（買えない先へ送らない）
  p.updatedAt = now;
}
fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
console.log(
  `\nproducts.json 反映: 直リンク化 ${ok.length}件 / 死にリンク削除 ${notFound.length}件`
);
console.log("次: git diff data/products.json で確認 → コミット → sync（--no-pull）");
