import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import { articleHash, guardArticleRows, seoRoot, withPublicationLock } from '../scripts/seo/article-guard.mjs';
import { withProcessLock, withRemoteProcessLock } from '../scripts/seo/process-lock.mjs';
import { exportProtected } from '../scripts/seo/export-protected.mjs';

const exporter = fileURLToPath(new URL('../scripts/seo/export-protected.mjs', import.meta.url));
const guardModule = new URL('../scripts/seo/article-guard.mjs', import.meta.url).href;
async function fixture(t: { after: (fn: () => Promise<void>) => void }) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'seo-remote-guard-'));
  const stateRoot = path.join(root, "canonical's state");
  await fs.mkdir(path.join(stateRoot, 'snapshots'), {recursive:true});
  await fs.writeFile(path.join(stateRoot, 'state.json'), JSON.stringify({schemaVersion:1,experiments:[]}));
  const before = {id:'article-1',slug:'tent',title:'Before',content:'PRIVATE PROSE',status:'published'};
  const after = {...before,title:'After'};
  await fs.writeFile(path.join(stateRoot, 'snapshots/exp-1.json'), JSON.stringify({experimentId:'exp-1',articleId:before.id,manifestHash:'hash',before,after}));
  // Transport simulator executes exactly the quoted remote argv locally. It does
  // not invoke a shell, connect to a host, or read SSH configuration/credentials.
  const sshBinary = path.join(root, 'fake-ssh.py');
  await fs.writeFile(sshBinary, '#!/usr/bin/env python3\nimport os,shlex,sys\na=shlex.split(sys.argv[-1]);assert a.pop(0)=="exec";os.execvp(a[0],a)\n', {mode:0o700});
  const config = {schemaVersion:1,mode:'ssh',host:'fake-macpro',stateRoot,exportScript:exporter,node:process.execPath,python:'python3',sshBinary};
  const configFile = path.join(root,'guard.json');
  await fs.writeFile(configFile,JSON.stringify(config));
  const oldConfig = process.env.SEO_GUARD_CONFIG, oldRoot = process.env.SEO_STATE_ROOT;
  process.env.SEO_GUARD_CONFIG=configFile;delete process.env.SEO_STATE_ROOT;
  t.after(async()=>{
    if(oldConfig===undefined)delete process.env.SEO_GUARD_CONFIG;else process.env.SEO_GUARD_CONFIG=oldConfig;
    if(oldRoot===undefined)delete process.env.SEO_STATE_ROOT;else process.env.SEO_STATE_ROOT=oldRoot;
    await fs.rm(root,{recursive:true,force:true});
  });
  return {root,stateRoot,before,after,config,configFile};
}

test('SSH lease exports fingerprints and blocks canonical publication throughout legacy sync',async t=>{
  const f=await fixture(t);
  assert.equal(seoRoot(),f.stateRoot);
  assert.throws(()=>guardArticleRows([f.before]),/active shared publication lease/);
  await withPublicationLock(seoRoot(),async()=>{
    await fs.access(path.join(f.stateRoot,'.publication.in-flight.json'));
    assert.deepEqual(guardArticleRows([f.before,{id:'new-article'}]),[{id:'new-article'}]);
    assert.deepEqual(guardArticleRows([f.after]),[]);
    assert.throws(()=>guardArticleRows([{...f.before,title:'Stale conflicting title'}]),/refusing full sync/);
    await assert.rejects(withProcessLock(path.join(f.stateRoot,'.publication.flock'),async()=>assert.fail('must remain locked')),/lock held/);
  });
  await assert.rejects(fs.access(path.join(f.stateRoot,'.publication.in-flight.json')));
  await withProcessLock(path.join(f.stateRoot,'.publication.flock'),async()=>{});
  assert.throws(()=>guardArticleRows([f.before]),/active shared publication lease/);
});

test('export contains only protected identifiers and fingerprints, never article prose',async t=>{
  const f=await fixture(t);
  const data=exportProtected(f.stateRoot);
  assert.deepEqual(data,{schemaVersion:1,protectedArticles:[{articleId:f.before.id,beforeHash:articleHash(f.before),afterHash:articleHash(f.after)}]});
  assert.equal(JSON.stringify(data).includes('PRIVATE PROSE'),false);
  await fs.unlink(path.join(f.stateRoot,'state.json'));
  assert.throws(()=>exportProtected(f.stateRoot),/Canonical SEO state/);
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('no export, no sync')),/acquisition failed/);
});

test('remote old locks and SSH failure fail closed without local fallback',async t=>{
  const f=await fixture(t);
  await fs.mkdir(path.join(f.stateRoot,'.publication.lock'));
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('legacy lock')),/migration/);
  await fs.rmdir(path.join(f.stateRoot,'.publication.lock'));
  const bad=path.join(f.root,'ssh-fails.py');
  await fs.writeFile(bad,'#!/usr/bin/env python3\nimport sys\nprint("SECRET RAW SSH ERROR",file=sys.stderr);sys.exit(255)\n',{mode:0o700});
  await assert.rejects(withRemoteProcessLock({...f.config,sshBinary:bad},async()=>assert.fail('ssh unavailable')),error=> !String(error).includes('SECRET') && /before acquisition/.test(String(error)));
});

