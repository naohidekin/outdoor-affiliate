import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { withProcessLock } from '../scripts/seo/process-lock.mjs';

const moduleUrl = new URL('../scripts/seo/process-lock.mjs', import.meta.url).href;
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function temporary(t: { after: (fn: () => Promise<void>) => void }) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'seo-flock-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return root;
}
function childProgram(lock: string, tail: string) {
  return `import {withProcessLock} from ${JSON.stringify(moduleUrl)}; await withProcessLock(${JSON.stringify(lock)}, async () => { console.log('ACQUIRED'); ${tail} });`;
}
async function ready(child: ReturnType<typeof spawn>) {
  let received = '';
  return new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Child acquisition timeout')), 5000);
    child.stdout?.on('data', chunk => {
      received += chunk;
      if (received.includes('ACQUIRED')) { clearTimeout(timeout); resolve(); }
    });
    child.once('exit', code => { clearTimeout(timeout); if (!received.includes('ACQUIRED')) reject(new Error(`Child exited: ${code}`)); });
  });
}

test('real Python flock excludes another process and leaves its inode in place', async t => {
  const root = await temporary(t);
  const lock = path.join(root, '.state.flock');
  await withProcessLock(lock, async () => {
    const child = spawn(process.execPath, ['--input-type=module', '-e', childProgram(lock, '')], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    child.stderr.on('data', chunk => { stderr += chunk; });
    const [code] = await once(child, 'close');
    assert.notEqual(code, 0);
    assert.match(stderr, /lock held/);
  });
  const first = await fs.stat(lock);
  await withProcessLock(lock, async () => {});
  assert.equal((await fs.stat(lock)).ino, first.ino);
});

test('SIGKILL of Node closes helper lease and the next process recovers without removing files', async t => {
  const root = await temporary(t);
  const lock = path.join(root, 'usage.json.flock');
  const child = spawn(process.execPath, ['--input-type=module', '-e', childProgram(lock, 'await new Promise(()=>{});')], { stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
  await ready(child);
  const inode = (await fs.stat(lock)).ino;
  child.kill('SIGKILL');
  await once(child, 'close');
  let acquired = false;
  for (let i = 0; i < 20 && !acquired; i++) {
    try { await withProcessLock(lock, async () => { acquired = true; }); }
    catch (error) { if (!String(error).includes('lock held')) throw error; await pause(25); }
  }
  assert.equal(acquired, true);
  assert.equal((await fs.stat(lock)).ino, inode);
});

test('unexpected helper death fail-stops Node before action can continue', async t => {
  const root = await temporary(t);
  const fake = path.join(root, 'dies-after-ready.py');
  const marker = path.join(root, 'must-not-exist');
  await fs.writeFile(fake, '#!/usr/bin/env python3\nimport time\nprint("READY",flush=True)\ntime.sleep(.15)\n', {mode:0o700});
  const child = spawn(process.execPath, ['--input-type=module', '-e', childProgram(path.join(root, 'test.flock'), `await new Promise(r=>setTimeout(r,700)); (await import('node:fs')).writeFileSync(${JSON.stringify(marker)}, 'unsafe');`)], { env:{...process.env, SEO_LOCK_PYTHON:fake}, stdio:['ignore','pipe','pipe'] });
  let stderr = '';
  child.stderr.on('data', chunk => { stderr += chunk; });
  const [code] = await once(child, 'close');
  assert.equal(code, 70);
  assert.equal(stderr.trim(), 'SEO lock ownership lost; terminating process safely');
  await assert.rejects(fs.access(marker));
});

test('legacy directory or file locks require migration and are never removed', async t => {
  const root = await temporary(t);
  for (const isDirectory of [true, false]) {
    const lock = path.join(root, `${isDirectory}.flock`);
    const old = lock.replace('.flock', '.lock');
    if (isDirectory) await fs.mkdir(old); else await fs.writeFile(old, 'old-owner');
    await assert.rejects(withProcessLock(lock, async () => assert.fail('must not execute')), /migration/);
    await fs.lstat(old);
    await assert.rejects(fs.access(lock));
  }
});

test('action failure releases kernel ownership', async t => {
  const root = await temporary(t);
  const lock = path.join(root, '.publication.flock');
  await assert.rejects(withProcessLock(lock, async () => { throw new Error('injected'); }), /injected/);
  await withProcessLock(lock, async () => {});
});
