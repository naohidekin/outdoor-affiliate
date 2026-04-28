# 4コマ漫画 & イラスト生成パイプライン実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** outdoor-affiliateのX投稿・ブログ記事用に、Claude APIで4コマストーリーを自動生成し、Pollinations AIで画像化、PuppeteerでHTML合成して1枚のPNGを出力するパイプラインを構築する。あわせて汎用イラスト生成スクリプトも実装する。

**Architecture:** ①シーケンシャルイラスト生成（gen-illust.mjs）でPollinationsのレート制限を回避、②4コマ生成はClaude API→Pollinations AI（各パネル逐次）→Puppeteer HTML合成の3ステップパイプライン（generate-4koma.mjs）とする。画像合成はsharp/canvas不要でPuppeteerのみ使用する。

**Tech Stack:** Node.js v25 / ESM / @anthropic-ai/sdk / Puppeteer（既存）/ Pollinations AI（無料API）/ .env.local（ANTHROPIC_API_KEY）

---

## File Map

| ファイル | 役割 |
|---|---|
| `scripts/gen-illust.mjs` | 汎用イラスト生成（B案：逐次処理・リトライ付き） |
| `scripts/generate-4koma.mjs` | 4コマ生成メインCLI（A案オーケストレーター） |
| `scripts/4koma/story-generator.mjs` | Claude API → 4パネルストーリーJSON |
| `scripts/4koma/panel-generator.mjs` | Pollinations AI → パネル画像（逐次） |
| `scripts/4koma/composer.mjs` | Puppeteer HTML → 4コマ合成PNG |
| `public/images/4koma/` | 出力先ディレクトリ |

---

## Task 1: 汎用イラスト生成スクリプト（B案）

**Files:**
- Create: `scripts/gen-illust.mjs`

- [ ] **Step 1: scriptsディレクトリを確認**

```bash
ls ~/Desktop/AI関連/claude/outdoor-affiliate/scripts/ | grep -E 'gen|illust'
```

- [ ] **Step 2: gen-illust.mjsを作成**

```javascript
// scripts/gen-illust.mjs
import https from 'https';
import fs from 'fs';
import path from 'path';

const DELAY_MS = 3000; // Pollinations anonymous tier: 1 req/queue
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
      res.pipe(file);
      file.on('finish', async () => {
        file.close();
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
    const result = await downloadImage(item, outDir);
    console.log(`  ✓ ${result.name} (${(result.size / 1024).toFixed(1)}KB)`);
    results.push(result);
    if (i < images.length - 1) await sleep(DELAY_MS);
  }
  return results;
}

// CLI直接実行
if (process.argv[1].endsWith('gen-illust.mjs')) {
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
```

- [ ] **Step 3: 動作確認（2枚のみ）**

```bash
cd ~/Desktop/AI関連/claude/outdoor-affiliate
node scripts/gen-illust.mjs /tmp/illust-test
```

Expected: `/tmp/illust-test/x-fire-tips.png`と`x-tent-tips.png`が生成される（各ファイル>10KB）。続きはCtrl+Cで止めてよい。

- [ ] **Step 4: コミット**

```bash
cd ~/Desktop/AI関連/claude/outdoor-affiliate
git add scripts/gen-illust.mjs
git commit -m "feat: add sequential illustration generator with retry (gen-illust.mjs)"
```

---

## Task 2: 4コマストーリー生成（Claude API）

**Files:**
- Create: `scripts/4koma/story-generator.mjs`

- [ ] **Step 1: 4komaディレクトリ作成**

```bash
mkdir -p ~/Desktop/AI関連/claude/outdoor-affiliate/scripts/4koma
```

- [ ] **Step 2: story-generator.mjsを作成**

```javascript
// scripts/4koma/story-generator.mjs
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

必ずJSON形式で返してください。`;

