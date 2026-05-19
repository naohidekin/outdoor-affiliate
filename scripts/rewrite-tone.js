#!/usr/bin/env node

/**
 * 文体一括変換スクリプト
 *
 * 全記事の口調を「断言・言い切り調」から「ですます調・友人目線」に変換する。
 * - 一人称: 俺 → 僕
 * - 文末: 〜だ / 〜である → 〜です / 〜ます
 * - トーン: 友人に話しかけるような温かさ
 * - markdown構造・shortcode ({{comparison:...}} 等) は必ず保持
 *
 * 使い方:
 *   node scripts/rewrite-tone.js               # 全記事を変換（バックアップあり）
 *   node scripts/rewrite-tone.js --dry-run     # 最初の1件をプレビュー（保存なし）
 *   node scripts/rewrite-tone.js --id=article-001  # 特定記事のみ
 */

import Anthropic from "@anthropic-ai/sdk";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ARTICLES_PATH = path.join(__dirname, "../data/articles.json");

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

function parseArgs() {
  const args = process.argv.slice(2);
  return {
    dryRun: args.includes("--dry-run"),
    targetId: args.find((a) => a.startsWith("--id="))?.split("=")[1],
  };
}

async function rewriteContent(content, articleId) {
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

  const articles = JSON.parse(fs.readFileSync(ARTICLES_PATH, "utf8"));

  let targets = articles;
  if (opts.targetId) {
    targets = articles.filter((a) => a.id === opts.targetId);
    if (targets.length === 0) {
      console.error(`記事が見つかりません: ${opts.targetId}`);
      process.exit(1);
    }
  }

  if (opts.dryRun) {
    // ドライラン: 最初の1件をプレビュー
    const art = targets[0];
    console.log(`\n=== DRY RUN: ${art.id} ===`);
    console.log("\n--- 変換前 (冒頭500字) ---");
    console.log(art.content.slice(0, 500));
    console.log("\n変換中...");
    const rewritten = await rewriteContent(art.content, art.id);
    console.log("\n--- 変換後 (冒頭500字) ---");
    console.log(rewritten.slice(0, 500));
    return;
  }

  // バックアップ
  const backupPath = ARTICLES_PATH.replace(".json", `.backup-${Date.now()}.json`);
  fs.copyFileSync(ARTICLES_PATH, backupPath);
  console.log(`バックアップ作成: ${path.basename(backupPath)}`);

  console.log(`\n変換対象: ${targets.length}件\n`);

  let successCount = 0;
  for (const art of targets) {
    if (!art.content) {
      console.log(`[SKIP] ${art.id} (content なし)`);
      continue;
    }
    process.stdout.write(`[${successCount + 1}/${targets.length}] ${art.id} ... `);
    try {
      const rewritten = await rewriteContent(art.content, art.id);
      // articles 配列内の該当記事を更新
      const idx = articles.findIndex((a) => a.id === art.id);
      if (idx !== -1) {
        articles[idx].content = rewritten;
        articles[idx].updatedAt = new Date().toISOString();
      }
      successCount++;
      console.log("完了");
    } catch (err) {
      console.log(`エラー: ${err.message}`);
    }
    // レート制限対策
    await new Promise((r) => setTimeout(r, 500));
  }

  // 保存
  fs.writeFileSync(ARTICLES_PATH, JSON.stringify(articles, null, 2), "utf8");
  console.log(`\n✅ ${successCount}件変換・保存完了`);
  console.log(`バックアップ: ${path.basename(backupPath)}`);
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
