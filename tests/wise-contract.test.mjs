import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadWisePolicy, passesWise, validWiseScores, requireWiseReview, wiseContentHash, findWiseProof, requireWiseBinding } from '../src/lib/wise-contract.mjs';

const scores = { w: 2, i: 2, s: 2, e: 2, ai: 3, sense: 2 };
test('default WISE root is independent of the CLI working directory', () => {
  const original = process.cwd();
  const elsewhere = fs.mkdtempSync(path.join(os.tmpdir(), 'wise-cwd-'));
  try {
    process.chdir(elsewhere);
    const policy = loadWisePolicy();
    assert.deepEqual(policy.sourceHashes, {
      'wise-master.md': '7f3a5a347bca6ffb57eccf053b2eef5a4c40c79cae8032b6ad7dcb95a4cd6144',
      'sense-master.md': '5099cf3df213c1a63f45aca9b28a1c3a858a0492fe6a4ae2c819f9f9fd85b2f8',
    });
  } finally {
    process.chdir(original);
    fs.rmSync(elsewhere, { recursive: true, force: true });
  }
});
test('all six independent owner floors fail closed including missing Sense and wrong axis', () => {
  assert.equal(passesWise(scores), true);
  for (const key of Object.keys(scores)) {
    assert.equal(passesWise({...scores, [key]: scores[key] - 1}), false);
    const missing = {...scores}; delete missing[key];
    assert.equal(validWiseScores(missing), false);
  }
  for (const value of [true, '3', NaN, Infinity, 0, 5]) assert.equal(passesWise({...scores, sense:value}), false);
  const wrong = {...scores, Science:2}; delete wrong.s;
  assert.equal(passesWise(wrong), false);
});
test('current policy and exact reviewed prose required; old proofs untouched', () => {
  const policy = loadWisePolicy();
  const text = 'synthetic prose';
  const artifact = {text, wisePolicy: policy.id, wiseContentHash: wiseContentHash(text), wiseScores:scores, wiseReviewPassed:true};
  assert.doesNotThrow(() => requireWiseReview(artifact));
  assert.equal(findWiseProof(text, [artifact]), artifact);
  for (const changed of [{...artifact, text:'changed'}, {...artifact, wisePolicy:'old'}, {...artifact, wiseScores:{...scores,sense:1}}]) {
    const before = structuredClone(changed);
    assert.throws(() => requireWiseReview(changed)); assert.deepEqual(changed,before);
  }
  assert.equal(findWiseProof('changed', [artifact]), null);
});
test('raw owner source and explanation corruption cannot be blessed by altered manifest', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'camp-wise-'));
  try {
    fs.mkdirSync(path.join(root,'rules/common'), {recursive:true});
    fs.mkdirSync(path.join(root,'docs'));
    for (const name of ['SKILL.md','docs/WISE-GEARMAN.md','docs/sense-definition.md','rules/common/wise-master.md','rules/common/sense-master.md','rules/common/wise-contract.json']) fs.copyFileSync(new URL('../'+name,import.meta.url),path.join(root,name));
    assert.equal(loadWisePolicy(root).id,loadWisePolicy().id);
    for (const [name, before, after] of [['rules/common/wise-master.md','Wit','Weight'], ['rules/common/wise-master.md','Wit','Warm'], ['rules/common/wise-master.md','Sincere','Science'], ['rules/common/wise-master.md','Sense','Missing'], ['SKILL.md','Sincere','Science']]) {
      const file = path.join(root,name); const raw = fs.readFileSync(file,'utf8');
      fs.writeFileSync(file,raw.replaceAll(before,after));
      assert.throws(() => loadWisePolicy(root)); fs.writeFileSync(file,raw);
    }
    const file = path.join(root,'rules/common/wise-contract.json'); const data = JSON.parse(fs.readFileSync(file));
    data.axes[2] = 'Science'; fs.writeFileSync(file,JSON.stringify(data));
    assert.throws(() => loadWisePolicy(root));
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
});

test('publication CLI requires a matching current six-axis review without private evidence', () => {
  const policy = loadWisePolicy(); const bundle = {wisePolicy:policy.id};
  const review = {wisePolicy:policy.id, passed:true, wiseScores:scores, fingerprint:'revision'};
  assert.doesNotThrow(() => requireWiseBinding(bundle,review,'revision'));
  for (const changed of [{...review, wisePolicy:'old'},{...review, fingerprint:'old'},{...review, wiseScores:{...scores,sense:1}},{...review,passed:false}]) assert.throws(() => requireWiseBinding(bundle,changed,'revision'));
});
