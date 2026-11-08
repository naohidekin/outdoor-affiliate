/** New-article-only approved catalog patches. No network or writes on import.
 * verifyApproval is a trusted caller dependency, NEVER a boolean in JSON stdin.
 * Until main supplies its ledger verifier, the standalone CLI fails closed.
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {articleRow, productFields, productRow, selectedRow, equal, requireValue as check,
  bundleHash, verifyApprovedImages, validateBundle, executeNewArticle, timestamp} from './publish.mjs';
import {revisionDependencies,productsBaseOrCandidate} from './revision-publisher.mjs';
import {atomicJson} from '../seo/article-guard.mjs';

const RAW = ['baseProducts','candidateProducts','changeSummary'];
const KEYS = [...RAW,'kind','productPatches'];
const EDIT = new Set(['name','brand','specs','imageUrl','affiliateUrl','amazonUrl','price','description','rating','availability','updatedAt','yahooUrl']);
const record = v => v && typeof v === 'object' && !Array.isArray(v);
const sameKeys = (v, keys) => record(v) && equal(Object.keys(v).sort(), [...keys].sort());
const contextHash = (input,deps,...keys) => bundleHash(input.bundle,{rawRequest:deps.rawRequest,fieldPath:['bundle','catalogCorrectionContext',...keys]});

function binding(input,deps) {
  check(input?.action==='publish-corrected','publish-corrected required');
  const b=input.bundle,c=b?.catalogCorrectionContext;
  check(sameKeys(c,KEYS) && c.kind==='catalog_correction' && !('revisionContext' in b),'new article correction binding required');
  if(deps.rawRequest)check(equal(JSON.parse(deps.rawRequest).bundle,b),'received bundle changed');
  check(/^[a-f0-9]{64}$/.test(input.revision||'') && input.revision===bundleHash(b,{rawRequest:deps.rawRequest}),'correction fingerprint changed');
  validateBundle(b); articleRow(b.article,input.revision); // Normal new-article schema, risk gate and timestamps BEFORE writes.
  check(!['productOverrides','baseProductRows','productPatches'].some(k=>k in b),'unbound correction fields refused');
  check(typeof c.changeSummary==='string' && c.changeSummary.trim() && c.changeSummary.length<=12000,'correction summary required');
  const before=c.baseProducts,after=c.candidateProducts,ids=b.article.productIds;
  check(Array.isArray(before) && Array.isArray(after) && before.length>0 && before.length<=20
    && equal(before.map(p=>p?.id),ids) && equal(after.map(p=>p?.id),ids) && equal(b.products,after),'exact ordered correction products required');
  const patches=[];
  for(let i=0;i<before.length;i++) {
    const old=before[i],next=after[i],oldRow=productRow(old),nextRow=productRow(next);
    check(equal(Object.keys(old).sort(),Object.keys(next).sort()),'product snapshot fields changed');
    const fields=Object.fromEntries(Object.keys(next).filter(k=>!equal(old[k],next[k])).map(k=>[k,next[k]]));
    check(Object.keys(fields).every(k=>EDIT.has(k)),'protected product fields changed');
    check(!('yahooUrl' in fields) || next.yahooUrl==='','Yahoo route changes may only remove the optional URL');
    check(typeof old.updatedAt==='string' && typeof next.updatedAt==='string','product timestamps required');
    if(Object.keys(fields).length) {
      check(oldRow.updated_at!==nextRow.updated_at,'patched product needs a new bound timestamp');
      patches.push({id:old.id,baseHash:contextHash(input,deps,'baseProducts',i),candidateHash:contextHash(input,deps,'candidateProducts',i),fields});
    }
  }
  check(equal(c.productPatches,patches),'approved product patches changed');
  return c;
}

function version(row) {
  const value=String(row?.xmin??'');
  check(/^[0-9]{1,10}$/.test(value) && BigInt(value)<=4294967295n,'fresh product xmin required');
}
async function productsEqual(db, expected) {
  const rows=await db.getProducts(expected.map(p=>p.id));
  check(Array.isArray(rows) && rows.length===expected.length && new Set(rows.map(p=>p.id)).size===rows.length,'product baseline missing');
  for(const p of expected) {
    const found=rows.find(r=>r.id===p.id); version(found);
    check(equal(selectedRow(found,productFields),productRow(p)),'full product baseline changed');
  }
  return rows;
}

/** Private durable evidence, independent of the global public in-flight fence.
 * Caller must hold the global publication lock for assertClear/start/update.
 * Unfinished entries fence ALL correction jobs, including different revisions.
 */
