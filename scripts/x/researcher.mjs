#!/usr/bin/env node
// scripts/x/researcher.mjs
// ネタ収集段。amble の researcher を踏襲しつつ、ギア男ドメインに合わせて:
//   ① 開放検索をやめ、軸ごとの手キュレーション QUERY_POOLS を使う
//   ② PR・キャンペーン・アフィリエイト源を弾く isPromoJunk フィルタ（← ユーザー診断の是正点）
//   ③ 4軸配分（camp0.7 / doctor0.2 / parenting0.1）を account-config から取り、
//      直近で 40% を超えた軸を自動抑制（軸バランスの自動調整）
//   ④ SimHash/文字重複で既出ネタを除外
// 生成したネタは data/x/ideas.jsonl に status:"active" で積む。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import {
  readJsonl,
  appendJsonl,
  generateId,
  jstNow,
  IDEA_BANK_PATH,
  isResearchKilled,
} from "./lib/file-lock.mjs";
import { callClaude, hasClaudeKey } from "./lib/claude-api.mjs";

const ROOT = resolve(import.meta.dirname, "../..");
const CONFIG = JSON.parse(readFileSync(resolve(ROOT, "data/account-config.json"), "utf8"));
const NEWS_FEED_PATH = resolve(ROOT, "data/news-feed.json");
const BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search";

// ─── 軸配分（account-config.axes の ratio を踏襲） ──────────────────────
const AXIS_RATIO = Object.fromEntries(CONFIG.axes.map((a) => [a.id, a.ratio]));
// 既定: { camp:0.7, doctor:0.2, parenting:0.1 }

// ─── 手キュレーション検索プール（開放検索しない = PR拾いを構造的に防ぐ） ──
const QUERY_POOLS = {
  camp: [
    "キャンプ ギア 比較 レビュー 実際",
    "テント 設営 失敗 コツ ファミリー",
    "焚き火台 使い分け ソロ ファミリー",
    "シュラフ 選び方 冬 快適温度 失敗",
    "クーラーボックス 保冷力 検証 比較",
    "ランタン 明るさ ルーメン 実用 比較",
    "キャンプ 初心者 買って後悔したギア",
    "アメニティドーム 10年 使用感 スノーピーク",
    "キャンプ 雨 対策 タープ 連結",
    "バーナー OD缶 CB缶 使い分け 実際",
    "キャンプ 収納 積載 車 コンテナ",
    "ふるさと納税 キャンプ ギア 返礼品",
  ],
  doctor: [
    "子供 キャンプ 熱中症 予防 水分",
    "キャンプ 虫刺され 対策 子供 安全",
    "テント内 一酸化炭素 暖房 危険",
    "アウトドア 応急処置 やけど 切り傷",
    "子供 発熱 アウトドア 受診 判断",
    "紫外線 対策 子供 屋外 日焼け",
    "食中毒 キャンプ 夏 予防 保冷",
    "睡眠 質 アウトドア 自律神経",
  ],
  parenting: [
    "子供 キャンプ 初体験 焚き火 反応",
    "家族キャンプ 子連れ 準備 大変",
    "子供 自然体験 成長 アウトドア",
    "パパ キャンプ 育児 分担 リアル",
  ],
};

// news-feed のカテゴリ→軸マップ（news_comment 用）
const NEWS_AXIS = "camp";

// ─── PR/キャンペーン/アフィリエイト源フィルタ（← 是正の核心） ──────────
const PROMO_HOST_PATTERNS = [
  /rakuten\.co\.jp/i,
  /amazon\.co\.jp/i,
  /amzn\.to/i,
  /a8\.net/i,
  /valuecommerce/i,
  /afl\.rakuten/i,
  /shopping\.yahoo/i,
  /store\.shopping/i,
  /px\.a8\.net/i,
  /moshimo/i,
  /felmat/i,
  /accesstrade/i,
];
const PROMO_TEXT_PATTERNS = [
  /PR\b/,
  /ＰＲ/,
  /プロモーション/,
  /タイアップ/,
  /提供[:：]/,
  /キャンペーン/,
  /クーポン/,
  /セール開催/,
  /最大\d+%OFF/i,
  /ポイント\d+倍/,
  /抽選で/,
  /プレゼント企画/,
  /アフィリエイト/,
  /\[?広告\]?/,
];

export function isPromoJunk(item) {
  const url = item.url || "";
  const text = `${item.title || ""} ${item.description || ""}`;
  if (PROMO_HOST_PATTERNS.some((re) => re.test(url))) return true;
  if (PROMO_TEXT_PATTERNS.some((re) => re.test(text))) return true;
  return false;
}

