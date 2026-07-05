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

function buildUserPrompt(idea) {
  const typeHint = idea.suggestedType && idea.suggestedType !== "null"
    ? `\n推奨タイプ: ${idea.suggestedType}`
    : "";
  return `次のネタから、ギア男の X 投稿を1本書いてください。

ネタ: ${idea.topic}
切り口: ${idea.angle || "(自由)"}
軸: ${idea.axis}${typeHint}

要件:
- ネタと切り口に忠実に。ネタから逸れない（後段で整合性を機械チェックします）
- 体温のある実体験ベース（時・場所・行動・数字のどれかを入れる）
- 本文のみ出力。前置き・解説・引用符・ハッシュタグ・URLは不要
- ${CONFIG.formatting?.maxChars || 140}字以内`;
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
      body = await callClaude({
        system,
        messages: [{ role: "user", content: buildUserPrompt(idea) }],
        maxTokens: 400,
        temperature: 0.85,
      });
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
