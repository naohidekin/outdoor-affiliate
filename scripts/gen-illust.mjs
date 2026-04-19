import https from 'https';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DELAY_MS = 3000;
const MAX_RETRIES = 3;

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function downloadImage(item, outDir, retries = 0) {
  const encoded = encodeURIComponent(item.prompt);
  const seed = Math.floor(Math.random() * 9999);
  const url = `https://image.pollinations.ai/prompt/${encoded}?width=${item.width ?? 512}&height=${item.height ?? 512}&seed=${seed}&nologo=true&model=flux`;
  const outPath = path.join(outDir, `${item.name}.png`);

  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(outPath);
    https.get(url, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        file.close();
        try { fs.unlinkSync(outPath); } catch {}
        const err = new Error(`HTTP ${res.statusCode}: ${item.name}`);
        if (retries < MAX_RETRIES) {
          console.log(`  [retry ${retries + 1}] ${item.name} (HTTP ${res.statusCode})`);
          sleep(DELAY_MS * 2).then(() => resolve(downloadImage(item, outDir, retries + 1)));
        } else {
          reject(err);
        }
        return;
      }
      res.pipe(file);
      file.on('finish', async () => {
        file.close();
        try {
          const stat = fs.statSync(outPath);
          if (stat.size < 1000) {
            fs.unlinkSync(outPath);
            if (retries < MAX_RETRIES) {
              console.log(`  [retry ${retries + 1}] ${item.name} (file too small: ${stat.size}B)`);
              await sleep(DELAY_MS * 2);
              resolve(downloadImage(item, outDir, retries + 1));
            } else {
              reject(new Error(`Failed after ${MAX_RETRIES} retries: ${item.name}`));
            }
          } else {
            resolve({ name: item.name, path: outPath, size: stat.size });
          }
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', async (err) => {
      file.close();
      if (retries < MAX_RETRIES) {
        console.log(`  [retry ${retries + 1}] ${item.name} (${err.message})`);
        await sleep(DELAY_MS * 2);
        resolve(downloadImage(item, outDir, retries + 1));
      } else {
        reject(err);
      }
    });
  });
}

export async function generateIllustrations(images, outDir = '/tmp') {
  fs.mkdirSync(outDir, { recursive: true });
  const results = [];
  for (const [i, item] of images.entries()) {
    console.log(`[${i + 1}/${images.length}] Generating: ${item.name}`);
    try {
      const result = await downloadImage(item, outDir);
      console.log(`  ✓ ${result.name} (${(result.size / 1024).toFixed(1)}KB)`);
      results.push(result);
    } catch (err) {
      console.error(`  ✗ Failed: ${item.name} — ${err.message}`);
      throw err;
    }
    if (i < images.length - 1) await sleep(DELAY_MS);
  }
  return results;
}

// CLI直接実行
const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const IMAGES = [
    { name: 'x-fire-tips', prompt: 'flat illustration, friendly Japanese man in outdoor cap showing campfire tips, holding firewood, happy expression, campfire beside him, vector art, warm orange tones, white background, no text, sticker style' },
    { name: 'x-tent-tips', prompt: 'flat illustration, Japanese man in outdoor cap setting up tent, smiling, forest background, clean vector art, earth tones, white background, no text' },
    { name: 'x-gear-review', prompt: 'flat illustration, camping gear layout flatlay, tent sleeping bag lantern cookware, top view, clean vector style, earth tones green brown, white background, no text' },
    { name: 'x-cooking', prompt: 'flat illustration, Japanese man cooking outdoor meal on camp stove, smiling, steam rising, forest background, clean vector art, warm colors, white background, no text' },
    { name: 'article-campsite', prompt: 'wide flat illustration, cozy campsite at dusk, tent with lantern glow, trees, campfire, camping chairs, family scene, vector art, warm sunset colors, horizontal banner style, no text', width: 800, height: 400 },
    { name: 'article-family', prompt: 'flat illustration, Japanese family camping together, father mother child, campfire, smiling, forest setting, clean vector art, warm earth tones, wide scene, no text', width: 800, height: 400 },
    { name: 'article-gear-header', prompt: 'flat illustration, horizontal banner, various outdoor camping gear icons, tent lantern boots compass backpack, arranged neatly, vector style, earthy green brown colors, white background, no text', width: 800, height: 400 },
  ];

  const outDir = process.argv[2] ?? '/tmp/illust-output';
  console.log(`Output dir: ${outDir}`);
  generateIllustrations(IMAGES, outDir)
    .then(res => console.log(`\n✅ Done: ${res.length} images`))
    .catch(err => { console.error('❌', err.message); process.exit(1); });
}
