#!/usr/bin/env node

/**
 * YouTube Researcher Agent — YouTube動画からネタを自動収集
 *
 * テーマツリーのギャップ（used_count が低いノード）を検出し、
 * YouTube検索 → 文字起こし → Claude API でネタ抽出 → x-content-seeds.json に追加
 *
 * 必要な環境変数:
 *   YOUTUBE_API_KEY — YouTube Data API v3 キー
 *   ANTHROPIC_API_KEY — Claude API キー
 *
 * 使い方:
 *   node scripts/youtube-researcher.js                  # 全軸リサーチ
 *   node scripts/youtube-researcher.js --axis camp      # キャンプ軸のみ
 *   node scripts/youtube-researcher.js --dry-run        # seeds更新なし
 *   node scripts/youtube-researcher.js --max-keywords 5 # キーワード数制限
 */

import { google } from "googleapis";
import { YoutubeTranscript } from "youtube-transcript/dist/youtube-transcript.esm.js";
import Anthropic from "@anthropic-ai/sdk";
import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  ipv4Fetch,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, axis: null, maxKeywords: 8 };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run":
        opts.dryRun = true;
        break;
      case "--axis":
        opts.axis = args[++i];
        break;
      case "--max-keywords":
        opts.maxKeywords = parseInt(args[++i], 10) || 8;
        break;
    }
  }
  return opts;
}

// ─── ノード名 → 日本語マッピング ────────────────────

const NODE_NAME_JA = {
  // camp > gear
  tent: "テント", burner: "バーナー", sleeping_bag: "シュラフ",
  lantern: "ランタン", table_chair: "テーブル チェア", tarp: "タープ",
  cookware: "調理器具", peg: "ペグ", backpack: "バックパック", mat: "マット",
  // camp > technique
  setup: "設営", fire: "焚き火", cooking: "キャンプ飯",
  rain_camp: "雨キャンプ", winter_camp: "冬キャンプ", solo_camp: "ソロキャンプ",
  storage: "収納", maintenance: "メンテナンス",
  // camp > location
  nagano: "長野 キャンプ場", highland: "高原キャンプ", lakeside: "湖畔キャンプ",
  forest: "林間キャンプ", seaside: "海キャンプ",
  // camp > style
  family: "ファミリーキャンプ", solo: "ソロキャンプ", duo: "デュオキャンプ",
  group: "グループキャンプ", car_camp: "車中泊キャンプ", minimalist: "ミニマリスト キャンプ",
  // ai
  site_building: "Webサイト AI構築", automation: "AI 自動化",
  prompt_tips: "プロンプト コツ", debugging: "AI デバッグ",
  workflow: "AI ワークフロー", cursor: "Cursor AI エディタ",
  github_copilot: "GitHub Copilot", v0: "v0 AI", other_ai_tools: "AI ツール 比較",
  coding_journey: "プログラミング 独学 AI", non_engineer_perspective: "非エンジニア AI開発",
  productivity: "AI 生産性",
  // parenting
  kids_gear: "子供 キャンプ道具", kids_reaction: "子供 キャンプ 反応",
  kids_cooking: "子供 キャンプ飯", campfire_time: "焚き火 家族",
  school_event: "学校 アウトドア行事", weekend_outdoor: "週末 外遊び 子供",
  seasonal_activity: "季節 子供 遊び", first_experience: "初めて キャンプ 子供",
  independence: "子供 自立 アウトドア", nature_education: "自然教育 子供",
  // doctor
  heat_stroke: "熱中症 キャンプ 対策", insect_bite: "虫刺され アウトドア 対処",
  first_aid: "応急処置 キャンプ", hydration: "水分補給 アウトドア",
  hypothermia: "低体温症 冬キャンプ", sun_protection: "日焼け対策 アウトドア",
  allergy: "アレルギー 子供 アウトドア", skin_care: "スキンケア アウトドア",
  sleep_outdoor: "睡眠 キャンプ", nutrition: "栄養 アウトドア",
  exercise: "運動 アウトドア 効果", mental_health: "メンタルヘルス 自然",
  seasonal_illness: "季節の病気 予防",
};

