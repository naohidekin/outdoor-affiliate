#!/usr/bin/env node

/**
 * X Trend Researcher CLI ラッパー
 *
 * 実装本体は src/lib/x-trend-researcher.mjs にあります。
 * このファイルは CLI 起動・argv パース・プロセス終了処理のみ担当。
 *
 * 使い方:
 *   node scripts/x-trend-researcher.js               # フル実行（Sheets 追記）
 *   node scripts/x-trend-researcher.js --dry-run     # 保存なし（草案をコンソール表示）
 *   node scripts/x-trend-researcher.js --max-queries=3  # Brave クエリ数を絞る
 */

import { runTrendResearcher, parseArgs } from "../src/lib/x-trend-researcher.mjs";

const opts = parseArgs();

runTrendResearcher(opts)
  .then((result) => {
    if (result.skipped) {
      console.log("[x-trend-researcher] スキップ（kill_switch=true）");
    } else {
      console.log(`[x-trend-researcher] 完了: ${result.generated}件生成`);
    }
  })
  .catch((err) => {
    console.error("[x-trend-researcher] エラー:", err.message);
    process.exit(1);
  });
