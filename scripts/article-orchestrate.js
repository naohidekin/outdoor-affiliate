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
import { loadEnv, readJson, writeJson, checkArticleKillSwitch } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.join(__dirname, "..");
const NODE = process.argv[0];

function jstDateString(d = new Date()) {
  return new Date(d.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstDateTimeString(d = new Date()) {
  const shifted = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  return shifted.toISOString().slice(0, 19).replace("T", " ");
}

function jstIsoString(d = new Date()) {
  const shifted = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  return `${shifted.toISOString().slice(0, 19)}+09:00`;
}

// エラーログに日時を入れる。
//
// 2026-08-16: launchd のエラーログは追記のみで日時が無く、
// 「git pull 失敗」「連続エラー3回で自動停止」が並んでいても、
// それが今朝のものか何日も前の残骸か区別できなかった。
// 障害の切り分けが止まるので、少なくともエラー側には必ず時刻を打つ。
// stdout 側は起動バナーに日時が入っているのでそのままにする。
const rawConsoleError = console.error.bind(console);
console.error = (...args) => rawConsoleError(`[${jstDateTimeString()} JST]`, ...args);

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

// ─── Git 同期 ───────────────────────────────────────

async function gitPull() {
  console.log("[article-orchestrate] git pull --ff-only ...");
  try {
    const { stdout } = await execFileAsync("git", ["pull", "--ff-only"], {
      cwd: PROJECT_ROOT,
      timeout: 30_000,
    });
    console.log(`[article-orchestrate] ${stdout.trim() || "Already up to date."}`);
    return true;
  } catch (err) {
    console.warn(`[article-orchestrate] git pull --ff-only 失敗。stash → pull → pop で再試行...`);
    try {
      await execFileAsync("git", ["stash"], { cwd: PROJECT_ROOT, timeout: 10_000 });
      await execFileAsync("git", ["pull", "--ff-only"], { cwd: PROJECT_ROOT, timeout: 30_000 });
      try {
        await execFileAsync("git", ["stash", "pop"], { cwd: PROJECT_ROOT, timeout: 10_000 });
      } catch {
        console.warn("[article-orchestrate] stash pop で競合。stashは保持。");
      }
      console.log("[article-orchestrate] git pull（stash経由）成功");
      return true;
    } catch (retryErr) {
      console.error(`[article-orchestrate] git pull 再試行も失敗: ${retryErr.message}`);
      return false;
    }
  }
}

async function gitCommitAndPush(message) {
  try {
    // 変更があるか確認
    const { stdout: status } = await execFileAsync("git", ["status", "--porcelain"], {
      cwd: PROJECT_ROOT,
    });
    if (!status.trim()) {
      console.log("[article-orchestrate] 変更なし。コミットスキップ。");
      return true;
    }

    await execFileAsync("git", ["add", "data/"], { cwd: PROJECT_ROOT });
    await execFileAsync("git", [
      "commit", "-m", `${message}\n\nCo-Authored-By: Article Pipeline <noreply@anthropic.com>`,
    ], { cwd: PROJECT_ROOT, timeout: 15_000 });

    // リモートが先に進んでいると push が弾かれ、ローカルにコミットだけが
    // 取り残される（次回以降 divergent branches で pull も止まる）。
    // commit 後に rebase で載せ替えてから push する。
    // 競合時は自動解決を試みず中断し、人が直す（データJSONを機械的に
    // 片側へ倒すと記事や商品が丸ごと消えるため）
    const pushWithRebase = async () => {
      try {
        await execFileAsync("git", ["pull", "--rebase"], {
          cwd: PROJECT_ROOT,
          timeout: 60_000,
        });
      } catch (err) {
        await execFileAsync("git", ["rebase", "--abort"], {
          cwd: PROJECT_ROOT,
        }).catch(() => {});
        throw new Error(`rebase失敗（競合の可能性・手動対応が必要）: ${err.message}`);
      }
      await execFileAsync("git", ["push"], { cwd: PROJECT_ROOT, timeout: 30_000 });
    };
    await pushWithRebase();
    console.log(`[article-orchestrate] git push 完了`);
    return true;
  } catch (err) {
    console.error(`[article-orchestrate] git commit/push 失敗: ${err.message}`);
    return false;
  }
}

// ─── エージェント起動（orchestrate.js と同じパターン） ──

/**
 * optional: true を渡したステップは、失敗しても連続失敗カウンタに数えない。
 * 記事の生成・公開に必須でない補助処理（クリック実績の取り込み等）が
 * 一時的なネットワーク障害で落ちただけで、3回連続に達して
 * パイプライン全体がキルスイッチで止まるのを避けるため。
 */
async function runAgent(script, args = [], { timeout = 300_000, optional = false } = {}) {
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
    if (optional) {
      console.error(`[article-orchestrate] ${script} は補助処理のため続行します`);
      return { success: false, error: err.message };
    }
    // 同一パイプライン実行内の連続失敗を記録
    articleConsecutiveFailures++;
    console.error(`[article-orchestrate] 連続失敗: ${articleConsecutiveFailures}回目`);

    // 3連続で自動KILL（記事パイプラインのみ停止）
    if (articleConsecutiveFailures >= 3) {
      console.error(`[article-orchestrate] 連続エラー${articleConsecutiveFailures}回。記事パイプライン自動停止。`);
      const ks = readJson("kill-switch.json") || {};
      ks.articleEnabled = true;
      ks.reason = `記事パイプライン連続エラー${articleConsecutiveFailures}回（最後: ${script}）`;
      ks.enabledAt = jstIsoString();
      ks.enabledBy = "auto-article-orchestrate";
      writeJson("kill-switch.json", ks);
    }

    return { success: false, error: err.message };
  }
}

async function runCodexReviewer(articleId) {
  const reviewed = await runAgent("article-codex-reviewer.js", ["--article-id", articleId], { timeout: 300_000 });
  if (!reviewed.success || !reviewed.stdout) return null;
  // stdoutの各行を末尾から走査し、最初にパースできるJSONを返す
  const lines = reviewed.stdout.trim().split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (!line.startsWith("{")) continue;
    try {
      return JSON.parse(line);
    } catch {
      // この行はJSONではない — 次の行を試す
    }
  }
  // 行単位で見つからなければ従来方式（非貪欲マッチ）でフォールバック
  const match = reviewed.stdout.match(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/);
  if (!match) return null;
  try {
    return JSON.parse(match[0]);
  } catch {
    console.warn("[article-orchestrate] Codex Reviewer JSON解析失敗");
    return null;
  }
}