/** ユーザー指定のブロード検索キーワード（軸ごと） */
const BROAD_KEYWORDS = {
  camp: [
    "売れてるキャンプ用品 2026",
    "買ってよかったキャンプ道具",
    "買って損したキャンプ用品",
    "100均キャンプグッズ",
    "キャンプ用品 徹底比較",
    "神キャンプ用品",
    "キャンプ あるある",
    "キャンプ 豆知識",
    "憧れのキャンプ用品",
  ],
  ai: [
    "Claude Code 使ってみた",
    "AI 個人開発 2026",
    "非エンジニア AI開発",
    "AI ツール おすすめ 2026",
  ],
  parenting: [
    "子連れキャンプ 失敗",
    "ファミリーキャンプ おすすめ",
    "子供とアウトドア 楽しむコツ",
    "子育て キャンプ",
  ],
  doctor: [
    "キャンプ 熱中症 対策",
    "アウトドア 怪我 対処法",
    "子供 虫刺され 対処",
    "キャンプ 健康管理",
  ],
};

// ─── テーマツリーギャップ検出 ────────────────────────

function findGaps(themeTree, targetAxis = null) {
  const gaps = [];

  function walk(node, path, axis) {
    if (node.children) {
      for (const [key, child] of Object.entries(node.children)) {
        walk(child, [...path, key], axis);
      }
    } else {
      gaps.push({
        path,
        axis,
        node: path[path.length - 1],
        used_count: node.used_count || 0,
        last_used: node.last_used || null,
      });
    }
  }

  for (const [axis, axisNode] of Object.entries(themeTree.axes)) {
    if (targetAxis && axis !== targetAxis) continue;
    walk(axisNode, [axis], axis);
  }

  // used_count 昇順 → last_used 古い順
  gaps.sort((a, b) => {
    if (a.used_count !== b.used_count) return a.used_count - b.used_count;
    if (!a.last_used) return -1;
    if (!b.last_used) return 1;
    return new Date(a.last_used) - new Date(b.last_used);
  });

  return gaps;
}

/**
 * ギャップに基づいて検索キーワードを生成。
 * ギャップの多いノード用キーワード + ブロードキーワードを混合。
 */
function generateKeywords(gaps, maxKeywords) {
  const keywords = [];
  const seenAxes = new Set();

  // ギャップ上位からノード固有のキーワードを追加
  for (const gap of gaps.slice(0, Math.ceil(maxKeywords * 0.6))) {
    const ja = NODE_NAME_JA[gap.node];
    if (!ja) continue;
    keywords.push({
      query: `${ja} おすすめ`,
      axis: gap.axis,
      targetNode: gap.node,
      source: "gap",
    });
    seenAxes.add(gap.axis);
  }

  // ブロードキーワードを追加（各軸から均等に）
  for (const [axis, kws] of Object.entries(BROAD_KEYWORDS)) {
    if (!seenAxes.has(axis) && gaps.some((g) => g.axis === axis)) {
      seenAxes.add(axis);
    }
    // シャッフルして上位を取る
    const shuffled = [...kws].sort(() => Math.random() - 0.5);
    for (const q of shuffled.slice(0, 2)) {
      keywords.push({ query: q, axis, targetNode: null, source: "broad" });
    }
  }

  return keywords.slice(0, maxKeywords);
}

// ─── YouTube 検索 ───────────────────────────────────

