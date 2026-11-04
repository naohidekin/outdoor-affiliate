/** Offline Lake & Sky social-card renderer. No Next server, remote resources or model calls.
 * stdin: {title, heading?, label?, products:[{name,dataUrl,sha256,verified:true}],outputPath}
 * One or two verified raster photographs; explicit absolute PNG output. Result is
 * a manifest on stdout, not an upload. A long title requires a supplied shorter
 * approved heading: this renderer never summarizes claims or silently truncates.
 * Pixel reproducibility assumes the same recorded Chromium/platform/font profile.
 */
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash, randomBytes } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer';
import sharp from 'sharp';

export const VERSION = 'lake-sky-social-card-v2';
const WIDTH = 1200, HEIGHT = 630, MAX_IMAGE = 8 * 1024 * 1024, MAX_REQUEST = 24 * 1024 * 1024;
const FONT = '"Hiragino Sans", "Noto Sans CJK JP", "Noto Sans JP", sans-serif';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = code => { throw new Error(code); };
const escape = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function text(value, max, code, optional = false) {
  if (optional && value === undefined) return '';
  if (typeof value !== 'string' || !value.trim() || value !== value.trim() || [...value].length > max ||
      /[\x00-\x1f\x7f]/.test(value)) fail(code);
  return value;
}
function decodePhoto(product) {
  if (!product || typeof product !== 'object' || product.verified !== true) fail('product_verification_required');
  const name = text(product.name, 90, 'product_name_invalid');
  if (typeof product.dataUrl !== 'string' || product.dataUrl.length > MAX_IMAGE * 4 / 3 + 100) fail('product_data_invalid');
  const match = /^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(product.dataUrl);
  if (!match) fail('product_data_invalid');
  const bytes = Buffer.from(match[2], 'base64');
  if (bytes.length < 32 || bytes.length > MAX_IMAGE || bytes.toString('base64') !== match[2]) fail('product_data_invalid');
  if (!/^[0-9a-f]{64}$/.test(product.sha256 ?? '') || sha(bytes) !== product.sha256) fail('product_hash_mismatch');
  return { name, bytes, mime: match[1], sha256: product.sha256 };
}
export async function validateInput(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      Object.keys(input).some(key => !['title', 'heading', 'label', 'products', 'outputPath'].includes(key))) fail('request_invalid');
  const title = text(input.title, 240, 'title_invalid');
  const parts = title.split('｜');
  const sourcedHeading = parts.length === 2 && parts.every(part => part.trim()) ? parts[1] : title;
  const heading = text(input.heading ?? sourcedHeading, 72, 'heading_requires_short_approved_input');
  const label = text(input.label, 24, 'label_invalid', true);
  if (!Array.isArray(input.products) || input.products.length < 1 || input.products.length > 2) fail('product_count_invalid');
  for (const product of input.products) decodePhoto(product);
  if (typeof input.outputPath !== 'string' || !path.isAbsolute(input.outputPath) ||
      !input.outputPath.endsWith('.png') || /[\x00-\x1f]/.test(input.outputPath)) fail('output_path_invalid');
  return { title, heading, label, products: input.products, outputPath: path.normalize(input.outputPath) };
}

