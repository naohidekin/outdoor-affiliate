#!/usr/bin/env node

/**
 * Orchestrator — 週次 / 日次パイプライン制御
 *
 * 全エージェントを順序通りに起動し、パイプライン全体を統括する。
 * 各エージェントは child_process.execFile で起動（プロセス分離）。
 *
 * 使い方:
 *   node scripts/orchestrate.js --pipeline weekly       # 週次パイプライン
 *   node scripts/orchestrate.js --pipeline daily        # 日次パイプライン
 *   node scripts/orchestrate.js --pipeline weekly --dry-run  # 確認のみ
 */

import { execFile } from "child_process";
import { promisify } from "util";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

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
      case "--pipeline":
        opts.pipeline = args[++i];
        break;
      case "--dry-run":
        opts.dryRun = true;
        break;
    }
  }
  return opts;
}

// ─── エージェント起動 ────────────────────────────────

async function runAgent(script, args = [], { timeout = 300_000, captureStdout = false } = {}) {
  const scriptPath = path.join(__dirname, script);
  const startTime = Date.now();
  const label = `${script} ${args.join(" ")}`.trim();

  console.log(`\n${"─".repeat(60)}`);
  console.log(`[orchestrate] 起動: ${label}`);
  console.log(`${"─".repeat(60)}`);

  try {
    const { stdout, stderr } = await execFileAsync(NODE, [scriptPath, ...args], {
      timeout,
      env: process.env,
      cwd: PROJECT_ROOT,
      maxBuffer: 10 * 1024 * 1024, // 10MB
    });

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    if (stdout) console.log(stdout);
    if (stderr) console.error(stderr);
    console.log(`[orchestrate] 完了: ${label} (${elapsed}s)`);

    return { success: true, stdout, stderr };
  } catch (err) {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.error(`[orchestrate] 失敗: ${label} (${elapsed}s)`);
    console.error(`  ${err.message}`);
    if (err.stdout) console.log(err.stdout);
    if (err.stderr) console.error(err.stderr);
    return { success: false, stdout: err.stdout || "", stderr: err.stderr || "", error: err.message };
  }
}

// ─── 週次パイプライン ────────────────────────────────

async function weeklyPipeline(dryRun) {
  console.log("\n╔══════════════════════════════════════════╗");
  console.log("║        週次パイプライン 開始              ║");
  console.log(`║        ${new Date().toISOString().slice(0, 19)}       ║`);
  console.log("╚══════════════════════════════════════════╝\n");

  // 1. Kill switch チェック
  const checkResult = await runAgent("supervisor-agent.js", ["--check"]);
  if (!checkResult.success) {
    console.error("[orchestrate] KILL SWITCH 有効。パイプライン中止。");
    return false;
  }

  // 2. バックアップ
  if (!dryRun) {
    await runAgent("supervisor-agent.js", ["--backup"]);
  } else {
    console.log("[DRY RUN] バックアップをスキップ");
  }

  // 3. Researcher → 週次プラン生成
  const researcherArgs = dryRun ? ["--dry-run"] : [];
  const researchResult = await runAgent("researcher-agent.js", researcherArgs, { captureStdout: true });

  if (researchResult.success && researchResult.stdout) {
    // stdout JSON を weekly-plan.json に保存
    try {
      const planJson = researchResult.stdout.trim();
      // JSON部分を抽出（stderr混入対策）
      const jsonMatch = planJson.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        const planPath = path.join(PROJECT_ROOT, "data", "weekly-plan.json");
        fs.writeFileSync(planPath, jsonMatch[0] + "\n", "utf-8");
        console.log("[orchestrate] data/weekly-plan.json を保存しました");
      }
    } catch (err) {
      console.warn(`[orchestrate] プランJSON保存失敗: ${err.message}`);
    }
  }

  // 4. Analyst → フィードバック更新
  const analystArgs = dryRun ? ["--dry-run"] : [];
  await runAgent("analyst-agent.js", analystArgs);

  // 5. Writer → 投稿生成
  const writerArgs = [];
  const planPath = path.join(PROJECT_ROOT, "data", "weekly-plan.json");
  if (fs.existsSync(planPath)) {
    writerArgs.push("--plan-file", "data/weekly-plan.json");
  }
  if (dryRun) writerArgs.push("--dry-run");
  await runAgent("generate-x-posts.js", writerArgs, { timeout: 600_000 }); // Writer は長時間

  // 6. Supervisor 品質チェック
  await runAgent("supervisor-agent.js", ["--quality-check"]);

  console.log("\n╔══════════════════════════════════════════╗");
  console.log("║        週次パイプライン 完了              ║");
  console.log("╚══════════════════════════════════════════╝\n");
  return true;
}

// ─── 日次パイプライン ────────────────────────────────

async function dailyPipeline(dryRun) {
  console.log("\n┌──────────────────────────────────────────┐");
  console.log("│        日次パイプライン 開始              │");
  console.log(`│        ${new Date().toISOString().slice(0, 19)}       │`);
  console.log("└──────────────────────────────────────────┘\n");

  // 1. Kill switch チェック
  const checkResult = await runAgent("supervisor-agent.js", ["--check"]);
  if (!checkResult.success) {
    console.error("[orchestrate] KILL SWITCH 有効。パイプライン中止。");
    return false;
  }

  // 2. Poster → 本日分を X投稿管理 へ
  if (!dryRun) {
    await runAgent("queue-to-sheets.js", ["--max=1"]);
  } else {
    console.log("[DRY RUN] queue-to-sheets をスキップ");
  }

  // 3. Fetcher → status 同期
  if (!dryRun) {
    await runAgent("sync-posted-status.js", []);
  } else {
    console.log("[DRY RUN] sync-posted-status をスキップ");
  }

  // 4. Analyst → 直近データ追記
  const analystArgs = ["--days", "7"];
  if (dryRun) analystArgs.push("--dry-run");
  await runAgent("analyst-agent.js", analystArgs);

  console.log("\n┌──────────────────────────────────────────┐");
  console.log("│        日次パイプライン 完了              │");
  console.log("└──────────────────────────────────────────┘\n");
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
