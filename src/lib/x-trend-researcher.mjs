/**
 * X Trend Researcher — 毎日のトレンド収集 → 投稿草案生成 → Sheets 追記
 *
 * 実行フロー:
 *   Step 1: Brave Search で日本語キャンプ/アウトドアトレンドを収集
 *   Step 2: X API でキャンプ軸バズ投稿を収集（直近24時間）
 *   Step 3: Claude ライターパス: オリジナル投稿3案生成
 *   Step 4: Claude エディターパス: NG語/文体/具体性チェック・修正
 *   Step 5: Google Sheets「下書き管理」に追記
 *
 * 必要な環境変数:
 *   BRAVE_API_KEY        — Brave Search API キー
 *   TWITTER_BEARER_TOKEN — X API v2 Bearer Token
 *   ANTHROPIC_API_KEY    — Claude API キー
 *   GOOGLE_CREDENTIALS   — Google サービスアカウント JSON 文字列
 *   X_SHEET_ID           — 下書き管理 Google Sheets ID
 */

import { TwitterApi } from "twitter-api-v2";
import { google } from "googleapis";
import Anthropic from "@anthropic-ai/sdk";
import {
  loadEnv,
  readJson,
  checkResearchKillSwitch,
  ipv4Fetch,
} from "./x-agent-utils.mjs";
import { checkXPostContent } from "./x-content-checks.mjs";

const DRAFT_SHEET = "下書き管理";

const TREND_QUERIES = [
  "キャンプ アウトドア 2026 トレンド 人気",
  "キャンプギア 新作 おすすめ",
  "ソロキャンプ ファミリーキャンプ 話題",
  "アウトドア 焚き火 テント 話題",
  "キャンプ 料理 道具",
];

const CAMP_BUZZ_QUERIES = [
  "(キャンプ OR アウトドア OR 焚き火) -is:retweet lang:ja",
  "(キャンプギア OR キャンプ道具) -is:retweet lang:ja",
];

// === Step 1: Brave Search トレンド収集 ===

async function searchBraveTrends(braveApiKey, maxQueries = 5) {
  const queries = TREND_QUERIES.slice(0, maxQueries);
  const results = [];

  for (const q of queries) {
    const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(q)}&count=5&country=jp`;
    try {
      const res = await ipv4Fetch(url, {
        headers: {
          "X-Subscription-Token": braveApiKey,
          Accept: "application/json",
        },
      });
      if (!res.ok) {
        console.warn(`  Brave Search エラー (${q}): HTTP ${res.status}`);
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }
      const data = await res.json();
      const items = (data.web?.results || []).map((r) => ({
        title: r.title,
        snippet: r.description || "",
        url: r.url,
      }));
      results.push({ query: q, results: items });
    } catch (err) {
      console.warn(`  Brave Search 例外 (${q}): ${err.message}`);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }

  console.log(`  Brave Search 完了: ${results.length}/${queries.length}クエリ`);
  return results;
}

// === Step 2: X バズ投稿収集 ===

async function searchXBuzz(xClient) {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const posts = [];

  for (const query of CAMP_BUZZ_QUERIES) {
    try {
      const res = await xClient.v2.search(query, {
        max_results: 20,
        "tweet.fields": ["public_metrics", "created_at"],
        start_time: since,
      });
      for (const t of res.data?.data || []) {
        const m = t.public_metrics || {};
        const score =
          (m.like_count || 0) * 3 +
          (m.retweet_count || 0) * 5 +
          (m.bookmark_count || 0) * 4;
        posts.push({ text: t.text, likes: m.like_count || 0, retweets: m.retweet_count || 0, score });
      }
    } catch (err) {
      console.warn(`  X バズ検索エラー: ${err.message}`);
    }
  }

  return posts.sort((a, b) => b.score - a.score).slice(0, 10);
}

// === Step 3: Claude ライターパス ===

async function writeTrendPost(claude, trends, buzz) {
  const config = readJson("account-config.json") || {};
  const persona = config.persona || {};

  const personaPreamble = `あなたは「ギア男」です。
- ${persona.occupation || "開業医"}。キャンプ歴${persona.experience || "10年"}、家族キャンプ中心
- メイン装備: ${persona.mainGear || "スノーピーク アメニティドームL＋メッシュタープ"}
- 文体: ですます調、友人に話しかけるような温かさ。一人称「僕」
- トーン: 断定より「個人的には〜」「3年使った結論から言うと〜」型を優先`;

  const patterns = readJson("high-performer-patterns.json");
  const patternBlock = patterns?.patterns?.length
    ? `## 参考：自分の高エンゲージ投稿パターン\n${patterns.patterns
        .map((p) => `- ${p.postType}: 「${(p.examples?.[0] || "").slice(0, 50)}...」`)
        .join("\n")}\n\n`
    : "";

  const trendSummary = trends
    .flatMap((t) => t.results.slice(0, 2))
    .map((r) => `- ${r.title}: ${r.snippet.slice(0, 80)}`)
    .slice(0, 10)
    .join("\n");

  const buzzSummary = buzz
    .slice(0, 5)
    .map((b) => `- ♥${b.likes} RT${b.retweets}: ${b.text.slice(0, 60)}`)
    .join("\n");

  const month = new Date().getMonth() + 1;
  const seasonCtx = config.seasonContext?.[String(month)] || "";

  try {
    const response = await claude.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 3000,
      messages: [
        {
          role: "user",
          content: `${personaPreamble}

