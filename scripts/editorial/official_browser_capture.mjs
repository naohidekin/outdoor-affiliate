// Inject a documented managed-browser Tab. Never launches a browser, signs in,
// retries navigation, or substitutes static checkout HTML for product evidence.
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

export const R1_URL = 'https://www.patagonia.jp/product/mens-r1-air-fleece-midlayer-jacket/40275.html';
export async function captureR1(tab, outputDir) {
  if (await tab.url() !== R1_URL) throw new Error('Exact R1 source URL required');
  const length = await tab.playwright.evaluate(() => document.documentElement.outerHTML.length);
  if (!Number.isSafeInteger(length) || length <= 0 || length > 3 * 1024 * 1024)
    throw new Error('DOM length exceeds capture bound');
  const passes = [];
  for (let pass = 0; pass < 2; pass++) {
    const chunks = [];
    for (let offset = 0; offset < length; offset += 80000)
      chunks.push(await tab.playwright.evaluate(({ offset }) =>
        document.documentElement.outerHTML.slice(offset, offset + 80000), { offset }));
    const html = chunks.join('');
    const afterLength = await tab.playwright.evaluate(() => document.documentElement.outerHTML.length);
    if (html.length !== length || afterLength !== length) throw new Error('Truncated or changed DOM capture');
    passes.push(html);
  }
  const finalUrl = await tab.url();
  if (finalUrl !== R1_URL || passes[0] !== passes[1]) throw new Error('DOM or final URL changed');
  const body = Buffer.from(passes[0], 'utf8');
  if (body.length > 3 * 1024 * 1024) throw new Error('DOM byte limit exceeded');
  await mkdir(outputDir, { recursive: true });
  const path = join(outputDir, '40275-browser-dom.html');
  const receipt = { schemaVersion: 1, model: '40275', requestedUrl: R1_URL, finalUrl,
    transport: 'managed-chrome-rendered-dom', captureCount: 1,
    capturedAtJST: new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().replace('Z', '+09:00'),
    domBytes: body.length, domSHA256: createHash('sha256').update(body).digest('hex'),
    path, domReadPasses: 2, readChunkChars: 80000, identicalPasses: true };
  await writeFile(path, body);
  await writeFile(join(outputDir, '40275-browser-receipt.json'), JSON.stringify(receipt, null, 2));
  return receipt;
}
