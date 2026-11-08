import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { bundleHash, productRow, execute } from './publish.mjs';
import {adviceEvidence,TEMPLATE_FILES} from './template-context.mjs';

function harness({ patched = true, count = 1 } = {}) {
  const adviceHtml='<aside aria-label="医師からのアドバイス"><h3>既存の注意</h3><p>既存の安全情報。</p><p>※一般的な医学情報で、個別の診療ではありません。</p></aside>';
  const observed=adviceEvidence(adviceHtml), files=Object.fromEntries(TEMPLATE_FILES.map(f=>[f,'a'.repeat(64)]));
  const ids = Array.from({length:count},(_,i)=>'p'+i);
  const baseArticle = {id:'article-024',slug:'firepit-beginner-guide',title:'旧記事',content:'旧本文',categoryId:'firepit',
    productIds:ids,status:'published',createdAt:'2026-01-01T00:00:00+09:00',publishedAt:'2026-02-01T00:00:00+09:00',
    updatedAt:'2026-09-01T00:00:00+09:00',excerpt:'旧要約',faqs:[],tags:[],generationMeta:{legacy:'keep'},author:'ギア男'};
  const baseProducts=ids.map(id=>({id,name:'SOTO ST-310',brand:'SOTO',categoryId:'firepit',specs:{weight:'wrong'},
    imageUrl:'https://images.example/item.png',affiliateUrl:'https://item.rakuten.co.jp/a/b/',amazonUrl:'',
    updatedAt:'2026-09-01T00:00:00+09:00'}));
  const candidateProducts=structuredClone(baseProducts);
  if(patched) for(const p of candidateProducts){p.specs={weight:'350g'};p.updatedAt='2026-11-08T12:00:00+09:00';}
  const productPatches=baseProducts.flatMap((p,i)=>{
    const next=candidateProducts[i];const fields=Object.fromEntries(Object.keys(next).filter(k=>JSON.stringify(next[k])!==JSON.stringify(p[k])).map(k=>[k,next[k]]));
    return Object.keys(fields).length?[{id:p.id,baseHash:bundleHash(p),candidateHash:bundleHash(next),fields}]:[];
  });
  const binding={kind:'article_revision',baseArticle,baseHash:bundleHash(baseArticle),changeSummary:'根拠を整理',
    editorialCorrectionInstructions:'未確認医療主張を削除',verifiedAuthorFacts:[],targetProductIds:ids,productRemovalReasons:{},baseProducts,candidateProducts,productPatches};
  const b={article:{...structuredClone(baseArticle),title:'改訂記事',content:'## 改訂本文\n広告'},products:candidateProducts,
    images:candidateProducts.map(p=>({productId:p.id,url:p.imageUrl,verified:true,sha256:createHash('sha256').update('image').digest('hex'),size:5})),revisionContext:binding,inheritedPresentationContext:{schemaVersion:1,kind:'unchanged_medical_advice',slug:baseArticle.slug,html:adviceHtml,
      domSha256:observed.domSha256,renderedText:observed.text,templateFiles:files,clinicalReverified:false,unchanged:true}};
  const fieldMap={id:'id',slug:'slug',title:'title',content:'content',categoryId:'category_id',productIds:'product_ids',status:'status',createdAt:'created_at',publishedAt:'published_at',updatedAt:'updated_at',excerpt:'excerpt',faqs:'faqs',tags:'tags',generationMeta:'generation_meta'};
  const state={adviceHtml,files,article:Object.fromEntries(Object.entries(fieldMap).map(([l,r])=>[r,structuredClone(baseArticle[l])])),products:baseProducts.map(p=>({...productRow(p),xmin:'10'})),writes:[],readbacks:0};
  const db={findProductArticles:async()=>[],findArticles:async()=>[structuredClone(state.article)],getProducts:async ids=>structuredClone(state.products.filter(p=>ids.includes(p.id))),
    insertDraft:async()=>{throw Error('no draft write');},
    patchProductCAS:async(before,patch)=>{state.writes.push('product:'+before.id);Object.assign(state.products.find(p=>p.id===before.id),patch);return [structuredClone(state.products.find(p=>p.id===before.id))];},
    patchPublishedCAS:async(before,patch)=>{state.writes.push('article');Object.assign(state.article,patch);return [structuredClone(state.article)];}};
  const deps={db,currentTemplateHashes:async()=>state.files,lock:async fn=>fn(),now:()=> '2026-11-08T12:01:00+09:00',revalidate:async()=>{},
    imageDigest:async()=>({sha256:b.images[0].sha256,size:5,contentType:'image/png'}),
    publicGet:async()=>`<main><article data-review-content-sha256="${createHash('sha256').update(b.article.content).digest('hex')}"><h1>${b.article.title}</h1><div id="article-reading-content">`+candidateProducts.map(p=>`<img src="${p.imageUrl}"><a href="${p.affiliateUrl}">購入</a>`).join('')+state.adviceHtml+'</div></article></main>'};
  const input={action:'publish-revision',bundle:b,revision:bundleHash(b)};
  input.approval={revision:input.revision,approverId:'U',evidence:{requestId:'exact-owner'}};
  return {input,state,deps};
}

