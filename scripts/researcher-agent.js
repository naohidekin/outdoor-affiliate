#!/usr/bin/env node

/**
 * Researcher Agent — ネタシード選定・テーマツリー管理・週次生成プラン作成
 *
 * Orchestrator の週次パイプラインから呼ばれ、今週の生成プランを JSON で stdout に出力する。
 * テーマツリーの「ギャップ検出」により、未使用・低使用テーマを優先的に選ぶ。
 *
 * 使い方:
 *   node scripts/researcher-agent.js                    # 週次プラン生成（stdout JSON）
 *   node scripts/researcher-agent.js --dry-run          # theme-tree 更新なし
 *   node scripts/researcher-agent.js --week 2026-W16    # 週ラベル上書き
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  loadPostHistory,
} from "../src/lib/x-agent-utils.mjs";
import {
  POST_TYPES,
  SEASON_CONTEXT,
} from "../src/lib/x-post-prompts.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, week: null };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run":
        opts.dryRun = true;
        break;
      case "--week":
        opts.week = args[++i];
        break;
    }
  }
  return opts;
}

// ─── テーマツリーのリーフ used_count を集約して低使用テーマを特定 ───

/**
 * テーマツリーからリーフノードを列挙。
 * @returns {Array<{ path: string[], axis: string, used_count: number, last_used: string|null }>}
 */
function getLeafNodes(themeTree) {
  const leaves = [];

  function walk(node, pathSoFar, axis) {
    if (node.children) {
      for (const [key, child] of Object.entries(node.children)) {
        walk(child, [...pathSoFar, key], axis);
      }
    } else {
      // リーフノード
      leaves.push({
        path: pathSoFar,
        axis,
        used_count: node.used_count || 0,
        last_used: node.last_used || null,
      });
    }
  }

  for (const [axis, axisNode] of Object.entries(themeTree.axes)) {
    walk(axisNode, [axis], axis);
  }

  return leaves;
}

/**
 * 指定 axis のリーフで used_count が最も低いテーマを返す。
 * 直近3回同じ親テーマ内で使われたものは除外。
 */
function getLowUsageThemes(themeTree, axis, recentThemes = []) {
  const leaves = getLeafNodes(themeTree).filter((l) => l.axis === axis);
  if (leaves.length === 0) return null;

  // 直近3回の親テーマを取得（path[1] が親テーマ）
  const recentParents = recentThemes.slice(-3).map((t) => t.split("/")[0]);

  // 同じ親テーマが3連続のものを除外
  const filtered = leaves.filter((l) => {
    const parent = l.path[1]; // axis の直下
    const consecutiveCount = recentParents.filter((p) => p === parent).length;
    return consecutiveCount < 3;
  });

  const candidates = filtered.length > 0 ? filtered : leaves;
  candidates.sort((a, b) => {
    if (a.used_count !== b.used_count) return a.used_count - b.used_count;
    if (!a.last_used) return -1;
    if (!b.last_used) return 1;
    return new Date(a.last_used) - new Date(b.last_used);
  });

  return candidates[0];
}

// ─── シード選択（テーマツリーギャップ考慮版）───────────

