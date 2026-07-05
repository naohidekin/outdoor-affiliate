// scripts/x/lib/notion.mjs
// v2 投稿を Notion「ギア男 X Posts」DB にドラフトとして書き込む。
// notion-poster.js(launchd自動)が ステータス=approved を投稿する既存レールに接続。
// → あなたは Notion 上で読んで、良いものを approved にするだけ（Sheetより視認性◎）。
import { hasClaudeKey } from "./claude-api.mjs"; // 未使用でも将来のため。副作用なし

const NOTION_VERSION = "2022-06-28";
// notion-poster.js の DB 定義と一致（type "post"）
export const GEARMAN_POSTS_DB_ID = "1d9bbe0c-30a5-4bfd-86b3-ced628cf05eb";
// GearMan Replies（type "reply"）— リプ精錬で使用
export const GEARMAN_REPLIES_DB_ID = "9feff0c2-142a-49f9-9985-d4d72868ad26";

export function hasNotionToken() {
  return !!process.env.NOTION_TOKEN;
}

async function notionCreatePage(databaseId, properties) {
  const token = process.env.NOTION_TOKEN;
  if (!token) throw new Error("NOTION_TOKEN が未設定です");
  const res = await fetch("https://api.notion.com/v1/pages", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Notion-Version": NOTION_VERSION,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ parent: { database_id: databaseId }, properties }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Notion page create failed (${res.status}): ${body.slice(0, 300)}`);
  }
  return res.json();
}

/**
 * v2 の reviewed 投稿を「ギア男 X Posts」DB に status で作成。
 * 既存 createNotionPost と同じプロパティ名（投稿ID/本文/ステータス/タイプ/生成日時/スコア/WISE/自己返信）。
 */
export async function pushPostToNotion(post, { status = "draft" } = {}) {
  const properties = {
    "投稿ID": { title: [{ text: { content: post.id } }] },
    "本文": { rich_text: [{ text: { content: (post.body || "").slice(0, 2000) } }] },
    "ステータス": { select: { name: status } },
    "タイプ": { select: { name: post.type || "outdoor_tip" } },
    "生成日時": { date: { start: post.createdAt || new Date().toISOString() } },
  };
  if (post.wiseScores) {
    const { w, i, s, e, ai } = post.wiseScores;
    const note = post.reviewedBy ? ` (${post.reviewedBy})` : "";
    const fc = post.needsHumanFactCheck ? ` ⚠要事実確認:${(post.claimsToVerify || []).length}` : "";
    properties["WISE"] = { rich_text: [{ text: { content: `W${w} I${i} S${s} E${e} AI${ai}${note}${fc}` } }] };
  }
  if (post.selfReply) {
    properties["自己返信"] = { rich_text: [{ text: { content: post.selfReply.slice(0, 2000) } }] };
  }
  return notionCreatePage(GEARMAN_POSTS_DB_ID, properties);
}
