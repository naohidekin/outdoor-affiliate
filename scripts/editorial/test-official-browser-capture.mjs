import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {captureR1,R1_URL} from './official_browser_capture.mjs';

function tab(html, {url=R1_URL,changed=false,truncated=false}={}) {
  let urls=0, reads=0;
  return {get reads(){return reads;},url:async()=>changed&&++urls>1?'https://example.com/':url,
    playwright:{evaluate:async(_,arg)=>{
      reads++; if(!arg)return html.length;
      const result=html.slice(arg.offset,arg.offset+80000);
      return truncated?result.slice(1):result;
    }}};
}
test('finite stable DOM export preserves bytes and provenance without navigation',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'r1-capture-'));
  try {
    const html='<html>'+ '実DOM'.repeat(40000)+'</html>',source=tab(html);
    const r=await captureR1(source,dir);
    assert.equal(await readFile(r.path,'utf8'),html);
    assert.equal(r.domBytes,Buffer.byteLength(html));
    assert.match(r.domSHA256,/^[a-f0-9]{64}$/);
    assert.equal(r.captureCount,1);assert.equal(r.identicalPasses,true);
    assert.ok(source.reads<=3+2*Math.ceil(html.length/80000));
  } finally {await rm(dir,{recursive:true,force:true});}
});
test('wrong URL, changed final URL, truncation and oversized DOM hold without retry',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'r1-capture-'));
  try {
    for(const source of [tab('<html/>',{url:R1_URL+'?x=1'}),tab('<html/>',{changed:true}),
      tab('<html/>',{truncated:true}),tab('x'.repeat(3*1024*1024+1))])
      await assert.rejects(captureR1(source,dir));
  } finally {await rm(dir,{recursive:true,force:true});}
});

test('DOM growth on an exact chunk boundary cannot produce a complete receipt',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'r1-capture-'));
  try {
    const original='x'.repeat(80000),grown=original+'<p>new</p>';let reads=0;
    const source={url:async()=>R1_URL,playwright:{evaluate:async(_,arg)=>{
      if(arg)return grown.slice(arg.offset,arg.offset+80000);
      return ++reads===1?original.length:grown.length;
    }}};
    await assert.rejects(captureR1(source,dir));
    await assert.rejects(readFile(join(dir,'40275-browser-receipt.json')));
  } finally {await rm(dir,{recursive:true,force:true});}
});
