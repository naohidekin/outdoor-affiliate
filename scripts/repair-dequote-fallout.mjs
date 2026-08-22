#!/usr/bin/env node
/**
 * dequote-reviews.mjs の変換で壊れた箇所を直す
 *
 * 2026-08-22: 61記事835行の引用符を外したが、3種類の取りこぼしが出た。
 * 私の変換の不備なので、適用済みの本文を後追いで修理する。
 *
 * ① 見出しの ** が閉じていない（21行）
 *    normalizeHead の正規表現が (.+?)(\*{0,2}) の形で、遅延マッチが
 *    末尾の ** まで飲み込んでいた。結果:
 *      「> レビューの傾向（…）**」   ← 開きが無い
 *      「**レビューの傾向（…）:」    ← 閉じが無い
 *    Markdown が壊れて画面に ** がそのまま出る。
 *
 * ② 1行に引用が2つ以上あると、最初の1組しか外れない
 *    「1人で簡単に張れた」「強風の中でも耐えられた」という…
 *      → 1人で簡単に張れた「強風の中でも耐えられた」という…
 *    括弧の数は合うので検出をすり抜けたが、文として明らかにおかしい。
 *
 * ④ 読点が要らない位置に入った（3行）
 *    「注意点: 「重さに慣れるまで数回かかる」という声も」の引用を外すとき、
 *    直前の文字が空白だったため読点を足す条件をすり抜けた。
 *      - 注意点: 、重さに慣れるまで数回かかるという声も
 *    「直前が句読点か」だけでなく「コロンや空白の直後か」も見る必要があった。
 *
 * ③ 入れ子の引用を含む行が丸ごと未処理
 *    > 「…屋外30℃超えだと「ちょっと涼しいかな」程度に落ちます」
 *    外側だけ外して、内側の強調は残す。
 *
 * 使い方:
 *   node scripts/repair-dequote-fallout.mjs           # 修理案を表示
 *   node scripts/repair-dequote-fallout.mjs --apply
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const APPLY = process.argv.includes("--apply");
const LABEL = "レビューの傾向（各モールのレビューを読んだ僕の要約です）";

const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));
const fixes = [];

for (const a of articles) {
  if (a.status !== "published") continue;
  const lines = (a.content || "").split("\n");
  let changed = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // ④ コロンや行頭の直後に読点が入ってしまった箇所を戻す
    if (/[:：]\s*、|^\s*[-*]\s*、/.test(line)) {
      const next = line.replace(/([:：]\s*)、/g, "$1").replace(/^(\s*[-*]\s*)、/, "$1");
      if (next !== line) {
        fixes.push({ a, i, why: "読点が要らない位置に入っていた", from: line, to: next });
        lines[i] = next;
        changed = true;
        continue;
      }
    }

    // ① ラベル行の ** を張り直す
    if (line.includes(LABEL) && ((line.match(/\*\*/g) || []).length % 2 === 1)) {
      const pre = (line.match(/^([>\s]*)/) || ["", ""])[1];
      const hash = (line.match(/^[>\s]*(#{1,4}\s*)/) || ["", ""])[1] || "";
      const colon = /[:：]\s*$/.test(line) ? line.trim().slice(-1) : "";
      // 見出し記法（#）が付いているときは ** を付けない
      const next = hash ? `${pre}${hash}${LABEL}${colon}` : `${pre}**${LABEL}**${colon}`;
      if (next !== line) {
        fixes.push({ a, i, why: "見出しの ** が閉じていない", from: line, to: next });
        lines[i] = next;
        changed = true;
      }
      continue;
    }

    // ② 行頭が引用でないのに、その直後に孤立した引用が続く形
    //    （1組目だけ外れた痕跡）。レビューブロック内に限る
    const orphan = line.match(/^([^「\n]{4,}?)「([^「」\n]{4,})」(という|と[^\n]{0,4}|。|、)/);
    if (orphan && isInReviewBlock(lines, i)) {
      // 直前が句読点なら読点を足さない。「…でした。、品質は確か」になる
      const next = line.replace(
        /([^\n])「([^「」\n]{4,})」/,
        (m, before, body) => `${before}${/[。、！？：]/.test(before) ? "" : "、"}${body}`
      );
      if (next !== line) {
        fixes.push({ a, i, why: "1行に引用が複数あり片方だけ外れていた", from: line, to: next });
        lines[i] = next;
        changed = true;
      }
      continue;
    }

    // ③ 入れ子の引用を含む行。外側だけ外す
    const nested = line.match(/^([>\s]*(?:[-*][ \t]*)?)「(.*「.*」.*)」([^\n]*)$/);
    if (nested && isInReviewBlock(lines, i)) {
      const next = `${nested[1]}${nested[2]}${nested[3].replace(/（\s*[^）]{0,30}利用\s*）\s*$/, "")}`;
      if (next !== line) {
        fixes.push({ a, i, why: "入れ子の引用で未処理だった", from: line, to: next });
        lines[i] = next;
        changed = true;
      }
    }
  }

  if (changed) a.__next = lines.join("\n");
}

/** その行が「レビューの傾向」見出しの直後のブロックに入っているか */
function isInReviewBlock(lines, idx) {
  for (let j = idx - 1; j >= 0 && idx - j <= 8; j--) {
    const l = lines[j];
    if (l.trim() === "") continue;
    if (l.includes(LABEL)) return true;
    if (/^[>\s]*#{1,4}\s|^[>\s]*\{\{|^[>\s]*---/.test(l)) return false;
  }
  return false;
}

const bySlug = new Map();
for (const f of fixes) {
  if (!bySlug.has(f.a.slug)) bySlug.set(f.a.slug, []);
  bySlug.get(f.a.slug).push(f);
}

for (const [slug, list] of bySlug) {
  console.log(`\n──── ${slug}（${list.length}行）────`);
  const seen = new Set();
  for (const f of list) {
    const k = f.from;
    if (seen.has(k)) continue;
    seen.add(k);
    const n = list.filter((x) => x.from === k).length;
    console.log(`  [${f.why}]${n > 1 ? ` ×${n}` : ""}`);
    console.log(`    − ${f.from.trim().slice(0, 92)}`);
    console.log(`    ＋ ${f.to.trim().slice(0, 92)}`);
  }
}

console.log(`\n── まとめ ──`);
console.log(`  ${bySlug.size}記事 / ${fixes.length}行を修理`);

if (!APPLY) {
  console.log("\n書き込むには --apply");
  process.exit(0);
}

const ts = new Date().toISOString();
let n = 0;
for (const a of articles) {
  if (!a.__next) continue;
  a.content = a.__next;
  delete a.__next;
  a.updatedAt = ts; // pull時のマージ巻き戻し防止
  n++;
}
for (const a of articles) delete a.__next;
fs.writeFileSync(ARTICLES, JSON.stringify(articles, null, 2));
console.log(`\ndata/articles.json を更新しました（${n}記事）`);
console.log("反映: npm run db:sync -- --no-pull");
