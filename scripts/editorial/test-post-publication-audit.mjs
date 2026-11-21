import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { chromium } from 'playwright';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { auditPublicPage, approvedHeadings, PUBLIC_GET_HELPER } from './post-publication-audit.mjs';

const amazon = 'https://www.amazon.co.jp/dp/B012345678?tag=owner-22';
const rakuten = 'https://hb.afl.rakuten.co.jp/ichiba/owner/shop';
const image = 'https://images.example/stove.png';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
function fixture(extra = '') {
const content = '## Visible heading\n\nApproved text.';
  const digest = createHash('sha256').update(content).digest('hex');
  return { url: 'https://camp-gear-lab.com/articles/stove', bundle: {
    article: { slug: 'stove', title: 'Approved title', content },
    products: [{ id: 'p1', name: 'SOTO ST-310', brand: 'SOTO', imageUrl: image, amazonUrl: amazon, affiliateUrl: rakuten }], images: [],
  }, html: `<!doctype html><html><head><style>body{margin:0} .article-body{min-height:1600px} img{width:40px;height:40px}</style></head>
<body><main><article data-review-content-sha256="${digest}"><h1>Approved title</h1><div class="article-body"><div class="prose"><h2>Visible heading</h2><p>Approved text.</p>${extra}</div></div>
    <details><summary>Hidden links</summary><a href="${amazon}" target="_blank">hidden</a></details>
    <img loading="lazy" src="${image}"><a href="${amazon}" target="_blank" onclick="fetch('/api/track-click',{method:'POST',body:'{}'});navigator.sendBeacon('/api/click','{}')">Amazon</a>
    <a href="${rakuten}" target="_blank">Rakuten</a></article></main></body></html>` };
}

function intentionalAbsenceFixture(extra = '') {
  const input = fixture();
  input.bundle.products[0].amazonUrl = '';
  input.intentionalAbsences = [{ productId: 'p1', productIndex: 0, productName: 'SOTO ST-310', brand: 'SOTO',
    channel: 'amazon', oldHref: amazon, remainingChannel: 'rakuten', remainingHref: rakuten, status: 'NA' }];
  input.html = input.html
    .replace(`<details><summary>Hidden links</summary><a href="${amazon}" target="_blank">hidden</a></details>`, '')
    .replace(`<a href="${amazon}" target="_blank" onclick="fetch('/api/track-click',{method:'POST',body:'{}'});navigator.sendBeacon('/api/click','{}')">Amazon</a>`, '')
    .replace(`<a href="${rakuten}" target="_blank">Rakuten</a>`,
      `<div class="product-card"><h3>SOTO ST-310</h3><a href="${rakuten}" aria-label="SOTO ST-310の価格・在庫を楽天市場で確認（新しいタブ）" target="_blank">Rakuten</a></div>${extra}`);
  return input;
}

function nonproductFixture(extra = '') {
  const content = '## 手順\n\n汚れを落とし、十分に乾かします。\n\n[テントの記事一覧](/categories/tent)';
  const digest = createHash('sha256').update(content).digest('hex');
  const imageHash = createHash('sha256').update(png).digest('hex');
  const receiptHash = '91022beb32baf836592d38c866d230a6328949aa4358d06b04eaf9629dfe4036';
  const sourceReceiptSha256 = 'ec7c19d069f5d651fb6569481606c81c7331281ccdcc49ba4afe5be1c6478dab';
  const sourceId = 'public:coleman-care', imageId = `illustration:${imageHash.slice(0, 20)}`;
  return { url: 'https://camp-gear-lab.com/articles/tent-care', bundle: {
    article: { slug: 'tent-care', title: 'テントをしまう前の確認手順', content, productIds: [], eyecatch: image,
      generationMeta: { editorialContext: { schemaVersion: 1, articleType: 'nonproduct', sourceApplicability: 'verified_public_references',
        commerceApplicability: 'not_applicable', imageApplicability: 'owned_illustration', sourceIds: [sourceId], sourceReceiptSha256,
        imageProofIds: [imageId] } } },
    products: [], references: [{ id: sourceId, kind: 'public-primary', url: 'https://www.coleman.co.jp/customersupport/faq/',
      canonicalUrl: 'https://www.coleman.co.jp/customersupport/faq/', title: 'Coleman FAQ', excerpt: '汚れを落として十分に乾燥させます。',
      claimScope: 'tent-care', checkedAt: '2026-11-16T10:00:00+09:00', httpStatus: 200, receiptSha256: receiptHash,
      excerptSha256: createHash('sha256').update('汚れを落として十分に乾燥させます。').digest('hex'), scope: 'tent-care' }],
    images: [{ id: imageId, role: 'eyecatch', ownership: 'owned_editorial_illustration', depictsRealProduct: false, referenceIds: [sourceId],
      compositionSha256: 'c'.repeat(64), url: image, finalUrl: image, sha256: imageHash, size: png.length, contentType: 'image/png',
      width: 1200, height: 630, verified: true, checkedAt: '2026-11-16T10:05:00+09:00',
      rendererEvidence: { passed: true, evidencePassed: true, version: 'editorial-illustration-v1', width: 1200, height: 630,
        pngSha256: imageHash, bytes: png.length, contentHash: 'c'.repeat(64), sourceIds: [sourceId], sourceReceiptSha256, networkRequests: 0 } }],
    commercialRoute: { status: 'not_applicable', reason: 'verified_nonproduct_article', verifiedBy: 'deterministic_contract_v1' },
  }, html: `<!doctype html><html><head><style>.article-body{min-height:1000px}img{width:600px;max-width:100%;height:auto}</style></head><body><main>` +
    `<article data-review-content-sha256="${digest}"><h1>テントをしまう前の確認手順</h1><div class="article-body"><div class="prose">` +
    `<h2>手順</h2><p>汚れを落とし、十分に乾かします。</p><p><a href="/categories/tent">テントの記事一覧</a></p>${extra}</div></div>` +
    `<img src="${image}" alt="テント保管手順の図解"></article></main></body></html>` };
}

