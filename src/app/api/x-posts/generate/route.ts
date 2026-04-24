import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { generatePosts } from "@/lib/x-post-generator.mjs";

// Vercel Hobby プランの上限は 300 秒。新パイプラインは軸×件数×リトライで
// 最長 3〜5 分かかる見込みなので、上限いっぱいに設定する。
export const maxDuration = 300;

interface GenerateOptions {
  autoApprove?: boolean;
  dryRun?: boolean;
  type?: string | null;
  count?: number | null;
  axis?: string | null;
  planFile?: string | null;
  research?: boolean;
}

interface GenerateResult {
  generated: number;
  blocked: number;
  qualityRetries: number;
  posts: unknown[];
}

export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json().catch(() => ({}));
  const opts: GenerateOptions = {
    autoApprove: body.autoApprove === true,
    dryRun: false,
    type: body.type || null,
    count: typeof body.count === "number" ? body.count : null,
    axis: body.axis || null,
    planFile: null,
    research: body.research === true,
  };

  try {
    const result: GenerateResult = await generatePosts(opts);
    return NextResponse.json({
      ok: true,
      generated: result.generated,
      blocked: result.blocked,
      qualityRetries: result.qualityRetries,
      // posts本体は大きいのでクライアントには返さず、件数だけ返す
      // 画面は /api/x-posts を再fetchして最新のSheets内容を取る
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const stack = err instanceof Error ? err.stack : undefined;
    console.error("[generate] error:", msg, stack);
    return NextResponse.json(
      { ok: false, error: msg },
      { status: 500 }
    );
  }
}