function selectSeedForType(type, { seeds, themeTree, month, postHistory }) {
  const meta = POST_TYPES[type];
  if (!meta) return null;

  const axis = meta.axis;

  // 季節・タイプ・軸でフィルタ
  const candidates = seeds.filter((s) => {
    if (!s.types.includes(type)) return false;
    if (s.season && s.season.length > 0 && !s.season.includes(month)) return false;
    if (axis && axis !== "all" && axis !== "rotate" && s.axis !== axis) return false;
    return true;
  });

  if (candidates.length === 0) return null;

  // テーマツリーのギャップ情報でスコアリング
  const lowUsageTheme = themeTree
    ? getLowUsageThemes(themeTree, axis === "rotate" ? "camp" : axis)
    : null;
  const preferredTheme = lowUsageTheme ? lowUsageTheme.path[lowUsageTheme.path.length - 1] : null;

  const today = new Date().toISOString().slice(0, 10);

  candidates.sort((a, b) => {
    // 鮮度の高いYouTubeシードを優先（freshUntil が有効期間内）
    const aFresh = a.source === "youtube" && a.freshUntil && a.freshUntil >= today ? -1 : 0;
    const bFresh = b.source === "youtube" && b.freshUntil && b.freshUntil >= today ? -1 : 0;
    if (aFresh !== bFresh) return aFresh - bFresh;

    // ブクマポテンシャルが高いシードを優先
    const potentialOrder = { high: 0, medium: 1, low: 2 };
    const aPot = potentialOrder[a.bookmarkPotential] ?? 1;
    const bPot = potentialOrder[b.bookmarkPotential] ?? 1;
    if (aPot !== bPot) return aPot - bPot;

    // テーマツリーギャップに合致するシードを優先
    const aMatchesGap = preferredTheme && a.theme && a.theme.toLowerCase().includes(preferredTheme) ? -1 : 0;
    const bMatchesGap = preferredTheme && b.theme && b.theme.toLowerCase().includes(preferredTheme) ? -1 : 0;
    if (aMatchesGap !== bMatchesGap) return aMatchesGap - bMatchesGap;

    // used_count 少ない順
    if (a.used_count !== b.used_count) return a.used_count - b.used_count;

    // last_used 古い順
    if (!a.last_used) return -1;
    if (!b.last_used) return 1;
    return new Date(a.last_used) - new Date(b.last_used);
  });

  return candidates[0];
}

// ��── 記事候補選定 ────────────────────────────────────

function selectArticles(articles, existingHistory, maxCount = 6) {
  // post-history の article_promo 投稿から記事 slug を推定
  // articleSlug フィールドがあればそれを使い、なければ text 内の URL からslugを抽出
  const recentSlugs = new Set();
  for (const e of existingHistory) {
    if (e.type !== "article_promo") continue;
    if (e.articleSlug) {
      recentSlugs.add(e.articleSlug);
    } else if (e.text) {
      const urlMatch = e.text.match(/camp-gear-lab\.com\/articles\/([^\s?/]+)/);
      if (urlMatch) recentSlugs.add(urlMatch[1]);
    }
  }

  const candidates = articles.filter((a) => !recentSlugs.has(a.slug));
  const pool = candidates.length >= maxCount ? candidates : articles;
  return pool.sort(() => Math.random() - 0.5).slice(0, maxCount);
}

// ─── 週ラベル生成 ────────────────────────────────────

function getWeekLabel(date = new Date()) {
  const year = date.getFullYear();
  // ISO week number
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
  return `${year}-W${String(weekNo).padStart(2, "0")}`;
}

// ─── テーマツリー更新 ─────────────────────────────────

function updateThemeTree(themeTree, usedSeeds) {
  const today = new Date().toISOString().split("T")[0];
  const leaves = getLeafNodes(themeTree);

  for (const seed of usedSeeds) {
    if (!seed || !seed.theme) continue;
    const themeKey = seed.theme.toLowerCase();

    // リーフノードとテーマ名の部分一致で更新
    for (const leaf of leaves) {
      const leafKey = leaf.path[leaf.path.length - 1];
      if (themeKey.includes(leafKey) || leafKey.includes(themeKey)) {
        // 実ノードを辿って更新
        let node = themeTree.axes[leaf.axis];
        for (let i = 1; i < leaf.path.length; i++) {
          node = node.children[leaf.path[i]];
        }
        node.used_count = (node.used_count || 0) + 1;
        node.last_used = today;
        break;
      }
    }
  }
}

// ─── エンゲージメント分析でテーマ優先度を判定 ──────────

