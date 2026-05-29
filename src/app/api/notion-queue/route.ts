import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Dynamic import since notion-queue is ESM .mjs
async function getNotionLib() {
  const mod = await import("../../../lib/notion-queue.mjs");
  return mod;
}

const NOTION_TOKEN = process.env.NOTION_TOKEN ?? "";

// DB configs for all Replies-type DBs (have source URL for reply/quote)
const REPLY_DBS = [
  {
    id: "gearman-replies",
    name: "ギア男 リプライ",
    databaseId: "9feff0c2-142a-49f9-9985-d4d72868ad26",
    account: "ギア男",
  },
  {
    id: "amble-replies",
    name: "アンブロ Replies",
    databaseId: "bb14682e-285b-41a5-a0d1-eccecf56e077",
    account: "アンブロ",
  },
  {
    id: "kodomo-replies",
    name: "こどもケアラボ Replies",
    databaseId: "8be1d3d2-5fee-4222-ab2e-1c1eba96dc90",
    account: "こどもケアラボ",
  },
];

export async function GET() {
  if (!NOTION_TOKEN) {
    return NextResponse.json({ error: "NOTION_TOKEN not set" }, { status: 500 });
  }
  try {
    const { queryApproved, extractText, extractUrl } = await getNotionLib();
    const items: object[] = [];
    for (const db of REPLY_DBS) {
      let pages: object[];
      try {
        pages = await queryApproved(db.databaseId, {}, NOTION_TOKEN);
      } catch {
        continue;
      }
      for (const page of pages as Array<{ id: string; properties: Record<string, unknown> }>) {
        const props = page.properties;
        const text = extractText(props["リプライ"]);
        const sourceUrl = extractUrl(props["元ポストURL"]);
        const postType = (props["投稿タイプ"] as { select?: { name?: string } } | undefined)?.select?.name ?? "リプライ";
        const authorTitle = extractText(props["投稿者"]) || page.id.slice(0, 8);
        items.push({
          pageId: page.id,
          dbId: db.id,
          dbName: db.name,
          account: db.account,
          text,
          sourceUrl,
          postType,
          author: authorTitle,
        });
      }
    }
    return NextResponse.json({ items });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  if (!NOTION_TOKEN) {
    return NextResponse.json({ error: "NOTION_TOKEN not set" }, { status: 500 });
  }
  const body = await req.json() as { pageId?: string; action?: string };
  const { pageId, action } = body;
  if (!pageId) {
    return NextResponse.json({ error: "pageId required" }, { status: 400 });
  }
  try {
    const { markPosted } = await getNotionLib();
    if (action === "mark_posted") {
      await markPosted(pageId, {}, NOTION_TOKEN);
      return NextResponse.json({ ok: true });
    }
    return NextResponse.json({ error: "unknown action" }, { status: 400 });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
