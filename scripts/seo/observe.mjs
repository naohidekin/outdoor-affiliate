#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createStore } from './state.mjs';
import { articleHash, atomicJson, seoRoot } from './article-guard.mjs';
import { dateInZone, shiftDay } from './metrics.mjs';

export function observationWindow(publishedAt, day) {
  const publicationDay = dateInZone(publishedAt, 'America/Los_Angeles');
  return { startDate: shiftDay(publicationDay, 1), endDate: shiftDay(publicationDay, day),
    beforeStart: shiftDay(publicationDay, -day), beforeEnd: shiftDay(publicationDay, -1) };
}
const metric = row => row ? {clicks:row.clicks,impressions:row.impressions,ctr:row.ctr,position:row.position} : null;
const pairKey = row => JSON.stringify(row.keys);
export function compareCohort(before, after, targets, fixedPairs = []) {
  const requested = new Set(targets.map(q=>typeof q==='string'?q:q.query));
  const baseline = before.filter(row=>requested.has(row.keys[0]));
  const current = new Map(after.map(row=>[pairKey(row),row]));
  const beforeMap=new Map(before.map(row=>[pairKey(row),row]));
  const identities=fixedPairs.length?fixedPairs.map(row=>({keys:[row.query,row.device]})):baseline;
  const rows = identities.map(row=>({query:row.keys[0],device:row.keys[1],before:metric(beforeMap.get(pairKey(row))),after:metric(current.get(pairKey(row)))}));
  const eligible = rows.filter(row=>row.before?.impressions>=10 && row.after?.impressions>=10);
  const count = (field, limit) => eligible.filter(row=>row[field].position<=limit).length;
  return {definition:'Fixed baseline query/device pairs on the same page; JP web; >=10 impressions in both periods. GSC average positions, not guaranteed live ranks.',
    size:rows.length,cohortOrigin:fixedPairs.length?'approval_baseline':'comparison_period_fallback',comparable:eligible.length,missingBefore:rows.filter(row=>!row.before).length,missingAfter:rows.filter(row=>!row.after).length,
    top3:{before:count('before',3),after:count('after',3)},top1:{before:count('before',1),after:count('after',1)},rows};
}
export async function collectObservation({api,experiment,day,settledThrough,now=new Date().toISOString()}) {
  const period = observationWindow(experiment.publishedAt,day);
  if(period.endDate>settledThrough) return {status:'waiting_for_settled_data',...period,settledThrough};
  const regex = '^'+experiment.urls.canonical.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(#.*)?$';
  const query = async (startDate,endDate,dimensions,page=true) => {
    const filters=[{dimension:'country',operator:'equals',expression:'jpn'}];
    if(page) filters.push({dimension:'page',operator:'includingRegex',expression:regex});
    const result=await api.searchanalytics.query({siteUrl:'https://camp-gear-lab.com/',requestBody:{
      startDate,endDate,type:'web',dataState:'final',dimensions,rowLimit:25000,dimensionFilterGroups:[{filters}]}});
    return result.data.rows || [];
  };
  const [before,after,beforePairs,afterPairs,siteBefore,siteAfter] = await Promise.all([
    query(period.beforeStart,period.beforeEnd,[]),query(period.startDate,period.endDate,[]),
    query(period.beforeStart,period.beforeEnd,['query','device']),query(period.startDate,period.endDate,['query','device']),
    query(period.beforeStart,period.beforeEnd,[],false),query(period.startDate,period.endDate,[],false)]);
  if(!before[0] || !after[0]) return {status:'missing_metrics',...period,settledThrough};
  return {status:'ready',observation:{observationId:`${experiment.id}:day-${day}:${period.endDate}`,observedAt:now,
    source:'gsc',sourceTimezone:'America/Los_Angeles',sourceValid:true,causalityClaim:false,checkpointDay:day,
    periodStart:period.startDate,periodEnd:period.endDate,settledThrough,metrics:metric(after[0]),
    comparison:{days:day,beforeStart:period.beforeStart,beforeEnd:period.beforeEnd,beforeMetrics:metric(before[0]),
      queryCohort:compareCohort(beforePairs,afterPairs,experiment.queryTargets,experiment.baseline?.queryPageDeviceRows || []),
      siteTrend:{before:metric(siteBefore[0]),after:metric(siteAfter[0]),note:'Context only; site totals are not a randomized control.'},
      limits:['Publication PT day excluded; equal complete day windows.','GSC omits anonymized queries. Missing pairs are not zero.','Seasonality, algorithm updates and other changes prevent causal attribution.']}}};
}
export async function main(args=process.argv.slice(2)) {
  const flag = name => {const i=args.indexOf(name);return i<0?undefined:args[i+1];};
  const root=path.resolve(flag('--root') || seoRoot());
  if(flag('--env-file')) process.loadEnvFile(flag('--env-file'));
  const store=createStore({root}); const due=await store.due();
  const latest=JSON.parse(fs.readFileSync(path.join(root,'metrics/latest.json'),'utf8'));
  if(latest.current.status!=='ok' || Date.now()-Date.parse(latest.collectedAt)>48*3600000) throw new Error('Fresh valid GSC collection required');
  const {google}=await import('googleapis');
  const credentials=JSON.parse(process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS || '{}');
  const auth=new google.auth.GoogleAuth({credentials,scopes:['https://www.googleapis.com/auth/webmasters.readonly']});
  const api=google.webmasters({version:'v3',auth});
  const {createClient}=await import('@supabase/supabase-js');
  const db=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_SERVICE_ROLE_KEY);
  const outcomes=[];
  for(const checkpoint of due.due) {
    const experiment=await store.get(checkpoint.experimentId);
    const snapshot=JSON.parse(fs.readFileSync(path.join(root,'snapshots',`${experiment.id}.json`),'utf8'));
    const {data,error}=await db.from('articles').select('*').eq('id',snapshot.articleId).single();
    if(error) throw new Error(`Cannot check content drift: ${error.message}`);
    if(articleHash(data)!==articleHash(snapshot.after)) {
      if(args.includes('--write')) await store.pause(experiment.id,'Remote content changed after publication; attribution review required');
      outcomes.push({id:experiment.id,status:'content_drift'});continue;
    }
    const result=await collectObservation({api,experiment,day:checkpoint.day,settledThrough:latest.current.settledThrough});
    if(result.status==='ready' && args.includes('--write')) {
      atomicJson(path.join(root,'observations',`${result.observation.observationId.replaceAll(':','_')}.json`),result.observation);
      await store.record(experiment.id,result.observation);
    }
    outcomes.push({id:experiment.id,day:checkpoint.day,...result});
  }
  console.log(JSON.stringify(outcomes,null,2));return outcomes;
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) main().catch(e=>{console.error(e.message);process.exitCode=1;});
