/** Fixed-file and actual-DOM evidence for inherited presentation, never clinical certification. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';

export const TEMPLATE_FILES=['src/app/articles/[slug]/page.tsx','src/components/MedicalAdvice.tsx','src/lib/medicalAdviceData.ts'];
const directory=path.dirname(fileURLToPath(import.meta.url));
const check=ok=>{if(!ok)throw Error('inherited_template_context_changed_or_unavailable_requires_reconciliation');};
const space=text=>String(text).replace(/\s+/g,' ').trim();
export async function templateHashes(repo) {
  return Object.fromEntries(await Promise.all(TEMPLATE_FILES.map(async file=>[file,
    createHash('sha256').update(await fs.readFile(path.join(repo,file))).digest('hex')])));
}
export function adviceEvidence(html,{fullPage=false}={}) {
  check(typeof html==='string' && Buffer.byteLength(html)<=8*1024*1024);
  const result=spawnSync('python3',['-I','-B',path.join(directory,'inherited_advice.py')],{
    input:JSON.stringify({html,fullPage}),encoding:'utf8',timeout:10000,maxBuffer:65536,
    env:{PATH:process.env.PATH||'/usr/bin:/bin',TZ:'Asia/Tokyo'}});
  check(result.status===0);
  try{return JSON.parse(result.stdout);}catch{throw Error('inherited_template_context_changed_or_unavailable_requires_reconciliation');}
}
export function validatePresentation(value,slug) {
  check(value && value.schemaVersion===1 && value.kind==='unchanged_medical_advice' && value.slug===slug
    && value.clinicalReverified===false && value.unchanged===true);
  check(JSON.stringify(Object.keys(value.templateFiles||{}).sort())===JSON.stringify([...TEMPLATE_FILES].sort())
    && Object.values(value.templateFiles).every(hash=>/^[a-f0-9]{64}$/.test(hash)));
  const observed=adviceEvidence(value.html);
  check(value.domSha256===observed.domSha256 && typeof value.renderedText==='string' && space(value.renderedText)===space(observed.text));
  return value;
}
export async function captureInheritedAdvice(page,slug,files) {
  const root=page.locator('main article #article-reading-content aside[aria-label="医師からのアドバイス"]');
  check(await root.count()===1 && await root.isVisible());
  const visible=await root.evaluate(element=>({html:element.outerHTML,renderedText:element.innerText.trim()}));
  const evidence=adviceEvidence(visible.html);
  const context={schemaVersion:1,kind:'unchanged_medical_advice',slug,...visible,
    domSha256:evidence.domSha256,templateFiles:files,clinicalReverified:false,unchanged:true};
  return validatePresentation(context,slug);
}
export function assertTemplateFiles(context,files) {
  check(TEMPLATE_FILES.every(file=>files?.[file]===context.templateFiles[file]));
}
export function assertPublicAdvice(context,html) {
  const observed=adviceEvidence(html,{fullPage:true});
  check(observed.domSha256===context.domSha256 && space(observed.text)===space(context.renderedText));
}