${patternBlock}## 今日のトレンド情報
${trendSummary || "（情報なし）"}

## X バズ投稿（直近24時間）
${buzzSummary || "（情報なし）"}

## 季節コンテキスト
${seasonCtx}

## タスク
上記情報を踏まえて、ギア男のオリジナルX投稿を3案作ってください。
URLは入れない。ハッシュタグは入れない。200文字以内。
「最高」「最強」「絶対」「神」等の煽り語禁止。体験談・気づき・失敗談ベースで。

postType は outdoor_tip / failure_story / news_comment から選ぶ。

## 出力（JSON配列）
[
  {
    "text": "投稿テキスト",
    "postType": "outdoor_tip",
    "axis": "camp",
    "rationale": "なぜこの投稿か（30文字以内）"
  }
]`,
        },
      ],
    });

    const text = response.content[0].text;
    const jsonMatch = text.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      console.warn("  writeTrendPost: JSON 取得失敗");
      return [];
    }
    return JSON.parse(jsonMatch[0]);
  } catch (err) {
    console.warn(`  writeTrendPost エラー: ${err.message}`);
    return [];
  }
}

// === Step 4: Claude エディターパス ===

async function editTrendPost(claude, drafts) {
  if (!drafts.length) return drafts;

  const config = readJson("account-config.json") || {};
  const ngWords = [
    ...(config.ngWords?.hype || []),
    ...(config.ngWords?.template || []),
    ...(config.ngWords?.medical || []),
    ...(config.ngWords?.landmark || []),
  ];
  const toneRules = config.tone?.rules || [];

  const draftsText = drafts.map((d, idx) => `[${idx + 1}] "${d.text}"`).join("\n");

  try {
    const response = await claude.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 2000,
      messages: [
        {
          role: "user",
          content: `以下のX投稿草案をチェック・修正してください。

## チェックルール
1. NGワード禁止: ${ngWords.join(", ")}
2. 文体: ${toneRules.join(" / ")}
3. 200文字以内
4. 体験談・データ・視点のいずれか1つ以上含む
5. 「〜らしい」「〜ではないでしょうか」等の曖昧表現は禁止（具体性を持たせる）

## 草案
${draftsText}

