/** One approved GS public-image replacement. No import-time effects. */
import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { withPublicationLock, seoRoot } from '../seo/article-guard.mjs';
import { loadEnv, productionDependencies, secureImageDigest, verifyPublicHTML } from './publish.mjs';

const ID = 'article-4735600b033b47dc34ae544c';
const SLUG = 'snowpeak-home-and-camp-burner-gs600-review';
const CARD_SHA = '6f5282dd3f4e2fda8d653e16efbd403abd2af206eecdc9f294bd1ddeb056791c';
const CONTENT_SHA = '353dbc0fb98f4b041d8b94f24c5fe89218f3a2c29820314a6015bf405125d484';
const OLD_REVISION = '623939432ba44eb422c69b6e3365ac7bc215f5108262f1ca6f1dbf6c1114cb61';
const APPROVAL = 'この画像で承認します。GS-600の公開画像を差し替えてください。引継ぎ文書の同期も、既存の変更を残したまま解消してください。';
const SITE = 'https://camp-gear-lab.com';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const obj = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const check = (ok, code) => { if (!ok) throw new Error(code); };
const stable = x => Array.isArray(x) ? x.map(stable) : obj(x) ? Object.fromEntries(Object.keys(x).sort().map(k => [k, stable(x[k])])) : x;
const same = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));
const publicRow = row => Object.fromEntries(Object.entries(row).filter(([k]) => !['generation_meta', 'updated_at'].includes(k)));
const stamp = () => new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Tokyo' }).replace(' ', 'T') + '+09:00';

export function assertBundle(bundle) {
  const a = bundle?.article, card = a?.generationMeta?.socialCard;
  check(obj(a) && a.id === ID && a.slug === SLUG && sha(Buffer.from(a.content || '', 'utf8')) === CONTENT_SHA,
    'gs_bundle_identity_mismatch');
  check(obj(card) && card.sha256 === CARD_SHA && card.contentType === 'image/png' &&
    card.width === 1200 && card.height === 630 && Number.isSafeInteger(card.size) &&
    card.size > 0 && card.size <= 2 * 1024 * 1024 && card.url === card.finalUrl &&
    /^https:\/\/[^/?#]+\/storage\/v1\/object\/public\/editorial-social-cards\/[a-f0-9]{2}\/[a-f0-9]{64}\.png$/.test(card.url) &&
    card.url.endsWith(`/${CARD_SHA.slice(0, 2)}/${CARD_SHA}.png`), 'gs_card_manifest_mismatch');
  check(Array.isArray(bundle.images) && bundle.images.filter(i => i?.role === 'social-card' &&
    i.verified === true && i.url === card.url && i.sha256 === card.sha256 && i.size === card.size).length === 1,
    'gs_card_evidence_mismatch');
  check(Array.isArray(bundle.products) && Array.isArray(a.productIds) &&
    same(bundle.products.map(p => p.id).sort(), [...a.productIds].sort()), 'gs_product_selection_mismatch');
  return card;
}

export function expectedOldMeta() { return { editorialRuntime: { author: 'ギア男', revision: OLD_REVISION } }; }
export function expectedNext(before, card, at) {
  return { ...before, generation_meta: { ...before.generation_meta, socialCard: card }, updated_at: at };
}
export function timestampKey(value) {
  const match = typeof value === 'string' && value.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/);
  check(match && Number.isFinite(Date.parse(match[1] + match[3])), 'gs_timestamp_invalid');
  const fraction = (match[2] || '').replace(/0+$/, '');
  return new Date(match[1] + match[3]).toISOString().slice(0, 19) + (fraction ? '.' + fraction : '') + 'Z';
}
export function matchesAfter(row, before, card, at) {
  return obj(row) && same(publicRow(row), publicRow(before)) &&
    same(row.generation_meta, { ...before.generation_meta, socialCard: card }) &&
    timestampKey(row.updated_at) === timestampKey(at);
}

/** Durable private audit. A pre-existing receipt always requires operator reconciliation. */
export function receiptWriter(root) {
  const directory = path.join(root, 'repair');
  const file = path.join(directory, `gs600-social-card-${CARD_SHA}.json`);
  return {
    exists: () => fs.existsSync(file),
    read: () => JSON.parse(fs.readFileSync(file, 'utf8')),
    write(value, first = false) {
      fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
      const temp = first ? file : file + '.' + randomUUID() + '.tmp';
      const fd = fs.openSync(temp, 'wx', 0o600);
      try { fs.writeFileSync(fd, JSON.stringify(value) + '\n'); fs.fsyncSync(fd); }
      finally { fs.closeSync(fd); }
      if (!first) fs.renameSync(temp, file);
      const dir = fs.openSync(directory, 'r');
      try { fs.fsyncSync(dir); } finally { fs.closeSync(dir); }
    },
  };
}

