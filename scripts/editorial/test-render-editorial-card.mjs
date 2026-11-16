import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import sharp from 'sharp';
import { renderEditorialCard, validateEditorialCardInput } from './render-editorial-card.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const receipt = 'a'.repeat(64);
function request(outputPath) {
  return {
    title: 'テントをしまう前の確認手順',
    heading: '乾かしてから、順番に確認',
    steps: [
      { kind: 'editorial_outline', text: '汚れを落とす' },
      { kind: 'editorial_outline', text: '十分に乾かす' },
      { kind: 'editorial_outline', text: '乾いた場所で保管する' },
    ],
    sourceIds: ['public:coleman-care', 'public:snowpeak-care'],
    sourceReceiptSha256: receipt,
    outputPath,
  };
}

test('strict source-bound input rejects invented, unbound, long, remote, or ambiguous content', async () => {
  const base = request('/tmp/editorial-card.png');
  await assert.doesNotReject(validateEditorialCardInput(base));
  for (const change of [
    { steps: base.steps.slice(0, 2) },
    { steps: [...base.steps, { kind: 'source_claim', text: '追加する' }] },
    { sourceIds: ['public:coleman-care', 'public:coleman-care'] },
    { sourceReceiptSha256: 'not-a-hash' },
    { outputPath: 'relative.png' },
    { heading: '長'.repeat(81) },
    { steps: base.steps.map((step, i) => i ? step : { ...step, text: '長'.repeat(41) }) },
    { remoteUrl: 'https://example.com/image.png' },
  ]) await assert.rejects(validateEditorialCardInput({ ...base, ...change }));
});

test('owned illustration is deterministic 1200x630 PNG with exact large labels and zero network', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-editorial-card-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const first = request(path.join(root, 'first.png'));
  const second = request(path.join(root, 'second.png'));
  const a = await renderEditorialCard(first);
  const b = await renderEditorialCard(second);
  const bytes = await fs.readFile(first.outputPath);
  const metadata = await sharp(bytes).metadata();
  const stats = await sharp(bytes).stats();
  assert.deepEqual([metadata.width, metadata.height, metadata.format], [1200, 630, 'png']);
  assert.equal(a.passed, true);
  assert.equal(a.evidencePassed, true);
  assert.equal(a.version, 'editorial-illustration-v1');
  assert.equal(a.pngSha256, hash(bytes));
  assert.equal(a.pngSha256, b.pngSha256);
  assert.equal(a.contentHash, b.contentHash);
  assert.equal(a.networkRequests, 0);
  assert.deepEqual(a.sourceIds, first.sourceIds);
  assert.equal(a.sourceReceiptSha256, receipt);
  assert.deepEqual(a.displayText.steps, first.steps);
  assert.equal(a.displayText.badge, 'キャンプのヒント');
  assert.equal(a.displayText.disclaimer, 'Camp Gear Lab編集部の図解');
  assert.equal(a.layout.stepCards.length, 3);
  assert.ok(a.layout.headingFontSize >= 42);
  assert.ok(a.layout.stepFontSize >= 26);
  assert.ok(new Set(stats.channels.slice(0, 3).map(channel => Math.round(channel.mean))).size > 1);
  assert.match(a.renderer.engine, /Chrome|Chromium/i);
  assert.ok(a.renderer.fontFamily.includes('sans-serif'));
});

test('CLI failure is fixed, parseable, and does not reflect input or touch a remote path', () => {
  const result = spawnSync(process.execPath, ['scripts/editorial/render-editorial-card.mjs'], {
    input: JSON.stringify({ outputPath: '/tmp/SECRET.png', remoteUrl: 'https://example.com/SECRET' }),
    encoding: 'utf8', timeout: 10000,
  });
  assert.notEqual(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), { passed: false, evidencePassed: false, error: 'editorial_card_render_failed' });
  assert.doesNotMatch(result.stdout + result.stderr, /SECRET/);
});
