import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function buildHtml(story, panelPaths) {
  const panels = story.panels.map((p, i) => {
    const imgB64 = fs.readFileSync(panelPaths[i]).toString('base64');
    const dialogue = escapeHtml(p.dialogue);
    const caption = escapeHtml(p.caption);
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
  body { background: white; font-family: 'Hiragino Sans', 'Noto Sans JP', 'Yu Gothic', sans-serif; }
  .wrapper { width: 800px; background: white; padding: 20px; }
  .title {
    text-align: center;
    font-size: 22px;
    font-weight: bold;
    color: #2d4a1e;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 3px solid #5a8a3c;
  }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .panel {
    border: 2px solid #333;
    border-radius: 8px;
    overflow: hidden;
    background: #fffdf5;
    position: relative;
  }
  .panel-num {
    position: absolute;
    top: 6px; left: 8px;
    background: #2d4a1e;
    color: white;
    font-size: 13px;
    font-weight: bold;
    width: 22px; height: 22px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
  }
  .img-wrap img { width: 100%; height: 220px; object-fit: cover; display: block; }
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
  <div class="title">${escapeHtml(story.title)}</div>
  <div class="grid">${panels}</div>
  <div class="footer">camp-gear-lab.com / @camp_gear_lab</div>
</div>
</body>
</html>`;
}

export async function compose4koma(story, panelPaths, outPath) {
  if (panelPaths.length !== story.panels.length) {
    throw new Error(`Panel count mismatch: ${panelPaths.length} paths vs ${story.panels.length} panels`);
  }

  const html = buildHtml(story, panelPaths);
  const htmlPath = outPath.replace(/\.png$/, '.html');
  fs.writeFileSync(htmlPath, html, 'utf-8');

  const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 840, height: 600 });
    await page.goto(`file://${htmlPath}`, { waitUntil: 'load' });
    await page.waitForSelector('.grid');

    const wrapper = await page.$('.wrapper');
    if (!wrapper) throw new Error('Wrapper element not found in HTML');
    await wrapper.screenshot({ path: outPath });
    console.log(`  ✓ Composed: ${outPath}`);
  } finally {
    await browser.close();
    try { fs.unlinkSync(htmlPath); } catch {}
  }

  return outPath;
}
