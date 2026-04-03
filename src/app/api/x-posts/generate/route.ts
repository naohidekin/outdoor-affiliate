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
  const d = new Date(today);
  d.setDate(d.getDate() + 1);

  while (dates.length < count) {
    const day = d.getDay();
    const isWeekend = day === 0 || day === 6;
    const dateStr = d.toISOString().slice(0, 10);
    if (isWeekend) {
      dates.push(dateStr);
    } else {
      dates.push(dateStr);
      if (dates.length < count) {
        dates.push(dateStr);
      }
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
  const seasonContext = SEASON_CONTEXT[month];

  const articleInfoList = selected
    .map((a) => {
      const cat = categories.find((c) => c.id === a.categoryId);
      const tags = CATEGORY_HASHTAGS[a.categoryId] || "";
      return `- タイトル: ${a.title}\n  スラッグ: ${a.slug}\n  カテゴリ: ${cat?.name || "不明"}\n  概要: ${a.excerpt}\n  ハッシュタグ: #アウトドア #キャンプ ${tags}`;
    })
    .join("\n\n");

  const prompt = `あなたはキャンプ歴10年の個人ブロガーです。自分のブログ「camp-gear-lab.com」の記事を紹介したり、キャンプの豆知識をXに投稿しています。

## 絶対に守ること
- **AIが書いたとバレない文体にする**。テンプレ感・まとめ記事感を排除する
- 「〜してみてはいかがでしょうか」「〜をご紹介します」「〜についてまとめました」は絶対に使わない
- 「おすすめ○選」「徹底比較」「完全ガイド」のような定型表現も使わない
- 一人称は使わず、体験談や実感ベースで書く（「先週使ってみたけど」「去年これで失敗した」など）
- 句読点を多用しない。体言止め、倒置法、口語的な省略を使う
- 絵文字は0〜1個。使わなくてもいい。顔文字は使わない
- 各投稿は280文字以内（URLとハッシュタグ含む）
- ハッシュタグは2〜3個、本文末尾に改行して配置

## 文体の例（こういう感じで書いて）
- 「このテント、設営5分は盛ってると思ったけどマジだった。ワンタッチ系で一番まともかも」
- 「夜露でテーブル濡れるの地味にストレス。アルミ天板にしてから全く気にならなくなった」
- 「春キャンプ、昼は暑いのに夜は5度とかザラ。フリース忘れて凍えた去年の自分に教えたい」

## 現在の季節
${month}月: ${seasonContext}

## タスク1: 記事紹介（${selected.length}件）
以下の記事を自然に紹介するポストを1件ずつ。記事URLは ${SITE_URL}/articles/{スラッグ}
宣伝っぽくなく、実体験や感想を交えて「ブログに書いた」感じで。

${articleInfoList}

## タスク2: キャンプ豆知識（${selected.length}件）
季節に合ったキャンプの実用的な豆知識。URLは不要。
教科書的にならず、自分の体験や失敗談ベースで。

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
