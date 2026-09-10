#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {atomicJson,articleHash,seoRoot,withPublicationLock} from './article-guard.mjs';

export function toMirror(row) {
  const mapped={...row};
  for(const [remote,local] of Object.entries({category_id:'categoryId',product_ids:'productIds',meta_description:'metaDescription',updated_at:'updatedAt'})){
    mapped[local]=mapped[remote];delete mapped[remote];
  }
  return mapped;
}
export async function main(args=process.argv.slice(2)) {
  const flag=name=>{const i=args.indexOf(name);return i<0?undefined:args[i+1];};
  const id=flag('--article');if(!/^[a-zA-Z0-9_-]+$/.test(id||''))throw new Error('--article ID required');
  const root=path.resolve(flag('--root')||seoRoot());
  if(flag('--env-file'))process.loadEnvFile(flag('--env-file'));
  const {createClient}=await import('@supabase/supabase-js');
  const db=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_SERVICE_ROLE_KEY);
  return withPublicationLock(root,async()=>{
    const {data,error}=await db.from('articles').select('*').eq('id',id).single();
    if(error)throw new Error(`Baseline fetch failed: ${error.message}`);
    if(data.status!=='published')throw new Error('Only existing published articles are in scope');
    const file=path.join(root,'mirror/articles.json');
    const rows=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):[];
    atomicJson(path.join(root,'research',`${id}-baseline.json`),data);
    atomicJson(file,[...rows.filter(row=>row.id!==id),toMirror(data)]);
    const result={id,slug:data.slug,updated_at:data.updated_at,hash:articleHash(data),mirror:file};
    console.log(JSON.stringify(result,null,2));return result;
  });
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(e.message);process.exitCode=1;});
