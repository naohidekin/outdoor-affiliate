#!/usr/bin/env node

/**
 * X投稿自動生成 CLI ラッパー
 *
 * 実装本体は src/lib/x-post-generator.mjs にあります（Next.js API route と共有するため）。
 * このファイルは CLI から呼び出される時の argv パースとプロセス終了処理のみ担当します。
 *
 * 使い方:
 *   node scripts/generate-x-posts.js                     # 週次バッチ（全タイプ）
 *   node scripts/generate-x-posts.js --dry-run            # 生成のみ（Sheets書き込みなし）
 *   node scripts/generate-x-posts.js --type ai_dev_log    # 特定タイプのみ
 *   node scripts/generate-x-posts.js --axis camp          # 特定軸のみ
 *   node scripts/generate-x-posts.js --count 3            # 件数指定
 *   node scripts/generate-x-posts.js --auto-approve       # 自動承認（レガシー互換）
 */

import { generatePosts, parseArgs } from "../src/lib/x-post-generator.mjs";

const opts = parseArgs();
generatePosts(opts)
  .then(() => {
    // 正常終了
  })
  .catch((err) => {
    console.error("エラー:", err.message);
    process.exit(1);
  });
