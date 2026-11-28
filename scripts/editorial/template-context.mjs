/** Fixed-file and actual-DOM evidence for inherited presentation, never clinical certification. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import ts from 'typescript';

export const TEMPLATE_FILES=['src/app/articles/[slug]/page.tsx','src/components/MedicalAdvice.tsx','src/lib/medicalAdviceData.ts'];
export const ADVICE_SELECTOR='main article #article-reading-content aside[aria-label="医師からのアドバイス"]';
const MEDICAL_MAP_FILE='src/lib/medicalAdviceData.ts';
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
function adviceState(html,{fullPage=false}={}) {
  check(typeof html==='string' && Buffer.byteLength(html)<=8*1024*1024);
  const result=spawnSync('python3',['-I','-B',path.join(directory,'inherited_advice.py')],{
    input:JSON.stringify({html,fullPage,allowAbsent:true}),encoding:'utf8',timeout:10000,maxBuffer:65536,
    env:{PATH:process.env.PATH||'/usr/bin:/bin',TZ:'Asia/Tokyo'}});
  check(result.status===0);
  try {
    const value=JSON.parse(result.stdout);
    check(value && (value.matchCount===0 || value.matchCount===1));
    return value;
  } catch { throw Error('inherited_template_context_changed_or_unavailable_requires_reconciliation'); }
}
function literal(node) {
  if(ts.isStringLiteral(node)||ts.isNumericLiteral(node)||node.kind===ts.SyntaxKind.TrueKeyword
      ||node.kind===ts.SyntaxKind.FalseKeyword||node.kind===ts.SyntaxKind.NullKeyword)return true;
  if(ts.isPrefixUnaryExpression(node))return [ts.SyntaxKind.PlusToken,ts.SyntaxKind.MinusToken].includes(node.operator)
    &&ts.isNumericLiteral(node.operand);
  if(ts.isArrayLiteralExpression(node))return node.elements.every(item=>!ts.isSpreadElement(item)&&literal(item));
  if(ts.isObjectLiteralExpression(node))return node.properties.every(property=>
    ts.isPropertyAssignment(property)&&!property.name?.questionToken
    &&(ts.isIdentifier(property.name)||ts.isStringLiteral(property.name)||ts.isNumericLiteral(property.name))
    &&literal(property.initializer));
  return false;
}
export function staticMedicalAdviceSlugs(source) {
  check(typeof source==='string' && Buffer.byteLength(source)<=1024*1024);
  const file=ts.createSourceFile(MEDICAL_MAP_FILE,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
  const declarations=[];let references=0;
  const count=node=>{if(ts.isIdentifier(node)&&node.text==='MEDICAL_ADVICE_MAP')references++;
    ts.forEachChild(node,count);};
  count(file);
  for(const statement of file.statements) {
    if(!ts.isVariableStatement(statement))continue;
    for(const declaration of statement.declarationList.declarations)
      if(ts.isIdentifier(declaration.name)&&declaration.name.text==='MEDICAL_ADVICE_MAP')
        declarations.push({declaration,statement});
  }
  check(declarations.length===1&&references===1);
  const {declaration,statement}=declarations[0];
  check((statement.modifiers||[]).some(modifier=>modifier.kind===ts.SyntaxKind.ExportKeyword)
    &&(statement.declarationList.flags&ts.NodeFlags.Const)!==0);
  const map=declaration.initializer;
  check(ts.isObjectLiteralExpression(map)&&literal(map));
  const slugs=map.properties.map(property=>ts.isStringLiteral(property.name)?property.name.text:null);
  check(slugs.every(Boolean)&&new Set(slugs).size===slugs.length);
  return slugs;
}
export async function medicalAdviceKind(repo,slug) {
  check(typeof slug==='string'&&slug);
  const source=await fs.readFile(path.join(repo,MEDICAL_MAP_FILE),'utf8');
  return staticMedicalAdviceSlugs(source).includes(slug)?'unchanged_medical_advice':'no_inherited_medical_advice';
}
export function validatePresentation(value,slug) {
  check(value && value.schemaVersion===1 && value.slug===slug
    && value.clinicalReverified===false && value.unchanged===true);
  check(JSON.stringify(Object.keys(value.templateFiles||{}).sort())===JSON.stringify([...TEMPLATE_FILES].sort())
    && Object.values(value.templateFiles).every(hash=>/^[a-f0-9]{64}$/.test(hash)));
  if(value.kind==='unchanged_medical_advice') {
    check(JSON.stringify(Object.keys(value).sort())===JSON.stringify([
      'schemaVersion','kind','slug','html','domSha256','renderedText','templateFiles','clinicalReverified','unchanged'].sort()));
    const observed=adviceEvidence(value.html);
    check(value.domSha256===observed.domSha256 && typeof value.renderedText==='string'
      &&space(value.renderedText)===space(observed.text));
  } else {
    check(value.kind==='no_inherited_medical_advice'
      &&JSON.stringify(Object.keys(value).sort())===JSON.stringify([
        'schemaVersion','kind','slug','selector','matchCount','medicalAdviceMapStatus','medicalAdviceMapSha256',
        'templateFiles','clinicalReverified','unchanged'].sort())
      &&value.selector===ADVICE_SELECTOR&&value.matchCount===0
      &&value.medicalAdviceMapStatus==='slug_absent_from_static_literal_map'
      &&value.medicalAdviceMapSha256===value.templateFiles[MEDICAL_MAP_FILE]);
  }
  return value;
}
export async function captureInheritedAdvice(page,slug,files,expectedKind='unchanged_medical_advice') {
  check(expectedKind==='unchanged_medical_advice'||expectedKind==='no_inherited_medical_advice');
  const root=page.locator(ADVICE_SELECTOR),count=await root.count();
  if(expectedKind==='no_inherited_medical_advice') {
    check(count===0);
    return validatePresentation({schemaVersion:1,kind:expectedKind,slug,selector:ADVICE_SELECTOR,matchCount:0,
      medicalAdviceMapStatus:'slug_absent_from_static_literal_map',medicalAdviceMapSha256:files[MEDICAL_MAP_FILE],
      templateFiles:files,clinicalReverified:false,unchanged:true},slug);
  }
  check(count===1 && await root.isVisible());
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
  validatePresentation(context,context.slug);
  const observed=adviceState(html,{fullPage:true});
  if(context.kind==='no_inherited_medical_advice')check(observed.matchCount===0);
  else check(observed.matchCount===1&&observed.domSha256===context.domSha256
    &&space(observed.text)===space(context.renderedText));
}
