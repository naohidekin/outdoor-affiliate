/** Read-only browser audit: verified public HTML on stdin, bounded safe GETs only.
 * No screenshots/persistence here. Every navigation is intercepted at context level.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { childEnvironment } from './render-preview.mjs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const directory = path.dirname(fileURLToPath(import.meta.url));
const MAX_BYTES = 8 * 1024 * 1024;
const check = (name, status, reason) => ({ name, status, reason });
const sha = value => createHash('sha256').update(value).digest('hex');

// Fixed helper, isolated Python, no shell, no environment credentials. Catalog
// validates every redirect and pins public DNS; the browser never opens sockets.
export const PUBLIC_GET_HELPER = `import json,sys
sys.path.insert(0,sys.argv[1])
import catalog
try:
 q=json.load(sys.stdin)
 domains=q['domains']
 r=catalog.Catalog({}).request(q['url'],{'Accept':'*/*'},allowed_domains=domains,exact_domains=True)
 sys.stdout.buffer.write(json.dumps({'type':r['headers'].get('content-type',''),'url':r['url']}).encode()+b'\\n'+r['body'])
except Exception:
 sys.exit(1)
`;
export function safeGet(url, domains, active = new Set()) {
  return new Promise((resolve, reject) => {
    const child = spawn('python3', ['-I', '-B', '-c', PUBLIC_GET_HELPER, directory], {
      env: { PATH: process.env.PATH || '/usr/bin:/bin', TZ: 'Asia/Tokyo' }, stdio: ['pipe', 'pipe', 'ignore'],
    });
    active.add(child);
    let size = 0, done = false;
    const chunks = [];
    const finish = error => {
      if (done) return;
      done = true; clearTimeout(timer); active.delete(child);
      if (error) { child.kill('SIGKILL'); reject(new Error('safe_get_unavailable')); return; }
      try {
        const data = Buffer.concat(chunks), split = data.indexOf(10);
        if (split < 0 || split > 4096) throw new Error();
        const meta = JSON.parse(data.subarray(0, split));
        resolve({ body: data.subarray(split + 1), contentType: meta.type, url: meta.url });
      } catch { reject(new Error('safe_get_unavailable')); }
    };
    const timer = setTimeout(() => finish(true), 12000);
    child.on('error', () => finish(true));
    child.stdin.on('error', () => finish(true));
    child.stdout.on('data', data => {
      size += data.length;
      if (size > MAX_BYTES + 4096) finish(true); else chunks.push(data);
    });
    child.on('close', code => finish(code !== 0));
    child.stdin.end(JSON.stringify({ url, domains }));
  });
}

export function approvedHeadings(content) {
  // ATX and setext H2 outside fenced/indented code. Match rendered inline text.
  const lines = content.split(/\r?\n/), result = [];
  let fence = null;
  const plain = value => value.replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/<[^>]*>/g, '')
    .replace(/[*_`~]/g, '').replace(/\s+/g, ' ').trim();
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i], marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length && /^ {0,3}(?:`+|~+)\s*$/.test(line)) fence = null;
      continue;
    }
    if (fence || /^(?: {4}|\t)/.test(line)) continue;
    const atx = line.match(/^ {0,3}##\s+(.+?)(?:\s+#+)?\s*$/);
    if (atx) result.push(plain(atx[1]));
    else if (line.trim() && /^ {0,3}-{3,}\s*$/.test(lines[i + 1] || '')) { result.push(plain(line)); i++; }
  }
  return result;
}

function approvedProse(bundle) {
  const products = new Map(bundle.products.map(p => [p.id, p]));
  const resolved = bundle.article.content.replace(/\{\{price:([^}]+)\}\}/g, (_, id) => {
    const price = products.get(id.trim())?.price;
    return price ? price.toLocaleString('ja-JP') + '円' : '';
  });
  return resolved.split(/(\{\{(?:product|comparison|ranking|youtube):[^}]+\}\})/g)
    .filter(part => part.trim() && !/^\{\{(?:product|comparison|ranking|youtube):/.test(part))
    .map(part => renderToStaticMarkup(React.createElement(ReactMarkdown, { remarkPlugins: [remarkGfm] }, part)));
}

function variants(source) {
  const urls = [source];
  try {
    const u = new URL(source);
    for (const px of [48, 96, 160, 192, 200, 300, 400, 600, 640, 800, 1200]) {
      if (u.hostname === 'thumbnail.image.rakuten.co.jp') { const v = new URL(u); v.search = `?_ex=${px}x${px}`; urls.push(v.href); }
      else if (u.hostname === 'm.media-amazon.com') urls.push(source.replace(/(?:\._[^/.]+_)?\.(jpg|jpeg|png|webp)(\?.*)?$/i, `._AC_SL${px}_.$1`));
    }
  } catch { /* Bound public URLs are checked by Catalog before any GET. */ }
  return urls;
}

export async function auditPublicPage(input, { browser: suppliedBrowser, fetcher = safeGet } = {}) {
  const checks = [], active = new Set();
  let browser = suppliedBrowser;
  let expired = false;
  const timer = setTimeout(() => { expired = true; for (const c of active) c.kill('SIGKILL'); void browser?.close(); }, 70000);
  try {
    if (!input || input.url !== `https://camp-gear-lab.com/articles/${input.bundle?.article?.slug}` ||
        typeof input.html !== 'string' || Buffer.byteLength(input.html) > MAX_BYTES) throw new Error();
    const origin = new URL(input.url).origin, bundle = input.bundle;
    if (!browser) {
      const require = createRequire(path.join(input.repo || path.resolve(directory, '../..'), 'package.json'));
      const { chromium } = require('playwright');
      browser = await chromium.launch({ headless: true, env: childEnvironment(process.env.HOME || '/tmp') });
    }
    const imageMap = new Map();
    for (const p of bundle.products) for (const variant of variants(p.imageUrl)) imageMap.set(variant, p.imageUrl);
    if (bundle.article.eyecatch) for (const variant of variants(bundle.article.eyecatch)) imageMap.set(variant, bundle.article.eyecatch);
    const cache = new Map();
    let requests = 0, downloaded = 0, concurrent = 0;
    async function get(url, domains) {
      if (!cache.has(url)) {
        if (++requests > 120 || expired) throw new Error();
        cache.set(url, (async () => {
          while (concurrent >= 4 && !expired) await delay(20);
          if (expired) throw new Error();
          concurrent++;
          try {
            const response = await fetcher(url, domains, active);
            downloaded += response.body.length;
            if (response.body.length > MAX_BYTES || downloaded > 48 * 1024 * 1024) throw new Error();
            return response;
          } finally { concurrent--; }
        })());
      }
      return cache.get(url);
    }
    for (const [name, width] of [['desktop', 1440], ['mobile', 390]]) {
      const start = checks.length;
      const add = (suffix, ok, good, bad, status = 'failed') => checks.push(check(`${name}.${suffix}`, ok ? 'passed' : status, ok ? good : bad));
      const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
      const navigations = [], resourceFailures = [];
      let loading = true, clicked = null;
      try {
        // Context routing sees the FIRST request of window.open/target=_blank.
        await context.route('**/*', async route => {
          const request = route.request();
          try {
            const u = new URL(request.url());
            if (request.isNavigationRequest()) {
              if (loading && request.url() === input.url && request.frame().parentFrame() === null) {
                loading = false;
                return await route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: input.html });
              }
              navigations.push(request.url());
              return await route.abort();
            }
            // No analytics scripts, API calls, beacons or mutations are sent.
            if (request.method() !== 'GET' || !['script', 'stylesheet', 'font', 'image'].includes(request.resourceType()) ||
                /\/(?:api|ingest|collect|analytics|tracking)(?:\/|$)|google-analytics|googletagmanager|posthog/i.test(u.pathname)) return await route.abort();
            let source = request.url(), domains = ['camp-gear-lab.com'];
            if (request.resourceType() === 'image') {
              const wanted = u.origin === origin && u.pathname === '/_next/image' ? new URL(u.searchParams.get('url'), origin).href : source;
              const approved = imageMap.get(wanted);
              if (approved) {
                // Fetch the actual rendered variant; never substitute original bytes.
                source = wanted; domains = [new URL(approved).hostname];
              } else if (u.origin !== origin || u.pathname === '/_next/image') return await route.abort();
            } else if (u.origin !== origin || !u.pathname.startsWith('/_next/static/')) return await route.abort();
            if (new URL(source).origin === origin && !['/_next/static/', '/images/', '/fonts/', '/logo', '/favicon'].some(p => new URL(source).pathname.startsWith(p)) && request.resourceType() !== 'image') return await route.abort();
            const response = await get(source, domains);
            return await route.fulfill({ status: 200, contentType: response.contentType, body: response.body });
          } catch {
            resourceFailures.push(true);
            await route.abort().catch(() => {});
          }
        });
        await context.addInitScript(() => {
          navigator.sendBeacon = () => true;
          window.gtag = () => {};
          window.dataLayer = [];
        });
        const page = await context.newPage();
        page.setDefaultTimeout(5000);
        await page.goto(input.url, { waitUntil: 'load', timeout: 20000 });
        await page.waitForTimeout(400); // Let hydration attach real merchant handlers.
        const article = page.locator('main article[data-review-content-sha256]');
        const expectedHash = sha(bundle.article.content);
        add('binding', await article.count() === 1 && await article.first().getAttribute('data-review-content-sha256') === expectedHash,
          'rendered_body_hash_exact', 'rendered_body_hash_mismatch');
        // Some articles split ArticleContent around an advice block. The reading
        // container remains one visible body even when .article-body occurs twice.
        const reading = article.locator('#article-reading-content');
        const body = await reading.count() === 1 ? reading : article.locator('.article-body');
        add('body', await body.count() === 1 && await body.isVisible() && (await body.innerText()).trim().length > 0,
          'article_body_visible', 'article_body_missing_or_hidden');
        const proseMatch = await body.evaluate((root, expected) => {
          // Compare ordered Markdown blocks using the same renderer as the site.
          // Product cards live outside .prose. TableScroll's UI is outside table.
          const normalize = (node, visibleOnly) => {
            const blockTags = new Set(['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'PRE', 'TH', 'TD', 'BLOCKQUOTE']);
            const parts = [];
            const visit = element => {
              if (element.nodeType === Node.TEXT_NODE) { parts.push(element.textContent); return; }
              if (element.nodeType !== Node.ELEMENT_NODE) return;
              if (visibleOnly && (!element.getClientRects().length || ['hidden', 'collapse'].includes(getComputedStyle(element).visibility))) return;
              if (element.classList.contains('table-shell')) { const table = element.querySelector('table'); if (table) visit(table); return; }
              const block = blockTags.has(element.tagName);
              if (block) parts.push('\n');
              if (element.tagName === 'BR') parts.push(' ');
              for (const child of element.childNodes) visit(child);
              if (block) parts.push('\n');
            };
            for (const child of node.childNodes) visit(child);
            return parts.join('').split('\n').map(line => line.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n');
          };
          const wanted = expected.map(html => {
            const template = document.createElement('template'); template.innerHTML = html;
            return normalize(template.content, false);
          }).join('\n');
          const shown = [...root.querySelectorAll('.article-body > .prose, :scope.article-body > .prose')]
            .map(node => normalize(node, true)).join('\n');
          return Boolean(wanted) && wanted === shown;
        }, approvedProse(bundle));
        add('prose', proseMatch, 'approved_prose_exact', 'approved_prose_mismatch');
        const h1 = article.locator('h1');
        add('title', await h1.count() === 1 && await h1.isVisible() && (await h1.innerText()).trim() === bundle.article.title,
          'rendered_title_exact', 'rendered_title_mismatch');
        for (const [i, heading] of approvedHeadings(bundle.article.content).entries()) {
          let found = false;
          for (const h of await body.locator('h2').all()) {
            if (await h.isVisible() && (await h.innerText()).replace(/\s+/g, ' ').trim() === heading) { found = true; break; }
          }
          add(`heading.${i}`, found, 'approved_heading_visible', 'approved_heading_missing_or_hidden');
        }
        add('tags', !/\{\{\s*(?:product|price|comparison|ranking)\b/i.test(await page.locator('main').innerText()),
          'no_unresolved_product_tags', 'unresolved_product_tags');
        await page.evaluate(() => { for (const image of document.images) image.loading = 'eager'; });
        let reached = false;
        for (let step = 0; step < 100; step++) {
          reached = await page.evaluate(() => {
            window.scrollBy(0, Math.max(200, innerHeight * 0.8));
            return scrollY + innerHeight >= document.documentElement.scrollHeight - 2;
          });
          await delay(25);
          if (reached) break;
        }
        add('scroll', reached, 'full_page_scrolled', 'page_scroll_limit_exceeded', 'unverified');
        await page.waitForFunction(() => [...document.images].filter(i => i.getClientRects().length && getComputedStyle(i).visibility !== 'hidden')
          .every(i => i.complete && i.naturalWidth > 0), null, { timeout: 8000 }).catch(() => {});
        const imageState = await page.evaluate(() => ({
          loaded: [...document.images].filter(i => i.getClientRects().length && getComputedStyle(i).visibility !== 'hidden').every(i => i.complete && i.naturalWidth > 0),
          sources: [...document.querySelectorAll('main article img')].filter(i => i.getClientRects().length &&
            getComputedStyle(i).visibility === 'visible' && i.complete && i.naturalWidth > 0).map(i => i.currentSrc || i.src),
          overflow: document.documentElement.scrollWidth > innerWidth + 1,
        }));
        add('images', imageState.loaded, 'visible_images_loaded', 'visible_images_not_loaded', resourceFailures.length ? 'unverified' : 'failed');
        add('overflow', !imageState.overflow, 'no_horizontal_overflow', 'horizontal_overflow');
        for (const [i, product] of bundle.products.entries()) {
          const wanted = variants(product.imageUrl);
          const shown = imageState.sources.some(source => {
            const u = new URL(source, origin);
            return wanted.includes(u.pathname === '/_next/image' && u.origin === origin ? new URL(u.searchParams.get('url'), origin).href : source);
          });
          add(`product_image.${i}`, shown, 'approved_product_image_rendered', 'approved_product_image_not_rendered');
          for (const [store, href] of [['rakuten', product.affiliateUrl], ['amazon', product.amazonUrl]]) {
            if (!href) { add(`click.${i}.${store}`, false, '', 'approved_merchant_url_missing', 'unverified'); continue; }
            const links = article.locator('a');
            let visible = null;
            for (const link of await links.all()) {
              if (await link.getAttribute('href') === href && await link.isVisible()) { visible = link; break; }
            }
            if (!visible) { add(`click.${i}.${store}`, false, '', 'exact_approved_visible_link_missing'); continue; }
            const before = navigations.length;
            clicked = href;
            await visible.click({ timeout: 5000, noWaitAfter: true });
            for (let wait = 0; wait < 40 && navigations.length === before; wait++) await delay(25);
            add(`click.${i}.${store}`, navigations.length === before + 1 && navigations[before] === new URL(clicked).href,
              'exact_approved_navigation_intercepted', 'approved_navigation_not_captured');
            for (const popup of context.pages()) if (popup !== page) await popup.close().catch(() => {});
          }
        }
        if (resourceFailures.length) add('resources', false, '', 'safe_resource_get_unavailable', 'unverified');
      } catch {
        checks.push(check(`${name}.execution`, 'unverified', 'viewport_timeout_or_unavailable'));
      } finally { await context.close().catch(() => {}); }
      const relevant = checks.slice(start);
      const status = relevant.some(c => c.status === 'failed') ? 'failed' : relevant.some(c => c.status === 'unverified') ? 'unverified' : 'passed';
      checks.push(check(name, status, status === 'passed' ? 'viewport_verified' : 'viewport_checks_incomplete'));
    }
  } catch { checks.push(check('browser', 'unverified', 'browser_input_or_engine_unavailable')); }
  finally {
    clearTimeout(timer);
    for (const child of active) child.kill('SIGKILL');
    if (browser && !suppliedBrowser) await browser.close().catch(() => {});
  }
  return { checks };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let size = 0; const chunks = [];
  try {
    for await (const chunk of process.stdin) { size += chunk.length; if (size > 2 * MAX_BYTES) throw new Error(); chunks.push(chunk); }
    process.stdout.write(JSON.stringify(await auditPublicPage(JSON.parse(Buffer.concat(chunks).toString('utf8')))) + '\n');
  } catch { process.stdout.write(JSON.stringify({ checks: [check('browser', 'unverified', 'browser_input_unavailable')] }) + '\n'); }
}