async function runSupervisorGate(articleId, cycle) {
  const result = await runAgent("supervisor-agent.js", ["--evaluate-article", articleId, "--cycle", String(cycle)]);
  if (!result.success || !result.stdout) return null;
  // stdoutの各行を末尾から走査し、最初にパースできるJSONを返す
  const lines = result.stdout.trim().split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (!line.startsWith("{")) continue;
    try {
      return JSON.parse(line);
    } catch {
      // この行はJSONではない
    }
  }
  const match = result.stdout.match(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/);
  if (!match) return null;
  try {
    return JSON.parse(match[0]);
  } catch {
    return null;
  }
}

function extractWriterArticleIdsFromStdout(stdout = "") {
  const ids = [];
  if (!stdout) return ids;
  const regex = /\{[\s\S]*?\}/g;
  const chunks = stdout.match(regex) || [];
  for (const chunk of chunks) {
    try {
      const parsed = JSON.parse(chunk);
      if (typeof parsed?.articleId === "string" && parsed.articleId) ids.push(parsed.articleId);
      if (Array.isArray(parsed?.articleIds)) {
        for (const id of parsed.articleIds) {
          if (typeof id === "string" && id) ids.push(id);
        }
      }
    } catch {
      // ignore non-JSON chunks
    }
  }
  return [...new Set(ids)];
}

function pickLatestDraftArticleId({ excludedIds = new Set(), beforeTimeMs = 0 } = {}) {
  const all = readJson("articles.json") || [];
  let latest = null;
  for (const article of all) {
    if (!article || article.status !== "draft" || !article.id || excludedIds.has(article.id)) continue;
    const tsRaw = article.updatedAt || article.createdAt;
    const ts = tsRaw ? Date.parse(tsRaw) : NaN;
    if (Number.isNaN(ts) || ts < beforeTimeMs) continue;
    if (!latest) {
      latest = article;
      continue;
    }
    const latestTs = Date.parse(latest.updatedAt || latest.createdAt || "");
    if (Number.isNaN(latestTs) || ts > latestTs) latest = article;
  }
  return latest?.id || null;
}

function appendRejectedArticle(articleId, gate, cycle = 2) {
  const articles = readJson("articles.json") || [];
  const article = articles.find((a) => a.id === articleId);
  if (!article) return;

  const rejected = readJson("rejected.json") || [];
  const duplicate = rejected.some((r) => r?.id === articleId && Number(r?.cycle) === Number(cycle));
  if (duplicate) return;

  rejected.push({
    id: article.id,
    slug: article.slug,
    title: article.title,
    cycle: Number(cycle),
    score: Number(gate?.score || 0),
    feedback: Array.isArray(gate?.feedback) ? gate.feedback : [],
    rejectedAt: jstIsoString(),
  });
  writeJson("rejected.json", rejected);
}

// パイプライン実行内の連続失敗カウンタ
let articleConsecutiveFailures = 0;