export function privateCorrectionJournal(root=path.join(os.homedir(),'.secretary/state/camp-editorial-slack/catalog-corrections')) {
  check(typeof root==='string' && path.isAbsolute(root) && root!==path.parse(root).root,'private journal root required');
  function privateRoot() {
    let info;
    try{info=fs.lstatSync(root);}catch(error){if(error.code==='ENOENT')return false;throw error;}
    check(info.isDirectory() && !info.isSymbolicLink() && (info.mode & 0o777)===0o700
      && info.uid===process.getuid(),'private journal directory required');
    for(let dir=path.resolve(root);;dir=path.dirname(dir)) {
      check(!fs.existsSync(path.join(dir,'.git')),'private journal must remain outside Git');
      if(dir===path.dirname(dir))break;
    }
    return true;
  }
  const file=revision=>{check(/^[a-f0-9]{64}$/.test(revision||''),'journal fingerprint required');return path.join(root,revision+'.json');};
  const syncDir=()=>{const fd=fs.openSync(root,'r');try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}};
  return {
    assertClear(revision) {
      if(!privateRoot())return;
      for(const name of fs.readdirSync(root)) {
        check(/^[a-f0-9]{64}\.json$/.test(name),'correction journal requires reconciliation');
        const target=path.join(root,name),info=fs.lstatSync(target);
        check(info.isFile() && !info.isSymbolicLink() && (info.mode & 0o777)===0o600
          && info.uid===process.getuid() && info.nlink===1,'private journal entry required');
        const saved=JSON.parse(fs.readFileSync(target,'utf8'));
        check(saved.schemaVersion===1 && saved.revision+'.json'===name && saved.status==='complete' && name!==revision+'.json','correction journal requires reconciliation; never replay');
      }
    },
    start(entry) {
      fs.mkdirSync(root,{recursive:true,mode:0o700});
      privateRoot();
      const fd=fs.openSync(file(entry.revision),'wx',0o600);
      try{fs.writeFileSync(fd,JSON.stringify(entry)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
      syncDir();
    },
    update(entry) {check(privateRoot(),'private journal missing');atomicJson(file(entry.revision),entry);},
  };
}

export async function executeCorrected(input,deps) {
  // Snapshot references across awaits; models/callers cannot edit the approved proposal in flight.
  input=structuredClone(input);
  const c=binding(input,deps),a=input.approval;
  check(record(a) && a.revision===input.revision && typeof a.approverId==='string' && a.approverId.trim()
    && record(a.evidence) && Object.keys(a.evidence).length>0,'exact correction owner approval required');
  check(typeof deps.verifyApproval==='function' && await deps.verifyApproval(input,{rawRequest:deps.rawRequest})===true,'trusted owner approval verifier required');
  check(deps.db && typeof deps.lock==='function' && deps.journal,'correction dependencies required');
  return deps.lock(async()=>{
    binding(input,deps);
    check(await deps.verifyApproval(input,{rawRequest:deps.rawRequest})===true,'trusted owner approval changed');
    await deps.journal.assertClear(input.revision);
    const article=input.bundle.article;
    check((await deps.db.findArticles(article.id,article.slug)).length===0,'new article identity already exists');
    const {pending}=await productsBaseOrCandidate(deps.db,c.baseProducts,c.candidateProducts); // ALL snapshots and tokens before any write.
    await verifyApprovedImages(input.bundle,deps.imageDigest);
    const affected=c.productPatches.length?await deps.db.findProductArticles(c.productPatches.map(p=>p.id)):[];
    check(Array.isArray(affected) && affected.length<=500,'affected published URL scope exceeds bound');
    const pages=new Map();
    for(const p of affected) {
      check(record(p) && typeof p.status==='string','affected article invalid');
      if(p.status!=='published')continue;
      check(typeof p.slug==='string' && /^[a-z0-9][a-z0-9-]*$/.test(p.slug)
        && typeof p.category_id==='string' && p.category_id.trim(),'affected published URL invalid');
      check(!pages.has(p.slug) || pages.get(p.slug)===p.category_id,'affected category mismatch');
      pages.set(p.slug,p.category_id);
    }
    const entry={schemaVersion:1,revision:input.revision,articleId:article.id,slug:article.slug,approval:a,
      context:c,affectedPages:[...pages].map(([slug,categoryId])=>({slug,categoryId})),
      createdAt:(deps.now||timestamp)(),status:'pending',products:[],articleEffect:'none'};
    // Persist the full approved plan before the first public write. Unknown results
    // keep both this evidence and the outer guard marker for operator reconciliation.
    await deps.journal.start(entry);
    try {
      for(const change of c.productPatches.filter(p=>pending.includes(p.id))) {
        const expected=c.baseProducts.find(p=>p.id===change.id),desired=c.candidateProducts.find(p=>p.id===change.id);
        const current=await productsBaseOrCandidate(deps.db,[expected],[desired]);
        if(!current.pending.length)continue; // Exactly approved candidate, never a stale overwrite.
        const fresh=current.rows[0];
        binding(input,deps);
        entry.products.push({id:change.id,attempted:true,verified:false,xmin:String(fresh.xmin)});
        await deps.journal.update(entry);
        const patch=Object.fromEntries(Object.entries(change.fields).map(([k,v])=>[productFields[k],v]));
        const changed=await deps.db.patchProductCAS(fresh,patch);
        check(Array.isArray(changed) && changed.length===1,'product CAS conflict');
        await productsEqual(deps.db,[c.candidateProducts.find(p=>p.id===change.id)]);
        entry.products.at(-1).verified=true;
        await deps.journal.update(entry);
      }
      await productsEqual(deps.db,c.candidateProducts);
      check((await deps.db.findArticles(article.id,article.slug)).length===0,'new article identity appeared');
      binding(input,deps);
      entry.articleEffect='insert_attempted';await deps.journal.update(entry);
      await deps.db.insertDraft(articleRow(article,input.revision));
      entry.articleEffect='publication_attempted';await deps.journal.update(entry);
      // Hold the existing outer global fence through ALL legacy DB/public/image
      // postchecks. The nested lock is deliberately a pass-through, never a new lease.
      const result=await executeNewArticle(input,{...deps,correctionLease:input.revision,lock:async fn=>fn()});
      for(const [slug,category] of pages)await deps.revalidate(slug,category);
      entry.status='complete';entry.articleEffect='verified';entry.result=result;
      await deps.journal.update(entry);
      return result;
    } catch {
      entry.status='requires_reconciliation';
      try {await deps.journal.update(entry);} catch { /* Existing pending evidence still fences replay. */ }
      // A partial product write already affects old pages. Attempt every known
      // invalidation, but never let cache recovery turn an unknown result into success.
      await Promise.allSettled([...pages].map(([slug,category])=>Promise.resolve().then(()=>deps.revalidate(slug,category))));
      throw Error('unknown: corrected product/article publication requires reconciliation');
    }
  });
}

/** The fixed helper independently reads the runtime's controlled private ledger.
 * No credentials, caller-provided executable paths or shell interpolation cross
 * this boundary. Original JSON preserves Python float fingerprints exactly.
 */
export function productionApprovalVerifier(env) {
  const root=env.CAMP_EDITORIAL_STATE_ROOT,owner=env.CAMP_EDITORIAL_OWNER_ID;
  return async (input,{rawRequest}={})=>{
    if(typeof root!=='string' || !path.isAbsolute(root) || typeof owner!=='string' || !owner.trim())return false;
    const helper=fileURLToPath(new URL('./verify_correction_approval.py',import.meta.url));
    const result=spawnSync('python3',[helper],{
      input:rawRequest??JSON.stringify(input),encoding:'utf8',timeout:10000,maxBuffer:4096,
      env:{PATH:process.env.PATH||'/usr/bin:/bin',TZ:'Asia/Tokyo',CAMP_EDITORIAL_STATE_ROOT:root,CAMP_EDITORIAL_OWNER_ID:owner},
    });
    if(result.status!==0)return false;
    try{return JSON.parse(result.stdout)?.verified===true;}catch{return false;}
  };
}

export function correctedDependencies(env,{verifyApproval,journalRoot}={}) {
  const root=journalRoot??(typeof env.CAMP_EDITORIAL_STATE_ROOT==='string' && path.isAbsolute(env.CAMP_EDITORIAL_STATE_ROOT)
    ?path.join(env.CAMP_EDITORIAL_STATE_ROOT,'catalog-corrections'):undefined);
  return {...revisionDependencies(env),verifyApproval:verifyApproval??productionApprovalVerifier(env),journal:privateCorrectionJournal(root)};
}
