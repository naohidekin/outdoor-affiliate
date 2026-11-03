/** node --test scripts/editorial/test-render-preview.mjs
 * RUN_RENDER_TESTS=1 enables real Next/Chromium integration (no API keys).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { childEnvironment, validateInput, expectedMerchants, verifyClick, verifyFaqVisibility, prepareApp, renderPreview, privateOutputDirectory, fetchPublicImage, createRequestHandler, IMAGE_HELPER } from './render-preview.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const merchant = { productId: 'preview-p1', productName: '検証用テント', store: 'amazon', href: 'https://www.amazon.co.jp/dp/B012345678/?tag=camp78-22' };
function request(outputDir = '/tmp/privateoutput') {
  return { repo, outputDir, bundle: {
    article: { id: 'preview-a1', slug: 'editorial-preview-test', title: '検証用のテント比較', categoryId: 'tent',
      content: '## テントの選び方\n仕様を確認します。\n{{comparison:preview-p1}}\n{{product:preview-p1}}\n## まとめ\n用途に合わせます。',
      productIds: ['preview-p1'], excerpt: '検証用記事', tags: [], faqs: [], createdAt: '2026-11-03T09:00:00+09:00',
      updatedAt: '2026-11-03T09:00:00+09:00', publishedAt: null, status: 'draft' },
    products: [{ id: 'preview-p1', name: '検証用テント', brand: '検証ブランド', price: 12000, specs: { '重量': '2kg' },
      categoryId: 'tent', description: '実際の本文コンポーネントを検証します。', imageUrl: '/tent-icon.svg',
      affiliateUrl: 'https://hb.afl.rakuten.co.jp/ichiba/preview/?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fshop%2Ftent%2F',
      amazonUrl: merchant.href, createdAt: '2026-11-03T09:00:00+09:00', updatedAt: '2026-11-03T09:00:00+09:00' }], images: [] } };
}

test('child environment drops all credentials, proxies and injection options', () => {
  const env = childEnvironment('/private/home', { SUPABASE_URL: 'secret', SUPABASE_SERVICE_ROLE_KEY: 'secret',
    NEXT_PUBLIC_SUPABASE_URL: 'secret', AWS_SECRET_ACCESS_KEY: 'secret', NODE_OPTIONS: '--require bad',
    HTTPS_PROXY: 'secret', PATH: 'bad', LANG: 'ja_JP.UTF-8' });
  assert.deepEqual(Object.keys(env).sort(), ['HOME', 'LANG', 'NEXT_TELEMETRY_DISABLED', 'NODE_ENV', 'PATH', 'TMPDIR', 'TZ'].sort());
  assert.equal(env.HOME, '/private/home');
  assert.equal(env.TZ, 'Asia/Tokyo');
});

test('input rejects missing products, duplicate IDs and path-like slugs', () => {
  const good = request();
  assert.equal(validateInput(good).bundle.article.slug, 'editorial-preview-test');
  for (const mutate of [r => { r.bundle.article.slug = '../private'; }, r => { r.bundle.products = []; },
    r => { r.bundle.products.push(r.bundle.products[0]); }, r => { r.bundle.article.content += '{{price:missing}}'; }]) {
    const bad = request(); mutate(bad); assert.throws(() => validateInput(bad));
  }
});

test('expected merchants keeps per-product identity and excludes unsafe hrefs', () => {
  const products = request().bundle.products;
  products[0].yahooUrl = 'javascript:alert(1)';
  assert.deepEqual(expectedMerchants(products).map(x => x.store), ['rakuten', 'amazon']);
  products[0].amazonUrl = 'https://user:pass@amazon.co.jp/';
  assert.equal(expectedMerchants(products).length, 1);
});

test('click verifier rejects wrong product, merchant, destination, missing event and path', () => {
  const beacon = { productId: merchant.productId, store: 'amazon', link_url: merchant.href, path: '/articles/test' };
  const events = [['event', 'affiliate_click', { product_id: merchant.productId, merchant: 'amazon', link_url: merchant.href }]];
  assert.deepEqual(verifyClick(merchant, beacon, events, merchant.href, '/articles/test'), []);
  for (const changed of [{ productId: 'other' }, { store: 'rakuten' }, { link_url: 'https://evil.test/' }, { path: '/wrong' }])
    assert.ok(verifyClick(merchant, { ...beacon, ...changed }, events, merchant.href, '/articles/test').length);
  assert.ok(verifyClick(merchant, beacon, [], merchant.href, '/articles/test').length);
  assert.ok(verifyClick(merchant, beacon, events, 'https://evil.test/', '/articles/test').length);
});

test('FAQ visibility requires each expected question and answer together in rendered FAQ text', () => {
  const faqs = [{ question: '収納は **簡単** ですか？', answer: '[説明書](https://maker.example/help)を確認します。' },
    { question: '重さは？', answer: '2kgです。' }];
  assert.deepEqual(verifyFaqVisibility(faqs, [], 'desktop'), [
    'desktop: FAQ question/answer not visibly rendered: #1',
    'desktop: FAQ question/answer not visibly rendered: #2']);
  assert.equal(verifyFaqVisibility(faqs, ['収納は 簡単 ですか？ 別の回答です。', '重さは？ 2kgです。'], 'mobile').length, 1);
  assert.deepEqual(verifyFaqVisibility(faqs, ['Q. 収納は 簡単 ですか？\n▼\n説明書を確認します。',
    '### 重さは？\n\n2kgです。'], 'mobile'), []);
});

test('real FAQ render catches empty body heading and accepts structured or inline Q&A on both viewports',
  { skip: process.env.RUN_RENDER_TESTS !== '1', timeout: 300000 }, async () => {
    const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'render-faq-'));
    try {
      const input = request(path.join(temp, 'privateoutput'));
      if (process.env.RENDER_DEPS) input.dependenciesRoot = process.env.RENDER_DEPS;
      const faq = { question: '収納は簡単ですか？', answer: '説明書を確認します。' };
      input.bundle.article.faqs = [faq];
      const structured = await renderPreview(input);
      assert.equal(structured.passed, true, JSON.stringify(structured));
      input.bundle.article.content += '\n## FAQ\n';
      const empty = await renderPreview(input);
      assert.equal(empty.passed, false);
      for (const viewport of ['desktop', 'mobile'])
        assert.ok(empty.failures.some(f => f.includes(`${viewport}: FAQ question/answer not visibly rendered`)), JSON.stringify(empty));
      input.bundle.article.content += `\n### ${faq.question}\n${faq.answer}\n`;
      const inline = await renderPreview(input);
      assert.equal(inline.passed, true, JSON.stringify(inline));
    } finally { await fs.rm(temp, { recursive: true, force: true }); }
  });

test('isolated app uses real sources and candidate data, never copies env or APIs', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'render-unit-'));
  try {
    const input = request();
    const before = await fs.readFile(path.join(repo, 'data/articles.json'));
    await prepareApp(input, temp, path.join(repo, 'node_modules'));
    assert.deepEqual(await fs.readFile(path.join(repo, 'data/articles.json')), before);
    const articles = JSON.parse(await fs.readFile(path.join(temp, 'data/articles.json')));
    assert.equal(articles.length, 1);
    assert.equal(articles[0].status, 'published');
    assert.equal(input.bundle.article.status, 'draft');
    for (const f of ['ArticleContent', 'ProductCard', 'ComparisonTable', 'AffiliateLink'])
      assert.deepEqual(await fs.readFile(path.join(temp, `src/components/${f}.tsx`)), await fs.readFile(path.join(repo, `src/components/${f}.tsx`)));
    for (const f of ['.env', '.env.local', 'src/app/api', 'src/middleware.ts'])
      await assert.rejects(fs.access(path.join(temp, f)));
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});

test('private outputs reject public paths and symlink aliases before writing; each run is private', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'render-output-'));
  try {
    await fs.mkdir(path.join(temp, 'public'));
    const forbidden = path.join(temp, 'public/new/nested');
    await assert.rejects(privateOutputDirectory(temp, forbidden), /repo\/public/);
    await assert.rejects(fs.access(path.join(temp, 'public/new')));
    await fs.symlink(path.join(temp, 'public'), path.join(temp, 'alias'));
    await assert.rejects(privateOutputDirectory(temp, path.join(temp, 'alias/new')), /repo\/public/);
    const output = path.join(temp, 'privateoutput');
    const a = await privateOutputDirectory(temp, output);
    const b = await privateOutputDirectory(temp, output);
    assert.notEqual(a, b);
    assert.equal((await fs.stat(a)).mode & 0o777, 0o700);
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});

test('missing dependency root returns explicit blocked, no screenshot or fabricated clicks', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'render-missing-deps-'));
  try {
    const result = await renderPreview({ ...request(), dependenciesRoot: temp });
    assert.equal(result.passed, false);
    assert.equal(result.status, 'blocked');
    assert.equal(result.desktop, null);
    assert.deepEqual(result.clicksVerified, { desktop: [], mobile: [] });
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});

test('CLI invalid JSON emits exactly one parseable result', () => {
  const run = spawnSync(process.execPath, [path.join(repo, 'scripts/editorial/render-preview.mjs')], { input: '{bad', encoding: 'utf8' });
  assert.equal(run.status, 0);
  assert.equal(JSON.parse(run.stdout).passed, false);
  assert.equal(run.stdout.trim().split('\n').length, 1);
});

test('real desktop/mobile render, images, CTA beacons/events and aborted popups; bad candidate fails',
  { skip: process.env.RUN_RENDER_TESTS !== '1', timeout: 300000 }, async () => {
    const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'render-integration-'));
    try {
      const input = request(path.join(temp, 'privateoutput'));
      if (process.env.RENDER_DEPS) input.dependenciesRoot = process.env.RENDER_DEPS;
      const good = await renderPreview(input);
      assert.equal(good.passed, true, JSON.stringify(good));
      for (const viewport of ['desktop', 'mobile']) {
        const png = await fs.readFile(good[viewport]);
        assert.equal(png.readUInt32BE(16), viewport === 'desktop' ? 1280 : 390);
        assert.equal((await fs.stat(good[viewport])).mode & 0o777, 0o600);
        assert.deepEqual(new Set(good.clicksVerified[viewport].map(c => c.store)), new Set(['amazon', 'rakuten']));
        assert.ok(good.clicksVerified[viewport].some(c => c.placement === 'product_card'));
        assert.ok(good.clicksVerified[viewport].some(c => c.placement === 'comparison_table'));
      }
      input.bundle.article.content += '\n# 重複する見出し\n{{unknown:unresolved}}';
      input.bundle.products[0].imageUrl = '/missing-image.png';
      const bad = await renderPreview(input);
      assert.equal(bad.passed, false);
      for (const condition of ['one H1', 'unresolved shortcode', 'image failed'])
        assert.ok(bad.failures.some(f => f.includes(condition)), JSON.stringify(bad));
    } finally { await fs.rm(temp, { recursive: true, force: true }); }
  });


const imageBytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC', 'base64');
const digest = body => createHash('sha256').update(body).digest('hex');
function imageBundle() {
  const b = request().bundle;
  b.products[0].imageUrl = 'https://images.example/tent.png';
  b.images = [{ productId: 'preview-p1', url: b.products[0].imageUrl, sha256: digest(imageBytes), size: imageBytes.length, verified: true }];
  return b;
}
function fakeRoute(url, type = 'image', navigation = false) {
  const actions = [];
  return { actions, request: () => ({ url: () => url, resourceType: () => type, isNavigationRequest: () => navigation }),
    continue: async () => actions.push(['continue']), abort: async () => actions.push(['abort']),
    fulfill: async data => actions.push(['fulfill', data]) };
}

test('route permits exact localhost origin, aborts external navigation/scripts, fulfills only checked image bytes', async () => {
  const failures = [], navigations = [], calls = [];
  const handler = createRequestHandler('http://127.0.0.1:4444', imageBundle(), { failures, navigations,
    imageFetcher: async url => { calls.push(url); return { body: imageBytes, contentType: 'image/png' }; } });
  for (const [url, type, nav, action] of [
    ['http://127.0.0.1:4444/_next/a.js', 'script', false, 'continue'],
    ['http://127.0.0.1:5555/a.png', 'image', false, 'abort'],
    ['https://www.amazon.co.jp/dp/B012345678', 'document', true, 'abort'],
    ['https://images.example/code.js', 'script', false, 'abort'],
    ['https://images.example/tent.png', 'image', false, 'fulfill'],
  ]) {
    const route = fakeRoute(url, type, nav); await handler(route); assert.equal(route.actions[0][0], action);
    if (action === 'fulfill') assert.deepEqual(route.actions[0][1].body, imageBytes);
  }
  assert.equal(calls.length, 1); assert.equal(navigations.length, 1);
});

test('image route rejects unknown URLs, changed same-URL bytes, invalid types, oversize and fetch errors without raw secrets', async () => {
  for (const mode of ['unknown', 'changed', 'type', 'oversize', 'error', 'proof']) {
    const failures = [], b = imageBundle();
    if (mode === 'proof') b.images = [];
    const handler = createRequestHandler('http://127.0.0.1:4444', b, { failures, imageFetcher: async () => {
      if (mode === 'error') throw Error('secret-token-reflection');
      return { body: mode === 'changed' ? Buffer.from('changed') : mode === 'oversize' ? Buffer.alloc(8 * 1024 * 1024 + 1) : imageBytes,
        contentType: mode === 'type' ? 'text/html' : 'image/png' };
    } });
    const route = fakeRoute('https://images.example/' + (mode === 'unknown' ? 'unknown.png' : 'tent.png'));
    await handler(route); assert.equal(route.actions[0][0], 'abort'); assert.ok(failures.length);
    assert.ok(!JSON.stringify(failures).includes('secret-token-reflection'));
  }
});

test('resized CDN requests are fulfilled using original bound/hash-checked bytes with cache shared across viewports', async () => {
  const b = imageBundle(), url = 'https://thumbnail.image.rakuten.co.jp/a.jpg?_ex=128x128';
  b.products[0].imageUrl = b.images[0].url = url;
  let calls = 0; const cache = new Map();
  for (const size of [800, 1200]) {
    const handler = createRequestHandler('http://127.0.0.1:4444', b, { cache, failures: [], imageFetcher: async original => {
      assert.equal(original, url); calls++; return { body: imageBytes, contentType: 'image/png' };
    } });
    const route = fakeRoute('https://thumbnail.image.rakuten.co.jp/a.jpg?_ex=' + size + 'x' + size);
    await handler(route); assert.equal(route.actions[0][0], 'fulfill');
  }
  assert.equal(calls, 1);
});

test('real Python image helper rejects HTTP, private literals and credentials without making HTTP connections', async () => {
  for (const url of ['http://public.example/a.png', 'https://127.0.0.1/a.png', 'https://[::1]/a.png', 'https://user:secret@public.example/a.png'])
    await assert.rejects(fetchPublicImage(url), /^Error: secure image fetch failed$/);
});

test('real Python image transport checks public DNS and every redirect before connecting', () => {
  const code = `import sys,json
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from catalog import Catalog
pub=[(2,1,6,'',('8.8.8.8',443))]; private=[(2,1,6,'',('10.0.0.1',443))]
with patch('catalog.socket.getaddrinfo',side_effect=[pub,private]) as dns, patch('catalog._PinnedHTTPS') as conn:
 r=conn.return_value.getresponse.return_value;r.status=302;r.getheaders.return_value=[('location','https://redirect.example/image.png')];r.read.return_value=b''
 try: Catalog({}).request('https://public.example/image.png')
 except Exception: pass
 else: raise AssertionError('private redirect accepted')
 assert dns.call_count==2 and conn.call_count==1
 print('redirect-rechecked')
`;
  const result = spawnSync('python3', ['-B', '-c', code, path.join(repo, 'scripts/editorial')], { encoding: 'utf8', env: { PATH: '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin', PYTHONDONTWRITEBYTECODE: '1' } });
  assert.equal(result.status, 0, result.stderr); assert.equal(result.stdout.trim(), 'redirect-rechecked');
});

test('real render uses fulfilled external approved bytes and blocks a replaced image',
  { skip: process.env.RUN_RENDER_TESTS !== '1', timeout: 300000 }, async () => {
    const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'render-external-integration-'));
    try {
      const input = request(path.join(temp, 'privateoutput')); input.bundle = imageBundle();
      if (process.env.RENDER_DEPS) input.dependenciesRoot = process.env.RENDER_DEPS;
      let fetched = 0;
      const good = await renderPreview(input, { imageFetcher: async () => { fetched++; return { body: imageBytes, contentType: 'image/png' }; } });
      assert.equal(good.passed, true, JSON.stringify(good)); assert.equal(fetched, 1);
      const bad = await renderPreview(input, { imageFetcher: async () => ({ body: Buffer.from('replaced'), contentType: 'image/png' }) });
      assert.equal(bad.passed, false); assert.ok(bad.failures.some(f => f.includes('image')));
    } finally { await fs.rm(temp, { recursive: true, force: true }); }
  });


test('real image helper framing returns validated actual bytes and hash with no credential environment', () => {
  const code = `import sys,base64,os
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from catalog import Catalog
body=base64.b64decode(sys.argv[3])
assert not any(k in os.environ for k in ('SUPABASE_SERVICE_ROLE_KEY','BRAVE_API_KEY','HTTPS_PROXY','ANTHROPIC_API_KEY','GEMINI_API_KEY'))
with patch.object(Catalog,'request',return_value={'headers':{'content-type':'image/png'},'body':body}):
 exec(sys.argv[2])
`;
  const result = spawnSync('python3', ['-I', '-B', '-c', code, path.join(repo, 'scripts/editorial'), IMAGE_HELPER, imageBytes.toString('base64')], {
    input: JSON.stringify({ url: 'https://images.example/tent.png' }), env: { PATH: '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin', TZ: 'Asia/Tokyo' },
  });
  assert.equal(result.status, 0, result.stderr.toString());
  const split = result.stdout.indexOf(10); assert.ok(split > 0);
  const header = JSON.parse(result.stdout.subarray(0, split));
  assert.equal(header.sha256, digest(imageBytes)); assert.equal(header.size, imageBytes.length);
  assert.deepEqual(result.stdout.subarray(split + 1), imageBytes);
});


test('localhost image optimizer cannot bypass the external image verifier', async () => {
  const failures = []; let calls = 0;
  const handler = createRequestHandler('http://127.0.0.1:4444', imageBundle(), { failures, imageFetcher: async url => {
    assert.equal(url, 'https://images.example/tent.png'); calls++;
    return { body: imageBytes, contentType: 'image/png' };
  } });
  const good = fakeRoute('http://127.0.0.1:4444/_next/image?url=https%3A%2F%2Fimages.example%2Ftent.png&w=800&q=75');
  await handler(good); assert.equal(good.actions[0][0], 'fulfill');
  const bad = fakeRoute('http://127.0.0.1:4444/_next/image?url=https%3A%2F%2F127.0.0.1%2Fprivate&w=800&q=75');
  await handler(bad); assert.equal(bad.actions[0][0], 'abort'); assert.equal(calls, 1); assert.ok(failures.length);
});
