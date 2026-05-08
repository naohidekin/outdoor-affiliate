/**
 * X投稿自動生成モジュール（4軸10タイプ対応）
 *
 * Claude APIを使ってX投稿を生成し、Google Sheets「下書き管理」に保存する。
 * CLI からは scripts/generate-x-posts.js 経由で呼び出される。
 * Next.js API route からは直接 import して呼べる。
 *
 * エクスポート:
 *   - generatePosts(opts): 生成実行。戻り値 { generated, blocked, qualityRetries, posts }
 *   - parseArgs(): process.argv から opts オブジェクトを作る（CLI用）
 */

import Anthropic from "@anthropic-ai/sdk";
import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { list as listBlob } from "@vercel/blob";

import {
  SITE_URL,
  CATEGORY_HASHTAGS,
  SEASON_CONTEXT,
  POST_TYPES,
  ACCOUNT_CONFIG,
  getApprovalLevel,
  getPromptForType,
  buildNewsCommentPrompt,
} from "./x-post-prompts.mjs";

import {
  checkXPostContent,
  checkThreadContent,
  applyChecksAndLabels,
} from "./x-content-checks.mjs";

import {
  loadEnv,
  bigramJaccard,
  loadPostHistory,
  appendToPostHistory,
  classifyFirstLinePattern,
  readJson as readDataJson,
  ipv4Fetch,
} from "./x-agent-utils.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// src/lib/ から data/ はルート直下なので 2つ上がる
const DATA_DIR = path.join(__dirname, "..", "..", "data");

const DRAFT_SHEET = "下書き管理";

// フォロワー増加フェーズ: article_promo（サイト誘導型）を生成対象から除外
const FOLLOWER_GROWTH_MODE = true;
const GROWTH_MODE_EXCLUDED_TYPES = new Set(["article_promo"]);

// env はモジュールロード時に読み込む。Next.js 経由でimportした場合は
// Next.js 側が既に process.env を管理しているため、loadEnv は冪等（既存値を上書きしない）。
loadEnv();

// === CLI オプション ===

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    autoApprove: false,
    dryRun: false,
    type: null,
    count: null,
    axis: null,
    planFile: null,
    research: false,
  };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    // --key=value 形式も受け付ける
    const eqIdx = arg.indexOf("=");
    const key = eqIdx !== -1 ? arg.slice(0, eqIdx) : arg;
    const val = eqIdx !== -1 ? arg.slice(eqIdx + 1) : args[i + 1];
    switch (key) {
      case "--auto-approve": opts.autoApprove = true; break;
      case "--dry-run":      opts.dryRun = true; break;
      case "--research":     opts.research = true; break;
      case "--type":         opts.type = val; if (eqIdx === -1) i++; break;
      case "--count":        opts.count = parseInt(val, 10); if (eqIdx === -1) i++; break;
      case "--axis":         opts.axis = val; if (eqIdx === -1) i++; break;
      case "--plan-file":    opts.planFile = val; if (eqIdx === -1) i++; break;
    }
  }
  // バリデーション
  if (opts.type && !POST_TYPES[opts.type]) {
    console.error(`未知のタイプ: ${opts.type}`);
    console.error(`有効なタイプ: ${Object.keys(POST_TYPES).join(", ")}`);
    process.exit(1);
  }
  if (opts.axis && !["camp", "parenting", "doctor"].includes(opts.axis)) {
    console.error(`未知の軸: ${opts.axis}`);
    console.error("有効な軸: camp, parenting, doctor");
    process.exit(1);
  }
  return opts;
}

// === ニュースフィード ===