async function searchYouTube(apiKey, query, maxResults = 5) {
  const youtube = google.youtube({ version: "v3", auth: apiKey });

  // 直近3ヶ月の動画に限定（鮮度最重視）
  const threeMonthsAgo = new Date();
  threeMonthsAgo.setMonth(threeMonthsAgo.getMonth() - 3);

  // 関連度順 + 日付順の2パスで鮮度と質を両立
  const results = [];
  const seenIds = new Set();

  for (const order of ["relevance", "date"]) {
    const res = await youtube.search.list({
      q: query,
      part: "snippet",
      type: "video",
      maxResults: Math.ceil(maxResults / 2) + 1,
      order,
      publishedAfter: threeMonthsAgo.toISOString(),
      relevanceLanguage: "ja",
      regionCode: "JP",
      videoDuration: "medium", // 4〜20分の動画に絞る（短すぎ・長すぎ除外）
    });

    for (const item of res.data.items || []) {
      if (seenIds.has(item.id.videoId)) continue;
      seenIds.add(item.id.videoId);
      results.push({
        videoId: item.id.videoId,
        title: item.snippet.title,
        channelTitle: item.snippet.channelTitle,
        publishedAt: item.snippet.publishedAt,
      });
    }
  }

  return results.slice(0, maxResults);
}

// ─── 文字起こし取得 ─────────────────────────────────

async function getTranscript(videoId, maxChars = 4000) {
  try {
    const segments = await YoutubeTranscript.fetchTranscript(videoId, {
      lang: "ja",
    });
    const fullText = segments.map((s) => s.text).join(" ");
    // 長すぎる場合は先頭部分のみ
    return fullText.slice(0, maxChars);
  } catch {
    // 字幕なし / エラー → null
    return null;
  }
}

// ─── Claude API でネタ抽出 ──────────────────────────

async function extractTopics(client, { keyword, axis, videos, transcripts, gapNodes }) {
  const videoSummaries = videos
    .map((v, i) => {
      const t = transcripts[i];
      if (!t) return null;
      return `### ${v.title}（${v.channelTitle}）\n${t}`;
    })
    .filter(Boolean)
    .join("\n\n---\n\n");

  if (!videoSummaries) return [];

  const month = new Date().getMonth() + 1;
  const gapList = gapNodes.length > 0
    ? gapNodes.map((n) => `${n} (${NODE_NAME_JA[n] || n})`).join(", ")
    : "制限なし";

  const prompt = `あなたはX投稿のネタリサーチャーです。以下のYouTube動画の文字起こしを読み、
「保存したくなる」X投稿のネタを抽出してください。

## 検索キーワード: ${keyword}
## 軸: ${axis}
## 現在: ${month}月
## テーマツリーで不足しているノード: ${gapList}

## 動画の文字起こし
${videoSummaries}

## 抽出基準（重要）
- 具体的な数字やスペック名がある話題（「○○は○gで○円」等）
- 「あるある」感のある失敗談や体験談
- A vs B の比較情報
- チェックリスト・手順系（保存される）
- 意外な事実・豆知識（ブクマされる）
- 今の季節（${month}月）に合う話題を優先

## 除外（重要）
- 単なる製品紹介（具体的な切り口がないもの）
- 特定YouTuberの個人ネタ・内輪ネタ（「○○さんの」「○○チャンネルの」）
- 動画の宣伝文句そのまま
- 一般常識レベルの内容（「水分補給しましょう」レベルは不要）
- 医学的根拠が怪しい民間療法・サプリ推し（doctor軸は特に厳格に）
- 再現性が低い個人の趣味（ピンク統一キャンプ等）

## 出力形式（JSONのみ、他のテキスト不要）
[
  {
    "theme": "テーマ名（テント、バーナー、焚き火等）",
    "angle": "角度（比較、失敗談、コスパ、豆知識、あるある等）",
    "hint": "X投稿にする際のネタ・切り口（100文字以内。具体的に）",
    "treeNode": "theme-treeのリーフノード名（tent, burner, fire等。不明なら null）",
    "types": ["outdoor_tip", "gear_thread"],
    "bookmarkPotential": "high/medium/low"
  }
]

最大5件。使えるネタがなければ空配列 [] を返してください。`;

  try {
    const response = await client.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 2000,
      messages: [{ role: "user", content: prompt }],
    });

    const text = response.content[0].text;
    const jsonMatch = text.match(/\[[\s\S]*\]/);
    if (!jsonMatch) return [];
    return JSON.parse(jsonMatch[0]);
  } catch (err) {
    console.warn(`[yt-researcher] Claude抽出失敗: ${err.message}`);
    return [];
  }
}

