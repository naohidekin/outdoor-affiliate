import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash, randomUUID } from 'node:crypto';
import { withProcessLock, withRemoteProcessLock } from './process-lock.mjs';
import { AsyncLocalStorage } from 'node:async_hooks';

export const PATCH_FIELDS = Object.freeze({ content: 'content', title: 'title', metaDescription: 'meta_description', excerpt: 'excerpt', faqs: 'faqs', tags: 'tags' });
const FIELDS = { id: 'id', slug: 'slug', status: 'status', categoryId: 'category_id', productIds: 'product_ids', author: 'author', ...PATCH_FIELDS };
export function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
  return value;
}
export function hash(value) { return createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex'); }
export function protectedFields(article) {
  return Object.fromEntries(Object.entries(FIELDS).map(([local, remote]) => [remote, article[remote] ?? article[local] ?? (['faqs', 'tags', 'productIds'].includes(local) ? [] : '')]));
}
export function articleHash(article) { return hash(protectedFields(article)); }
const publicationScope = new AsyncLocalStorage();
export function readGuardConfig() {
  const file = process.env.SEO_GUARD_CONFIG || path.join(os.homedir(), '.config/campgearlab-seo/guard.json');
  let value;
  try { value = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT' && !process.env.SEO_GUARD_CONFIG) return null; throw new Error('SEO host guard configuration missing or invalid'); }
  if (value?.schemaVersion !== 1 || !['local', 'ssh'].includes(value.mode) || typeof value.stateRoot !== 'string' || !path.isAbsolute(value.stateRoot)) throw new Error('Invalid SEO host guard configuration');
  if (value.mode === 'ssh') {
    if (process.env.SEO_STATE_ROOT) throw new Error('SSH guard conflicts with SEO_STATE_ROOT; refusing an unprotected local override');
    if (typeof value.host !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.@-]*$/.test(value.host) || typeof value.exportScript !== 'string' || !path.isAbsolute(value.exportScript)) throw new Error('Invalid SEO SSH guard configuration');
  }
  return value;
}
export function seoRoot() {
  const config = readGuardConfig();
  return path.resolve(process.env.SEO_STATE_ROOT || config?.stateRoot || path.join(os.homedir(), '.secretary/state/campgearlab-seo'));
}
function routeFor(root) {
  const config = readGuardConfig();
  // Explicit roots remain useful for isolated tooling/tests. Legacy full sync
  // always passes seoRoot(), which binds it to this host's canonical guard.
  return config && path.resolve(root) === seoRoot() ? config : null;
}
export function validateProtection(value) {
  if (value?.schemaVersion !== 1 || !Array.isArray(value.protectedArticles)) throw new Error('Invalid SEO protection export');
  for (const row of value.protectedArticles) {
    if (typeof row?.articleId !== 'string' || !row.articleId || !/^[a-f0-9]{64}$/.test(row.beforeHash || '') || !/^[a-f0-9]{64}$/.test(row.afterHash || '')) throw new Error('Invalid SEO protected article fingerprint');
  }
  return value.protectedArticles;
}
export function assertCanonicalState(root) {
  let state;
  try { state = JSON.parse(fs.readFileSync(path.join(root, 'state.json'), 'utf8')); }
  catch { throw new Error('Canonical SEO state is unavailable; refusing unprotected sync'); }
  if (state?.schemaVersion !== 1 || !Array.isArray(state.experiments)) throw new Error('Canonical SEO state is invalid');
}

export function atomicJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  const fd = fs.openSync(tmp, 'wx', 0o600);
  try { fs.writeFileSync(fd, `${JSON.stringify(value, null, 2)}\n`); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  fs.renameSync(tmp, file);
  const dir = fs.openSync(path.dirname(file), 'r');
  try { fs.fsyncSync(dir); } finally { fs.closeSync(dir); }
}
function assertNoPublicationInFlight(root) {
  try { fs.lstatSync(path.join(root, '.publication.in-flight.json')); }
  catch (error) { if (error.code === 'ENOENT') return; throw error; }
  throw new Error('SEO publication in-flight marker exists; reconcile DB before operator clearance');
}
function createPublicationMarker(root, value) {
  // O_EXCL is required even after the earlier check: losing the helper lease
  // could let another owner create its marker before this Node turn resumes.
  // Never replace or remove an existing/partially written marker on failure.
  const marker = path.join(root, '.publication.in-flight.json');
  const fd = fs.openSync(marker, 'wx', 0o600);
  try {
    fs.writeFileSync(fd, JSON.stringify(value) + '\n');
    fs.fsyncSync(fd);
  } finally { fs.closeSync(fd); }
  const directory = fs.openSync(root, 'r');
  try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
}
function clearPublicationMarker(root, token) {
  const marker = path.join(root, '.publication.in-flight.json');
  const stored = JSON.parse(fs.readFileSync(marker, 'utf8'));
  if (stored.token !== token) throw new Error('SEO publication marker ownership changed');
  fs.unlinkSync(marker);
  const directory = fs.openSync(root, 'r');
  try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
}
export async function withPublicationLock(root, action, { readOnly = false } = {}) {
  if (typeof readOnly !== 'boolean') throw new Error('Publication readOnly must be an explicit boolean');
  const config = routeFor(root);
  if (config?.mode === 'ssh') {
    return withRemoteProcessLock(config, async exported => {
      const scope = { root: path.resolve(root), mode: 'ssh', protectedArticles: validateProtection(exported), active: true };
      try { return await publicationScope.run(scope, action); }
      finally { scope.active = false; }
    }, { readOnly });
  }
  if (config) assertCanonicalState(root);
  return withProcessLock(path.join(root, '.publication.flock'), async () => {
    // The durable marker fences later publications even when this OS lock is
    // released by a crash while a previously sent DB request is still in flight.
    // It is never recovered by age. An operator must reconcile the DB first.
    assertNoPublicationInFlight(root);
    const token = randomUUID();
    if (!readOnly) createPublicationMarker(root, {
      schemaVersion: 1, token,
      createdAt: new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Tokyo' }).replace(' ', 'T') + '+09:00',
      owner: { host: os.hostname(), pid: process.pid },
    });
    const scope = { root: path.resolve(root), mode: 'local', requireCanonical: !!config, active: true };
    try {
      const result = await publicationScope.run(scope, action);
      if (!readOnly) clearPublicationMarker(root, token);
      return result;
    } finally { scope.active = false; }
  });
}
export function readSnapshots(root) {
  const dir = path.join(root, 'snapshots');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter(f => f.endsWith('.json')).map(f => {
    const value = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    if (!value.experimentId || !value.articleId || !value.before || !value.after || !value.manifestHash) throw new Error(`Invalid SEO publication snapshot: ${f}`);
    return value;
  });
}
// Protected records are never sent to full-row upsert, even when unchanged. This
// prevents a later remote edit racing the full sync from being overwritten.
export function guardArticleRows(rows, root = seoRoot()) {
  const scope = publicationScope.getStore();
  if (scope && (!scope.active || scope.root !== path.resolve(root))) throw new Error('SEO guard publication lease is expired or covers another root');
  const config = scope ? null : routeFor(root);
  let protectedArticles;
  if (scope?.mode === 'ssh') {
    protectedArticles = scope.protectedArticles;
  } else {
    if (config?.mode === 'ssh') throw new Error('Remote SEO guard requires an active shared publication lease');
    if (config || scope?.requireCanonical) assertCanonicalState(root);
    protectedArticles = readSnapshots(root).map(record => ({ articleId: record.articleId, beforeHash: articleHash(record.before), afterHash: articleHash(record.after) }));
  }
  return rows.filter(row => {
    const records = protectedArticles.filter(record => record.articleId === row.id);
    if (!records.length) return true;
    const fingerprint = articleHash(row);
    if (!records.some(record => fingerprint === record.beforeHash || fingerprint === record.afterHash)) {
      throw new Error(`SEO protected article ${row.id} differs from publication snapshot; refusing full sync`);
    }
    return false;
  });
}