export async function generate4komaStory(theme) {
  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    messages: [{
      role: 'user',
      content: `テーマ「${theme}」で4コマ漫画のストーリーをJSONで生成してください。

JSON形式:
{
  "title": "4コマのタイトル",
  "theme": "${theme}",
  "panels": [
    {
      "panel": 1,
      "scene": "背景・状況の説明（Pollinations AIへの英語プロンプトで使用）",
      "character_pose": "キャラクターのポーズ・表情（英語）",
      "dialogue": "セリフ（日本語、20文字以内）",
      "caption": "コマのキャプション（日本語、15文字以内、なければnull）"
    },
    { "panel": 2, ... },
    { "panel": 3, ... },
    { "panel": 4, ... }
  ]
}`
    }]
  });

  const text = response.content[0].text;
  const match = text.match(/\{[\s\S]+\}/);
  if (!match) throw new Error('No JSON found in response');
  return JSON.parse(match[0]);
}

// CLI直接実行
if (process.argv[1].endsWith('story-generator.mjs')) {
  const theme = process.argv[2] ?? 'キャンプ飯の失敗';
  console.log(`Generating story for theme: "${theme}"...`);
  generate4komaStory(theme)
    .then(story => console.log(JSON.stringify(story, null, 2)))
    .catch(err => { console.error('❌', err.message); process.exit(1); });
}
```

- [ ] **Step 3: 動作確認**

```bash
cd ~/Desktop/AI関連/claude/outdoor-affiliate
node scripts/4koma/story-generator.mjs "焚き火の失敗"
```

Expected: 4パネルのJSONが出力される。`panels`配列に`dialogue`・`scene`・`character_pose`が含まれること。

- [ ] **Step 4: コミット**

```bash
git add scripts/4koma/story-generator.mjs
git commit -m "feat: add 4koma story generator using Claude API"
```

---

## Task 3: パネル画像生成（Pollinations AI・逐次）

**Files:**
- Create: `scripts/4koma/panel-generator.mjs`

- [ ] **Step 1: panel-generator.mjsを作成**

```javascript
// scripts/4koma/panel-generator.mjs
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

async function downloadPanel(url, outPath, retries = 0) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(outPath);
    https.get(url, (res) => {
      res.pipe(file);
      file.on('finish', async () => {
        file.close();
        const stat = fs.statSync(outPath);
        if (stat.size < 2000) {
          fs.unlinkSync(outPath);
          if (retries < MAX_RETRIES) {
            await sleep(DELAY_MS * 2);
            resolve(downloadPanel(url, outPath, retries + 1));
          } else {
            reject(new Error(`Panel download failed after retries: ${outPath}`));
          }
        } else {
          resolve(stat.size);
        }
      });
    }).on('error', reject);
  });
}

export async function generatePanelImages(story, outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const paths = [];
  for (const panel of story.panels) {
    const prompt = buildPrompt(panel);
    const encoded = encodeURIComponent(prompt);
    const seed = panel.panel * 1000 + Math.floor(Math.random() * 100);
    const url = `https://image.pollinations.ai/prompt/${encoded}?width=512&height=512&seed=${seed}&nologo=true&model=flux`;
    const outPath = path.join(outDir, `panel-${panel.panel}.png`);
    console.log(`  [panel ${panel.panel}/4] Generating...`);
    await downloadPanel(url, outPath);
    console.log(`  ✓ panel-${panel.panel}.png`);
    paths.push(outPath);
    if (panel.panel < 4) await sleep(DELAY_MS);
  }
  return paths;
}
```

- [ ] **Step 2: コミット**

```bash
git add scripts/4koma/panel-generator.mjs
git commit -m "feat: add 4koma panel image generator (sequential Pollinations AI)"
```

---

## Task 4: Puppeteer HTML合成（4コマ → 1枚PNG）

**Files:**
- Create: `scripts/4koma/composer.mjs`

- [ ] **Step 1: composer.mjsを作成**

```javascript
// scripts/4koma/composer.mjs
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

