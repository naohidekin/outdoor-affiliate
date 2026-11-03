/** Dedicated public bucket transport. --setup is the only bucket creation path. */
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import sharp from 'sharp';

export const BUCKET = 'editorial-social-cards';
const MAX = 2 * 1024 * 1024;
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const requireValue = (ok, code) => { if (!ok) throw new Error(code); };

export function storageOrigin(env) {
  const raw = env.SUPABASE_URL;
  requireValue(typeof raw === 'string' && /^https:\/\/[^\s]+$/.test(raw), 'storage_unconfigured');
  let url;
  try { url = new URL(raw); } catch { throw new Error('storage_unconfigured'); }
  requireValue(url.protocol === 'https:' && url.hostname && !url.username && !url.password &&
    !url.search && !url.hash && url.pathname === '/' && (!url.port || url.port === '443'), 'storage_unconfigured');
  requireValue(typeof env.SUPABASE_SERVICE_ROLE_KEY === 'string' && env.SUPABASE_SERVICE_ROLE_KEY.length > 0,
    'storage_unconfigured');
  return url.origin;
}

export async function storageRequest(env, path, method, body, fetcher = fetch, contentType) {
  const origin = storageOrigin(env);
  const headers = { apikey: env.SUPABASE_SERVICE_ROLE_KEY,
    Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}` };
  if (contentType) headers['Content-Type'] = contentType;
  let response;
  try {
    response = await fetcher(origin + path, { method, headers, body, redirect: 'error',
      signal: AbortSignal.timeout(30000) });
  } catch { throw new Error('storage_transport_unknown'); }
  return response;
}

export async function setupBucket(env, fetcher = fetch) {
  // Invoked explicitly with --setup; the article build path never calls this.
  const response = await storageRequest(env, '/storage/v1/bucket', 'POST', JSON.stringify({
    id: BUCKET, name: BUCKET, public: true, file_size_limit: MAX,
    allowed_mime_types: ['image/png'],
  }), fetcher, 'application/json');
  requireValue(response.status === 200 || response.status === 201, 'storage_bucket_setup_failed');
  return { created: true, bucket: BUCKET };
}

export async function uploadCard(env, input, fetcher = fetch) {
  requireValue(input && typeof input === 'object' &&
    /^[a-f0-9]{2}\/[a-f0-9]{64}\.png$/.test(input.path || ''), 'storage_path_invalid');
  requireValue(typeof input.dataBase64 === 'string' && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(input.dataBase64),
    'storage_data_invalid');
  const bytes = Buffer.from(input.dataBase64, 'base64');
  requireValue(bytes.length > 0 && bytes.length <= MAX && input.dataBase64 === bytes.toString('base64') &&
    bytes.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex')), 'storage_data_invalid');
  try {
    const meta = await sharp(bytes, { limitInputPixels: 1200 * 630 }).metadata();
    requireValue(meta.format === 'png' && meta.width === 1200 && meta.height === 630 &&
      (meta.pages || 1) === 1, 'storage_data_invalid');
    await sharp(bytes, { limitInputPixels: 1200 * 630 }).raw().toBuffer();
  } catch { throw new Error('storage_data_invalid'); }
  const sha = digest(bytes);
  requireValue(input.path === `${sha.slice(0, 2)}/${sha}.png`, 'storage_path_hash_mismatch');
  const origin = storageOrigin(env);
  const bucket = await storageRequest(env, `/storage/v1/bucket/${BUCKET}`, 'GET', undefined, fetcher);
  requireValue(bucket.status === 200, 'storage_bucket_absent');
  let info;
  try { info = await bucket.json(); } catch { throw new Error('storage_bucket_invalid'); }
  requireValue(info?.id === BUCKET && info.public === true && info.file_size_limit === MAX &&
    Array.isArray(info.allowed_mime_types) && info.allowed_mime_types.length === 1 &&
    info.allowed_mime_types[0] === 'image/png', 'storage_bucket_invalid');
  let posted = false;
  try {
    const post = await storageRequest(env, `/storage/v1/object/${BUCKET}/${input.path}`, 'POST', bytes,
      async (url, options) => fetcher(url, { ...options, headers: { ...options.headers, 'x-upsert': 'false' } }), 'image/png');
    posted = post.status === 200 || post.status === 201;
  } catch {
    // A timed-out POST may already have committed. Never send a second POST.
  }
  const url = `${origin}/storage/v1/object/public/${BUCKET}/${input.path}`;
  let read;
  try { read = await fetcher(url, { method: 'GET', redirect: 'error', signal: AbortSignal.timeout(30000) }); }
  catch { throw new Error(posted ? 'storage_readback_failed' : 'storage_upload_unknown'); }
  requireValue(read.status === 200 && read.headers.get('content-type')?.split(';')[0].toLowerCase() === 'image/png',
    posted ? 'storage_readback_failed' : 'storage_upload_unknown');
  const actual = Buffer.from(await read.arrayBuffer());
  requireValue(actual.length === bytes.length && digest(actual) === sha,
    posted ? 'storage_readback_mismatch' : 'storage_existing_mismatch');
  return { verified: true, url, path: input.path, sha256: sha, size: bytes.length };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    let input = '';
    for await (const chunk of process.stdin) { input += chunk; requireValue(input.length <= 3 * MAX, 'storage_input_too_large'); }
    const payload = input.trim() ? JSON.parse(input) : {};
    const value = process.argv.includes('--setup') ? await setupBucket(process.env) : await uploadCard(process.env, payload);
    process.stdout.write(JSON.stringify(value));
  } catch {
    // Never print Supabase responses, request URLs, supplied data or credentials.
    process.stdout.write(JSON.stringify({ verified: false, error: 'social_card_storage_failed' }));
    process.exitCode = 1;
  }
}