test('revision private staging reads baselines but never mutates public rows',async()=>{
 const h=harness();const result=await execute({...h.input,action:'stage-revision',approval:null},h.deps);
 assert.equal(result.status,'private_revision');assert.deepEqual(h.state.writes,[]);
});
test('exact approval updates corrected shared products before article, preserves published identity and dates',async()=>{
 const h=harness();const before=structuredClone(h.state.article);const result=await execute(h.input,h.deps);
 assert.equal(result.verified,true);assert.deepEqual(h.state.writes,['product:p0','article']);
 for(const k of ['id','slug','status','created_at','published_at'])assert.deepEqual(h.state.article[k],before[k]);
 assert.equal(h.state.article.generation_meta.legacy,'keep');assert.equal(h.state.products[0].specs.weight,'350g');
 assert.equal(result.readback.fingerprint,h.input.revision);
});
test('missing/wrong approval and legacy action cannot publish revisions',async()=>{
 for(const mode of ['missing','wrong','legacy']){const h=harness();if(mode==='missing')h.input.approval=null;
 if(mode==='wrong')h.input.approval.revision='0'.repeat(64);if(mode==='legacy')h.input.action='publish';
 await assert.rejects(execute(h.input,h.deps));assert.deepEqual(h.state.writes,[]);}
});
test('stale any product or article baseline rejects before first write',async()=>{
 for(const mode of ['product','article']){const h=harness({count:2});if(mode==='product')h.state.products[1].description='drift';else h.state.article.content='remote drift';
 await assert.rejects(execute(h.input,h.deps));assert.deepEqual(h.state.writes,[]);}
});
test('nonallowlisted target, product identity/category, protected dates, or product substitutions fail',async()=>{
 for(const mutate of [b=>b.article.id='article-other',b=>b.products[0].categoryId='other',b=>b.article.publishedAt='2026-11-08T00:00:00+09:00',b=>b.products[0].name='unapproved']){
 const h=harness();mutate(h.input.bundle);h.input.revision=bundleHash(h.input.bundle);h.input.approval.revision=h.input.revision;
 await assert.rejects(execute(h.input,h.deps));assert.deepEqual(h.state.writes,[]);}
});
test('partial or unverified product mutation stops before article CAS',async()=>{
 for(const mode of ['unknown','readback','second-stale']){const h=harness({count:2});const patch=h.deps.db.patchProductCAS;
 h.deps.db.patchProductCAS=async(before,fields)=>{if(mode==='unknown')throw Error('unknown');if(mode==='second-stale'&&before.id==='p1')return [];
 const result=await patch(before,fields);if(mode==='readback')h.state.products[0].specs={weight:'drift'};return result;};
 await assert.rejects(execute(h.input,h.deps),/reconciliation/);assert.ok(!h.state.writes.includes('article'));}
});
test('article CAS miss, readback drift and stale public HTML never report success',async()=>{
 for(const mode of ['cas','db','html']){const h=harness({patched:false});const patch=h.deps.db.patchPublishedCAS;
 if(mode==='cas')h.deps.db.patchPublishedCAS=async()=>[];
 if(mode==='db')h.deps.db.patchPublishedCAS=async(...args)=>{const result=await patch(...args);h.state.article.title='drift';return result;};
 if(mode==='html')h.deps.publicGet=async()=>'<h1>stale</h1>';
 await assert.rejects(execute(h.input,h.deps),/reconciliation/);}
});
test('unchanged products are not patched; 13 legacy bound products accepted',async()=>{
 const h=harness({patched:false,count:13});const result=await execute(h.input,h.deps);
 assert.equal(result.verified,true);assert.deepEqual(h.state.writes,['article']);
});

