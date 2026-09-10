#!/usr/bin/env node
// Registers this task's usage and refreshes preceding registered tasks, including
// their final response tokens on the next run. Only matching task trees are read.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {main as accountUsage} from './usage.mjs';
import {seoRoot,atomicJson} from './article-guard.mjs';

export async function findTaskSessions(threadId,sessionsRoot) {
  if(!/^[a-f0-9-]{36}$/.test(threadId||''))throw new Error('Explicit valid Codex task ID required');
  const names=await fs.readdir(sessionsRoot,{recursive:true});
  const own=names.find(name=>name.endsWith(`${threadId}.jsonl`));
  if(!own)throw new Error('Codex task log not found');
  const parentFile=path.join(sessionsRoot,own);
  const dayDir=path.dirname(parentFile);
  const files=(await fs.readdir(dayDir)).filter(name=>name.endsWith('.jsonl')).map(name=>path.join(dayDir,name));
  const metadata=[];
  for(const file of files) {
    const handle=await fs.open(file,'r');
    try {
      const buffer=Buffer.alloc(65536);const {bytesRead}=await handle.read(buffer,0,buffer.length,0);
      const line=buffer.subarray(0,bytesRead).toString().split('\n')[0];
      const record=JSON.parse(line);metadata.push({file,payload:record.payload});
    }finally{await handle.close();}
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
  const kind=flag('--kind')||'operations';
  if(!['implementation','operations'].includes(kind))throw new Error('Invalid cost kind');
  const registryFile=path.join(root,'usage-sessions.json');
  await fs.mkdir(root,{recursive:true});
  const lock=registryFile+'.lock';await fs.mkdir(lock);
  try {
    let registry={schemaVersion:1,tasks:[]};
    try{registry=JSON.parse(await fs.readFile(registryFile,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
    const old=registry.tasks.find(item=>item.threadId===threadId);
    if(old && old.kind!==kind)throw new Error('Task already registered with another accounting kind');
    if(!old)registry.tasks.push({threadId,kind,...(flag('--since')?{since:flag('--since')}:{})});
    const reports=[];
    for(const task of registry.tasks) {
      const files=await findTaskSessions(task.threadId,path.join(os.homedir(),'.codex/sessions'));
      const usageArgs=['--id',task.threadId,'--kind',task.kind,'--root',root,'--write',...files.flatMap(file=>['--session',file])];
      if(task.since)usageArgs.push('--since',task.since);
      const report=await accountUsage(usageArgs);
      reports.push({id:task.threadId,kind:task.kind,credits:report.run.codexCreditsEstimate,through:report.run.finishedAt});
    }
    atomicJson(registryFile,registry);
    console.log(JSON.stringify({reports,note:'Current running task is a partial total. Next execution refreshes final-response usage. Standard-rate estimates, not actual billed money; child tasks that start on another day need explicit registration.'},null,2));
    return reports;
  }finally{await fs.rm(lock,{recursive:true});}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(e.message);process.exitCode=1;});