function loadNewsFeed(count) {
  const filePath = path.join(DATA_DIR, "news-feed.json");
  if (!fs.existsSync(filePath)) {
    console.warn("[news_comment] data/news-feed.json が無いため空で続行");
    return [];
  }
  let all;
  try {
    all = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch (err) {
    console.warn(`[news_comment] news-feed.json 読み込み失敗: ${err.message}`);
    return [];
  }
  const usable = (Array.isArray(all) ? all : []).filter((n) => !n.used && !n.sensitive);
  if (usable.length === 0) {
    console.warn("[news_comment] 使用可能なニュースなし、空で続行");
    return [];
  }
  return usable.sort(() => Math.random() - 0.5).slice(0, count);
}

function markNewsUsed(usedItems) {
  const filePath = path.join(DATA_DIR, "news-feed.json");
  try {
    const all = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    const usedIds = new Set(usedItems.map((n) => n.id));
    const updated = all.map((n) => (usedIds.has(n.id) ? { ...n, used: true } : n));
    fs.writeFileSync(filePath, JSON.stringify(updated, null, 2), "utf-8");
  } catch (err) {
    console.warn(`[markNewsUsed] 書き込み失敗（read-only fs か）: ${err.message}`);
  }
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
      range: `${DRAFT_SHEET}!A2:R`,
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
        selfScore: r[14] ? parseFloat(r[14]) : null,
        firstLinePattern: r[15] || null,
        similarityScore: r[16] ? parseFloat(r[16]) : null,
        retryCount: r[17] ? parseInt(r[17], 10) : null,
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
  try {
    fs.writeFileSync(seedPath, JSON.stringify(seedData, null, 2) + "\n", "utf-8");
  } catch (err) {
    // Vercel 等の read-only filesystem では書き込み不能。ログだけ出して続行。
    console.warn(`[saveSeeds] 書き込み失敗（read-only fs か）: ${err.message}`);
  }
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

const UTM_TYPES = new Set(["article_promo", "seasonal_hook", "parenting_outdoor", "news_comment", "rakuten_room_pick"]);

function addUtmIfNeeded(post, type) {
  // UTM 付与は対象タイプのみ
  if (UTM_TYPES.has(type) && post.url) {
    const utmSuffix = `utm_source=x&utm_medium=social&utm_campaign=${type}`;
    const sep = post.url.includes("?") ? "&" : "?";
    post.url = `${post.url}${sep}${utmSuffix}`;
  }

  // 全タイプ共通: 本文のURL全除去（URLは必ずセルフリプライのみ — 本文掲載禁止）
  const stripUrl = (t) =>
    (t || "").replace(/https?:\/\/\S+/g, "").replace(/\n\n\n+/g, "\n\n").trim();

  if (post.text) {
    post.text = stripUrl(post.text);
  }
  if (post.tweets) {
    post.tweets = post.tweets.map((t) =>
      stripUrl(t)
    );
  }

  return post;
}

// === gear_thread Sheets フォーマット ===

function formatThreadForSheets(tweets) {
  return `[THREAD] ${JSON.stringify(tweets)}`;
}

// === 自己採点 ===

async function selfScorePost(client, { type, axis, text }) {
  const prompt = `あなたは X 投稿の品質審査員です。
以下の投稿を10基準で採点してください（各0〜10点）。
**平均6.5未満は不合格**。ペルソナ一致度(#5)・軸適合(#9)・フック(#1)は特に意識して採点。
全体に厳しすぎず、6点台の標準的な投稿は通過させる方針。お世辞は不要。

## 投稿
タイプ: ${type}
軸: ${axis}
テキスト:
${text}

## 採点基準（各0〜10点）
1. フックの強さ: 1行目で「読み進めたい」と思わせる力。スクロールを止められるか
2. 有益性: 読者にとって実用的な価値があるか。「知ってよかった」と思えるか
3. 具体性: 数値・製品名・状況・体験の具体性。抽象的な一般論になっていないか
4. テンポ感: 文のリズム・読みやすさ。句読点の間隔、改行のバランス
5. ペルソナ一致度: 「ギア男」のキャラ（37歳・長野・キャンプ歴10年・2児の父）に合致しているか
6. オリジナリティ: 既視感がないか。テンプレ的・どこかで見た投稿になっていないか
7. ブクマ誘発力: 「あとで見返したい」「保存しておきたい」と思わせる情報密度
8. アクション誘発: いいね・RT・リプライしたくなる衝動を生むか
9. 軸適合: 発信軸（${axis}）のトーン・ターゲット層に合致しているか
10. 文字数・構成: 280文字以内に収まり、導入→本題→締めの構成バランスが取れているか

## 出力形式（JSONのみ）
{ "scores": [8, 7, 9, 8, 7, 8, 9, 6, 7, 8], "total": 7.7, "comment": "改善ポイントを1文で" }`;

  try {
    // 自己採点は Haiku（軽量・高速）で十分。生成本体は Sonnet のまま。
    // Vercel Hobby 300s 上限でのタイムアウトを避けるため、採点のみ速度優先に切り替え。
    const response = await client.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 500,
      messages: [{ role: "user", content: prompt }],
    });
    const jsonMatch = response.content[0].text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return { total: 0, scores: [], comment: "JSON parse failed" };
    return JSON.parse(jsonMatch[0]);
  } catch (err) {
    console.warn(`[self-score] 採点失敗: ${err.message}`);
    return { total: 7.0, scores: [], comment: "scoring failed, default pass" };
  }
}

// === 類似チェック ===

function checkSimilarity(newText) {
  const history = loadPostHistory();
  let maxSimilarity = 0;
  for (const entry of history.entries) {
    const sim = bigramJaccard(newText, entry.text);
    if (sim > maxSimilarity) maxSimilarity = sim;
  }
  return maxSimilarity;
}

// === パターンローテーション（書き出し + フォーマット） ===

function buildPatternRotationBlock() {
  const history = loadPostHistory();
  const patternsData = readDataJson("first-line-patterns.json");
  if (!patternsData || !patternsData.categories) return "";

  const recentPatterns = history.entries
    .slice(-3)
    .map((e) => e.firstLinePattern)
    .filter(Boolean);

  if (recentPatterns.length === 0) return "";

  // 直近パターン以外のカテゴリから例を選出
  const availableCategories = patternsData.categories.filter(
    (c) => !recentPatterns.includes(c.id)
  );
  if (availableCategories.length === 0) return "";

  const examples = availableCategories
    .sort(() => Math.random() - 0.5)
    .slice(0, 3)
    .map((c) => c.examples[Math.floor(Math.random() * c.examples.length)]);

  return `\n## 書き出しパターン指示
以下のパターンは直近で使用済みのため避けてください: ${recentPatterns.join(", ")}
代わりに以下の書き出しスタイルを参考にしてください:
${examples.map((e) => `- 「${e}」`).join("\n")}`;
}

