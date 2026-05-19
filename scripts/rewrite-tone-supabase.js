#!/usr/bin/env node

/**
 * Supabase記事の文体一括変換スクリプト
 *
 * Supabaseにある記事を直接取得し、断言調→ですます調に変換して書き戻す。
 *
 * 使い方:
 *   node scripts/rewrite-tone-supabase.js --dry-run          # 最初の1件プレビュー
 *   node scripts/rewrite-tone-supabase.js --status=draft     # 下書きのみ変換
 *   node scripts/rewrite-tone-supabase.js --slug=compact-chair-ranking  # スラッグ指定
 *   node scripts/rewrite-tone-supabase.js                    # 全記事変換
 */

import Anthropic from "@anthropic-ai/sdk";
import { createClient } from "@supabase/supabase-js";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

function parseArgs() {
  const args = process.argv.slice(2);
  return {
    dryRun: args.includes("--dry-run"),
    status: args.find((a) => a.startsWith("--status="))?.split("=")[1],
    slug: args.find((a) => a.startsWith("--slug="))?.split("=")[1],
  };
}

async function rewriteContent(content) {
  const prompt = `以下のキャンプギアレビュー記事を、文体だけ変換してください。

## 変換ルール
- 一人称「俺」は「僕」に変更する
- 文末の「〜だ」「〜である」「〜した。」等の断言調を「〜です」「〜ます」「〜しました」に変換する
- 「〜一択」→「〜が一番だと思います」「〜がおすすめです」のように温かみを持たせる
- 「〜がベスト」→「〜がベストです」
- 「必須だ」→「必須です」「欠かせません」
- 友人に話しかけるような温かいトーンにする（押しつけがましくなく、共感ベースで）
- 結論は明確に伝えるが、断定一辺倒にしない

## 絶対に変えないもの
- markdown の見出し（#, ##, ### 等）・箇条書き・表の構造
- {{comparison:...}} {{products:...}} 等のショートコード（一字一句そのまま）
- 商品名・ブランド名・型番・数値・URL
- 記事の構成・見出し文言・内容の意味

## 入力記事
${content}

## 出力
変換後の記事本文のみ出力してください。余計な説明・コメントは不要です。`;

  const res = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 8192,
    messages: [{ role: "user", content: prompt }],
  });

  return res.content[0].text.trim();
}

async function main() {
  const opts = parseArgs();

  if (!process.env.ANTHROPIC_API_KEY) {
    console.error("ANTHROPIC_API_KEY が未設定");
    process.exit(1);
  }
  if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_ROLE_KEY) {
    console.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が未設定");
    process.exit(1);
  }

  // Supabaseから記事を取得
  let query = supabase.from("articles").select("id, slug, title, content, status, updated_at");

  if (opts.slug) {
    query = query.eq("slug", opts.slug);
  } else if (opts.status) {
    query = query.eq("status", opts.status);
  }

  const { data: articles, error } = await query;
  if (error) {
    console.error("Supabase取得エラー:", error.message);
    process.exit(1);
  }

  const targets = articles.filter((a) => a.content);
  console.log(`取得: ${targets.length}件`);

  if (targets.length === 0) {
    console.log("対象なし");
    return;
  }

  if (opts.dryRun) {
    const art = targets[0];
    console.log(`\n=== DRY RUN: ${art.slug} ===`);
    console.log("\n--- 変換前 (冒頭500字) ---");
    console.log(art.content.slice(0, 500));
    console.log("\n変換中...");
    const rewritten = await rewriteContent(art.content);
    console.log("\n--- 変換後 (冒頭500字) ---");
    console.log(rewritten.slice(0, 500));
    return;
  }

  let successCount = 0;
  for (const art of targets) {
    process.stdout.write(`[${successCount + 1}/${targets.length}] ${art.slug} ... `);
    try {
      const rewritten = await rewriteContent(art.content);
      const { error: updateError } = await supabase
        .from("articles")
        .update({ content: rewritten, updated_at: new Date().toISOString() })
        .eq("id", art.id);
      if (updateError) throw new Error(updateError.message);
      successCount++;
      console.log("完了");
    } catch (err) {
      console.log(`エラー: ${err.message}`);
    }
    await new Promise((r) => setTimeout(r, 500));
  }

  console.log(`\n✅ ${successCount}/${targets.length}件変換・Supabase更新完了`);
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
