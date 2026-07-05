#!/usr/bin/env node
// scripts/x/reply.mjs
// ギア男 リプ精錬パイプライン（案B: X検索を使わず $0）。
// 入力: data/x/reply-targets.txt（1行 = 「URL | 軸 | 相手の投稿本文」）
// 流れ: 生成(Opus, 価値付加リプ) → GPT-4o独立採点 → opsec → GearMan Replies DB(draft)
//   → あなたが Notion で確認・承認 → 引用なら notion-poster が自動、通常リプは手動コピペ
// 共有エンジン viral-engage-core.mjs には触れない（他アカウント無影響）。
// ペルソナは account-config（persona.mjs）を使用（engage-config の別トーンは使わない）。
import { loadEnv } from "./lib/file-lock.mjs";
loadEnv();

import { readFileSync, existsSync, appendFileSync } from "node:fs";
import { resolve } from "node:path";
import { generateId, jstNow, readJsonl } from "./lib/file-lock.mjs";
import { buildPersonaSystem, CONFIG } from "./lib/persona.mjs";
import { callClaude, hasClaudeKey } from "./lib/claude-api.mjs";
import { callGPT, hasOpenAIKey } from "./lib/openai-api.mjs";
import { mechanicalScan } from "./opsec-checker.mjs";
import { pushReplyToNotion } from "./lib/notion.mjs";

const ROOT = resolve(import.meta.dirname, "../..");
const TARGETS_PATH = resolve(ROOT, "data/x/reply-targets.txt");
const REPLIES_LOG = resolve(ROOT, "data/x/replies.jsonl");
const WRITER_MODEL = process.env.X_WRITER_MODEL || "claude-opus-4-8";
const WRITER_FALLBACK = process.env.X_WRITER_FALLBACK_MODEL || "claude-sonnet-4-6";
const MAX_CHARS = CONFIG.formatting?.maxChars || 140;

// 入力パース: 基本は「URLだけ」を1行ずつ。任意で「URL | 軸」「URL | 軸 | 本文」も可。
// 本文が無ければ fxtwitter から自動取得する。# 始まりと空行は無視。軸省略時は camp。
function parseTargets() {
  if (!existsSync(TARGETS_PATH)) return [];
  return readFileSync(TARGETS_PATH, "utf8")
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"))
    .map((line) => {
      const parts = line.split("|").map((s) => s.trim());
      const url = parts[0];
      let axis = "camp";
      let text = "";
      if (parts.length >= 3) {
        axis = ["camp", "doctor", "parenting"].includes(parts[1]) ? parts[1] : "camp";
        text = parts.slice(2).join(" | ");
      } else if (parts.length === 2) {
        // 2列目が軸なら軸、そうでなければ本文とみなす
        if (["camp", "doctor", "parenting"].includes(parts[1])) axis = parts[1];
        else text = parts[1];
      }
      return { url, axis, targetText: text };
    })
    .filter((t) => t.url && /\/status\/\d+/.test(t.url));
}

// URL からツイート本文を取得（公開ミラー fxtwitter、認証不要・$0）。取れなければ null。
async function fetchTweetText(url) {
  const fx = url.replace(/^https?:\/\/(x\.com|twitter\.com|mobile\.twitter\.com)/i, "https://api.fxtwitter.com");
  try {
    const res = await fetch(fx, { headers: { "User-Agent": "gearman-reply/1.0" } });
    if (!res.ok) return null;
    const data = await res.json();
    return data?.tweet?.text || data?.tweet?.raw_text?.text || null;
  } catch {
    return null;
  }
}

const AXIS_ANGLE = {
  camp: "10年のギア選び・実体験から、相手の投稿に“もう一歩踏み込む視点か具体”を足す（比較の裏側・失敗から得た基準・スペックの実感など）",
  doctor: "医師(内科ホームドクター)目線を一つ添える。ただし専門科・症例・薬剤名・機器名・効能断定はNG(薬機法)。「本職柄」程度で",
  parenting: "子育て×アウトドアの実感を一つ添える。子供の学年・学校名・個人名は出さない",
};

