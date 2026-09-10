import test from 'node:test';
import assert from 'node:assert/strict';
import {compactQueryPages,selectCandidates,dateInZone,shiftDay,collectGsc} from '../scripts/seo/metrics.mjs';
test('PT source dates are not mislabeled JST and day arithmetic crosses month',()=>{
  assert.equal(dateInZone('2026-09-11T00:00:00Z','America/Los_Angeles'),'2026-09-10');
  assert.equal(dateInZone('2026-09-11T00:00:00Z','Asia/Tokyo'),'2026-09-11');
  assert.equal(shiftDay('2026-03-01',-1),'2026-02-28');
});
test('jump links do not multiply impressions, base URL wins',()=>{
  const base='https://camp-gear-lab.com/articles/test';
  const rows=[['#one',100],['#two',100],['',120]].map(([f,n])=>({keys:['query',base+f,'MOBILE'],impressions:n,clicks:3,position:5,ctr:.03}));
  assert.equal(compactQueryPages(rows).length,1);
  assert.equal(compactQueryPages(rows)[0].impressions,120);
  assert.equal(selectCandidates(compactQueryPages(rows))[0].impressions,120);
});
test('GSC refuses incomplete range and errors propagate instead of zero',async()=>{
  const api={searchanalytics:{query:async()=>({data:{metadata:{first_incomplete_date:'2026-09-09'}}})}};
  await assert.rejects(collectGsc(api,{startDate:'2026-09-01',endDate:'2026-09-09'}),/not settled/);
  const failed={searchanalytics:{query:async()=>{throw new Error('denied');}}};
  await assert.rejects(collectGsc(failed),/denied/);
});