function loadEngagementInsights() {
  const feedback = readJson("analyst-feedback.json");
  const engagement = readJson("x-engagement.json");
  const insights = {
    highEngagementTypes: [],   // ブクマ・いいねが多いタイプ
    lowEngagementTypes: [],    // 反応が薄いタイプ
    replyTopics: [],           // 読者が質問/反応したトピック
    topPostHints: [],          // トップ投稿のヒント
  };

  // analyst-feedback からタイプ別エンゲージメント
  if (feedback?.engagementByType) {
    for (const [type, stats] of Object.entries(feedback.engagementByType)) {
      const avgScore = stats.count > 0 ? (stats.bookmarks + stats.likes) / stats.count : 0;
      if (avgScore >= 3) {
        insights.highEngagementTypes.push(type);
      } else if (stats.count >= 3 && avgScore < 1) {
        insights.lowEngagementTypes.push(type);
      }
    }
  }

  // x-engagement からリプライテーマ
  if (engagement?.replyDigest) {
    insights.replyTopics = engagement.replyDigest
      .slice(0, 5)
      .map((r) => r.text?.slice(0, 50))
      .filter(Boolean);
  }

  // トップ投稿のヒント
  if (feedback?.topEngagementPosts) {
    insights.topPostHints = feedback.topEngagementPosts
      .slice(0, 3)
      .map((p) => `[${p.postType}] ${p.textPreview}`);
  }

  return insights;
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  // Kill switch チェック
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[researcher] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  // データ読み込み
  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  const themeTree = readJson("theme-tree.json");
  const articlesRaw = readJson("articles.json") || [];
  const articles = articlesRaw.filter((a) => a.status === "published");
  const history = loadPostHistory();
  const month = new Date().getMonth() + 1;

  // エンゲージメントインサイト読み込み
  const engInsights = loadEngagementInsights();
  if (engInsights.highEngagementTypes.length > 0) {
    console.error(`[researcher] 高エンゲージメントタイプ: ${engInsights.highEngagementTypes.join(", ")}`);
  }

  // 週次プラン構築
  const plan = [];
  const usedSeeds = [];

  for (const [type, meta] of Object.entries(POST_TYPES)) {
    let count = Math.ceil(meta.weeklyCount);

    // エンゲージメントが高いタイプは件数を増やす（最大+1）
    if (engInsights.highEngagementTypes.includes(type) && count < 3) {
      count++;
      console.error(`[researcher] ${type} は高エンゲージメント → ${count}件に増加`);
    }

    const seed = selectSeedForType(type, {
      seeds: seedData.seeds,
      themeTree,
      month,
      postHistory: history.entries,
    });

    // エンゲージメントヒント生成
    let engagementHint = null;
    if (engInsights.highEngagementTypes.includes(type)) {
      engagementHint = "高エンゲージメント: ブクマ・いいねが多い。同じ切り口を維持。";
    } else if (engInsights.lowEngagementTypes.includes(type)) {
      engagementHint = "低エンゲージメント: 切り口を変えてみる。読者の反応を見て調整。";
    }

    plan.push({
      type,
      count,
      axis: meta.axis,
      seedId: seed ? seed.id : null,
      engagementHint,
    });

    if (seed) usedSeeds.push(seed);
  }

  // 記事候補選定
  const selectedArticles = selectArticles(articles, history.entries);

  // 週次プラン出力
  const weekLabel = opts.week || getWeekLabel();
  const output = {
    week: weekLabel,
    month,
    seasonContext: SEASON_CONTEXT[month] || "",
    plan,
    selectedArticles: selectedArticles.map((a) => a.slug),
    engagementInsights: {
      replyTopics: engInsights.replyTopics,
      topPostHints: engInsights.topPostHints,
    },
  };

  // stdout に JSON 出力（Orchestrator が受け取る）
  console.log(JSON.stringify(output, null, 2));

  // テーマツリー更新
  if (!opts.dryRun && themeTree) {
    updateThemeTree(themeTree, usedSeeds);
    writeJson("theme-tree.json", themeTree);
    console.error("[researcher] theme-tree.json を更新しました");
  }

  // シード使用記録
  if (!opts.dryRun) {
    const today = new Date().toISOString().slice(0, 10);
    for (const seed of usedSeeds) {
      const s = seedData.seeds.find((x) => x.id === seed.id);
      if (s) {
        s.used_count++;
        s.last_used = today;
      }
    }
    writeJson("x-content-seeds.json", seedData);
    console.error("[researcher] x-content-seeds.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[researcher] エラー:", err.message);
  process.exit(1);
});
