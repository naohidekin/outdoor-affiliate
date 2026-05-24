#!/usr/bin/env node
/**
 * ギア男 エンゲージスカウト CLI
 *
 * バイラル投稿を検索し、ペルソナに合ったリプライを生成する。
 * 共通エンジン (viral-engage-core.mjs) を使用。
 *
 * Usage:
 *   node scripts/engage-scout.js --days=2 --count=35 --min-score=30
 *   node scripts/engage-scout.js --dry-run
 *   node scripts/engage-scout.js --axis=camp --count=10
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { runViralEngage, parseArgs } from "../../lib/viral-engage-core.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_DIR = path.resolve(__dirname, "..");

// engage-config.json を読み込み
const configPath = path.join(PROJECT_DIR, "data", "engage-config.json");
const config = JSON.parse(fs.readFileSync(configPath, "utf-8"));

// storage.basePath を絶対パスに変換
config.storage.basePath = path.join(PROJECT_DIR, config.storage.basePath || "data");

// CLI オプション解析
const validAxes = config.axes.map((a) => a.id);
const opts = parseArgs(validAxes);

// 実行
runViralEngage(config, opts, { projectDir: PROJECT_DIR })
  .then((result) => {
    const draftCount = (result.posts || []).filter(
      (p) => p.generatedContent?.reply?.status === "draft"
    ).length;
    console.log(`\n=== 結果 ===`);
    console.log(`スカウト: ${result.scouted}件 / 生成: ${result.generated}件 / 合格リプライ: ${draftCount}件`);
    process.exit(0);
  })
  .catch((err) => {
    console.error("エラー:", err.message);
    process.exit(1);
  });
