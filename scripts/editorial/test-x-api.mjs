import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import test from 'node:test';
import { projectReadback, projectThreadReadback, projectDayRoots } from './x-api.mjs';

const target = path.join(path.dirname(fileURLToPath(import.meta.url)), 'x-api.mjs');
const run = (input, env = {}) => spawnSync(process.execPath, [target], {
  input: JSON.stringify(input), encoding: 'utf8', timeout: 5000,
  env: { PATH: process.env.PATH ?? '', ...env },
});

const dayPayload = { accountId: '123', start: '2026-11-15T15:00:00Z', end: '2026-11-16T02:00:00Z' };
const dayPost = (id = '1', created_at = dayPayload.start) => ({ id, author_id: '123', created_at });

test('dayroots requires an exact integer result count, including empty responses', () => {
  for (const data of [undefined, [], [dayPost()]]) {
    const length = data?.length ?? 0;
    for (const result_count of [undefined, null, false, String(length), -1, 0.5, length + 1]) {
      assert.throws(() => projectDayRoots({ data, meta: { result_count } }, dayPayload));
    }
    assert.equal(projectDayRoots({ data, meta: { result_count: length } }, dayPayload).complete, true);
  }
});

test('dayroots rejects malformed errors, metadata and continuation even with zero results', () => {
  for (const errors of [null, {}, '', false, 0, [{}]]) {
    assert.throws(() => projectDayRoots({ data: [], meta: { result_count: 0 }, errors }, dayPayload));
  }
  assert.equal(projectDayRoots({ meta: { result_count: 0 }, errors: [] }, dayPayload).complete, true);
  for (const meta of [null, [], '', 1, { result_count: 0, next_token: '' },
    { result_count: 0, next_token: null }, { result_count: 0, next_token: 'more' }]) {
    assert.throws(() => projectDayRoots({ data: [], meta }, dayPayload));
  }
});

test('dayroots keeps the caller cutoff and rejects posts outside the JST interval', () => {
  const response = post => ({ data: [post], meta: { result_count: 1 } });
  assert.equal(projectDayRoots(response(dayPost()), dayPayload).end, dayPayload.end);
  for (const at of ['2026-11-15T14:59:59Z', dayPayload.end, '2026-11-16T15:00:00Z']) {
    assert.throws(() => projectDayRoots(response(dayPost('1', at)), dayPayload));
  }
  for (const post of [null, [], {}, { ...dayPost(), author_id: '999' },
    { ...dayPost(), id: 1 }, { ...dayPost(), referenced_tweets: null }]) {
    assert.throws(() => projectDayRoots(response(post), dayPayload));
  }
  assert.throws(() => projectDayRoots({ data: [dayPost(), dayPost()], meta: { result_count: 2 } }, dayPayload));
  for (const accountId of [123, null, '', '0']) {
    assert.throws(() => projectDayRoots({ meta: { result_count: 0 } }, { ...dayPayload, accountId }));
  }
});

test('dayroots request bounds require whole-second UTC timestamps', () => {
  for (const field of ['start', 'end']) {
    const value = dayPayload[field];
    for (const invalid of [value.replace('Z', '.000Z'), value.replace('Z', '.123456Z'),
      value.replace('Z', '+00:00'), value.replace('Z', ''), value.replace(':00Z', 'Z'),
      '2026-02-30T15:00:00Z']) {
      assert.throws(() => projectDayRoots({ meta: { result_count: 0 } },
        { ...dayPayload, [field]: invalid }), /daybounds/);
    }
  }
});

test('dayroots accepts up to 48 hours from JST midnight and rejects longer windows', () => {
  const payload = { ...dayPayload, end: '2026-11-17T15:00:00Z' };
  const data = [dayPost('1'), dayPost('2', '2026-11-16T14:30:00Z'),
    dayPost('3', '2026-11-17T14:59:59Z')];
  const response = { data, meta: { result_count: data.length } };
  for (const end of ['2026-11-17T02:00:00Z', payload.end]) {
    const posts = data.filter(post => post.created_at < end);
    const result = projectDayRoots({ data: posts, meta: { result_count: posts.length } }, { ...payload, end });
    assert.equal(result.complete, true);
    assert.deepEqual(result.roots.map(post => post.id), posts.map(post => post.id));
  }
  assert.throws(() => projectDayRoots(response, { ...payload, end: '2026-11-17T15:00:01Z' }), /daybounds/);
  assert.throws(() => projectDayRoots({ ...response, meta: { result_count: 3, next_token: 'more' } }, payload), /incomplete/);
  const hundred = Array.from({ length: 100 }, (_, index) => dayPost(String(index + 1)));
  assert.equal(projectDayRoots({ data: hundred, meta: { result_count: 100 } }, payload).roots.length, 100);
  assert.throws(() => projectDayRoots({ data: [...hundred, dayPost('101')], meta: { result_count: 101 } }, payload), /incomplete/);
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

test('thread readback binds own direct reply and ordered public photo URLs', () => {
  const root = { data: { id: '111', author_id: '123', text: 'main',
    attachments: { media_keys: ['3_a'] }, referenced_tweets: [] },
    includes: { media: [{ media_key: '3_a', type: 'photo', url: 'https://pbs.twimg.com/media/a.png' }] } };
  const reply = { id: '222', author_id: '123', text: 'reply', attachments: { media_keys: [] },
    referenced_tweets: [{ type: 'replied_to', id: '111' }] };
  const result = projectThreadReadback(root, { tweets: [reply,
    { ...reply, id: '333', author_id: '999' }] });
  assert.equal(result.main.id, '111');
  assert.deepEqual(result.replies.map(item => item.id), ['222']);
  assert.deepEqual(result.media, [{ mediaKey: '3_a', type: 'photo',
    url: 'https://pbs.twimg.com/media/a.png' }]);
});

test('thread readback rejects missing reply and non-photo media', () => {
  const root = { data: { id: '111', author_id: '123', text: 'main',
    attachments: { media_keys: ['3_a'] }, referenced_tweets: [] },
    includes: { media: [{ media_key: '3_a', type: 'video', url: 'https://pbs.twimg.com/media/a' }] } };
  assert.throws(() => projectThreadReadback(root, { tweets: [] }));
  assert.throws(() => projectThreadReadback(root, { tweets: [{ id: '222', author_id: '123', text: 'r',
    referenced_tweets: [{ type: 'replied_to', id: '111' }] }] }));
});

test('dayroots counts original and quote roots at the JST boundary, never replies or retweets', async () => {
  const { projectDayRoots } = await import('./x-api.mjs');
  const start = '2026-11-15T15:00:00Z', end = '2026-11-16T02:00:00Z';
  const post = (id, refs = []) => ({ id, author_id: '123', created_at: start, referenced_tweets: refs });
  const result = projectDayRoots({ data: [post('1'), post('2', [{ type: 'quoted', id: '8' }]),
    post('3', [{ type: 'replied_to', id: '1' }]), post('4', [{ type: 'retweeted', id: '9' }])],
    meta: { result_count: 4 } }, { accountId: '123', start, end });
  assert.deepEqual(result.roots, [{ id: '1', createdAt: start }, { id: '2', createdAt: start }]);
  assert.equal(result.complete, true);
  for (const response of [{ data: [], meta: { next_token: 'more' } },
    { data: [], errors: [{}], meta: {} }, { data: [post('1'), post('1')], meta: {} },
    { data: [{ ...post('1'), author_id: '999' }], meta: {} }, { data: [] }]) {
    assert.throws(() => projectDayRoots(response, { accountId: '123', start, end }));
  }
});
