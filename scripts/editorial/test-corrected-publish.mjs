import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execute,bundleHash,productRow,sha,articleFields,normalizeTimestamps} from './publish.mjs';
import {privateCorrectionJournal} from './corrected-publisher.mjs';
import {adviceEvidence,TEMPLATE_FILES} from './template-context.mjs';
import {withPublicationLock} from '../seo/article-guard.mjs';

function harness(t,{count=2}={}) {
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'corrected-test-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const old=Array.from({length:count},(_,i)=>({id:'p'+i,name:'Tent',categoryId:'tent',specs:{weight:'wrong'},imageUrl:'https://images.example/a.png',
  affiliateUrl:'https://item.rakuten.co.jp/a/b/',amazonUrl:'',updatedAt:'2026-09-01T00:00:00+09:00'}));
 const next=old.map(p=>({...p,specs:{weight:'350g'},updatedAt:'2026-11-08T12:00:00+09:00'}));
 const ctx={kind:'catalog_correction',baseProducts:old,candidateProducts:next,changeSummary:'仕様訂正',
  productPatches:old.map((p,i)=>({id:p.id,baseHash:bundleHash(p),candidateHash:bundleHash(next[i]),fields:{specs:next[i].specs,updatedAt:next[i].updatedAt}}))};
 const bundle={article:{id:'editorial-new',slug:'new-tent',title:'Tent guide',categoryId:'tent',content:'広告 本文',excerpt:'Guide',
   productIds:next.map(p=>p.id),status:'draft',publishedAt:null,createdAt:'2026-11-08T12:00:00+09:00',updatedAt:'2026-11-08T12:00:00+09:00'},
  products:next,catalogCorrectionContext:ctx,images:next.map(p=>({productId:p.id,url:p.imageUrl,verified:true,sha256:sha('image'),size:5}))};
 const input={action:'publish-corrected',bundle,revision:bundleHash(bundle)};
 input.approval={revision:input.revision,approverId:'OWNER',evidence:{requestId:'approved'}};
 const state={products:old.map(p=>({...productRow(p),xmin:'10'})),articles:[],writes:[],caches:[],events:[]};
 const db={
  getProducts:async ids=>structuredClone(state.products.filter(p=>ids.includes(p.id))),
  findArticles:async(id,slug)=>structuredClone(state.articles.filter(a=>a.id===id||a.slug===slug)),
  findProductArticles:async()=>{state.events.push('affected');return [{id:'old',slug:'old-tent',status:'published',category_id:'tent'},{id:'old2',slug:'old-other',status:'published',category_id:'other'}];},
  patchProductCAS:async(before,fields)=>{state.events.push('patch');const p=state.products.find(p=>p.id===before.id);if(p.xmin!==before.xmin)return [];
    state.writes.push(p.id);Object.assign(p,fields,{xmin:String(Number(p.xmin)+1)});return [structuredClone(p)];},
  insertDraft:async row=>{state.writes.push('draft');state.articles.push(structuredClone(row));},
  publishCAS:async(before,fields)=>{state.writes.push('publish');const a=state.articles.find(a=>a.id===before.id);Object.assign(a,fields);return [structuredClone(a)];}
 };
 const deps={db,journal:privateCorrectionJournal(path.join(root,'journal')),lock:(fn,options)=>withPublicationLock(path.join(root,'guard'),fn,options),
  verifyApproval:async()=>true,now:()=> '2026-11-08T12:01:00+09:00',
  imageDigest:async()=>{state.events.push('image');return {sha256:sha('image'),size:5,contentType:'image/png'};},
  revalidate:async(slug,category)=>state.caches.push([slug,category]),
  publicGet:async()=>`<h1>${bundle.article.title}</h1><div data-review-content-sha256="${sha(bundle.article.content)}">`+next.map(p=>`<img src="${p.imageUrl}"><a href="${p.affiliateUrl}">shop</a>`).join('')+'</div>'};
 return {input,state,deps,root};
}

test('approved corrections precede new draft, retain full fingerprint, invalidate every affected page',async t=>{
 const h=harness(t);const result=await execute(h.input,h.deps);
 assert.equal(result.verified,true);assert.equal(result.readback.fingerprint,h.input.revision);
 assert.deepEqual(h.state.writes,['p0','p1','draft','publish']);
 assert.ok(h.state.events.indexOf('affected')<h.state.events.indexOf('patch'));
 assert.ok(h.state.events.indexOf('image')<h.state.events.indexOf('patch'));
 for(const page of [['old-tent','tent'],['old-other','other'],['new-tent','tent']])assert.ok(h.state.caches.some(p=>JSON.stringify(p)===JSON.stringify(page)));
 assert.equal(h.state.articles[0].generation_meta.editorialRuntime.revision,h.input.revision);
 const journal=JSON.parse(fs.readFileSync(path.join(h.root,'journal',h.input.revision+'.json')));
 assert.equal(journal.status,'complete');assert.equal(journal.products.length,2);
});

