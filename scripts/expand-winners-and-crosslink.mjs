#!/usr/bin/env node

/**
 * #1 売れ筋2商品の横展開 ＋ #2 秋クラスターの相互リンク補強。
 *  横展開:
 *   - NEMO Fillo(枕) → cot-vs-mat-comparison(寝心地)のまとめに
 *   - S'more OKURUMI(春秋シュラフ) → spring-sleeping-bag-guideの予算帯に
 *  相互リンク:
 *   - 秋①(寒さ対策) → 秋②(ハブ)・秋③(服装)への戻りリンク
 *   - 秋②(ハブ) → 秋③(服装)へのリンク＋関連記事追加
 * 使い方: node scripts/expand-winners-and-crosslink.mjs  →  npm run db:sync
 * ※ 冪等（各編集は適用済みならスキップ）
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const get = (slug) => articles.find((a) => a.slug === slug);
let changed = 0;

// 1回の置換ヘルパー（from→to、既にtoがあればスキップ、fromが無ければ警告）
function edit(a, label, from, to, addPids = []) {
  if (!a) { console.log(`⚠️ 記事なし: ${label}`); return; }
  if (a.content.includes(to)) { console.log(`  ⏭️ 適用済: ${label}`); return; }
  if (!a.content.includes(from)) { console.log(`  ⚠️ アンカー無し: ${label}`); return; }
  a.content = a.content.replace(from, to);
  if (addPids.length) a.productIds = Array.from(new Set([...(a.productIds || []), ...addPids]));
  a.updatedAt = now;
  changed++;
  console.log(`✅ ${label}`);
}

// ── #1 横展開 ──
// NEMO枕 → cot-vs-mat-comparison（まとめ末尾）
edit(
  get("cot-vs-mat-comparison"),
  "cot-vs-mat: NEMO枕カード",
  "ぼくみたいに「腰バキバキの朝」を経験する前に、寝床だけはちゃんと整えておいてください。",
  "ぼくみたいに「腰バキバキの朝」を経験する前に、寝床だけはちゃんと整えておいてください。\n\nそして寝床が整ったら、最後の仕上げは枕です。首元が安定すると睡眠の質が一段上がります。かさばらないので、コットやマットに1つ足しておくと快適さが違います。\n\n{{product:pillow-nemo-fillo}}",
  ["pillow-nemo-fillo"]
);

// S'more春秋シュラフ → spring-sleeping-bag-guide（1万円以下の穴場）
edit(
  get("spring-sleeping-bag-guide"),
  "spring-sleeping-bag: S'moreカード",
  "### 予算5,000〜10,000円（化繊）",
  "### 予算5,000〜10,000円（化繊）\n\n同じ1万円以下でも、ダウンの穴場を狙うならS'more OKURUMI BAGが候補です。ダウン90%・約580gと軽量で、快適温度5〜15℃と春秋にちょうどいい封筒型。丸洗いでき、2つ連結すれば掛け布団にもなります。\n\n{{product:sb-smore-okurumi}}",
  ["sb-smore-okurumi"]
);

// ── #2 相互リンク補強 ──
// 秋① → 秋③（服装）
edit(
  get("autumn-winter-camp-cold-gear-guide"),
  "秋①→秋③ 服装リンク",
  "レイヤリングの詳しい組み方は[春キャンプの服装ガイド](/articles/spring-camp-clothing-guide)の3レイヤーの考え方が、そのまま秋にも使えます。",
  "秋向けの詳しい組み方は[秋キャンプの服装・防寒レイヤリングガイド](/articles/autumn-camp-clothing-layering-guide)にまとめました。基本の考え方は[春キャンプの服装ガイド](/articles/spring-camp-clothing-guide)も参考になります。"
);
// 秋① → 秋②（ハブ）
edit(
  get("autumn-winter-camp-cold-gear-guide"),
  "秋①→秋② ハブリンク",
  "気になったギアがあれば、上のリンクからチェックしてみてください。暖かくして、いいシーズンを。",
  "気になったギアがあれば、上のリンクからチェックしてみてください。暖かくして、いいシーズンを。\n\n秋キャンプ全体の楽しみ方と注意点は[秋キャンプ完全ガイド](/articles/autumn-camp-complete-guide)にまとめています。あわせてどうぞ。"
);
// 秋② → 秋③（服装・本文）
edit(
  get("autumn-camp-complete-guide"),
  "秋②→秋③ 服装リンク(本文)",
  "服装の重ね方（レイヤリング）は[春キャンプの服装ガイド](/articles/spring-camp-clothing-guide)の3レイヤーの考え方が、そのまま秋にも使えます。",
  "服装の重ね方（レイヤリング）は[秋キャンプの服装・防寒レイヤリングガイド](/articles/autumn-camp-clothing-layering-guide)で詳しく解説しています。"
);
// 秋② → 秋③（関連記事）
edit(
  get("autumn-camp-complete-guide"),
  "秋②→秋③ 関連記事追加",
  "### 関連記事\n\n- [秋冬キャンプの寒さ対策ギア完全ガイド](/articles/autumn-winter-camp-cold-gear-guide)",
  "### 関連記事\n\n- [秋冬キャンプの寒さ対策ギア完全ガイド](/articles/autumn-winter-camp-cold-gear-guide)\n- [秋キャンプの服装・防寒レイヤリングガイド](/articles/autumn-camp-clothing-layering-guide)"
);

fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 ${changed} 箇所を更新。次に  npm run db:sync  で反映してください。`);
