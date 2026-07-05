#!/usr/bin/env node
// scripts/x/writer.mjs
// ネタ(ideas.jsonl の active)→ ドラフト投稿を生成し posts.jsonl に status:"draft" で積む。
// 重要: 自己採点はしない（採点は独立 reviewer に委ねる = 自己採点の甘さを排除）。
// SimHash 近似重複だけ writer 段で弾く（採点ではなく機械的重複防止）。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import {
  readJsonl,
  appendJsonl,
  writeJsonl,
  generateId,
  jstNow,
  IDEA_BANK_PATH,
  POSTS_PATH,
  isKillSwitchOn,
} from "./lib/file-lock.mjs";
import { callClaude, hasClaudeKey } from "./lib/claude-api.mjs";
import { buildPersonaSystem, CONFIG } from "./lib/persona.mjs";
import { checkSimilarity } from "./lib/scoring.mjs";

const SIM_THRESHOLD = CONFIG.safety?.similarityThreshold ?? 0.7;

// X投稿本文も脱AI・体温が最重要のため Opus 4.8 を既定に（短文で増分はほぼゼロ）。
// X_WRITER_MODEL で上書き可、404 時は下記へ自動フォールバック。
const WRITER_MODEL = process.env.X_WRITER_MODEL || "claude-opus-4-8";
const WRITER_FALLBACK = process.env.X_WRITER_FALLBACK_MODEL || "claude-sonnet-4-6";

// 軸ごとの「独自視点」の出し方（WISE-GEARMAN の I 軸を作文段階で満たす）
const AXIS_INSIGHT = {
  camp: "10年のギア選び・比較の蓄積から来る視点を1つ入れる（同価格帯を試した結論、スペックの裏側、失敗から得た基準など）",
  doctor: "医師（内科ホームドクター）目線を1つ入れる。ただし専門科・症例・薬剤名・機器名・効能断定はNG（薬機法）。「本職柄」程度で",
  parenting: "子供との具体的な一場面（子供の反応・言葉）を1つ入れる。学年・学校名・個人名は出さない",
};

function buildUserPrompt(idea) {
  const typeHint = idea.suggestedType && idea.suggestedType !== "null"
    ? `\n推奨タイプ: ${idea.suggestedType}`
    : "";
  const insight = AXIS_INSIGHT[idea.axis] || AXIS_INSIGHT.camp;
  return `次のネタから、ギア男の X 投稿を1本書いてください。この投稿は独立採点者が「AI臭さ」「独自視点」「体温」で厳しく採点します。通る文章を書いてください。

ネタ: ${idea.topic}
切り口: ${idea.angle || "(自由)"}
軸: ${idea.axis}${typeHint}

【必須（これが無いと落ちます）】
1. 具体的な場面: 「時（先週末・3年使って・冬の朝など）」＋「場所や状況」＋「具体的な行動か数字」のうち2つ以上を必ず入れる。一般論で終わらせない
2. 独自視点: ${insight}
3. ネタと切り口に忠実（後段で整合性を機械チェックします）

【禁止（AI臭として落とされます）】
- 「導入→本題→まとめ」の整いすぎた三段構成。教科書的な結論づけをしない
- 文末を「〜です。〜ます。」で単調に揃える → 体言止め・問いかけ・言い切りを混ぜて変化をつける
- 「〜することがあります」「〜べきでした」「〜と言えるでしょう」等の定型フレーズ
- あれもこれも詰め込む → 一つの具体的な気づきに絞る

【出力】
- 本文のみ。前置き・解説・引用符・ハッシュタグ・URLは不要
- ${CONFIG.formatting?.maxChars || 140}字以内。友人に話しかける温度で`;
}

// WRITER_MODEL で生成、404 なら WRITER_FALLBACK で1度だけ再試行
async function generateBody(system, prompt) {
  const params = { system, messages: [{ role: "user", content: prompt }], maxTokens: 400, temperature: 0.9 };
  try {
    return await callClaude({ ...params, model: WRITER_MODEL });
  } catch (e) {
    const notFound = e?.status === 404 || /not_found|model:/i.test(e?.message || "");
    if (notFound && WRITER_MODEL !== WRITER_FALLBACK) {
      console.warn(`[writer] モデル ${WRITER_MODEL} が404 → ${WRITER_FALLBACK} へフォールバック`);
      return await callClaude({ ...params, model: WRITER_FALLBACK });
    }
    throw e;
  }
}

export async function runWriter({ count = 6, dryRun = false } = {}) {
  if (isKillSwitchOn()) {
    console.log("[writer] kill-switch ON。スキップ。");
    return { drafted: 0, skipped: 0 };
  }
  if (!hasClaudeKey()) {
    console.warn("[writer] ANTHROPIC_API_KEY 未設定。生成スキップ。");
    return { drafted: 0, skipped: 0 };
  }

  const ideas = readJsonl(IDEA_BANK_PATH);
  const active = ideas.filter((i) => i.status === "active");
  if (active.length === 0) {
    console.log("[writer] active なネタがありません。");
    return { drafted: 0, skipped: 0 };
  }

  const system = buildPersonaSystem();
  const existingPosts = readJsonl(POSTS_PATH).filter((p) => p.status !== "rejected" && p.similarityHash);

  let drafted = 0;
  let skipped = 0;
  const targets = active.slice(0, count);

  for (const idea of targets) {
    let body;
    try {
      body = await generateBody(system, buildUserPrompt(idea));
    } catch (e) {
      console.warn(`[writer] 生成失敗 (${idea.id}): ${e.message}`);
      continue;
    }
    body = body.replace(/^["「『]|["」』]$/g, "").trim();

    // 近似重複チェック（採点ではなく機械的重複防止）
    const sim = checkSimilarity(body, existingPosts, SIM_THRESHOLD);
    if (!sim.pass) {
      console.log(`[writer] 重複スキップ (${idea.id}) sim=${sim.maxSimilarity} ~ ${sim.mostSimilarId}`);
      skipped++;
      continue;
    }

    const post = {
      id: generateId("gx", readJsonl(POSTS_PATH)),
      status: "draft",
      axis: idea.axis,
      type: idea.suggestedType || "outdoor_tip",
      body,
      ideaId: idea.id,
      ideaTopic: idea.topic,
      ideaAngle: idea.angle || null,
      sourceUrls: idea.sourceUrls || [],
      similarityHash: sim.hash,
      createdAt: jstNow(),
    };

    if (dryRun) {
      console.log(`[writer] (dry) draft: ${body.slice(0, 50)}...`);
    } else {
      appendJsonl(POSTS_PATH, post);
      // ネタを used に落とす
      const all = readJsonl(IDEA_BANK_PATH);
      const idx = all.findIndex((i) => i.id === idea.id);
      if (idx >= 0) {
        all[idx] = { ...all[idx], status: "used", usedAt: jstNow() };
        writeJsonl(IDEA_BANK_PATH, all);
      }
    }
    existingPosts.push({ ...post });
    drafted++;
  }

  console.log(`[writer] 完了。draft ${drafted}件、重複skip ${skipped}件。`);
  return { drafted, skipped };
}

// CLI
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const args = process.argv.slice(2);
  const ci = args.indexOf("--count");
  const count = ci >= 0 ? parseInt(args[ci + 1], 10) : 6;
  const dryRun = args.includes("--dry-run");
  runWriter({ count, dryRun }).catch((e) => {
    console.error(`[writer] Fatal: ${e.message}`);
    process.exit(1);
  });
}
