import fs from "node:fs";
import path from "node:path";
import Anthropic from "@anthropic-ai/sdk";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticatedRequest } from "@/lib/auth";

export const runtime = "nodejs";

const HOME = process.env.HOME || "/Users/NaohideKin";

// --- Business-specific scoring rubrics (10 dimensions each) ---

const RUBRICS: Record<string, { dims: string[]; description: string }> = {
  "jsh-threads": {
    dims: [
      "hook_strength",
      "usefulness",
      "specificity",
      "tempo_rhythm",
      "persona_match",
      "readability",
      "authenticity",
      "actionability",
      "uniqueness",
      "share_trigger",
    ],
    description:
      "Japan Shop Helper の Threads 投稿。訪日外国人向けに日本のショッピング・観光のTipsを英語で発信する。旅行者視点の実用性・具体性・シェアしたくなる内容が重要。",
  },
  "drAuto-note": {
    dims: [
      "accuracy",
      "readability",
      "originality",
      "expertise_depth",
      "reader_benefit",
      "cta_strength",
      "seo_fit",
      "tone_consistency",
      "structure",
      "engagement",
    ],
    description:
      "Dr.auto の note 記事。開業医がAI・医療・クリニック経営について書く。医師の専門性と体験談ベースの説得力、読者メリットの明確さが重要。",
  },
  "gearman-x": {
    dims: [
      "persona_fit",
      "camp_relevance",
      "hook_strength",
      "readability",
      "authenticity",
      "engagement",
      "humor",
      "actionability",
      "uniqueness",
      "share_trigger",
    ],
    description:
      "ギア男の X 投稿。長野在住37歳開業医・キャンプ歴10年のパパキャンパーとして、ギア比較・キャンプ体験・医師目線を発信。AI臭がなく体温のある文章が重要。",
  },
  "gearman-article": {
    dims: [
      "seo_fit",
      "readability",
      "expertise",
      "structure",
      "originality",
      "depth",
      "cta_effectiveness",
      "internal_link_value",
      "tone",
      "uniqueness",
    ],
    description:
      "ギア男のキャンプギア比較記事。SEOを意識しつつ、体験談・スペック比較・正直な評価で差別化。AI特有フレーズがなく読者の役に立つ内容。",
  },
  "amble-x": {
    dims: [
      "persona_fit",
      "financial_relevance",
      "hook_strength",
      "readability",
      "authenticity",
      "engagement",
      "actionability",
      "uniqueness",
      "trust",
      "share_trigger",
    ],
    description:
      "アンブロの X 投稿。小児科医・開業医として投資・お金のリアルを発信。専門性と体験に基づく信頼感、フォロワーに役立つ実践情報が重要。",
  },
  "kodomo-x": {
    dims: [
      "accuracy",
      "warmth",
      "nonAI",
      "persona",
      "length",
      "hashtags",
      "cta",
      "opsec",
      "engagement",
      "originality",
    ],
    description:
      "こどもケアラボの X 投稿。小児科医視点の育児・子ども医療情報。医学的正確性・温かみ・AI感のなさ・ペルソナ一貫性が評価軸。",
  },
};

function getRubricKey(
  business: string,
  type: string,
): string {
  return `${business}-${type}`;
}

function buildScoringPrompt(
  rubricKey: string,
  text: string,
): { system: string; user: string } {
  const rubric = RUBRICS[rubricKey] ?? RUBRICS["jsh-threads"];
  const dimList = rubric.dims.map((d, i) => `${i + 1}. ${d}`).join("\n");

  const system = `あなたはコンテンツ品質評価の専門家です。
以下のコンテンツを10次元で評価してください。

【コンテンツの文脈】
${rubric.description}

【評価次元】
${dimList}

【評価基準】
- 各次元を 1〜10 の整数で評価する（10が最高）
- 8以上: 優秀、合格水準
- 6〜7: 普通、改善の余地あり
- 5以下: 要改善

【出力形式】
必ず以下のJSONのみを返すこと（説明文不要）:
{"scores":{"${rubric.dims.join('":X,"')}":X}}`;

  const user = `以下のコンテンツを評価してください:\n\n${text}`;

  return { system, user };
}

function parseScores(
  content: string,
  dims: string[],
): Record<string, number> | null {
  try {
    // Extract JSON from response
    const match = content.match(/\{[\s\S]*\}/);
    if (!match) return null;
    const parsed = JSON.parse(match[0]) as { scores?: Record<string, unknown> };
    const raw: Record<string, unknown> = (parsed.scores as Record<string, unknown>) ?? (parsed as Record<string, unknown>);
    const result: Record<string, number> = {};
    for (const dim of dims) {
      const val = raw[dim];
      if (typeof val === "number" && val >= 1 && val <= 10) {
        result[dim] = val;
      }
    }
    return Object.keys(result).length > 0 ? result : null;
  } catch {
    return null;
  }
}

