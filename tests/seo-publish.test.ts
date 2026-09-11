/* eslint-disable @typescript-eslint/no-explicit-any -- Deliberately mutable fault-injection fixtures model malformed manifests and database responses. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { articleHash, manifestHash, publishExperiment, verifyPublicHtml, supabaseAdapter } from '../scripts/seo/publish.mjs';
import { guardArticleRows, withPublicationLock } from '../scripts/seo/article-guard.mjs';

function fixture(t: { after: (fn: () => void) => void }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'seo-publish-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const articlesFile = path.join(root, 'articles.json');
  const row = { id: 'article-1', slug: 'tent', status: 'published', title: 'Old title', content: 'Old body', excerpt: 'summary', meta_description: 'old meta', tags: [], faqs: [], product_ids: ['product-1'], category_id: 'tents', updated_at: '2026-09-01T12:00:00+09:00', quality_score: 99 };
  const local = { ...row, metaDescription: row.meta_description, productIds: row.product_ids, updatedAt: row.updated_at };
  // Local source is camelCase, with unrelated data preserved exactly.
  delete (local as Partial<typeof row>).meta_description;
  delete (local as Partial<typeof row>).product_ids;
  delete (local as Partial<typeof row>).updated_at;
  fs.writeFileSync(articlesFile, JSON.stringify([local, { id: 'other', title: 'untouched' }]));
  const manifest: any = { experimentId: 'exp-1', articleId: row.id, slug: row.slug, baseline: { updated_at: row.updated_at, hash: articleHash(row) }, patches: { title: 'New title' }, evidence: [{ url: 'https://camp-gear-lab.com/articles/tent', note: 'Editorial evidence' }] };
  function approve() { manifest.approval = { model: 'gpt-6-astra', decision: 'approved', evidenceReviewed: true, noInventedClaims: true, manifestHash: manifestHash(manifest) }; }
  approve();
  let remote: any = structuredClone(row);
  let writes = 0;
  let requests = 0;
  const db = { read: async () => structuredClone(remote), compareAndSwap: async (_id: string, time: string, patch: any) => { assert.equal(time, remote.updated_at); writes++; remote = { ...remote, ...patch }; return structuredClone(remote); } };
  const options: any = { root, articlesFile, db, revalidateSecret: 'test-only', authorize: async () => {}, now: () => '2026-09-11T12:00:00+09:00', fetchImpl: async () => { requests++; return { ok: true, status: 200, text: async () => '<html><h1>New title</h1></html>' }; } };
  return { root, row, manifest, options, approve, get remote() { return remote; }, set remote(value) { remote = value; }, get writes() { return writes; }, get requests() { return requests; } };
}

test('dry run validates and has no local, DB, state, or HTTP writes', async t => {
  const f = fixture(t);
  const before = fs.readFileSync(f.options.articlesFile, 'utf8');
  const result = await publishExperiment(f.manifest, f.options);
  assert.equal(result.status, 'dry_run');
  assert.equal(f.writes, 0); assert.equal(f.requests, 0);
  assert.equal(fs.readFileSync(f.options.articlesFile, 'utf8'), before);
  assert.equal(fs.existsSync(path.join(f.root, 'snapshots')), false);
});
test('refuses stale hash and timestamp, missing timestamp, unapproved content, forbidden fields', async t => {
  const f = fixture(t);
  f.remote = { ...f.remote, title: 'External edit' };
  await assert.rejects(publishExperiment(f.manifest, f.options), /baseline changed/);
  f.remote = { ...f.row, updated_at: null };
  await assert.rejects(publishExperiment(f.manifest, f.options), /updated_at missing/);
  f.remote = { ...f.row, updated_at: '2026-09-02T12:00:00+09:00' };
  await assert.rejects(publishExperiment(f.manifest, f.options), /baseline changed/);
  f.remote = { ...f.row };
  f.manifest.patches.title = 'Unapproved';
  await assert.rejects(publishExperiment(f.manifest, f.options), /Astra approval/);
  f.manifest.patches.slug = 'bad'; f.approve();
  await assert.rejects(publishExperiment(f.manifest, f.options), /Only article editorial fields/);
  assert.equal(f.writes, 0);
});
test('apply requires revalidation secret and state authorization before writes', async t => {
  const f = fixture(t);
  await assert.rejects(publishExperiment(f.manifest, { ...f.options, apply: true, revalidateSecret: '' }), /REVALIDATE_SECRET/);
  assert.equal(f.writes, 0);
  // Simulate explicit operator clearance after proving no DB request was sent.
  fs.unlinkSync(path.join(f.root, '.publication.in-flight.json'));
  await assert.rejects(publishExperiment(f.manifest, { ...f.options, apply: true, authorize: undefined }), /Persistent experiment approval/);
  assert.equal(f.writes, 0);
});
test('selective apply snapshots before/after, preserves other fields and rows, verifies public body', async t => {
  const f = fixture(t);
  const result = await publishExperiment(f.manifest, { ...f.options, apply: true });
  assert.equal(result.status, 'verified');
  assert.equal(f.remote.title, 'New title');
  assert.equal(f.remote.quality_score, 99); assert.deepEqual(f.remote.product_ids, ['product-1']);
  const local = JSON.parse(fs.readFileSync(f.options.articlesFile, 'utf8'));
  assert.deepEqual(local[1], { id: 'other', title: 'untouched' });
  assert.equal(local[0].title, 'New title');
  assert.equal(f.writes, 1);
  const journal = JSON.parse(fs.readFileSync(result.snapshotFile, 'utf8'));
  assert.equal(journal.before.title, 'Old title'); assert.equal(journal.after.title, 'New title');
});
test('failed public verification stays pending and retry never reapplies DB', async t => {
  const f = fixture(t);
  const result = await publishExperiment(f.manifest, { ...f.options, apply: true, fetchImpl: async () => ({ ok: true, status: 200, text: async () => '<h1>Old title</h1>' }) });
  assert.equal(result.status, 'verification_pending'); assert.equal(f.writes, 1);
  const retried = await publishExperiment(f.manifest, { ...f.options, apply: true });
  assert.equal(retried.status, 'verified'); assert.equal(f.writes, 1);
});
test('local concurrent edit after DB write remains pending and is not overwritten', async t => {
  const f = fixture(t);
  const result = await publishExperiment(f.manifest, { ...f.options, apply: true, onStatus: async (status: string) => {
    if (status === 'remote_applied') {
      const articles = JSON.parse(fs.readFileSync(f.options.articlesFile, 'utf8'));
      articles[0].content = 'Concurrent local edit';
      fs.writeFileSync(f.options.articlesFile, JSON.stringify(articles));
    }
  } });
  assert.equal(result.status, 'verification_pending');
  assert.match(fs.readFileSync(f.options.articlesFile, 'utf8'), /Concurrent local edit/);
});
test('legacy guard skips protected article and refuses mismatches', async t => {
  const f = fixture(t);
  await publishExperiment(f.manifest, { ...f.options, apply: true });
  assert.deepEqual(guardArticleRows([f.row, { id: 'other' }], f.root), [{ id: 'other' }]);
  assert.deepEqual(guardArticleRows([f.remote], f.root), []);
  assert.throws(() => guardArticleRows([{ ...f.remote, content: 'stale overwrite' }], f.root), /refusing full sync/);
  await withPublicationLock(f.root, async () => assert.rejects(withPublicationLock(f.root, async () => {}), /lock held/));
});
test('CAS adapter requires id and baseline timestamp and exactly one returned row', async () => {
  const calls: any[] = [];
  const chain: any = { update: (patch: any) => { calls.push(['update', patch]); return chain; }, eq: (k: string, v: string) => { calls.push([k, v]); return chain; }, select: async () => ({ data: [], error: null }) };
  const adapter = supabaseAdapter({ from: () => chain });
  await assert.rejects(adapter.compareAndSwap('target', 'baseline', { title: 'new' }), /zero rows/);
  assert.deepEqual(calls.slice(1), [['id', 'target'], ['updated_at', 'baseline']]);
});
test('content checks detect unchanged HTML, not just status 200 or scripts', () => {
  const manifest = { patches: { content: '# Heading\n\nNew prose.' } };
  assert.equal(verifyPublicHtml('<h1>Heading</h1><p>New prose.</p>', manifest, { content: '# Heading\n\nOld prose.' }), true);
  assert.throws(() => verifyPublicHtml('<p>Old prose.</p><script>New prose.</script>', manifest, { content: 'Old prose.' }), /Public content/);
});

test('CAS race retains durable recovery snapshot and never calls HTTP', async t => {
  const f = fixture(t);
  await assert.rejects(publishExperiment(f.manifest, { ...f.options, apply: true, db: { ...f.options.db, compareAndSwap: async () => { throw new Error('conditional update affected zero rows'); } } }), /zero rows/);
  assert.equal(f.requests, 0);
  const journal = JSON.parse(fs.readFileSync(path.join(f.root, 'snapshots/exp-1.json'), 'utf8'));
  assert.equal(journal.status, 'prepared');
  assert.equal(journal.before.title, 'Old title');
  assert.deepEqual(guardArticleRows([f.row], f.root), []);
});

test('ambiguous remote write blocks until DB reconciliation then recovers without reapply', async t => {
  const f = fixture(t);
  await assert.rejects(publishExperiment(f.manifest, { ...f.options, apply: true, db: { ...f.options.db, compareAndSwap: async (...args: any[]) => { await f.options.db.compareAndSwap(...args); throw new Error('network disconnected after commit'); } } }), /disconnected/);
  assert.equal(f.writes, 1);
  await assert.rejects(publishExperiment(f.manifest, { ...f.options, apply: true }), /in-flight marker/);
  assert.equal(f.writes, 1);
  // Operator verifies the finished remote write and explicitly clears the fence.
  const journal = JSON.parse(fs.readFileSync(path.join(f.root, 'snapshots/exp-1.json'), 'utf8'));
  assert.equal(articleHash(f.remote), articleHash(journal.after));
  fs.unlinkSync(path.join(f.root, '.publication.in-flight.json'));
  const result = await publishExperiment(f.manifest, { ...f.options, apply: true });
  assert.equal(result.status, 'verified'); assert.equal(f.writes, 1);
});

test('revalidation failure never marks observing', async t => {
  const f = fixture(t);
  const statuses: string[] = [];
  const result = await publishExperiment(f.manifest, { ...f.options, apply: true, onStatus: async (s: string) => { statuses.push(s); }, fetchImpl: async () => ({ ok: false, status: 401 }) });
  assert.equal(result.status, 'verification_pending');
  assert.deepEqual(statuses, ['prepared', 'remote_applied', 'verification_pending']);
});

test('link-only edits verify href and paragraph extensions do not look stale',()=>{
  const manifest={patches:{content:'Read [this guide](/articles/new).'}};
  assert.equal(verifyPublicHtml('<p>Read <a href="/articles/new">this guide</a>.</p>',manifest,{content:'Read [this guide](/articles/old).'}),true);
  assert.throws(()=>verifyPublicHtml('<p>Read <a href="/articles/old">this guide</a>.</p>',manifest,{content:'Read [this guide](/articles/old).'}),/links mismatch/);
  assert.equal(verifyPublicHtml('<p>Old body extended.</p>',{patches:{content:'Old body extended.'}},{content:'Old body'}),true);
});
test('changed FAQ must match visible answer and FAQPage, not hidden scripts',()=>{
  const faq={question:'Weight?',answer:'9.8 kg'};
  const manifest={patches:{faqs:[faq]}};
  const schema='<script type="application/ld+json">'+JSON.stringify({'@type':'FAQPage',mainEntity:[{name:faq.question,acceptedAnswer:{text:faq.answer}}]})+'</script>';
  assert.equal(verifyPublicHtml('<h3>Weight?</h3><p>9.8 kg</p>'+schema,manifest,{faqs:[]}),true);
  assert.throws(()=>verifyPublicHtml('<h3>Weight?</h3><p>8.5 kg</p>'+schema,manifest,{faqs:[]}),/FAQs mismatch/);
});

test('inline Japanese links do not add artificial spaces in rendered comparison',()=>{
  assert.equal(verifyPublicHtml('<p>製品の<a href="https://example.com/spec">公式仕様</a>です。</p>',{patches:{content:'製品の[公式仕様](https://example.com/spec)です。'}},{content:'古い説明です。'}),true);
});