// ─── シード生成 ─────────────────────────────────────

function createSeed(topic, axis, videoIds) {
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const rand = Math.random().toString(36).slice(2, 6);
  const month = new Date().getMonth() + 1;

  // 季節の推定（現在月 ± 2ヶ月）
  const seasonRange = [];
  for (let m = month - 2; m <= month + 2; m++) {
    const normalized = ((m - 1 + 12) % 12) + 1;
    seasonRange.push(normalized);
  }

  return {
    id: `yt-${date}-${rand}`,
    axis,
    theme: topic.theme || "その他",
    angle: topic.angle || "豆知識",
    types: topic.types || ["outdoor_tip"],
    season: seasonRange,
    used_count: 0,
    last_used: null,
    hint: topic.hint,
    source: "youtube",
    sourceVideoIds: videoIds,
    fetchedAt: new Date().toISOString().slice(0, 10),
    freshUntil: new Date(Date.now() + 90 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10), // 90日間は鮮度あり
    bookmarkPotential: topic.bookmarkPotential || "medium",
  };
}

// ─── 重複チェック ───────────────────────────────────

function isDuplicate(newHint, existingSeeds) {
  const newLower = newHint.toLowerCase();
  for (const s of existingSeeds) {
    if (!s.hint) continue;
    const existing = s.hint.toLowerCase();
    // 完全一致 or 70%以上の文字重複
    if (existing === newLower) return true;
    // 簡易的な部分一致チェック
    const shorter = newLower.length < existing.length ? newLower : existing;
    const longer = newLower.length < existing.length ? existing : newLower;
    if (longer.includes(shorter)) return true;
  }
  return false;
}

// ─── テーマツリー更新 ───────────────────────────────

function updateThemeTreeForTopics(themeTree, topics) {
  const today = new Date().toISOString().slice(0, 10);

  for (const topic of topics) {
    if (!topic.treeNode) continue;

    // 全軸のリーフを走査して一致するノードを更新
    for (const [, axisNode] of Object.entries(themeTree.axes)) {
      const updated = updateNodeRecursive(axisNode, topic.treeNode, today);
      if (updated) break;
    }
  }
}

