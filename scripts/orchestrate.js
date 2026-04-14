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
import { loadEnv, readJson, writeJson } from "../src/lib/x-agent-utils.mjs";

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

// ─── Git 同期 ───────────────────────────────────────

async function gitPull() {
  console.log("[orchestrate] git pull --ff-only ...");
  try {
    const { stdout } = await execFileAsync("git", ["pull", "--ff-only"], {
      cwd: PROJECT_ROOT,
      timeout: 30_000,
    });
    console.log(`[orchestrate] ${stdout.trim() || "Already up to date."}`);
    return true;
  } catch (err) {
    console.error(`[orchestrate] git pull 失敗: ${err.message}`);
    return false;
  }
}

async function gitCommitAndPush(message) {
  try {
    const { stdout: status } = await execFileAsync("git", ["status", "--porcelain"], {
      cwd: PROJECT_ROOT,
    });
    if (!status.trim()) {
      console.log("[orchestrate] 変更なし。コミットスキップ。");
      return true;
    }

    await execFileAsync("git", ["add", "data/"], { cwd: PROJECT_ROOT });
    await execFileAsync("git", [
      "commit", "-m", `${message}\n\nCo-Authored-By: X Pipeline <noreply@anthropic.com>`,
    ], { cwd: PROJECT_ROOT, timeout: 15_000 });
    await execFileAsync("git", ["push"], { cwd: PROJECT_ROOT, timeout: 30_000 });
    console.log(`[orchestrate] git push 完了`);
    return true;
  } catch (err) {
    console.error(`[orchestrate] git commit/push 失敗: ${err.message}`);
    return false;
  }
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
    // 連続エラーをkill-switch.jsonに記録
    const ks = readJson("kill-switch.json") || {};
    const errors = ks.consecutiveErrors || [];
    errors.push({ type: `agent-fail:${script}`, at: new Date().toISOString() });
    ks.consecutiveErrors = errors.slice(-5); // 直近5件保持
    writeJson("kill-switch.json", ks);

    // 3連続で自動KILL
    if (ks.consecutiveErrors.length >= 3) {
      console.error(`[orchestrate] 連続エラー${ks.consecutiveErrors.length}回。自動KILL SWITCH 有効化。`);
      ks.enabled = true;
      ks.reason = `連続エラー${ks.consecutiveErrors.length}回: ${errors.slice(-3).map((e) => e.type).join(", ")}`;
      ks.enabledAt = new Date().toISOString();
      ks.enabledBy = "auto-orchestrate";
      writeJson("kill-switch.json", ks);
    }

    return { success: false, stdout: err.stdout || "", stderr: err.stderr || "", error: err.message };
  }
}

// エージェント成功時にエラーカウントをリセット
function clearOrchestrateErrors() {
  const ks = readJson("kill-switch.json") || {};
  if (ks.consecutiveErrors?.length > 0) {
    ks.consecutiveErrors = [];
    writeJson("kill-switch.json", ks);
  }
}

// ─── 週次パイプライン ────────────────────────────────

async function weeklyPipeline(dryRun) {
  console.log("\n╔══════════════════════════════════════════╗");
  console.log("║        週次パイプライン 開始              ║");
  console.log(`║        ${new Date().toISOString().slice(0, 19)}       ║`);
  console.log("╚══════════════════════════════════════════╝\n");

  // 0. Git pull（最新取得）
  if (!dryRun) {
    const pulled = await gitPull();
    if (!pulled) {
      console.error("[orchestrate] git pull 失敗。手動で解決してください。");
      return false;
    }
  }

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

  // 3a. リサーチソース（全ソースを順次実行、API未設定のソースは自動スキップ）
  const researchSources = [
    { script: "youtube-researcher.js", envKey: "YOUTUBE_API_KEY", label: "YouTube" },
    { script: "research-sources/google-trends.js", envKey: "GOOGLE_CUSTOM_SEARCH_KEY", label: "Google検索" },
    { script: "research-sources/rakuten-ranking.js", envKey: "RAKUTEN_APP_ID", label: "楽天ランキング" },
    { script: "research-sources/amazon-reviews.js", envKey: "AMAZON_ACCESS_KEY", label: "Amazon" },
  ];

  for (const src of researchSources) {
    if (process.env[src.envKey]) {
      const srcArgs = dryRun ? ["--dry-run"] : [];
      console.log(`[orchestrate] ${src.label} リサーチ開始`);
      await runAgent(src.script, srcArgs, { timeout: 600_000 });
    } else {
      console.log(`[orchestrate] ${src.envKey} 未設定。${src.label} リサーチをスキップ`);
    }
  }

  // 3b. Researcher → 週次プラン生成
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

  // 7. Supervisor 週次レポート生成
  await runAgent("supervisor-agent.js", ["--weekly-report"]);

  // 8. ログローテーション（30日超のログ・バックアップを削除）
  try {
    const { execFileSync } = await import("child_process");
    execFileSync("bash", [path.join(__dirname, "rotate-logs.sh")], {
      cwd: PROJECT_ROOT,
      stdio: "inherit",
    });
  } catch (err) {
    console.warn(`[orchestrate] ログローテーション失敗（継続）: ${err.message}`);
  }

  // 9. Git commit & push
  if (!dryRun) {
    await gitCommitAndPush("data: X投稿パイプライン週次実行");
  }

  // パイプライン正常完了 → エラーカウントリセット
  clearOrchestrateErrors();

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

  // 0. Git pull（最新取得）
  if (!dryRun) {
    const pulled = await gitPull();
    if (!pulled) {
      console.error("[orchestrate] git pull 失敗。手動で解決してください。");
      return false;
    }
  }

  // 1. Kill switch チェック
  const dailyCheckResult = await runAgent("supervisor-agent.js", ["--check"]);
  if (!dailyCheckResult.success) {
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

  // 5. Git commit & push
  if (!dryRun) {
    await gitCommitAndPush("data: X投稿パイプライン日次実行");
  }

  // パイプライン正常完了 → エラーカウントリセット
  clearOrchestrateErrors();

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