test('headings ignore fenced and indented code and retain actual H2', () => {
  assert.deepEqual(approvedHeadings('## A\n```md\n## B\n```\n    ## C\nD\n---\n## **E**'), ['A', 'D', 'E']);
});

test('fixed browser helper refuses subdomain redirect before contacting it', () => {
  // Exercise the actual fixed helper and real Catalog policy with an offline
  // transport only. No DNS or network is used, including on the rejected hop.
  const setup = `import sys,json,atexit
sys.path.insert(0,sys.argv[1])
import catalog
calls=[]
def fetch(url,headers,timeout):
 calls.append(url)
 return {'status':302,'headers':{'location':'https://unapproved.images.example/product.png'},'body':b''}
Original=catalog.Catalog
class OfflineCatalog(Original):
 def __init__(self,env): super().__init__(env,fetcher=fetch)
catalog.Catalog=OfflineCatalog
atexit.register(lambda:sys.stderr.write(json.dumps(calls)))
`;
  const result = spawnSync('python3', ['-I', '-B', '-c', setup + PUBLIC_GET_HELPER,
    fileURLToPath(new URL('.', import.meta.url))], {
    input: JSON.stringify({ url: 'https://images.example/product.png', domains: ['images.example'] }),
    encoding: 'utf8', timeout: 5000, env: { PATH: process.env.PATH || '/usr/bin:/bin', TZ: 'Asia/Tokyo' },
  });
  assert.equal(result.status, 1);
  assert.deepEqual(JSON.parse(result.stderr), ['https://images.example/product.png']);
  assert.equal(result.stdout, '');
});

test('unchanged hash and headings cannot hide changed prose or hidden product image', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [mutate, reason] of [
      [html => html.replace('Approved text.', 'Changed paragraph.'), 'approved_prose_mismatch'],
      [html => html.replace('<img loading=', '<img style="display:none" loading='), 'approved_product_image_not_rendered'],
    ]) {
      const input = fixture(); input.html = mutate(input.html);
      const result = await auditPublicPage(input, { browser, fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
      assert.ok(result.checks.some(c => c.status === 'failed' && c.reason === reason), reason);
    }
  } finally { await browser.close(); }
});

test('approved external images use only exact approved hostname redirect domain', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const result = await auditPublicPage(fixture(), { browser, fetcher: async (url, domains) => {
      assert.deepEqual(domains, ['images.example']);
      return { body: png, contentType: 'image/png', url };
    } });
    assert.deepEqual(result.checks.filter(c => c.status !== 'passed'), []);
  } finally { await browser.close(); }
});

test('offline Chromium: lazy images, visible exact links, popup first request, no measurement transport', async () => {
  const browser = await chromium.launch({ headless: true });
  const gets = [];
  try {
    const result = await auditPublicPage(fixture(), { browser, fetcher: async url => {
      gets.push(url);
      assert.equal(url, image);
      return { body: png, contentType: 'image/png', url };
    } });
    assert.deepEqual(result.checks.filter(c => c.status !== 'passed'), [], result);
    assert.deepEqual(gets, [image]);
    assert.equal(result.checks.filter(c => c.reason === 'exact_approved_navigation_intercepted').length, 4);
  } finally { await browser.close(); }
});

