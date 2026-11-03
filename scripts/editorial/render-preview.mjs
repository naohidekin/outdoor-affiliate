/** Private renderer: one JSON request on stdin, one JSON result on stdout.
 * desktop/mobile are screenshot paths or null. Failures are strings; status is
 * passed/failed/blocked. No publisher, repo data writes, or runtime credentials.
 * --deps accepts a package root or its node_modules directory.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

export function childEnvironment(home, inherited = process.env) {
  // An allowlist, not a blacklist: no Supabase, NEXT_PUBLIC_*, NODE_OPTIONS,
  // proxy, cloud credentials, or shell startup files reach the Next process.
  return { PATH: `${path.dirname(process.execPath)}:/usr/bin:/bin`, HOME: home,
    TMPDIR: home, TZ: 'Asia/Tokyo', LANG: inherited.LANG || 'en_US.UTF-8',
    NODE_ENV: 'development', NEXT_TELEMETRY_DISABLED: '1' };
}

export function validateInput(input) {
  if (!input || typeof input !== 'object') throw new Error('JSON object required');
  const { bundle, repo, outputDir } = input;
  if (!repo || !outputDir || typeof repo !== 'string' || typeof outputDir !== 'string')
    throw new Error('repo and outputDir are required paths');
  if (!bundle?.article || !Array.isArray(bundle.products)) throw new Error('bundle.article and bundle.products required');
  const a = bundle.article;
  if (!/^[a-z0-9][a-z0-9-]*$/.test(a.slug || '') || !a.title || typeof a.content !== 'string')
    throw new Error('article slug, title and content required');
  if (!Array.isArray(a.productIds)) throw new Error('article.productIds required');
  const ids = bundle.products.map(p => p?.id);
  if (ids.some(id => typeof id !== 'string' || !id) || new Set(ids).size !== ids.length)
    throw new Error('product IDs must be unique nonempty strings');
  for (const id of a.productIds) if (!ids.includes(id)) throw new Error(`missing product: ${id}`);
  // Missing custom-tag IDs otherwise disappear silently in ArticleContent.
  for (const match of a.content.matchAll(/\{\{(product|comparison|ranking|price):([^}]+)\}\}/g))
    for (const id of match[2].split(',').map(x => x.trim()))
      if (!ids.includes(id)) throw new Error(`unresolved ${match[1]} product: ${id}`);
  return { ...input, repo: path.resolve(repo), outputDir: path.resolve(outputDir) };
}

export function expectedMerchants(products) {
  return products.flatMap(p => [['rakuten', p.affiliateUrl], ['amazon', p.amazonUrl], ['yahoo', p.yahooUrl]]
    .filter(([, href]) => {
      try { const u = new URL(href); return u.protocol === 'https:' && !u.username && !u.password; }
      catch { return false; }
    }).map(([store, href]) => ({ productId: p.id, productName: p.name, store, href })));
}

export function verifyClick(expected, beacon, events, navigation, articlePath) {
  const failures = [];
  if (!beacon || beacon.productId !== expected.productId || beacon.store !== expected.store ||
      beacon.link_url !== expected.href || beacon.path !== articlePath)
    failures.push(`click payload mismatch: ${expected.productId}/${expected.store}`);
  const event = events.find(e => e[0] === 'event' && e[1] === 'affiliate_click' &&
    e[2]?.product_id === expected.productId && e[2]?.merchant === expected.store && e[2]?.link_url === expected.href);
  if (!event) failures.push(`affiliate event missing: ${expected.productId}/${expected.store}`);
  if (navigation !== new URL(expected.href).href) failures.push(`navigation mismatch: ${expected.productId}/${expected.store}`);
  return failures;
}

export async function privateOutputDirectory(repo, outputDir) {
  // Resolve the nearest existing ancestor before mkdir, including symlinked
  // parents. Reject public destinations without modifying the source tree.
  let ancestor = path.resolve(outputDir);
  const missing = [];
  while (true) {
    try { ancestor = await fs.realpath(ancestor); break; }
    catch (e) {
      if (e.code !== 'ENOENT') throw e;
      missing.unshift(path.basename(ancestor));
      ancestor = path.dirname(ancestor);
    }
  }
  const destination = path.join(ancestor, ...missing);
  const publicDir = await fs.realpath(path.join(repo, 'public'));
  if (destination === publicDir || destination.startsWith(publicDir + path.sep))
    throw new Error('outputDir must not be inside repo/public');
  await fs.mkdir(destination, { recursive: true, mode: 0o700 });
  // A fresh private run directory prevents overwrites and preexisting screenshot
  // symlinks. Return exact screenshot paths in the result, not guessed filenames.
  const run = await fs.mkdtemp(path.join(destination, 'render-'));
  await fs.chmod(run, 0o700);
  return run;
}

async function copyTree(source, target) {
  // Do not dereference symlinks into private source data or another checkout.
  await fs.cp(source, target, { recursive: true, filter: async p => !(await fs.lstat(p)).isSymbolicLink() });
}

export async function prepareApp(input, app, modules) {
  const { repo, bundle } = input;
  for (const dir of ['components', 'lib']) await copyTree(path.join(repo, 'src', dir), path.join(app, 'src', dir));
  await copyTree(path.join(repo, 'src/app/articles'), path.join(app, 'src/app/articles'));
  // Only page sources: no production API routes, middleware, instrumentation,
  // .env files, analytics layout, or remote next/font build requests.
  await fs.copyFile(path.join(repo, 'src/app/globals.css'), path.join(app, 'src/app/globals.css'));
  await fs.writeFile(path.join(app, 'src/app/layout.tsx'), `import './globals.css';
export default function Layout({children}:{children:React.ReactNode}) { return <html lang="ja" className="h-full antialiased"><body className="min-h-full flex flex-col bg-snow text-ink">{children}</body></html>; }\n`);
  for (const file of ['tsconfig.json', 'postcss.config.mjs'])
    await fs.copyFile(path.join(repo, file), path.join(app, file));
  await fs.writeFile(path.join(app, 'package.json'), JSON.stringify({ private: true, type: 'module' }));
  await fs.writeFile(path.join(app, 'next.config.mjs'), 'export default { images: { unoptimized: true }, devIndicators: false };\n');
  await fs.symlink(modules, path.join(app, 'node_modules'), 'dir');
  await fs.mkdir(path.join(app, 'data'));
  // Public snapshots supply categories only; the app cannot see other articles.
  const categories = JSON.parse(await fs.readFile(path.join(repo, 'data/categories.json'), 'utf8'));
  const article = { ...bundle.article, status: 'published' };
  if (!categories.some(c => c.id === article.categoryId)) throw new Error('unknown article categoryId');
  const products = structuredClone(bundle.products);
  await fs.mkdir(path.join(app, 'public'), { recursive: true });
  // Existing public assets are needed by Header/Footer and relative product URLs.
  await copyTree(path.join(repo, 'public'), path.join(app, 'public'));
  for (const [i, image] of (bundle.images || []).entries()) {
    if (!image.path) continue;
    const ext = path.extname(image.path).toLowerCase();
    if (!['.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif', '.svg'].includes(ext)) throw new Error('unsupported local image');
    const name = `editorial-candidate-${i}${ext}`;
    await fs.copyFile(path.resolve(image.path), path.join(app, 'public', name));
    const url = `/${name}`;
    const product = products.find(p => p.id === image.productId);
    if (product) product.imageUrl = url;
    if (image.role === 'eyecatch' || image.path === article.eyecatch) article.eyecatch = url;
    if (image.url) article.content = article.content.split(image.url).join(url);
  }
  for (const [file, value] of Object.entries({ articles: [article], products, categories }))
    await fs.writeFile(path.join(app, 'data', `${file}.json`), JSON.stringify(value));
}

async function availablePort() {
  const s = net.createServer();
  await new Promise((resolve, reject) => { s.once('error', reject); s.listen(0, '127.0.0.1', resolve); });
  const port = s.address().port;
  await new Promise(resolve => s.close(resolve));
  return port;
}

async function inspectViewport(browser, origin, input, name, width, result) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  const beacons = [], navigations = [], errors = [];
  const articlePath = `/articles/${input.bundle.article.slug}`;
  // Context routing covers new-tab requests before a popup can contact a merchant.
  // Only remote images may leave the browser; no tracking, scripts or navigation.
  await context.route('**/*', async route => {
    const request = route.request();
    const u = new URL(request.url());
    if (u.origin === origin) return route.continue();
    if (request.isNavigationRequest()) navigations.push(request.url());
    if (request.resourceType() === 'image' && u.protocol === 'https:') return route.continue();
    return route.abort();
  });
  await page.route('**/api/track-click', async route => {
    if (new URL(route.request().url()).origin !== origin) return route.abort();
    try { beacons.push(route.request().postDataJSON()); } catch { beacons.push(null); }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
  });
  context.on('page', popup => { popup.on('domcontentloaded', () => popup.close().catch(() => {})); });
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => {
    window.__previewEvents = [];
    window.gtag = (...args) => window.__previewEvents.push(args);
  });
  try {
    const response = await page.goto(origin + articlePath, { waitUntil: 'networkidle', timeout: 120000 });
    if (response.status() !== 200) throw new Error(`article HTTP ${response.status()}`);
    await page.locator('.article-body').first().waitFor();
    // Trigger every lazy image before checking naturalWidth and full-page capture.
    for (const img of await page.locator('img').all()) {
      if (await img.isVisible()) await img.scrollIntoViewIfNeeded();
    }
    await page.evaluate(() => { for (const image of document.images) image.loading = 'eager'; });
    await page.waitForFunction(() => [...document.images].filter(i => i.getClientRects().length).every(i => i.complete && i.naturalWidth > 0), null, { timeout: 15000 }).catch(() => {});
    await page.evaluate(() => document.fonts.ready);
    const observations = await page.evaluate(() => ({
      h1: document.querySelectorAll('h1').length,
      shortcode: /\{\{[^}]+\}\}/.test(document.body.innerText),
      overflow: document.documentElement.scrollWidth > innerWidth + 1,
      brokenImages: [...document.images].filter(i => i.getClientRects().length && (!i.complete || i.naturalWidth <= 0)).map(i => i.currentSrc || i.src),
    }));
    if (observations.h1 !== 1) result.failures.push(`${name}: expected one H1, got ${observations.h1}`);
    if (observations.shortcode) result.failures.push(`${name}: unresolved shortcode`);
    if (observations.overflow) result.failures.push(`${name}: horizontal overflow`);
    for (const src of observations.brokenImages) result.failures.push(`${name}: image failed: ${src}`);
    await page.evaluate(() => window.scrollTo(0, 0));
    const screenshot = path.join(input.outputDir, `${name}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    await fs.chmod(screenshot, 0o600);
    result[name] = screenshot;

    const expected = expectedMerchants(input.bundle.products.filter(p => input.bundle.article.productIds.includes(p.id)));
    const checked = [];
    result.clicksVerified[name] = checked;
    // Inspect every merchant CTA instance, including comparison/card/top/end/sidebar.
    const links = page.locator('a[rel~="sponsored"][aria-label]');
    const seen = new Set();
    for (let i = 0; i < await links.count(); i++) {
      const link = links.nth(i);
      if (!await link.isVisible()) continue;
      const href = await link.getAttribute('href');
      const label = await link.getAttribute('aria-label');
      const matches = expected.filter(e => e.href === href && label.includes(e.productName));
      if (matches.length !== 1) { result.failures.push(`${name}: unexpected/ambiguous merchant CTA: ${href}`); continue; }
      const merchant = matches[0];
      const n = beacons.length, nav = navigations.length;
      await page.evaluate(() => { window.__previewEvents = []; });
      await link.click();
      await page.waitForFunction(() => window.__previewEvents.some(e => e[1] === 'affiliate_click')).catch(() => {});
      const deadline = Date.now() + 4000;
      while ((beacons.length === n || navigations.length === nav) && Date.now() < deadline) await delay(50);
      const events = await page.evaluate(() => window.__previewEvents);
      const failures = verifyClick(merchant, beacons[n], events, navigations[nav], articlePath);
      if (beacons.length !== n + 1) failures.push(`expected one click beacon, got ${beacons.length - n}`);
      result.failures.push(...failures.map(f => `${name}: ${f}`));
      if (!failures.length) { checked.push({ productId: merchant.productId, store: merchant.store, href, placement: beacons[n].placement }); seen.add(`${merchant.productId}/${merchant.store}`); }
      for (const popup of context.pages()) if (popup !== page) await popup.close();
    }
    for (const e of expected) if (!seen.has(`${e.productId}/${e.store}`)) result.failures.push(`${name}: missing verified merchant CTA: ${e.productId}/${e.store}`);
    result.clicksVerified[name] = checked;
    result.failures.push(...errors.map(e => `${name}: browser error: ${e}`));
  } finally { await context.close(); }
}

export async function renderPreview(raw) {
  const result = { passed: false, desktop: null, mobile: null, failures: [], clicksVerified: { desktop: [], mobile: [] }, status: 'failed' };
  let temp, server, browser;
  try {
    const input = validateInput(raw);
    const major = Number(process.versions.node.split('.')[0]);
    if (![20, 24].includes(major)) { result.status = 'blocked'; throw new Error('Node 20 or 24 required'); }
    const root = path.resolve(input.dependenciesRoot || input.repo);
    const dependencyRoot = path.basename(root) === 'node_modules' ? path.dirname(root) : root;
    const require = createRequire(path.join(dependencyRoot, 'package.json'));
    let chromium, nextBin;
    try { ({ chromium } = require('playwright')); nextBin = require.resolve('next/dist/bin/next'); }
    catch { result.status = 'blocked'; throw new Error(`Playwright/Next unavailable at ${dependencyRoot}; run npm ci and npx playwright install chromium`); }
    try { await fs.access(chromium.executablePath()); }
    catch { result.status = 'blocked'; throw new Error('Playwright Chromium unavailable; run npx playwright install chromium'); }
    // Screenshots are private runner artifacts, never under repo/public.
    input.outputDir = await privateOutputDirectory(input.repo, input.outputDir);
    temp = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-private-render-'));
    await fs.chmod(temp, 0o700);
    const modules = path.dirname(path.dirname(require.resolve('next/package.json')));
    await prepareApp(input, temp, modules);
    const port = await availablePort();
    const origin = `http://127.0.0.1:${port}`;
    let logs = '';
    server = spawn(process.execPath, [nextBin, 'dev', '--webpack', '--hostname', '127.0.0.1', '--port', String(port)],
      { cwd: temp, env: childEnvironment(temp), stdio: ['ignore', 'pipe', 'pipe'], detached: true });
    server.stdout.on('data', c => { logs = (logs + c).slice(-6000); });
    server.stderr.on('data', c => { logs = (logs + c).slice(-6000); });
    let spawnError;
    server.on('error', e => { spawnError = e; });
    const deadline = Date.now() + 60000;
    while (!logs.includes('Ready in')) {
      if (spawnError) throw spawnError;
      if (server.exitCode !== null || Date.now() > deadline) throw new Error(`Next startup failed: ${logs}`);
      await delay(100);
    }
    try { browser = await chromium.launch({ headless: true, env: childEnvironment(temp) }); }
    catch (e) { result.status = 'blocked'; throw new Error(`Chromium launch blocked: ${e.message}`); }
    for (const [name, width] of [['desktop', 1280], ['mobile', 390]]) {
      try { await inspectViewport(browser, origin, input, name, width, result); }
      catch (e) { result.failures.push(`${name}: ${e.message}`); }
    }
    result.passed = result.failures.length === 0 && !!result.desktop && !!result.mobile;
    result.status = result.passed ? 'passed' : 'failed';
  } catch (e) { result.failures.push(e.message); }
  finally {
    await browser?.close().catch(() => {});
    if (server?.pid) {
      try { process.kill(-server.pid, 'SIGTERM'); } catch { /* already exited */ }
      await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(2000)]);
      try { process.kill(-server.pid, 'SIGKILL'); } catch { /* already exited */ }
    }
    if (temp) await fs.rm(temp, { recursive: true, force: true });
  }
  return result;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let input = '';
  try {
    for await (const chunk of process.stdin) input += chunk;
    const request = JSON.parse(input);
    const i = process.argv.indexOf('--deps');
    if (i !== -1) { if (!process.argv[i + 1]) throw new Error('--deps requires a path'); request.dependenciesRoot = process.argv[i + 1]; }
    process.stdout.write(JSON.stringify(await renderPreview(request)) + '\n');
  } catch (e) {
    process.stdout.write(JSON.stringify({ passed: false, desktop: null, mobile: null, failures: [e.message], clicksVerified: { desktop: [], mobile: [] }, status: 'failed' }) + '\n');
  }
}
