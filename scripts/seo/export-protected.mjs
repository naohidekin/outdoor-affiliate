#!/usr/bin/env node
// Read-only export for a caller already holding canonical .publication.flock.
// No article text, evidence, credentials or local filesystem paths are emitted.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readSnapshots, articleHash, assertCanonicalState, validateProtection } from './article-guard.mjs';

export function exportProtected(root) {
  assertCanonicalState(root);
  const protectedArticles = readSnapshots(root).map(record => {
    if (record.before.id !== record.articleId || record.after.id !== record.articleId) throw new Error('Publication journal article identity mismatch');
    return { articleId: record.articleId, beforeHash: articleHash(record.before), afterHash: articleHash(record.after) };
  });
  const result = { schemaVersion: 1, protectedArticles };
  validateProtection(result);
  return result;
}
function main(args = process.argv.slice(2)) {
  const index = args.indexOf('--root');
  if (index < 0 || !args[index + 1] || !path.isAbsolute(args[index + 1])) throw new Error('An explicit canonical --root is required');
  process.stdout.write(JSON.stringify(exportProtected(args[index + 1])) + '\n');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch { process.stderr.write('SEO protection export failed\n'); process.exitCode = 1; }
}
