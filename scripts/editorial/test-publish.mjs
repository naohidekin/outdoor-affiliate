import test from 'node:test';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { bundleHash, articleRow, productRow, execute, verifyPublicHTML, parseArguments, loadEnv, productionDependencies } from './publish.mjs';
import { withPublicationLock } from '../seo/article-guard.mjs';

function bundle() {
  return { article: { id: 'editorial-test', slug: 'test-slug', title: '新しいテント', categoryId: 'tent', content: '## 本文\n広告', excerpt: 'summary', author: 'ギア男', productIds: ['p1'], status: 'draft', createdAt: '2026-11-03T12:00:00+09:00', updatedAt: '2026-11-03T12:00:00+09:00', publishedAt: null },
    products: [{ id: 'p1', name: 'Tent T-100', brand: 'Maker', categoryId: 'tent', specs: { model: 'T-100' }, imageUrl: 'https://img.example/tent.jpg', affiliateUrl: 'https://item.rakuten.co.jp/a/b/', amazonUrl: '' }], images: [{ productId: 'p1', url: 'https://img.example/tent.jpg', sha256: createHash('sha256').update('approved-image-bytes').digest('hex'), size: 20, verified: true }] };
}
function harness(b = bundle()) {
  const state = { rows: [], products: b.products.map(productRow), writes: [], cleared: false, html: '' };
  const db = {
    async findArticles(id, slug) { return structuredClone(state.rows.filter(r => r.id === id || r.slug === slug)); },
    async getProducts() { return structuredClone(state.products); },
    async insertDraft(row) { state.writes.push('insert'); state.rows.push(structuredClone(row)); },
    async publishCAS(row, patch) {
      state.writes.push('patch');
      const found = state.rows.find(r => r.id === row.id && r.status === 'draft' && r.updated_at === row.updated_at);
      if (!found) return [];
      Object.assign(found, patch); return [structuredClone(found)];
    },
  };
  const deps = { db, imageDigest: async () => ({ sha256: createHash('sha256').update('approved-image-bytes').digest('hex'), size: 20, contentType: 'image/png' }), lock: async action => action(), now: () => '2026-11-03T12:01:00+09:00',
    async revalidate() { state.cleared = true; },
    async publicGet() { return state.html; } };
  return { b, state, deps, input: { bundle: b, revision: bundleHash(b) } };
}
function approval(revision) { return { revision, approverId: 'U-owner', evidence: { event: 'trusted-ledger-event' } }; }
function html(b) {
  return `<main data-review-content-sha256="${bundleHash(b.article.content, { contentOnly: true })}"><h1>${b.article.title}</h1><img src="/_next/image?url=${encodeURIComponent(b.products[0].imageUrl)}&amp;w=800"><a href="${b.products[0].affiliateUrl}">購入</a></main>`;
}

test('production minimal insert accepts empty 201 only with exact stage readback', async t => {
  const h = harness();
  let stored, inserts = 0, articleReads = 0, productReads = 0;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const target = new URL(url);
    if (options.method === 'POST') {
      assert.equal(options.headers.Prefer, 'return=minimal,handling=strict');
      stored = JSON.parse(options.body); inserts++;
      return new Response(null, { status: 201 });
    }
    if (target.pathname.endsWith('/products')) {
      productReads++;
      return Response.json(h.state.products);
    }
    articleReads++;
    return Response.json(stored ? [stored] : []);
  });
  const deps = productionDependencies({ SUPABASE_URL: 'https://db.example', SUPABASE_SERVICE_ROLE_KEY: 'test-only' });
  deps.lock = async action => action();
  const result = await execute({ ...h.input, action: 'stage' }, deps);
  assert.equal(result.status, 'draft');
  assert.equal(inserts, 1);
  assert.equal(articleReads, 2);
  assert.equal(productReads, 2);
  assert.equal(stored.generation_meta.editorialRuntime.revision, h.input.revision);
});

