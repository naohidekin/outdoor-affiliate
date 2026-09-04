#!/usr/bin/env node
/**
 * 楽天アフィリエイトの計測IDを既存リンクに付ける（段階適用）
 *
 * 背景（2026-09-04）: 注文明細CSVの measurement_id 列は108件中106件が空で、
 * 値が入っていた2件も「楽天ROOM」だった。サイトのリンクに計測IDが付いて
 * いないので、「記事経由で売れたもの」と「読者がついでに買ったもの」を
 * 推測でしか分けられない。8月の楽天報酬 ¥14,205 のうち、キャンプ由来は
 * 26.8% しかなかった。ここを実測で分けたい。
 *
 * 引き継ぎ書は `rafcid=wsc_i_is_<UUID>` を計測IDと見ていたが、これは誤り。
 * 386商品中238件に rafcid が付いた状態で measurement_id は空のままだった。
 * 最終URLの rafcid は計測IDの有無に関係なく同じ値になる。別物である。
 *
 * 計測IDは楽天アフィリエイトの「商品リンクを作成」で発行し、**パスの一部**
 * としてリンクに入る。クエリパラメータではない。
 *
 *   付与前  https://hb.afl.rakuten.co.jp/ichiba/<アフィリID>/?pc=...
 *   付与後  https://hb.afl.rakuten.co.jp/ichiba/<アフィリID>/_RTLink143831?pc=...
 *
 * ## 規約について（読むこと）
 *
 * 楽天の作成画面には「HTMLソース内の計測IDの変更はご遠慮ください。既存の
 * リンクで計測IDを追加、変更する場合は、再度リンクを作り直し、HTMLソース
 * 全体を差し替えるようにお願いします」と書かれている。
 *
 * この注意書きが想定しているのは、`<a>` と計測用 `<img>` が同居する
 * HTMLソースだと考えている。片方だけ書き換えると食い違うためである。
 * こちらが持っているのはURL単体で、生成される文字列は作成画面が出すものと
 * 同じ形になる。実測でも、付与あり・なしで同じ商品ページに200で着地する。
 *
 * それでも字面には反するので、**段階適用にしている**。まずクリック上位の
 * 20記事だけに付け、翌月の注文明細に計測IDが出るのを確認してから広げる。
 * 効かなかった場合や楽天から指摘があった場合は --remove で全部戻せる。
 *
 * ## 使い方
 *
 *   node scripts/add-measurement-id.mjs                # 第1段の対象を確認（書き込まない）
 *   node scripts/add-measurement-id.mjs --apply        # 第1段を反映
 *   node scripts/add-measurement-id.mjs --all          # 残り全部を確認
 *   node scripts/add-measurement-id.mjs --all --apply  # 残り全部を反映
 *   node scripts/add-measurement-id.mjs --remove --apply  # 付けたものを全部外す
 *
 * 対象リストは scratch/stage1-target.json（無ければ --all 相当になる）。
 *
 * ## 安全装置
 * - 既定は dry-run。--apply を付けない限り書き込まない
 * - すでに計測IDが付いているリンクは触らない（冪等）
 * - 形が想定と違うリンクは触らず、最後にまとめて報告する
 * - 書き換えた記事・商品の updatedAt を必ず進める（db:sync に載せるため）
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const ALL = argv.includes("--all");
const REMOVE = argv.includes("--remove");

// 楽天アフィリエイトの管理画面で発行した計測ID。公開URLに入る値なので秘密ではない。
// 名前は camp-gear-lab。上限20個までなので、記事ごとには作らない。
const MEASUREMENT_ID = process.env.RAKUTEN_MEASUREMENT_ID || "_RTLink143831";

// https://hb.afl.rakuten.co.jp/{ichiba|hgc}/{アフィリID}/{計測ID}?...
// 計測IDの部分が空なら未付与、入っていれば付与済み
const LINK_RE = /(https:\/\/hb\.afl\.rakuten\.co\.jp\/(?:ichiba|hgc)\/[A-Za-z0-9.]+\/)([^?\s)]*)(\?)/g;

const read = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, "data", f), "utf8"));
const write = (f, v) =>
  fs.writeFileSync(path.join(ROOT, "data", f), JSON.stringify(v, null, 2) + "\n");

const nowIso = () => {
  const d = new Date();
  return d.toISOString().replace(/\.(\d{3})\d*Z$/, ".$1Z");
};

/** 1本のURL群を書き換える。戻り値は [新しい文字列, 付けた数, 触らなかった数] */
function rewrite(text) {
  let added = 0;
  let skipped = 0;
  const out = text.replace(LINK_RE, (all, head, mid, q) => {
    if (REMOVE) {
      if (!mid) return all;
      skipped++;
      return head + q;
    }
    if (mid) return all; // すでに何か入っている。触らない
    added++;
    return head + MEASUREMENT_ID + q;
  });
  return [out, REMOVE ? skipped : added, 0];
}

