#!/usr/bin/env node
// scripts/x/pipeline.mjs
// ギア男 X投稿 段階分割パイプライン オーケストレーター（amble 踏襲）。
//   researcher → writer → reviewer(GPT独立採点) → evidence(校閲) → opsec(ガード)
// 各段が status をゲートし、落ちた投稿は rejected。生き残りは reviewed になり、
// 人間承認(approve.mjs / dashboard)→ posted へ進む。
//
// 使い方:
//   node scripts/x/pipeline.mjs --ideas 10 --posts 6         # 本番
//   node scripts/x/pipeline.mjs --dry-run                    # 破壊せず流す
//   node scripts/x/pipeline.mjs --from writer                # 途中段から
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { isKillSwitchOn, readJsonl, POSTS_PATH } from "./lib/file-lock.mjs";

const STAGES = ["researcher", "writer", "reviewer", "evidence", "opsec"];

async function runStep(name, fn) {
  console.log(`\n${"=".repeat(48)}\nSTEP: ${name.toUpperCase()}\n${"=".repeat(48)}`);
  try {
    return await fn();
  } catch (e) {
    console.error(`[pipeline] ${name} failed: ${e.message}`);
    return { error: e.message };
  }
}

async function main() {
  if (isKillSwitchOn()) {
    console.log("[pipeline] kill-switch ON。終了。");
    return;
  }
  const args = process.argv.slice(2);
  const getNum = (flag, def) => {
    const i = args.indexOf(flag);
    return i >= 0 ? parseInt(args[i + 1], 10) : def;
  };
  const dryRun = args.includes("--dry-run");
  const ideas = getNum("--ideas", 10);
  const posts = getNum("--posts", 6);
  const fromIdx = args.indexOf("--from");
  const startStage = fromIdx >= 0 ? args[fromIdx + 1] : STAGES[0];
  const startFrom = Math.max(0, STAGES.indexOf(startStage));

  const { runResearcher } = await import("./researcher.mjs");
  const { runWriter } = await import("./writer.mjs");
  const { runReviewer } = await import("./reviewer.mjs");
  const { runEvidenceChecker } = await import("./evidence-checker.mjs");
  const { runOpsecChecker } = await import("./opsec-checker.mjs");

  const results = {};
  if (startFrom <= 0) results.researcher = await runStep("researcher", () => runResearcher({ count: ideas, dryRun }));
  if (startFrom <= 1) results.writer = await runStep("writer", () => runWriter({ count: posts, dryRun }));
  if (startFrom <= 2) results.reviewer = await runStep("reviewer", () => runReviewer({ dryRun }));
  if (startFrom <= 3) results.evidence = await runStep("evidence", () => runEvidenceChecker({ dryRun }));
  if (startFrom <= 4) results.opsec = await runStep("opsec", () => runOpsecChecker({ dryRun }));

  // サマリ
  console.log(`\n${"=".repeat(48)}\nPIPELINE SUMMARY${dryRun ? " (dry-run)" : ""}\n${"=".repeat(48)}`);
  const all = readJsonl(POSTS_PATH);
  const byStatus = {};
  all.forEach((p) => (byStatus[p.status] = (byStatus[p.status] || 0) + 1));
  console.log(`posts.jsonl total: ${all.length}`);
  for (const [s, c] of Object.entries(byStatus).sort()) console.log(`  ${s}: ${c}`);
  console.log("\n次: reviewed の投稿を承認 → キュー投入");
  console.log("  node scripts/x/approve.mjs   （または admin ダッシュボード）");
}

main().catch((e) => {
  console.error(`[pipeline] Fatal: ${e.message}`);
  process.exit(1);
});
