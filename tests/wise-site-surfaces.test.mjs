import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {verify,verifySurface} from '../scripts/verify-wise-contract.mjs';
test('active site writers, reviewers and publishing gates use the owner raw contract',()=>{
 assert.equal(verify().passed,true);
});
test('site prompt guard rejects wrong owner axes and missing real Sense score',()=>{
 for(const text of ['W（Warm / 体温）','W — Weight','S（Science）','SincereScience']) assert.throws(()=>verifySurface('synthetic',text));
 const source=fs.readFileSync(new URL('../scripts/x/reviewer.mjs',import.meta.url),'utf8');
 assert.throws(()=>verifySurface('scripts/x/reviewer.mjs',source.replace('"sense": N','"missing": N')));
});