test('production empty 201 insert never bypasses absent, changed or failed readback', async t => {
  for (const mode of ['missing', 'changed', 'network']) {
    await t.test(mode, async t => {
      const h = harness();
      let stored, inserts = 0;
      t.mock.method(globalThis, 'fetch', async (url, options) => {
        if (options.method === 'POST') {
          stored = JSON.parse(options.body); inserts++;
          return new Response(null, { status: 201 });
        }
        if (new URL(url).pathname.endsWith('/products')) return Response.json(h.state.products);
        if (!stored) return Response.json([]);
        if (mode === 'network') throw new Error('test readback unavailable');
        return Response.json(mode === 'missing' ? [] : [{ ...stored, title: 'changed' }]);
      });
      const deps = productionDependencies({ SUPABASE_URL: 'https://db.example', SUPABASE_SERVICE_ROLE_KEY: 'test-only' });
      deps.lock = async action => action();
      await assert.rejects(execute({ ...h.input, action: 'stage' }, deps), /unknown: draft mutation requires reconciliation/);
      assert.equal(inserts, 1);
    });
  }
});

test('production GET and CAS still reject empty 201 and inserts reject malformed or failed replies', async t => {
  const deps = productionDependencies({ SUPABASE_URL: 'https://db.example', SUPABASE_SERVICE_ROLE_KEY: 'test-only' });
  const row = articleRow(bundle().article, bundleHash(bundle()));
  const stub = t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 201 }));
  await assert.rejects(deps.db.findArticles(row.id, row.slug), /publisher response invalid/);
  await assert.rejects(deps.db.getProducts(['p1']), /publisher response invalid/);
  await assert.rejects(deps.db.publishCAS({ ...row, xmin: '100' }, { status: 'published' }), /publisher response invalid/);
  stub.mock.mockImplementation(async () => new Response('not JSON', { status: 201 }));
  await assert.rejects(deps.db.insertDraft(row), /publisher response invalid/);
  stub.mock.mockImplementation(async () => new Response(null, { status: 500 }));
  await assert.rejects(deps.db.insertDraft(row), /publisher HTTP failed/);
});

test('stage inserts only an absent identity, idempotent same revision, refuses stale/published', async () => {
  const h = harness();
  const result = await execute({ ...h.input, action: 'stage' }, h.deps);
  assert.equal(result.status, 'draft');
  assert.equal(h.state.rows[0].generation_meta.editorialRuntime.revision, h.input.revision);
  await execute({ ...h.input, action: 'stage' }, h.deps);
  assert.deepEqual(h.state.writes, ['insert']);
  h.state.rows[0].title = 'remote changed';
  await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps), /draft mismatch/);
  h.state.rows[0].status = 'published';
  await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps));
});

test('stage refuses slug conflict, changed catalog and arbitrary article fields', async () => {
  const h = harness(); h.state.rows.push({ id: 'other', slug: h.b.article.slug, status: 'draft' });
  await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps));
  h.state.rows = []; h.state.products[0].price = 1;
  await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps), /product mismatch/);
  assert.equal(h.state.writes.length, 0);
  const other = harness(); other.b.article.unsafe = true; other.input.revision = bundleHash(other.b);
  await assert.rejects(execute({ ...other.input, action: 'stage' }, other.deps), /unsupported article/);
});

test('publish requires bound approval, full draft match and exact product equality', async () => {
  const h = harness(); await execute({ ...h.input, action: 'stage' }, h.deps);
  for (const a of [null, approval('0'.repeat(64)), { revision: h.input.revision, approverId: 'U' }])
    await assert.rejects(execute({ ...h.input, action: 'publish', approval: a }, h.deps));
  h.state.rows[0].excerpt = 'drift';
  await assert.rejects(execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps), /draft mismatch/);
  assert.deepEqual(h.state.writes, ['insert']);
});

test('publish CAS readback, revalidation and actual public fields precede verified result', async () => {
  const h = harness(); await execute({ ...h.input, action: 'stage' }, h.deps); h.state.html = html(h.b);
  const result = await execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps);
  assert.equal(result.verified, true); assert.equal(h.state.cleared, true);
  assert.equal(result.readback.fingerprint, h.input.revision);
  assert.equal(result.remoteUpdatedAt, '2026-11-03T12:01:00+09:00');
  assert.deepEqual(h.state.writes, ['insert', 'patch']);
});

