import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {findTaskSessions} from '../scripts/seo/account-run.mjs';
import {toMirror} from '../scripts/seo/snapshot.mjs';
import {articleHash} from '../scripts/seo/article-guard.mjs';
test('usage discovery includes only selected task and descendants',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'seo-tree-'));
 try {
  const parent='11111111-1111-1111-1111-111111111111';const child='22222222-2222-2222-2222-222222222222';
  for(const [id,parentId] of [[parent,null],[child,parent],['33333333-3333-3333-3333-333333333333',child],['44444444-4444-4444-4444-444444444444',null]])await fs.writeFile(path.join(root,`rollout-${id}.jsonl`),JSON.stringify({type:'session_meta',payload:{id,source:parentId?{subagent:{thread_spawn:{parent_thread_id:parentId}}}:'vscode'}})+'\n');
  const files=await findTaskSessions(parent,root);assert.equal(files.length,3);assert.equal(files.some((f:string)=>f.includes('44444444')),false);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});
test('private mirror removes DB aliases so metadata edits and retries retain correct hashes',()=>{
 const row={id:'a',content:'body',meta_description:'old',category_id:'tent',product_ids:[],updated_at:'2026-09-11T00:00:00Z'};
 const mirror=toMirror(row);assert.equal(articleHash(mirror),articleHash(row));
 assert.equal(Object.hasOwn(mirror,'meta_description'),false);
 assert.equal(articleHash({...mirror,metaDescription:'new'}),articleHash({...row,meta_description:'new'}));
});

test('session discovery follows descendants across midnight and ignores malformed unrelated lines',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'seo-tree-days-'));
 try {
  const parent='11111111-1111-1111-1111-111111111111';const child='22222222-2222-2222-2222-222222222222';const grandchild='33333333-3333-3333-3333-333333333333';
  for(const [day,id,parentId] of [['11',parent,null],['12',child,parent],['13',grandchild,child]]){
    const dir=path.join(root,'2026','09',day!);await fs.mkdir(dir,{recursive:true});
    await fs.writeFile(path.join(dir,`rollout-${id}.jsonl`),'malformed unrelated record\n'+JSON.stringify({type:'session_meta',payload:{id,source:parentId?{subagent:{thread_spawn:{parent_thread_id:parentId}}}:'vscode'}})+'\n');
  }
  await fs.writeFile(path.join(root,'unrelated.jsonl'),'broken\nnull\n');
  const files=await findTaskSessions(parent,root);assert.equal(files.length,3);assert.ok(files.some(file=>file.includes('/13/')));
  await fs.writeFile(path.join(root,'2026','09','11',`rollout-${parent}.jsonl`),'broken\n');
  await assert.rejects(findTaskSessions(parent,root),/parent session metadata/);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('migration freezes existing historical run while new-host task is measured normally',async()=>{
 const {main}=await import('../scripts/seo/account-run.mjs');
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'seo-frozen-'));
 try{
  const old='11111111-1111-1111-1111-111111111111';const current='22222222-2222-2222-2222-222222222222';
  const sessions=path.join(root,'new-host-sessions');await fs.mkdir(sessions);
  const historical={id:old,kind:'implementation',codexCreditsEstimate:123.4,finishedAt:'2026-09-11T01:00:00Z',sourcePaths:['old-host-only.jsonl'],customEvidence:{keep:true}};
  await fs.writeFile(path.join(root,'usage.json'),JSON.stringify({schemaVersion:1,runs:[historical]}));
  await fs.writeFile(path.join(root,'usage-sessions.json'),JSON.stringify({schemaVersion:1,tasks:[{threadId:old,kind:'implementation',frozenOnMigration:true}]}));
  const records=[{type:'session_meta',payload:{id:current,source:'vscode'}},{type:'turn_context',payload:{model:'gpt-6-astra'}},{timestamp:'2026-09-12T00:00:00Z',type:'event_msg',payload:{type:'token_count',info:{total_token_usage:{input_tokens:100,cached_input_tokens:0,output_tokens:10}}}}];
  await fs.writeFile(path.join(sessions,`rollout-${current}.jsonl`),records.map(r=>JSON.stringify(r)).join('\n')+'\n');
  const reports=await main(['--thread',current,'--kind','operations','--root',root,'--sessions-root',sessions]);
  assert.equal(reports.length,2);assert.equal(reports[0].frozenOnMigration,true);
  const usage=JSON.parse(await fs.readFile(path.join(root,'usage.json'),'utf8'));
  assert.deepEqual(usage.runs.find((run:{id:string})=>run.id===old),historical);
  assert.equal(usage.runs.filter((run:{id:string})=>run.id===current).length,1);
  assert.ok(usage.runs.find((run:{id:string})=>run.id===current).codexCreditsEstimate>0);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('frozen migration task missing from usage fails before adding the new task or reading sessions',async()=>{
 const {main}=await import('../scripts/seo/account-run.mjs');
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'seo-frozen-missing-'));
 try{
  const old='11111111-1111-1111-1111-111111111111';const current='22222222-2222-2222-2222-222222222222';
  const registry=JSON.stringify({schemaVersion:1,tasks:[{threadId:old,kind:'implementation',frozenOnMigration:true}]});
  await fs.writeFile(path.join(root,'usage-sessions.json'),registry);
  await fs.writeFile(path.join(root,'usage.json'),JSON.stringify({schemaVersion:1,runs:[]}));
  await assert.rejects(main(['--thread',current,'--root',root,'--sessions-root',path.join(root,'absent')]),/existing usage run/);
  assert.equal(await fs.readFile(path.join(root,'usage-sessions.json'),'utf8'),registry);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});
