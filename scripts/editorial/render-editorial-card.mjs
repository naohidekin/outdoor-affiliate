/** Offline owned-editorial illustration renderer. One JSON stdin/stdout pair. */
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash, randomBytes } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer';

const VERSION = 'editorial-illustration-v1';
const WIDTH = 1200, HEIGHT = 630, MAX_REQUEST = 64 * 1024;
const FONT = 'Arial, "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif';
const BADGE = 'キャンプのヒント';
const DISCLAIMER = 'Camp Gear Lab編集部の図解';
const fail = code => { throw new Error(code); };
const hash = value => createHash('sha256').update(value).digest('hex');
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;

export async function validateEditorialCardInput(raw) {
  const keys = ['heading', 'outputPath', 'sourceIds', 'sourceReceiptSha256', 'steps', 'title'].sort();
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || JSON.stringify(Object.keys(raw).sort()) !== JSON.stringify(keys)) fail('input_fields');
  const text = (value, max) => typeof value === 'string' && value.trim() === value && value.length > 0 && value.length <= max && !/[\u0000-\u001f]/.test(value);
  if (!text(raw.title, 120) || !text(raw.heading, 80) || !Array.isArray(raw.steps) || raw.steps.length < 3 || raw.steps.length > 5 ||
      !Array.isArray(raw.sourceIds) || raw.sourceIds.length < 1 || new Set(raw.sourceIds).size !== raw.sourceIds.length ||
      raw.sourceIds.some(id => !text(id, 120) || !id.startsWith('public:')) || !/^[a-f0-9]{64}$/.test(raw.sourceReceiptSha256 || '') ||
      !path.isAbsolute(raw.outputPath) || path.extname(raw.outputPath).toLowerCase() !== '.png') fail('input_contract');
  if (raw.steps.some(step => !step || typeof step !== 'object' || Array.isArray(step) ||
      JSON.stringify(Object.keys(step).sort()) !== JSON.stringify(['kind', 'text']) || step.kind !== 'editorial_outline' || !text(step.text, 40)))
    fail('step_binding');
  return structuredClone(raw);
}

function documentHtml(input) {
  const cards = input.steps.map((step, index) => `<li class="step"><span class="number">${index + 1}</span><span class="step-text">${escape(step.text)}</span></li>`).join('');
  return `<!doctype html><html lang="ja"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; connect-src 'none'; font-src 'none'"><style>
  *{box-sizing:border-box}html,body{margin:0;width:${WIDTH}px;height:${HEIGHT}px;font-family:${FONT};font-synthesis:none;-webkit-font-smoothing:antialiased;background:#f7f3e8;color:#17243a}
  main{position:relative;width:${WIDTH}px;height:${HEIGHT}px;overflow:hidden;background:linear-gradient(135deg,#f8f3e6 0%,#f8f3e6 55%,#e9efe8 55%,#e9efe8 100%)}
  .rail{position:absolute;left:0;top:0;width:18px;height:630px;background:#e66b3c}.brand{position:absolute;left:58px;top:38px;font-size:22px;font-weight:700;letter-spacing:1px;color:#31513f}
  .label{position:absolute;left:58px;top:86px;padding:8px 14px;border:2px solid #31513f;border-radius:999px;font-size:19px;font-weight:700;color:#31513f;background:#fffdf7}
  .title{position:absolute;left:58px;top:143px;width:455px;max-height:90px;font-size:31px;line-height:1.34;font-weight:700;color:#52615b;overflow:hidden}
  .heading{position:absolute;left:58px;top:245px;width:470px;height:184px;font-size:49px;line-height:1.22;font-weight:800;letter-spacing:.01em;color:#17243a;display:flex;align-items:center;overflow-wrap:anywhere}
  .disclaimer{position:absolute;left:58px;bottom:50px;width:470px;font-size:20px;line-height:1.4;font-weight:700;color:#695f51}
  .diagram{position:absolute;left:585px;top:48px;width:555px;height:534px;margin:0;padding:0;list-style:none;display:flex;flex-direction:column;justify-content:center;gap:14px}
  .step{position:relative;min-height:82px;width:555px;padding:17px 22px 17px 92px;border:2px solid #31513f;border-radius:18px;background:#fffdf7;display:flex;align-items:center;box-shadow:7px 7px 0 #cbd8ce}
  .step:not(:last-child)::after{content:'↓';position:absolute;left:35px;bottom:-22px;z-index:3;color:#e66b3c;font-size:24px;font-weight:900}
  .number{position:absolute;left:20px;top:50%;transform:translateY(-50%);width:50px;height:50px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#e66b3c;color:white;font-size:27px;font-weight:800}
  .step-text{font-size:29px;line-height:1.28;font-weight:800;color:#17243a;overflow-wrap:anywhere}
  </style></head><body><main><div class="rail"></div><div class="brand">Camp Gear Lab</div><div class="label">${BADGE}</div><div class="title">${escape(input.title)}</div><div class="heading">${escape(input.heading)}</div><div class="disclaimer">${DISCLAIMER}</div><ol class="diagram">${cards}</ol></main></body></html>`;
}

