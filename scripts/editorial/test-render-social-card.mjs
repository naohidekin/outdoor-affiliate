import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import sharp from 'sharp';
import { renderSocialCard, validateInput, preparePhoto } from './render-social-card.mjs';

const hash = b => createHash('sha256').update(b).digest('hex');
async function fixture(name = '商品写真の描画テスト') {
  // Explicitly synthetic geometry, never presented as an actual product photo.
  const inset = await sharp({ create: { width: 180, height: 390, channels: 3, background: '#9c8c69' } }).png().toBuffer();
  const bytes = await sharp({ create: { width: 900, height: 600, channels: 3, background: 'white' } })
    .composite([{ input: inset, left: 360, top: 105 }]).png().toBuffer();
  return { name, dataUrl: 'data:image/png;base64,' + bytes.toString('base64'), sha256: hash(bytes), verified: true };
}
async function setup(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-card-test-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return root;
}
function request(root, photo) {
  return { title: '商品写真｜収納寸法・購入前の確認点', heading: '収納寸法・購入前の確認点',
    products: [photo], outputPath: path.join(root, 'card.png') };
}

test('verified raster inputs only; no external URLs, SVG, mismatched hashes or invented default label', async t => {
  const root = await setup(t), p = await fixture();
  for (const change of [{ verified: false }, { dataUrl: 'https://example.com/a.png' },
    { dataUrl: 'data:image/svg+xml;base64,' + Buffer.from('<svg/>').toString('base64') },
    { sha256: '0'.repeat(64) }, { dataUrl: p.dataUrl + 'BAD' }]) {
    await assert.rejects(validateInput(request(root, { ...p, ...change })));
  }
  const input = await validateInput(request(root, p));
  assert.equal(input.label, '');
  assert.equal(input.heading, '収納寸法・購入前の確認点');
  for (const title of ['製品｜確認点｜補足', '｜確認点', '製品｜']) {
    const sourced = await validateInput({ ...request(root, p), title, heading: undefined });
    assert.equal(sourced.heading, title);
  }
  await assert.rejects(validateInput({ ...request(root, p), outputPath: 'relative.png' }));
  await assert.rejects(validateInput({ ...request(root, p), products: [p, p, p] }));
});

test('whitespace-only crop preserves all non-white product pixels with padding', async () => {
  const p = await fixture(), prepared = await preparePhoto(p);
  assert.ok(prepared.crop.left < 360 && prepared.crop.top < 105);
  assert.ok(prepared.crop.left + prepared.crop.width > 540);
  assert.ok(prepared.crop.top + prepared.crop.height > 495);
  assert.ok(prepared.crop.width < 400 && prepared.crop.height < 550);
  assert.equal(prepared.sha256, p.sha256);
});

test('one photo: 1200x630 PNG, large uncropped hero, exact display text, no network and deterministic bytes', async t => {
  const root = await setup(t), p = await fixture(), input = request(root, p);
  const a = await renderSocialCard(input);
  const b = await renderSocialCard({ ...input, outputPath: path.join(root, 'same.png') });
  const bytes = await fs.readFile(input.outputPath), meta = await sharp(bytes).metadata();
  assert.deepEqual([meta.width, meta.height, meta.format], [1200, 630, 'png']);
  assert.equal(a.pngSha256, hash(bytes));
  assert.equal(a.pngSha256, b.pngSha256);
  assert.equal(a.contentHash, b.contentHash);
  assert.equal(a.displayText.heading, input.heading);
  assert.deepEqual(a.displayText.productNames, [p.name]);
  assert.equal(a.displayText.label, '');
  assert.equal(a.networkRequests, 0);
  assert.ok(a.layout.headingFontSize >= 40);
  assert.ok(a.layout.photos[0].height >= 420);
  assert.equal(a.sources[0].sha256, p.sha256);
  assert.equal(a.passed, true);
});

test('two products: preserve both source hashes, names, whole subjects and photo order', async t => {
  const root = await setup(t), p = await fixture('製品A'), q = await fixture('製品B');
  const input = { ...request(root, p), products: [p, q], label: '公開仕様をチェック' };
  const result = await renderSocialCard(input);
  assert.deepEqual(result.displayText.productNames, ['製品A', '製品B']);
  assert.equal(result.displayText.label, input.label);
  assert.equal(result.sources.length, 2);
  assert.equal(result.layout.photos.length, 2);
  for (const bounds of result.layout.photos) {
    assert.ok(bounds.height >= 360);
    assert.ok(bounds.x >= 576 && bounds.right <= 1200 && bounds.bottom <= 630);
  }
});

