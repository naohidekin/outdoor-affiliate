/** Dependency-injected executor only. No production runner, credentials or network adapter. */
import {isDeepStrictEqual as equal} from 'node:util';
import {validatePreparedRetraction,retractionHash,textHash} from './safety-retraction.mjs';
const check=(v,m)=>{if(!v)throw Error(m);};
const ACTIVE=new Set(['article-037','728d8163-ebda-427a-ace8-ec1494bf1261']);
const ALIAS='https://camp-gear-lab.com/articles/insect-repellent-bracelet-ranking';
const CANONICAL='https://camp-gear-lab.com/articles/insect-repellent-gear-roundup';
const SCOPE={channel:'chatgpt',roomId:'23c691108d088198a11cf37ab7eab55a',ownerId:'user-0tmIgoZEss24lHzstHN0apfu'};
const OWNER_MESSAGE='Sentinel_727fb8374a3c81919c6b320c21a16c0f';
const PROPOSALS=['Sentinel_bf658317985c8191af5db9638bc6e96f','Sentinel_1bfb3ae268948191bf5c0e79b7fac2ae'];
function requireRunning(deps){check(deps.requireRunning()===true,'execution suspended');}
function validate(input){
 const {prepared:p,baseArticle:b,owner,review}=input;
 validatePreparedRetraction(p,b);
 check(ACTIVE.has(b.id),'target not enabled for execution');
 check(owner && equal(owner.scope,SCOPE) && owner.text==='訂正案が出たら訂正して。','exact owner source and scope required');
 check(owner.messageId===OWNER_MESSAGE && equal(owner.proposalReferences,PROPOSALS) && !('messageTs' in owner),'exact ChatGPT source/proposals required');
 check(owner.candidateHash===p.candidateHash && owner.baseHash===p.baseHash,'owner candidate binding changed');
 check(review?.status==='passed' && review.candidateHash===p.candidateHash && review.baseHash===p.baseHash && review.manifestHash===retractionHash(p.manifest),'independent review binding required');
 check(typeof review.artifactReference==='string' && review.artifactReference.length>0 && review.reviewerId && review.preparerId && review.reviewerId!==review.preparerId,'independent review provenance required');
 check(review.deletionOnly===true && review.safetyWarningsPreserved===true && review.remainingRecommendationChecked===true,'semantic safety review required');
 check(typeof input.deps.requireRunning==='function','execution policy guard required');
 for(const k of ['verifyOwnerBinding','verifyIndependentReview','verifyPresentation','verifyRenderedCandidate','readRedirect','publicGet','revalidate','lock','now'])check(typeof input.deps[k]==='function','missing dependency '+k);
 check(input.deps.db && ['findArticles','patchPublishedCAS'].every(k=>typeof input.deps.db[k]==='function'),'CAS dependencies required');
}
async function redirect(deps){
 const r=await deps.readRedirect(ALIAS);
 check(r?.status===308 && r.url===ALIAS && r.location===CANONICAL,'permanent canonical redirect changed');
}
export function verifyRetractionDOM(html,p){
 check(typeof html==='string','public HTML required');
 const visible=html.replace(/<!--[\s\S]*?-->|<(script|style|template)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,'');
 const digest=textHash(p.candidate.content);
 const tags=visible.match(/<[a-z][^>]*>/gi)||[];
 check(tags.some(t=>new RegExp('\\bdata-review-content-sha256\\s*=\\s*["\\\']'+digest+'["\\\']','i').test(t)),'public content hash mismatch');
 for(const id of p.manifest.removeProductIds)check(!visible.includes(id),'removed product remains in public DOM');
 return {contentHash:digest,domHash:textHash(visible)};
}
export async function executeSafetyRetraction(input){
 validate(input);const {prepared:p,baseArticle:b,deps}=input;
 requireRunning(deps);
 // Callbacks must validate real saved evidence; supplied records alone grant no authority.
 check(await deps.verifyOwnerBinding(input.owner,p)===true,'untrusted owner evidence');
 check(await deps.verifyIndependentReview(input.review,p)===true,'untrusted review evidence');
 return deps.lock(async()=>{
  validate(input);
  const before=await deps.db.findArticles(b.id,b.slug);
  check(Array.isArray(before)&&before.length===1&&equal(before[0],b),'full baseline including xmin changed');
  await redirect(deps);
  check(await deps.verifyPresentation(b,p)===true,'inherited presentation changed');
  const now=deps.now();check(typeof now==='string'&&Number.isFinite(Date.parse(now))&&Date.parse(now)>Date.parse(b.updated_at),'fresh timestamp required');
  const patch={content:p.candidate.content,faqs:structuredClone(p.candidate.faqs),product_ids:[...p.candidate.product_ids],updated_at:now};
  requireRunning(deps);
  let phase='article_update';
  try{
   const changed=await deps.db.patchPublishedCAS(before[0],patch);
   check(Array.isArray(changed)&&changed.length===1,'CAS conflict');
   phase='db_readback';
   const rows=await deps.db.findArticles(b.id,b.slug);
   check(Array.isArray(rows)&&rows.length===1,'DB readback missing');
   const {xmin,...actual}=rows[0],{xmin:oldVersion,...expected}= {...b,...patch};
   check(/^\d{1,10}$/.test(String(xmin))&&BigInt(xmin)<=4294967295n&&String(xmin)!==String(oldVersion),'new xmin required');
   check(equal(actual,expected),'complete DB readback mismatch');
   phase='cache';await deps.revalidate(b.slug,b.category_id);
   phase='public_readback';await redirect(deps);
   const url='https://camp-gear-lab.com/articles/'+b.slug,html=await deps.publicGet(url);
   const proof=verifyRetractionDOM(html,p);
   check(await deps.verifyRenderedCandidate(p.candidate,html)===true,'rendered content/FAQ mismatch');
   check(await deps.verifyPresentation(b,p,html)===true,'inherited public presentation changed');
   return {kind:'safety_retraction_v1',status:'verified',articleId:b.id,candidateHash:p.candidateHash,baseHash:p.baseHash,url,...proof,remoteUpdatedAt:now,redirectPreserved:true};
  }catch(error){const failure=Error('unknown: safety retraction requires read-only reconciliation');failure.diagnostic={phase};throw failure;}
 },{readOnly:false});
}