function updateNodeRecursive(node, targetName, today) {
  if (!node.children) return false;
  for (const [key, child] of Object.entries(node.children)) {
    if (key === targetName && !child.children) {
      // リーフノード発見
      child.used_count = (child.used_count || 0) + 1;
      child.last_used = today;
      return true;
    }
    if (child.children && updateNodeRecursive(child, targetName, today)) {
      return true;
    }
  }
  return false;
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  // Kill switch
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[yt-researcher] KILL SWITCH: ${ks.reason}`);
    process.exit(1);
  }

  // API キー確認
  const youtubeApiKey = process.env.YOUTUBE_API_KEY;
  if (!youtubeApiKey) {
    console.error("[yt-researcher] YOUTUBE_API_KEY が設定されていません");
    console.error("  → Google Cloud Console で YouTube Data API v3 のキーを取得してください");
    process.exit(1);
  }
  const anthropicKey = process.env.ANTHROPIC_API_KEY;
  if (!anthropicKey) {
    console.error("[yt-researcher] ANTHROPIC_API_KEY が設定されていません");
    process.exit(1);
  }

  const client = new Anthropic({ apiKey: anthropicKey, fetch: ipv4Fetch, maxRetries: 3 });

  // データ読み込み
  const themeTree = readJson("theme-tree.json");
  if (!themeTree) {
    console.error("[yt-researcher] theme-tree.json が見つかりません");
    process.exit(1);
  }

  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  const existingSeeds = seedData.seeds || [];

  // ギャップ検出
  const gaps = findGaps(themeTree, opts.axis);
  console.log(`[yt-researcher] テーマツリーギャップ: ${gaps.length}ノード`);
  for (const g of gaps.slice(0, 5)) {
    console.log(`  ${g.axis}/${g.path.join("/")} — used: ${g.used_count}`);
  }

  // キーワード生成
  const keywords = generateKeywords(gaps, opts.maxKeywords);
  console.log(`\n[yt-researcher] 検索キーワード: ${keywords.length}件`);
  for (const kw of keywords) {
    console.log(`  [${kw.source}] ${kw.axis}: "${kw.query}" ${kw.targetNode ? `→ ${kw.targetNode}` : ""}`);
  }

  // YouTube検索 → 文字起こし → ネタ抽出
  const allNewSeeds = [];
  const allTopics = [];

  for (const kw of keywords) {
    console.log(`\n${"─".repeat(50)}`);
    console.log(`[yt-researcher] 検索: "${kw.query}"`);

    // YouTube検索
    let videos;
    try {
      videos = await searchYouTube(youtubeApiKey, kw.query, 5);
    } catch (err) {
      console.warn(`  YouTube検索失敗: ${err.message}`);
      continue;
    }

    if (videos.length === 0) {
      console.log("  → 動画なし");
      continue;
    }
    console.log(`  → ${videos.length}件の動画`);

    // 文字起こし取得（上位3件）
    const targetVideos = videos.slice(0, 3);
    const transcripts = [];
    for (const v of targetVideos) {
      console.log(`  📹 ${v.title.slice(0, 50)}`);
      const transcript = await getTranscript(v.videoId);
      transcripts.push(transcript);
      if (transcript) {
        console.log(`    → 字幕取得: ${transcript.length}文字`);
      } else {
        console.log(`    → 字幕なし（スキップ）`);
      }
    }

    if (transcripts.every((t) => !t)) {
      console.log("  → 全動画の字幕取得に失敗");
      continue;
    }

    // ギャップノードを収集（このキーワードに関連するノード）
    const gapNodes = kw.targetNode
      ? [kw.targetNode]
      : gaps.filter((g) => g.axis === kw.axis).slice(0, 5).map((g) => g.node);

    // Claude でネタ抽出
    console.log("  🤖 Claude でネタ抽出中...");
    const topics = await extractTopics(client, {
      keyword: kw.query,
      axis: kw.axis,
      videos: targetVideos,
      transcripts,
      gapNodes,
    });

    console.log(`  → ${topics.length}件のネタ抽出`);
    for (const t of topics) {
      console.log(`    [${t.bookmarkPotential}] ${t.theme}/${t.angle}: ${t.hint?.slice(0, 60)}`);
    }

    // 重複チェック → シード生成
    const videoIds = targetVideos.map((v) => v.videoId);
    for (const topic of topics) {
      if (!topic.hint) continue;
      if (isDuplicate(topic.hint, existingSeeds)) {
        console.log(`    → 重複スキップ: ${topic.hint.slice(0, 40)}`);
        continue;
      }
      const seed = createSeed(topic, kw.axis, videoIds);
      allNewSeeds.push(seed);
      allTopics.push(topic);
    }
  }

  // 結果サマリ
  console.log(`\n${"═".repeat(50)}`);
  console.log(`[yt-researcher] 結果: ${allNewSeeds.length}件の新規シード`);
  for (const s of allNewSeeds) {
    console.log(`  [${s.axis}] ${s.theme}/${s.angle} — ${s.hint.slice(0, 60)} (🔖${s.bookmarkPotential})`);
  }

  // 保存
  if (opts.dryRun) {
    console.log("\n[DRY RUN] seeds・theme-tree の更新をスキップしました");
  } else if (allNewSeeds.length > 0) {
    // x-content-seeds.json に追加
    seedData.seeds.push(...allNewSeeds);
    writeJson("x-content-seeds.json", seedData);
    console.log(`\n[yt-researcher] x-content-seeds.json に ${allNewSeeds.length}件追加`);

    // theme-tree 更新
    updateThemeTreeForTopics(themeTree, allTopics);
    writeJson("theme-tree.json", themeTree);
    console.log("[yt-researcher] theme-tree.json を更新しました");
  } else {
    console.log("\n[yt-researcher] 追加するシードがありません");
  }
}

main().catch((err) => {
  console.error("[yt-researcher] エラー:", err.message);
  process.exit(1);
});
