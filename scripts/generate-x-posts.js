#!/usr/bin/env node

/**
 * X投稿自動生成スクリプト（4軸10タイプ対応）
 *
 * Claude APIを使って10タイプのX投稿を生成する。
 * 生成結果はGoogle Sheets「下書き管理」シートに保存される。
 *
 * 使い方:
 *   node scripts/generate-x-posts.js                     # 週次バッチ（全タイプ）
 *   node scripts/generate-x-posts.js --dry-run            # 生成のみ（Sheets書き込みなし）
 *   node scripts/generate-x-posts.js --type ai_dev_log    # 特定タイプのみ
 *   node scripts/generate-x-posts.js --axis camp          # 特定軸のみ
 *   node scripts/generate-x-posts.js --count 3            # 件数指定
 *   node scripts/generate-x-posts.js --auto-approve       # 自動承認（レガシー互換）
 */

import Anthropic from "@anthropic-ai/sdk";
import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

import {
  SITE_URL,
  CATEGORY_HASHTAGS,
  SEASON_CONTEXT,
  POST_TYPES,
  getApprovalLevel,
  getPromptForType,
} from "../src/lib/x-post-prompts.mjs";

import {
  checkXPostContent,
  checkThreadContent,
  applyChecksAndLabels,
} from "../src/lib/x-content-checks.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

const DRAFT_SHEET = "下書き管理";

// === .env.local 読み込み ===

const envPath = path.join(__dirname, "..", ".env.local");
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match) {
      process.env[match[1].trim()] = match[2].trim().replace(/^["']|["']$/g, "");
    }
  }
}

// === CLI オプション ===

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    autoApprove: false,
    dryRun: false,
    type: null,
    count: null,
    axis: null,
  };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--auto-approve": opts.autoApprove = true; break;
      case "--dry-run":      opts.dryRun = true; break;
      case "--type":         opts.type = args[++i]; break;
      case "--count":        opts.count = parseInt(args[++i], 10); break;
      case "--axis":         opts.axis = args[++i]; break;
    }
  }
  // バリデーション
  if (opts.type && !POST_TYPES[opts.type]) {
    console.error(`未知のタイプ: ${opts.type}`);
    console.error(`有効なタイプ: ${Object.keys(POST_TYPES).join(", ")}`);
    process.exit(1);
  }
  if (opts.axis && !["camp", "ai", "parenting", "doctor"].includes(opts.axis)) {
    console.error(`未知の軸: ${opts.axis}`);
    console.error("有効な軸: camp, ai, parenting, doctor");
    process.exit(1);
  }
  return opts;
}

// === ユーティリティ ===

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
  let d = new Date(today);
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

// === Google Sheets ===

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
      range: `${DRAFT_SHEET}!A2:N`,
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
        axis: r[10] || null,
        seedId: r[11] || null,
        validationErrors: r[12] || null,
        autoApproved: r[13] || null,
      }));
  } catch {
    return [];
  }
}

// === シード管理 ===

function loadSeeds() {
  const seedPath = path.join(DATA_DIR, "x-content-seeds.json");
  if (!fs.existsSync(seedPath)) return { seeds: [] };
  return JSON.parse(fs.readFileSync(seedPath, "utf-8"));
}

function saveSeeds(seedData) {
  const seedPath = path.join(DATA_DIR, "x-content-seeds.json");
  fs.writeFileSync(seedPath, JSON.stringify(seedData, null, 2) + "\n", "utf-8");
}

function selectSeed(seedData, { type, month, axis }) {
  const candidates = seedData.seeds.filter((s) => {
    if (!s.types.includes(type)) return false;
    if (s.season && s.season.length > 0 && !s.season.includes(month)) return false;
    if (axis && axis !== "all" && axis !== "rotate" && s.axis !== axis) return false;
    return true;
  });

  if (candidates.length === 0) return null;

  candidates.sort((a, b) => {
    if (a.used_count !== b.used_count) return a.used_count - b.used_count;
    if (!a.last_used) return -1;
    if (!b.last_used) return 1;
    return new Date(a.last_used) - new Date(b.last_used);
  });

  return candidates[0];
}

function markSeedUsed(seedData, seedId) {
  const seed = seedData.seeds.find((s) => s.id === seedId);
  if (seed) {
    seed.used_count++;
    seed.last_used = new Date().toISOString().slice(0, 10);
  }
}

// === UTM パラメータ ===

const UTM_TYPES = new Set(["article_promo", "gear_thread", "seasonal_hook", "parenting_outdoor"]);

