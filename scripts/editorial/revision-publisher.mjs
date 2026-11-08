/** Targeted, revision-bound updates. Importing never performs network or writes. */
import { articleFields, productFields, normalizeTimestamps, selectedRow, equal, requireValue as check,
  bundleHash, productRow, verifyApprovedImages, verifyPublicHTML, sha, timestamp, productionDependencies } from './publish.mjs';
import { withPublicationLock, seoRoot } from '../seo/article-guard.mjs';
import { detectMedicalRisks } from '../../src/lib/medical-review-gate.mjs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {templateHashes,validatePresentation,assertTemplateFiles,assertPublicAdvice} from './template-context.mjs';
const REPO=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');

const TARGETS = { 'article-024':'firepit-beginner-guide', 'article-005':'single-burner-ranking', 'article-002':'landlock-vs-landnest-shelter' };
const EDIT = new Set(['title','content','excerpt','metaDescription','faqs','tags','productIds','author','generationMeta']);
const PRODUCT_EDIT = new Set(['name','brand','specs','imageUrl','affiliateUrl','amazonUrl','price','description','rating','availability','updatedAt','yahooUrl']);
const record = v => v && typeof v === 'object' && !Array.isArray(v);
const row = article => normalizeTimestamps(Object.fromEntries(Object.entries(articleFields).map(([k,v])=>[v,article[k] ?? null])));
const atHash = (input,deps,...keys)=>bundleHash(input.bundle,{rawRequest:deps.rawRequest,fieldPath:['bundle','revisionContext',...keys]});

function binding(input,deps) {
  const {bundle:b,revision} = input; const c=b?.revisionContext, base=c?.baseArticle, a=b?.article;
  check(record(c) && c.kind==='article_revision' && record(base) && record(a), 'revision binding required');
  validatePresentation(b.inheritedPresentationContext,a.slug);
  check(TARGETS[base.id]===base.slug && a.id===base.id && a.slug===base.slug && base.status==='published', 'fixed revision target required');
  check(revision===bundleHash(b,{rawRequest:deps.rawRequest}) && /^[a-f0-9]{64}$/.test(revision||''), 'revision fingerprint changed');
  check(c.baseHash===atHash(input,deps,'baseArticle'), 'revision baseline hash changed');
  check(typeof c.changeSummary==='string' && c.changeSummary.trim() && typeof c.editorialCorrectionInstructions==='string'
    && c.editorialCorrectionInstructions.trim(), 'revision specification required');
  check(Array.isArray(c.verifiedAuthorFacts) && c.verifiedAuthorFacts.every(f=>typeof f==='string' && f.trim() && a.content.includes(f)), 'author fact missing');
  for (const key of new Set([...Object.keys(base),...Object.keys(a)]))
    if(!EDIT.has(key)) check(equal(base[key]??null,a[key]??null),'protected revision article field changed');
  check(Object.keys(a).every(k=>k in articleFields || k==='author'),'unsupported revision article field');
  const oldMeta={...(base.generationMeta||{})}, nextMeta={...(a.generationMeta||{})};
  delete oldMeta.socialCard;delete nextMeta.socialCard;
  check(equal(oldMeta,nextMeta),'unrelated generation metadata changed');
  check(a.author===(base.author || base.generationMeta?.editorialRuntime?.author || 'ギア男'),'revision author changed');
  check(detectMedicalRisks([a.title,a.content,JSON.stringify(a.faqs||[])].join('\n')).length===0,'medical-risk revision requires separate review');
  const ids=c.targetProductIds;
  check(Array.isArray(base.productIds) && Array.isArray(ids) && ids.length>0 && ids.length<=20 && new Set(ids).size===ids.length
    && ids.every(id=>typeof id==='string' && base.productIds.includes(id)) && equal(a.productIds,ids),'revision product selection changed');
  check(record(c.productRemovalReasons) && equal(Object.keys(c.productRemovalReasons).sort(),base.productIds.filter(id=>!ids.includes(id)).sort())
    && Object.values(c.productRemovalReasons).every(s=>typeof s==='string' && s.trim()),'removed product reasons required');
  check(Array.isArray(c.baseProducts) && Array.isArray(c.candidateProducts) && equal(b.products,c.candidateProducts)
    && equal(c.baseProducts.map(p=>p.id),ids) && equal(c.candidateProducts.map(p=>p.id),ids),'exact product snapshots required');
  const patches=[];
  for(let i=0;i<ids.length;i++) {
    const old=c.baseProducts[i], next=c.candidateProducts[i];productRow(old);productRow(next);
    check(equal(Object.keys(old).sort(),Object.keys(next).sort()),'product snapshot fields changed');
    const fields=Object.fromEntries(Object.keys(next).filter(k=>!equal(old[k],next[k])).map(k=>[k,next[k]]));
    check(Object.keys(fields).every(k=>PRODUCT_EDIT.has(k)),'protected product field changed');
    check(!('yahooUrl' in fields) || next.yahooUrl==='','Yahoo route changes may only remove the optional URL');
    check(typeof old.updatedAt==='string' && typeof next.updatedAt==='string','product timestamps required');
    if(Object.keys(fields).length) {
      check(old.updatedAt!==next.updatedAt,'patched product timestamp required');
      patches.push({id:old.id,baseHash:atHash(input,deps,'baseProducts',i),candidateHash:atHash(input,deps,'candidateProducts',i),fields});
    }
  }
  check(equal(c.productPatches,patches),'approved product patches changed');
  check(!('productOverrides' in b) && !('productPatches' in b),'unbound product patches refused');
  const imageProofs=b.images;
  check(Array.isArray(imageProofs) && imageProofs.length<=41 && b.products.every(p=>imageProofs.some(i=>i.productId===p.id && i.url===p.imageUrl && i.verified===true)), 'product image binding required');
  if(a.generationMeta?.socialCard){
    const card=a.generationMeta.socialCard, proofs=imageProofs.filter(i=>i.role==='social-card');
    check(proofs.length===1 && card.width===1200 && card.height===630 && ['url','sha256','size','contentType'].every(k=>card[k] && card[k]===proofs[0][k]),'revision photo card proof missing');
  }
  return c;
}