test('strict nonproduct audit records merchant NA in both viewports while all content, image, paragraph, and internal-link checks still pass', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const result = await auditPublicPage(nonproductFixture(), { browser,
      fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    assert.deepEqual(result.commercialRoute, { status: 'not_applicable', measured: false, reason: 'verified_nonproduct_article' });
    for (const viewport of ['desktop', 'mobile']) {
      assert.deepEqual(result.checks.find(c => c.name === `${viewport}.merchant`), {
        name: `${viewport}.merchant`, status: 'not_applicable', reason: 'verified_nonproduct_article',
      });
      for (const suffix of ['binding', 'body', 'prose', 'title', 'heading.0', 'images', 'eyecatch', 'paragraphs', 'internal_links', 'overflow', viewport])
        assert.equal(result.checks.find(c => c.name === `${viewport}.${suffix}` || c.name === suffix)?.status, 'passed', `${viewport}.${suffix}`);
    }
  } finally { await browser.close(); }
});

test('nonproduct audit rejects forged metadata or merchant links instead of omitting merchant checks', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const forged = nonproductFixture('<a href="https://www.amazon.co.jp/dp/B000000001">merchant</a>');
    const withMerchant = await auditPublicPage(forged, { browser, fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const viewport of ['desktop', 'mobile'])
      assert.equal(withMerchant.checks.find(c => c.name === `${viewport}.merchant`)?.status, 'failed');
    const badMeta = nonproductFixture();
    badMeta.bundle.article.generationMeta.editorialContext.sourceReceiptSha256 = '0'.repeat(64);
    const rejected = await auditPublicPage(badMeta, { browser, fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    assert.ok(rejected.checks.some(c => c.name === 'browser' && c.status === 'unverified'));
  } finally { await browser.close(); }
});

test('nonproduct audit rejects an official link whose visible text stayed unchanged', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const input = nonproductFixture();
    input.bundle.article.content += '\n\n[公式FAQ](https://www.coleman.co.jp/customersupport/faq/)';
    input.html = input.html.replace(/data-review-content-sha256="[^"]+"/,
      `data-review-content-sha256="${createHash('sha256').update(input.bundle.article.content).digest('hex')}"`)
      .replace('</div></div>', '<p><a href="https://www.coleman.co.jp/wrong/">公式FAQ</a></p></div></div>');
    const result = await auditPublicPage(input, { browser, fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const viewport of ['desktop', 'mobile'])
      assert.equal(result.checks.find(c => c.name === `${viewport}.approved_links`)?.status, 'failed');
  } finally { await browser.close(); }
});

test('offline Chromium fails hidden body, absent headings, tags and overflow', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const input = fixture('<p>{{price:p1}}</p><div style="width:2000px">overflow</div>');
    input.html = input.html.replace('<h2>Visible heading</h2>', '<h2 style="display:none">Visible heading</h2>');
    const result = await auditPublicPage(input, { browser, fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const reason of ['approved_heading_missing_or_hidden', 'unresolved_product_tags', 'horizontal_overflow']) {
      assert.ok(result.checks.some(c => c.status === 'failed' && c.reason === reason), reason);
    }
    const hidden = fixture();
    hidden.html = hidden.html.replace('class="article-body"', 'class="article-body" style="display:none"');
    const result2 = await auditPublicPage(hidden, { browser, fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    assert.ok(result2.checks.some(c => c.reason === 'article_body_missing_or_hidden'));
  } finally { await browser.close(); }
});

test('intentional missing purchase channel needs strict absence proof in both viewports', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const result = await auditPublicPage(intentionalAbsenceFixture(), { browser,
      fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const viewport of ['desktop', 'mobile']) {
      assert.deepEqual(result.checks.find(c => c.name === `${viewport}.purchase_absent.0.amazon`), {
        name: `${viewport}.purchase_absent.0.amazon`, status: 'passed', reason: 'approved_purchase_channel_absent',
      });
    }
  } finally { await browser.close(); }
});

