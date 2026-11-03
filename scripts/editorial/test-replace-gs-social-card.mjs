import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { replaceGsCard, reconcileGsCard, receiptWriter, expectedOldMeta, matchesAfter, timestampKey,
  productionRepairDependencies } from './replace-gs-social-card.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ID = 'article-4735600b033b47dc34ae544c';
const SLUG = 'snowpeak-home-and-camp-burner-gs600-review';
const SHA = '6f5282dd3f4e2fda8d653e16efbd403abd2af206eecdc9f294bd1ddeb056791c';
const oldAt = '2026-11-03T10:52:40+00:00';
const nextAt = '2026-11-04T00:55:11+09:00';
const card = { url: `https://db.example/storage/v1/object/public/editorial-social-cards/${SHA.slice(0, 2)}/${SHA}.png`,
  sha256: SHA, size: 1234, contentType: 'image/png', width: 1200, height: 630 };
const clone = x => structuredClone(x);
const hash = text => createHash('sha256').update(text).digest('hex');
const bundle = { article: { id: ID, slug: SLUG, title: 'GS', content: 'Approved article', productIds: ['p'],
  generationMeta: { socialCard: card } }, products: [{ id: 'p' }], images: [] };

function harness(mode = 'normal') {
  const state = { row: { id: ID, slug: SLUG, status: 'published', category_id: 'burner',
    content: bundle.article.content, product_ids: ['p'], generation_meta: expectedOldMeta(), updated_at: oldAt,
    published_at: oldAt, title: 'GS', faqs: [] }, products: [{ id: 'p', name: 'product' }],
    writes: 0, revalidations: 0, receipts: [] };
  const receipt = { exists: () => state.receipts.length > 0, read: () => clone(state.receipts.at(-1)),
    write: (value, first) => { if (first) assert.equal(state.receipts.length, 0); state.receipts.push(clone(value)); } };
  const db = { findArticles: async () => [clone(state.row)], getProducts: async () => clone(state.products),
    patchCardCAS: async (before, patch) => {
      state.writes++;
      assert.equal(before.updated_at, oldAt);
      assert.deepEqual(Object.keys(patch).sort(), ['generation_meta', 'updated_at']);
      assert.deepEqual(before.generation_meta, expectedOldMeta());
      if (mode === 'conflict') return [];
      state.row = { ...state.row, ...patch, updated_at: new Date(patch.updated_at).toISOString() };
      if (mode === 'timeout') throw Error('lost response');
      return [clone(state.row)];
    } };
  const deps = { lock: fn => fn(), db, receipt, now: () => nextAt,
    imageDigest: async () => ({ sha256: SHA, size: card.size, contentType: 'image/png' }),
    revalidate: async () => { state.revalidations++; }, publicGet: async () => '<html>verified</html>' };
  const policy = { validateBundle: () => card, contentSha: hash(bundle.article.content),
    htmlVerifier: html => html === '<html>verified</html>' };
  return { state, deps, policy };
}

test('timezone-aware readback preserves fractional precision and other fields', () => {
  assert.equal(timestampKey('2026-11-04T00:55:11.123400+09:00'), '2026-11-03T15:55:11.1234Z');
  const before = harness().state.row;
  const after = { ...before, updated_at: '2026-11-03T15:55:11+00:00',
    generation_meta: { ...before.generation_meta, socialCard: card } };
  assert.equal(matchesAfter(after, before, card, nextAt), true);
  assert.equal(matchesAfter({ ...after, content: 'changed' }, before, card, nextAt), false);
  assert.equal(matchesAfter({ ...after, updated_at: '2026-11-03T15:55:11.001+00:00' }, before, card, nextAt), false);
});

test('one CAS, durable approval receipt first, all other DB fields and products preserved', async () => {
  const { state, deps, policy } = harness();
  const old = clone(state.row), products = clone(state.products);
  const result = await replaceGsCard(bundle, deps, policy);
  assert.equal(result.verified, true);
  assert.equal(state.writes, 1);
  assert.equal(state.revalidations, 1);
  assert.equal(state.receipts[0].phase, 'prepared');
  assert.match(state.receipts[0].approvalText, /^この画像で承認します。/);
  assert.equal(state.receipts.at(-1).phase, 'complete');
  assert.equal(state.row.content, old.content);
  assert.equal(state.row.published_at, old.published_at);
  assert.deepEqual(state.products, products);
  await assert.rejects(replaceGsCard(bundle, deps, policy), /receipt_requires_reconciliation/);
  assert.equal(state.writes, 1);
});

test('lost PATCH response reconciles by GET without a second write', async () => {
  const { state, deps, policy } = harness('timeout');
  const result = await replaceGsCard(bundle, deps, policy);
  assert.equal(result.verified, true);
  assert.equal(state.writes, 1);
});

test('postwrite cache failure resumes from exact DB receipt without another PATCH', async () => {
  const { state, deps, policy } = harness();
  deps.revalidate = async () => { state.revalidations++; throw Error('cache unavailable'); };
  await assert.rejects(replaceGsCard(bundle, deps, policy), /cache unavailable/);
  assert.equal(state.writes, 1);
  assert.equal(state.receipts.at(-1).phase, 'db_verified');
  deps.revalidate = async () => { state.revalidations++; };
  const result = await reconcileGsCard(bundle, deps, policy);
  assert.equal(result.reconciled, true);
  assert.equal(state.writes, 1);
  assert.equal(state.receipts.at(-1).phase, 'complete');
});

test('CAS conflict and changed current row stop without retry', async () => {
  const conflicted = harness('conflict');
  await assert.rejects(replaceGsCard(bundle, conflicted.deps, conflicted.policy), /patch_result_unknown/);
  assert.equal(conflicted.state.writes, 1);
  assert.equal(conflicted.state.receipts.at(-1).phase, 'prepared');
  const changed = harness(); changed.state.row.content = 'different';
  await assert.rejects(replaceGsCard(bundle, changed.deps, changed.policy), /current_version_mismatch/);
  assert.equal(changed.state.writes, 0);
});

test('receipt is private and durable before any DB write', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'gs-repair-test-'));
  try {
    const receipt = receiptWriter(directory);
    receipt.write({ phase: 'prepared' }, true);
    assert.equal(receipt.exists(), true);
    assert.deepEqual(receipt.read(), { phase: 'prepared' });
    const file = fs.readdirSync(path.join(directory, 'repair'))[0];
    assert.equal(fs.statSync(path.join(directory, 'repair', file)).mode & 0o777, 0o600);
    receipt.write({ phase: 'complete' });
    assert.equal(receipt.read().phase, 'complete');
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('production CAS URL binds old metadata and updated timestamp', async () => {
  const oldFetch = globalThis.fetch;
  let seen;
  try {
    globalThis.fetch = async (url, options) => { seen = { url: new URL(url), options };
      return { ok: true, json: async () => [] }; };
    const deps = productionRepairDependencies({ stateRoot: '/tmp/unused' },
      { SUPABASE_URL: 'https://db.example/', SUPABASE_SERVICE_ROLE_KEY: 'test-only' });
    await deps.db.patchCardCAS(harness().state.row, { generation_meta: {}, updated_at: nextAt });
    assert.equal(seen.url.searchParams.get('updated_at'), `eq.${oldAt}`);
    assert.equal(seen.url.searchParams.get('generation_meta'), `eq.${JSON.stringify(expectedOldMeta())}`);
    assert.equal(seen.options.method, 'PATCH');
    assert.equal(seen.options.redirect, 'error');
  } finally { globalThis.fetch = oldFetch; }
});
