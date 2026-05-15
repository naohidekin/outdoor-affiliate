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
import { execSync } from "child_process";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.join(__dirname, "..");

const opts = parseArgs();
runViralScout(opts)
  .then(() => {
    // --push フラグがある場合は git push で Vercel に反映
    if (process.argv.includes("--push")) {
      try {
        const result = execSync(
          'git diff --quiet data/viral-scout-results.json data/buzz-first-lines.json 2>/dev/null || ' +
          '(git add data/viral-scout-results.json data/buzz-first-lines.json && ' +
          `git commit -m "chore: auto update viral-scout results $(date '+%Y-%m-%d')" && ` +
          'git push origin HEAD)',
          { cwd: REPO, stdio: "pipe", shell: "/bin/bash" }
        ).toString();
        console.log("[viral-scout] git push 完了 → Vercel デプロイ開始");
        if (result) console.log(result);
      } catch (e) {
        // 変更なしの場合も含めてエラーは無視（ログだけ残す）
        console.log("[viral-scout] git push スキップ（変更なし or エラー）:", e.message?.slice(0, 80));
      }
    }
  })
  .catch((err) => {
    console.error("[viral-scout] エラー:", err.message);
    process.exit(1);
  });