async function productsEqual(db, expected) {
  const rows=await db.getProducts(expected.map(p=>p.id));
  check(Array.isArray(rows) && rows.length===expected.length && new Set(rows.map(p=>p.id)).size===rows.length,'product baseline missing');
  for(const p of expected)check(equal(selectedRow(rows.find(r=>r.id===p.id)||{},productFields),productRow(p)),'product baseline changed');
  return rows;
}

// Compare the complete normalized catalog row, never only the patch fields.
// Candidate-first also makes unchanged baseline==candidate rows a strict no-op.
export async function productsBaseOrCandidate(db, before, candidates) {
  const rows=await db.getProducts(before.map(p=>p.id));
  check(Array.isArray(rows) && rows.length===before.length && new Set(rows.map(p=>p.id)).size===rows.length,'product baseline missing');
  const pending=[];
  for(const base of before) {
    const current=rows.find(p=>p.id===base.id),desired=candidates.find(p=>p.id===base.id);
    check(current && desired,'product snapshot missing');
    const token=String(current.xmin??'');
    check(/^[0-9]{1,10}$/.test(token) && BigInt(token)<=4294967295n,'fresh product xmin required');
    const actual=selectedRow(current,productFields);
    if(equal(actual,productRow(desired)))continue;
    check(equal(actual,productRow(base)),'full product baseline or candidate changed');
    pending.push(base.id);
  }
  return {rows,pending};
}

async function verifyInheritedPresentation(input,deps,html) {
  const context=validatePresentation(input.bundle.inheritedPresentationContext,input.bundle.article.slug);
  const files=await (deps.currentTemplateHashes ? deps.currentTemplateHashes() : templateHashes(REPO));
  assertTemplateFiles(context,files);
  const currentHTML=html ?? await deps.publicGet('https://camp-gear-lab.com/articles/'+input.bundle.article.slug);
  assertPublicAdvice(context,currentHTML);
}

