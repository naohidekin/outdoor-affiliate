/**
 * 4コマ漫画自動生成CLI
 *
 * 使い方:
 *   node scripts/generate-4koma.mjs                        # デフォルトテーマで1本
 *   node scripts/generate-4koma.mjs --theme="焚き火の失敗" # テーマ指定
 *   node scripts/generate-4koma.mjs --count=3              # 複数本生成
 *   node scripts/generate-4koma.mjs --dry-run              # ストーリー生成のみ（画像なし）
 */

import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
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
import { generatePanelImages, STYLE_KEYS } from './4koma/panel-generator.mjs';
import { compose4koma } from './4koma/composer.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const DEFAULT_THEMES = [
  'キャンプ飯の失敗',
  '焚き火で失敗',
  'テント設営あるある',
  '道具を買いすぎた',
  '子供とキャンプ',
  '雨キャンプの洗礼',
  'ギア収納の悩み',
];

async function generateOne(theme, outBaseDir, dryRun, style = 'painting') {
  console.log(`\n🎨 Theme: "${theme}"`);

  console.log('Step 1/3: Generating story with Claude...');
  const story = await generate4komaStory(theme);
  console.log(`  Title: ${story.title}`);
  story.panels.forEach(p => console.log(`  [${p.panel}] ${p.dialogue}`));

  if (dryRun) {
    console.log('\n[dry-run] Story JSON:');
    console.log(JSON.stringify(story, null, 2));
    return null;
  }

  const slug = theme.replace(/[^\w\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf]/g, '-').replace(/-+/g, '-').slice(0, 30);
  const date = new Date().toISOString().slice(0, 10);
  const outPath = path.join(outBaseDir, `${date}-${slug}-${style}.png`);
  const panelDir = path.join(os.tmpdir(), `4koma-panels-${slug}-${Date.now()}`);

  console.log(`Step 2/3: Generating panel images [style: ${style}]...`);
  const panelPaths = await generatePanelImages(story, panelDir, style);

  console.log('Step 3/3: Composing 4-panel image...');
  await compose4koma(story, panelPaths, outPath);

  fs.rmSync(panelDir, { recursive: true, force: true });
  console.log(`✅ Done: ${outPath}`);
  return outPath;
}

async function run() {
  const args = process.argv.slice(2);
  const themeArg = args.find(a => a.startsWith('--theme='))?.split('=').slice(1).join('=');
  const countArg = parseInt(args.find(a => a.startsWith('--count='))?.split('=')[1] ?? '1');
  const styleArg = args.find(a => a.startsWith('--style='))?.split('=')[1] ?? 'painting';
  const dryRun = args.includes('--dry-run');

  if (!STYLE_KEYS.includes(styleArg)) {
    console.error(`❌ Unknown style: "${styleArg}". Available: ${STYLE_KEYS.join(', ')}`);
    process.exit(1);
  }

  const themes = themeArg ? [themeArg] : DEFAULT_THEMES.slice(0, countArg);
  const outBaseDir = path.join(__dirname, '../public/images/4koma');
  fs.mkdirSync(outBaseDir, { recursive: true });

  const results = [];
  for (const theme of themes) {
    const outPath = await generateOne(theme, outBaseDir, dryRun, styleArg);
    if (outPath) results.push(outPath);
  }

  if (results.length > 0) {
    console.log(`\n🎉 Generated ${results.length} 4コマ manga:`);
    results.forEach(p => console.log(`  ${p}`));
  }
}

run().catch(err => { console.error('❌', err.message); process.exit(1); });
