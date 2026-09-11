import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';

const HELPER = `import fcntl, os, sys
try:
    fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('BUSY', flush=True)
        sys.exit(3)
    print('READY', flush=True)
    while sys.stdin.buffer.read(4096):
        pass
    os.close(fd)
except Exception:
    print('ERROR', flush=True)
    sys.exit(4)
`;

async function rejectLegacyLock(lockFile) {
  if (!lockFile.endsWith('.flock')) throw new Error('SEO process lock must use a .flock file');
  try { await fs.lstat(lockFile.slice(0, -6) + '.lock'); }
  catch (error) { if (error.code === 'ENOENT') return; throw new Error('SEO lock migration inspection failed'); }
  throw new Error('SEO legacy active lock exists; migration requires confirmed inactivity and operator cleanup');
}

/**
 * Kernel-owned lock with a stdin lease. Files are permanent and never unlinked.
 * If the helper dies during action, fail-stop the entire Node process (exit 70).
 * Rejecting a Promise cannot cancel arbitrary in-flight actions; continuing after
 * losing ownership would permit concurrent writes. Callers must retry from their
 * durable journals after this fail-stop, never catch and continue the old action.
 */
export async function withProcessLock(lockFile, action) {
  lockFile = path.resolve(lockFile);
  await rejectLegacyLock(lockFile);
  await fs.mkdir(path.dirname(lockFile), { recursive: true });
  const child = spawn(process.env.SEO_LOCK_PYTHON || 'python3', ['-u', '-c', HELPER, lockFile], { stdio: ['pipe', 'pipe', 'pipe'] });
  return withLease(child, async () => {
    await rejectLegacyLock(lockFile);
    return action();
  }, false, 5000);
}

const REMOTE_HELPER = `import datetime, fcntl, json, os, socket, subprocess, sys, uuid
try:
    root, node, exporter, read_only = sys.argv[1:5]
    marker = os.path.join(root, '.publication.in-flight.json')
    legacy = os.path.join(root, '.publication.lock')
    if os.path.lexists(legacy):
        print('MIGRATION', flush=True)
        sys.exit(5)
    fd = os.open(os.path.join(root, '.publication.flock'), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('BUSY', flush=True)
        sys.exit(3)
    if os.path.lexists(legacy):
        print('MIGRATION', flush=True)
        sys.exit(5)
    if os.path.lexists(marker):
        print('INFLIGHT', flush=True)
        sys.exit(6)
    result = subprocess.run([node, exporter, '--root', root], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=True)
    data = json.loads(result.stdout)
    token = uuid.uuid4().hex
    if read_only != 'true':
        # Never replace a marker created by a delayed former local owner.
        # O_EXCL closes the gap after the earlier existence check.
        handle = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(handle, 'w') as out:
            json.dump({'schemaVersion': 1, 'token': token, 'createdAt': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(), 'owner': {'host': socket.gethostname(), 'pid': os.getpid()}}, out)
            out.flush()
            os.fsync(out.fileno())
        directory = os.open(root, os.O_RDONLY)
        os.fsync(directory)
        os.close(directory)
    print('PROTECTED ' + json.dumps(data, separators=(',', ':')), flush=True)
    print('READY', flush=True)
    for line in sys.stdin:
        if line.strip() == 'RELEASE' and read_only != 'true':
            with open(marker) as source:
                stored = json.load(source)
            if stored.get('token') != token:
                raise RuntimeError('marker ownership changed')
            os.unlink(marker)
            directory = os.open(root, os.O_RDONLY)
            os.fsync(directory)
            os.close(directory)
            print('RELEASED', flush=True)
            break
    os.close(fd)
except Exception:
    print('ERROR', flush=True)
    sys.exit(4)
`;

