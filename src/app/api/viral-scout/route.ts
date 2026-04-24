import { NextResponse } from "next/server";
import { execFile } from "child_process";
import fs from "fs";
import path from "path";
import {
  getOverrides,
  markDeleted,
  setStatus,
} from "@/lib/viral-scout-overrides";

const DATA_PATH = path.join(process.cwd(), "data", "viral-scout-results.json");

interface ViralPostGenerated {
  text?: string;
  axis?: string;
  rationale?: string;
  status?: string;
  postedAt?: string;
  validationErrors?: string;
}

interface ViralPost {
  tweetId: string;
  generatedContent?: {
    quoteTweet?: ViralPostGenerated;
    reply?: ViralPostGenerated;
  };
  [key: string]: unknown;
}

interface ViralScoutData {
  viralPosts?: ViralPost[];
  aggregateAnalysis?: { totalAnalyzed?: number; [k: string]: unknown };
  [key: string]: unknown;
}

export async function GET() {
  try {
    if (!fs.existsSync(DATA_PATH)) {
      return NextResponse.json({ viralPosts: [], config: null, aggregateAnalysis: null });
    }
    const data: ViralScoutData = JSON.parse(fs.readFileSync(DATA_PATH, "utf-8"));
    // overrides を適用（deletedを除外、status/postedAtをマージ）
    let overrides;
    try {
      overrides = await getOverrides();
    } catch (err) {
      // Sheets接続失敗時は overrides なしで返す（完全停止しない）
      console.warn("[viral-scout GET] overrides取得失敗、生データで返します:", err);
      return NextResponse.json(data);
    }

    const filteredPosts = (data.viralPosts || []).filter((p) => {
      const ov = overrides.get(p.tweetId);
      return !ov?.deleted;
    });

    for (const post of filteredPosts) {
      const ov = overrides.get(post.tweetId);
      if (!ov || !post.generatedContent) continue;
      if (post.generatedContent.quoteTweet && ov.quoteStatus) {
        post.generatedContent.quoteTweet.status = ov.quoteStatus;
        if (ov.quotePostedAt) post.generatedContent.quoteTweet.postedAt = ov.quotePostedAt;
      }
      if (post.generatedContent.reply && ov.replyStatus) {
        post.generatedContent.reply.status = ov.replyStatus;
        if (ov.replyPostedAt) post.generatedContent.reply.postedAt = ov.replyPostedAt;
      }
    }

    // totalAnalyzedも削除分を反映
    if (data.aggregateAnalysis && typeof data.aggregateAnalysis.totalAnalyzed === "number") {
      data.aggregateAnalysis.totalAnalyzed = filteredPosts.length;
    }
    data.viralPosts = filteredPosts;

    return NextResponse.json(data);
  } catch (err) {
    console.error("[viral-scout GET]", err);
    return NextResponse.json({ error: "読み込みエラー" }, { status: 500 });
  }
}

export async function PATCH(req: Request) {
  try {
    const { tweetId, field, status } = await req.json();
    if (!tweetId || !field || !status) {
      return NextResponse.json({ error: "tweetId / field / status が必要です" }, { status: 400 });
    }
    if (field !== "quoteTweet" && field !== "reply") {
      return NextResponse.json({ error: "field は quoteTweet か reply" }, { status: 400 });
    }
    const postedAt = status === "posted" ? new Date().toISOString() : "";
    await setStatus(tweetId, field, status, postedAt || undefined);
    return NextResponse.json({ ok: true, postedAt: postedAt || null });
  } catch (err) {
    console.error("[viral-scout PATCH]", err);
    return NextResponse.json({ error: "更新エラー" }, { status: 500 });
  }
}

export async function DELETE(req: Request) {
  try {
    const { tweetIds } = await req.json();
    if (!Array.isArray(tweetIds) || tweetIds.length === 0) {
      return NextResponse.json({ error: "tweetIds (非空配列) が必要です" }, { status: 400 });
    }
    await markDeleted(tweetIds);
    return NextResponse.json({ ok: true, deleted: tweetIds.length });
  } catch (err) {
    console.error("[viral-scout DELETE]", err);
    return NextResponse.json({ error: "削除エラー" }, { status: 500 });
  }
}

export async function POST(req: Request) {
  const cwd = path.resolve(process.cwd());
  const script = path.join(cwd, "scripts", "viral-scout-agent.js");
  const { days = 2, minScore = 20 } = await req.json().catch(() => ({}));

  return new Promise<NextResponse>((resolve) => {
    execFile(
      "node",
      ["--dns-result-order=ipv4first", script, `--days=${days}`, `--min-score=${minScore}`],
      { cwd, env: { ...process.env }, timeout: 600_000 },
      (error, stdout, stderr) => {
        const output = (stdout + stderr).trim();
        if (error && error.code !== 0) {
          resolve(NextResponse.json({ ok: false, output }, { status: 500 }));
        } else {
          resolve(NextResponse.json({ ok: true, output }));
        }
      }
    );
  });
}