// エージェント成功時にカウンタリセット
function resetArticleFailures() {
  articleConsecutiveFailures = 0;
}

// ─── 週次パイプライン ────────────────────────────────

async function weeklyPipeline(dryRun) {
  console.log("\n╔══════════════════════════════════════════════╗");
  console.log("║     記事パイプライン（週次）開始              ║");
  console.log(`║     ${jstDateTimeString()} JST      ║`);
  console.log("╚══════════════════════════════════════════════╝\n");

  // 0. Git pull（最新取得）
  if (!dryRun) {
    const pulled = await gitPull();
    if (!pulled) {
      console.error("[article-orchestrate] git pull 失敗。手動で解決してください。");
      return false;
    }
  }

  // 1. Kill Switch チェック（統合チェック: enabled + articleEnabled）
  const ks = checkArticleKillSwitch();
  if (ks.killed) {
    console.error(`[article-orchestrate] ${ks.reason || "KILL SWITCH 有効"}。中止。`);
    return false;
  }

  // 2. バックアップ
  if (!dryRun) {
    await runAgent("supervisor-agent.js", ["--backup"]);
  }

  // 3. Analyst → フィードバック更新
  const analystArgs = dryRun ? ["--dry-run"] : [];
  await runAgent("article-analyst-agent.js", analystArgs);

  // 4. Researcher → テーマ選定
  const researcherArgs = dryRun ? ["--dry-run"] : [];
  const researchResult = await runAgent("article-researcher-agent.js", researcherArgs);
  if (!researchResult.success) {
    console.error("[article-orchestrate] テーマ選定失敗。中止。");
    return false;
  }

  // 5. Product Agent → 商品調査
  const productArgs = dryRun ? ["--dry-run"] : [];
  const productResult = await runAgent("article-product-agent.js", productArgs);
  if (!productResult.success) {
    console.error("[article-orchestrate] 商品調査失敗。中止。");
    return false;
  }

  // 5.5 商品画像の空白検出・修復（非ブロッキング）
  // Amazon P/{ASIN} 形式は画像未登録でも200で空白GIFを返すため、
  // 新規収集分を含む全商品を実バイト数で検査し、楽天API画像へ差し替える。
  // 失敗しても記事生成には影響しないため警告のみで続行する。
  {
    const fixArgs = dryRun ? ["--dry-run"] : [];
    const imageFixResult = await runAgent("fix-blank-amazon-images.mjs", fixArgs, {
      timeout: 600_000,
    });
    if (!imageFixResult.success) {
      console.warn("[article-orchestrate] 商品画像修復に失敗しましたが続行します");
    }
  }

  // 6. Writer + Codex Reviewer + Supervisor（max 2 cycles）
  const writerStartMs = Date.now();
  const beforeArticles = readJson("articles.json") || [];
  const beforeIds = new Set(beforeArticles.map((a) => a.id));
  const writerArgs = dryRun ? ["--dry-run"] : [];
  const writerRun = await runAgent("article-writer-agent.js", writerArgs, { timeout: 600_000 });
  if (!writerRun.success) {
    console.error("[article-orchestrate] Writer失敗。中止。");
    return false;
  }

  if (!dryRun) {
    const reviewerTargets = [];
    const idsFromWriter = extractWriterArticleIdsFromStdout(writerRun.stdout || "");
    for (const id of idsFromWriter) reviewerTargets.push(id);

    if (reviewerTargets.length === 0) {
      const latestId = pickLatestDraftArticleId({ excludedIds: beforeIds, beforeTimeMs: writerStartMs });
      if (latestId) reviewerTargets.push(latestId);
    }

    if (reviewerTargets.length === 0) {
      const afterFirst = readJson("articles.json") || [];
      const newArticles = afterFirst.filter((a) => !beforeIds.has(a.id));
      for (const article of newArticles) reviewerTargets.push(article.id);
    }

    const uniqueReviewerTargets = [...new Set(reviewerTargets)];
    for (const articleId of uniqueReviewerTargets) {
      const article = (readJson("articles.json") || []).find((a) => a.id === articleId);
      if (!article || article.status === "published") continue;

      let cycle = 1;
      let gate = null;
      let feedbackPayload = null;

      try {
        const codexResult = await runCodexReviewer(articleId);
        if (codexResult) {
          const latest = readJson("articles.json") || [];
          const idx = latest.findIndex((x) => x.id === articleId);
          if (idx >= 0) {
            if (typeof codexResult.revised_content === "string" && codexResult.revised_content.trim()) {
              latest[idx].content = codexResult.revised_content;
            }
            latest[idx].wise_scores = codexResult.wise_scores || null;
            latest[idx].updatedAt = jstIsoString();
            writeJson("articles.json", latest);
          }
        }
      } catch (e) {
        console.warn("[orchestrate] Codex Reviewer スキップ:", e.message);
      }

      gate = await runSupervisorGate(articleId, cycle);
      const cycle1Passed = gate?.passed === true && Number(gate?.score || 0) >= 7.5;
      if (!cycle1Passed) {
        cycle = 2;
        feedbackPayload = {
          wise_scores: (readJson("articles.json") || []).find((x) => x.id === articleId)?.wise_scores || null,
          feedback: gate.feedback || [],
        };
        await runAgent("article-writer-agent.js", ["--retry", articleId, "--feedback-json", JSON.stringify(feedbackPayload)], { timeout: 600_000 });

        try {
          const codexResultCycle2 = await runCodexReviewer(articleId);
          if (codexResultCycle2) {
            const latest = readJson("articles.json") || [];
            const idx = latest.findIndex((x) => x.id === articleId);
            if (idx >= 0) {
              if (typeof codexResultCycle2.revised_content === "string" && codexResultCycle2.revised_content.trim()) {
                latest[idx].content = codexResultCycle2.revised_content;
              }
              latest[idx].wise_scores = codexResultCycle2.wise_scores || null;
              latest[idx].updatedAt = jstIsoString();
              writeJson("articles.json", latest);
            }
          }
        } catch (e) {
          console.warn("[orchestrate] Codex Reviewer(2nd) スキップ:", e.message);
        }

        gate = await runSupervisorGate(articleId, cycle);
        const cycle2Passed = gate?.passed === true && Number(gate?.score || 0) >= 7.5;
        if (!cycle2Passed) {
          appendRejectedArticle(articleId, gate, 2);
          console.warn(`[article-orchestrate] articleId=${articleId} を rejected.json に記録しました`);
        }
      }
    }
  }

  // 7. Publisher → 即日公開分を処理
  if (!dryRun) {
    await runAgent("article-publisher-agent.js", []);
  }

  // 8. 品質チェック
  await runAgent("supervisor-agent.js", ["--quality-check"]);

  // 9. Git commit & push
  if (!dryRun) {
    await gitCommitAndPush("data: 記事パイプライン週次実行");
  }

  // 10. Supabase同期
  if (!dryRun) {
    await runAgent("sync-to-supabase.js", []);
  }

  // パイプライン正常完了 → エラーカウントリセット
  resetArticleFailures();

  console.log("\n╔══════════════════════════════════════════════╗");
  console.log("║     記事パイプライン（週次）完了              ║");
  console.log("╚══════════════════════════════════════════════╝\n");
  return true;
}

