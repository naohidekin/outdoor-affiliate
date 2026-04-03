#!/usr/bin/env node

/**
 * 人気記事リポストスクリプト
 * Google Analytics (GA4) からPV上位の記事を取得し、
 * 最近X投稿していない人気記事のリポストを自動生成
 *
 * 必要な環境変数:
 *   GA4_PROPERTY_ID       — GA4 プロパティID (例: 123456789)
 *   INDEXING_CREDENTIALS  — GA4閲覧権限を持つサービスアカウントJSON
 *   GOOGLE_CREDENTIALS    — Google Sheets書き込み用サービスアカウントJSON
 *
 * 使い方:
 *   node scripts/popular-repost.js
 *   node scripts/popular-repost.js --days=14     (過去14日のデータ)
 *   node scripts/popular-repost.js --count=3     (3件生成)
 *   node scripts/popular-repost.js --auto-approve (自動承認)
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

// .env.local を手動読み込み
const envPath = path.join(__dirname, "..", ".env.local");
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match && !process.env[match[1].trim()]) {
      process.env[match[1].trim()] = match[2].trim();
    }
  }
}

const GA4_PROPERTY_ID = process.env.GA4_PROPERTY_ID;
const DAYS = parseInt(
  process.argv.find((a) => a.startsWith("--days="))?.split("=")[1] || "7"
);
const COUNT = parseInt(
  process.argv.find((a) => a.startsWith("--count="))?.split("=")[1] || "2"
);
const AUTO_APPROVE = process.argv.includes("--auto-approve");

async function getPopularPages() {
  const { google } = await import("googleapis");

  const credentials = JSON.parse(process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS || "{}");
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
  });

  const analyticsData = google.analyticsdata({ version: "v1beta", auth });

  const today = new Date();
  const startDate = new Date(today.getTime() - DAYS * 24 * 60 * 60 * 1000);

  const formatDate = (d) => d.toISOString().slice(0, 10);

  const res = await analyticsData.properties.runReport({
    property: `properties/${GA4_PROPERTY_ID}`,
    requestBody: {
      dateRanges: [
        {
          startDate: formatDate(startDate),
          endDate: formatDate(today),
        },
      ],
      dimensions: [{ name: "pagePath" }],
      metrics: [
        { name: "screenPageViews" },
        { name: "engagedSessions" },
      ],
      dimensionFilter: {
        filter: {
          fieldName: "pagePath",
          stringFilter: {
            matchType: "BEGINS_WITH",
            value: "/articles/",
          },
        },
      },
      orderBys: [
        {
          metric: { metricName: "screenPageViews" },
          desc: true,
        },
      ],
      limit: 20,
    },
  });

  const rows = res.data.rows || [];
  return rows.map((row) => ({
    path: row.dimensionValues[0].value,
    pageViews: parseInt(row.metricValues[0].value),
    engagedSessions: parseInt(row.metricValues[1].value),
    slug: row.dimensionValues[0].value.replace("/articles/", "").replace(/\/$/, ""),
  }));
}

async function getRecentXPosts() {
  const { google } = await import("googleapis");

  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
  });

  const sheets = google.sheets({ version: "v4", auth });
  const spreadsheetId = process.env.X_SHEET_ID;

  if (!spreadsheetId) return [];

  try {
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: "下書き管理!A2:J",
    });

    const rows = res.data.values || [];
    // 過去14日以内に投稿/生成された記事slugを収集
    const twoWeeksAgo = new Date(
      Date.now() - 14 * 24 * 60 * 60 * 1000
    ).toISOString();

    return rows
      .filter((r) => r[3] && r[8] > twoWeeksAgo) // articleSlug exists & recent
      .map((r) => r[3]); // articleSlug
  } catch {
    return [];
  }
}

async function generateRepostText(article, pageViews) {
  // Claude APIで魅力的なリポストテキストを生成
  const apiKey = process.env.ANTHROPIC_API_KEY;

  if (!apiKey) {
    // APIキーがない場合はテンプレートで生成
    return `📊 今週よく読まれています！\n\n${article.title}\n\n${article.excerpt.slice(0, 80)}\n\nhttps://camp-gear-lab.com/articles/${article.slug}\n\n#キャンプ #アウトドア`;
  }

  const { default: Anthropic } = await import("@anthropic-ai/sdk");
  const client = new Anthropic({ apiKey });

  const message = await client.messages.create({
    model: "claude-sonnet-4-20250514",
    max_tokens: 300,
    messages: [
      {
        role: "user",
        content: `あなたは「ギア男」というキャンプ好きのX(Twitter)アカウントの中の人です。
以下の人気記事をリポスト（再紹介）するツイートを1つ作ってください。

記事タイトル: ${article.title}
記事の要約: ${article.excerpt}
PV数: 過去${DAYS}日で${pageViews}PV（人気記事）
URL: https://camp-gear-lab.com/articles/${article.slug}

ルール:
- 280文字以内
- 「今週人気」「よく読まれています」「改めて紹介」などの再紹介感を出す
- 記事の具体的な価値を1-2行で伝える
- URLは最後に配置
- ハッシュタグは1-2個（#キャンプ 必須 + 記事に合ったもの1つ）
- 絵文字は控えめに（1-2個）
- AIっぽさを排除。自然な口語体で
- 投稿テキストのみ出力（説明不要）`,
      },
    ],
  });

  return message.content[0].text.trim();
}

async function saveToSheets(posts) {
  const { google } = await import("googleapis");

  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });

  const sheets = google.sheets({ version: "v4", auth });
  const spreadsheetId = process.env.X_SHEET_ID;

  if (!spreadsheetId) {
    console.log("⚠️ X_SHEET_ID未設定。Sheets保存をスキップ");
    return;
  }

  const rows = posts.map((p) => [
    p.id,
    "article_repost",
    p.text,
    p.articleSlug,
    p.url,
    "#キャンプ",
    AUTO_APPROVE ? "approved" : "draft",
    new Date().toISOString().slice(0, 10),
    new Date().toISOString(),
    "",
  ]);

  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: "下書き管理!A:J",
    valueInputOption: "RAW",
    requestBody: { values: rows },
  });
}

async function main() {
  if (!GA4_PROPERTY_ID) {
    console.log("⚠️ GA4_PROPERTY_ID が未設定です。");
    console.log("");
    console.log("以下を .env.local に追加してください:");
    console.log("  GA4_PROPERTY_ID=123456789");
    console.log("");
    console.log("設定方法:");
    console.log("  1. Google Analytics (analytics.google.com) にアクセス");
    console.log("  2. 管理 → プロパティ設定 → プロパティID をコピー");
    console.log("  3. 管理 → プロパティアクセス管理 → サービスアカウントに閲覧者権限を付与");
    console.log(
      "     （GOOGLE_CREDENTIALSのサービスアカウントメールアドレスを追加）"
    );
    process.exit(0);
  }

  console.log(`\n📊 人気記事リポスト生成`);
  console.log(`  期間: 過去${DAYS}日`);
  console.log(`  生成数: ${COUNT}件`);
  console.log(`  自動承認: ${AUTO_APPROVE ? "ON" : "OFF"}\n`);

  // 1. GA4から人気ページ取得
  console.log("🔍 GA4から人気ページを取得中...");
  const popularPages = await getPopularPages();

  if (popularPages.length === 0) {
    console.log("❌ 記事ページのデータが見つかりません");
    process.exit(0);
  }

  console.log(`  ${popularPages.length}件の記事ページを取得\n`);
  popularPages.slice(0, 5).forEach((p, i) => {
    console.log(`  ${i + 1}. ${p.slug} (${p.pageViews} PV)`);
  });

  // 2. 最近投稿した記事を除外
  console.log("\n🔍 最近のX投稿をチェック...");
  const recentSlugs = await getRecentXPosts();
  console.log(`  過去14日に投稿済み: ${recentSlugs.length}件`);

  const candidates = popularPages.filter(
    (p) => !recentSlugs.includes(p.slug)
  );

  if (candidates.length === 0) {
    console.log("❌ リポスト候補がありません（全て最近投稿済み）");
    process.exit(0);
  }

  // 3. articles.jsonとマッチング
  const articles = JSON.parse(
    fs.readFileSync(path.join(DATA_DIR, "articles.json"), "utf-8")
  );

  const toRepost = candidates
    .map((c) => {
      const article = articles.find(
        (a) => a.slug === c.slug && a.status === "published"
      );
      return article ? { ...c, article } : null;
    })
    .filter(Boolean)
    .slice(0, COUNT);

  if (toRepost.length === 0) {
    console.log("❌ マッチする公開記事がありません");
    process.exit(0);
  }

  // 4. リポストテキスト生成
  console.log(`\n✍️ ${toRepost.length}件のリポストを生成中...\n`);

  const posts = [];
  for (const item of toRepost) {
    const text = await generateRepostText(item.article, item.pageViews);
    const id = `xp-repost-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

    posts.push({
      id,
      text,
      articleSlug: item.article.slug,
      url: `https://camp-gear-lab.com/articles/${item.article.slug}`,
      pageViews: item.pageViews,
    });

    console.log(`--- ${item.article.title.slice(0, 40)} (${item.pageViews} PV) ---`);
    console.log(text);
    console.log("");
  }

  // 5. Sheetsに保存
  console.log("💾 Google Sheetsに保存中...");
  await saveToSheets(posts);

  console.log(
    `\n✅ ${posts.length}件のリポストを${AUTO_APPROVE ? "承認済み" : "下書き"}で保存しました`
  );
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