export async function preparePhoto(product) {
  const decoded = decodePhoto(product);
  const processor = sharp(decoded.bytes, { limitInputPixels: 16_000_000, animated: false, failOn: 'warning' });
  const metadata = await processor.metadata();
  if (metadata.format !== decoded.mime || metadata.pages > 1 || !metadata.width || !metadata.height ||
      metadata.width > 10000 || metadata.height > 10000) fail('product_raster_invalid');
  // Auto-orient according to metadata, then trim ONLY exactly white/transparent
  // border pixels. Every non-white pixel remains, with additional white margin.
  const { data, info } = await processor.rotate().ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  let left = info.width, right = -1, top = info.height, bottom = -1;
  for (let y = 0; y < info.height; y++) for (let x = 0; x < info.width; x++) {
    const i = (y * info.width + x) * 4;
    if (data[i + 3] !== 0 && (data[i] !== 255 || data[i + 1] !== 255 || data[i + 2] !== 255)) {
      left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
    }
  }
  if (right < left || bottom < top) fail('product_empty_photo');
  const padding = Math.max(16, Math.ceil(Math.max(right - left + 1, bottom - top + 1) * .045));
  left = Math.max(0, left - padding); top = Math.max(0, top - padding);
  right = Math.min(info.width - 1, right + padding); bottom = Math.min(info.height - 1, bottom + padding);
  const crop = { left, top, width: right - left + 1, height: bottom - top + 1 };
  const cropped = await sharp(data, { raw: { width: info.width, height: info.height, channels: 4 } })
    .extract(crop).png({ compressionLevel: 9 }).toBuffer();
  return { name: decoded.name, sha256: decoded.sha256, size: decoded.bytes.length,
    originalWidth: metadata.width, originalHeight: metadata.height, crop,
    displaySha256: sha(cropped), dataUrl: 'data:image/png;base64,' + cropped.toString('base64') };
}
function nameMarkup(name) {
  // Preserve literal spaces and the complete source tokens; Japanese product
  // words and model codes may wrap between tokens, never inside a token.
  return name.split(/(\s+)/).map(part => /^\s*$/.test(part) ? escape(part) :
    `<span class="model-token">${escape(part)}</span>`).join('');
}
function html(input, photos) {
  const count = photos.length;
  const images = photos.map((photo, index) => {
    const slotWidth = count === 1 ? 572 : 278, slotHeight = 520;
    const scale = Math.min(slotWidth / photo.crop.width, slotHeight / photo.crop.height);
    const width = photo.crop.width * scale, height = photo.crop.height * scale;
    const centerX = count === 1 ? 888 : 728 + index * 300;
    return `<img class="photo" src="${photo.dataUrl}" alt="${escape(photo.name)}" style="left:${centerX - width / 2}px;top:${(HEIGHT - height) / 2}px;width:${width}px;height:${height}px">`;
  }).join('');
  const heading = input.heading.split(/(?<=[・と])/).map(part => `<span class="phrase">${escape(part)}</span>`).join('');
  return `<!doctype html><html lang="ja"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'none'; font-src 'none'; connect-src 'none'"><style>
  *{box-sizing:border-box}html,body{margin:0;width:1200px;height:630px;background:#fff;font-family:${FONT};font-synthesis:none;-webkit-font-smoothing:antialiased}
  #card{position:relative;width:1200px;height:630px;background:#fff;overflow:hidden}
  .lake{position:absolute;inset:0 auto 0 0;width:576px;background:#1E3A8A}
  .accent{position:absolute;left:56px;top:101px;width:42px;height:5px;background:#E7C56A}
  .brand{position:absolute;left:56px;top:43px;font-size:25px;font-weight:600;color:#fff;letter-spacing:.3px}
  #names{position:absolute;left:56px;top:132px;width:450px;height:104px;color:#DBEAFE;font-size:${count === 1 ? 26 : 23}px;font-weight:500;line-height:1.35;overflow-wrap:anywhere}
  .product-name{display:block}.model-token{display:inline-block;white-space:nowrap}#heading{position:absolute;left:56px;top:244px;width:450px;height:266px;color:#fff;font-size:58px;line-height:1.24;font-weight:700;letter-spacing:0;overflow-wrap:anywhere;line-break:strict}
  .phrase{display:inline-block;white-space:nowrap}#footer{position:absolute;left:56px;top:557px;width:450px;height:38px;color:#BFDBFE;font-size:21px;font-weight:500;line-height:1.4}
  .photo{position:absolute;display:block;object-fit:contain;object-position:center;image-rendering:auto}
  .edge{position:absolute;left:576px;top:0;width:4px;height:630px;background:#DBEAFE}
  </style></head><body><main id="card"><div class="lake"></div><div class="brand">Camp Gear Lab</div><div class="accent"></div>
  <div id="names">${photos.map(p => `<span class="product-name">${nameMarkup(p.name)}</span>`).join('')}</div><div id="heading">${heading}</div>
  <div id="footer">${input.label ? escape(input.label) : 'camp-gear-lab.com'}</div>${images}<div class="edge"></div></main></body></html>`;
}
async function writePng(outputPath, png) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true, mode: 0o700 });
  try {
    const stat = await fs.lstat(outputPath);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 8 * 1024 * 1024 || sha(await fs.readFile(outputPath)) !== sha(png)) fail('output_exists');
    return;
  } catch (e) { if (e.code !== 'ENOENT') throw e; }
  const temporary = path.join(path.dirname(outputPath), '.' + randomBytes(12).toString('hex') + '.png');
  try {
    await fs.writeFile(temporary, png, { flag: 'wx', mode: 0o600 });
    await fs.link(temporary, outputPath); // Atomic no-clobber publication, no partial PNG.
  } finally { await fs.rm(temporary, { force: true }); }
}
export async function renderSocialCard(raw) {
  const input = await validateInput(raw);
  const photos = await Promise.all(input.products.map(preparePhoto));
  const sourceBinding = { version: VERSION, title: input.title, heading: input.heading, label: input.label,
    products: photos.map(p => ({ name: p.name, sha256: p.sha256 })) };
  let browser, profile;
  try {
    profile = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-social-browser-'));
    browser = await puppeteer.launch({ headless: true, userDataDir: profile, timeout: 30000,
      env: { PATH: process.env.PATH || '/usr/bin:/bin', HOME: profile, TMPDIR: profile, TZ: 'Asia/Tokyo', LANG: 'ja_JP.UTF-8' },
      args: ['--disable-background-networking', '--disable-component-update', '--disable-default-apps', '--no-first-run', '--disable-sync'] });
    const page = await browser.newPage();
    await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
    await page.setRequestInterception(true);
    let networkRequests = 0;
    page.on('request', request => {
      if (request.url().startsWith('data:') || request.url() === 'about:blank') request.continue();
      else { networkRequests++; request.abort(); }
    });
    await page.setContent(html(input, photos), { waitUntil: 'load', timeout: 15000 });
    const layout = await page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all([...document.images].map(img => img.decode()));
      const heading = document.querySelector('#heading'), names = document.querySelector('#names');
      const fits = el => el.scrollHeight <= el.clientHeight && el.scrollWidth <= el.clientWidth &&
        [...el.children].every(child => child.getBoundingClientRect().right <= el.getBoundingClientRect().right);
      let size = 58;
      while (!fits(heading) && size > 40) heading.style.fontSize = --size + 'px';
      if (!fits(heading)) throw Error('heading_overflow_requires_short_approved_input');
      let nameSize = parseInt(getComputedStyle(names).fontSize, 10);
      while (!fits(names) && nameSize > 20) names.style.fontSize = --nameSize + 'px';
      if (!fits(names)) throw Error('product_name_overflow');
      const rect = el => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
      };
      const photos = [...document.images].map(rect);
      if (photos.some(r => r.x < 580 || r.y < 0 || r.right > 1200 || r.bottom > 630)) throw Error('product_layout_overflow');
      return { headingFontSize: size, productNameFontSize: nameSize, heading: rect(heading), photos,
        headingPhrases: [...heading.children].map(el => ({ text: el.textContent, ...rect(el) })),
        modelTokens: [...names.querySelectorAll('.model-token')].map(el => ({ text: el.textContent, ...rect(el) })),
        renderedHeading: heading.textContent, renderedNames: [...names.children].map(el => el.textContent) };
    });
    if (networkRequests || layout.renderedHeading !== input.heading ||
        JSON.stringify(layout.renderedNames) !== JSON.stringify(photos.map(p => p.name))) fail('render_evidence_mismatch');
    const png = Buffer.from(await page.screenshot({ type: 'png', clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT } }));
    const engine = await browser.version();
    await writePng(input.outputPath, png);
    return { passed: true, version: VERSION, width: WIDTH, height: HEIGHT, outputPath: input.outputPath,
      contentHash: sha(JSON.stringify(sourceBinding)), pngSha256: sha(png), bytes: png.length,
      displayText: { title: input.title, heading: input.heading, productNames: photos.map(p => p.name), label: input.label, brand: 'Camp Gear Lab' },
      sources: photos.map(({ dataUrl, ...evidence }) => evidence), layout, networkRequests,
      renderer: { engine, platform: process.platform, fontFamily: FONT } };
  } finally {
    if (browser) await browser.close();
    if (profile) await fs.rm(profile, { recursive: true, force: true });
  }
}
export async function main() {
  try {
    let input = '';
    for await (const chunk of process.stdin) {
      input += chunk;
      if (Buffer.byteLength(input) > MAX_REQUEST) fail('request_oversized');
    }
    process.stdout.write(JSON.stringify(await renderSocialCard(JSON.parse(input))) + '\n');
  } catch {
    process.stdout.write(JSON.stringify({ passed: false, error: 'social_card_render_failed' }) + '\n');
    process.exitCode = 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
