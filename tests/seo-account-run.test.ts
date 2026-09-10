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