/** 想定外の形のリンクを拾う（ドメイン直下など） */
function findOdd(text, label, bag) {
  for (const m of text.matchAll(/https:\/\/hb\.afl\.rakuten\.co\.jp[^\s)"']*/g)) {
    const u = m[0];
    if (!/\/(?:ichiba|hgc)\/[A-Za-z0-9.]+\//.test(u)) bag.push(`${label}: ${u.slice(0, 70)}`);
  }
}

// ─── 対象の決定 ──────────────────────────────────────────────
let target = null;
const targetFile = path.join(ROOT, "scratch", "stage1-target.json");
if (!ALL && fs.existsSync(targetFile)) {
  target = JSON.parse(fs.readFileSync(targetFile, "utf8"));
}
const inScopeArticle = (slug) => ALL || REMOVE || !target || target.articles.includes(slug);
const inScopeProduct = (id) => ALL || REMOVE || !target || target.products.includes(id);

const articles = read("articles.json");
const products = read("products.json");
const odd = [];
const touchedA = [];
const touchedP = [];
const NOW = nowIso();

for (const a of articles) {
  findOdd(a.content || "", `記事 ${a.slug}`, odd);
  if (!inScopeArticle(a.slug)) continue;
  const [next, n] = rewrite(a.content || "");
  if (n > 0) {
    if (APPLY) {
      a.content = next;
      a.updatedAt = NOW;
    }
    touchedA.push([a.slug, n]);
  }
}

for (const p of products) {
  const u = p.affiliateUrl || "";
  if (!u.includes("hb.afl.rakuten")) continue;
  findOdd(u, `商品 ${p.id}`, odd);
  if (!inScopeProduct(p.id)) continue;
  const [next, n] = rewrite(u);
  if (n > 0) {
    if (APPLY) {
      p.affiliateUrl = next;
      p.updatedAt = NOW;
    }
    touchedP.push([p.id, n]);
  }
}

// ─── 報告 ────────────────────────────────────────────────────
const verb = REMOVE ? "外す" : "付ける";
const scope = REMOVE ? "全体（切り戻し）" : ALL ? "全体" : "第1段（クリック上位20記事）";
const linksA = touchedA.reduce((s, [, n]) => s + n, 0);
const linksP = touchedP.reduce((s, [, n]) => s + n, 0);

console.log(`\n計測ID ${MEASUREMENT_ID} を${verb}  対象: ${scope}${APPLY ? "" : "  (DRY RUN)"}\n`);
console.log(`  記事 ${touchedA.length}本 / リンク ${linksA}本`);
for (const [s, n] of touchedA.sort((x, y) => y[1] - x[1]).slice(0, 25))
  console.log(`    ${String(n).padStart(3)}本  ${s}`);
if (touchedA.length > 25) console.log(`    … 他${touchedA.length - 25}本`);
console.log(`\n  商品 ${touchedP.length}件 / リンク ${linksP}本`);
console.log(`\n  合計 ${linksA + linksP}本`);

if (odd.length) {
  console.log(`\n▼ 形が想定と違うリンク ${odd.length}本（触っていない）`);
  for (const o of [...new Set(odd)].slice(0, 10)) console.log(`    ${o}`);
}

if (!APPLY) {
  console.log(`\n書き込んでいません。反映するには --apply を付けてください。`);
} else {
  write("articles.json", articles);
  write("products.json", products);
  console.log(`\n書き込みました。次に必ず: npm run data:normalize && npm test`);
}