## 出力（JSON配列）
[
  {
    "index": 1,
    "text": "修正後テキスト",
    "changed": false
  }
]`,
        },
      ],
    });

    const text = response.content[0].text;
    const jsonMatch = text.match(/\[[\s\S]*\]/);
    if (!jsonMatch) return drafts;

    const edited = JSON.parse(jsonMatch[0]);
    return drafts.map((d, idx) => {
      const e = edited.find((x) => x.index === idx + 1);
      if (!e) return d;
      return { ...d, text: e.text || d.text, _raw: e.changed ? d.text : undefined };
    });
  } catch (err) {
    console.warn(`  editTrendPost エラー: ${err.message}`);
    return drafts;
  }
}

// === Step 5: Google Sheets 追記 ===

async function appendTrendPostsToSheets(sheets, posts) {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) throw new Error("X_SHEET_ID が設定されていません");

  // JST で今日の日付を算出
  const nowJst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const tomorrow = new Date(nowJst.getTime() + 24 * 60 * 60 * 1000);
  const scheduledDate = tomorrow.toISOString().slice(0, 10);
  const generatedAt = nowJst.toISOString().slice(0, 19).replace("T", " ");

  const rows = posts.map((p) => {
    const rand4 = Math.random().toString(36).slice(2, 6);
    const id = `tr-${nowJst.toISOString().slice(0, 10).replace(/-/g, "")}-${rand4}`;
    const check = checkXPostContent(p.text || "");

    return [
      id,                              // A: id
      p.postType || "outdoor_tip",     // B: type
      p.text || "",                    // C: text
      "",                              // D: articleSlug
      "",                              // E: url
      "",                              // F: hashtags
      check.ok ? "draft" : "needs_review", // G: status
      scheduledDate,                   // H: scheduledDate
      generatedAt,                     // I: generatedAt
      "",                              // J: postedAt
      p.axis || "camp",                // K: axis
      "trend-researcher",              // L: seedId
      [...check.errors, ...check.warnings].join(" / ") || "", // M: validationErrors
      "false",                         // N: autoApproved
      "",                              // O: selfScore
      "",                              // P: firstLinePattern
      "",                              // Q: similarityScore
      "0",                             // R: retryCount
      "",                              // S: selfReply
      "",                              // T: formatPattern
      "",                              // U: imageUrl
    ];
  });

  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A:U`,
    valueInputOption: "RAW",
    insertDataOption: "INSERT_ROWS",
    requestBody: { values: rows },
  });

  console.log(`  Sheets 追記完了: ${rows.length}件`);
}

// === argv パーサー ===

export function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, maxQueries: 5 };
  for (const a of args) {
    if (a === "--dry-run") opts.dryRun = true;
    const mq = a.match(/^--max-queries=(\d+)$/);
    if (mq) opts.maxQueries = parseInt(mq[1], 10);
  }
  return opts;
}

// === メインエントリ ===

export async function runTrendResearcher(opts = {}) {
  loadEnv();

  const ks = checkResearchKillSwitch();
  if (ks.killed) {
    console.log(`[trend-researcher] kill_switch=true のため終了: ${ks.reason}`);
    return { skipped: true };
  }

  const braveApiKey = process.env.BRAVE_API_KEY;
  if (!braveApiKey) throw new Error("BRAVE_API_KEY が設定されていません");

  const xClient = new TwitterApi(process.env.TWITTER_BEARER_TOKEN);
  const claude = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

  let sheets = null;
  if (!opts.dryRun) {
    sheets = google.sheets({
      version: "v4",
      auth: new google.auth.GoogleAuth({
        credentials: JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}"),
        scopes: ["https://www.googleapis.com/auth/spreadsheets"],
      }),
    });
  }

  const maxQueries = opts.maxQueries ?? 5;

  // Step 1: Brave トレンド収集
  console.log("\n[Step 1] Brave Search トレンド収集...");
  const trends = await searchBraveTrends(braveApiKey, maxQueries);

  // Step 2: X バズ収集
  console.log("\n[Step 2] X バズ投稿収集...");
  const buzz = await searchXBuzz(xClient);
  console.log(`  X バズ: ${buzz.length}件`);

  // Step 3: ライターパス
  console.log("\n[Step 3] 投稿草案生成...");
  const drafts = await writeTrendPost(claude, trends, buzz);
  console.log(`  草案: ${drafts.length}案`);

  if (!drafts.length) {
    console.warn("[trend-researcher] 草案生成失敗 — 終了");
    return { skipped: false, generated: 0 };
  }

  // Step 4: エディターパス
  console.log("\n[Step 4] 草案ブラッシュアップ...");
  const finalDrafts = await editTrendPost(claude, drafts);

  // Step 5: Sheets 追記
  if (opts.dryRun) {
    console.log("\n[DRY RUN] Sheets 追記スキップ");
    for (const d of finalDrafts) {
      const check = checkXPostContent(d.text || "");
      console.log(`  [${d.postType}/${d.axis}] ${check.ok ? "✓" : "⚠"} ${d.text}`);
    }
  } else {
    console.log("\n[Step 5] Sheets 追記...");
    await appendTrendPostsToSheets(sheets, finalDrafts);
  }

  console.log("\n[完了] Trend Researcher 終了");
  return { skipped: false, generated: finalDrafts.length };
}
