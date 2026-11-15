#!/usr/bin/env node

import fs from "fs";
import { loadWisePolicy, validWiseScores, passesWise, wiseContentHash } from "../src/lib/wise-contract.mjs";
import path from "path";
import { fileURLToPath } from "url";
import Anthropic from "@anthropic-ai/sdk";
import { loadEnv, readJson } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.join(__dirname, "..");
const SKILL_PATH = path.join(PROJECT_ROOT, "SKILL.md");
const MODEL = "claude-sonnet-4-6";

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { articleId: null, content: "", topicBrief: null };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--article-id") opts.articleId = args[++i];
    if (args[i] === "--content") opts.content = args[++i] || "";
    if (args[i] === "--topic-brief") {
      try {
        opts.topicBrief = JSON.parse(args[++i] || "{}");
      } catch {
        opts.topicBrief = null;
      }
    }
  }
  return opts;
}

function loadSkillDoc() {
  return loadWisePolicy().text + "\n\n" + fs.readFileSync(SKILL_PATH, "utf-8");
}

function fallbackResult(content) {
  return { passed: false, wise_scores: null, supervisor_scores: null, wisePolicy: null,
    issues: [{ criterion: "WISE-AS", severity: "major", note: "review unavailable" }], revised_content: content };
}

async function reviewWithClaude(content, topicBrief) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY 未設定");

  const skillDoc = loadSkillDoc();
  const client = new Anthropic({ apiKey });

  const prompt = `あなたは記事品質レビュアーです。以下のSKILL基準を厳密適用し、WISE採点と必要最小限の本文修正を行ってください。

[SKILL全文]
${skillDoc}

[topicBrief]
${JSON.stringify(topicBrief || {}, null, 2)}

[article]
${content}

出力はJSONのみ。必ず以下の形式:
{
  "wise_scores": { "w": 1-4, "i": 1-4, "s": 1-4, "e": 1-4, "ai": 1-4, "sense": 1-4 },
  "supervisor_scores": { "wise_w": 0-10, "wise_i": 0-10, "wise_s": 0-10, "wise_e": 0-10, "wise_ai": 0-10, "wise_sense": 0-10 },
  "issues": [{ "criterion": "W|I|S|E|AI|Sense", "severity": "major|minor", "note": "具体的な問題点" }],
  "revised_content": "修正済みMarkdown"
}

制約:
- 六軸は原本の1–4点。Supervisor用の六フィールドは同じ意味を独立して0–10点で評価し、1–4点から換算しない
- 問題が軽微なら最小修正
- 問題がなければ原文をそのまま返す
- 禁止フレーズがあれば必ず置換`;

  const res = await client.messages.create({
    model: MODEL,
    max_tokens: 16000,
    system: "必ず有効なJSONオブジェクトのみを返す。前後テキスト禁止。",
    messages: [{ role: "user", content: prompt }],
  });

  const text = res.content?.[0]?.text?.trim() || "";
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) throw new Error("JSON parse failed");
  return JSON.parse(match[0]);
}

function readArticleAndTopic(articleId) {
  const articles = readJson("articles.json") || [];
  const plan = readJson("article-weekly-plan.json") || {};
  const article = articles.find((a) => a.id === articleId);
  if (!article) return { article: null, topicBrief: null };
  const topic = (plan.articles || []).find((t) => t.slug === article.slug) || null;
  return {
    article,
    topicBrief: topic
      ? {
          slug: topic.slug,
          title: topic.title,
          angle: topic.angle,
          targetKeywords: topic.targetKeywords || [],
          format_recommendation: topic.format_recommendation || topic.formatRecommendation || "guide",
        }
      : null,
  };
}

async function main() {
  const opts = parseArgs();

  let inputContent = opts.content || "";
  let topicBrief = opts.topicBrief;

  if (opts.articleId) {
    const result = readArticleAndTopic(opts.articleId);
    if (result.article) {
      inputContent = result.article.content || "";
      topicBrief = topicBrief || result.topicBrief;
    }
  }

  if (!inputContent) {
    console.log(JSON.stringify(fallbackResult("")));
    return;
  }

  try {
    const reviewed = await reviewWithClaude(inputContent, topicBrief || {});
    const keys = ["wise_w", "wise_i", "wise_s", "wise_e", "wise_ai", "wise_sense"];
    if (!validWiseScores(reviewed.wise_scores) || !reviewed.supervisor_scores
        || Object.keys(reviewed.supervisor_scores).length !== keys.length
        || !keys.every(k => typeof reviewed.supervisor_scores[k] === "number" && Number.isFinite(reviewed.supervisor_scores[k]) && reviewed.supervisor_scores[k] >= 0 && reviewed.supervisor_scores[k] <= 10)) throw new Error("complete owner and supervisor scores required");
    const safe = {
      passed: passesWise(reviewed.wise_scores) && Array.isArray(reviewed.issues) && !reviewed.issues.some(issue => issue.severity === "major"),
      wiseReviewPassed: passesWise(reviewed.wise_scores) && Array.isArray(reviewed.issues) && !reviewed.issues.some(issue => issue.severity === "major"),
      wisePolicy: loadWisePolicy().id,
      wiseContentHash: wiseContentHash(reviewed.revised_content || inputContent),
      wise_scores: reviewed.wise_scores,
      supervisor_scores: reviewed.supervisor_scores,
      issues: Array.isArray(reviewed.issues) ? reviewed.issues : [],
      revised_content: reviewed.revised_content || inputContent,
    };
    console.log(JSON.stringify(safe));
  } catch (err) {
    console.warn(`[article-codex-reviewer] warning: ${err.message}`);
    console.log(JSON.stringify(fallbackResult(inputContent)));
  }
}

main().catch((err) => {
  console.warn(`[article-codex-reviewer] warning: ${err.message}`);
  console.log(JSON.stringify(fallbackResult("")));
});