function buildReplyPrompt(t) {
  return `次の X 投稿への「リプライ」を1本書いてください。目的は、相手に喜ばれ、あなた(ギア男)のプロフィールを見たくなるリプです。独立採点者が厳しく採点します。

## 相手の投稿
"""
${t.targetText || "(本文未提供)"}
"""
URL: ${t.url}
軸: ${t.axis}

## 良いリプの条件（これが無いと落ちます）
1. 相手の投稿の“具体”に触れて反応する（一般的な相槌でなく、その投稿ならではの点に）
2. ${AXIS_ANGLE[t.axis] || AXIS_ANGLE.camp}
3. 相手を立てる/共感しつつ、押し付けない。売り込み・宣伝・自分語りの独演にしない

## 禁止（AI臭・地雷として落とされます）
- 「わかります」「素敵ですね」だけの空リプ、当たり障りのない同意
- 「〜してみてはいかがでしょうか」「〜と言えるでしょう」等の定型/上から目線
- 誇張(最高/絶対/必ず)・効能断定・車種/専門科/未所有ギアの具体名・URL

## 出力
- リプ本文のみ。前置き・引用符・ハッシュタグ・URLは不要
- ${MAX_CHARS}字以内。ですます調、一人称「僕」、友人に話しかける温度`;
}

async function generateReply(system, t) {
  const params = { system, messages: [{ role: "user", content: buildReplyPrompt(t) }], maxTokens: 300, temperature: 0.9 };
  try {
    return await callClaude({ ...params, model: WRITER_MODEL });
  } catch (e) {
    const nf = e?.status === 404 || /not_found|model:/i.test(e?.message || "");
    if (nf && WRITER_MODEL !== WRITER_FALLBACK) return await callClaude({ ...params, model: WRITER_FALLBACK });
    throw e;
  }
}

// リプ専用ルーブリック（各1-4、合格 全て≥3）
function buildReviewPrompt(t, reply) {
  return `X のリプライを独立採点してください。投稿者はギア男（東京在住40歳・開業医/内科ホームドクター・キャンプ歴10年・2児の父、ですます調・一人称「僕」）。

## 相手の投稿
"""
${t.targetText || "(不明)"}
"""
## ギア男のリプ案
"""
${reply}
"""
## 採点(各1-4)
- R(関連): 相手の投稿の具体に的確に反応しているか(一般的な相槌は低)
- V(価値): 独自の知見/経験を足しているか(空同意は低)
- P(人間味): AI臭くない・媚びてない・ギア男の温度か
- F(誘引): これを見て投稿者のプロフィールを覗きたくなるか
## 出力(JSONのみ)
{ "scores": { "r": N, "v": N, "p": N, "f": N }, "notes": "所見(日本語1-2文)" }
合格: R≥3 AND V≥3 AND P≥3 AND F≥3`;
}

