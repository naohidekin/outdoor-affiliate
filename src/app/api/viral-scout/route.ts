import { NextResponse } from "next/server";
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
    if (field === "quoteTweet" && post.generatedContent?.quoteTweet) {
      post.generatedContent.quoteTweet.status = status;
    } else if (field === "reply" && post.generatedContent?.reply) {
      post.generatedContent.reply.status = status;
    }
    fs.writeFileSync(DATA_PATH, JSON.stringify(data, null, 2) + "\n", "utf-8");
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: "更新エラー" }, { status: 500 });
  }
}