test('ambiguous mutation keeps durable canonical guard marker and never reports verified', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'editorial-publish-test-'));
  try {
    const h = harness(); h.deps.lock = action => withPublicationLock(root, action);
    h.deps.db.insertDraft = async () => { throw new Error('SERVICE-SECRET network reset'); };
    await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps), /unknown/);
    assert.equal(fs.existsSync(path.join(root, '.publication.in-flight.json')), true);
    await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps), /in-flight/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('CAS misses, DB drift, failed cache clear and stale HTML fail closed', async () => {
  for (const mode of ['cas', 'db', 'cache', 'html']) {
    const h = harness(); await execute({ ...h.input, action: 'stage' }, h.deps); h.state.html = html(h.b);
    if (mode === 'cas') h.deps.db.publishCAS = async () => [];
    if (mode === 'db') { const publish = h.deps.db.publishCAS; h.deps.db.publishCAS = async (...args) => { const result = await publish(...args); h.state.rows[0].tags = ['unexpected']; return result; }; }
    if (mode === 'cache') h.deps.revalidate = async () => { throw new Error('SECRET'); };
    if (mode === 'html') h.state.html = '<h1>stale</h1>';
    await assert.rejects(execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps), /unknown/);
  }
});

test('HTML proof requires real attributes and title, never script strings', () => {
  const b = bundle(); assert.equal(verifyPublicHTML(html(b), b), true);
  for (const text of [html(b).replace('<a href=', '<a data-href='), html(b).replace(b.article.title, 'wrong'),
    `<script>${html(b)}</script>`, html(b).replace('data-review-content-sha256', 'data-other')])
    assert.equal(verifyPublicHTML(text, b), false);
});

test('Python canonical JSON-only UTF8 revision; raw preserves floats and never reads paths', () => {
  const raw = '{"bundle":{"日本":"文","n":1.0,"small":1e-7,"nested":{"z":2,"a":1}}}';
  const expected = spawnSync('python3', ['-c', 'import sys,json,hashlib; b=json.load(sys.stdin)["bundle"];print(hashlib.sha256(json.dumps(b,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest())'], { input: raw, encoding: 'utf8' }).stdout.trim();
  assert.equal(bundleHash(JSON.parse(raw).bundle, { rawRequest: raw }), expected);
  assert.throws(() => bundleHash({ number: NaN }));
  assert.match(bundleHash({ path: '/does/not/exist', file_path: '/etc/passwd' }), /^[a-f0-9]{64}$/);
});

test('explicit dotenv file only parsed in memory and argument errors disclose no values', () => {
  assert.deepEqual(parseArguments(['stage', '--env-file', '/tmp/existing.env']), { action: 'stage', envFile: '/tmp/existing.env' });
  assert.throws(() => parseArguments(['--unsafe-override']));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'editorial-env-test-'));
  try {
    const file = path.join(root, '.env'); fs.writeFileSync(file, 'SUPABASE_SERVICE_ROLE_KEY="test-only"\nBRAVE_API_KEY=abc # comment\n');
    const env = loadEnv(file, {}); assert.equal(env.SUPABASE_SERVICE_ROLE_KEY, 'test-only'); assert.equal(env.BRAVE_API_KEY, 'abc');
    assert.deepEqual(Object.keys(env).sort(), ['BRAVE_API_KEY', 'SUPABASE_SERVICE_ROLE_KEY']);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('ledger-generated article identity is accepted for a new marked draft', async () => {
  const b = bundle(); b.article.id = 'article-' + 'a'.repeat(24);
  const h = harness(b); await execute({ ...h.input, action: 'stage' }, h.deps);
  assert.equal(h.state.rows[0].id, b.article.id);
});


test('Supabase UTC timestamp normalization is compared by instant across full article fields', async () => {
  const h = harness();
  const insert = h.deps.db.insertDraft;
  h.deps.db.insertDraft = async row => { await insert(row); for (const key of ['created_at', 'updated_at']) h.state.rows[0][key] = new Date(row[key]).toISOString(); };
  await execute({ ...h.input, action: 'stage' }, h.deps);
  await execute({ ...h.input, action: 'stage' }, h.deps);
  h.state.html = html(h.b);
  const publish = h.deps.db.publishCAS;
  h.deps.db.publishCAS = async (...args) => { const rows = await publish(...args); for (const row of h.state.rows) for (const key of ['updated_at', 'published_at']) row[key] = new Date(row[key]).toISOString(); return rows; };
  const result = await execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps);
  assert.equal(result.verified, true);
  assert.equal(result.remoteUpdatedAt, '2026-11-03T03:01:00.000Z');
});