// ─── 軸バランス: 直近ネタで 40% を超える軸を抑制 ──────────────────────
function getOverRepresentedAxes(ideas, recentN = 20) {
  const recent = ideas.slice(-recentN);
  if (recent.length === 0) return [];
  const counts = {};
  for (const idea of recent) counts[idea.axis] = (counts[idea.axis] || 0) + 1;
  return Object.entries(counts)
    .filter(([, c]) => c / recent.length > 0.4)
    .map(([axis]) => axis);
}

// 目標比率から、over-represented を抑制した実効比率で軸を選ぶ
function selectAxes(count, overRepresented) {
  const adjusted = { ...AXIS_RATIO };
  for (const axis of overRepresented) if (adjusted[axis]) adjusted[axis] *= 0.3;
  const total = Object.values(adjusted).reduce((s, w) => s + w, 0) || 1;
  const norm = Object.fromEntries(Object.entries(adjusted).map(([k, w]) => [k, w / total]));
  const axes = [];
  for (let i = 0; i < count; i++) {
    // index ベースの決定的抽選（Math.random は使うが順序の再現性は不要）
    const r = Math.random();
    let cum = 0;
    for (const [axis, w] of Object.entries(norm)) {
      cum += w;
      if (r <= cum) {
        axes.push(axis);
        break;
      }
    }
  }
  return axes;
}

// ─── ソース検索 ──────────────────────────────────────────────────────
async function braveSearch(query) {
  const apiKey = process.env.BRAVE_API_KEY;
  if (!apiKey) {
    console.warn("[researcher] BRAVE_API_KEY 未設定、Brave検索スキップ");
    return [];
  }
  const url = `${BRAVE_API_URL}?q=${encodeURIComponent(query)}&count=5&search_lang=jp`;
  const res = await fetch(url, {
    headers: { Accept: "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": apiKey },
  });
  if (!res.ok) throw new Error(`Brave error ${res.status}`);
  const data = await res.json();
  return (data.web?.results || []).map((r) => ({ title: r.title, url: r.url, description: r.description }));
}

function loadNewsFeed() {
  if (!existsSync(NEWS_FEED_PATH)) return [];
  try {
    const items = JSON.parse(readFileSync(NEWS_FEED_PATH, "utf8"));
    return items
      .filter((it) => !it.used && !it.sensitive)
      .slice(0, 8)
      .map((it) => ({ title: it.title, url: it.url, description: it.summary || it.title, newsId: it.id }));
  } catch {
    return [];
  }
}

// ─── Claude でネタ化 ─────────────────────────────────────────────────
async function generateIdeas(searchResults, axis, existingIdeas) {
  const existingTopics = existingIdeas.slice(-30).map((i) => i.topic).join("、");
  const dedupeNote = existingTopics ? `\n\n既出（避ける）:\n${existingTopics}` : "";
  const axisGuide = {
    camp: "キャンプ・ギアの実体験ベースのネタ。比較・失敗・発見。ギア男（東京在住40歳・キャンプ歴10年・アメドL使い）の視点。",
    doctor: "医師（開業医・内科ホームドクター）目線の健康・安全のネタ。薬機法ガード必須。専門科・症例・薬剤名・機器名は出さない。効能断定NG。",
    parenting: "子育て×アウトドアのほっこり/自虐ネタ。子供の学年・学校名・個人名は出さない（「小学生の息子」までの粒度）。",
  };
  const prompt = `以下の検索結果から、X（Twitter）投稿のネタを2-3個生成してください。

軸: ${axis}
方向性: ${axisGuide[axis] || ""}

投稿者ペルソナ: ギア男（東京在住40歳、開業医・内科ホームドクター、キャンプ歴10年、2児の父、アメニティドームL＋メッシュタープ使い、一人称「僕」、ですます調）

ネタ化ルール:
- 商品PR・キャンペーン・セール情報はネタにしない（体験・気づき・比較の視点に変換する）
- 拾った素材の丸写しではなく、ギア男の視点での「切り口」を作る
- 車種・専門科・医薬品名・医療機器名・東京より細かい地名・未所有ギアの所有主張はネタに含めない

検索結果:
${searchResults.map((r) => `- ${r.title}: ${r.description}`).join("\n")}
${dedupeNote}

出力（JSON配列のみ、説明不要）:
[{ "topic": "ネタ要約(20-40字)", "angle": "切り口(どの視点で書くか)", "sourceUrls": ["参考URL"], "suggestedType": "outdoor_tip | failure_story | poll_question | doc_health_tip | parenting_outdoor | news_comment | null" }]`;

  const response = await callClaude({
    system: "あなたはX投稿企画のアシスタントです。JSONのみ出力してください。",
    messages: [{ role: "user", content: prompt }],
    model: "claude-sonnet-4-20250514",
    maxTokens: 640,
    temperature: 0.8,
  });
  const m = response.match(/\[[\s\S]*\]/);
  if (!m) return [];
  try {
    return JSON.parse(m[0]);
  } catch {
    return [];
  }
}