function parseReview(text) {
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("採点をJSON解析できません");
  const cleaned = m[0].replace(/```json?/gi, "").replace(/,\s*([}\]])/g, "$1");
  const p = JSON.parse(cleaned);
  if (!p.scores || typeof p.scores.r !== "number") throw new Error("scores 不正");
  const s = p.scores;
  p.pass = s.r >= 3 && s.v >= 3 && s.p >= 3 && s.f >= 3;
  return p;
}

async function reviewReply(t, reply) {
  const prompt = buildReviewPrompt(t, reply);
  if (hasOpenAIKey()) {
    try {
      return parseReview(
        await callGPT({
          system: "You independently score a Japanese X reply for a persona account. Output ONLY JSON.",
          messages: [{ role: "user", content: prompt }],
          model: "gpt-4o",
          maxTokens: 300,
          temperature: 0.3,
        })
      );
    } catch (e) {
      console.warn(`[reply] GPT採点失敗、Claudeへ: ${e.message}`);
    }
  }
  return parseReview(
    await callClaude({
      system: "あなたはX返信の独立採点者です。媚び・AI臭を厳しく。JSONのみ出力。",
      messages: [{ role: "user", content: prompt }],
      model: "claude-haiku-4-5-20251001",
      maxTokens: 300,
      temperature: 0.3,
    })
  );
}

export async function runReply({ dryRun = false } = {}) {
  if (!hasClaudeKey()) {
    console.warn("[reply] ANTHROPIC_API_KEY 未設定。スキップ。");
    return { pushed: 0 };
  }
  const targets = parseTargets();
  if (targets.length === 0) {
    console.log(`[reply] 対象がありません。${TARGETS_PATH} に「URL | 軸 | 相手の本文」を追記してください。`);
    return { pushed: 0 };
  }
  const useGPT = hasOpenAIKey();
  console.log(`[reply] ${targets.length}件の対象。生成=${WRITER_MODEL} / 採点=${useGPT ? "GPT-4o" : "claude-haiku fallback"}`);
  const system = buildPersonaSystem();

  let pushed = 0;
  let rejected = 0;
  for (const t of targets) {
    // 本文未指定なら fxtwitter から自動取得（URL貼るだけ運用）
    if (!t.targetText) {
      t.targetText = await fetchTweetText(t.url);
      if (!t.targetText) {
        console.warn(`[reply] 本文取得失敗 ${t.url} — スキップ（"URL | 軸 | 本文" で本文を手動指定も可）`);
        continue;
      }
    }
    let reply;
    try {
      reply = (await generateReply(system, t)).replace(/^["「『]|["」』]$/g, "").trim();
    } catch (e) {
      console.warn(`[reply] 生成失敗 (${t.url}): ${e.message}`);
      continue;
    }

    // opsec 機械ガード
    const mech = mechanicalScan(reply);
    if (mech.length) {
      console.log(`[reply] REJECT(opsec) ${t.url} | ${mech.join(", ")} | ${reply}`);
      rejected++;
      continue;
    }

    // 独立採点
    let rv;
    try {
      rv = await reviewReply(t, reply);
    } catch (e) {
      console.warn(`[reply] 採点失敗 (${t.url}): ${e.message} — スキップ`);
      continue;
    }
    const s = rv.scores;
    if (!rv.pass) {
      console.log(`[reply] REJECT R${s.r}V${s.v}P${s.p}F${s.f} | ${t.url} | ${rv.notes}`);
      rejected++;
      continue;
    }

    const rec = {
      id: generateId("gr", readJsonl(REPLIES_LOG)),
      targetUrl: t.url,
      axis: t.axis,
      replyText: reply,
      scores: s,
      reviewedBy: useGPT ? "gpt-4o" : "claude-haiku",
      status: "pushed",
      createdAt: jstNow(),
    };
    if (dryRun) {
      console.log(`[reply] (dry) PASS R${s.r}V${s.v}P${s.p}F${s.f} | ${reply}`);
      pushed++;
      continue;
    }
    try {
      await pushReplyToNotion({ targetUrl: t.url, replyText: reply, axis: t.axis }, { status: "draft" });
      appendFileSync(REPLIES_LOG, JSON.stringify(rec) + "\n", "utf8");
      pushed++;
      console.log(`[reply] ✓ PASS R${s.r}V${s.v}P${s.p}F${s.f} → Notion | ${reply.slice(0, 50)}`);
    } catch (e) {
      console.error(`[reply] Notion投入失敗 (${t.url}): ${e.message}`);
    }
  }
  console.log(`[reply] 完了。Notion投入 ${pushed} / reject ${rejected}。→ GearMan Replies を確認し承認してください。`);
  return { pushed, rejected };
}

// CLI
import { fileURLToPath } from "node:url";
if (resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1] || "")) {
  const dryRun = process.argv.includes("--dry-run");
  runReply({ dryRun }).catch((e) => {
    console.error(`[reply] Fatal: ${e.message}`);
    process.exit(1);
  });
}