// ─── 日次パイプライン ────────────────────────────────

async function dailyPipeline(dryRun) {
  console.log("\n┌──────────────────────────────────────────────┐");
  console.log("│     記事パイプライン（日次）開始              │");
  console.log(`│     ${jstDateTimeString()} JST      │`);
  console.log("└──────────────────────────────────────────────┘\n");

  // 0. Git pull（最新取得）
  if (!dryRun) {
    const pulled = await gitPull();
    if (!pulled) {
      console.error("[article-orchestrate] git pull 失敗。手動で解決してください。");
      return false;
    }
  }

  // 1. Kill Switch チェック（統合チェック: enabled + articleEnabled）
  const ks2 = checkArticleKillSwitch();
  if (ks2.killed) {
    console.error(`[article-orchestrate] ${ks2.reason || "KILL SWITCH 有効"}。中止。`);
    return false;
  }

  // 2. Publisher → 本日公開予定の記事を公開
  if (!dryRun) {
    await runAgent("article-publisher-agent.js", []);
  } else {
    await runAgent("article-publisher-agent.js", ["--dry-run"]);
  }

  // 2.5 クリック実績を Supabase から取り込む
  // これが無いと Analyst が空の affiliate-clicks.json を読み、CTRが常に0になる。
  // 2026-08-13 まで実際にそうなっており、記事評価がPVだけで行われていた。
  // 補助処理なので失敗しても続行し、連続失敗カウンタにも数えない
  // （クリックが取れなくてもPV分析は成立する）
  if (!dryRun) {
    await runAgent("pull-affiliate-clicks.mjs", ["--write"], { optional: true });
  }

  // 3. Analyst → 直近7日の記事PV更新
  const analystArgs2 = ["--days", "7"];
  if (dryRun) analystArgs2.push("--dry-run");
  await runAgent("article-analyst-agent.js", analystArgs2);

  // 4. Git commit & push
  if (!dryRun) {
    await gitCommitAndPush("data: 記事パイプライン日次実行");
  }

  // 5. Supabase同期
  if (!dryRun) {
    await runAgent("sync-to-supabase.js", ["--articles-only"]);
  }

  // パイプライン正常完了 → エラーカウントリセット
  resetArticleFailures();

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
