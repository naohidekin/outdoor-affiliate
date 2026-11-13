import test from 'node:test';
import assert from 'node:assert/strict';
import {RETRACTION_TARGETS,deletionUnits,prepareRetraction,validatePreparedRetraction,retractionHash,textHash} from './safety-retraction.mjs';
function fixture(id=Object.keys(RETRACTION_TARGETS)[0]){
 const t=RETRACTION_TARGETS[id];
 const baseArticle={id,slug:t.slug,status:'published',xmin:'9855',title:'不変',content:`残す注意。\n\n## 推奨\n\n赤ちゃんへおすすめ。\n\n{{product:${t.product}}}\n\n## 残す\n\n使わないでください。`,faqs:[{question:'乳児は？',answer:'おすすめ'},{question:'注意？',answer:'使わない'}],product_ids:[t.product,'other'],generation_meta:{preserve:true},created_at:'2026-01-01',updated_at:'2026-11-13',published_at:'2026-02-01'};
 const span=deletionUnits(baseArticle.content).find(x=>x.type==='section'&&baseArticle.content.slice(x.start,x.end).includes('赤ちゃん'));
 return {baseArticle,baseHash:retractionHash(baseArticle),manifest:{contentDeletions:[span],faqDeletions:[{index:0,sha256:retractionHash(baseArticle.faqs[0])}],removeProductIds:[t.product]}};
}
test('all four targets produce exact deletion-only unapproved drafts, preserving unrelated fields',()=>{
 for(const id of Object.keys(RETRACTION_TARGETS)){const f=fixture(id),before=structuredClone(f),p=prepareRetraction(f);assert.deepEqual(f,before);assert.equal(p.status,'unapproved_draft');assert.equal(p.requiresIndependentReview,true);assert.equal(p.requiresTrustedOwnerBinding,true);assert.ok(p.candidate.content.includes('使わないでください'));assert.ok(!p.candidate.content.includes('赤ちゃん'));assert.deepEqual(p.candidate.product_ids,['other']);assert.deepEqual(p.candidate.faqs,[f.baseArticle.faqs[1]]);for(const k of Object.keys(f.baseArticle).filter(k=>!['content','faqs','product_ids'].includes(k)))assert.deepEqual(p.candidate[k],f.baseArticle[k]);assert.deepEqual(validatePreparedRetraction(p,f.baseArticle),p);}
});
test('wrong identity, status, version, baseline and extra keys fail',()=>{
 for(const change of [f=>f.baseArticle.id='other',f=>f.baseArticle.slug='other',f=>f.baseArticle.status='draft',f=>f.baseArticle.xmin='',f=>f.baseHash='0'.repeat(64),f=>f.manifest.extra=true]){const f=fixture();change(f);assert.throws(()=>prepareRetraction(f));}
});
test('partial words, negation, shifted offsets, altered hashes, duplicate and overlap refused',()=>{
 for(const change of [f=>{const d=f.manifest.contentDeletions[0];d.start++;d.sha256=textHash(f.baseArticle.content.slice(d.start,d.end));},f=>f.manifest.contentDeletions[0].sha256='0'.repeat(64),f=>f.manifest.contentDeletions.push(f.manifest.contentDeletions[0]),f=>f.manifest.contentDeletions.push(deletionUnits(f.baseArticle.content).find(d=>d.type==='paragraph'&&f.baseArticle.content.slice(d.start,d.end).includes('赤ちゃん')))]){const f=fixture();change(f);assert.throws(()=>prepareRetraction(f));}
 const content='使わないでください。';const units=deletionUnits(content);assert.equal(units.length,1);assert.equal(content.slice(units[0].start,units[0].end),content);
});
test('FAQ edits/reordering and other product removals forbidden',()=>{
 for(const change of [f=>f.manifest.faqDeletions[0].sha256='bad',f=>f.manifest.faqDeletions.push(f.manifest.faqDeletions[0]),f=>f.manifest.faqDeletions[0].index=-1,f=>f.manifest.removeProductIds.push('other')]){const f=fixture();change(f);assert.throws(()=>prepareRetraction(f));}
});
test('leftover target comparison prevents preparation; complete paragraph deletion can remove it',()=>{
 const f=fixture(),id=f.manifest.removeProductIds[0];f.baseArticle.content+=`\n\n{{comparison:${id},other}}`;f.baseHash=retractionHash(f.baseArticle);assert.throws(()=>prepareRetraction(f),/remains/);f.manifest.contentDeletions.push(deletionUnits(f.baseArticle.content).find(d=>d.type==='paragraph'&&f.baseArticle.content.slice(d.start,d.end).includes('comparison')));assert.ok(prepareRetraction(f));
});
test('closed quote/list/table units supported, header row and inline nodes not eligible',()=>{
 const s='> 引用段落\n\n- 一項目\n- 二項目\n\n| 商品 | 用途 |\n| --- | --- |\n| 対象 | 乳児 |\n| 他 | 成人 |';const u=deletionUnits(s);assert.ok(u.some(x=>x.type==='blockquote'));assert.ok(u.some(x=>x.type==='listItem'));assert.equal(u.filter(x=>x.type==='tableRow').length,2);assert.ok(!u.some(x=>x.type==='text'));assert.ok(!u.some(x=>x.type==='paragraph'&&s.slice(x.start,x.end)==='引用段落'));
});
test('tampered candidate, flags or additional fields cannot pass deterministic readback',()=>{
 for(const mutate of [p=>p.candidate.title='書換え',p=>p.candidate.content+='追加',p=>p.candidate.faqs.reverse(),p=>p.requiresIndependentReview=false,p=>p.approval={accepted:true}]){const f=fixture(),p=prepareRetraction(f);if(mutate.toString().includes('reverse'))p.candidate.faqs.push({question:'追加',answer:'追加'});mutate(p);assert.throws(()=>validatePreparedRetraction(p,f.baseArticle));}
});

test('bracelet alias remains redirected and does not claim own public content match',()=>{
 const f=fixture(),p=prepareRetraction(f);assert.equal(p.publicPath.canonicalSlug,'insect-repellent-gear-roundup');assert.equal(p.publicPath.redirectPreserved,true);assert.equal(p.publicPath.requiresOwnPublicContentMatch,false);p.publicPath.canonicalSlug=f.baseArticle.slug;assert.throws(()=>validatePreparedRetraction(p,f.baseArticle));
 const q=prepareRetraction(fixture('article-037'));assert.equal(q.publicPath.requiresOwnPublicContentMatch,true);
});

test('candidate nested objects never alias baseline',()=>{
 const f=fixture(),before=structuredClone(f.baseArticle),p=prepareRetraction(f);p.candidate.faqs[0].answer='changed';p.candidate.generation_meta.preserve=false;assert.deepEqual(f.baseArticle,before);
});
test('non JSON, coercible xmin, malformed products and FAQ fail closed',()=>{
 for(const change of [f=>f.baseArticle.xmin=['9855'],f=>f.baseArticle.xmin=9855,f=>f.baseArticle.product_ids.push(1),f=>f.baseArticle.faqs.push(null),f=>f.baseArticle.faqs[1].answer=123]){const f=fixture();change(f);f.baseHash=retractionHash(f.baseArticle);assert.throws(()=>prepareRetraction(f));}
 for(const value of [NaN,Infinity,undefined,()=>{},new Date(),[,1],{x:undefined}])assert.throws(()=>retractionHash(value));
 const cyclic={};cyclic.self=cyclic;assert.throws(()=>retractionHash(cyclic));
});
