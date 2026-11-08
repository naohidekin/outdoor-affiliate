/** Local Chromium DOM only: no network, API keys or public writes. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {templateHashes,captureInheritedAdvice,adviceEvidence,assertPublicAdvice,assertTemplateFiles} from './template-context.mjs';
import {childEnvironment} from './render-preview.mjs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const advice='<aside aria-label="医師からのアドバイス" class="unchanged"><h3>🩺 医師から一言：既存の注意</h3><p>安全情報は変更しません。</p><ul><li>既存の注意事項</li></ul><p>※一般的な医学情報です。症状がある場合は医療機関を受診してください。</p></aside>';
const pageHTML=html=>'<main><article><div id="article-reading-content">'+html+'</div></article></main>';

test('actual desktop/mobile inherited advice agrees and includes rendered disclaimer',async()=>{
 const browser=await chromium.launch({headless:true,env:childEnvironment(process.env.TMPDIR||'/tmp')});
 try {
  const files=await templateHashes(repo);let first;
  for(const width of [1280,390]){
   const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
   await context.route('**/*',route=>route.abort());
   const page=await context.newPage();await page.setContent(pageHTML(advice));
   const observed=await captureInheritedAdvice(page,'firepit-beginner-guide',files);
   assert.ok(observed.renderedText.includes('症状がある場合は医療機関'));
   assert.equal(observed.clinicalReverified,false);
   if(first)assert.deepEqual(observed,first);first=observed;
   assertPublicAdvice(observed,pageHTML(advice));
   assert.throws(()=>assertPublicAdvice(observed,pageHTML(advice.replace('安全情報','異なる情報'))));
   assert.throws(()=>assertTemplateFiles(observed,{...files,'src/components/MedicalAdvice.tsx':'0'.repeat(64)}));
   assertTemplateFiles(observed,files);
   await page.setContent(pageHTML(advice+advice));
   await assert.rejects(captureInheritedAdvice(page,'firepit-beginner-guide',files));
   await page.setContent(pageHTML(advice.replace('<p>安全情報','<p hidden>安全情報')));
   await assert.rejects(captureInheritedAdvice(page,'firepit-beginner-guide',files));
   await context.close();
  }
 }finally{await browser.close();}
});
test('DOM evidence cannot come from script, template or an unscoped sidebar',()=>{
 for(const html of ['<script>'+advice+'</script>','<template>'+advice+'</template>',advice])
  assert.throws(()=>adviceEvidence(html,{fullPage:true}));
 assert.equal(adviceEvidence(advice).domSha256,adviceEvidence(pageHTML(advice),{fullPage:true}).domSha256);
});

test('all three actual unchanged MedicalAdvice components retain their complete rendered text on both viewports',async()=>{
 const fs=await import('node:fs/promises'),ts=await import('typescript'),React=await import('react');
 const {renderToStaticMarkup}=await import('react-dom/server');const {createRequire}=await import('node:module');
 const require=createRequire(import.meta.url);
 async function load(relative){
  const source=await fs.readFile(path.join(repo,relative),'utf8'),exports={};
  const compiled=ts.default.transpileModule(source,{compilerOptions:{module:ts.default.ModuleKind.CommonJS,jsx:ts.default.JsxEmit.ReactJSX}}).outputText;
  new Function('require','exports',compiled)(require,exports);return exports;
 }
 const component=(await load('src/components/MedicalAdvice.tsx')).default;
 const map=(await load('src/lib/medicalAdviceData.ts')).MEDICAL_ADVICE_MAP;
 const files=await templateHashes(repo),browser=await chromium.launch({headless:true,env:childEnvironment(process.env.TMPDIR||'/tmp')});
 try{
  for(const slug of ['firepit-beginner-guide','single-burner-ranking','landlock-vs-landnest-shelter']){
   const html=renderToStaticMarkup(React.createElement(component,map[slug]));let first;
   for(const width of [1280,390]){
    const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
    await context.route('**/*',route=>route.abort());const page=await context.newPage();await page.setContent(pageHTML(html));
    const proof=await captureInheritedAdvice(page,slug,files);
    assert.ok(proof.renderedText.includes(map[slug].body));
    for(const bullet of map[slug].bullets)assert.ok(proof.renderedText.includes(bullet));
    assert.ok(proof.renderedText.includes('個別の診療行為ではありません'));
    assertPublicAdvice(proof,pageHTML(html));if(first)assert.deepEqual(proof,first);first=proof;
    await context.close();
   }
  }
 }finally{await browser.close();}
});
