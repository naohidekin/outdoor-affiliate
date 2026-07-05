#!/usr/bin/env node
// scripts/x/push-notion.mjs
// reviewed（＋CLI承認済み approved）の投稿を Notion「ギア男 X Posts」DB に
// ステータス=draft で投入する。あなたは Notion で読んで良いものを approved にする
// → notion-poster.js(launchd) が投稿。Sheet より視認性・アクセス性が高い。
// 投入済みは status を "in_notion" にして二重投入を防ぐ。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { resolve } from "node:path";
import { readJsonl, updatePost, jstNow, POSTS_PATH } from "./lib/file-lock.mjs";
import { pushPostToNotion, hasNotionToken } from "./lib/notion.mjs";

export async function runPushNotion({ dryRun = false } = {}) {
  if (!hasNotionToken()) {
    console.warn("[notion] NOTION_TOKEN 未設定。Notion投入スキップ（Sheet/JSONレールは影響なし）。");
    return { pushed: 0 };
  }
  const posts = readJsonl(POSTS_PATH);
  // reviewed（正規ルート）＋ 旧CLIで approved にした分も回収
  const targets = posts.filter((p) => ["reviewed", "approved"].includes(p.status) && !p.notionPushedAt);
  if (targets.length === 0) {
    console.log("[notion] 投入対象(reviewed/approved)がありません。");
    return { pushed: 0 };
  }
  console.log(`[notion] ${targets.length}件を「ギア男 X Posts」DBに draft 投入`);
  let pushed = 0;
  for (const post of targets) {
    if (dryRun) {
      console.log(`[notion] (dry) → ${post.id}: ${post.body.slice(0, 40)}...`);
      pushed++;
      continue;
    }
    try {
      await pushPostToNotion(post, { status: "draft" });
      updatePost(post.id, { status: "in_notion", notionPushedAt: jstNow() });
      pushed++;
      console.log(`[notion] ✓ ${post.id}`);
    } catch (e) {
      console.error(`[notion] 失敗 ${post.id}: ${e.message}`);
    }
  }
  console.log(`[notion] 完了。${pushed}件を Notion に投入。→ Notionで確認し approved にすると notion-poster が投稿します。`);
  return { pushed };
}

// CLI
import { fileURLToPath } from "node:url";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const dryRun = process.argv.includes("--dry-run");
  runPushNotion({ dryRun }).catch((e) => {
    console.error(`[notion] Fatal: ${e.message}`);
    process.exit(1);
  });
}