test('production revision transport uses conditional PATCH with unchanged identity and original dates',async t=>{
 const {revisionDependencies}=await import('./revision-publisher.mjs');
 const calls=[];t.mock.method(globalThis,'fetch',async(url,options)=>{calls.push({url:new URL(url),options});return Response.json([]);});
 const deps=revisionDependencies({SUPABASE_URL:'https://db.example',SUPABASE_SERVICE_ROLE_KEY:'test-only'});
 await deps.db.patchProductCAS({id:'p0',xmin:'9798',updated_at:'2026-01-01T00:00:00Z',category_id:'tent'},{specs:{weight:'350g'},updated_at:'2026-11-08T12:00:00+09:00'});
 await deps.db.patchPublishedCAS({id:'article-024',xmin:'9855',slug:'firepit-beginner-guide',updated_at:'2026-01-01T00:00:00Z',created_at:'2026-01-01T00:00:00Z',published_at:'2026-02-01T00:00:00Z',generation_meta:null},{content:'approved',updated_at:'2026-11-08T12:01:00+09:00'});
 assert.equal(calls[0].options.method,'PATCH');assert.equal(calls[0].url.searchParams.get('updated_at'),'eq.2026-01-01T00:00:00Z');
 assert.equal(calls[0].url.searchParams.get('xmin'),'eq.9798');assert.equal(calls[1].url.searchParams.get('xmin'),'eq.9855');
 assert.equal(calls[1].url.searchParams.get('status'),'eq.published');assert.equal(calls[1].url.searchParams.has('generation_meta'),false);
 assert.deepEqual(Object.keys(JSON.parse(calls[1].options.body)).sort(),['content','updated_at']);
});

