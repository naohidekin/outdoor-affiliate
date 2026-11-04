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
    products: [{ id: 'p1', imageUrl: image, amazonUrl: amazon, affiliateUrl: rakuten }], images: [],
  }, html: `<!doctype html><html><head><style>body{margin:0} .article-body{min-height:1600px} img{width:40px;height:40px}</style></head>
<body><main><article data-review-content-sha256="${digest}"><h1>Approved title</h1><div class="article-body"><div class="prose"><h2>Visible heading</h2><p>Approved text.</p>${extra}</div></div>
    <details><summary>Hidden links</summary><a href="${amazon}" target="_blank">hidden</a></details>
    <img loading="lazy" src="${image}"><a href="${amazon}" target="_blank" onclick="fetch('/api/track-click',{method:'POST',body:'{}'});navigator.sendBeacon('/api/click','{}')">Amazon</a>
    <a href="${rakuten}" target="_blank">Rakuten</a></article></main></body></html>` };
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
