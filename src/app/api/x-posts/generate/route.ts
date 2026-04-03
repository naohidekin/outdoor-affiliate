import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import { isAuthenticated } from "@/lib/auth";
import { getPublishedArticles, getCategories } from "@/lib/db";
import { getSheetsXPosts, saveSheetsXPosts } from "@/lib/sheets-xposts";
import { XPost } from "@/lib/types";

const SITE_URL = "https://camp-gear-lab.com";

const CATEGORY_HASHTAGS: Record<string, string> = {
  tent: "#テント #ファミキャン",
  light: "#ランタン #キャンプギア",
  "sleeping-bag": "#シュラフ #寝袋",
  burner: "#バーナー #キャンプ飯",
  backpack: "#登山 #バックパック",
  wear: "#アウトドアウェア #レインウェア",
  shoes: "#トレッキングシューズ #登山靴",
};

const SEASON_CONTEXT: Record<number, string> = {
  1: "冬キャンプシーズン。防寒対策、冬用シュラフ、薪ストーブが話題",
  2: "冬キャンプ後半。春キャンプの準備が始まる時期",
  3: "春キャンプシーズン開始。花見キャンプ、新生活でキャンプデビュー",
  4: "春キャンプ本番。GWキャンプの計画時期。朝晩の寒暖差に注意",
  5: "GWキャンプ。新緑の季節。虫対策が必要になり始める",
  6: "梅雨シーズン。雨キャンプの準備、レインウェア選び",
  7: "夏キャンプ開始。暑さ対策、水遊び、虫除け必須",
  8: "夏キャンプ本番。高原キャンプ、川遊び、お盆キャンプ",
  9: "秋キャンプ開始。涼しくなり始め、焚き火が気持ちいい季節",
  10: "秋キャンプ本番。紅葉キャンプ、焚き火、温かい料理",
  11: "秋冬の境目。防寒ギアの見直し、冬キャンプ準備",
  12: "冬キャンプシーズン突入。年末キャンプ、冬装備の確認",
};

function generateId() {
  const now = new Date();
  const date = now.toISOString().slice(0, 10).replace(/-/g, "");
  const rand = Math.random().toString(36).slice(2, 6);
  return `xp-${date}-${rand}`;
}

function getScheduledDates(count: number): string[] {
  const dates: string[] = [];
  const today = new Date();
  const targetDays = [1, 3, 5, 0]; // Mon, Wed, Fri, Sun
  const d = new Date(today);
  d.setDate(d.getDate() + 1);

  while (dates.length < count) {
    if (targetDays.includes(d.getDay())) {
      dates.push(d.toISOString().slice(0, 10));
    }
    d.setDate(d.getDate() + 1);
  }
  return dates;
}

export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

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
  const articles = getPublishedArticles();
  const categories = getCategories();
  const existingPosts = await getSheetsXPosts();

  if (articles.length === 0) {
    return NextResponse.json(
      { error: "公開済み記事がありません" },
      { status: 400 }
    );
  }

  // 最近投稿した記事を避ける
  const recentSlugs = new Set(
    existingPosts
      .filter((p) => p.type === "article_promo" && p.status !== "draft")
      .slice(0, articles.length - 1)
      .map((p) => p.articleSlug)
  );

  const candidates = articles.filter((a) => !recentSlugs.has(a.slug));
  const selected =
    candidates.length >= 2
      ? candidates.sort(() => Math.random() - 0.5).slice(0, 2)
      : articles.sort(() => Math.random() - 0.5).slice(0, 2);

  const month = new Date().getMonth() + 1;
  const seasonContext = SEASON_CONTEXT[month];

  const articleInfoList = selected
    .map((a) => {
      const cat = categories.find((c) => c.id === a.categoryId);
      const tags = CATEGORY_HASHTAGS[a.categoryId] || "";
      return `- タイトル: ${a.title}\n  スラッグ: ${a.slug}\n  カテゴリ: ${cat?.name || "不明"}\n  概要: ${a.excerpt}\n  ハッシュタグ: #アウトドア #キャンプ ${tags}`;
    })
    .join("\n\n");

  const prompt = `あなたはアウトドア・キャンプ情報ブログ「camp-gear-lab.com」のSNS担当です。
Xに投稿するテキストを生成してください。

## ルール
- 各投稿は280文字以内（URLとハッシュタグ含む）
- 自然な日本語で、親しみやすいトーン（「〜だよ」「〜しよう」）
- 絵文字は1〜2個まで
- ハッシュタグは投稿本文の末尾に改行して配置
- 宣伝臭くない、読者に役立つ内容

## 現在の季節情報
${month}月: ${seasonContext}

## タスク1: 記事紹介ポスト（2件）
以下の記事を紹介するポストを1件ずつ作成してください。
記事URLは ${SITE_URL}/articles/{スラッグ} です。

${articleInfoList}

## タスク2: アウトドアTipsポスト（2件）
季節に合ったキャンプの豆知識・Tipsを2件作成してください。
URLは不要。ハッシュタグは #アウトドア #キャンプ + 内容に合った1〜2個。

## 出力形式
以下のJSON配列で出力してください。他のテキストは不要です。
[
  {
    "type": "article_promo",
    "text": "投稿本文（ハッシュタグ含む）",
    "articleSlug": "記事のスラッグ",
    "url": "記事のURL"
  },
  {
    "type": "outdoor_tip",
    "text": "投稿本文（ハッシュタグ含む）",
    "articleSlug": null,
    "url": null
  }
]`;

  const response = await client.messages.create({
    model: "claude-sonnet-4-20250514",
    max_tokens: 2000,
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
  const scheduledDates = getScheduledDates(generated.length);
  const status = autoApprove ? "approved" : "draft";

  const newPosts: XPost[] = generated.map(
    (
      g: {
        type: "article_promo" | "outdoor_tip";
        text: string;
        articleSlug: string | null;
        url: string | null;
      },
      i: number
    ) => ({
      id: generateId(),
      type: g.type,
      text: g.text,
      articleSlug: g.articleSlug,
      url: g.url,
      hashtags: "",
      status,
      scheduledDate: scheduledDates[i],
      generatedAt: new Date().toISOString(),
      postedAt: null,
    })
  );

  await saveSheetsXPosts(newPosts);

  return NextResponse.json({ generated: newPosts.length, posts: newPosts });
}