test('SSH configuration rejects SEO_STATE_ROOT local bypass; local host configuration resolves canonical state',async t=>{
  const f=await fixture(t);
  process.env.SEO_STATE_ROOT=f.root;
  assert.throws(()=>seoRoot(),/conflicts/);
  await fs.writeFile(f.configFile,JSON.stringify({schemaVersion:1,mode:'local',stateRoot:f.stateRoot}));
  assert.equal(seoRoot(),f.root); // Local mode preserves explicit canonical override.
  delete process.env.SEO_STATE_ROOT;
  assert.equal(seoRoot(),f.stateRoot);
  await withPublicationLock(seoRoot(),async()=>assert.deepEqual(guardArticleRows([f.before]),[]));
});

test('SSH loss after READY stops the caller before a later legacy write',async t=>{
  const f=await fixture(t);
  const fake=path.join(f.root,'drops-ssh.py');
  const marker=path.join(f.root,'unsafe-write');
  await fs.writeFile(fake,'#!/usr/bin/env python3\nimport time\nprint(\'PROTECTED {"schemaVersion":1,"protectedArticles":[]}\',flush=True)\nprint("READY",flush=True)\ntime.sleep(.15)\n',{mode:0o700});
  await fs.writeFile(f.configFile,JSON.stringify({...f.config,sshBinary:fake}));
  const code=`import {seoRoot,withPublicationLock} from ${JSON.stringify(guardModule)};await withPublicationLock(seoRoot(),async()=>{await new Promise(r=>setTimeout(r,1000));(await import('node:fs')).writeFileSync(${JSON.stringify(marker)},'unsafe');});`;
  const child=spawn(process.execPath,['--input-type=module','-e',code],{env:{...process.env},stdio:['ignore','pipe','pipe']});
  let stderr='';child.stderr.on('data',chunk=>{stderr+=chunk;});
  const [exitCode]=await once(child,'close');
  assert.equal(exitCode,70);assert.match(stderr,/lock ownership lost/);
  await assert.rejects(fs.access(marker));
});


test('remote action rejection preserves the durable marker and blocks the next publisher',async t=>{
  const f=await fixture(t);
  await assert.rejects(withPublicationLock(seoRoot(),async()=>{throw new Error('ambiguous DB request');}),/ambiguous DB/);
  const marker=path.join(f.stateRoot,'.publication.in-flight.json');
  const saved=await fs.readFile(marker,'utf8');
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('must remain stopped')),/in-flight marker/);
  assert.equal(await fs.readFile(marker,'utf8'),saved);
  // Kernel lock is free; the durable fence, not an orphan lock, prevents writes.
  await withProcessLock(path.join(f.stateRoot,'.publication.flock'),async()=>{});
});

test('killed real remote helper leaves its marker even after the SSH lease disappears',async t=>{
  const f=await fixture(t);
  const marker=path.join(f.stateRoot,'.publication.in-flight.json');
  const code=`import {seoRoot,withPublicationLock} from ${JSON.stringify(guardModule)};await withPublicationLock(seoRoot(),async()=>{const m=JSON.parse((await import('node:fs')).readFileSync(${JSON.stringify(marker)},'utf8'));process.kill(m.owner.pid,'SIGKILL');await new Promise(()=>{});});`;
  const child=spawn(process.execPath,['--input-type=module','-e',code],{env:{...process.env},stdio:['ignore','pipe','pipe']});
  child.stderr.resume();
  const [exitCode]=await once(child,'close');
  assert.equal(exitCode,70);
  await fs.access(marker);
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('unknown DB state')),/in-flight marker/);
});

test('read-only local and SSH failures create no in-flight marker',async t=>{
  const f=await fixture(t);
  for(const mode of ['ssh','local']){
    await fs.writeFile(f.configFile,JSON.stringify({...f.config,mode}));
    await assert.rejects(withPublicationLock(seoRoot(),async()=>{
      await assert.rejects(fs.access(path.join(f.stateRoot,'.publication.in-flight.json')));
      throw new Error('read-only validation failed');
    },{readOnly:true}),/read-only validation/);
    await assert.rejects(fs.access(path.join(f.stateRoot,'.publication.in-flight.json')));
    await withPublicationLock(seoRoot(),async()=>{});
    await assert.rejects(fs.access(path.join(f.stateRoot,'.publication.in-flight.json')));
  }
});

test('local publication failure leaves a durable fence until explicit operator clearance',async t=>{
  const f=await fixture(t);
  await fs.writeFile(f.configFile,JSON.stringify({...f.config,mode:'local'}));
  await assert.rejects(withPublicationLock(seoRoot(),async()=>{throw new Error('write outcome unknown');}),/outcome unknown/);
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('must not publish')),/in-flight marker/);
});

