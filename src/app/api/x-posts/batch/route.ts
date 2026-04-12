import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import {
  batchUpdateSheetsXPostStatus,
  batchDeleteSheetsXPosts,
} from "@/lib/sheets-xposts";

const VALID_ACTIONS = ["approve", "discard", "delete"] as const;
type BatchAction = (typeof VALID_ACTIONS)[number];

export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await req.json();
  const { action, ids } = body as { action: BatchAction; ids: string[] };

  if (!VALID_ACTIONS.includes(action)) {
    return NextResponse.json(
      { error: `無効なアクション: ${action}` },
      { status: 400 }
    );
  }
  if (!Array.isArray(ids) || ids.length === 0) {
    return NextResponse.json(
      { error: "ids が空です" },
      { status: 400 }
    );
  }

  try {
    let count: number;
    if (action === "delete") {
      count = await batchDeleteSheetsXPosts(ids);
    } else {
      const status = action === "approve" ? "approved" : "discarded";
      count = await batchUpdateSheetsXPostStatus(ids, status);
    }
    return NextResponse.json({ ok: true, count });
  } catch (e) {
    console.error("Batch operation error:", e);
    return NextResponse.json(
      { error: "バッチ操作に失敗しました" },
      { status: 500 }
    );
  }
}
