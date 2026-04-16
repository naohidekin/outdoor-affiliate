#!/usr/bin/env node
/**
 * 全記事整合性チェック
 * 1. 「◯選」タイトル vs 実際の製品数（comparisonタグ）
 * 2. comparisonタグの幽霊ID（productsテーブルに存在しないID）
 * 3. 本文内の死内部リンク（/articles/{slug}が存在しない）
 */
import { createClient } from "@supabase/supabase-js";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

// データ取得
const { data: articles, error: aErr } = await supabase
  .from("articles").select("id, slug, title, content, product_ids");
if (aErr) { console.error("articles取得失敗:", aErr.message); process.exit(1); }

const { data: products, error: pErr } = await supabase
  .from("products").select("id");
if (pErr) { console.error("products取得失敗:", pErr.message); process.exit(1); }

const productIdSet = new Set((products || []).map(p => p.id));
const articleSlugSet = new Set((articles || []).map(a => a.slug));

let totalIssues = 0;

// ─── チェック1: 「◯選」 vs comparison タグのID数 ────────
console.log("=== チェック1: 「◯選」タイトル vs comparisonタグ製品数 ===\n");
let c1 = 0;
for (const a of articles) {
  const titleMatch = a.title?.match(/(\d+)選/);
  if (!titleMatch) continue;
  const claimed = parseInt(titleMatch[1]);

  const compTags = (a.content || "").match(/\{\{comparison:([^}]+)\}\}/g) || [];
  for (const tag of compTags) {
    const ids = tag.replace(/\{\{comparison:|}\}/g, "").split(",").map(s => s.trim()).filter(Boolean);
    if (ids.length !== claimed) {
      console.log(`❌ [${a.slug}]`);
      console.log(`   タイトル: ${a.title}`);
      console.log(`   宣言: ${claimed}選 / comparisonタグID数: ${ids.length}`);
      console.log();
      c1++; totalIssues++;
    }
  }
}
if (c1 === 0) console.log("✅ 問題なし\n");

// ─── チェック2: comparisonタグの幽霊ID ─────────────────
console.log("=== チェック2: comparisonタグに存在しない製品ID ===\n");
let c2 = 0;
for (const a of articles) {
  const compTags = (a.content || "").match(/\{\{comparison:([^}]+)\}\}/g) || [];
  for (const tag of compTags) {
    const ids = tag.replace(/\{\{comparison:|}\}/g, "").split(",").map(s => s.trim()).filter(Boolean);
    const ghosts = ids.filter(id => !productIdSet.has(id));
    if (ghosts.length > 0) {
      console.log(`❌ [${a.slug}]`);
      console.log(`   存在しないID: ${ghosts.join(", ")}`);
      console.log();
      c2++; totalIssues++;
    }
  }
}
if (c2 === 0) console.log("✅ 問題なし\n");

// ─── チェック3: 本文内の死内部リンク ────────────────────
console.log("=== チェック3: 本文内の死内部リンク（/articles/{slug}） ===\n");
let c3 = 0;
for (const a of articles) {
  const links = (a.content || "").match(/\/articles\/([\w-]+)/g) || [];
  const slugs = [...new Set(links.map(l => l.replace("/articles/", "")))];
  const dead = slugs.filter(s => !articleSlugSet.has(s));
  if (dead.length > 0) {
    console.log(`❌ [${a.slug}]`);
    console.log(`   死リンク先: ${dead.join(", ")}`);
    console.log();
    c3++; totalIssues++;
  }
}
if (c3 === 0) console.log("✅ 問題なし\n");

console.log(`\n=============================`);
console.log(`合計問題数: ${totalIssues}件`);
console.log(`  チェック1（◯選不一致）: ${c1}件`);
console.log(`  チェック2（幽霊ID）: ${c2}件`);
console.log(`  チェック3（死リンク）: ${c3}件`);
