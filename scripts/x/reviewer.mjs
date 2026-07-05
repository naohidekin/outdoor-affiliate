#!/usr/bin/env node
// scripts/x/reviewer.mjs
// 独立採点段（draft → cross_reviewed / rejected）。
// amble を踏襲:
//   - 書き手=Claude に対し 採点=GPT-4o（別ベンダー）で独立性を担保 → 自己採点の甘さを排除
//   - pass 判定はサーバ側で再計算（モデルの pass フラグを信用しない）
//   - OPENAI_API_KEY が無ければ Claude 別モデル(haiku)へ警告付きフォールバック
// 採点基準は docs/WISE-GEARMAN.md（W/I/S/E/AI 各1-4、合格 W≥2,I≥2,S≥2,E≥2,AI≥3）。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { readJsonl, updatePost, jstNow, POSTS_PATH } from "./lib/file-lock.mjs";
import { callGPT, hasOpenAIKey } from "./lib/openai-api.mjs";
import { callClaude } from "./lib/claude-api.mjs";

const ROOT = resolve(import.meta.dirname, "../..");
const WISE_PATH = resolve(ROOT, "docs/WISE-GEARMAN.md");
let WISE_TEXT = "";
try {
  if (existsSync(WISE_PATH)) WISE_TEXT = readFileSync(WISE_PATH, "utf8");
} catch {
  /* fall back to inline */
}

const PASS = { w: 2, i: 2, s: 2, e: 2, ai: 3 };

function judgePass(s) {
  return s.w >= PASS.w && s.i >= PASS.i && s.s >= PASS.s && s.e >= PASS.e && s.ai >= PASS.ai;
}

function buildPrompt(body, ideaTopic) {
  return `以下の X 投稿を独立レビューしてください。

## 投稿者
ギア男（@camp_gear_lab）: 東京在住40歳・開業医(内科ホームドクター)・キャンプ歴10年・2児の父。一人称「僕」、ですます調。

## 元ネタ（この投稿はこのネタから書かれた）
${ideaTopic || "(不明)"}

## 投稿文
"""
${body}
"""

## 採点基準（WISE-GEARMAN、各1-4）
${WISE_TEXT || "W(体温:実体験), I(独自視点:医師×ギアオタク), S(誠実:正直・押し付けない), E(共感:読者に刺さる), AI(AI臭くない)"}

## 指示
1. W/I/S/E/AI を各1-4で独立採点
2. AI軸は特に厳しく: Claude特有の丁寧すぎ・構造的すぎ・定型句・文末単調を検出
3. この投稿はClaudeが生成したもの。同系列に甘くならないよう厳格に

## 出力（JSONのみ）
{ "scores": { "w": N, "i": N, "s": N, "e": N, "ai": N }, "notes": "所見(日本語2文)" }
合格: W≥2 AND I≥2 AND S≥2 AND E≥2 AND AI≥3`;
}

function parse(responseText) {
  const m = responseText.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("採点レスポンスをJSONとして解析できません");
  const parsed = JSON.parse(m[0]);
  if (!parsed.scores || typeof parsed.scores.w !== "number") throw new Error("scores 構造が不正");
  parsed.pass = judgePass(parsed.scores); // サーバ側で再計算（モデルの判定を信用しない）
  return parsed;
}

async function reviewWithGPT(body, topic) {
  const out = await callGPT({
    system:
      "You independently review an X post written by Claude. Score with WISE-GEARMAN. " +
      "Be especially critical of AI-generated patterns (over-polished, over-structured, formulaic). Output ONLY JSON.",
    messages: [{ role: "user", content: buildPrompt(body, topic) }],
    model: "gpt-4o",
    maxTokens: 400,
    temperature: 0.3,
  });
  return parse(out);
}

async function reviewWithClaudeFallback(body, topic) {
  console.warn("[reviewer] WARNING: OpenAIキー無し → Claude haiku へフォールバック（独立性が低下）");
  const out = await callClaude({
    system:
      "あなたはX投稿のクロスレビュアーです。WISE-GEARMANで独立採点。" +
      "この投稿はClaude生成物。同系列として甘くならないよう、特にAI臭さを厳しく。JSONのみ出力。",
    messages: [{ role: "user", content: buildPrompt(body, topic) }],
    model: "claude-haiku-4-5-20251001",
    maxTokens: 400,
    temperature: 0.3,
  });
  return parse(out);
}

export async function runReviewer({ dryRun = false } = {}) {
  const posts = readJsonl(POSTS_PATH);
  const targets = posts.filter((p) => p.status === "draft");
  if (targets.length === 0) {
    console.log("[reviewer] draft がありません。");
    return { passed: 0, rejected: 0 };
  }
  const useGPT = hasOpenAIKey();
  console.log(`[reviewer] ${targets.length}件を独立採点（${useGPT ? "GPT-4o" : "claude-haiku fallback"}）`);

  let passed = 0;
  let rejected = 0;
  for (const post of targets) {
    let result;
    let reviewedBy = useGPT ? "gpt-4o" : "claude-haiku-fallback";
    try {
      result = useGPT
        ? await reviewWithGPT(post.body, post.ideaTopic)
        : await reviewWithClaudeFallback(post.body, post.ideaTopic);
    } catch (e) {
      if (useGPT) {
        try {
          result = await reviewWithClaudeFallback(post.body, post.ideaTopic);
          reviewedBy = "claude-haiku-fallback";
        } catch (e2) {
          console.error(`[reviewer] 両採点者が失敗 ${post.id}: ${e2.message} — スキップ`);
          continue;
        }
      } else {
        console.error(`[reviewer] 採点失敗 ${post.id}: ${e.message} — スキップ`);
        continue;
      }
    }

    const patch = {
      wiseScores: result.scores,
      reviewedBy,
      reviewedAt: jstNow(),
    };
    if (result.pass) {
      if (!dryRun) updatePost(post.id, { ...patch, status: "cross_reviewed", reviewNotes: result.notes });
      passed++;
      const s = result.scores;
      console.log(`[reviewer] PASS ${post.id} (${reviewedBy}) W${s.w} I${s.i} S${s.s} E${s.e} AI${s.ai}`);
    } else {
      if (!dryRun)
        updatePost(post.id, { ...patch, status: "rejected", rejectedBy: "reviewer", rejectionReason: result.notes });
      rejected++;
      const s = result.scores;
      console.log(`[reviewer] REJECT ${post.id} W${s.w} I${s.i} S${s.s} E${s.e} AI${s.ai} | ${result.notes}`);
    }
  }
  console.log(`[reviewer] 完了。pass ${passed} / reject ${rejected}`);
  return { passed, rejected };
}

// CLI
import { fileURLToPath } from "node:url";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const dryRun = process.argv.includes("--dry-run");
  runReviewer({ dryRun }).catch((e) => {
    console.error(`[reviewer] Fatal: ${e.message}`);
    process.exit(1);
  });
}
