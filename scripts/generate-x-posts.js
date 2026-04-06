#!/usr/bin/env node

/**
 * X投稿自動生成スクリプト
 * Claude APIを使ってX投稿をタイプ別に生成し、Sheets「下書き管理」に保存する
 *
 * 使い方:
 *   node scripts/generate-x-posts.js                       # legacy: article_promo+outdoor_tip 同時
 *   node scripts/generate-x-posts.js --auto-approve
 *   node scripts/generate-x-posts.js --type=seasonal --count=3
 *   node scripts/generate-x-posts.js --type=outdoor_tip --count=3
 *   node scripts/generate-x-posts.js --type=article_promo --count=3
 *   node scripts/generate-x-posts.js --type=rakuten_sale --count=2 --sale-event=hb-2026-04
 *   node scripts/generate-x-posts.js --type=amazon_deal --count=2 --deal-event=spring-2026
 *
 * gear_story タイプは docs/author-gear.md 完成後に有効化されます。
 */

import Anthropic from "@anthropic-ai/sdk";
import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  buildLegacyBatchPrompt,
  buildSeasonalPrompt,
  buildOutdoorTipPrompt,
  buildArticlePromoPrompt,
  buildRakutenSalePrompt,
  buildAmazonDealPrompt,
} from "../src/lib/x-post-prompts.mjs";
import { applyChecksAndLabels } from "../src/lib/x-content-checks.mjs";

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

/**
 * 投稿スロットを返す: {date, time} の配列
 * 平日は朝07:30/昼12:15/夜20:00 の3スロット、休日は昼12:15のみ
 * 上限スロット数 count に達するまで日付を進める
 */
function getScheduledSlots(count) {
  const SLOTS_WEEKDAY = ["07:30", "12:15", "20:00"];
  const SLOTS_WEEKEND = ["12:15"];
  const out = [];
  const today = new Date();
  const d = new Date(today);
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

// 後方互換: 既存呼び出しが date 配列を期待しているケースのため
function getScheduledDates(count) {
  return getScheduledSlots(count).map((s) => s.date);
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

function findCalendarEvent(filename, eventId) {
  const filePath = path.join(DATA_DIR, filename);
  if (!fs.existsSync(filePath)) {
    throw new Error(`${filename} が見つかりません`);
  }
  const list = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  if (eventId) {
    const found = list.find((e) => e.id === eventId);
    if (!found) throw new Error(`${filename} に id=${eventId} のイベントなし`);
    return found;
  }
  // 直近の未来イベントを優先
  const today = new Date().toISOString().slice(0, 10);
  return (
    list.find((e) => e.startDate >= today) || list[list.length - 1] || null
  );
}

function buildPromptForType({
  type,
  articles,
  categories,
  month,
  count,
  saleEventId,
  dealEventId,
}) {
  switch (type) {
    case "legacy":
      return buildLegacyBatchPrompt({ articles, categories, month });
    case "article_promo":
      return buildArticlePromoPrompt({
        articles: articles.slice(0, count),
        categories,
        month,
      });
    case "outdoor_tip":
      return buildOutdoorTipPrompt({ count, month });
    case "seasonal":
      return buildSeasonalPrompt({ count, month });
    case "rakuten_sale": {
      const ev = findCalendarEvent("rakuten-sale-calendar.json", saleEventId);
      if (!ev) throw new Error("rakuten-sale-calendar.json にイベントなし");
      return buildRakutenSalePrompt({
        saleEvent: ev,
        articles: articles.slice(0, count),
        categories,
        count,
      });
    }
    case "amazon_deal": {
      const ev = findCalendarEvent("amazon-deal-calendar.json", dealEventId);
      if (!ev) throw new Error("amazon-deal-calendar.json にイベントなし");
      return buildAmazonDealPrompt({
        dealEvent: ev,
        articles: articles.slice(0, count),
        categories,
        count,
      });
    }
    case "gear_story":
      throw new Error(
        "gear_story タイプは docs/author-gear.md 完成まで無効です"
      );
    default:
      throw new Error(`未知のタイプ: ${type}`);
  }
}

async function generatePosts({
  autoApprove = false,
  type = "legacy",
  count = 6,
  saleEventId,
  dealEventId,
}) {
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
  const selectCount = Math.min(count, articles.length);
  const selected =
    candidates.length >= selectCount
      ? candidates.sort(() => Math.random() - 0.5).slice(0, selectCount)
      : articles.sort(() => Math.random() - 0.5).slice(0, selectCount);

  const month = new Date().getMonth() + 1;
  const prompt = buildPromptForType({
    type,
    articles: selected,
    categories,
    month,
    count,
    saleEventId,
    dealEventId,
  });

  console.log("Claude APIでポストを生成中...");

  const response = await client.messages.create({
    model: "claude-sonnet-4-20250514",
    max_tokens: 4000,
    messages: [{ role: "user", content: prompt }],
  });

  const content = response.content[0].text;
  const jsonMatch = content.match(/\[[\s\S]*\]/);
  if (!jsonMatch) {
    console.error("JSON解析に失敗しました:\n", content);
    process.exit(1);
  }

  const generated = JSON.parse(jsonMatch[0]);
  const slots = getScheduledSlots(generated.length);

  // NGワード/誇大表現/PRラベル チェック
  const checked = applyChecksAndLabels(generated);

  const newPosts = checked.map((g, i) => ({
    id: generateId(),
    type: g.type,
    text: g.text,
    articleSlug: g.articleSlug,
    url: g.url,
    hashtags: "",
    // 違反検出時は --auto-approve でも draft 強制
    status: g._checkOk && autoApprove ? "approved" : "draft",
    scheduledDate: slots[i].date,
    generatedAt: new Date().toISOString(),
    postedAt: null,
    scheduledTime: slots[i].time,
    imageUrl: "",
    prLabel: g.prLabel ? "true" : "",
    validationErrors: g.validationErrors || "",
  }));

  // Google Sheetsに保存（A〜N列、後方互換）
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
    p.scheduledTime,
    p.imageUrl,
    p.prLabel,
    p.validationErrors,
  ]);

  await sheets.spreadsheets.values.append({
    spreadsheetId: process.env.X_SHEET_ID,
    range: `${DRAFT_SHEET}!A:N`,
    valueInputOption: "RAW",
    requestBody: { values: rows },
  });

  const blocked = newPosts.filter((p) => p.validationErrors).length;
  console.log(
    `\n${newPosts.length}件生成（type=${type}, blocked=${blocked}）:\n`
  );
  for (const p of newPosts) {
    console.log(
      `[${p.scheduledDate}] ${p.type}${p.validationErrors ? " ⚠ " + p.validationErrors : ""}`
    );
    console.log(p.text);
    console.log("---");
  }
}

function parseFlag(name, fallback) {
  const arg = process.argv.find((a) => a.startsWith(`${name}=`));
  return arg ? arg.split("=")[1] : fallback;
}

const autoApprove = process.argv.includes("--auto-approve");
const type = parseFlag("--type", "legacy");
const count = parseInt(parseFlag("--count", "6"), 10);
const saleEventId = parseFlag("--sale-event");
const dealEventId = parseFlag("--deal-event");

generatePosts({ autoApprove, type, count, saleEventId, dealEventId }).catch(
  (err) => {
    console.error("エラー:", err.message);
    process.exit(1);
  }
);