export async function replaceGsCard(bundle, deps, testPolicy = {}) {
  const card = (testPolicy.validateBundle || assertBundle)(bundle);
  return deps.lock(async () => {
    check(!deps.receipt.exists(), 'gs_repair_receipt_requires_reconciliation');
    const rows = await deps.db.findArticles(ID, SLUG);
    check(rows.length === 1 && rows[0].id === ID && rows[0].slug === SLUG && rows[0].status === 'published',
      'gs_published_row_mismatch');
    const before = rows[0];
    check(same(before.generation_meta, testPolicy.oldMeta || expectedOldMeta()) &&
      timestampKey(before.updated_at) === timestampKey(testPolicy.oldUpdatedAt || '2026-11-03T10:52:40+00:00') &&
      sha(Buffer.from(before.content || '', 'utf8')) === (testPolicy.contentSha || CONTENT_SHA) &&
      same(before.product_ids, bundle.article.productIds), 'gs_current_version_mismatch');
    const productIds = bundle.article.productIds;
    const productsBefore = await deps.db.getProducts(productIds);
    check(productsBefore.length === productIds.length && same(productsBefore.map(p => p.id).sort(), [...productIds].sort()),
      'gs_products_mismatch');
    const image = await deps.imageDigest(card.url);
    check(image.sha256 === CARD_SHA && image.size === card.size && image.contentType === 'image/png',
      'gs_public_png_mismatch');
    const at = deps.now();
    check(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/.test(at), 'gs_repair_time_invalid');
    const after = expectedNext(before, card, at);
    const audit = { schemaVersion: 1, action: 'replace-published-gs-social-card', articleId: ID, slug: SLUG,
      approvalText: APPROVAL, approvedCardSha256: CARD_SHA, oldRevision: OLD_REVISION,
      beforeUpdatedAt: before.updated_at, beforeMetadataSha256: sha(Buffer.from(JSON.stringify(stable(before.generation_meta)))),
      beforeRowSha256: sha(Buffer.from(JSON.stringify(stable(before)))), nextUpdatedAt: at,
      nextMetadataSha256: sha(Buffer.from(JSON.stringify(stable(after.generation_meta)))), phase: 'prepared' };
    deps.receipt.write(audit, true); // fsync before the first external write.
    // Even when PATCH times out, read the exact row. Never issue a second PATCH.
    let patchResult;
    try { patchResult = await deps.db.patchCardCAS(before, { generation_meta: after.generation_meta, updated_at: at }); }
    catch { patchResult = null; }
    let readback;
    try { readback = await deps.db.findArticles(ID, SLUG); }
    catch { throw new Error('gs_patch_result_unknown'); }
    check(readback.length === 1 && matchesAfter(readback[0], before, card, at),
      'gs_patch_result_unknown');
    check(patchResult === null || (Array.isArray(patchResult) && patchResult.length === 1 &&
      matchesAfter(patchResult[0], before, card, at)),
      'gs_patch_result_unknown');
    const productsAfter = await deps.db.getProducts(productIds);
    check(same(productsAfter, productsBefore), 'gs_product_readback_mismatch');
    deps.receipt.write({ ...audit, phase: 'db_verified' });
    await deps.revalidate(SLUG, before.category_id);
    const html = await deps.publicGet(`${SITE}/articles/${SLUG}`);
    check((testPolicy.htmlVerifier || verifyPublicHTML)(html, bundle), 'gs_public_metadata_mismatch');
    const finalImage = await deps.imageDigest(card.url);
    check(same(finalImage, image), 'gs_public_png_changed');
    deps.receipt.write({ ...audit, phase: 'complete', verifiedAt: deps.now() });
    return { verified: true, articleId: ID, cardSha256: CARD_SHA, updatedAt: at };
  });
}