// ssh executes one remote command through the account's shell; quote every
// argument, including the embedded Python, instead of concatenating raw paths.
function shellQuote(value) { return "'" + String(value).replace(/'/g, "'\"'\"'") + "'"; }
export async function withRemoteProcessLock(options, action, { readOnly = false } = {}) {
  if (typeof readOnly !== 'boolean') throw new Error('Publication readOnly must be an explicit boolean');
  const { host, stateRoot, exportScript, node = 'node', python = 'python3', sshBinary = 'ssh' } = options;
  if (typeof host !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.@-]*$/.test(host)) throw new Error('Invalid SEO guard SSH host');
  for (const value of [stateRoot, exportScript]) if (typeof value !== 'string' || !path.isAbsolute(value) || value.includes('\0')) throw new Error('SEO guard remote paths must be absolute');
  for (const value of [node, python]) if (typeof value !== 'string' || !value || value.includes('\0')) throw new Error('Invalid SEO guard remote executable');
  const command = 'exec ' + [python, '-u', '-c', REMOTE_HELPER, stateRoot, node, exportScript, String(readOnly)].map(shellQuote).join(' ');
  const child = spawn(sshBinary, ['-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2', host, command], { stdio: ['pipe', 'pipe', 'pipe'] });
  return withLease(child, action, true, 45000, !readOnly);
}

async function withLease(child, action, requireProtected, acquireTimeout, explicitRelease = false) {
  let ready = false, releasing = false, closed = false, buffer = '', protectedData, succeeded = false, releaseAcknowledged = false;
  let resolveClosed;
  const closedPromise = new Promise(resolve => { resolveClosed = resolve; });
  child.stderr.resume(); // Never expose SSH/Python paths, argv or raw errors.
  child.stdin.on('error', () => {});
  child.on('exit', () => {
    if (ready && !releasing) {
      process.stderr.write('SEO lock ownership lost; terminating process safely\n');
      process.exit(70);
    }
  });
  child.on('close', () => { closed = true; resolveClosed(); });
  let timer;
  try {
    await new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error('SEO lock acquisition timed out')), acquireTimeout);
      child.once('error', () => reject(new Error('SEO lock helper could not start')));
      child.once('exit', () => { if (!ready) reject(new Error('SEO lock helper exited before acquisition')); });
      child.stdout.on('data', chunk => {
        if (ready) {
          buffer += chunk.toString();
          if (buffer.split('\n').includes('RELEASED')) releaseAcknowledged = true;
          return;
        }
        buffer += chunk.toString();
        if (buffer.length > 4 * 1024 * 1024) return reject(new Error('SEO lock response exceeded size limit'));
        let end;
        while ((end = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
          if (requireProtected && line.startsWith('PROTECTED ')) {
            try { protectedData = JSON.parse(line.slice(10)); }
            catch { return reject(new Error('SEO remote protection response invalid')); }
          } else if (line === 'READY') {
            if (requireProtected && !protectedData) return reject(new Error('SEO remote protection response missing'));
            ready = true; resolve(); return;
          } else {
            reject(new Error(line === 'BUSY' ? 'SEO lock held by another process' : line === 'MIGRATION' ? 'SEO legacy active lock exists; migration requires operator cleanup' : line === 'INFLIGHT' ? 'SEO publication in-flight marker exists; reconcile DB before operator clearance' : 'SEO lock helper acquisition failed'));
            return;
          }
        }
      });
    });
    clearTimeout(timer);
    const result = await action(protectedData);
    succeeded = true;
    return result;
  } finally {
    clearTimeout(timer);
    releasing = true;
    child.stdin.end(explicitRelease && succeeded ? 'RELEASE\n' : undefined);
    if (!closed) {
      const cleanupTimer = setTimeout(() => child.kill('SIGKILL'), 2000);
      await closedPromise;
      clearTimeout(cleanupTimer);
    }
    if (explicitRelease && succeeded && !releaseAcknowledged) throw new Error('SEO publication release was not confirmed; inspect the in-flight marker');
  }
}
