#!/usr/bin/env node
// scripts/x/approve.mjs
// 人間承認段（reviewed → approved）＋ 既存投稿レールへの橋渡し。
// reviewed になった投稿を、既存 data/post-queue.json の queue 配列に
// 既存アイテム形状 {status,type,text,url,selfReply,scheduledDate,queuedAt} で
// 追加する。これにより既存 queue-to-sheets.js / sync-posted-status.js が
// そのまま投稿・計測を担当する（新旧パイプラインを二重に持たない）。
//
// 使い方:
//   node scripts/x/approve.mjs --list             # reviewed 一覧
//   node scripts/x/approve.mjs --id gx-...         # 1件承認
//   node scripts/x/approve.mjs --all               # doctor軸(manual)以外を一括承認
//   node scripts/x/approve.mjs --all --include-manual
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { readJsonl, updatePost, jstNow, POSTS_PATH } from "./lib/file-lock.mjs";
import { CONFIG } from "./lib/persona.mjs";

const ROOT = resolve(import.meta.dirname, "../..");
const QUEUE_PATH = resolve(ROOT, "data/post-queue.json");

// doctor 軸（医療）は承認レベル manual を強制（安全側）
function requiresManual(post) {
  if (post.axis === "doctor") return true;
  const t = CONFIG.postTypes?.[post.type];
  return t?.approval === "manual";
}

function loadQueue() {
  try {
    return JSON.parse(readFileSync(QUEUE_PATH, "utf8"));
  } catch {
    return { version: 1, description: "X投稿キュー", queue: [] };
  }
}

function toQueueItem(post) {
  // 既存キューのアイテム形状に合わせる
  return {
    status: "pending",
    type: post.type,
    text: post.body,
    url: (post.sourceUrls && post.sourceUrls[0]) || null,
    selfReply: post.selfReply || null,
    scheduledDate: null,
    queuedAt: jstNow(),
    // トレーサビリティ（既存コンシューマは未知フィールドを無視する）
    _pipelineId: post.id,
    _wiseScores: post.wiseScores || null,
  };
}

function main() {
  const args = process.argv.slice(2);
  const list = args.includes("--list");
  const all = args.includes("--all");
  const includeManual = args.includes("--include-manual");
  const idIdx = args.indexOf("--id");
  const id = idIdx >= 0 ? args[idIdx + 1] : null;

  const posts = readJsonl(POSTS_PATH);
  const reviewed = posts.filter((p) => p.status === "reviewed");

  if (list || (!all && !id)) {
    console.log(`reviewed: ${reviewed.length}件`);
    reviewed.forEach((p) => {
      const s = p.wiseScores || {};
      const man = requiresManual(p) ? " [manual承認必須]" : "";
      console.log(`- ${p.id} (${p.axis}/${p.type})${man} W${s.w ?? "-"}I${s.i ?? "-"}S${s.s ?? "-"}E${s.e ?? "-"}AI${s.ai ?? "-"}`);
      console.log(`    ${p.body.slice(0, 60).replace(/\n/g, " ")}`);
    });
    if (!list) console.log("\n承認: --id <id> / --all（doctor軸除く）/ --all --include-manual");
    return;
  }

  let targets = [];
  if (id) targets = reviewed.filter((p) => p.id === id);
  else if (all) targets = includeManual ? reviewed : reviewed.filter((p) => !requiresManual(p));

  if (targets.length === 0) {
    console.log("承認対象がありません。");
    return;
  }

  const queue = loadQueue();
  let approved = 0;
  for (const post of targets) {
    queue.queue.push(toQueueItem(post));
    updatePost(post.id, { status: "approved", approvedAt: jstNow(), approvedBy: "human" });
    approved++;
    console.log(`[approve] ${post.id} → キュー投入`);
  }
  writeFileSync(QUEUE_PATH, JSON.stringify(queue, null, 2) + "\n", "utf8");
  console.log(`[approve] ${approved}件を post-queue.json に投入。既存 queue-to-sheets が投稿します。`);
  const skipped = reviewed.length - approved;
  if (skipped > 0 && !includeManual)
    console.log(`[approve] manual承認必須 ${skipped}件は保留（--id 個別指定 or --include-manual）。`);
}

main();
