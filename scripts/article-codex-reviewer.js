#!/usr/bin/env node

import fs from "fs";
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
  try {
    return fs.readFileSync(SKILL_PATH, "utf-8");
  } catch {
    return "";
  }
}

function fallbackResult(content) {
  return {
    wise_scores: { w: 3, i: 3, s: 3, e: 3, ai: 3 },
    issues: [{ criterion: "AI", severity: "minor", note: "review skipped" }],
    revised_content: content,
  };
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
  "wise_scores": { "w": 1-5, "i": 1-5, "s": 1-5, "e": 1-5, "ai": 1-5 },
  "issues": [{ "criterion": "W|I|S|E|AI", "severity": "major|minor", "note": "具体的な問題点" }],
  "revised_content": "修正済みMarkdown"
}

制約:
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
    const safe = {
      wise_scores: reviewed.wise_scores || { w: 3, i: 3, s: 3, e: 3, ai: 3 },
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
