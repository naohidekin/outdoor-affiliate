#!/usr/bin/env node

/**
 * Article Orchestrator — 記事パイプラインの統括制御
 *
 * 使い方:
 *   node scripts/article-orchestrate.js --pipeline weekly    # 週次（水曜09:00）
 *   node scripts/article-orchestrate.js --pipeline daily     # 日次（毎日10:00）
 *   node scripts/article-orchestrate.js --pipeline weekly --dry-run
 */

import { execFile } from "child_process";
import { promisify } from "util";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv, readJson } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.join(__dirname, "..");
const NODE = process.argv[0];

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { pipeline: null, dryRun: false };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--pipeline": opts.pipeline = args[++i]; break;
      case "--dry-run":  opts.dryRun = true; break;
    }
  }
  return opts;
}

// ─── エージェント起動（orchestrate.js と同じパターン） ──

async function runAgent(script, args = [], { timeout = 300_000 } = {}) {
  const scriptPath = path.join(__dirname, script);
  const startTime = Date.now();
  const label = `${script} ${args.join(" ")}`.trim();

  console.log(`\n${"─".repeat(60)}`);
  console.log(`[article-orchestrate] 起動: ${label}`);
  console.log(`${"─".repeat(60)}`);

  try {
    const { stdout, stderr } = await execFileAsync(NODE, [scriptPath, ...args], {
      timeout,
      env: process.env,
      cwd: PROJECT_ROOT,
      maxBuffer: 10 * 1024 * 1024,
    });

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    if (stdout) console.log(stdout);
    if (stderr) console.error(stderr);
    console.log(`[article-orchestrate] 完了: ${label} (${elapsed}s)`);
    return { success: true, stdout, stderr };
  } catch (err) {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.error(`[article-orchestrate] 失敗: ${label} (${elapsed}s)`);
    console.error(`  ${err.message}`);
    if (err.stdout) console.log(err.stdout);
    if (err.stderr) console.error(err.stderr);
    return { success: false, error: err.message };
  }
}

// ─── 週次パイプライン ────────────────────────────────

async function weeklyPipeline(dryRun) {
  console.log("\n╔══════════════════════════════════════════════╗");
  console.log("║     記事パイプライン（週次）開始              ║");
  console.log(`║     ${new Date().toISOString().slice(0, 19)}           ║`);
  console.log("╚══════════════════════════════════════════════╝\n");

  // 0. Kill Switch チェック
  const checkResult = await runAgent("supervisor-agent.js", ["--check"]);
  if (!checkResult.success) {
    console.error("[article-orchestrate] KILL SWITCH 有効。中止。");
    return false;
  }
  const ksData = readJson("kill-switch.json");
  if (ksData?.articleEnabled) {
    console.error("[article-orchestrate] 記事パイプライン Kill Switch 有効。中止。");
    return false;
  }

  // 1. バックアップ
  if (!dryRun) {
    await runAgent("supervisor-agent.js", ["--backup"]);
  }

  // 2. Analyst → フィードバック更新
  const analystArgs = dryRun ? ["--dry-run"] : [];
  await runAgent("article-analyst-agent.js", analystArgs);

  // 3. Researcher → テーマ選定
  const researcherArgs = dryRun ? ["--dry-run"] : [];
  const researchResult = await runAgent("article-researcher-agent.js", researcherArgs);
  if (!researchResult.success) {
    console.error("[article-orchestrate] テーマ選定失敗。中止。");
    return false;
  }

  // 4. Product Agent → 商品調査
  const productArgs = dryRun ? ["--dry-run"] : [];
  const productResult = await runAgent("article-product-agent.js", productArgs);
  if (!productResult.success) {
    console.error("[article-orchestrate] 商品調査失敗。中止。");
    return false;
  }

  // 5. Writer → 記事生成（長時間かかる可能性）
  const writerArgs = dryRun ? ["--dry-run"] : [];
  await runAgent("article-writer-agent.js", writerArgs, { timeout: 600_000 });

  // 6. Publisher → 即日公開分を処理
  if (!dryRun) {
    await runAgent("article-publisher-agent.js", []);
  }

  // 7. 品質チェック
  await runAgent("supervisor-agent.js", ["--quality-check"]);

  console.log("\n╔══════════════════════════════════════════════╗");
  console.log("║     記事パイプライン（週次）完了              ║");
  console.log("╚══════════════════════════════════════════════╝\n");
  return true;
}

// ─── 日次パイプライン ────────────────────────────────

async function dailyPipeline(dryRun) {
  console.log("\n┌──────────────────────────────────────────────┐");
  console.log("│     記事パイプライン（日次）開始              │");
  console.log(`│     ${new Date().toISOString().slice(0, 19)}           │`);
  console.log("└──────────────────────────────────────────────┘\n");

  // 0. Kill Switch チェック
  const checkResult = await runAgent("supervisor-agent.js", ["--check"]);
  if (!checkResult.success) {
    console.error("[article-orchestrate] KILL SWITCH 有効。中止。");
    return false;
  }
  const ksData = readJson("kill-switch.json");
  if (ksData?.articleEnabled) {
    console.error("[article-orchestrate] 記事パイプライン Kill Switch 有効。中止。");
    return false;
  }

  // 1. Publisher → 本日公開予定の記事を公開
  if (!dryRun) {
    await runAgent("article-publisher-agent.js", []);
  } else {
    await runAgent("article-publisher-agent.js", ["--dry-run"]);
  }

  // 2. Analyst → 直近7日の記事PV更新
  const analystArgs = ["--days", "7"];
  if (dryRun) analystArgs.push("--dry-run");
  await runAgent("article-analyst-agent.js", analystArgs);

  console.log("\n┌──────────────────────────────────────────────┐");
  console.log("│     記事パイプライン（日次）完了              │");
  console.log("└──────────────────────────────────────────────┘\n");
  return true;
}

// ─── エントリポイント ────────────────────────────────

const opts = parseArgs();

if (!opts.pipeline || !["weekly", "daily"].includes(opts.pipeline)) {
  console.log("使い方: --pipeline weekly|daily [--dry-run]");
  process.exit(0);
}

const success = opts.pipeline === "weekly"
  ? await weeklyPipeline(opts.dryRun)
  : await dailyPipeline(opts.dryRun);

process.exit(success ? 0 : 1);
