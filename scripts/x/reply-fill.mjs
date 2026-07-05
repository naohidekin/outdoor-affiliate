#!/usr/bin/env node
// scripts/x/reply-fill.mjs
// スマホ完結リプ運用のMac側ジョブ（launchdで定期実行）。
// GearMan Replies DB の「元ポストURLあり・リプライ空・未処理」行を見つけ、
// 本文取得→Opus生成→GPT-4o採点→opsec を通して「リプライ」欄を埋める。
//   合格 → リプライに文を書き、ステータス=draft（あなたがスマホで承認）
//   不合格 → ステータス=rejected、リプライに理由を残す（再処理されないように）
// あなたのスマホ操作: ①URLを行追加 ②生成されたリプを読んで approved に。それだけ。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { isKillSwitchOn } from "./lib/file-lock.mjs";
import { buildPersonaSystem } from "./lib/persona.mjs";
import { hasClaudeKey } from "./lib/claude-api.mjs";
import { processTarget } from "./reply.mjs";
import {
  GEARMAN_REPLIES_DB_ID,
  hasNotionToken,
  notionQueryDatabase,
  notionUpdatePage,
  propUrl,
  propRichText,
  propSelect,
} from "./lib/notion.mjs";

// 既に処理済み/対象外のステータス（これらは再生成しない）
const DONE_STATUS = new Set(["draft", "approved", "posted", "rejected", "投稿済み", "引用済み"]);
// 軸を後ろに付けたい場合の簡易プロパティ名（任意・無ければ camp）
const AXIS_PROP = "軸";

export async function runReplyFill({ dryRun = false } = {}) {
  if (isKillSwitchOn()) return console.log("[reply-fill] kill-switch ON。終了。");
  if (!hasClaudeKey() || !hasNotionToken()) {
    return console.warn("[reply-fill] ANTHROPIC_API_KEY / NOTION_TOKEN 未設定。終了。");
  }
  let pages;
  try {
    pages = await notionQueryDatabase(GEARMAN_REPLIES_DB_ID);
  } catch (e) {
    return console.error(`[reply-fill] Notion取得失敗: ${e.message}`);
  }

  // 対象: 元ポストURLあり & リプライ空 & 未処理ステータス
  const pending = pages.filter((pg) => {
    const p = pg.properties;
    const url = propUrl(p, "元ポストURL");
    const reply = propRichText(p, "リプライ");
    const status = propSelect(p, "ステータス");
    return url && /\/status\/\d+/.test(url) && !reply && !DONE_STATUS.has(status || "");
  });

  if (pending.length === 0) return console.log("[reply-fill] 処理対象の行はありません。");
  console.log(`[reply-fill] ${pending.length}件を処理`);
  const system = buildPersonaSystem();

  for (const pg of pending) {
    const p = pg.properties;
    const url = propUrl(p, "元ポストURL");
    const axisRaw = propSelect(p, AXIS_PROP);
    const axis = ["camp", "doctor", "parenting"].includes(axisRaw) ? axisRaw : "camp";

    const r = await processTarget({ url, axis, targetText: "" }, system);

    if (dryRun) {
      console.log(`[reply-fill] (dry) ${url} → ${r.ok ? "PASS: " + r.reply : "REJECT: " + r.reason}`);
      continue;
    }
    try {
      if (r.ok) {
        const s = r.scores;
        await notionUpdatePage(pg.id, {
          "リプライ": { rich_text: [{ text: { content: r.reply.slice(0, 2000) } }] },
          "ステータス": { select: { name: "draft" } },
        });
        console.log(`[reply-fill] ✓ ${url} R${s.r}V${s.v}P${s.p}F${s.f} → draft`);
      } else {
        await notionUpdatePage(pg.id, {
          "リプライ": { rich_text: [{ text: { content: `【自動生成NG】${r.reason}`.slice(0, 2000) } }] },
          "ステータス": { select: { name: "rejected" } },
        });
        console.log(`[reply-fill] ✗ ${url} rejected: ${r.reason}`);
      }
    } catch (e) {
      console.error(`[reply-fill] 更新失敗 ${url}: ${e.message}`);
    }
  }
  console.log("[reply-fill] 完了。スマホのNotionで draft を確認し approved にしてください。");
}

// CLI
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const dryRun = process.argv.includes("--dry-run");
  runReplyFill({ dryRun }).catch((e) => {
    console.error(`[reply-fill] Fatal: ${e.message}`);
    process.exit(1);
  });
}
