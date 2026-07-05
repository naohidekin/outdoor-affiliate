#!/usr/bin/env node
// scripts/x/reply-cleanup.mjs
// GearMan Replies DB を軽くする整理ツール。既定は「集計を見るだけ(安全)」。
// フラグを付けた時だけアーカイブ（Notionゴミ箱へ＝30日は復元可能。ハード削除しない）。
//   node scripts/x/reply-cleanup.mjs                      # 集計だけ表示(何もしない)
//   node scripts/x/reply-cleanup.mjs --archive-rejected   # 却下をアーカイブ
//   node scripts/x/reply-cleanup.mjs --archive-posted-days 30  # 30日より前の投稿済みをアーカイブ
// draft / approved（生きてる行）は常に残す。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import {
  GEARMAN_REPLIES_DB_ID,
  hasNotionToken,
  notionQueryAll,
  notionArchivePage,
  propSelect,
} from "./lib/notion.mjs";

const KEEP = new Set(["draft", "approved"]); // 絶対に消さない

function daysAgo(iso) {
  if (!iso) return Infinity;
  return (Date.now() - new Date(iso).getTime()) / 86400000;
}

export async function runCleanup({ archiveRejected = false, archivePostedDays = null } = {}) {
  if (!hasNotionToken()) return console.warn("[cleanup] NOTION_TOKEN 未設定。終了。");
  const pages = await notionQueryAll(GEARMAN_REPLIES_DB_ID);
  console.log(`[cleanup] GearMan Replies 全 ${pages.length} 行`);

  // ステータス別集計
  const byStatus = {};
  for (const pg of pages) {
    const st = propSelect(pg.properties, "ステータス") || "(空)";
    byStatus[st] = (byStatus[st] || 0) + 1;
  }
  console.log("  ステータス別:");
  for (const [s, c] of Object.entries(byStatus).sort((a, b) => b[1] - a[1])) console.log(`    ${s}: ${c}`);

  // アーカイブ対象を決める
  const targets = [];
  for (const pg of pages) {
    const st = propSelect(pg.properties, "ステータス");
    if (KEEP.has(st)) continue;
    if (archiveRejected && st === "rejected") targets.push(pg);
    else if (archivePostedDays != null && ["posted", "投稿済み"].includes(st) && daysAgo(pg.last_edited_time) > archivePostedDays) {
      targets.push(pg);
    }
  }

  if (!archiveRejected && archivePostedDays == null) {
    console.log("\n集計のみ（何も変更していません）。実際に減らすには:");
    console.log("  却下を片付ける:      npm run x:v2:reply:cleanup -- --archive-rejected");
    console.log("  古い投稿済みを片付ける: npm run x:v2:reply:cleanup -- --archive-posted-days 30");
    return;
  }

  console.log(`\n[cleanup] アーカイブ対象: ${targets.length} 行（Notionゴミ箱へ・30日復元可）`);
  let done = 0;
  for (const pg of targets) {
    try {
      await notionArchivePage(pg.id);
      done++;
      if (done % 20 === 0) console.log(`  ...${done}/${targets.length}`);
    } catch (e) {
      console.error(`  archive失敗 ${pg.id}: ${e.message}`);
    }
  }
  console.log(`[cleanup] 完了。${done} 行をアーカイブしました。draft/approved は残しています。`);
}

// CLI
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const args = process.argv.slice(2);
  const archiveRejected = args.includes("--archive-rejected");
  const di = args.indexOf("--archive-posted-days");
  const archivePostedDays = di >= 0 ? parseInt(args[di + 1], 10) : null;
  runCleanup({ archiveRejected, archivePostedDays }).catch((e) => {
    console.error(`[cleanup] Fatal: ${e.message}`);
    process.exit(1);
  });
}