test('existing catalog addedAt calendar date passes stage validation and still requires exact product readback', async () => {
  const b = bundle(); b.products[0].addedAt = '2026-04-22';
  const h = harness(b);
  assert.equal(productRow(b.products[0]).added_at, '2026-04-22');
  const result = await execute({ ...h.input, action: 'stage' }, h.deps);
  assert.equal(result.status, 'draft');
  assert.deepEqual(h.state.writes, ['insert']);
  h.state.products[0].added_at = '2026-04-23';
  await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps), /product mismatch/);
  assert.deepEqual(h.state.writes, ['insert']);
});

test('invalid catalog addedAt calendar date fails before stage mutation', async () => {
  const h = harness();
  h.b.products[0].addedAt = '2026-02-30';
  h.input.revision = bundleHash(h.b);
  await assert.rejects(execute({ ...h.input, action: 'stage' }, h.deps), /invalid calendar date/);
  assert.deepEqual(h.state.writes, []);
});


test('same image URL replaced bytes refuses publication before PATCH', async () => {
  const h = harness(); await execute({ ...h.input, action: 'stage' }, h.deps); h.state.html = html(h.b);
  h.deps.imageDigest = async () => ({ sha256: createHash('sha256').update('replaced-image-bytes').digest('hex'), size: 20, contentType: 'image/png' });
  await assert.rejects(execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps), /image bytes mismatch/);
  assert.deepEqual(h.state.writes, ['insert']); assert.equal(h.state.rows[0].status, 'draft');
});

test('all approved images must have verified hashes, size and product URL binding', async () => {
  for (const mode of ['missing', 'hash', 'size', 'url', 'verified']) {
    const b = bundle();
    if (mode === 'missing') b.images = [];
    if (mode === 'hash') b.images[0].sha256 = 'invalid';
    if (mode === 'size') b.images[0].size = 8 * 1024 * 1024 + 1;
    if (mode === 'url') b.images[0].url = 'https://img.example/other.jpg';
    if (mode === 'verified') b.images[0].verified = false;
    const h = harness(b); await execute({ ...h.input, action: 'stage' }, h.deps);
    await assert.rejects(execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps), /image/);
    assert.deepEqual(h.state.writes, ['insert']);
  }
});


test('image change after PATCH never yields verified publication', async () => {
  const h = harness(); await execute({ ...h.input, action: 'stage' }, h.deps); h.state.html = html(h.b);
  let count = 0; const approved = h.deps.imageDigest;
  h.deps.imageDigest = async url => ++count === 1 ? approved(url) : { sha256: '0'.repeat(64), size: 20, contentType: 'image/png' };
  await assert.rejects(execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps), /unknown/);
  assert.deepEqual(h.state.writes, ['insert', 'patch']);
});

test('social card requires exact unique OG and Twitter meta, not hydration or legacy image', () => {
  const b = bundle();
  b.article.generationMeta = { socialCard: { url: 'https://img.example/card.png' } };
  const tags = '<meta property="og:image" content="https://img.example/card.png"><meta name="twitter:image" content="https://img.example/card.png">';
  assert.equal(verifyPublicHTML(tags + html(b), b), true);
  for (const bad of ['', tags.replace('name="twitter:image"', 'name="other"'), tags.replace('card.png', 'wrong.png'), tags + '<meta property="og:image" content="https://img.example/legacy.png">', `<script>${tags}</script>`]) {
    assert.equal(verifyPublicHTML(bad + html(b), b), false);
  }
});

