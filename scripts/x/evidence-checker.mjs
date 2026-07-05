#!/usr/bin/env node
// scripts/x/evidence-checker.mjs
// 校閲・整合性段（cross_reviewed → evidence_ok / rejected）。
// ユーザー診断の是正点「ネタは拾うが、生成後にネタとの噛み合い・校閲が抜けて
// 少しズレたポストになる」への直接対応。
//   ① 整合性（coherence）: 投稿が元ネタ(topic/angle)から逸れていないか → 逸れたら reject
//   ② 断定スペックの検出: 検証不能な数値スペック/価格/型番の断定を洗い出す
//      → coherence OK でも claimsToVerify を付けて人間確認に回す（誤情報の拡散防止）
// 独立性のため採点と別に判定。GPT 優先・Claude フォールバック。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { resolve } from "node:path";
import { readJsonl, updatePost, jstNow, POSTS_PATH } from "./lib/file-lock.mjs";
import { callGPT, hasOpenAIKey } from "./lib/openai-api.mjs";
import { callClaude } from "./lib/claude-api.mjs";

function buildPrompt(post) {
  return `X投稿が「元ネタ」に忠実か、事実面で危うくないかを校閲してください。

## 元ネタ
topic: ${post.ideaTopic || "(不明)"}
angle: ${post.ideaAngle || "(不明)"}
axis: ${post.axis}

## 投稿文
"""
${post.body}
"""

## 判定
1. coherence(1-4): 投稿は元ネタ(topic/angle)に忠実か。1=無関係にズレた / 2=かすっている / 3=概ね沿う / 4=ネタを的確に投稿化
2. claimsToVerify: 投稿に含まれる「検証が必要な断定」(具体的な数値スペック・価格・型番・"○年で△△"等の事実主張)を配列で列挙。無ければ []
3. dangerousClaim(bool): 事実と異なると炎上/誤情報になる断定があるか（例: 安全性の誤り、価格の断定ミス）

## 出力（JSONのみ）
{ "coherence": N, "claimsToVerify": ["..."], "dangerousClaim": false, "notes": "所見(日本語1-2文)" }`;
}

function parse(text) {
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("evidence レスポンスをJSON解析できません");
  const cleaned = m[0].replace(/```json?/gi, "").replace(/,\s*([}\]])/g, "$1");
  const p = JSON.parse(cleaned);
  if (typeof p.coherence !== "number") throw new Error("coherence が不正");
  p.claimsToVerify = Array.isArray(p.claimsToVerify) ? p.claimsToVerify : [];
  p.dangerousClaim = !!p.dangerousClaim;
  return p;
}

async function judge(post) {
  const prompt = buildPrompt(post);
  if (hasOpenAIKey()) {
    try {
      return parse(
        await callGPT({
          system: "You proofread an X post against its source idea. Output ONLY JSON.",
          messages: [{ role: "user", content: prompt }],
          model: "gpt-4o",
          maxTokens: 400,
          temperature: 0.2,
        })
      );
    } catch (e) {
      console.warn(`[evidence] GPT失敗、Claudeへ: ${e.message}`);
    }
  }
  return parse(
    await callClaude({
      system: "あなたはX投稿の校閲者です。元ネタとの整合性と事実面を判定。JSONのみ出力。",
      messages: [{ role: "user", content: prompt }],
      model: "claude-haiku-4-5-20251001",
      maxTokens: 400,
      temperature: 0.2,
    })
  );
}

export async function runEvidenceChecker({ dryRun = false, coherenceMin = 3 } = {}) {
  const posts = readJsonl(POSTS_PATH);
  const targets = posts.filter((p) => p.status === "cross_reviewed");
  if (targets.length === 0) {
    console.log("[evidence] cross_reviewed がありません。");
    return { passed: 0, rejected: 0 };
  }
  console.log(`[evidence] ${targets.length}件を校閲`);
  let passed = 0;
  let rejected = 0;

  for (const post of targets) {
    let r;
    try {
      r = await judge(post);
    } catch (e) {
      console.error(`[evidence] 判定失敗 ${post.id}: ${e.message} — スキップ`);
      continue;
    }
    const fail = r.coherence < coherenceMin || r.dangerousClaim;
    if (fail) {
      if (!dryRun)
        updatePost(post.id, {
          status: "rejected",
          rejectedBy: "evidence",
          rejectionReason: `coherence=${r.coherence} danger=${r.dangerousClaim}: ${r.notes}`,
          evidence: r,
          evidenceAt: jstNow(),
        });
      rejected++;
      console.log(`[evidence] REJECT ${post.id} coherence=${r.coherence} danger=${r.dangerousClaim} | ${r.notes}`);
    } else {
      if (!dryRun)
        updatePost(post.id, {
          status: "evidence_ok",
          evidence: r,
          evidenceAt: jstNow(),
          claimsToVerify: r.claimsToVerify,
          needsHumanFactCheck: r.claimsToVerify.length > 0,
        });
      passed++;
      const flag = r.claimsToVerify.length ? ` ⚠要確認:${r.claimsToVerify.length}件` : "";
      console.log(`[evidence] OK ${post.id} coherence=${r.coherence}${flag}`);
    }
  }
  console.log(`[evidence] 完了。ok ${passed} / reject ${rejected}`);
  return { passed, rejected };
}

// CLI
import { fileURLToPath } from "node:url";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const dryRun = process.argv.includes("--dry-run");
  runEvidenceChecker({ dryRun }).catch((e) => {
    console.error(`[evidence] Fatal: ${e.message}`);
    process.exit(1);
  });
}