test('actual GS pipeline name remains complete, model unbroken and title suffix verbatim', async t => {
  const root = await setup(t), p = await fixture('スノーピーク HOME&CAMP バーナー カーキ GS-600KH');
  const title = 'HOME&CAMP バーナー GS-600KH｜収納寸法・専用ガス・購入前の確認点';
  const result = await renderSocialCard({ title, products: [p], outputPath: path.join(root, 'actual.png') });
  assert.equal(result.displayText.heading, title.split('｜').at(-1));
  assert.deepEqual(result.displayText.productNames, [p.name]);
  assert.ok(result.layout.productNameFontSize >= 20);
  assert.deepEqual(result.layout.modelTokens.map(item => item.text), p.name.split(' '));
  for (const token of result.layout.modelTokens) {
    assert.ok(token.height <= result.layout.productNameFontSize * 1.35 + 1);
    assert.ok(token.right <= 506);
  }
  const model = result.layout.modelTokens.find(item => item.text === 'GS-600KH');
  assert.ok(model);
  assert.ok(model.height <= result.layout.productNameFontSize * 1.35 + 1);
  assert.ok(model.right <= 506);
});

test('overflow fails closed rather than clipping or rewriting a long title/name', async t => {
  const root = await setup(t), p = await fixture();
  await assert.rejects(renderSocialCard({ ...request(root, p), heading: '確認すべき公表仕様'.repeat(30) }), /heading/);
  await assert.rejects(renderSocialCard({ ...request(root, p), heading: undefined, title: '長いタイトル'.repeat(30) }), /heading/);
  await assert.rejects(renderSocialCard({ ...request(root, p), products: [{ ...p, name: '長い商品名'.repeat(30) }] }), /product/);
  assert.equal(await fs.stat(path.join(root, 'card.png')).catch(() => null), null);
});

test('text escaping cannot execute HTML or initiate an external resource', async t => {
  const root = await setup(t), p = await fixture('A <img src=x>');
  const result = await renderSocialCard({ ...request(root, p), heading: '<img src=x> & 確認' });
  assert.equal(result.displayText.heading, '<img src=x> & 確認');
  assert.equal(result.networkRequests, 0);
});

test('CLI rejects unknown request keys/oversize without reflecting input or executing paths', () => {
  const result = spawnSync(process.execPath, ['scripts/editorial/render-social-card.mjs'], {
    input: JSON.stringify({ outputPath: '/tmp/x.png', executablePath: '/tmp/UNTRUSTED_SECRET' }),
    encoding: 'utf8', timeout: 5000,
  });
  assert.notEqual(result.status, 0);
  assert.doesNotMatch(result.stdout + result.stderr, /UNTRUSTED_SECRET/);
  assert.equal(JSON.parse(result.stdout).passed, false);
});


test('SOTO and CB headings preserve exact text and fit complete phrases without splitting compounds', async t => {
  const root = await setup(t);
  const cases = [
    ['旧型ウインドマスターとアミカスの選び方', ['旧型ウインドマスターと', 'アミカスの選び方'],
      ['SOTO ウインドマスター SOD-310', 'SOTO アミカス SOD-320 シングルバーナー']],
    ['ST-310・US-1900の仕様確認', ['ST-310・', 'US-1900の仕様確認'],
      ['SOTO レギュレーターストーブ ST-310', 'ユニフレーム ツインバーナー US-1900']],
  ];
  for (const [index, [heading, phrases, names]] of cases.entries()) {
    const result = await renderSocialCard({ title: '比較｜' + heading,
      products: await Promise.all(names.map(name => fixture(name))), outputPath: path.join(root, index + '.png') });
    assert.equal(result.layout.renderedHeading, heading);
    assert.deepEqual(result.layout.renderedNames, names);
    assert.deepEqual(result.layout.headingPhrases.map(p => p.text), phrases);
    assert.ok(result.layout.headingFontSize >= 40);
    for (const phrase of result.layout.headingPhrases) {
      assert.ok(phrase.height <= result.layout.headingFontSize * 1.24 + 1);
      assert.ok(phrase.x >= result.layout.heading.x && phrase.right <= result.layout.heading.right);
      assert.ok(phrase.bottom <= result.layout.heading.bottom);
    }
  }
});