function calcAvg(scores: Record<string, number>): number {
  const vals = Object.values(scores);
  if (vals.length === 0) return 0;
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
}

// --- Write-back helpers ---

function writeBackJson(
  filePath: string,
  id: string,
  scores: Record<string, number>,
): void {
  const raw = fs.readFileSync(filePath, "utf8");
  const data = JSON.parse(raw);
  const arr: Array<Record<string, unknown>> = Array.isArray(data)
    ? data
    : (data.posts ?? data.queue ?? []);
  const idx = arr.findIndex((item) => item.id === id || String(item.id) === id);
  if (idx !== -1) {
    arr[idx] = { ...arr[idx], scores };
    if (Array.isArray(data)) {
      fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
    } else {
      fs.writeFileSync(
        filePath,
        `${JSON.stringify({ ...data, [Array.isArray(data.posts) ? "posts" : "queue"]: arr }, null, 2)}\n`,
        "utf8",
      );
    }
  }
}

function writeBackJsonl(
  filePath: string,
  id: string,
  scores: Record<string, number>,
): void {
  const raw = fs.readFileSync(filePath, "utf8");
  const lines = raw.split("\n");
  const newLines = lines.map((line) => {
    if (!line.trim()) return line;
    try {
      const obj = JSON.parse(line) as Record<string, unknown>;
      if (obj.id === id) {
        return JSON.stringify({ ...obj, _scores: scores });
      }
    } catch {
      /* skip */
    }
    return line;
  });
  fs.writeFileSync(filePath, newLines.join("\n"), "utf8");
}

function getSourcePath(business: string, type: string): string {
  switch (`${business}-${type}`) {
    case "gearman-x":
      return path.join(
        HOME,
        "Desktop/AI関連/claude/outdoor-affiliate/data/x-posts.json",
      );
    case "gearman-article":
      return path.join(
        HOME,
        "Desktop/AI関連/claude/outdoor-affiliate/data/articles.json",
      );
    case "amble-x":
      return path.join(
        HOME,
        "Desktop/AI関連/claude/san-pedinvestor-x/data/x-posts.json",
      );
    case "kodomo-x":
      return path.join(
        HOME,
        "Desktop/AI関連/parent-child-medical/data/x/posts.jsonl",
      );
    case "jsh-threads":
      return path.join(
        HOME,
        "dev/threads-japan-mistakes/data/post-queue.json",
      );
    default:
      return "";
  }
}

export async function POST(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  let body: {
    business: string;
    type: string;
    id: string;
    text: string;
    writeBack?: boolean;
  };

  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "不正なリクエスト" }, { status: 400 });
  }

  const { business, type, id, text, writeBack = true } = body;
  if (!business || !type || !id || !text) {
    return NextResponse.json(
      { error: "business, type, id, text が必要です" },
      { status: 400 },
    );
  }

  const rubricKey = getRubricKey(business, type);
  const rubric = RUBRICS[rubricKey];
  if (!rubric) {
    return NextResponse.json(
      { error: `未対応の business/type: ${rubricKey}` },
      { status: 400 },
    );
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "ANTHROPIC_API_KEY が設定されていません" },
      { status: 500 },
    );
  }

  const client = new Anthropic({ apiKey });
  const { system, user } = buildScoringPrompt(rubricKey, text);

  let scores: Record<string, number> | null = null;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const response = await client.messages.create({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 512,
        system,
        messages: [{ role: "user", content: user }],
      });
      const content =
        response.content[0]?.type === "text" ? response.content[0].text : "";
      scores = parseScores(content, rubric.dims);
      if (scores) break;
    } catch (err) {
      if (attempt === 2) {
        console.error("Claude API error:", err);
        return NextResponse.json(
          { error: "Claude API エラー" },
          { status: 502 },
        );
      }
    }
  }

  if (!scores) {
    return NextResponse.json(
      { error: "スコアのパースに失敗しました" },
      { status: 502 },
    );
  }

  const avgScore = calcAvg(scores);

  // Write back to source file if requested (not for dr-auto CSV)
  if (writeBack && business !== "drAuto") {
    try {
      const sourcePath = getSourcePath(business, type);
      if (sourcePath) {
        // Strip prefix from id (e.g. "jsh-post-xxx" -> "post-xxx")
        const rawId = id.replace(/^(gearman-x-|gearman-article-|amble-|kodomo-|jsh-)/, "");
        if (sourcePath.endsWith(".jsonl")) {
          writeBackJsonl(sourcePath, rawId, scores);
        } else {
          writeBackJson(sourcePath, rawId, scores);
        }
      }
    } catch (err) {
      console.error("Write-back error (non-fatal):", err);
      // Non-fatal: return scores even if write-back fails
    }
  }

  return NextResponse.json({ scores, avgScore });
}
