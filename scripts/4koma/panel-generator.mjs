import https from 'https';
import fs from 'fs';
import path from 'path';

const DELAY_MS = 3500;
const MAX_RETRIES = 3;

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const STYLES = {
  painting: 'soft manga illustration, gentle watercolor shading, warm pastel tones, friendly Japanese man in outdoor cap and camping jacket, character fills most of the frame, medium shot centered on character, background simple and blurred, white background, no text, no speech bubbles',
  flat:     'flat vector illustration, clean bold line art, earth tones green brown orange, friendly Japanese man in outdoor cap and camping jacket, character centered, simple background, white background, no text, no speech bubbles',
  sketch:   'pencil sketch manga style, rough expressive hand-drawn lines, light hatching, monochrome with soft grey tones, friendly Japanese man in outdoor cap, character fills frame, minimal background, no text, no speech bubbles',
  chibi:    'cute chibi manga style, big round eyes, rounded simplified body, bright cheerful colors, friendly Japanese man in outdoor cap and camping jacket, character large in frame, simple pastel background, no text, no speech bubbles',
  retro:    'retro 1980s Japanese manga style, bold thick ink lines, screen tone dot shading, high contrast black and white, friendly Japanese man in outdoor cap, expressive exaggerated emotions, character prominent, no text, no speech bubbles',
  webtoon:  'modern webtoon style, clean digital line art, soft color gradients, bright warm palette, friendly Japanese man in outdoor cap and camping jacket, character centered and fills frame, simple clean background, no text, no speech bubbles',
  manga:    'classic Japanese manga style, bold clean ink lines, strong black outlines, cel-shading, high contrast black and white with spot color, expressive character art, friendly Japanese man in outdoor cap and camping jacket, character fills frame, minimal background, no text, no speech bubbles',
};

export const STYLE_KEYS = Object.keys(STYLES);

function buildPrompt(panel, style = 'painting') {
  const base = STYLES[style] ?? STYLES.painting;
  return `${base}, ${panel.character_pose}, simple ${panel.scene}, character prominent in frame`;
}

async function downloadPanel(url, outPath, itemName, retries = 0) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(outPath);
    https.get(url, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        file.close();
        try { fs.unlinkSync(outPath); } catch {}
        if (retries < MAX_RETRIES) {
          console.log(`    [retry ${retries + 1}] panel ${itemName} (HTTP ${res.statusCode})`);
          sleep(DELAY_MS * 2).then(() => resolve(downloadPanel(url, outPath, itemName, retries + 1)));
        } else {
          reject(new Error(`HTTP ${res.statusCode}: panel ${itemName}`));
        }
        return;
      }
      res.pipe(file);
      file.on('finish', async () => {
        file.close();
        try {
          const stat = fs.statSync(outPath);
          if (stat.size < 2000) {
            fs.unlinkSync(outPath);
            if (retries < MAX_RETRIES) {
              console.log(`    [retry ${retries + 1}] panel ${itemName} (too small: ${stat.size}B)`);
              await sleep(DELAY_MS * 2);
              resolve(downloadPanel(url, outPath, itemName, retries + 1));
            } else {
              reject(new Error(`Panel download failed after retries: ${itemName}`));
            }
          } else {
            resolve(stat.size);
          }
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', async (err) => {
      file.close();
      if (retries < MAX_RETRIES) {
        console.log(`    [retry ${retries + 1}] panel ${itemName} (${err.message})`);
        await sleep(DELAY_MS * 2);
        resolve(downloadPanel(url, outPath, itemName, retries + 1));
      } else {
        reject(err);
      }
    });
  });
}

export async function generatePanelImages(story, outDir, style = 'painting') {
  fs.mkdirSync(outDir, { recursive: true });
  const paths = [];
  // baseSeed is fixed per story so all panels stay in the same seed neighborhood,
  // improving character consistency slightly within a single 4-panel run
  const baseSeed = Math.floor(Math.random() * 100000);
  for (const panel of story.panels) {
    const prompt = buildPrompt(panel, style);
    const encoded = encodeURIComponent(prompt);
    const seed = baseSeed + panel.panel;
    const url = `https://image.pollinations.ai/prompt/${encoded}?width=512&height=512&seed=${seed}&nologo=true&model=flux`;
    const outPath = path.join(outDir, `panel-${panel.panel}.png`);
    console.log(`  [${panel.panel}/4] Generating panel...`);
    try {
      const size = await downloadPanel(url, outPath, panel.panel);
      console.log(`    ✓ panel-${panel.panel}.png (${(size / 1024).toFixed(1)}KB)`);
    } catch (err) {
      console.error(`    ✗ panel-${panel.panel} failed: ${err.message}`);
      throw err;
    }
    paths.push(outPath);
    if (panel.panel < story.panels.length) await sleep(DELAY_MS);
  }
  return paths;
}