test('new article intentional absence permits an empty baseline URL without weakening DOM proof', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const input = intentionalAbsenceFixture();
    input.intentionalAbsences[0].oldHref = '';
    const result = await auditPublicPage(input, { browser,
      fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const viewport of ['desktop', 'mobile']) {
      assert.equal(result.checks.find(c => c.name === `${viewport}.purchase_absent.0.amazon`)?.status, 'passed');
    }
  } finally { await browser.close(); }
});

test('hidden old URL and replacement merchant links reject every viewport', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const extra of [
      `<a hidden href="${amazon}">old</a>`,
      '<a hidden href="https://www.amazon.co.jp/dp/B000000001?tag=owner-22" aria-label="SOTO ST-310の価格・在庫をAmazonで確認（新しいタブ）">replacement</a>',
    ]) {
      const result = await auditPublicPage(intentionalAbsenceFixture(extra), { browser,
        fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
      for (const viewport of ['desktop', 'mobile']) {
        const proof = result.checks.find(c => c.name === `${viewport}.purchase_absent.0.amazon`);
        assert.equal(proof?.status, 'failed', `${viewport}: ${extra}`);
      }
    }
  } finally { await browser.close(); }
});

test('unrelated product merchant links do not create a false product absence failure', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const other = 'https://www.amazon.co.jp/dp/B000000002?tag=owner-22';
    const input = intentionalAbsenceFixture(`<div class="product-card"><h3>Other product</h3><a href="${other}" target="_blank" aria-label="Other productの価格・在庫をAmazonで確認（新しいタブ）">Amazon</a></div>`);
    input.bundle.products.push({ id: 'p2', name: 'Other product', imageUrl: image, amazonUrl: other, affiliateUrl: '' });
    const result = await auditPublicPage(input, { browser,
      fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const viewport of ['desktop', 'mobile']) {
      assert.equal(result.checks.find(c => c.name === `${viewport}.purchase_absent.0.amazon`)?.status, 'passed', JSON.stringify(result));
    }
  } finally { await browser.close(); }
});

test('an approved other-product URL cannot hide in an identified comparison column', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const other = 'https://www.amazon.co.jp/dp/B000000003?tag=owner-22';
    const table = `<table class="product-comparison"><thead><tr><th scope="col">比較項目</th><th scope="col">SOTO ST-310</th></tr></thead><tbody><tr><th scope="row">販売店</th><td><a href="${other}" target="_blank">wrong approved product</a></td></tr></tbody></table>`;
    const input = intentionalAbsenceFixture(table);
    input.bundle.products.push({ id: 'p2', name: 'Other product', imageUrl: image, amazonUrl: other, affiliateUrl: rakuten });
    const result = await auditPublicPage(input, { browser,
      fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const viewport of ['desktop', 'mobile']) {
      assert.equal(result.checks.find(c => c.name === `${viewport}.purchase_absent.0.amazon`)?.status, 'failed');
    }
  } finally { await browser.close(); }
});

test('every RecommendationCTA product row must retain the approved remaining store', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const row = (links, alt = 'SOTO ST-310') => `<div class="flex flex-col sm:flex-row sm:items-center gap-3 px-5 py-4"><div><img src="${image}" alt="${alt}"><p class="text-base font-semibold">SOTO ST-310</p></div><div>${links}</div></div>`;
    const remaining = `<a href="${rakuten}" target="_blank" aria-label="SOTO ST-310の価格・在庫を楽天市場で確認（新しいタブ）">Rakuten</a>`;
    for (const [markup, expected] of [
      [row('<p>販売店リンクは現在掲載していません。</p>'), 'failed'],
      [row(remaining), 'passed'],
      [row(remaining, 'Wrong product'), 'failed'],
    ]) {
      const result = await auditPublicPage(intentionalAbsenceFixture(markup), { browser,
        fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
      for (const viewport of ['desktop', 'mobile']) {
        assert.equal(result.checks.find(c => c.name === `${viewport}.purchase_absent.0.amazon`)?.status,
          expected, `${viewport}: ${markup}`);
      }
    }
  } finally { await browser.close(); }
});

test('ambiguous missing product container never passes absence from an empty selector', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const input = intentionalAbsenceFixture();
    input.html = input.html.replace('<div class="product-card"><h3>SOTO ST-310</h3>', '<div><p>SOTO ST-310</p>');
    const result = await auditPublicPage(input, { browser,
      fetcher: async url => ({ body: png, contentType: 'image/png', url }) });
    for (const viewport of ['desktop', 'mobile']) {
      assert.equal(result.checks.find(c => c.name === `${viewport}.purchase_absent.0.amazon`)?.status, 'failed');
    }
  } finally { await browser.close(); }
});