/** Readback-only continuation after the canonical marker has been reconciled by the operator. */
export async function reconcileGsCard(bundle, deps, testPolicy = {}) {
  const card = (testPolicy.validateBundle || assertBundle)(bundle);
  return deps.lock(async () => {
    check(deps.receipt.exists(), 'gs_repair_receipt_missing');
    const audit = deps.receipt.read();
    check(audit.schemaVersion === 1 && audit.articleId === ID && audit.slug === SLUG &&
      audit.approvalText === APPROVAL && audit.approvedCardSha256 === CARD_SHA &&
      ['prepared', 'db_verified'].includes(audit.phase), 'gs_repair_receipt_invalid');
    const rows = await deps.db.findArticles(ID, SLUG);
    check(rows.length === 1 && rows[0].status === 'published', 'gs_repair_db_ambiguous');
    const current = rows[0];
    const before = { ...current, generation_meta: testPolicy.oldMeta || expectedOldMeta(), updated_at: audit.beforeUpdatedAt };
    check(sha(Buffer.from(JSON.stringify(stable(before)))) === audit.beforeRowSha256 &&
      matchesAfter(current, before, card, audit.nextUpdatedAt) &&
      sha(Buffer.from(current.content || '', 'utf8')) === (testPolicy.contentSha || CONTENT_SHA),
      'gs_repair_db_unreconciled');
    const image = await deps.imageDigest(card.url);
    check(image.sha256 === CARD_SHA && image.size === card.size && image.contentType === 'image/png',
      'gs_public_png_mismatch');
    deps.receipt.write({ ...audit, phase: 'db_verified' });
    await deps.revalidate(SLUG, current.category_id);
    const html = await deps.publicGet(`${SITE}/articles/${SLUG}`);
    check((testPolicy.htmlVerifier || verifyPublicHTML)(html, bundle), 'gs_public_metadata_mismatch');
    deps.receipt.write({ ...audit, phase: 'complete', verifiedAt: deps.now() });
    return { verified: true, articleId: ID, cardSha256: CARD_SHA, updatedAt: current.updated_at, reconciled: true };
  });
}

export function productionRepairDependencies(config, env) {
  const base = productionDependencies(env);
  const origin = new URL(env.SUPABASE_URL);
  check(origin.protocol === 'https:' && !origin.username && !origin.password && !origin.search && !origin.hash && origin.pathname === '/',
    'gs_db_origin_invalid');
  const headers = { apikey: env.SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
    'Content-Type': 'application/json', Prefer: 'return=representation,handling=strict' };
  const db = { ...base.db, async patchCardCAS(before, patch) {
    const query = new URLSearchParams({ id: `eq.${ID}`, slug: `eq.${SLUG}`, status: 'eq.published',
      updated_at: `eq.${before.updated_at}`, generation_meta: `eq.${JSON.stringify(before.generation_meta)}`,
      select: Object.keys(before).join(',') });
    let response;
    try { response = await fetch(`${origin.origin}/rest/v1/articles?${query}`, { method: 'PATCH', headers,
      body: JSON.stringify(patch), redirect: 'error', signal: AbortSignal.timeout(25000) }); }
    catch { throw new Error('gs_patch_result_unknown'); }
    check(response.ok, 'gs_patch_result_unknown');
    try { return await response.json(); } catch { throw new Error('gs_patch_result_unknown'); }
  } };
  return { db, imageDigest: secureImageDigest, revalidate: base.revalidate, publicGet: base.publicGet,
    receipt: receiptWriter(config.stateRoot), now: stamp,
    lock: action => withPublicationLock(seoRoot(), action) };
}

async function main() {
  try {
    check((process.argv.length === 6 || (process.argv.length === 7 && process.argv[6] === '--reconcile')) &&
      process.argv[2] === '--config' && process.argv[4] === '--bundle',
      'gs_arguments_invalid');
    const config = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
    const bundle = JSON.parse(fs.readFileSync(process.argv[5], 'utf8'));
    check(path.isAbsolute(config.stateRoot) && path.isAbsolute(config.envFile) &&
      path.isAbsolute(config.seoGuardConfig) && !process.env.SEO_STATE_ROOT, 'gs_config_invalid');
    assertBundle(bundle);
    process.env.SEO_GUARD_CONFIG = config.seoGuardConfig;
    const env = loadEnv(config.envFile, {});
    check(env.REVALIDATE_SECRET && env.SUPABASE_SERVICE_ROLE_KEY && env.SUPABASE_URL,
      'gs_environment_invalid');
    const deps = productionRepairDependencies(config, env);
    const result = process.argv.includes('--reconcile') ? await reconcileGsCard(bundle, deps) : await replaceGsCard(bundle, deps);
    process.stdout.write(JSON.stringify(result) + '\n');
  } catch {
    // No credentials, row data or request bodies ever leave this process.
    process.stdout.write(JSON.stringify({ verified: false, error: 'gs_repair_requires_reconciliation' }) + '\n');
    process.exitCode = 1;
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