async function writePng(outputPath, png) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true, mode: 0o700 });
  try {
    const current = await fs.readFile(outputPath);
    if (hash(current) !== hash(png)) fail('output_exists');
    return;
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const temporary = path.join(path.dirname(outputPath), `.${randomBytes(12).toString('hex')}.png`);
  try {
    await fs.writeFile(temporary, png, { flag: 'wx', mode: 0o600 });
    await fs.link(temporary, outputPath);
  } finally { await fs.rm(temporary, { force: true }); }
}

export async function renderEditorialCard(raw) {
  const input = await validateEditorialCardInput(raw);
  const sourceBinding = { version: VERSION, title: input.title, heading: input.heading, steps: input.steps,
    sourceIds: input.sourceIds, sourceReceiptSha256: input.sourceReceiptSha256, badge: BADGE, disclaimer: DISCLAIMER };
  let browser, profile;
  try {
    profile = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-editorial-browser-'));
    browser = await puppeteer.launch({ headless: true, userDataDir: profile, timeout: 30000,
      env: { PATH: process.env.PATH || '/usr/bin:/bin', HOME: profile, TMPDIR: profile, TZ: 'Asia/Tokyo', LANG: 'ja_JP.UTF-8' },
      args: ['--disable-background-networking', '--disable-component-update', '--disable-default-apps', '--no-first-run', '--disable-sync'] });
    const page = await browser.newPage();
    await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
    await page.setRequestInterception(true);
    let networkRequests = 0;
    page.on('request', request => {
      if (request.url() === 'about:blank') request.continue();
      else { networkRequests++; request.abort(); }
    });
    await page.setContent(documentHtml(input), { waitUntil: 'load', timeout: 15000 });
    const layout = await page.evaluate(async () => {
      await document.fonts.ready;
      const rect = element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
      const heading = document.querySelector('.heading'), title = document.querySelector('.title');
      let headingFontSize = 49;
      while ((heading.scrollHeight > heading.clientHeight || heading.scrollWidth > heading.clientWidth) && headingFontSize > 42)
        heading.style.fontSize = --headingFontSize + 'px';
      if (heading.scrollHeight > heading.clientHeight || heading.scrollWidth > heading.clientWidth || title.scrollHeight > title.clientHeight) throw Error('text_overflow');
      const stepCards = [...document.querySelectorAll('.step')].map((card, index) => ({ index, text: card.querySelector('.step-text').textContent, ...rect(card) }));
      if (stepCards.some(card => card.x < 585 || card.right > 1140 || card.y < 48 || card.bottom > 582)) throw Error('diagram_overflow');
      return { headingFontSize, titleFontSize: 31, stepFontSize: 29, heading: rect(heading), title: rect(title), stepCards };
    });
    if (networkRequests !== 0 || layout.stepCards.map(item => item.text).join('\n') !== input.steps.map(item => item.text).join('\n')) fail('render_evidence_mismatch');
    const png = Buffer.from(await page.screenshot({ type: 'png', clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT } }));
    await writePng(input.outputPath, png);
    return { passed: true, evidencePassed: true, version: VERSION, width: WIDTH, height: HEIGHT, outputPath: input.outputPath,
      pngSha256: hash(png), bytes: png.length, contentHash: hash(JSON.stringify(stable(sourceBinding))),
      displayText: { title: input.title, heading: input.heading, steps: input.steps, brand: 'Camp Gear Lab', badge: BADGE, disclaimer: DISCLAIMER },
      layout, renderer: { engine: await browser.version(), platform: process.platform, fontFamily: FONT }, networkRequests,
      sourceIds: input.sourceIds, sourceReceiptSha256: input.sourceReceiptSha256 };
  } finally {
    if (browser) await browser.close();
    if (profile) await fs.rm(profile, { recursive: true, force: true });
  }
}

async function main() {
  try {
    let input = '';
    for await (const chunk of process.stdin) { input += chunk; if (Buffer.byteLength(input) > MAX_REQUEST) fail('request_oversized'); }
    process.stdout.write(JSON.stringify(await renderEditorialCard(JSON.parse(input))) + '\n');
  } catch {
    process.stdout.write(JSON.stringify({ passed: false, evidencePassed: false, error: 'editorial_card_render_failed' }) + '\n');
    process.exitCode = 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