function addUtmIfNeeded(post, type) {
  if (!UTM_TYPES.has(type)) return post;

  const utmSuffix = `utm_source=x&utm_medium=social&utm_campaign=${type}`;

  // gear_thread: 最終ツイートの URL のみ
  if (type === "gear_thread" && post.tweets) {
    const lastIdx = post.tweets.length - 1;
    post.tweets[lastIdx] = post.tweets[lastIdx].replace(
      /(https?:\/\/camp-gear-lab\.com\/articles\/[^\s?]+)/,
      (match) => `${match}?${utmSuffix}`
    );
    if (post.url) {
      const sep = post.url.includes("?") ? "&" : "?";
      post.url = `${post.url}${sep}${utmSuffix}`;
    }
    return post;
  }

  if (post.url) {
    const sep = post.url.includes("?") ? "&" : "?";
    post.url = `${post.url}${sep}${utmSuffix}`;
    // text 内の URL にも UTM を付与
    post.text = post.text.replace(
      /(https?:\/\/camp-gear-lab\.com\/articles\/[^\s?]+)/,
      (match) => `${match}?${utmSuffix}`
    );
  }

  return post;
}

// === gear_thread Sheets フォーマット ===

function formatThreadForSheets(tweets) {
  return `[THREAD] ${JSON.stringify(tweets)}`;
}

// === 生成プラン ===

function determineGenerationPlan(opts) {
  const plan = [];

  if (opts.type) {
    const meta = POST_TYPES[opts.type];
    const count = opts.count || Math.ceil(meta.weeklyCount);
    plan.push({ type: opts.type, count, axis: opts.axis || meta.axis });
  } else {
    for (const [type, meta] of Object.entries(POST_TYPES)) {
      // --axis フィルタ
      if (opts.axis) {
        if (meta.axis !== "all" && meta.axis !== "rotate" && meta.axis !== opts.axis) continue;
      }
      const count = opts.count || Math.ceil(meta.weeklyCount);
      plan.push({ type, count, axis: meta.axis });
    }
  }

  return plan;
}

// === メイン ===

