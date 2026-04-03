#!/usr/bin/env node

/**
 * X投稿自動生成スクリプト
 * Claude APIを使って記事紹介とアウトドアTipsのポストを生成する
 * 生成結果はGoogle Sheets「下書き管理」シートに保存される
 *
 * 使い方:
 *   node scripts/generate-x-posts.js
 *   node scripts/generate-x-posts.js --auto-approve
 */

import Anthropic from "@anthropic-ai/sdk";
import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");
const SITE_URL = "https://camp-gear-lab.com";

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

const CATEGORY_HASHTAGS = {
  tent: "#テント #ファミキャン",
  light: "#ランタン #キャンプギア",
  "sleeping-bag": "#シュラフ #寝袋",
  burner: "#バーナー #キャンプ飯",
  backpack: "#登山 #バックパック",
  wear: "#アウトドアウェア #レインウェア",
  shoes: "#トレッキングシューズ #登山靴",
};

const SEASON_CONTEXT = {
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

const DRAFT_SHEET = "下書き管理";

function readJson(filename) {
  const filePath = path.join(DATA_DIR, filename);
  if (!fs.existsSync(filePath)) return [];
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

function generateId() {
  const now = new Date();
  const date = now.toISOString().slice(0, 10).replace(/-/g, "");
  const rand = Math.random().toString(36).slice(2, 6);
  return `xp-${date}-${rand}`;
}

function getScheduledDates(count) {
  const dates = [];
  const today = new Date();
  const targetDays = [1, 3, 5, 0]; // Mon, Wed, Fri, Sun
  let d = new Date(today);
  d.setDate(d.getDate() + 1);

  while (dates.length < count) {
    if (targetDays.includes(d.getDay())) {
      dates.push(d.toISOString().slice(0, 10));
    }
    d.setDate(d.getDate() + 1);
  }
  return dates;
}

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

async function getExistingPosts() {
  const sheets = await getSheets();
  const spreadsheetId = process.env.X_SHEET_ID;
  try {
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${DRAFT_SHEET}!A2:J`,
    });
    const rows = res.data.values || [];
    return rows
      .filter((r) => r[0])
      .map((r) => ({
        id: r[0],
        type: r[1],
        text: r[2],
        articleSlug: r[3] || null,
        url: r[4] || null,
        hashtags: r[5] || "",
        status: r[6],
        scheduledDate: r[7],
        generatedAt: r[8],
        postedAt: r[9] || null,
      }));
  } catch {
    return [];
  }
}

async function generatePosts(autoApprove = false) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.error("ANTHROPIC_API_KEY が設定されていません");
    process.exit(1);
  }
  if (!process.env.X_SHEET_ID) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const client = new Anthropic({ apiKey });
  const articles = readJson("articles.json").filter(
    (a) => a.status === "published"
  );
  const categories = readJson("categories.json");
  const existingPosts = await getExistingPosts();

  if (articles.length === 0) {
    console.error("公開済み記事がありません");
    process.exit(1);
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
記事URLは https://camp-gear-lab.com/articles/{スラッグ} です。

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

  console.log("Claude APIでポストを生成中...");

  const response = await client.messages.create({
    model: "claude-sonnet-4-20250514",
    max_tokens: 2000,
    messages: [{ role: "user", content: prompt }],
  });

  const content = response.content[0].text;
  const jsonMatch = content.match(/\[[\s\S]*\]/);
  if (!jsonMatch) {
    console.error("JSON解析に失敗しました:\n", content);
    process.exit(1);
  }

  const generated = JSON.parse(jsonMatch[0]);
  const scheduledDates = getScheduledDates(generated.length);
  const status = autoApprove ? "approved" : "draft";

  const newPosts = generated.map((g, i) => ({
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
  }));

  // Google Sheetsに保存
  const sheets = await getSheets();
  const rows = newPosts.map((p) => [
    p.id,
    p.type,
    p.text,
    p.articleSlug || "",
    p.url || "",
    p.hashtags,
    p.status,
    p.scheduledDate,
    p.generatedAt,
    p.postedAt || "",
  ]);

  await sheets.spreadsheets.values.append({
    spreadsheetId: process.env.X_SHEET_ID,
    range: `${DRAFT_SHEET}!A:J`,
    valueInputOption: "RAW",
    requestBody: { values: rows },
  });

  console.log(
    `\n${newPosts.length}件のポストを生成しました（status: ${status}）:\n`
  );
  for (const p of newPosts) {
    console.log(`[${p.scheduledDate}] ${p.type}`);
    console.log(p.text);
    console.log("---");
  }
}

const autoApprove = process.argv.includes("--auto-approve");
generatePosts(autoApprove).catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
