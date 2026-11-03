import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import sharp from 'sharp';
import { uploadCard, setupBucket, BUCKET } from './social-card-storage.mjs';

const env = { SUPABASE_URL: 'https://db.example.com', SUPABASE_SERVICE_ROLE_KEY: 'test-only' };
const data = await sharp({ create: { width: 1200, height: 630, channels: 3, background: '#b7d6e2' } }).png().toBuffer();
const sha = createHash('sha256').update(data).digest('hex');
const path = `${sha.slice(0, 2)}/${sha}.png`;
const input = { path, dataBase64: data.toString('base64') };
const reply = (status, body, type = 'application/json') => ({ status,
  headers: new Headers({ 'content-type': type }), json: async () => body,
  arrayBuffer: async () => Buffer.from(body) });
const bucket = { id: BUCKET, public: true, file_size_limit: 2 * 1024 * 1024, allowed_mime_types: ['image/png'] };

test('configured public bucket, create-only upload, exact bytes readback', async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push([url, options]);
    if (url.endsWith(`/bucket/${BUCKET}`)) return reply(200, bucket);
    if (url.includes('/object/public/')) return reply(200, data, 'image/png');
    return reply(201, {});
  };
  const result = await uploadCard(env, input, fetcher);
  assert.equal(result.verified, true);
  assert.equal(result.sha256, sha);
  assert.equal(calls[1][1].headers['x-upsert'], 'false');
  assert.equal(calls[1][1].redirect, 'error');
  assert.deepEqual(Buffer.from(calls[1][1].body), data);
  assert.equal(calls[2][1].method, 'GET');
});

test('absent or misconfigured bucket never uploads', async () => {
  for (const response of [reply(404, {}), reply(200, { ...bucket, public: false }),
    reply(200, { ...bucket, allowed_mime_types: ['image/jpeg'] })]) {
    let calls = 0;
    await assert.rejects(uploadCard(env, input, async () => { calls++; return response; }));
    assert.equal(calls, 1);
  }
});

test('collision and timed-out upload reconcile only exact public bytes without repost', async () => {
  for (const result of ['collision', 'timeout']) {
    let posts = 0;
    const verified = await uploadCard(env, input, async (url) => {
      if (url.endsWith(`/bucket/${BUCKET}`)) return reply(200, bucket);
      if (url.includes('/object/public/')) return reply(200, data, 'image/png');
      posts++;
      if (result === 'timeout') throw Error('timeout');
      return reply(409, {});
    });
    assert.equal(verified.sha256, sha);
    assert.equal(posts, 1);
  }
  await assert.rejects(uploadCard(env, input, async (url) => url.endsWith(`/bucket/${BUCKET}`)
    ? reply(200, bucket) : url.includes('/object/public/') ? reply(200, Buffer.from('changed'), 'image/png') : reply(201, {})),
  /storage_readback_mismatch/);
  await assert.rejects(uploadCard(env, input, async (url) => url.endsWith(`/bucket/${BUCKET}`)
    ? reply(200, bucket) : url.includes('/object/public/') ? reply(200, Buffer.from('changed'), 'image/png') : reply(409, {})),
  /storage_existing_mismatch/);
  await assert.rejects(uploadCard(env, input, async (url) => url.endsWith(`/bucket/${BUCKET}`)
    ? reply(200, bucket) : url.includes('/object/public/') ? reply(404, {}) : reply(409, {})),
  /storage_upload_unknown/);
});

test('tampered digest and unsupported data stop before network', async () => {
  let calls = 0;
  const fetcher = async () => { calls++; throw Error('must not call'); };
  await assert.rejects(uploadCard(env, { ...input, path: `aa/${'a'.repeat(64)}.png` }, fetcher), /storage_path_hash_mismatch/);
  await assert.rejects(uploadCard(env, { ...input, dataBase64: Buffer.from('jpg').toString('base64') }, fetcher), /storage_data_invalid/);
  assert.equal(calls, 0);
});

test('only explicit setup function creates bucket', async () => {
  const calls = [];
  await setupBucket(env, async (url, options) => { calls.push([url, options]); return reply(201, {}); });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(JSON.parse(calls[0][1].body).public, true);
});
