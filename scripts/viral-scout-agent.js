#!/usr/bin/env node

/**
 * Viral Scout Agent CLI ラッパー
 *
 * 実装本体は src/lib/viral-scout-agent.mjs にあります（Next.js API route と共有）。
 * このファイルは CLI から呼び出される時の argv パースとプロセス終了処理のみ担当。
 *
 * 使い方:
 *   node scripts/viral-scout-agent.js                  # フル実行
 *   node scripts/viral-scout-agent.js --dry-run        # 保存なし
 *   node scripts/viral-scout-agent.js --axis ai        # 特定軸のみ
 *   node scripts/viral-scout-agent.js --count=50       # 目標件数
 *   node scripts/viral-scout-agent.js --min-score=50   # 最低エンゲージメントスコア
 *   node scripts/viral-scout-agent.js --days=2         # 直近N日のみ
 */

import { runViralScout, parseArgs } from "../src/lib/viral-scout-agent.mjs";

const opts = parseArgs();
runViralScout(opts)
  .then(() => {
    // 正常終了
  })
  .catch((err) => {
    console.error("[viral-scout] エラー:", err.message);
    process.exit(1);
  });
