import test from 'node:test';
import assert from 'node:assert/strict';
import {observationWindow,compareCohort,collectObservation} from '../scripts/seo/observe.mjs';
test('complete PT windows exclude publication day, use equal preceding periods',()=>{
  assert.deepEqual(observationWindow('2026-09-11T09:00:00+09:00',7),{startDate:'2026-09-11',endDate:'2026-09-17',beforeStart:'2026-09-03',beforeEnd:'2026-09-09'});
});
test('fixed pairs keep missing after unknown and separate average-position thresholds',()=>{
  const before=[{keys:['tent','MOBILE'],clicks:5,impressions:100,ctr:.05,position:5},{keys:['tent','DESKTOP'],clicks:2,impressions:20,ctr:.1,position:2}];
  const result=compareCohort(before,[{...before[0],position:2}],['tent']);
  assert.deepEqual(result.top3,{before:0,after:1});assert.equal(result.missingAfter,1);assert.equal(result.rows[1].after,null);
});
test('incomplete postpublication data does not issue API requests or produce observation',async()=>{
  const result=await collectObservation({api:{},experiment:{publishedAt:'2026-09-11T09:00:00+09:00'},day:7,settledThrough:'2026-09-16'});
  assert.equal(result.status,'waiting_for_settled_data');assert.equal(result.observation,undefined);
});

test('approval cohort remains fixed when a comparison period has no rows',()=>{
 const result=compareCohort([],[],['tent'],[{query:'tent',device:'MOBILE'}]);
 assert.equal(result.size,1);assert.equal(result.missingBefore,1);assert.equal(result.missingAfter,1);assert.equal(result.comparable,0);assert.equal(result.cohortOrigin,'approval_baseline');
});
