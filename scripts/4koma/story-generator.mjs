import Anthropic from '@anthropic-ai/sdk';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

function loadEnv() {
  const envPath = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../.env.local');
  try {
    const lines = readFileSync(envPath, 'utf-8').split('\n');
    for (const line of lines) {
      const [k, ...v] = line.split('=');
      if (k && v.length && !process.env[k]) process.env[k] = v.join('=').trim();
    }
  } catch {}
}
loadEnv();

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const SYSTEM_PROMPT = `あなたはキャンプ・アウトドア系アフィリエイトサイト「ギア男キャンプ研究所」の4コマ漫画ライターです。

キャラクター設定：
- ギア男（主人公）: 30代の小児科医、キャンプ好き、ちょっとマニアック
- 妻や子供が登場することもある
- キャンプギアを真剣に研究するのが趣味

4コマの型：
- 1コマ目: 状況設定（問題提起 or あるある）
- 2コマ目: 行動・試行
- 3コマ目: 予想外の展開（オチへの布石）
- 4コマ目: オチ（笑い or 共感 or ためになる結末）

必ずJSON形式のみを返してください。説明文・前置き・コードブロックは不要です。`;

const USER_TEMPLATE = (theme) => `テーマ「${theme}」で4コマ漫画のストーリーをJSONで生成してください。

{
  "title": "4コマのタイトル",
  "theme": "${theme}",
  "panels": [
    {
      "panel": 1,
      "scene": "背景・状況の説明（英語、Pollinations AIプロンプト用）",
      "character_pose": "キャラクターのポーズ・表情（英語）",
      "dialogue": "セリフ（日本語、20文字以内）",
      "caption": "コマのキャプション（日本語、15文字以内、不要ならnull）"
    },
    { "panel": 2, "scene": "...", "character_pose": "...", "dialogue": "...", "caption": null },
    { "panel": 3, "scene": "...", "character_pose": "...", "dialogue": "...", "caption": null },
    { "panel": 4, "scene": "...", "character_pose": "...", "dialogue": "...", "caption": null }
  ]
}`;

export async function generate4komaStory(theme) {
  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    messages: [{ role: 'user', content: USER_TEMPLATE(theme) }],
  });

  const text = response.content[0].text.trim();
  const match = text.match(/\{[\s\S]+\}/);
  if (!match) throw new Error(`No JSON found in Claude response: ${text.slice(0, 200)}`);
  return JSON.parse(match[0]);
}

// CLI直接実行
const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const theme = process.argv[2] ?? 'キャンプ飯の失敗';
  console.log(`Generating story for theme: "${theme}"...`);
  generate4komaStory(theme)
    .then(story => console.log(JSON.stringify(story, null, 2)))
    .catch(err => { console.error('❌', err.message); process.exit(1); });
}
