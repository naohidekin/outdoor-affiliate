// scripts/x/lib/claude-api.mjs
// Anthropic SDK の薄いラッパー。既存 x-post-generator.mjs と同じ規約
// （ANTHROPIC_API_KEY / ipv4 fetch / maxRetries:3）に合わせる。
import Anthropic from "@anthropic-ai/sdk";
import dns from "node:dns";

// 既存パイプラインと同様、IPv4 優先で DNS 解決（一部環境の IPv6 詰まり対策）
dns.setDefaultResultOrder?.("ipv4first");

let _client = null;
function getClient() {
  if (_client) return _client;
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY が未設定です");
  _client = new Anthropic({ apiKey, maxRetries: 3 });
  return _client;
}

export function hasClaudeKey() {
  return !!process.env.ANTHROPIC_API_KEY;
}

// 既存の記事パイプライン(article-*-agent)が使う現行モデル。
// 旧X系の "claude-sonnet-4-20250514" は404になるため使わない。
// X_CLAUDE_MODEL で上書き可能。
export const DEFAULT_CLAUDE_MODEL = process.env.X_CLAUDE_MODEL || "claude-sonnet-4-6";

/**
 * @returns {Promise<string>} テキスト本文
 */
export async function callClaude({
  system,
  messages,
  model = DEFAULT_CLAUDE_MODEL,
  maxTokens = 1024,
  temperature = 0.7,
}) {
  const client = getClient();
  const base = { model, max_tokens: maxTokens, ...(system ? { system } : {}), messages };
  let res;
  try {
    res = await client.messages.create({ ...base, temperature });
  } catch (e) {
    // Opus 4.8/4.7・Sonnet 5・Fable 5 等は sampling param を受け付けず 400。外して再試行。
    const samplingRejected = e?.status === 400 && /temperature|top_p|top_k/i.test(e?.message || "");
    if (samplingRejected) {
      res = await client.messages.create(base);
    } else {
      throw e;
    }
  }
  return res.content
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("")
    .trim();
}