export async function executeRevision(input,deps) {
  const c=binding(input,deps), publishing=input.action==='publish-revision';
  if(publishing)check(record(input.approval) && input.approval.revision===input.revision && typeof input.approval.approverId==='string'
    && input.approval.approverId && record(input.approval.evidence) && Object.keys(input.approval.evidence).length,'exact revision owner approval required');
  check(deps.db && deps.lock,'revision dependencies required');
  return deps.lock(async()=>{
    binding(input,deps);
    const found=await deps.db.findArticles(c.baseArticle.id,c.baseArticle.slug);
    check(found.length===1 && equal(selectedRow(found[0],articleFields),row(c.baseArticle)),'published article baseline changed');
    const {pending}=await productsBaseOrCandidate(deps.db,c.baseProducts,c.candidateProducts); // ALL checked before first public write.
    if(!publishing)return {status:'private_revision',articleId:c.baseArticle.id,revision:input.revision};
    await verifyInheritedPresentation(input,deps); // Template and current public DOM before ANY mutation.
    await verifyApprovedImages(input.bundle,deps.imageDigest);
    const affected=c.productPatches.length ? await deps.db.findProductArticles(c.productPatches.map(p=>p.id)) : [];
    check(Array.isArray(affected) && affected.length<=500,'affected article cache scope unavailable');
    const candidate=row(input.bundle.article);
    candidate.generation_meta={...(input.bundle.article.generationMeta||{}),editorialRuntime:{revision:input.revision,author:input.bundle.article.author}};
    candidate.updated_at=(deps.now||timestamp)();
    const patch=Object.fromEntries(['title','content','excerpt','meta_description','faqs','tags','product_ids','generation_meta','updated_at'].map(k=>[k,candidate[k]]));
    let phase='product_updates';
    try {
      for(const change of c.productPatches.filter(p=>pending.includes(p.id))) {
        const base=c.baseProducts.find(p=>p.id===change.id),desired=c.candidateProducts.find(p=>p.id===change.id);
        const fresh=await productsBaseOrCandidate(deps.db,[base],[desired]);
        if(!fresh.pending.length)continue; // Another approved job installed exactly this row.
        const before=fresh.rows[0];
        const fields=Object.fromEntries(Object.entries(change.fields).map(([k,v])=>[productFields[k],v]));
        const changed=await deps.db.patchProductCAS(before,fields);
        check(Array.isArray(changed) && changed.length===1,'product CAS conflict');
        await productsEqual(deps.db,[desired]);
      }
      await productsEqual(deps.db,c.candidateProducts); // Confirm every patched row before article CAS.
      const current=await deps.db.findArticles(c.baseArticle.id,c.baseArticle.slug);
      check(current.length===1 && equal(selectedRow(current[0],articleFields),row(c.baseArticle)),'article changed during product updates');
      await verifyInheritedPresentation(input,deps);
      phase='article_update';
      const changed=await deps.db.patchPublishedCAS(current[0],patch);
      check(Array.isArray(changed) && changed.length===1,'published article CAS conflict');
      phase='article_readback';
      const readback=await deps.db.findArticles(c.baseArticle.id,c.baseArticle.slug);
      check(readback.length===1 && equal(selectedRow(readback[0],articleFields),normalizeTimestamps(candidate)),'revision DB readback mismatch');
      await productsEqual(deps.db,c.candidateProducts);
      const pages=new Map(affected.filter(p=>p.status==='published').map(p=>[p.slug,p.category_id]));
      pages.set(c.baseArticle.slug,c.baseArticle.categoryId);
      phase='cache_revalidation';
      for(const [slug,category] of pages)await deps.revalidate(slug,category);
      const url='https://camp-gear-lab.com/articles/'+c.baseArticle.slug;
      phase='public_readback';
      await verifyRevisionPublicReadback(input,deps,url);
      phase='image_readback';
      await verifyApprovedImages(input.bundle,deps.imageDigest);
      return {verified:true,url,contentHash:sha(input.bundle.article.content),remoteUpdatedAt:readback[0].updated_at,
        readback:{verified:true,fingerprint:input.revision,inheritedAdviceDomSha256:input.bundle.inheritedPresentationContext.domSha256,...(input.bundle.article.generationMeta?.socialCard?{socialCard:input.bundle.article.generationMeta.socialCard}:{})}};
    } catch (error) {
      const failure=Error('unknown: revision product/article publication requires reconciliation');
      failure.diagnostic={phase,...error?.diagnostic};throw failure;
    }
  },{readOnly:!publishing});
}

