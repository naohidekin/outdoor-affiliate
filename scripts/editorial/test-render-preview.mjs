/** node --test scripts/editorial/test-render-preview.mjs
 * RUN_RENDER_TESTS=1 enables real Next/Chromium integration (no API keys).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { childEnvironment, validateInput, expectedMerchants, verifyClick, prepareApp, renderPreview, privateOutputDirectory } from './render-preview.mjs';

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