test('published card readback carries exact approved manifest only after metadata and bytes agree', async () => {
  const b = bundle();
  const manifest = { url: 'https://img.example/card.png', sha256: b.images[0].sha256, size: 20, contentType: 'image/png', width: 1200, height: 630, templateVersion: 'test-v1', sources: [{ productId: 'p1', sha256: b.images[0].sha256 }] };
  b.article.generationMeta = { socialCard: manifest };
  b.images.push({ ...manifest, role: 'social-card', verified: true });
  const h = harness(b);
  await execute({ ...h.input, action: 'stage' }, h.deps);
  h.state.html = `<meta property="og:image" content="${manifest.url}"><meta name="twitter:image" content="${manifest.url}">` + html(b);
  const result = await execute({ ...h.input, action: 'publish', approval: approval(h.input.revision) }, h.deps);
  assert.deepEqual(result.readback.socialCard, manifest);
  assert.equal(result.readback.verified, true);
});

test('production draft publication xmin CAS blocks same-timestamp concurrent body edits and never retries',async t=>{
 const {correctedDependencies}=await import('./corrected-publisher.mjs');
 for(const [name,constructor] of [['normal',productionDependencies],['corrected-inherited',correctedDependencies]]){
  await t.test(name,async t=>{
   const h=harness(),root=fs.mkdtempSync(path.join(os.tmpdir(),'draft-xmin-'));
   t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
   const original={...articleRow(h.b.article,h.input.revision),xmin:'100'};
   let stored=structuredClone(original),attempts=0,writes=0,publicReads=0,caches=0;const reads=[];
   t.mock.method(globalThis,'fetch',async(url,options)=>{
    const target=new URL(url);
    if(target.pathname.endsWith('/products'))return Response.json(h.state.products.map(p=>({...p,xmin:'42'})));
    assert.ok(target.pathname.endsWith('/articles'));
    if(options.method!=='PATCH'){reads.push(target);return Response.json([structuredClone(stored)]);}
    attempts++;
    // A different writer changes the body after the GET, keeping updated_at and
    // editorial marker identical. PostgreSQL advances xmin for that transaction.
    stored.content='Unapproved concurrent body';stored.xmin='101';
    const expected=target.searchParams.get('xmin');
    if(expected && expected!=='eq.'+stored.xmin)return Response.json([]);
    writes++;Object.assign(stored,JSON.parse(options.body));return Response.json([structuredClone(stored)]);
   });
   const deps=constructor({SUPABASE_URL:'https://db.example',SUPABASE_SERVICE_ROLE_KEY:'test-only'});
   deps.lock=fn=>withPublicationLock(root,fn);
   deps.imageDigest=h.deps.imageDigest;
   deps.revalidate=async()=>{caches++;};deps.publicGet=async()=>{publicReads++;return html(h.b);};
   const request={...h.input,action:'publish',approval:approval(h.input.revision)};
   await assert.rejects(execute(request,deps),/reconciliation/);
   assert.equal(attempts,1);assert.equal(writes,0);
   assert.equal(stored.status,'draft');assert.equal(stored.published_at,null);
   assert.equal(stored.content,'Unapproved concurrent body');assert.equal(stored.updated_at,original.updated_at);
   assert.equal(publicReads,0);assert.equal(caches,0);
   assert.ok(reads.every(u=>u.searchParams.get('select').split(',').includes('xmin')));
   await assert.rejects(execute(request,deps),/in-flight/);assert.equal(attempts,1);
  });
 }
});

test('production publish CAS requires a fresh valid uint32 xmin before any REST mutation',async t=>{
 let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return Response.json([]);});
 const deps=productionDependencies({SUPABASE_URL:'https://db.example',SUPABASE_SERVICE_ROLE_KEY:'test-only'});
 const before=articleRow(bundle().article,bundleHash(bundle()));
 for(const xmin of [undefined,null,'','-1','4294967296','1.2','1e3','not-a-version'])
  await assert.rejects(deps.db.publishCAS({...before,xmin},{status:'published'}),/version/);
 assert.equal(calls,0);
});