test('legacy stage and publish refuse correction context with no effects',async t=>{
 for(const action of ['stage','publish']){const h=harness(t);await assert.rejects(execute({...h.input,action},h.deps),/correction/);
 assert.deepEqual(h.state.writes,[]);assert.equal(fs.existsSync(path.join(h.root,'journal')),false);}
});

test('unsigned, wrong revision or untrusted owner approval cannot write',async t=>{
 for(const mode of ['absent','wrong','unsigned','owner']){const h=harness(t);
 if(mode==='absent')h.input.approval=null;
 if(mode==='wrong')h.input.approval.revision='0'.repeat(64);
 if(mode==='unsigned')delete h.deps.verifyApproval;
 if(mode==='owner')h.deps.verifyApproval=async()=>false;
 await assert.rejects(execute(h.input,h.deps),/approval/);assert.deepEqual(h.state.writes,[]);}
});

test('stale baselines, missing xmin, existing article identity and affected overflow refuse before writes',async t=>{
 for(const mode of ['baseline','xmin','id','slug','overflow','image']){const h=harness(t);
 if(mode==='baseline')h.state.products[1].description='concurrent';
 if(mode==='xmin')delete h.state.products[1].xmin;
 if(mode==='id')h.state.articles=[{id:h.input.bundle.article.id,slug:'elsewhere',status:'draft'}];
 if(mode==='slug')h.state.articles=[{id:'other',slug:h.input.bundle.article.slug,status:'published'}];
 if(mode==='overflow')h.deps.db.findProductArticles=async()=>Array.from({length:501},()=>({slug:'old',category_id:'tent',status:'published'}));
 if(mode==='image')h.deps.imageDigest=async()=>({sha256:'0'.repeat(64),size:5,contentType:'image/png'});
 await assert.rejects(execute(h.input,h.deps));assert.deepEqual(h.state.writes,[]);}
});

test('tampered patches, category, hash, snapshot or selected products cannot write even with new fingerprint',async t=>{
 for(const mode of ['patch','category','hash','snapshot','products','timestamp','source']){const h=harness(t),c=h.input.bundle.catalogCorrectionContext;
 if(mode==='patch')c.productPatches[0].fields.name='unbound';
 if(mode==='category')c.candidateProducts[0].categoryId='other';
 if(mode==='hash')c.productPatches[0].baseHash='0'.repeat(64);
 if(mode==='snapshot')delete c.candidateProducts[0].name;
 if(mode==='products')h.input.bundle.products=structuredClone(c.baseProducts);
 if(mode==='timestamp')c.candidateProducts[0].updatedAt='2026-11-08T12:00:00';
 if(mode==='source')c.source='invented';
 h.input.revision=bundleHash(h.input.bundle);h.input.approval.revision=h.input.revision;
 await assert.rejects(execute(h.input,h.deps));assert.deepEqual(h.state.writes,[]);}
});

test('partial second CAS fences rerun and records attempted and confirmed products durably',async t=>{
 const h=harness(t);const patch=h.deps.db.patchProductCAS;
 h.deps.db.patchProductCAS=async(before,fields)=>before.id==='p1'?[]:patch(before,fields);
 await assert.rejects(execute(h.input,h.deps),/reconcil/);
 assert.deepEqual(h.state.writes,['p0']);
 const journal=JSON.parse(fs.readFileSync(path.join(h.root,'journal',h.input.revision+'.json')));
 assert.equal(journal.status,'requires_reconciliation');assert.equal(journal.products[0].verified,true);assert.equal(journal.products[1].verified,false);
 await assert.rejects(execute(h.input,h.deps),/in-flight|reconcil/);assert.deepEqual(h.state.writes,['p0']);
 assert.ok(h.state.caches.some(([slug])=>slug==='old-tent'));
});