// === 投稿フォーマットパターンローテーション ===

function buildFormatPatternBlock() {
  const history = loadPostHistory();
  const formatData = readDataJson("post-format-patterns.json");
  if (!formatData || !formatData.formats) return "";

  // 直近3件の formatPattern を取得
  const recentFormats = history.entries
    .slice(-3)
    .map((e) => e.formatPattern)
    .filter(Boolean);

  // 全サブカテゴリをフラット化
  const allPatterns = [];
  for (const fmt of formatData.formats) {
    for (const sub of fmt.subCategories) {
      const fullId = `${fmt.id}/${sub.id}`;
      allPatterns.push({
        fullId,
        parentName: fmt.name,
        subName: sub.name,
        description: sub.description,
        promptHint: sub.promptHint,
        parentDescription: fmt.description,
      });
    }
  }

  // 直近3件を除外
  const available = allPatterns.filter((p) => !recentFormats.includes(p.fullId));
  const pool = available.length > 0 ? available : allPatterns;

  // ランダムに2〜3パターン選出（Claudeに選択肢を与える）
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  const selected = shuffled.slice(0, 3);

  const lines = selected.map(
    (p) => `- **${p.fullId}** [${p.parentName} > ${p.subName}]: ${p.promptHint}`
  );

  const avoidList = recentFormats.length > 0
    ? `\n⚠️ 直近使用済み（避けること）: ${recentFormats.join(", ")}`
    : "";

  return `\n## 投稿フォーマットパターン指示
以下のフォーマットパターンから選んで投稿を構成してください。
複数件生成する場合は、異なるパターンを使い分けること。
${avoidList}

### 推奨パターン:
${lines.join("\n")}

**formatPattern フィールドに使用したパターンID（例: short_complete/expose）を必ず記載すること。**`;
}

// === バズ1行目参照ブロック ===

function buildBuzzFirstLinesBlock(currentType = null) {
  const buzzData = readDataJson("buzz-first-lines.json");
  if (!buzzData || !buzzData.lines || buzzData.lines.length === 0) return "";

  // パターン別にグループ化し、高エンゲージメントのものを優先
  const lines = buzzData.lines
    .filter((l) => l.text && l.text.length >= 10)
    .sort((a, b) => ((b.bookmarks || 0) + (b.likes || 0)) - ((a.bookmarks || 0) + (a.likes || 0)));

  // ランダムに5件選出（同じものばかり参照しないように）
  const shuffled = [...lines].sort(() => Math.random() - 0.5);
  const selected = shuffled.slice(0, 5);

  if (selected.length === 0) return "";

  return `\n## バズった投稿の1行目（参考・構造だけ学んで自分のジャンルに変換すること）
${selected.map((l) => `- 「${l.text}」 [${l.pattern || "未分類"}]${l.likes ? ` ♥${l.likes}` : ""}`).join("\n")}
**注意**: これらをそのまま使わない。構造・リズム・フック感だけ参考にして、自分のネタで書く。`;
}

// === リサーチデータ注入 ===