test('partial product write leaves durable guard marker and cannot auto-replay',async()=>{
 const fs=await import('node:fs'),os=await import('node:os'),path=await import('node:path');
 const {withPublicationLock}=await import('../seo/article-guard.mjs');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'revision-cas-'));
 try {const h=harness();h.deps.lock=(fn,options)=>withPublicationLock(root,fn,options);
 let attempts=0;h.deps.db.patchProductCAS=async()=>{attempts++;throw Error('unknown');};
 await assert.rejects(execute(h.input,h.deps),/reconciliation/);
 assert.equal(fs.existsSync(path.join(root,'.publication.in-flight.json')),true);
 h.state.products=h.input.bundle.products.map(p=>({...productRow(p),xmin:'20'})); // Desired data never clears an unknown prior attempt.
 await assert.rejects(execute(h.input,h.deps),/in-flight/);assert.equal(attempts,1);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('raw Python floats remain exactly bound in baseline and complete candidate fingerprints',async()=>{
 const {spawnSync}=await import('node:child_process');const h=harness();
 h.input.bundle.revisionContext.baseArticle.qualityScore=8;
 h.input.bundle.article.qualityScore=8;h.state.article.quality_score=8;
 const script=`import json,sys,hashlib
v=json.load(sys.stdin)
c=v['bundle']['revisionContext']
c['baseArticle']['qualityScore']=8.0
v['bundle']['article']['qualityScore']=8.0
f=lambda x:hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
c['baseHash']=f(c['baseArticle'])
v['revision']=f(v['bundle'])
v['approval']['revision']=v['revision']
print(json.dumps(v,ensure_ascii=False))`;
 const made=spawnSync('python3',['-c',script],{input:JSON.stringify(h.input),encoding:'utf8'});
 assert.equal(made.status,0);h.deps.rawRequest=made.stdout;const input=JSON.parse(made.stdout);
 assert.equal((await execute(input,h.deps)).verified,true);
});


test('revision production reads require fresh xmin and never compare it as article/product content',async t=>{
 const {revisionDependencies}=await import('./revision-publisher.mjs');const calls=[];
 t.mock.method(globalThis,'fetch',async(url)=>{calls.push(new URL(url));return Response.json([{id:'p0',xmin:'42'}]);});
 const deps=revisionDependencies({SUPABASE_URL:'https://db.example',SUPABASE_SERVICE_ROLE_KEY:'test-only'});
 await deps.db.getProducts(['p0']);await deps.db.findArticles('article-024','firepit-beginner-guide');
 assert.ok(calls.every(u=>u.searchParams.get('select').split(',').includes('xmin')));
 await assert.rejects(deps.db.patchProductCAS({id:'p0',updated_at:'same',category_id:'tent'},{}),/version/);
 assert.equal(calls.length,2);
});

test('same-timestamp concurrent product or article edit increments xmin and cannot be overwritten',async t=>{
 const {revisionDependencies}=await import('./revision-publisher.mjs');
 for(const kind of ['products','articles']){
  let stored={id:kind==='products'?'p0':'article-024',slug:'firepit-beginner-guide',category_id:'tent',
    status:'published',created_at:'2026-01-01T00:00:00Z',published_at:'2026-02-01T00:00:00Z',
    updated_at:'2026-09-01T00:00:00Z',xmin:'100',generation_meta:null,content:'original',specs:{weight:'original'}};
  let writes=0;
  const stub=t.mock.method(globalThis,'fetch',async(url,options)=>{
   const u=new URL(url);
   if(options.method!=='PATCH')return Response.json([structuredClone(stored)]);
   // A different writer edits the row after our GET without advancing updated_at.
   stored.xmin='101';if(kind==='products')stored.specs={weight:'concurrent'};else stored.content='concurrent';
   if(u.searchParams.has('xmin') && u.searchParams.get('xmin')!=='eq.'+stored.xmin)return Response.json([]);
   writes++;Object.assign(stored,JSON.parse(options.body));return Response.json([stored]);
  });
  const deps=revisionDependencies({SUPABASE_URL:'https://db.example',SUPABASE_SERVICE_ROLE_KEY:'test-only'});
  const before=(await(kind==='products'?deps.db.getProducts(['p0']):deps.db.findArticles('article-024','firepit-beginner-guide')))[0];
  const result=await(kind==='products'?deps.db.patchProductCAS(before,{specs:{weight:'approved'}}):deps.db.patchPublishedCAS(before,{content:'approved'}));
  assert.deepEqual(result,[]);assert.equal(writes,0);assert.equal(stored.updated_at,before.updated_at);
  assert.equal(kind==='products'?stored.specs.weight:stored.content,'concurrent');stub.mock.restore();
 }
});


function yahooHarness(next) {
 const h=harness({patched:false}),c=h.input.bundle.revisionContext;
 c.baseProducts[0].yahooUrl='https://shopping.yahoo.co.jp/search?p=legacy';
 c.candidateProducts[0].yahooUrl=next;c.candidateProducts[0].updatedAt='2026-11-08T12:00:00+09:00';
 c.changeSummary+='。商品同一性未確認のYahoo検索リンクを非表示';
 const old=c.baseProducts[0],candidate=c.candidateProducts[0];
 c.productPatches=[{id:old.id,baseHash:bundleHash(old),candidateHash:bundleHash(candidate),fields:{yahooUrl:next,updatedAt:candidate.updatedAt}}];
 h.state.products=c.baseProducts.map(p=>({...productRow(p),xmin:'10'}));h.input.revision=bundleHash(h.input.bundle);h.input.approval.revision=h.input.revision;
 return h;
}
test('approved Yahoo route removal only clears that optional field via bound product CAS',async()=>{
 const h=yahooHarness('');assert.equal((await execute(h.input,h.deps)).verified,true);
 assert.equal(h.state.products[0].yahoo_url,'');assert.deepEqual(h.state.writes,['product:p0','article']);
});
test('changed nonempty Yahoo route or null is rejected before any write',async()=>{
 for(const next of ['https://store.shopping.yahoo.co.jp/shop/item.html',null]){
 const h=yahooHarness(next);await assert.rejects(execute(h.input,h.deps),/Yahoo|product field/);assert.deepEqual(h.state.writes,[]);}
});


test('missing inherited context, changed template bytes or public advice blocks before any write',async()=>{
 for(const mode of ['missing','template','dom']){
  const h=harness();
  if(mode==='missing'){delete h.input.bundle.inheritedPresentationContext;h.input.revision=bundleHash(h.input.bundle);h.input.approval.revision=h.input.revision;}
  if(mode==='template')h.state.files={...h.state.files,[TEMPLATE_FILES[1]]:'b'.repeat(64)};
  if(mode==='dom')h.state.adviceHtml=h.state.adviceHtml.replace('既存の安全情報','changed public advice');
  await assert.rejects(execute(h.input,h.deps),/inherited/);assert.deepEqual(h.state.writes,[]);
 }
});
test('inherited context drift during product writes blocks article CAS and requires reconciliation',async()=>{
 const h=harness();const patch=h.deps.db.patchProductCAS;
 h.deps.db.patchProductCAS=async(...args)=>{const result=await patch(...args);h.state.adviceHtml=h.state.adviceHtml.replace('既存の安全情報','changed public advice');return result;};
 await assert.rejects(execute(h.input,h.deps),/reconciliation/);assert.deepEqual(h.state.writes,['product:p0']);
});

test('revision accepts exact desired rows without patch, refuses any third field or timestamp before writes',async()=>{
 for(const mode of ['desired','field','timestamp']){
  const h=harness({count:2});h.state.products=h.input.bundle.products.map(p=>({...productRow(p),xmin:'20'}));
  if(mode==='field')h.state.products[1].description='third state';
  if(mode==='timestamp')h.state.products[1].updated_at='2026-11-08T12:00:01+09:00';
  if(mode==='desired'){
   assert.equal((await execute(h.input,h.deps)).verified,true);assert.deepEqual(h.state.writes,['article']);
  }else{await assert.rejects(execute(h.input,h.deps));assert.deepEqual(h.state.writes,[]);}
 }
});

test('revision fresh pre-CAS read skips candidate installed since initial baseline check',async()=>{
 const h=harness(),get=h.deps.db.getProducts;let reads=0;
 h.deps.db.getProducts=async ids=>{if(++reads===2)h.state.products=h.input.bundle.products.map(p=>({...productRow(p),xmin:'20'}));return get(ids);};
 assert.equal((await execute(h.input,h.deps)).verified,true);assert.deepEqual(h.state.writes,['article']);
});

test('revision mixed rows patch only baseline; fresh third state blocks before product or article mutation',async()=>{
 for(const mode of ['mixed','third']){
  const h=harness({count:2});
  if(mode==='mixed')h.state.products[1]={...productRow(h.input.bundle.products[1]),xmin:'20'};
  else{const get=h.deps.db.getProducts;let reads=0;h.deps.db.getProducts=async ids=>{if(++reads===2)h.state.products[0].updated_at='2026-11-08T12:00:01+09:00';return get(ids);};}
  if(mode==='mixed'){
   assert.equal((await execute(h.input,h.deps)).verified,true);assert.deepEqual(h.state.writes,['product:p0','article']);
  }else{await assert.rejects(execute(h.input,h.deps),/reconcil/);assert.deepEqual(h.state.writes,[]);}
 }
});