test('same-timestamp concurrent edit is fenced by fresh per-product xmin',async t=>{
 const h=harness(t),patch=h.deps.db.patchProductCAS;
 h.deps.db.patchProductCAS=async(before,fields)=>{h.state.products[0].xmin='11';h.state.products[0].specs={weight:'concurrent'};return patch(before,fields);};
 await assert.rejects(execute(h.input,h.deps),/reconcil/);assert.deepEqual(h.state.writes,[]);assert.equal(h.state.products[0].specs.weight,'concurrent');
});

test('readback drift stops before next patch; stale HTML and failed cache never report success',async t=>{
 for(const mode of ['readback','html','cache']){const h=harness(t),patch=h.deps.db.patchProductCAS;
 if(mode==='readback')h.deps.db.patchProductCAS=async(...args)=>{const result=await patch(...args);h.state.products[0].specs={weight:'drift'};return result;};
 if(mode==='html')h.deps.publicGet=async()=>'<h1>old</h1>';
 if(mode==='cache')h.deps.revalidate=async()=>{throw Error('cache unavailable');};
 await assert.rejects(execute(h.input,h.deps),/reconcil/);
 if(mode==='readback')assert.deepEqual(h.state.writes,['p0']);
 assert.equal(JSON.parse(fs.readFileSync(path.join(h.root,'journal',h.input.revision+'.json'))).status,'requires_reconciliation');}
});

test('production verifier refuses missing controlled owner/root before spawning any helper',async()=>{
 const {productionApprovalVerifier}=await import('./corrected-publisher.mjs');
 for(const env of [{},{CAMP_EDITORIAL_STATE_ROOT:'/tmp/private-only'},{CAMP_EDITORIAL_OWNER_ID:'OWNER'}])
  assert.equal(await productionApprovalVerifier(env)({action:'publish-corrected'}),false);
});

test('private journal fences another revision after global marker clearance and rejects unsafe directories',async t=>{
 const h=harness(t);const patch=h.deps.db.patchProductCAS;
 h.deps.db.patchProductCAS=async(before,fields)=>before.id==='p1'?[]:patch(before,fields);
 await assert.rejects(execute(h.input,h.deps),/reconcil/);
 assert.throws(()=>h.deps.journal.assertClear('f'.repeat(64)),/reconcil/);
 const unsafe=path.join(h.root,'unsafe');fs.mkdirSync(unsafe,{mode:0o755});
 assert.throws(()=>privateCorrectionJournal(unsafe).assertClear('f'.repeat(64)),/private/);
 const link=path.join(h.root,'link');fs.symlinkSync(path.join(h.root,'journal'),link);
 assert.throws(()=>privateCorrectionJournal(link).assertClear('f'.repeat(64)),/private/);
});

test('production fixed helper verifies actual private ledger, rejects forged approval, and preserves raw Python float hashes',async t=>{
 const {productionApprovalVerifier}=await import('./corrected-publisher.mjs');
 const {spawnSync}=await import('node:child_process');
 const h=harness(t),root=fs.realpathSync(h.root);
 const make=spawnSync('python3',['-c',`
import hashlib,json,os,sqlite3,sys
from pathlib import Path
v=json.load(sys.stdin)
b=v['bundle']; c=b['catalogCorrectionContext']
f=lambda x:hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
for old,new,patch in zip(c['baseProducts'],c['candidateProducts'],c['productPatches']):
 old['price']=new['price']=100.0
 patch['baseHash']=f(old);patch['candidateHash']=f(new)
b['products']=c['candidateProducts'];v['revision']=f(b)
approval=dict(revision=v['revision'],user_id='OWNER',request_id='actual-owner',at='2026-11-08T12:00:00+09:00',source='codex')
v['approval']=dict(revision=v['revision'],approverId='OWNER',evidence=dict(requestId=approval['request_id'],approvedAt=approval['at'],source='codex'))
j=dict(id=b['article']['id'],kind='article',stage='approved',publication=None,revision=v['revision'],bundle=b,
 theme=dict(categoryId='tent',productIds=b['article']['productIds']),catalogCorrectionContext=c,approval=approval,
 review=dict(score=8.5,passed=True,fingerprint=v['revision'],evidence={k:True for k in ['facts','images','affiliate','medical','render']},polish=dict(model='gemini-3.8-flash',validated=True)),
 astraReview=dict(passed=True,issues=[],reviewedBy='Astra',fingerprint=v['revision'],evidence=dict(summary='independent review')))
p=Path(sys.argv[1])/'ledger.sqlite3'
with sqlite3.connect(p) as db:
 db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT)')
 db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY,data TEXT)')
 db.execute('CREATE TABLE effects (job_id TEXT,kind TEXT,status TEXT)')
 db.execute('INSERT INTO meta VALUES (?,?)',('owner_id','OWNER'))
 db.execute('INSERT INTO jobs VALUES (?,?)',(j['id'],json.dumps(j,ensure_ascii=False)))
 db.execute('INSERT INTO effects VALUES (?,?,?)',(j['id'],'publish','in_flight'))
os.chmod(p,0o600)
print(json.dumps(v,ensure_ascii=False))
`,root],{input:JSON.stringify(h.input),encoding:'utf8'});
 assert.equal(make.status,0,make.stderr);
 const input=JSON.parse(make.stdout),verify=productionApprovalVerifier({CAMP_EDITORIAL_STATE_ROOT:root,CAMP_EDITORIAL_OWNER_ID:'OWNER'});
 const db=path.join(root,'ledger.sqlite3'),before=fs.readFileSync(db);
 assert.equal(await verify(input,{rawRequest:make.stdout}),true);
 // JSON.parse/stringify loses Python's 100.0 fingerprint; the received raw bytes are required.
 assert.equal(await verify(input),false);
 const forged=structuredClone(input);forged.approval.approverId='FORGED';
 assert.equal(await verify(forged),false);
 assert.deepEqual(fs.readFileSync(db),before);
 h.input=input;h.deps.rawRequest=make.stdout;h.deps.verifyApproval=verify;
 for(const p of h.state.products)p.price=100;
 assert.equal((await execute(h.input,h.deps)).verified,true);
});