function loadLatestResearch() {
  const researchDir = path.join(DATA_DIR, "x-research");
  if (!fs.existsSync(researchDir)) return null;
  const files = fs.readdirSync(researchDir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .reverse();
  if (files.length === 0) return null;
  try {
    return JSON.parse(fs.readFileSync(path.join(researchDir, files[0]), "utf-8"));
  } catch {
    return null;
  }
}

function buildResearchBlock(axis) {
  const research = loadLatestResearch();
  if (!research) return "";

  const axisData = research.axes?.[axis] || research.axes?.["camp"];
  if (!axisData?.summary) return "";

  const s = axisData.summary;
  const topPosts = (axisData.posts || []).slice(0, 3);

  const lines = [
    `\n## リサーチデータ（${research.date}調査 / ${axis}軸 高エンゲージメント投稿の傾向）`,
    `- 文字数・行数: 平均${s.avgChars}文字 / ${s.avgLines}行`,
    `- 絵文字: 平均${s.avgEmoji}個/投稿`,
    `- 主要フック: ${s.topHooks?.join(", ") || "不明"}`,
    `- リスト型: ${s.listRate}% / URLあり: ${s.urlRate}%`,
    `- 総評: ${s.insight}`,
  ];

  if (topPosts.length > 0) {
    lines.push("\n### 高エンゲージメント投稿の例（構造を参考にすること）");
    for (const p of topPosts) {
      const preview = p.text.slice(0, 60).replace(/\n/g, " ");
      lines.push(`- 「${preview}…」 ♥${p.metrics.likes} RT${p.metrics.retweets}`);
    }
    lines.push("**注意**: これらを直接引用・転用しない。フック構造・リズムだけ参考にすること。");
  }

  return lines.join("\n");
}

// === Viral Scout 分析結果の注入 ===

function buildViralScoutBlock(axis) {
  const filePath = path.join(DATA_DIR, "viral-scout-results.json");
  if (!fs.existsSync(filePath)) return "";
  let data;
  try {
    data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch {
    return "";
  }
  if (!data.aggregateAnalysis || !Array.isArray(data.viralPosts)) return "";

  // 鮮度チェック: 7日以上古ければ警告的に扱う（ただし無視はしない）
  const scoutedAt = data.scoutedAt ? new Date(data.scoutedAt) : null;
  const ageDays = scoutedAt ? Math.floor((Date.now() - scoutedAt) / 86400000) : null;

  const axisKey = (axis === "all" || axis === "rotate" || !axis) ? null : axis;
  const byAxis = axisKey ? data.aggregateAnalysis.byAxis?.[axisKey] : null;

  const aggLines = [];
  if (byAxis && byAxis.count >= 3) {
    aggLines.push(`### ${axisKey}軸のバイラル傾向（N=${byAxis.count}, 平均engagement=${byAxis.avgEngagement}）`);
    if (byAxis.topHooks?.length) {
      aggLines.push(`- トップフック: ${byAxis.topHooks.slice(0, 3).map((h) => `${h.pattern}(${h.pct}%)`).join(" / ")}`);
    }
    if (byAxis.topFormats?.length) {
      aggLines.push(`- 形式: ${byAxis.topFormats.slice(0, 3).map((h) => `${h.pattern}(${h.pct}%)`).join(" / ")}`);
    }
  } else {
    const agg = data.aggregateAnalysis;
    aggLines.push(`### 全軸のバイラル傾向（N=${agg.totalAnalyzed}）`);
    if (agg.topHooks?.length) aggLines.push(`- トップフック: ${agg.topHooks.slice(0, 3).map((h) => `${h.pattern}(${h.pct}%)`).join(" / ")}`);
    if (agg.topEmotionalTriggers?.length) aggLines.push(`- 感情トリガー: ${agg.topEmotionalTriggers.slice(0, 3).map((h) => `${h.pattern}(${h.pct}%)`).join(" / ")}`);
    if (agg.topFormats?.length) aggLines.push(`- 形式: ${agg.topFormats.slice(0, 3).map((h) => `${h.pattern}(${h.pct}%)`).join(" / ")}`);
    if (agg.topShareability?.length) aggLines.push(`- シェア動機: ${agg.topShareability.slice(0, 3).map((h) => `${h.pattern}(${h.pct}%)`).join(" / ")}`);
  }

  // 高adaptability（ギア男に転用しやすい）を優先し、軸マッチを優先
  const axisPosts = data.viralPosts
    .filter((p) => !axisKey || p.axis === axisKey)
    .sort((a, b) => (b.metrics?.engagementScore || 0) - (a.metrics?.engagementScore || 0));

  const highAdapt = axisPosts.filter((p) => p.analysis?.adaptability === "high");
  const picked = (highAdapt.length >= 3 ? highAdapt : axisPosts).slice(0, 3);

  const exampleLines = picked.map((p) => {
    const t = (p.text || "").replace(/\s+/g, " ").slice(0, 90);
    const m = p.metrics || {};
    const a = p.analysis || {};
    const techs = (a.keyTechniques || []).slice(0, 2).join("/");
    return `- 「${t}…」(♥${m.likes || "?"} RT${m.retweets || "?"} / hook=${a.hook || "?"} / format=${a.format || "?"}${techs ? " / 手法=" + techs : ""})`;
  });

  if (aggLines.length === 0 && exampleLines.length === 0) return "";

  const dateStr = scoutedAt ? scoutedAt.toISOString().slice(0, 10) : "?";
  const freshness = ageDays !== null && ageDays > 7 ? ` ⚠️ ${ageDays}日前のデータ` : "";

  return `\n## Viral Scout 分析（${dateStr}時点${freshness}）— 実際に伸びている投稿の構造を反映せよ
${aggLines.join("\n")}

### ${axisKey || "全軸"}の高エンゲージメント実例（構造・フック・手法だけ学ぶこと）
${exampleLines.join("\n")}

**使い方**: 上の「hook / format / 手法」の組み合わせを自分のネタで再現する。本文そのものは絶対に転用しない。ギア男ペルソナと今回のtypeに沿った題材で、同じ型だけ真似ること。`;
}

// === Analyst ディレクティブ注入 ===

function buildAnalystHintsBlock(currentType = null) {
  const feedback = readDataJson("analyst-feedback.json");
  if (!feedback) return "";

  const parts = [];

  // ディレクティブ（優先表示）
  if (feedback.writerDirectives && feedback.writerDirectives.length > 0) {
    const relevant = feedback.writerDirectives.filter((d) =>
      d.appliesTo.includes("all") || d.appliesTo.includes(currentType)
    );
    if (relevant.length > 0) {
      parts.push("## アナリストからの指示（必ず従うこと）");
      for (const d of relevant) {
        const priority = d.priority === "high" ? "【必須】" : "";
        parts.push(`- ${priority}${d.directive}（理由: ${d.reason}）`);
      }
    }
  }

  // 従来のヒント（補足情報）
  if (feedback.writerHints && feedback.writerHints.length > 0) {
    parts.push("\n## 直近の分析フィードバック");
    // ディレクティブと重複しない分だけ追加（先頭5件）
    const hintsWithoutDirectives = feedback.writerHints.filter(
      (h) => !h.startsWith("【重要】")
    );
    for (const h of hintsWithoutDirectives.slice(0, 5)) {
      parts.push(`- ${h}`);
    }
  }

  return parts.length > 0 ? "\n" + parts.join("\n") : "";
}

// === ハイパフォーマーパターン few-shot injection ===

function buildHighPerformerBlock() {
  const filePath = path.join(DATA_DIR, "high-performer-patterns.json");
  if (!fs.existsSync(filePath)) return "";

  let data;
  try {
    data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch {
    return "";
  }

  if (!data || !data.patterns || data.patterns.length === 0) return "";

  const lines = [];
  for (const p of data.patterns) {
    if (!p.examples || p.examples.length === 0) continue;
    lines.push(`### [${p.postType}] (平均スコア: ${p.avgEngagementScore})`);
    for (const ex of p.examples) {
      lines.push(`- 「${ex}」`);
    }
  }

  if (lines.length === 0) return "";

  const updatedAt = data.updatedAt ? data.updatedAt.slice(0, 10) : "?";
  return `\n## 実績の高い書き出し例（${updatedAt}時点・上位${data.topN || "?"}件から抽出）
同じ型・トーンを参考にしつつ、題材は今回のネタに置き換えること。そのまま転用禁止。
${lines.join("\n")}`;
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
      // フォロワー増加モード: サイト誘導型タイプを除外
      if (FOLLOWER_GROWTH_MODE && GROWTH_MODE_EXCLUDED_TYPES.has(type)) continue;
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

// === 自動画像添付 ===

// type 別の Unsplash 検索クエリ
const UNSPLASH_QUERIES = {
  outdoor_tip: "camping outdoor nature tips",
  seasonal_hook: "outdoor seasonal camping nature",
  failure_story: "camping adventure outdoor fun",
  parenting_outdoor: "family camping children outdoor",
  ai_dev_log: "laptop coding nature",
  doc_health_tip: "doctor health wellness lifestyle",
  poll_question: "outdoor camping choice gear",
  news_comment: "news outdoor",
  repost_rewrite: "outdoor camping nature",
  rakuten_room_pick: "camping gear equipment outdoor",
};

/**
 * Vercel Blob 上の 4コマ漫画・キーイラスト URL を全件取得。
 * BLOB_READ_WRITE_TOKEN 未設定時は空配列を返し、呼び出し側は Unsplash fallback。
 */
async function loadBlobImagePool() {
  if (!process.env.BLOB_READ_WRITE_TOKEN) return [];
  try {
    const urls = [];
    for (const prefix of ["4koma-", "keyvisual-"]) {
      const { blobs } = await listBlob({ prefix });
      for (const b of blobs) urls.push(b.url);
    }
    return urls;
  } catch (err) {
    console.warn(`[loadBlobImagePool] ${err.message}`);
    return [];
  }
}

/**
 * Unsplash で type に合った写真URLを1件取得。失敗時は null。
 */
async function fetchUnsplashImage(type) {
  const key = process.env.UNSPLASH_ACCESS_KEY;
  if (!key) return null;
  const query = UNSPLASH_QUERIES[type] || "outdoor camping nature";
  try {
    const url = `https://api.unsplash.com/search/photos?query=${encodeURIComponent(query)}&per_page=10&orientation=landscape`;
    const res = await fetch(url, { headers: { Authorization: `Client-ID ${key}` } });
    if (!res.ok) return null;
    const data = await res.json();
    const photos = data.results || [];
    if (!photos.length) return null;
    const photo = photos[Math.floor(Math.random() * photos.length)];
    return photo.urls?.regular ? `${photo.urls.regular}&w=1200&q=80` : null;
  } catch (err) {
    console.warn(`[fetchUnsplashImage] ${err.message}`);
    return null;
  }
}

/**
 * 投稿に自動添付する画像URLを選ぶ。
 * 優先順序: Blob プール（4コマ・キーイラスト）→ Unsplash → null
 */
async function pickAutoImage(type, blobImagePool) {
  if (Array.isArray(blobImagePool) && blobImagePool.length > 0) {
    return blobImagePool[Math.floor(Math.random() * blobImagePool.length)];
  }
  const unsplashUrl = await fetchUnsplashImage(type);
  return unsplashUrl || "";
}

// === メイン ===

async function generatePosts(opts) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("ANTHROPIC_API_KEY が設定されていません");
  }
  if (!opts.dryRun && !process.env.X_SHEET_ID) {
    throw new Error("X_SHEET_ID が設定されていません");
  }

  // 品質ゲートでの再生成回数を追跡（API経由で呼ばれた時に返す）
  let qualityRetries = 0;

  const client = new Anthropic({ apiKey, fetch: ipv4Fetch, maxRetries: 3 });
  const articles = readJson("articles.json").filter((a) => a.status === "published");
  const categories = readJson("categories.json");
  const productsData = readJson("products.json");
  const products = productsData.products || productsData;
  const seedData = loadSeeds();
  const month = new Date().getMonth() + 1;

  // 安全装置の閾値（account-config.json から）
  const safetyConfig = ACCOUNT_CONFIG.safety || {};
  const QUALITY_THRESHOLD = safetyConfig.qualityThreshold || 7.0;
  const SIMILARITY_THRESHOLD = safetyConfig.similarityThreshold || 0.85;
  const MAX_RETRIES = safetyConfig.maxRetries || 2;

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

  // プラン決定: --plan-file があれば Researcher の出力を使用
  let plan;
  if (opts.planFile) {
    const planPath = path.join(__dirname, "..", opts.planFile);
    if (fs.existsSync(planPath)) {
      const weeklyPlan = JSON.parse(fs.readFileSync(planPath, "utf-8"));
      plan = weeklyPlan.plan || [];
      console.log(`[plan-file] ${opts.planFile} から ${plan.length} タイプのプランを読み込み`);
    } else {
      console.warn(`[plan-file] ${opts.planFile} が見つかりません。通常プランで続行`);
      plan = determineGenerationPlan(opts);
    }
  } else {
    plan = determineGenerationPlan(opts);
  }

  const allPosts = [];
  const usedNewsItems = [];
  const patternsData = readDataJson("first-line-patterns.json");

  // 投稿に自動添付する画像URL一覧を1回だけ取得（Vercel Blob の 4koma/keyvisual を優先）
  // BLOB_READ_WRITE_TOKEN 未設定時はスキップして Unsplash fallback
  const blobImageUrls = await loadBlobImagePool();
  console.log(`画像プール: Blob ${blobImageUrls.length}件 / Unsplash fallback有効`);

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

    // rakuten_room_pick: ROOM投稿済み商品をコンテキストに追加
    if (item.type === "rakuten_room_pick") {
      const progressPath = path.join(DATA_DIR, "rakuten-room-supabase-progress.json");
      try {
        const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
        const postedIds = new Set(progress.posted || []);
        // products.json から ROOM投稿済み商品を抽出
        const allProducts = products || [];
        context.roomProducts = allProducts
          .filter((p) => postedIds.has(p.id) && p.affiliateUrl?.includes("rakuten"))
          .map((p) => ({ id: p.id, name: p.name, price: p.price, productUrl: p.affiliateUrl }))
          .sort(() => Math.random() - 0.5)
          .slice(0, 10);
        if (context.roomProducts.length === 0) {
          console.log(`[rakuten_room_pick] ROOM投稿済み商品が見つかりません。一般的な内容で生成します`);
        } else {
          console.log(`[rakuten_room_pick] ROOM投稿済み商品 ${context.roomProducts.length}件をプロンプトに注入`);
        }
      } catch (err) {
        console.warn(`[rakuten_room_pick] 進捗ファイル読み込みエラー: ${err.message}`);
        context.roomProducts = [];
      }
    }

    // news_comment: ニュースフィードをコンテキストに追加
    if (item.type === "news_comment") {
      context.newsItems = loadNewsFeed(item.count);
      if (context.newsItems.length === 0) {
        console.log(`[news_comment] ニュースが無いためスキップ`);
        continue;
      }
      usedNewsItems.push(...context.newsItems);
    }

    console.log(`[${item.type}] ${item.count}件を生成中...${seed ? ` (seed: ${seed.id})` : ""}`);

    // プロンプト生成（フォーマットパターン + 書き出しローテーション + バズ1行目 + Analyst ディレクティブ）
    let prompt = getPromptForType(item.type, context);
    prompt += buildFormatPatternBlock();
    prompt += buildPatternRotationBlock();
    prompt += buildBuzzFirstLinesBlock(item.type);
    prompt += buildViralScoutBlock(item.axis);
    prompt += buildAnalystHintsBlock(item.type);
    prompt += buildHighPerformerBlock();
    if (opts.research) {
      prompt += buildResearchBlock(item.axis === "all" || item.axis === "rotate" ? "camp" : item.axis);
    }
    if (FOLLOWER_GROWTH_MODE) {
      prompt += `\n\n## 【最重要】フォロワー増加モード
- **本文にURLを絶対に含めない**（http:// https:// camp-gear-lab.com 等すべて禁止）
- サイトへの誘導・記事紹介・商品リンクは書かない
- 「〜はこちら」「詳しくはプロフィールのリンクから」も禁止
- 目的は共感・保存・フォロー。純粋な価値提供の投稿のみ生成すること`;
    }

    const isThread = item.type === "gear_thread";
    const approvalLevel = getApprovalLevel(item.type);
    const postAxis = seed?.axis || POST_TYPES[item.type].axis;

    // リトライループ（最大3回: 初回 + 2リトライ）
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      if (attempt > 0) {
        console.log(`[${item.type}] リトライ ${attempt}/2...`);
      }

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
        break;
      }

      const content = response.content[0].text;
      const jsonMatch = content.match(/\[[\s\S]*\]/);
      if (!jsonMatch) {
        console.error(`[${item.type}] JSON解析に失敗:\n${content.slice(0, 200)}`);
        break;
      }

      let generated;
      try {
        generated = JSON.parse(jsonMatch[0]);
      } catch (err) {
        console.error(`[${item.type}] JSONパースエラー: ${err.message}`);
        break;
      }

      // UTM パラメータ付与
      generated = generated.map((g) => addUtmIfNeeded(g, item.type));

      // ハッシュタグを safety net で削除（# は X アルゴリズム上不利）
      // Claude が指示を無視して入れた場合に備えて、本文と selfReply / tweets から strip する
      const stripHashtags = (s) =>
        typeof s === "string"
          ? s.replace(/(^|\s)#[^\s#]+/g, "$1").replace(/[ \t]+\n/g, "\n").trim()
          : s;
      generated = generated.map((g) => ({
        ...g,
        text: stripHashtags(g.text),
        selfReply: stripHashtags(g.selfReply),
        tweets: Array.isArray(g.tweets) ? g.tweets.map(stripHashtags) : g.tweets,
      }));

      // NG チェック
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

      // 類似チェック + 自己採点
      let needsRetry = false;
      const posts = [];

      for (const g of generated) {
        const postText = isThread && g.tweets ? formatThreadForSheets(g.tweets) : g.text;
        const plainText = isThread && g.tweets ? g.tweets.join(" ") : g.text;

        // NG語チェック失敗でもリトライ（薬機法・医療法系のブロックエラーを防ぐ）
        if (!g._checkOk && attempt < MAX_RETRIES) {
          console.log(`[${item.type}] NGチェック失敗 (${g.validationErrors}) → 再生成`);
          qualityRetries++;
          needsRetry = true;
          continue;
        }

        // 類似チェック
        const similarityScore = checkSimilarity(plainText);
        if (similarityScore > SIMILARITY_THRESHOLD && attempt < MAX_RETRIES) {
          console.log(`[${item.type}] 類似度 ${similarityScore.toFixed(2)} > ${SIMILARITY_THRESHOLD} → 再生成`);
          qualityRetries++;
          needsRetry = true;
          continue;
        }

        // 自己採点
        const scoreResult = await selfScorePost(client, {
          type: item.type,
          axis: postAxis,
          text: plainText,
        });

        // カテゴリ別最低点（persona=#5,軸=#9 / engagement=#1,#7,#8 / compliance=残り）
        const s = scoreResult.scores || [];
        const personaMin = s.length >= 9 ? Math.min(s[4], s[8]) : null;
        const engagementMin = s.length >= 8 ? Math.min(s[0], s[6], s[7]) : null;
        const PERSONA_MIN_THRESHOLD = 5;
        const ENGAGEMENT_MIN_THRESHOLD = 5;

        console.log(`[${item.type}] selfScore: ${scoreResult.total} (persona最低=${personaMin ?? "N/A"}, engagement最低=${engagementMin ?? "N/A"})`);
        if (scoreResult.comment) {
          console.log(`  └ 改善ポイント: ${scoreResult.comment}`);
        }

        const totalBelow = scoreResult.total < QUALITY_THRESHOLD;
        const personaBelow = personaMin !== null && personaMin < PERSONA_MIN_THRESHOLD;
        const engagementBelow = engagementMin !== null && engagementMin < ENGAGEMENT_MIN_THRESHOLD;

        if ((totalBelow || personaBelow || engagementBelow) && attempt < MAX_RETRIES) {
          const reasons = [];
          if (totalBelow) reasons.push(`total<${QUALITY_THRESHOLD}`);
          if (personaBelow) reasons.push(`persona<${PERSONA_MIN_THRESHOLD}`);
          if (engagementBelow) reasons.push(`engagement<${ENGAGEMENT_MIN_THRESHOLD}`);
          console.log(`[${item.type}] 品質不足 (${reasons.join(", ")}) → 再生成`);
          qualityRetries++;
          needsRetry = true;
          continue;
        }

        // 書き出しパターン分類
        const firstLinePattern = classifyFirstLinePattern(plainText, patternsData);

        // ステータス判定
        let status;
        if (scoreResult.total < QUALITY_THRESHOLD && attempt >= MAX_RETRIES) {
          status = "discarded";
        } else if (!g._checkOk) {
          status = "draft";
        } else if (opts.autoApprove || approvalLevel === "auto") {
          status = "approved";
        } else {
          status = "draft";
        }

        if (similarityScore > SIMILARITY_THRESHOLD) {
          g.validationErrors = [g.validationErrors, "類似投稿あり"].filter(Boolean).join(" / ");
          if (status !== "discarded") status = "draft";
        }

        // article_promo: 記事に紐づく製品の imageUrl を自動取得
        let postImageUrl = g.imageUrl || "";
        if (!postImageUrl && item.type === "article_promo" && g.articleSlug) {
          const article = articles.find((a) => a.slug === g.articleSlug);
          if (article) {
            const productIds = (article.products || article.productIds || []).slice(0, 3);
            for (const pid of productIds) {
              const prod = products.find((p) => p.id === pid);
              if (prod?.imageUrl) { postImageUrl = prod.imageUrl; break; }
            }
          }
        }
        // それ以外（doc_health_tip / ai_dev_log / outdoor_tip 等）は
        // Blob の 4コマ・キーイラストプールから抽選 → 無ければ Unsplash
        if (!postImageUrl) {
          postImageUrl = await pickAutoImage(item.type, blobImageUrls);
        }

        posts.push({
          id: generateId(),
          type: item.type,
          text: postText,
          articleSlug: g.articleSlug || "",
          url: g.url || "",
          imageUrl: postImageUrl,
          hashtags: "",
          status,
          scheduledDate: "",
          generatedAt: new Date().toISOString(),
          postedAt: "",
          axis: postAxis,
          seedId: seed?.id || "",
          validationErrors: g.validationErrors || "",
          autoApproved: status === "approved" ? "true" : "false",
          selfScore: scoreResult.total,
          firstLinePattern,
          similarityScore,
          retryCount: attempt,
          selfReply: g.selfReply || "",
          formatPattern: g.formatPattern || "",
        });
      }

      if (posts.length > 0) {
        allPosts.push(...posts);
        break; // 成功、リトライ不要
      }
      if (!needsRetry) break; // リトライ対象がない
    }

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
    const statusIcon = p.status === "approved" ? "v" : p.status === "discarded" ? "D" : "x";
    console.log(`[${statusIcon}] [${p.type}] (${p.axis}) status=${p.status}`);
    if (p.text.startsWith("[THREAD]")) {
      const tweets = JSON.parse(p.text.replace("[THREAD] ", ""));
      tweets.forEach((t, i) => console.log(`  ${i + 1}. ${t}`));
    } else {
      console.log(`  ${p.text}`);
    }
    if (p.seedId) console.log(`  seed: ${p.seedId}`);
    if (p.selfScore != null) console.log(`  score: ${p.selfScore} | 1L: ${p.firstLinePattern} | fmt: ${p.formatPattern || "-"} | sim: ${(p.similarityScore || 0).toFixed(2)} | retry: ${p.retryCount || 0}`);
    if (p.imageUrl) console.log(`  image: ${p.imageUrl.slice(0, 80)}`);
    if (p.validationErrors) console.log(`  NG: ${p.validationErrors}`);
    console.log("---");
  }

  // 保存
  if (opts.dryRun) {
    console.log("\n[DRY RUN] Sheets書き込み・seeds.json更新をスキップしました");
  } else {
    // Google Sheets 書き込み（A:R 18列）
    const sheets = await getSheets();
    const rows = allPosts.map((p) => [
      p.id,                                                // A
      p.type,                                              // B
      p.text,                                              // C
      p.articleSlug,                                       // D
      p.url,                                               // E
      p.hashtags,                                          // F
      p.status,                                            // G
      p.scheduledDate,                                     // H
      p.generatedAt,                                       // I
      p.postedAt,                                          // J
      p.axis,                                              // K
      p.seedId,                                            // L
      p.validationErrors,                                  // M
      p.autoApproved,                                      // N
      p.selfScore != null ? String(p.selfScore) : "",      // O
      p.firstLinePattern || "",                            // P
      p.similarityScore != null ? String(p.similarityScore) : "", // Q
      String(p.retryCount || 0),                           // R
      p.selfReply || "",                                   // S
      p.formatPattern || "",                               // T
      p.imageUrl || "",                                    // U
    ]);

    await sheets.spreadsheets.values.append({
      spreadsheetId: process.env.X_SHEET_ID,
      range: `${DRAFT_SHEET}!A:U`,
      valueInputOption: "RAW",
      // INSERT_ROWS: 必ず新規行として挿入（既存データの「table」検出に
      // 引きずられて変な列に書き込まれるのを防ぐ）
      insertDataOption: "INSERT_ROWS",
      requestBody: { values: rows },
    });

    // seeds.json 書き戻し
    saveSeeds(seedData);

    // post-history.json に追記
    for (const p of allPosts) {
      if (p.status !== "discarded") {
        appendToPostHistory({
          id: p.id,
          type: p.type,
          axis: p.axis,
          text: p.text,
          articleSlug: p.articleSlug || null,
          firstLinePattern: p.firstLinePattern || null,
          formatPattern: p.formatPattern || null,
          selfScore: p.selfScore != null ? p.selfScore : null,
          postedAt: null,
          seedId: p.seedId || null,
          engagements: null,
        });
      }
    }

    // news_comment: 使用済みニュースをマーク
    if (usedNewsItems.length > 0) markNewsUsed(usedNewsItems);

    console.log(`\nSheets に ${allPosts.length}件を保存しました`);
  }

  const blocked = allPosts.filter((p) => p.validationErrors).length;
  return {
    generated: allPosts.length,
    blocked,
    qualityRetries,
    posts: allPosts,
  };
}

// === 公開API ===
export { generatePosts, parseArgs };
