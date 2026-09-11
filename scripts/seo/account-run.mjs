#!/usr/bin/env node
// Refresh current-host task trees; migration-frozen runs remain historical data.
import fs from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {main as accountUsage} from './usage.mjs';
import {seoRoot,atomicJson} from './article-guard.mjs';
import {withProcessLock} from './process-lock.mjs';

async function sessionMetadata(file) {
  const stream = createReadStream(file, {encoding:'utf8'});
  const lines = createInterface({input:stream, crlfDelay:Infinity});
  try {
    for await (const line of lines) {
      let record;
      try { record = JSON.parse(line); } catch { continue; }
      if (record?.type === 'session_meta') return record.payload;
    }
    return null;
  } finally { lines.close(); stream.destroy(); }
}
export async function findTaskSessions(threadId,sessionsRoot) {
  if(!/^[a-f0-9-]{36}$/.test(threadId||''))throw new Error('Explicit valid Codex task ID required');
  const names=(await fs.readdir(sessionsRoot,{recursive:true})).filter(name=>name.endsWith('.jsonl')).sort();
  const own=names.find(name=>name.endsWith(`${threadId}.jsonl`));
  if(!own)throw new Error('Codex task log not found');
  const parentFile=path.join(sessionsRoot,own);
  const metadata=[];
  for(const name of names) {
    const file=path.join(sessionsRoot,name);
    const payload=await sessionMetadata(file);
    if(file===parentFile && payload?.id!==threadId)throw new Error('Required Codex parent session metadata is missing or invalid');
    if(payload?.id)metadata.push({file,payload});
  }
  const ids=new Set([threadId]),selected=new Set([parentFile]);
  for(let i=0;i<metadata.length;i++)for(const {file,payload} of metadata) {
    if(ids.has(payload?.source?.subagent?.thread_spawn?.parent_thread_id)){ids.add(payload.id);selected.add(file);}
  }
  return [...selected];
}
export async function main(args=process.argv.slice(2)) {
  const flag=name=>{const index=args.indexOf(name);return index<0?undefined:args[index+1];};
  const root=path.resolve(flag('--root')||seoRoot());
  const threadId=flag('--thread')||process.env.CODEX_THREAD_ID;
  if(!/^[a-f0-9-]{36}$/.test(threadId||''))throw new Error('Explicit valid Codex task ID required');
  const kind=flag('--kind')||'operations';
  if(!['implementation','operations'].includes(kind))throw new Error('Invalid cost kind');
  const registryFile=path.join(root,'usage-sessions.json');
  return withProcessLock(registryFile+'.flock',async()=>{
    let registry={schemaVersion:1,tasks:[]};
    try{registry=JSON.parse(await fs.readFile(registryFile,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
    const old=registry.tasks.find(item=>item.threadId===threadId);
    if(old && old.kind!==kind)throw new Error('Task already registered with another accounting kind');
    if(!old)registry.tasks.push({threadId,kind,...(flag('--since')?{since:flag('--since')}:{})});
    // Validate every frozen record before reading sessions or changing usage.
    // A migration flag can preserve measured history, never invent missing cost.
    const frozen=new Map();
    const frozenTasks=registry.tasks.filter(task=>task.frozenOnMigration===true);
    if(frozenTasks.length)await withProcessLock(path.join(root,'usage.json.flock'),async()=>{
      let usage;
      try{usage=JSON.parse(await fs.readFile(path.join(root,'usage.json'),'utf8'));}catch{throw new Error('Frozen migration usage ledger is missing or invalid');}
      for(const task of frozenTasks){
        const matches=(usage.runs||[]).filter(run=>run.id===task.threadId);
        if(matches.length!==1 || matches[0].kind!==task.kind)throw new Error('Frozen migration task requires exactly one existing usage run of the same kind');
        frozen.set(task.threadId,matches[0]);
      }
    });
    const reports=[];
    for(const task of registry.tasks) {
      let run=frozen.get(task.threadId);
      if(!run){
        const files=await findTaskSessions(task.threadId,flag('--sessions-root')||path.join(os.homedir(),'.codex/sessions'));
        const usageArgs=['--id',task.threadId,'--kind',task.kind,'--root',root,'--write',...files.flatMap(file=>['--session',file])];
        if(task.since)usageArgs.push('--since',task.since);
        run=(await accountUsage(usageArgs)).run;
      }
      reports.push({id:task.threadId,kind:task.kind,credits:run.codexCreditsEstimate,through:run.finishedAt,...(frozen.has(task.threadId)?{frozenOnMigration:true}:{})});
    }
    atomicJson(registryFile,registry);
    console.log(JSON.stringify({reports,note:'Current running task is a partial total. Next execution refreshes final-response usage. Migration-frozen tasks preserve their existing usage runs. Standard-rate estimates, not actual billed money.'},null,2));
    return reports;
  });
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(e.message);process.exitCode=1;});
