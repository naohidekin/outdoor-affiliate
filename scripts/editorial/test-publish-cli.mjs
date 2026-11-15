import test from 'node:test';
import {loadWisePolicy} from '../../src/lib/wise-contract.mjs';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
for(const action of ['stage-revision','publish-revision','publish-corrected']) {
 test('CLI dynamically imports '+action+' without unresolved top-level await',()=>{
  const r=spawnSync(process.execPath,[fileURLToPath(new URL('./publish.mjs',import.meta.url))],{
   input:JSON.stringify({action,bundle:{wisePolicy:loadWisePolicy().id},revision:'invalid',
    review:{wisePolicy:loadWisePolicy().id,passed:true,fingerprint:'invalid',wiseScores:{w:3,i:3,s:3,e:3,ai:3,sense:3}}}),encoding:'utf8',timeout:10000,
   env:{PATH:process.env.PATH,HOME:process.env.HOME,SEO_GUARD_CONFIG:'/nonexistent-test-guard.json',SUPABASE_URL:'https://invalid.example',SUPABASE_SERVICE_ROLE_KEY:'test-only',REVALIDATE_SECRET:'test-only'}});
  assert.equal(r.status,1);
  assert.equal(JSON.parse(r.stdout).verified,false);
  assert.equal(JSON.parse(r.stdout).error,'publication_result_unknown');
 });
}

test('revision affected articles use JSONB containment alternatives, not array overlap',async()=>{
 const {revisionDependencies}=await import('./revision-publisher.mjs');
 const old=globalThis.fetch;
 try {
  globalThis.fetch=async url=>{
   const q=new URL(url).searchParams;
   assert.equal(q.get('or'),'(product_ids.cs.["p1"],product_ids.cs.["p2"])');
   assert.equal(q.has('product_ids'),false);
   assert.equal(q.get('limit'),'501');
   return {ok:true,json:async()=>[]};
  };
  await revisionDependencies({SUPABASE_URL:'https://invalid.example',SUPABASE_SERVICE_ROLE_KEY:'test-only'}).db.findProductArticles(['p1','p2']);
 }finally{globalThis.fetch=old}
});

test('safe diagnostics discard secret-bearing text and unknown fields',async()=>{
 const {safeDiagnostic}=await import('./publisher-diagnostics.mjs');
 assert.deepEqual(safeDiagnostic({phase:'public_readback',operation:'db_read_articles',httpStatus:404,dbCode:'42883',message:'secret',url:'secret',headers:'secret'}),{phase:'public_readback',operation:'db_read_articles',httpStatus:404,dbCode:'42883'});
 assert.deepEqual(safeDiagnostic({phase:'secret',operation:'secret',httpStatus:999,dbCode:'secret-value',exitCode:'13'}),{});
});
test('database read errors retain only operation, status and SQLSTATE',async()=>{
 const {revisionDependencies}=await import('./revision-publisher.mjs');const old=globalThis.fetch;
 try{
  globalThis.fetch=async()=>({ok:false,status:404,json:async()=>({code:'42883',message:'secret',details:'secret'})});
  await assert.rejects(revisionDependencies({SUPABASE_URL:'https://invalid.example',SUPABASE_SERVICE_ROLE_KEY:'test'}).db.findProductArticles(['p']),error=>{
   assert.deepEqual(error.diagnostic,{operation:'db_read_articles',httpStatus:404,dbCode:'42883'});
   assert.ok(!JSON.stringify(error).includes('secret'));return true;
  });
 }finally{globalThis.fetch=old}
});

for (const action of ['stage','publish','stage-revision','publish-revision','publish-corrected']) {
 test('CLI holds legacy missing policy before any publication effect: '+action,()=>{
  const r=spawnSync(process.execPath,[fileURLToPath(new URL('./publish.mjs',import.meta.url))],{
   input:JSON.stringify({action,bundle:{},revision:'invalid'}),encoding:'utf8',timeout:10000,
   env:{PATH:process.env.PATH,HOME:process.env.HOME,SEO_GUARD_CONFIG:'/nonexistent-test-guard.json',SUPABASE_URL:'https://invalid.example',SUPABASE_SERVICE_ROLE_KEY:'test-only',REVALIDATE_SECRET:'test-only'}});
  assert.equal(r.status,1);
  const result=JSON.parse(r.stdout);
  assert.equal(result.verified,false); assert.equal(result.error,'publisher_input_or_environment_invalid');
  assert.equal(result.diagnostic.phase,'input_environment');
 });
}