test('Yahoo correction may only remove an existing optional URL, never replace or null it',async t=>{
 for(const value of ['',null,'https://store.shopping.yahoo.co.jp/shop/new.html']){
  const h=harness(t,{count:1}),c=h.input.bundle.catalogCorrectionContext;
  c.baseProducts[0].yahooUrl='https://shopping.yahoo.co.jp/search?p=tent';
  c.candidateProducts[0].yahooUrl=value;
  c.productPatches[0].fields.yahooUrl=value;
  c.productPatches[0].baseHash=bundleHash(c.baseProducts[0]);
  c.productPatches[0].candidateHash=bundleHash(c.candidateProducts[0]);
  h.state.products=c.baseProducts.map(p=>({...productRow(p),xmin:'10'}));
  h.input.revision=bundleHash(h.input.bundle);h.input.approval.revision=h.input.revision;
  if(value===''){
   assert.equal((await execute(h.input,h.deps)).verified,true);
   assert.equal(h.state.products[0].yahoo_url,'');
  }else{
   await assert.rejects(execute(h.input,h.deps),/Yahoo/);assert.deepEqual(h.state.writes,[]);
  }
 }
});

test('already applied exact candidate skips every product patch; third field or timestamp state blocks all writes',async t=>{
 for(const mode of ['desired','field','timestamp']){
  const h=harness(t),c=h.input.bundle.catalogCorrectionContext;
  h.state.products=c.candidateProducts.map(p=>({...productRow(p),xmin:'20'}));
  if(mode==='field')h.state.products[1].description='third state';
  if(mode==='timestamp')h.state.products[1].updated_at='2026-11-08T12:00:01+09:00';
  if(mode==='desired'){
   assert.equal((await execute(h.input,h.deps)).verified,true);
   assert.deepEqual(h.state.writes,['draft','publish']);
  }else{await assert.rejects(execute(h.input,h.deps));assert.deepEqual(h.state.writes,[]);}
 }
});

test('candidate appearing at fresh pre-CAS read is skipped, but own unresolved journal still fences it',async t=>{
 const h=harness(t),c=h.input.bundle.catalogCorrectionContext,get=h.deps.db.getProducts;let reads=0;
 h.deps.db.getProducts=async ids=>{
  if(++reads===2)h.state.products=c.candidateProducts.map(p=>({...productRow(p),xmin:'20'}));
  return get(ids);
 };
 assert.equal((await execute(h.input,h.deps)).verified,true);
 assert.deepEqual(h.state.writes,['draft','publish']);
 const k=harness(t);k.state.products=k.input.bundle.products.map(p=>({...productRow(p),xmin:'20'}));
 k.deps.journal.start({schemaVersion:1,revision:k.input.revision,status:'requires_reconciliation'});
 let baselineReads=0;const getBlocked=k.deps.db.getProducts;k.deps.db.getProducts=async ids=>{baselineReads++;return getBlocked(ids);};
 await assert.rejects(execute(k.input,k.deps),/reconcil/);assert.deepEqual(k.state.writes,[]);assert.equal(baselineReads,0);
});