// Retry only reads after cache invalidation, never a product/article mutation.
export async function verifyRevisionPublicReadback(input,deps,url) {
  const delays=deps.publicReadbackDelays ?? [0];
  check(Array.isArray(delays)&&delays.length>0&&delays.length<=4&&delays.every(n=>Number.isInteger(n)&&n>=0&&n<=5000),'invalid public readback delays');
  let last;
  for(const delay of delays) {
    if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
    try {
      const html=await deps.publicGet(url);
      check(verifyPublicHTML(html,input.bundle),'revision public HTML mismatch');
      await verifyInheritedPresentation(input,deps,html);
      return html;
    } catch(error){last=error;}
  }
  throw last;
}

export function revisionDependencies(env) {
  const base=productionDependencies(env), origin=new URL(env.SUPABASE_URL).origin;
  const headers={apikey:env.SUPABASE_SERVICE_ROLE_KEY,Authorization:'Bearer '+env.SUPABASE_SERVICE_ROLE_KEY,'Content-Type':'application/json'};
  async function request(table,query,patch) {
    let response;
    const operation='db_'+(patch?'patch_':'read_')+table;
    try {response=await fetch(origin+'/rest/v1/'+table+'?'+new URLSearchParams(query),{
      headers:{...headers,...(patch?{Prefer:'return=representation,handling=strict'}:{})},
      ...(patch?{method:'PATCH',body:JSON.stringify(patch)}:{}),redirect:'error',signal:AbortSignal.timeout(25000)});
      if(!response.ok) {
        let dbCode;try{const body=await response.json();if(/^[A-Z0-9]{5}$/.test(body?.code||''))dbCode=body.code;}catch{}
        const error=Error('revision database request failed');
        error.diagnostic={operation,httpStatus:response.status,...(dbCode?{dbCode}:{})};throw error;
      }
      return await response.json();
    } catch(error) {
      if(error?.diagnostic)throw error;
      const failure=Error('revision database result unknown');failure.diagnostic={operation};throw failure;
    }
  }
  // xmin is fetched with these exact rows and used only for this short read/CAS window.
  // Semantic baselines remain the approved full field snapshots; version tokens are not proposal identity.
  const quoted=ids=>ids.map(id=>'"'+String(id).replace(/\\/g,'\\\\').replace(/"/g,'\\"')+'"').join(',');
  function version(before) {
    const token=String(before?.xmin ?? '');
    check(/^[0-9]{1,10}$/.test(token) && BigInt(token)<=4294967295n,'fresh database row version required');
    return token;
  }
  async function readVersioned(table,query) {
    const rows=await request(table,query);
    check(Array.isArray(rows),'versioned database rows required');
    rows.forEach(version); // Refuse a missing token before the first product mutation.
    return rows;
  }
  base.db.findArticles=(id,slug)=>readVersioned('articles',{select:[...Object.values(articleFields),'xmin'].join(','),
    or:`(id.eq.${id},slug.eq.${slug})`});
  base.db.getProducts=ids=>readVersioned('products',{select:[...Object.values(productFields),'xmin'].join(','),id:'in.('+quoted(ids)+')'});
  async function patchVersioned(table,before,query,patch) {
    return request(table,{...query,xmin:'eq.'+version(before)},patch);
  }
  base.db.patchProductCAS=(before,patch)=>patchVersioned('products',before,{id:'eq.'+before.id,updated_at:'eq.'+before.updated_at,
    category_id:before.category_id===null?'is.null':'eq.'+before.category_id,select:Object.values(productFields).join(',')},patch);
  base.db.patchPublishedCAS=(before,patch)=>patchVersioned('articles',before,{id:'eq.'+before.id,slug:'eq.'+before.slug,status:'eq.published',
    updated_at:'eq.'+before.updated_at,created_at:'eq.'+before.created_at,published_at:'eq.'+before.published_at,
    select:Object.values(articleFields).join(',')},patch);
  base.db.findProductArticles=ids=>request('articles',{select:'id,slug,status,category_id',
    or:'('+ids.map(id=>'product_ids.cs.'+JSON.stringify([id])).join(',')+')',limit:501});
  base.publicReadbackDelays=[0,1000,3000];
  base.lock=(action,options)=>withPublicationLock(seoRoot(),action,options);
  return base;
}
