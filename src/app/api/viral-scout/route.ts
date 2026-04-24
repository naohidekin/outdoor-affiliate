import { NextResponse } from "next/server";
import { execFile } from "child_process";
import fs from "fs";
import path from "path";

const DATA_PATH = path.join(process.cwd(), "data", "viral-scout-results.json");

export async function GET() {
  try {
    if (!fs.existsSync(DATA_PATH)) {
      return NextResponse.json({ viralPosts: [], config: null, aggregateAnalysis: null });
    }
    const data = JSON.parse(fs.readFileSync(DATA_PATH, "utf-8"));
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({ error: "読み込みエラー" }, { status: 500 });
  }
}

export async function PATCH(req: Request) {
  try {
    const { tweetId, field, status } = await req.json();
    if (!fs.existsSync(DATA_PATH)) {
      return NextResponse.json({ error: "データなし" }, { status: 404 });
    }
    const data = JSON.parse(fs.readFileSync(DATA_PATH, "utf-8"));
    const post = data.viralPosts?.find((p: { tweetId: string }) => p.tweetId === tweetId);
    if (!post) {
      return NextResponse.json({ error: "投稿が見つかりません" }, { status: 404 });
    }
    const target =
      field === "quoteTweet"
        ? post.generatedContent?.quoteTweet
        : field === "reply"
        ? post.generatedContent?.reply
        : null;
    if (!target) {
      return NextResponse.json({ error: "対象フィールドがありません" }, { status: 400 });
    }
    target.status = status;
    // posted遷移でタイムスタンプを記録、posted→他へ戻す時はクリア
    if (status === "posted") {
      target.postedAt = new Date().toISOString();
    } else if (target.postedAt) {
      delete target.postedAt;
    }
    fs.writeFileSync(DATA_PATH, JSON.stringify(data, null, 2) + "\n", "utf-8");
    return NextResponse.json({ ok: true, postedAt: target.postedAt || null });
  } catch (err) {
    return NextResponse.json({ error: "更新エラー" }, { status: 500 });
  }
}

export async function DELETE(req: Request) {
  try {
    const { tweetIds } = await req.json();
    if (!Array.isArray(tweetIds) || tweetIds.length === 0) {
      return NextResponse.json({ error: "tweetIds (非空配列) が必要です" }, { status: 400 });
    }
    if (!fs.existsSync(DATA_PATH)) {
      return NextResponse.json({ error: "データなし" }, { status: 404 });
    }
    const data = JSON.parse(fs.readFileSync(DATA_PATH, "utf-8"));
    const idSet = new Set<string>(tweetIds);
    const before: number = data.viralPosts?.length || 0;
    data.viralPosts = (data.viralPosts || []).filter(
      (p: { tweetId: string }) => !idSet.has(p.tweetId)
    );
    const after: number = data.viralPosts.length;
    // 集約analysisの件数表示も更新しておく（別の再集計はしない）
    if (data.aggregateAnalysis && typeof data.aggregateAnalysis.totalAnalyzed === "number") {
      data.aggregateAnalysis.totalAnalyzed = after;
    }
    fs.writeFileSync(DATA_PATH, JSON.stringify(data, null, 2) + "\n", "utf-8");
    return NextResponse.json({ ok: true, deleted: before - after, remaining: after });
  } catch (err) {
    console.error("[viral-scout DELETE] error:", err);
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