test('either independent article approval order applies shared desired product exactly once',async t=>{
 for(const order of ['revision-first','new-first']){
  const h=harness(t,{count:1}),c=h.input.bundle.catalogCorrectionContext;
  const advice='<aside aria-label="医師からのアドバイス"><h3>既存の注意</h3><p>既存の安全情報。</p><p>※一般的な医学情報で、個別の診療ではありません。</p></aside>';
  const evidence=adviceEvidence(advice),files=Object.fromEntries(TEMPLATE_FILES.map(f=>[f,'a'.repeat(64)]));
  const base={id:'article-005',slug:'single-burner-ranking',title:'Original',content:'Original body',excerpt:'Original',categoryId:'tent',
   productIds:['p0'],status:'published',createdAt:'2026-01-01T00:00:00+09:00',updatedAt:'2026-09-01T00:00:00+09:00',
   publishedAt:'2026-02-01T00:00:00+09:00',author:'ギア男',faqs:[],tags:[]};
  const context={kind:'article_revision',baseArticle:base,baseHash:bundleHash(base),changeSummary:'Correct specs',editorialCorrectionInstructions:'Correct specs',
   verifiedAuthorFacts:[],targetProductIds:['p0'],productRemovalReasons:{},baseProducts:c.baseProducts,candidateProducts:c.candidateProducts,productPatches:c.productPatches};
  const bundle={article:{...base,title:'Revised',content:'Revised body'},products:c.candidateProducts,images:h.input.bundle.images,revisionContext:context,
   inheritedPresentationContext:{schemaVersion:1,kind:'unchanged_medical_advice',slug:base.slug,html:advice,domSha256:evidence.domSha256,
    renderedText:evidence.text,templateFiles:files,clinicalReverified:false,unchanged:true}};
  const revision={action:'publish-revision',bundle,revision:bundleHash(bundle)};
  revision.approval={revision:revision.revision,approverId:'OWNER',evidence:{requestId:'independent-revision-owner-approval'}};
  const original=normalizeTimestamps(Object.fromEntries(Object.entries(articleFields).map(([k,v])=>[v,base[k]??null])));
  h.state.articles.push(structuredClone(original));
  h.deps.currentTemplateHashes=async()=>files;
  h.deps.db.patchPublishedCAS=async(before,patch)=>{
   h.state.writes.push('revision');const article=h.state.articles.find(a=>a.id===before.id);Object.assign(article,patch);return [structuredClone(article)];
  };
  const get=h.deps.publicGet;
  h.deps.publicGet=async url=>url.endsWith('/'+base.slug)
   ?`<main><article><h1>${bundle.article.title}</h1><div data-review-content-sha256="${sha(bundle.article.content)}"><div id="article-reading-content">`+
    bundle.products.map(p=>`<img src="${p.imageUrl}"><a href="${p.affiliateUrl}">shop</a>`).join('')+advice+'</div></div></article></main>'
   :get(url);
  const first=order==='revision-first'?revision:h.input,second=order==='revision-first'?h.input:revision;
  assert.equal((await execute(first,h.deps)).verified,true);
  if(order==='new-first')assert.deepEqual(h.state.articles.find(a=>a.id===base.id),original);
  const writes=h.state.writes.filter(w=>w==='p0').length;
  assert.equal(writes,1);
  assert.equal((await execute(second,h.deps)).verified,true);
  assert.equal(h.state.writes.filter(w=>w==='p0').length,1);
  assert.equal(h.state.articles.find(a=>a.id===base.id).title,'Revised');
  assert.equal(h.state.articles.find(a=>a.id==='editorial-new').status,'published');
 }
});

test('mixed base/candidate rows patch only baseline; third state at pre-CAS read stops before mutation',async t=>{
 for(const mode of ['mixed','third']){
  const h=harness(t),c=h.input.bundle.catalogCorrectionContext;
  if(mode==='mixed')h.state.products[1]={...productRow(c.candidateProducts[1]),xmin:'20'};
  else{const get=h.deps.db.getProducts;let reads=0;h.deps.db.getProducts=async ids=>{if(++reads===2)h.state.products[0].updated_at='2026-11-08T12:00:01+09:00';return get(ids);};}
  if(mode==='mixed'){
   assert.equal((await execute(h.input,h.deps)).verified,true);assert.deepEqual(h.state.writes,['p0','draft','publish']);
  }else{await assert.rejects(execute(h.input,h.deps),/reconcil/);assert.deepEqual(h.state.writes,[]);}
 }
});
