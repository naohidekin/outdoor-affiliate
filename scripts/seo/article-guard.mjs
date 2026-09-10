import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';

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
export function seoRoot() { return path.resolve(process.env.SEO_STATE_ROOT || path.join(os.homedir(), '.secretary/state/campgearlab-seo')); }
export function atomicJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  const fd = fs.openSync(tmp, 'wx', 0o600);
  try { fs.writeFileSync(fd, `${JSON.stringify(value, null, 2)}\n`); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  fs.renameSync(tmp, file);
  const dir = fs.openSync(path.dirname(file), 'r');
  try { fs.fsyncSync(dir); } finally { fs.closeSync(dir); }
}
export async function withPublicationLock(root, action) {
  fs.mkdirSync(root, { recursive: true });
  const lock = path.join(root, '.publication.lock');
  try { fs.mkdirSync(lock); } catch (error) { if (error.code === 'EEXIST') throw new Error('SEO publication/sync lock held; inspect unfinished publication before retry'); throw error; }
  try { return await action(); } finally { fs.rmdirSync(lock); }
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
  const snapshots = readSnapshots(root);
  return rows.filter(row => {
    const records = snapshots.filter(s => s.articleId === row.id);
    if (!records.length) return true;
    const fingerprint = articleHash(row);
    if (!records.some(s => fingerprint === articleHash(s.before) || fingerprint === articleHash(s.after))) {
      throw new Error(`SEO protected article ${row.id} differs from publication snapshot; refusing full sync`);
    }
    return false;
  });
}
