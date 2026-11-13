/** Pure preparation only. No publication, model, network, approval registration or DB access. */
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';

export const RETRACTION_TARGETS=Object.freeze({
 '028b70f2-30ee-4451-b4c2-ba3510f3f78d':Object.freeze({slug:'insect-repellent-bracelet-ranking',product:'insect-repellent-011'}),
 '728d8163-ebda-427a-ace8-ec1494bf1261':Object.freeze({slug:'insect-repellent-gear-roundup',product:'insect-repellent-011'}),
 'article-037':Object.freeze({slug:'family-camp-safety-guide',product:'insect-repellent-011'}),
 '1dfcabdc-d52f-4fb5-aca0-6b260dc9ecd0':Object.freeze({slug:'natural-aroma-insect-repellent-camping',product:'insect-repellent-019'})
});
export const RETRACTION_PUBLIC_PATHS=Object.freeze(Object.fromEntries(Object.entries(RETRACTION_TARGETS).map(([id,t])=>[id,Object.freeze({requestedSlug:t.slug,canonicalSlug:id==='028b70f2-30ee-4451-b4c2-ba3510f3f78d'?'insect-repellent-gear-roundup':t.slug,redirectPreserved:id==='028b70f2-30ee-4451-b4c2-ba3510f3f78d',requiresOwnPublicContentMatch:id!=='028b70f2-30ee-4451-b4c2-ba3510f3f78d'})])));
const check=(v,m)=>{if(!v)throw Error(m);};
export const textHash=s=>createHash('sha256').update(s).digest('hex');
const canonical=v=>v===null?'null':Array.isArray(v)?'['+v.map(canonical).join(',')+']':typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
function assertJSON(v,seen=new Set()){
 if(v===null||typeof v==='string'||typeof v==='boolean')return;
 if(typeof v==='number'){check(Number.isFinite(v),'finite JSON numbers required');return;}
 check(typeof v==='object'&&!seen.has(v),'plain noncyclic JSON required');
 check(Array.isArray(v)||Object.getPrototypeOf(v)===Object.prototype,'plain JSON objects required');
 check(Object.getOwnPropertySymbols(v).length===0,'symbol keys forbidden');
 seen.add(v);
 if(Array.isArray(v)){check(Object.keys(v).length===v.length,'dense JSON arrays required');for(const x of v)assertJSON(x,seen);}
 else for(const key of Object.keys(v)){check(Object.getOwnPropertyDescriptor(v,key).get===undefined,'accessors forbidden');assertJSON(v[key],seen);}
 seen.delete(v);
}
export const retractionHash=v=>{assertJSON(v);return textHash(canonical(v));};
const keys=(v,ks)=>v&&typeof v==='object'&&!Array.isArray(v)&&isDeepStrictEqual(Object.keys(v).sort(),ks.slice().sort());

/** UTF-16 offsets, as used by mdast. Only closed structural nodes, never inline words. */
export function deletionUnits(content){
 check(typeof content==='string'&&content.length>0,'content required');
 const ast=unified().use(remarkParse).use(remarkGfm).parse(content),units=[];
 const add=(type,start,end)=>units.push({type,start,end,sha256:textHash(content.slice(start,end))});
 const walk=(node,parent)=>{
  const safe=['paragraph','blockquote','listItem','table'].includes(node.type) || (node.type==='tableRow'&&parent.children[0]!==node);
  // A nested paragraph excludes quote/list syntax; only its closed parent may be removed.
  if(safe && !(node.type==='paragraph'&&parent?.type!=='root'))add(node.type,node.position.start.offset,node.position.end.offset);
  for(const child of node.children||[])walk(child,node);
 };
 walk(ast,null);
 ast.children.forEach((node,i)=>{
  if(node.type!=='heading')return;
  let j=i+1;while(j<ast.children.length&&!(ast.children[j].type==='heading'&&ast.children[j].depth<=node.depth))j++;
  add('section',node.position.start.offset,ast.children[j-1].position.end.offset);
 });
 return units;
}

/** Produces an unapproved draft. Semantic review and trusted owner binding remain mandatory. */
export function prepareRetraction({baseArticle,baseHash,manifest}){
 assertJSON(baseArticle);assertJSON(manifest);
 check(baseArticle&&typeof baseArticle==='object'&&!Array.isArray(baseArticle),'base required');
 const target=RETRACTION_TARGETS[baseArticle.id];
 check(target&&baseArticle.slug===target.slug&&baseArticle.status==='published','fixed identity required');
 check(typeof baseArticle.xmin==='string'&&/^\d{1,10}$/.test(baseArticle.xmin)&&BigInt(baseArticle.xmin)<=4294967295n,'fresh xmin required');
 check(baseHash===retractionHash(baseArticle),'baseline hash changed');
 check(keys(manifest,['contentDeletions','faqDeletions','removeProductIds']),'manifest fields invalid');
 check(Array.isArray(manifest.contentDeletions)&&manifest.contentDeletions.length>0&&manifest.contentDeletions.length<=100,'content deletions required');
 check(Array.isArray(baseArticle.product_ids)&&baseArticle.product_ids.every(id=>typeof id==='string'&&id.trim().length>0)&&new Set(baseArticle.product_ids).size===baseArticle.product_ids.length&&baseArticle.product_ids.includes(target.product),'target product absent');
 check(isDeepStrictEqual(manifest.removeProductIds,[target.product]),'only target product may be removed');
 const units=deletionUnits(baseArticle.content),deletions=manifest.contentDeletions;
 let end=-1;
 for(const d of deletions){
  check(keys(d,['type','start','end','sha256'])&&units.some(u=>isDeepStrictEqual(u,d)),'not an exact closed structural unit');
  check(d.start>=end,'deletions must be ordered, unique and nonoverlapping');end=d.end;
 }
 let content=baseArticle.content;
 for(const d of deletions.slice().reverse())content=content.slice(0,d.start)+content.slice(d.end);
 check(content.trim().length>0,'empty article refused');
 check(!content.includes(target.product),'target shortcode/comparison/reference remains');
 check(Array.isArray(baseArticle.faqs)&&baseArticle.faqs.every(f=>f&&typeof f==='object'&&!Array.isArray(f)&&typeof f.question==='string'&&typeof f.answer==='string')&&Array.isArray(manifest.faqDeletions),'FAQ objects required');
 let prior=-1;const removed=new Set();
 for(const f of manifest.faqDeletions){
  check(keys(f,['index','sha256'])&&Number.isInteger(f.index)&&f.index>prior&&f.index<baseArticle.faqs.length&&f.sha256===retractionHash(baseArticle.faqs[f.index]),'FAQ deletion must match exact ordered full object');
  prior=f.index;removed.add(f.index);
 }
 const candidate=structuredClone(baseArticle);
 candidate.content=content;candidate.faqs=candidate.faqs.filter((_,i)=>!removed.has(i));candidate.product_ids=baseArticle.product_ids.filter(id=>id!==target.product);
 return {kind:'safety_retraction_v1',status:'unapproved_draft',publicPath:structuredClone(RETRACTION_PUBLIC_PATHS[baseArticle.id]),baseHash,manifest:structuredClone(manifest),candidate,candidateHash:retractionHash(candidate),requiresIndependentReview:true,requiresTrustedOwnerBinding:true};
}

export function validatePreparedRetraction(prepared,baseArticle){
 const expected=prepareRetraction({baseArticle,baseHash:prepared.baseHash,manifest:prepared.manifest});
 check(isDeepStrictEqual(prepared,expected),'prepared candidate or flags changed');
 return expected;
}
