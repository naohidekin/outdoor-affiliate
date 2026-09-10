#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createStore, publicationEventFromJournal } from './state.mjs';
import { PATCH_FIELDS, articleHash, hash, atomicJson, seoRoot, withPublicationLock } from './article-guard.mjs';

export { articleHash } from './article-guard.mjs';
export function manifestHash(manifest) {
  const body = Object.fromEntries(Object.entries(manifest).filter(([key]) => key !== 'approval'));
  return hash(body);
}
export function validateManifest(manifest) {
  if (!/^[a-zA-Z0-9_-]+$/.test(manifest.experimentId || '') || !manifest.articleId || !manifest.slug) throw new Error('Manifest identity required');
  if (!manifest.baseline?.updated_at || !Number.isFinite(Date.parse(manifest.baseline.updated_at)) || !/^[a-f0-9]{64}$/.test(manifest.baseline.hash || '')) throw new Error('Baseline timestamp and hash required');
  const fields = Object.keys(manifest.patches || {});
  if (!fields.length || fields.some(f => !Object.hasOwn(PATCH_FIELDS, f))) throw new Error('Only article editorial fields may be patched');
  for (const field of fields) {
    const value = manifest.patches[field];
    if (field === 'tags' && (!Array.isArray(value) || value.some(v => typeof v !== 'string'))) throw new Error('Invalid tags');
    else if (field === 'faqs' && (!Array.isArray(value) || value.some(v => !v || typeof v.question !== 'string' || typeof v.answer !== 'string' || Object.keys(v).some(k => !['question', 'answer'].includes(k))))) throw new Error('Invalid FAQs');
    else if (!['tags', 'faqs'].includes(field) && (typeof value !== 'string' || !value.trim())) throw new Error(`Invalid ${field}`);
  }
  if (!Array.isArray(manifest.evidence) || !manifest.evidence.length) throw new Error('Evidence required');
  const approval = manifest.approval;
  if (approval?.model !== 'gpt-6-astra' || approval.decision !== 'approved' || approval.manifestHash !== manifestHash(manifest) || approval.evidenceReviewed !== true || approval.noInventedClaims !== true) throw new Error('Astra approval bound to exact manifest and evidence required');
  return manifest;
}
const jstNow = () => new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Tokyo' }).replace(' ', 'T') + '+09:00';
const sameTime = (a, b) => !!a && !!b && Date.parse(a) === Date.parse(b);
const readArticles = file => {
  const raw = fs.readFileSync(file, 'utf8');
  const articles = JSON.parse(raw);
  if (!Array.isArray(articles)) throw new Error('Authoritative article JSON must be array');
  return { raw, articles };
};
function findArticle(articles, id) {
  const matches = articles.filter(a => a.id === id);
  if (matches.length !== 1) throw new Error('Expected exactly one local authoritative article');
  return matches[0];
}
function applyLocal(file, manifest, journal) {
  const lock = `${file}.lock`;
  let fd;
  try { fd = fs.openSync(lock, 'wx'); } catch { throw new Error('Local articles locked by another writer'); }
  try {
    const { raw, articles } = readArticles(file);
    const local = findArticle(articles, manifest.articleId);
    if (articleHash(local) === articleHash(journal.after)) return;
    if (articleHash(local) !== articleHash(journal.before)) throw new Error('Local target changed since approved baseline');
    const updated = articles.map(a => a.id === manifest.articleId ? { ...a, ...manifest.patches, updatedAt: journal.after.updated_at } : a);
    if (fs.readFileSync(file, 'utf8') !== raw) throw new Error('Local article file changed concurrently');
    atomicJson(file, updated);
  } finally { fs.closeSync(fd); fs.unlinkSync(lock); }
}
// Fail closed when rendered HTML cannot demonstrate the changed material. A 200
// response alone is never a publication verification. Markdown is rendered by
// the site, so compare visible prose rather than raw Markdown punctuation.
function text(value) {
  return String(value).replace(/\\u003c/g, '<').replace(/\\"/g, '"').replace(/&quot;/g, '"').replace(/&#(?:39|x27);/g, "'").replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/<\/?(?:p|div|br|li|tr|td|th|h[1-6])\b[^>]*>/gi, ' ').replace(/<[^>]+>/g, '').replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/(^|\n)\s*[#>*+|-]+\s*/g, '$1').replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim();
}
export function verifyPublicHtml(html, manifest, before) {
  // Exclude scripts: stale rendered content cannot pass via unrelated embedded data.
  const visible = text(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ''));
  const all = text(html);
  const visibleHtml = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  const blocks = new Set([...visibleHtml.matchAll(/<(p|li|td|th|h[1-6])\b[^>]*>([\s\S]*?)<\/\1>/gi)].map(match=>text(match[2])));
  const href = value => new URL(value.replace(/&amp;/g,'&'), 'https://camp-gear-lab.com').href;
  const markdownLinks = value => new Set([...String(value).matchAll(/(?<!!)\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)/g)].map(match=>href(match[1])));
  for (const [field, value] of Object.entries(manifest.patches)) {
    if (field === 'content') {
      const oldLines = new Set(String(before.content).split('\n').map(text).filter(Boolean));
      const newLines = String(value).split('\n').map(text).filter(Boolean);
      const added = newLines.filter(line => !oldLines.has(line));
      const removed = [...oldLines].filter(line => !newLines.includes(line));
      const oldLinks=markdownLinks(before.content),newLinks=markdownLinks(value);
      const addedLinks=[...newLinks].filter(link=>!oldLinks.has(link)),removedLinks=[...oldLinks].filter(link=>!newLinks.has(link));
      const publicLinks=new Set([...visibleHtml.matchAll(/<a\b[^>]*href=["']([^"']*)["']/gi)].map(match=>href(match[1])));
      if (!added.length && !removed.length && !addedLinks.length && !removedLinks.length) throw new Error('Content change has no verifiable rendered text or links');
      if (added.some(line => !visible.includes(line)) || removed.some(line => blocks.has(line))) throw new Error('Public content does not match changed paragraphs');
      if(addedLinks.some(link=>!publicLinks.has(link)) || removedLinks.some(link=>publicLinks.has(link))) throw new Error('Public content links mismatch');
    } else if (field === 'faqs') {
      const old = before.faqs || [];
      const changed=value.filter(f=>!old.some(previous=>previous.question===f.question && previous.answer===f.answer));
      const entities=[];
      const visit=node=>{if(!node||typeof node!=='object')return;if(node['@type']==='FAQPage')entities.push(...(node.mainEntity||[]));for(const value of Object.values(node))if(typeof value==='object'){if(Array.isArray(value))value.forEach(visit);else visit(value);}};
      for(const match of html.matchAll(/<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)){try{visit(JSON.parse(match[1]));}catch{throw new Error('Invalid public structured data');}}
      if (changed.some(f => !visible.includes(text(f.question)) || !visible.includes(text(f.answer)) || !entities.some(e=>text(e.name)===text(f.question) && text(e.acceptedAnswer?.text)===text(f.answer)))) throw new Error('Public FAQs mismatch');
      if (old.some(f => !value.some(n => n.question === f.question) && visible.includes(text(f.question)))) throw new Error('Removed FAQ remains public');
    } else if (field === 'tags') {
      if (value.some(tag => !html.includes(`content="${tag.replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"`))) throw new Error('Public tags mismatch');
      if ((before.tags || []).some(tag => !value.includes(tag) && html.includes(`content="${tag}"`))) throw new Error('Removed tag remains public');
    } else if (field === 'title') {
      if (![...html.matchAll(/<h1\b[^>]*>([\s\S]*?)<\/h1>/gi)].some(match => text(match[1]) === text(value))) throw new Error('Public title mismatch');
    } else if (field === 'metaDescription') {
      const descriptions = [...html.matchAll(/<meta\b[^>]*>/gi)].map(match => match[0]).filter(tag => /name=["']description["']/i.test(tag));
      if (!descriptions.some(tag => { const match = tag.match(/content="([^"]*)"/i); return match && text(match[1]) === text(value); })) throw new Error('Public metaDescription mismatch');
    } else if (!all.includes(text(value))) throw new Error(`Public ${field} mismatch`);
  }
  return true;
}
export function supabaseAdapter(client) {
  return {
    async read(id) {
      const { data, error } = await client.from('articles').select('*').eq('id', id).single();
      if (error) throw new Error(`Article read failed: ${error.message}`);
      return data;
    },
    async compareAndSwap(id, updatedAt, patches) {
      const { data, error } = await client.from('articles').update(patches).eq('id', id).eq('updated_at', updatedAt).select('*');
      if (error) throw new Error(`Article conditional update failed: ${error.message}`);
      if (!data || data.length !== 1) throw new Error('Article changed concurrently; conditional update affected zero rows');
      return data[0];
    },
  };
}
export async function publishExperiment(manifest, options) {
  validateManifest(manifest);
  const { db, root = seoRoot(), articlesFile = path.join(root, 'mirror/articles.json'), apply = false, revalidateSecret, fetchImpl = fetch, now = jstNow, onStatus = async () => {}, authorize = async () => { throw new Error('Persistent experiment approval authorization required'); } } = options;
  // Dry-run still validates remote and local evidence, but never creates files,
  // acquires locks, changes experiment state, or contacts revalidation.
  const run = async () => {
    await authorize(manifest);
    const snapshotFile = path.join(root, 'snapshots', `${manifest.experimentId}.json`);
    let journal = fs.existsSync(snapshotFile) ? JSON.parse(fs.readFileSync(snapshotFile, 'utf8')) : null;
    if (journal && journal.manifestHash !== manifestHash(manifest)) throw new Error('Experiment already has a different publication manifest');
    const current = await db.read(manifest.articleId);
    const local = findArticle(readArticles(articlesFile).articles, manifest.articleId);
    if (!current?.updated_at || !Number.isFinite(Date.parse(current.updated_at))) throw new Error('Remote updated_at missing');
    if (current.id !== manifest.articleId || current.slug !== manifest.slug || current.status !== 'published' || local.slug !== manifest.slug) throw new Error('Article identity or published status mismatch');
    const alreadyApplied = journal && articleHash(current) === articleHash(journal.after) && sameTime(current.updated_at, journal.after.updated_at);
    if (!alreadyApplied && (articleHash(current) !== manifest.baseline.hash || !sameTime(current.updated_at, manifest.baseline.updated_at))) throw new Error('Remote baseline changed; refusing stale publication');
    if (articleHash(local) !== manifest.baseline.hash && !(alreadyApplied && articleHash(local) === articleHash(current))) throw new Error('Local authoritative article differs from approved baseline');
    if (!apply) return { status: 'dry_run', experimentId: manifest.experimentId, fields: Object.keys(manifest.patches), alreadyApplied: !!alreadyApplied };
    if (!revalidateSecret) throw new Error('REVALIDATE_SECRET required before applying publication');
    if (!alreadyApplied) {
      const patch = Object.fromEntries(Object.entries(manifest.patches).map(([key, value]) => [PATCH_FIELDS[key], value]));
      patch.updated_at = now();
      if (Date.parse(patch.updated_at) <= Date.parse(current.updated_at)) throw new Error('Publication timestamp must advance baseline');
      if (articleHash({ ...current, ...patch }) === articleHash(current)) throw new Error('Manifest does not change any article fields');
      journal = { experimentId: manifest.experimentId, articleId: manifest.articleId, manifestHash: manifestHash(manifest), status: 'prepared', before: current, after: { ...current, ...patch }, preparedAt: now() };
      atomicJson(snapshotFile, journal);
      await onStatus('prepared', journal);
      await authorize(manifest);
      const result = await db.compareAndSwap(manifest.articleId, current.updated_at, patch);
      if (articleHash(result) !== articleHash(journal.after)) throw new Error('Conditional update returned unexpected article fields');
      journal.after = result;
      journal.status = 'remote_applied';
      atomicJson(snapshotFile, journal);
    }
    try {
      journal.status = 'remote_applied';
      await onStatus('remote_applied', journal);
      applyLocal(articlesFile, manifest, journal);
      const response = await fetchImpl('https://camp-gear-lab.com/api/revalidate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-revalidate-secret': revalidateSecret }, body: JSON.stringify({ slug: manifest.slug, categoryId: current.category_id }), signal: AbortSignal.timeout(30000) });
      if (!response.ok) throw new Error(`ISR revalidation failed: ${response.status}`);
      const publicResponse = await fetchImpl(`https://camp-gear-lab.com/articles/${encodeURIComponent(manifest.slug)}`, { cache: 'no-store', signal: AbortSignal.timeout(30000) });
      if (!publicResponse.ok) throw new Error(`Public page failed: ${publicResponse.status}`);
      verifyPublicHtml(await publicResponse.text(), manifest, journal.before);
      const confirmed = await db.read(manifest.articleId);
      if (articleHash(confirmed) !== articleHash(journal.after) || !sameTime(confirmed.updated_at, journal.after.updated_at)) throw new Error('Remote article changed during public verification');
      journal.status = 'verified';
      journal.verifiedAt = now();
      delete journal.error;
      atomicJson(snapshotFile, journal);
      await onStatus('verified', journal);
      return { status: 'verified', experimentId: manifest.experimentId, snapshotFile };
    } catch (error) {
      journal.status = 'verification_pending';
      journal.error = error.message;
      atomicJson(snapshotFile, journal);
      await onStatus('verification_pending', journal);
      return { status: 'verification_pending', experimentId: manifest.experimentId, error: error.message, snapshotFile };
    }
  };
  return apply ? withPublicationLock(root, run) : run();
}

async function main() {
  const args = process.argv.slice(2);
  const value = flag => args[args.indexOf(flag) + 1];
  if (!args.includes('--manifest')) throw new Error('Usage: publish.mjs --manifest FILE [--apply] [--env-file PROJECT/.env.local]');
  const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const envFile = args.includes('--env-file') ? path.resolve(value('--env-file')) : path.join(projectRoot, '.env.local');
  // Caller explicitly identifies this project's environment file; never search.
  if (fs.existsSync(envFile)) process.loadEnvFile(envFile);
  const { createClient } = await import('@supabase/supabase-js');
  if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_ROLE_KEY) throw new Error('Project Supabase environment not configured');
  const manifest = JSON.parse(fs.readFileSync(path.resolve(value('--manifest')), 'utf8'));
  const root = args.includes('--root') ? path.resolve(value('--root')) : seoRoot(projectRoot);
  const store = createStore({ root });
  const result = await publishExperiment(manifest, {
    root, articlesFile: args.includes('--articles-file') ? path.resolve(value('--articles-file')) : path.join(root, 'mirror/articles.json'), apply: args.includes('--apply'), revalidateSecret: process.env.REVALIDATE_SECRET,
    db: supabaseAdapter(createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY)),
    authorize: async () => {
      const experiment = await store.get(manifest.experimentId);
      if (!experiment || !['approved', 'publishing', 'verification_pending', 'observing'].includes(experiment.status)) throw new Error('Experiment is not approved for publication');
      if (hash(experiment.approval) !== hash(manifest.approval) || experiment.beforeContentHash !== manifest.baseline.hash || experiment.urls?.canonical !== `https://camp-gear-lab.com/articles/${manifest.slug}`) throw new Error('Persistent experiment approval does not match publication manifest');
    },
    onStatus: async (_status, journal) => store.event(manifest.experimentId, publicationEventFromJournal(journal)),
  });
  console.log(JSON.stringify(result, null, 2));
  if (result.status === 'verification_pending') process.exitCode = 2;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch(error => { console.error(error.message); process.exitCode = 1; });
