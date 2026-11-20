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

// Exact titles/outlines from the owner-selected 2026-11-20 proposals.json.
const selectedProposals = [
  ['tent-pole-joint-grommet-care-guide', 'テントポールの手入れ｜継ぎ目とグロメットの汚れを残さず収納するには',
    ['幕体とは分けて金属部の汚れを見る', 'ポールは土を落として乾燥を確認', '継ぎ目とグロメットを確認する', '防錆の案内はメーカーの対象を守る', '収納前に残す確認事項'], ['public:coleman-care']],
  ['coleman-synthetic-sleeping-bag-wash-label-guide', 'コールマンの化繊寝袋は洗濯機で洗える？洗濯表示を確認する順番',
    ['洗う方法を決める前に表示をそろえる', 'ウォッシャブルアイコンがある場合', 'アイコンがなく素材がすべて化繊の場合', 'ラベルで確認できない条件は決めつけない', '不明な条件を公式へ確認する準備'], ['public:coleman-synthetic-wash']],
  ['thermos-bottle-compatible-parts-search-guide', 'サーモスのパッキンはどれを買う？品番から適合部品を探す手順',
    ['製品から探すか部品から探すかを分ける', '製品の品番・色名・JANコードで探す', '交換用部品名・JANコードから逆に探す', '複数キーワードと入力表記を確認する', '適合が分からないまま購入しない'], ['public:thermos-product-parts', 'public:thermos-parts-product']],
];
const contains = (outer, inner) => inner.x >= outer.x - 0.01 && inner.y >= outer.y - 0.01 &&
  inner.right <= outer.right + 0.01 && inner.bottom <= outer.bottom + 0.01;

for (const [slug, title, outline, sourceIds] of selectedProposals) {
  test(`actual selected five-step layout: ${slug}`, async t => {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-editorial-selected-'));
    t.after(() => fs.rm(root, { recursive: true, force: true }));
    const input = { ...request(path.join(root, `${slug}.png`)), title,
      heading: title.split('？').slice(1).join('？') || (title.includes('｜') ? title.split('｜')[1] : title),
      steps: outline.map(text => ({ kind: 'editorial_outline', text })), sourceIds };
    const result = await renderEditorialCard(input);
    const png = await fs.readFile(input.outputPath);
    const metadata = await sharp(png).metadata();
    assert.equal(result.passed, true);
    assert.equal(result.evidencePassed, true);
    assert.equal(result.networkRequests, 0);
    assert.deepEqual([metadata.width, metadata.height, metadata.format], [1200, 630, 'png']);
    assert.equal(result.pngSha256, hash(png));
    assert.deepEqual(result.displayText.steps, input.steps);
    assert.equal(result.displayText.title, title);
    assert.equal(result.displayText.heading, input.heading);
    assert.deepEqual(result.sourceIds, sourceIds);
    assert.equal(result.sourceReceiptSha256, receipt);
    const layout = result.layout;
    assert.ok(layout.titleFontSize >= 22);
    assert.ok(layout.headingFontSize >= 42);
    assert.ok(layout.stepFontSize >= 26);
    assert.ok(layout.titleLines.length <= 2);
    assert.equal(layout.stepCards.length, 5);
    assert.deepEqual(layout.stepCards.map(card => card.text), outline);
    assert.ok(layout.title.bottom <= layout.heading.y);
    assert.ok(layout.heading.bottom <= layout.textBoxes.disclaimer.y);
    for (const box of Object.values(layout.textBoxes)) {
      assert.ok(contains({ x: 0, y: 0, right: 1200, bottom: 630 }, box));
      assert.ok(box.lines.length > 0);
      for (const line of box.lines) assert.ok(contains(box, line));
    }
    for (const [index, card] of layout.stepCards.entries()) {
      assert.ok(contains({ x: 585, y: 48, right: 1140, bottom: 582 }, card));
      assert.ok(contains(card, card.textBox));
      assert.ok(contains(card, card.numberBox));
      assert.ok(card.numberBox.right < card.textBox.x);
      for (const line of card.textBox.lines) assert.ok(contains(card.textBox, line));
      for (const line of card.numberBox.lines) assert.ok(contains(card.numberBox, line));
      if (index) assert.ok(card.y - layout.stepCards[index - 1].bottom >= 14);
    }
    t.diagnostic(JSON.stringify({ slug, pngSha256: result.pngSha256, width: result.width, height: result.height,
      fonts: [layout.titleFontSize, layout.headingFontSize, layout.stepFontSize], steps: outline,
      title: layout.title, heading: layout.heading, stepCards: layout.stepCards }));
  });
}

test('all three font floors remain usable without relaxing readability', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-editorial-floors-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const result = await renderEditorialCard({ ...request(path.join(root, 'floors.png')),
    title: '長'.repeat(40), heading: '長'.repeat(33),
    steps: Array.from({ length: 5 }, () => ({ kind: 'editorial_outline', text: '確認'.repeat(10) })) });
  assert.deepEqual([result.layout.titleFontSize, result.layout.headingFontSize, result.layout.stepFontSize], [22, 42, 26]);
  assert.equal(result.layout.titleLines.length, 2);
  assert.equal(result.evidencePassed, true);
});

test('text exceeding font floors fails explicitly without writing a clipped PNG', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'camp-editorial-overflow-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  for (const change of [
    { title: '長'.repeat(120) },
    { heading: '長'.repeat(80) },
    { steps: Array.from({ length: 5 }, () => ({ kind: 'editorial_outline', text: '長'.repeat(40) })) },
  ]) {
    const input = { ...request(path.join(root, 'overflow.png')), ...change };
    await assert.rejects(renderEditorialCard(input), /text_overflow|diagram_overflow/);
    await assert.rejects(fs.stat(input.outputPath), { code: 'ENOENT' });
  }
});