test('Node SIGKILL sends EOF without RELEASE and remote marker blocks the next publication',async t=>{
  const f=await fixture(t);
  const marker=path.join(f.stateRoot,'.publication.in-flight.json');
  const code=`import {seoRoot,withPublicationLock} from ${JSON.stringify(guardModule)};await withPublicationLock(seoRoot(),async()=>{console.log('ACTION_STARTED');await new Promise(()=>{});});`;
  const child=spawn(process.execPath,['--input-type=module','-e',code],{env:{...process.env},stdio:['ignore','pipe','pipe']});
  child.stderr.resume();
  t.after(async()=>{if(child.exitCode===null&&child.signalCode===null)child.kill('SIGKILL');});
  await new Promise<void>((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Action startup timeout')),5000);
    child.stdout.on('data',chunk=>{if(String(chunk).includes('ACTION_STARTED')){clearTimeout(timer);resolve();}});
  });
  await fs.access(marker);
  child.kill('SIGKILL');await once(child,'close');
  let fenced=false;
  for(let i=0;i<20&&!fenced;i++){
    try{await withPublicationLock(seoRoot(),async()=>assert.fail('must remain fenced'));}
    catch(error){if(/in-flight marker/.test(String(error)))fenced=true;else if(!/lock held/.test(String(error)))throw error;}
    if(!fenced)await new Promise(resolve=>setTimeout(resolve,25));
  }
  assert.equal(fenced,true);await fs.access(marker);
});

test('local helper loss leaves the publication marker while generic OS lock can recover',async t=>{
  const f=await fixture(t);
  await fs.writeFile(f.configFile,JSON.stringify({...f.config,mode:'local'}));
  const fake=path.join(f.root,'local-helper-dies.py');
  await fs.writeFile(fake,'#!/usr/bin/env python3\nimport time\nprint("READY",flush=True)\ntime.sleep(.15)\n',{mode:0o700});
  const code=`import {seoRoot,withPublicationLock} from ${JSON.stringify(guardModule)};await withPublicationLock(seoRoot(),async()=>{await new Promise(()=>{});});`;
  const child=spawn(process.execPath,['--input-type=module','-e',code],{env:{...process.env,SEO_LOCK_PYTHON:fake},stdio:['ignore','pipe','pipe']});
  child.stderr.resume();const [exitCode]=await once(child,'close');
  assert.equal(exitCode,70);
  await fs.access(path.join(f.stateRoot,'.publication.in-flight.json'));
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('must remain fenced')),/in-flight marker/);
});


test('local exclusive marker create never overwrites an owner arriving after the existence check',async t=>{
  const f=await fixture(t);
  await fs.writeFile(f.configFile,JSON.stringify({...f.config,mode:'local'}));
  const marker=path.join(f.stateRoot,'.publication.in-flight.json');
  const competing=JSON.stringify({schemaVersion:1,token:'competing-owner',owner:{pid:12345}});
  const originalOpen=fsSync.openSync;
  let injected=false;
  const spy=t.mock.method(fsSync,'openSync',(...args:Parameters<typeof fsSync.openSync>)=>{
    if(String(args[0])===marker&&!injected){
      injected=true;
      const fd=originalOpen(marker,'wx',0o600);
      try{fsSync.writeFileSync(fd,competing);fsSync.fsyncSync(fd);}finally{fsSync.closeSync(fd);}
    }
    return originalOpen(...args);
  });
  try{
    await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('competing owner must prevent action')),error=>(error as NodeJS.ErrnoException).code==='EEXIST');
  }finally{spy.mock.restore();}
  assert.equal(injected,true);
  assert.equal(await fs.readFile(marker,'utf8'),competing);
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('must remain fenced')),/in-flight marker/);
});


test('remote exclusive marker create preserves an owner arriving after its existence check',async t=>{
  const f=await fixture(t);
  const marker=path.join(f.stateRoot,'.publication.in-flight.json');
  const competing=JSON.stringify({schemaVersion:1,token:'delayed-local-owner',owner:{pid:12345}});
  const raceExporter=path.join(f.root,'export-inserts-competing-owner.mjs');
  // Export runs after the remote helper's initial marker check and before its
  // marker create. Simulate a delayed previous local owner arriving in that gap.
  await fs.writeFile(raceExporter,`import fs from 'node:fs';import {exportProtected} from ${JSON.stringify(new URL('../scripts/seo/export-protected.mjs',import.meta.url).href)};const data=exportProtected(${JSON.stringify(f.stateRoot)});fs.writeFileSync(${JSON.stringify(marker)},${JSON.stringify(competing)},{flag:'wx',mode:0o600});process.stdout.write(JSON.stringify(data)+'\\n');`);
  await fs.writeFile(f.configFile,JSON.stringify({...f.config,exportScript:raceExporter}));
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('must not overwrite competing marker')),/acquisition failed/);
  assert.equal(await fs.readFile(marker,'utf8'),competing);
  await assert.rejects(withPublicationLock(seoRoot(),async()=>assert.fail('must remain fenced')),/in-flight marker/);
});