// 既出ネタとの重複（文字 60% 一致）
function isDuplicateTopic(topic, existingIdeas) {
  if (!topic) return false;
  return existingIdeas.some((e) => {
    if (!e.topic) return false;
    if (e.topic === topic) return true;
    const overlap = [...topic].filter((c) => e.topic.includes(c)).length;
    return overlap / topic.length > 0.6 && overlap / e.topic.length > 0.6;
  });
}

export async function runResearcher({ count = 10, dryRun = false } = {}) {
  if (isResearchKilled()) {
    console.log("[researcher] research kill-switch ON。スキップ。");
    return 0;
  }
  if (!hasClaudeKey()) {
    console.warn("[researcher] ANTHROPIC_API_KEY 未設定。ネタ化スキップ。");
    return 0;
  }

  const existingIdeas = readJsonl(IDEA_BANK_PATH);
  const over = getOverRepresentedAxes(existingIdeas);
  if (over.length) console.log(`[researcher] 過剰軸(>40%)を抑制: ${over.join(", ")}`);

  const axes = selectAxes(count, over);
  const axisCounts = {};
  for (const a of axes) axisCounts[a] = (axisCounts[a] || 0) + 1;

  // 軸ごとに検索タスクを組む
  const tasks = [];
  for (const [axis, n] of Object.entries(axisCounts)) {
    const pool = [...(QUERY_POOLS[axis] || [])].sort(() => Math.random() - 0.5);
    for (const q of pool.slice(0, Math.max(1, n))) tasks.push({ axis, query: q });
    // camp 軸は news も 1 枠（非センシティブ・未使用のみ）
    if (axis === "camp") tasks.push({ axis: NEWS_AXIS, query: null, source: "news" });
  }

  const settled = await Promise.allSettled(
    tasks.map(async (t) => {
      const raw = t.source === "news" ? loadNewsFeed() : await braveSearch(t.query);
      const clean = raw.filter((item) => !isPromoJunk(item)); // ← PR除外
      const dropped = raw.length - clean.length;
      if (dropped > 0) console.log(`[researcher] PR/campaign除外 ${dropped}件 (${t.query || "news"})`);
      return { ...t, results: clean };
    })
  );

  let generated = 0;
  for (const s of settled) {
    if (s.status === "rejected") {
      console.warn(`[researcher] 検索失敗: ${s.reason?.message}`);
      continue;
    }
    const { axis, results, query } = s.value;
    if (!results.length) continue;
    let ideas = [];
    try {
      ideas = await generateIdeas(results, axis, existingIdeas);
    } catch (e) {
      console.warn(`[researcher] ネタ化失敗 (${query || "news"}): ${e.message}`);
      continue;
    }
    for (const idea of ideas) {
      if (isDuplicateTopic(idea.topic, existingIdeas)) {
        console.log(`[researcher] 重複スキップ: ${idea.topic}`);
        continue;
      }
      const record = {
        id: generateId("idea", readJsonl(IDEA_BANK_PATH)),
        axis,
        topic: idea.topic,
        angle: idea.angle,
        sourceUrls: (idea.sourceUrls || []).filter((u) => !isPromoJunk({ url: u })),
        suggestedType: idea.suggestedType || null,
        status: "active",
        createdAt: jstNow(),
      };
      if (dryRun) {
        console.log(`[researcher] (dry) + ${record.topic} (${axis})`);
      } else {
        appendJsonl(IDEA_BANK_PATH, record);
      }
      existingIdeas.push(record);
      generated++;
      if (generated >= count) break;
    }
    if (generated >= count) break;
  }

  console.log(`[researcher] 完了。ネタ${generated}件生成（目標${count}）。`);
  return generated;
}

// CLI
import { fileURLToPath } from "node:url";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const args = process.argv.slice(2);
  const ci = args.indexOf("--count");
  const count = ci >= 0 ? parseInt(args[ci + 1], 10) : 10;
  const dryRun = args.includes("--dry-run");
  runResearcher({ count, dryRun }).catch((e) => {
    console.error(`[researcher] Fatal: ${e.message}`);
    process.exit(1);
  });
}
