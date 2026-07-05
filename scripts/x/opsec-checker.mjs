#!/usr/bin/env node
// scripts/x/opsec-checker.mjs
// 最終ガード段（evidence_ok → reviewed / rejected）。
// ペルソナ具体度ガード（捏造・身バレ防止）＋ 薬機法/景表法。
//   ① 機械 regex 即弾き（config.personaGuards + ngWords）… 車種/専門科/学年/効能断定/選挙/誇大
//   ② LLM 意味検査 … 未所有ギアの所有主張、微妙な効能断定、個別医療相談への回答
// reviewed になった投稿だけが人間承認(approve.mjs / dashboard)→ posted に進める。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { resolve } from "node:path";
import { readJsonl, updatePost, jstNow, POSTS_PATH } from "./lib/file-lock.mjs";
import { CONFIG } from "./lib/persona.mjs";
import { callGPT, hasOpenAIKey } from "./lib/openai-api.mjs";
import { callClaude } from "./lib/claude-api.mjs";

const G = CONFIG.personaGuards || {};
const NG = CONFIG.ngWords || {};

// docs/author-gear.md 記載の「所有ギア」allowlist（所有主張してよいもの）
const OWNED_GEAR = [
  "スノーピーク アメニティドーム",
  "アメニティドーム",
  "アメドL",
  "メッシュタープ",
  "スノーピーク 焚火台 L",
  "焚火台L",
  "コールマン 2500 ノーススター",
  "ノーススター",
  "ユニフレーム ツーバーナー",
  "ユニフレーム US-1900",
  "US-1900",
  "ユニフレーム フィールドラック",
  "フィールドラック",
  "スタンレー グロウラー",
  "キャプテンスタッグ 焚き火台", // 過去機(引退)
];

// ─── ① 機械 regex 即弾き ─────────────────────────────────────────────
export function mechanicalScan(body) {
  const hits = [];
  const add = (cat, list) => {
    for (const w of list || []) if (w && body.includes(w)) hits.push(`${cat}:${w}`);
  };
  add("車種", G.carModels);
  add("専門科", G.medicalSpecialties);
  add("学年", G.childGradeLevels);
  add("効能断定(薬機法)", NG.medical);
  add("誇大", NG.landmark);
  add("政治", NG.political);
  add("NG誇張", NG.hype);
  return hits;
}

// ─── ② LLM 意味検査 ──────────────────────────────────────────────────
function buildPrompt(body) {
  return `X投稿のコンプライアンス/身バレを最終チェックしてください。

## 投稿者ギア男の「所有ギア」リスト（これ以外を"愛用/所有/○年使った"と書くのは違反。"気になる/欲しい"はOK）
${OWNED_GEAR.join(" / ")}

## 投稿文
"""
${body}
"""

## 違反フラグ（true/false）
- unownedGearClaim: 所有リスト外のギアを所有・愛用・長期使用しているかのように書いている
- medicalEfficacy: 薬機法/景表法に触れる効能効果の断定（治る・効く・予防できる・痩せる等の暗示含む）
- medicalAdvice: 個別の医療相談に具体的に回答している（一般情報はOK、個別診断・治療指示はNG）
- privacyLeak: 東京より細かい地名・医院名・学校名・家族の個人名・専門科の特定
- hype: 煽り・過度な宣伝・断定的誇張

## 出力（JSONのみ）
{ "unownedGearClaim": false, "medicalEfficacy": false, "medicalAdvice": false, "privacyLeak": false, "hype": false, "notes": "違反があれば該当箇所を1文で" }`;
}

function parse(text) {
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("opsec レスポンスをJSON解析できません");
  const cleaned = m[0].replace(/```json?/gi, "").replace(/,\s*([}\]])/g, "$1");
  return JSON.parse(cleaned);
}

async function semanticScan(body) {
  const prompt = buildPrompt(body);
  if (hasOpenAIKey()) {
    try {
      return parse(
        await callGPT({
          system: "You are a compliance/opsec reviewer for a Japanese X account. Output ONLY JSON.",
          messages: [{ role: "user", content: prompt }],
          model: "gpt-4o",
          maxTokens: 300,
          temperature: 0,
        })
      );
    } catch (e) {
      console.warn(`[opsec] GPT失敗、Claudeへ: ${e.message}`);
    }
  }
  return parse(
    await callClaude({
      system: "あなたはX投稿のコンプライアンス最終チェック担当です。JSONのみ出力。",
      messages: [{ role: "user", content: prompt }],
      model: "claude-haiku-4-5-20251001",
      maxTokens: 300,
      temperature: 0,
    })
  );
}

export async function runOpsecChecker({ dryRun = false } = {}) {
  const posts = readJsonl(POSTS_PATH);
  const targets = posts.filter((p) => p.status === "evidence_ok");
  if (targets.length === 0) {
    console.log("[opsec] evidence_ok がありません。");
    return { passed: 0, rejected: 0 };
  }
  console.log(`[opsec] ${targets.length}件を最終ガード`);
  let passed = 0;
  let rejected = 0;

  for (const post of targets) {
    // ① 機械 regex（LLM を呼ぶ前に確実に弾く）
    const mech = mechanicalScan(post.body);
    if (mech.length) {
      if (!dryRun)
        updatePost(post.id, {
          status: "rejected",
          rejectedBy: "opsec-mechanical",
          rejectionReason: `機械検出: ${mech.join(", ")}`,
          opsecAt: jstNow(),
        });
      rejected++;
      console.log(`[opsec] REJECT(機械) ${post.id} | ${mech.join(", ")}`);
      continue;
    }

    // ② LLM 意味検査
    let r;
    try {
      r = await semanticScan(post.body);
    } catch (e) {
      console.error(`[opsec] 意味検査失敗 ${post.id}: ${e.message} — 安全側で保留(reviewed化しない)`);
      continue;
    }
    const flags = ["unownedGearClaim", "medicalEfficacy", "medicalAdvice", "privacyLeak", "hype"].filter(
      (k) => r[k]
    );
    if (flags.length) {
      if (!dryRun)
        updatePost(post.id, {
          status: "rejected",
          rejectedBy: "opsec-semantic",
          rejectionReason: `${flags.join(",")}: ${r.notes || ""}`,
          opsec: r,
          opsecAt: jstNow(),
        });
      rejected++;
      console.log(`[opsec] REJECT ${post.id} | ${flags.join(",")} | ${r.notes || ""}`);
    } else {
      if (!dryRun) updatePost(post.id, { status: "reviewed", opsec: r, opsecAt: jstNow() });
      passed++;
      console.log(`[opsec] OK→reviewed ${post.id}`);
    }
  }
  console.log(`[opsec] 完了。reviewed ${passed} / reject ${rejected}`);
  return { passed, rejected };
}

// CLI
import { fileURLToPath } from "node:url";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const dryRun = process.argv.includes("--dry-run");
  runOpsecChecker({ dryRun }).catch((e) => {
    console.error(`[opsec] Fatal: ${e.message}`);
    process.exit(1);
  });
}
