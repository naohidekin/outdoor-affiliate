// scripts/x/lib/openai-api.mjs
// OpenAI Chat Completions の薄いラッパー（別ベンダー独立採点用）。
// OPENAI_API_KEY が無ければ hasOpenAIKey()=false を返し、呼び出し側で
// Claude 別モデルへフォールバックする。SDK 依存を増やさず fetch で叩く。

export function hasOpenAIKey() {
  return !!process.env.OPENAI_API_KEY;
}

/**
 * @returns {Promise<string>} テキスト本文
 */
export async function callGPT({
  system,
  messages,
  model = "gpt-4o",
  maxTokens = 512,
  temperature = 0.3,
}) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY が未設定です");

  const payload = {
    model,
    max_tokens: maxTokens,
    temperature,
    messages: system ? [{ role: "system", content: system }, ...messages] : messages,
  };

  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`OpenAI error ${res.status}: ${err.slice(0, 200)}`);
  }

  const data = await res.json();
  return (data.choices?.[0]?.message?.content || "").trim();
}
