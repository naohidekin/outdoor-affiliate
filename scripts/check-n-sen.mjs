#!/usr/bin/env node
import { createClient } from "@supabase/supabase-js";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

const { data, error } = await supabase
  .from("articles")
  .select("slug, title, product_ids, content");

if (error) { console.error(error.message); process.exit(1); }

const issues = [];
for (const a of data) {
  const m = a.title?.match(/(\d+)選/);
  if (!m) continue;
  const claimed = parseInt(m[1]);

  // product_ids による実数カウント
  const byProductIds = (a.product_ids || []).length;

  // content 内のランキング見出し数（## 1. / ### 1位 / **第1位** 等）でクロスチェック
  const rankMatches = (a.content || "").match(/(?:#{1,3}\s*(?:\d+位|第\d+位|TOP\d+|\d+\.))|(?:\*\*第\d+位)/g) || [];
  const byContent = rankMatches.length;

  // どちらかが claimed と一致しなければ報告
  const actual = byProductIds > 0 ? byProductIds : byContent;
  if (actual > 0 && actual !== claimed) {
    issues.push({ slug: a.slug, title: a.title, claimed, byProductIds, byContent });
  }
}

if (issues.length === 0) {
  console.log("✅ 不一致なし");
} else {
  console.log(`❌ ${issues.length}件の不一致\n`);
  for (const x of issues) {
    console.log(`[${x.claimed}選 宣言 / product_ids:${x.byProductIds}件 / content見出し:${x.byContent}件]`);
    console.log(`  ${x.title}`);
    console.log(`  slug: ${x.slug}\n`);
  }
}
