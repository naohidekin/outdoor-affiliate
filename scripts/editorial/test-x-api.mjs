import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import test from 'node:test';
import { projectReadback } from './x-api.mjs';

const target = path.join(path.dirname(fileURLToPath(import.meta.url)), 'x-api.mjs');
const run = (input, env = {}) => spawnSync(process.execPath, [target], {
  input: JSON.stringify(input), encoding: 'utf8', timeout: 5000,
  env: { PATH: process.env.PATH ?? '', ...env },
});

test('unknown action and arbitrary destination fail before auth or network', () => {
  const result = run({ action: 'fetch', payload: { url: 'http://127.0.0.1/private' } });
  assert.notEqual(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), { error: 'x_api_unavailable' });
  assert.equal(result.stderr, '');
});

test('preflight without OAuth credentials fails closed with sanitized output', () => {
  const result = run({ action: 'preflight', payload: {} });
  assert.notEqual(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), { error: 'x_api_unavailable' });
  assert.equal(result.stderr, '');
});

test('oversized and malformed media input is never reflected', () => {
  const result = run({ action: 'upload', payload: { data: 'SECRET_PAYLOAD', mime: 'image/png' } },
    { X_API_KEY: 'a', X_API_SECRET: 'b', X_ACCESS_TOKEN: 'c', X_ACCESS_SECRET: 'd' });
  assert.notEqual(result.status, 0);
  assert.doesNotMatch(result.stdout + result.stderr, /SECRET_PAYLOAD|X_ACCESS/);
});

test('readback projection preserves entity offsets and media key without interpretation', () => {
  const post = { id: '111', author_id: '123', text: '💡 https://t.co/photo',
    entities: { urls: [{ start: 3, end: 21, url: 'https://t.co/photo',
      expanded_url: 'https://x.com/gear/status/111/photo/1', media_key: '3_333' }] },
    attachments: { media_keys: ['3_333'] }, referenced_tweets: [] };
  const result = projectReadback(post);
  assert.deepEqual(result.urls, post.entities.urls);
  assert.deepEqual(result.mediaKeys, ['3_333']);
  assert.equal(result.text, post.text);
});
