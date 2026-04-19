import https from 'https';
import fs from 'fs';
import path from 'path';

const DELAY_MS = 3500;
const MAX_RETRIES = 3;

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const CHARACTER_BASE = 'flat manga style, friendly Japanese man in outdoor cap and camping jacket, simple clean line art, white background, no text on image, no speech bubbles in image';

function buildPrompt(panel) {
  return `${CHARACTER_BASE}, ${panel.character_pose}, ${panel.scene}, panel ${panel.panel} of 4-panel comic`;
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

export async function generatePanelImages(story, outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const paths = [];
  // baseSeed is fixed per story so all panels stay in the same seed neighborhood,
  // improving character consistency slightly within a single 4-panel run
  const baseSeed = Math.floor(Math.random() * 100000);
  for (const panel of story.panels) {
    const prompt = buildPrompt(panel);
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