function buildHtml(story, panelPaths) {
  const panels = story.panels.map((p, i) => {
    const imgB64 = fs.readFileSync(panelPaths[i]).toString('base64');
    const dialogue = p.dialogue ? p.dialogue.replace(/"/g, '&quot;').replace(/</g, '&lt;') : '';
    const caption = p.caption ? p.caption.replace(/"/g, '&quot;').replace(/</g, '&lt;') : '';
    return `
      <div class="panel">
        <div class="panel-num">${p.panel}</div>
        <div class="img-wrap">
          <img src="data:image/png;base64,${imgB64}" alt="panel ${p.panel}" />
        </div>
        ${dialogue ? `<div class="dialogue">${dialogue}</div>` : ''}
        ${caption ? `<div class="caption">${caption}</div>` : ''}
      </div>`;
  }).join('');

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: white; font-family: 'Hiragino Sans', 'Noto Sans JP', sans-serif; }
  .wrapper {
    width: 800px;
    background: white;
    padding: 20px;
  }
  .title {
    text-align: center;
    font-size: 22px;
    font-weight: bold;
    color: #2d4a1e;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 3px solid #5a8a3c;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .panel {
    border: 2px solid #333;
    border-radius: 8px;
    overflow: hidden;
    background: #fffdf5;
    position: relative;
  }
  .panel-num {
    position: absolute;
    top: 6px;
    left: 8px;
    background: #2d4a1e;
    color: white;
    font-size: 13px;
    font-weight: bold;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
  }
  .img-wrap img {
    width: 100%;
    height: 220px;
    object-fit: cover;
    display: block;
  }
  .dialogue {
    background: white;
    border-top: 1px solid #ddd;
    padding: 8px 10px;
    font-size: 15px;
    font-weight: bold;
    color: #222;
    text-align: center;
    min-height: 36px;
  }
  .caption {
    background: #f0f5eb;
    padding: 4px 8px;
    font-size: 12px;
    color: #555;
    text-align: center;
  }
  .footer {
    text-align: right;
    font-size: 11px;
    color: #999;
    margin-top: 10px;
  }
</style>
</head>
<body>
<div class="wrapper">
  <div class="title">${story.title}</div>
  <div class="grid">${panels}</div>
  <div class="footer">camp-gear-lab.com / @camp_gear_lab</div>
</div>
</body>
</html>`;
}

export async function compose4koma(story, panelPaths, outPath) {
  const html = buildHtml(story, panelPaths);
  const htmlPath = outPath.replace('.png', '.html');
  fs.writeFileSync(htmlPath, html, 'utf-8');

  const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 840, height: 10 });
  await page.goto(`file://${htmlPath}`);
  await page.waitForSelector('.grid');

  const wrapper = await page.$('.wrapper');
  await wrapper.screenshot({ path: outPath });
  await browser.close();

  fs.unlinkSync(htmlPath);
  console.log(`  ✓ Composed: ${outPath}`);
  return outPath;
}
```

- [ ] **Step 2: コミット**

```bash
git add scripts/4koma/composer.mjs
git commit -m "feat: add 4koma composer using Puppeteer HTML screenshot"
```

---

## Task 5: メインCLIオーケストレーター

**Files:**
- Create: `scripts/generate-4koma.mjs`
- Create: `public/images/4koma/.gitkeep`

- [ ] **Step 1: 出力ディレクトリ作成**

```bash
mkdir -p ~/Desktop/AI関連/claude/outdoor-affiliate/public/images/4koma
touch ~/Desktop/AI関連/claude/outdoor-affiliate/public/images/4koma/.gitkeep
```

- [ ] **Step 2: generate-4koma.mjsを作成**

```javascript
// scripts/generate-4koma.mjs
import { readFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import os from 'os';
import fs from 'fs';

function loadEnv() {
  const envPath = path.join(path.dirname(fileURLToPath(import.meta.url)), '../.env.local');
  try {
    const lines = readFileSync(envPath, 'utf-8').split('\n');
    for (const line of lines) {
      const [k, ...v] = line.split('=');
      if (k && v.length && !process.env[k]) process.env[k] = v.join('=').trim();
    }
  } catch {}
}
loadEnv();

import { generate4komaStory } from './4koma/story-generator.mjs';
import { generatePanelImages } from './4koma/panel-generator.mjs';
import { compose4koma } from './4koma/composer.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function run() {
  const args = process.argv.slice(2);
  const themeArg = args.find(a => a.startsWith('--theme='))?.split('=')[1];
  const countArg = parseInt(args.find(a => a.startsWith('--count='))?.split('=')[1] ?? '1');
  const dryRun = args.includes('--dry-run');

  const THEMES = [
    'キャンプ飯の失敗',
    '焚き火で失敗',
    'テント設営あるある',
    '道具を買いすぎた',
    '子供とキャンプ',
    '雨キャンプの洗礼',
    'ギア収納の悩み',
  ];

  const themes = themeArg
    ? [themeArg]
    : THEMES.slice(0, countArg);

  const outBaseDir = path.join(__dirname, '../public/images/4koma');
  const tmpDir = path.join(os.tmpdir(), '4koma-panels');

  for (const theme of themes) {
    console.log(`\n🎨 Theme: "${theme}"`);
    console.log('Step 1/3: Generating story with Claude...');
    const story = await generate4komaStory(theme);
    console.log(`  Title: ${story.title}`);

    const slug = theme.replace(/[^\w\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf]/g, '-').slice(0, 30);
    const date = new Date().toISOString().slice(0, 10);
    const outPath = path.join(outBaseDir, `${date}-${slug}.png`);
    const panelDir = path.join(tmpDir, slug);

    if (dryRun) {
      console.log('  [dry-run] Story JSON:');
      console.log(JSON.stringify(story, null, 2));
      continue;
    }

    console.log('Step 2/3: Generating panel images...');
    const panelPaths = await generatePanelImages(story, panelDir);

    console.log('Step 3/3: Composing 4-panel image...');
    await compose4koma(story, panelPaths, outPath);

    // Cleanup temp panels
    fs.rmSync(panelDir, { recursive: true, force: true });
    console.log(`✅ Done: ${outPath}`);
  }
}

run().catch(err => { console.error('❌', err.message); process.exit(1); });
```

- [ ] **Step 3: エンドツーエンド動作確認（dry-run）**

```bash
cd ~/Desktop/AI関連/claude/outdoor-affiliate
node scripts/generate-4koma.mjs --theme="焚き火の失敗" --dry-run
```

Expected: Claude APIが呼ばれ、4パネルのJSONが表示される。画像生成はスキップ。

- [ ] **Step 4: 本番実行（1コマ）**

```bash
node scripts/generate-4koma.mjs --theme="焚き火の失敗"
```

Expected: `public/images/4koma/2026-04-19-焚き火の失敗.png` が生成される（800px幅の4コマ画像）。

- [ ] **Step 5: 生成画像確認**

```bash
ls -la ~/Desktop/AI関連/claude/outdoor-affiliate/public/images/4koma/
open ~/Desktop/AI関連/claude/outdoor-affiliate/public/images/4koma/*.png
```

Expected: 4コマ漫画のPNGが開き、2x2グリッドにパネル・セリフ・タイトルが含まれること。

- [ ] **Step 6: 全ファイルをコミット**

```bash
cd ~/Desktop/AI関連/claude/outdoor-affiliate
git add scripts/generate-4koma.mjs scripts/4koma/ public/images/4koma/
git commit -m "feat: add 4koma manga generator pipeline (Claude API + Pollinations AI + Puppeteer)"
```

---

## セルフレビュー

### Spec Coverage
- [x] B案: 逐次イラスト生成・リトライ付き → Task 1
- [x] A案: Claude APIストーリー生成 → Task 2
- [x] A案: Pollinations AIパネル生成（逐次） → Task 3
- [x] A案: Puppeteer HTML→PNG合成 → Task 4
- [x] CLI統合・dry-run対応 → Task 5

### Known Limitations
- Pollinations AI anonymous tierは1リクエスト/キュー制限 → 逐次処理で対応済み
- パネル画像のキャラクター一貫性はモデル側に依存（毎回異なる可能性あり）
- 日本語フォントはシステムフォント依存（`Hiragino Sans`はmacOSのみ）
- Puppeteerの`headless: 'new'`はPuppeteer v20以降で有効