async function generatePosts(opts) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.error("ANTHROPIC_API_KEY が設定されていません");
    process.exit(1);
  }
  if (!opts.dryRun && !process.env.X_SHEET_ID) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const client = new Anthropic({ apiKey });
  const articles = readJson("articles.json").filter((a) => a.status === "published");
  const categories = readJson("categories.json");
  const seedData = loadSeeds();
  const month = new Date().getMonth() + 1;

  // 既存投稿（repost_rewrite 用 + 重複回避用）
  let existingPosts = [];
  if (!opts.dryRun) {
    try {
      existingPosts = await getExistingPosts();
    } catch {
      console.warn("既存投稿の取得に失敗（初回 or 認証エラー）。続行します。");
    }
  }

  // 記事選択（article_promo, gear_thread 用）
  const recentSlugs = new Set(
    existingPosts
      .filter((p) => p.type === "article_promo" && p.status !== "draft")
      .slice(0, articles.length - 1)
      .map((p) => p.articleSlug)
  );
  const articleCandidates = articles.filter((a) => !recentSlugs.has(a.slug));
  const selectCount = Math.min(6, articles.length);
  const selectedArticles =
    articleCandidates.length >= selectCount
      ? articleCandidates.sort(() => Math.random() - 0.5).slice(0, selectCount)
      : articles.sort(() => Math.random() - 0.5).slice(0, selectCount);

  const plan = determineGenerationPlan(opts);
  const allPosts = [];

  console.log(`\n生成プラン: ${plan.map((p) => `${p.type}(${p.count}件)`).join(", ")}`);
  console.log(`季節: ${month}月 - ${SEASON_CONTEXT[month]}\n`);

  for (const item of plan) {
    // repost_rewrite: 過去投稿チェック
    if (item.type === "repost_rewrite") {
      const thirtyDaysAgo = new Date();
      thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
      const rewriteCandidates = existingPosts.filter(
        (p) => p.status === "posted" && p.postedAt && new Date(p.postedAt) < thirtyDaysAgo
      );
      if (rewriteCandidates.length === 0) {
        console.log(`[repost_rewrite] 30日以上前の投稿がないためスキップ`);
        continue;
      }
    }

    // シード選択
    const seed = selectSeed(seedData, { type: item.type, month, axis: item.axis });

    // コンテキスト構築
    const context = {
      month,
      count: item.count,
      seed,
      articles: selectedArticles,
      categories,
    };

    // repost_rewrite: 過去投稿をコンテキストに追加
    if (item.type === "repost_rewrite") {
      const thirtyDaysAgo = new Date();
      thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
      context.existingPosts = existingPosts
        .filter((p) => p.status === "posted" && p.postedAt && new Date(p.postedAt) < thirtyDaysAgo)
        .slice(0, 10);
    }

    console.log(`[${item.type}] ${item.count}件を生成中...${seed ? ` (seed: ${seed.id})` : ""}`);

    // プロンプト生成
    const prompt = getPromptForType(item.type, context);

    // Claude API 呼び出し
    let response;
    try {
      response = await client.messages.create({
        model: "claude-sonnet-4-20250514",
        max_tokens: 4000,
        messages: [{ role: "user", content: prompt }],
      });
    } catch (err) {
      console.error(`[${item.type}] API呼び出し失敗: ${err.message}`);
      continue;
    }

    const content = response.content[0].text;
    const jsonMatch = content.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      console.error(`[${item.type}] JSON解析に失敗:\n${content.slice(0, 200)}`);
      continue;
    }

    let generated;
    try {
      generated = JSON.parse(jsonMatch[0]);
    } catch (err) {
      console.error(`[${item.type}] JSONパースエラー: ${err.message}`);
      continue;
    }

    // UTM パラメータ付与
    generated = generated.map((g) => addUtmIfNeeded(g, item.type));

    // NG チェック
    const isThread = item.type === "gear_thread";
    generated = generated.map((g) => {
      let check;
      if (isThread && g.tweets) {
        check = checkThreadContent(g.tweets, { type: item.type });
      } else {
        check = checkXPostContent(g.text, { type: item.type });
      }
      const errs = [...check.errors, ...check.warnings];
      return {
        ...g,
        validationErrors: errs.length > 0 ? errs.join(" / ") : "",
        _checkOk: check.ok,
      };
    });

    // ステータス判定
    const approvalLevel = getApprovalLevel(item.type);
    const posts = generated.map((g) => {
      let status;
      if (!g._checkOk) {
        status = "draft";
      } else if (opts.autoApprove || approvalLevel === "auto") {
        status = "approved";
      } else {
        status = "draft";
      }

      return {
        id: generateId(),
        type: item.type,
        text: isThread && g.tweets ? formatThreadForSheets(g.tweets) : g.text,
        articleSlug: g.articleSlug || "",
        url: g.url || "",
        hashtags: "",
        status,
        scheduledDate: "",
        generatedAt: new Date().toISOString(),
        postedAt: "",
        axis: seed?.axis || POST_TYPES[item.type].axis,
        seedId: seed?.id || "",
        validationErrors: g.validationErrors || "",
        autoApproved: status === "approved" ? "true" : "false",
      };
    });

    allPosts.push(...posts);

    // シード使用記録
    if (seed) markSeedUsed(seedData, seed.id);
  }

  // スケジュール割り当て
  const scheduledDates = getScheduledDates(allPosts.length);
  allPosts.forEach((p, i) => {
    p.scheduledDate = scheduledDates[i] || "";
  });

  // 結果出力
  console.log(`\n========== 生成結果: ${allPosts.length}件 ==========\n`);
  for (const p of allPosts) {
    const statusIcon = p.status === "approved" ? "v" : "x";
    console.log(`[${statusIcon}] [${p.type}] (${p.axis}) status=${p.status}`);
    if (p.text.startsWith("[THREAD]")) {
      const tweets = JSON.parse(p.text.replace("[THREAD] ", ""));
      tweets.forEach((t, i) => console.log(`  ${i + 1}. ${t}`));
    } else {
      console.log(`  ${p.text}`);
    }
    if (p.seedId) console.log(`  seed: ${p.seedId}`);
    if (p.validationErrors) console.log(`  NG: ${p.validationErrors}`);
    console.log("---");
  }

  // 保存
  if (opts.dryRun) {
    console.log("\n[DRY RUN] Sheets書き込み・seeds.json更新をスキップしました");
  } else {
    // Google Sheets 書き込み
    const sheets = await getSheets();
    const rows = allPosts.map((p) => [
      p.id,              // A
      p.type,            // B
      p.text,            // C
      p.articleSlug,     // D
      p.url,             // E
      p.hashtags,        // F
      p.status,          // G
      p.scheduledDate,   // H
      p.generatedAt,     // I
      p.postedAt,        // J
      p.axis,            // K
      p.seedId,          // L
      p.validationErrors,// M
      p.autoApproved,    // N
    ]);

    await sheets.spreadsheets.values.append({
      spreadsheetId: process.env.X_SHEET_ID,
      range: `${DRAFT_SHEET}!A:N`,
      valueInputOption: "RAW",
      requestBody: { values: rows },
    });

    // seeds.json 書き戻し
    saveSeeds(seedData);
    console.log(`\nSheets に ${allPosts.length}件を保存しました`);
  }
}

// === エントリポイント ===

const opts = parseArgs();
generatePosts(opts).catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
