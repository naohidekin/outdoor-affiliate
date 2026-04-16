import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";

export const maxDuration = 120; // Vercel Pro: 最大300s
import { isAuthenticated } from "@/lib/auth";
import { getPublishedArticles, getCategories } from "@/lib/db";
import { getSheetsXPosts, saveSheetsXPosts } from "@/lib/sheets-xposts";
import { XPost, XPostType } from "@/lib/types";
// 共通プロンプトlib（Lake & Sky トーン明文化）
import { buildLegacyBatchPrompt } from "@/lib/x-post-prompts.mjs";
import { applyChecksAndLabels } from "@/lib/x-content-checks.mjs";

function generateId() {
  const now = new Date();
  const date = now.toISOString().slice(0, 10).replace(/-/g, "");
  const rand = Math.random().toString(36).slice(2, 6);
  return `xp-${date}-${rand}`;
}

// 平日3スロット(朝07:30/昼12:15/夜20:00)、休日1スロット(昼12:15)
function getScheduledSlots(
  count: number
): Array<{ date: string; time: string }> {
  const SLOTS_WEEKDAY = ["07:30", "12:15", "20:00"];
  const SLOTS_WEEKEND = ["12:15"];
  const out: Array<{ date: string; time: string }> = [];
  const d = new Date();
  d.setDate(d.getDate() + 1);
  while (out.length < count) {
    const day = d.getDay();
    const isWeekend = day === 0 || day === 6;
    const slots = isWeekend ? SLOTS_WEEKEND : SLOTS_WEEKDAY;
    const dateStr = d.toISOString().slice(0, 10);
    for (const t of slots) {
      if (out.length >= count) break;
      out.push({ date: dateStr, time: t });
    }
    d.setDate(d.getDate() + 1);
  }
  return out;
}

export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "ANTHROPIC_API_KEYが設定されていません" },
      { status: 500 }
    );
  }

  const body = await request.json().catch(() => ({}));
  const autoApprove = body.autoApprove === true;

  const client = new Anthropic({ apiKey });
  const articles = await getPublishedArticles();
  const categories = await getCategories();
  const existingPosts = await getSheetsXPosts();

  if (articles.length === 0) {
    return NextResponse.json(
      { error: "公開済み記事がありません" },
      { status: 400 }
    );
  }

  const recentSlugs = new Set(
    existingPosts
      .filter((p) => p.type === "article_promo" && p.status !== "draft")
      .slice(0, articles.length - 1)
      .map((p) => p.articleSlug)
  );

  const candidates = articles.filter((a) => !recentSlugs.has(a.slug));
  const selectCount = Math.min(6, articles.length);
  const selected =
    candidates.length >= selectCount
      ? candidates.sort(() => Math.random() - 0.5).slice(0, selectCount)
      : articles.sort(() => Math.random() - 0.5).slice(0, selectCount);

  const month = new Date().getMonth() + 1;
  const prompt = buildLegacyBatchPrompt({
    articles: selected,
    categories,
    month,
  });

  const response = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 4000,
    messages: [{ role: "user", content: prompt }],
  });

  const content =
    response.content[0].type === "text" ? response.content[0].text : "";
  const jsonMatch = content.match(/\[[\s\S]*\]/);
  if (!jsonMatch) {
    return NextResponse.json(
      { error: "生成結果の解析に失敗しました" },
      { status: 500 }
    );
  }

  const generated = JSON.parse(jsonMatch[0]);
  const slots = getScheduledSlots(generated.length);

  // NGワード/誇大表現/PRラベル チェック適用
  const checked = applyChecksAndLabels(generated) as Array<{
    type: XPostType;
    text: string;
    articleSlug: string | null;
    url: string | null;
    prLabel: boolean;
    validationErrors?: string;
    _checkOk: boolean;
  }>;

  const newPosts: XPost[] = checked.map((g, i) => ({
    id: generateId(),
    type: g.type,
    text: g.text,
    articleSlug: g.articleSlug,
    url: g.url,
    hashtags: "",
    // 違反検出時は autoApprove でも draft に強制
    status: (g._checkOk && autoApprove ? "approved" : "draft") as XPost["status"],
    scheduledDate: slots[i].date,
    generatedAt: new Date().toISOString(),
    postedAt: null,
    axis: "camp",
    validationErrors: g.validationErrors,
    autoApproved: g._checkOk && autoApprove ? "true" : "false",
  }));

  await saveSheetsXPosts(newPosts);

  const blocked = newPosts.filter((p) => p.validationErrors).length;
  return NextResponse.json({
    generated: newPosts.length,
    blocked,
    posts: newPosts,
  });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("[generate] error:", msg);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
