import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import sharp from "sharp";
import { isAuthenticated } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

const STYLES: Record<string, string> = {
  painting: "soft manga illustration, gentle watercolor shading, warm pastel tones, friendly Japanese man in outdoor cap and camping jacket, character fills most of the frame, medium shot centered on character, background simple and blurred, white background, no text, no speech bubbles",
  flat:     "flat vector illustration, clean bold line art, earth tones green brown orange, friendly Japanese man in outdoor cap and camping jacket, character centered, simple background, white background, no text, no speech bubbles",
  sketch:   "pencil sketch manga style, rough expressive hand-drawn lines, light hatching, monochrome with soft grey tones, friendly Japanese man in outdoor cap, character fills frame, minimal background, no text, no speech bubbles",
  chibi:    "cute chibi manga style, big round eyes, rounded simplified body, bright cheerful colors, friendly Japanese man in outdoor cap and camping jacket, character large in frame, simple pastel background, no text, no speech bubbles",
  retro:    "retro 1980s Japanese manga style, bold thick ink lines, screen tone dot shading, high contrast black and white, friendly Japanese man in outdoor cap, expressive exaggerated emotions, character prominent, no text, no speech bubbles",
  webtoon:  "modern webtoon style, clean digital line art, soft color gradients, bright warm palette, friendly Japanese man in outdoor cap and camping jacket, character centered and fills frame, simple clean background, no text, no speech bubbles",
  manga:    "classic Japanese manga style, bold clean ink lines, strong black outlines, cel-shading, high contrast black and white with spot color, expressive character art, friendly Japanese man in outdoor cap and camping jacket, character fills frame, minimal background, no text, no speech bubbles",
};

const SYSTEM_PROMPT = `あなたはキャンプ・アウトドア系アフィリエイトサイト「ギア男キャンプ研究所」の4コマ漫画ライターです。

キャラクター設定：
- ギア男（主人公）: 30代の小児科医、キャンプ好き、ちょっとマニアック
- 妻や子供が登場することもある

4コマの型：1コマ目=状況設定、2コマ目=行動・試行、3コマ目=予想外の展開、4コマ目=オチ

必ずJSON形式のみを返してください。説明文・前置き・コードブロックは不要です。`;

function buildStoryPrompt(theme: string) {
  return `テーマ「${theme}」で4コマ漫画のストーリーをJSONで生成してください。返却はJSONのみ。

{
  "title": "4コマのタイトル",
  "theme": "${theme}",
  "panels": [
    { "panel": 1, "scene": "背景・状況（英語）", "character_pose": "ポーズ・表情（英語）", "dialogue": "セリフ（日本語20文字以内）", "caption": null },
    { "panel": 2, "scene": "...", "character_pose": "...", "dialogue": "...", "caption": null },
    { "panel": 3, "scene": "...", "character_pose": "...", "dialogue": "...", "caption": null },
    { "panel": 4, "scene": "...", "character_pose": "...", "dialogue": "...", "caption": null }
  ]
}`;
}

interface Panel { panel: number; scene: string; character_pose: string; dialogue: string; caption: string | null; }
interface Story { title: string; theme: string; panels: Panel[]; }

function buildImageUrl(panel: Panel, style: string, seed: number): string {
  const base = STYLES[style] ?? STYLES.painting;
  const prompt = `${base}, ${panel.character_pose}, simple ${panel.scene}, character prominent in frame`;
  return `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=512&height=512&seed=${seed}&nologo=true&model=flux`;
}

async function downloadImage(url: string, retries = 2): Promise<Buffer> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(25000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length < 2000) throw new Error(`Too small: ${buf.length}B`);
      return buf;
    } catch (e) {
      if (i === retries - 1) throw e;
      await new Promise(r => setTimeout(r, 2000));
    }
  }
  throw new Error("Download failed");
}

async function compose4koma(panelBuffers: Buffer[]): Promise<Buffer> {
  // 2×2 grid: 810×540 px
  const PW = 390, PH = 255, PAD = 10, GAP = 10;
  const W = PAD + PW + GAP + PW + PAD;   // 810
  const H = PAD + PH + GAP + PH + PAD;   // 540

  const positions = [
    { x: PAD, y: PAD },
    { x: PAD + PW + GAP, y: PAD },
    { x: PAD, y: PAD + PH + GAP },
    { x: PAD + PW + GAP, y: PAD + PH + GAP },
  ];

  const resized = await Promise.all(
    panelBuffers.map(buf => sharp(buf).resize(PW, PH, { fit: "cover" }).png().toBuffer())
  );

  return sharp({ create: { width: W, height: H, channels: 3, background: { r: 255, g: 255, b: 255 } } })
    .composite(resized.map((buf, i) => ({ input: buf, top: positions[i].y, left: positions[i].x })))
    .png()
    .toBuffer();
}

export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { theme, style } = await req.json();
  if (!theme || !style) {
    return NextResponse.json({ error: "theme と style は必須です" }, { status: 400 });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "ANTHROPIC_API_KEY が未設定です" }, { status: 500 });
  }

  const stream = new ReadableStream({
    async start(controller) {
      const enc = new TextEncoder();
      const send = (data: Record<string, unknown>) =>
        controller.enqueue(enc.encode(`data: ${JSON.stringify(data)}\n\n`));

      try {
        // Step 1: Story
        send({ log: "Step 1/3: ストーリーをClaudeで生成中...\n" });
        const client = new Anthropic({ apiKey });
        const response = await client.messages.create({
          model: "claude-haiku-4-5-20251001",
          max_tokens: 1024,
          system: SYSTEM_PROMPT,
          messages: [{ role: "user", content: buildStoryPrompt(theme) }],
        });
        const raw = response.content[0].type === "text" ? response.content[0].text.trim() : "";
        const jsonMatch = raw.match(/\{[\s\S]+\}/);
        if (!jsonMatch) throw new Error("Claude response has no JSON");
        const story: Story = JSON.parse(jsonMatch[0]);
        if (!Array.isArray(story.panels) || story.panels.length !== 4) {
          throw new Error(`Expected 4 panels, got ${story.panels?.length}`);
        }
        send({ log: `  タイトル: ${story.title}\n` });
        story.panels.forEach(p => send({ log: `  [${p.panel}] ${p.dialogue}\n` }));

        // Step 2: Images (parallel)
        send({ log: "\nStep 2/3: パネル画像を生成中（並行）...\n" });
        const baseSeed = Math.floor(Math.random() * 100000);
        story.panels.forEach(p => send({ log: `  Generating panel ${p.panel}/4...\n` }));
        const panelBuffers = await Promise.all(
          story.panels.map(async (panel) => {
            const url = buildImageUrl(panel, style, baseSeed + panel.panel);
            const buf = await downloadImage(url);
            send({ log: `    ✓ panel ${panel.panel} (${(buf.length / 1024).toFixed(1)}KB)\n` });
            return buf;
          })
        );

        // Step 3: Compose
        send({ log: "\nStep 3/3: Composing 4-panel image...\n" });
        const imageBuffer = await compose4koma(panelBuffers);
        const dataUrl = `data:image/png;base64,${imageBuffer.toString("base64")}`;

        send({ log: "✅ 完了！\n" });
        send({ done: true, code: 0, imagePath: dataUrl });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        send({ log: `❌ エラー: ${msg}\n` });
        send({ done: true, code: 1, imagePath: null });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
