#!/usr/bin/env node
// Deterministic data collection: no LLM calls; GSC dates retain their PT basis.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { seoRoot } from './article-guard.mjs';

const SITE = 'https://camp-gear-lab.com/';
export const dateInZone = (instant, zone) => new Intl.DateTimeFormat('en-CA', {
  timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date(instant));
export function shiftDay(day, n) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) throw new Error('Invalid date');
  return new Date(Date.parse(`${day}T12:00:00Z`) + n * 86400000).toISOString().slice(0, 10);
}
function metric(row) {
  if (!row) return null;
  return { clicks: row.clicks, impressions: row.impressions, ctr: row.ctr, position: row.position };
}
export function compactQueryPages(rows) {
  const map = new Map();
  for (const row of rows) {
    const [query, page, device] = row.keys || [];
    let url;
    try { url = new URL(page); } catch { continue; }
    if (url.origin !== 'https://camp-gear-lab.com' || !url.pathname.startsWith('/articles/')) continue;
    const fragment = Boolean(url.hash); url.hash = '';
    const key = JSON.stringify([query, url.href, device]);
    const old = map.get(key);
    // GSC can report multiple jump links. Do not add their impressions together.
    if (!old || (old.fragment && !fragment) || (old.fragment === fragment && row.impressions > old.impressions)) {
      map.set(key, { query, url: url.href, device, ...metric(row), fragment });
    }
  }
  return [...map.values()].map(row => { const result={...row}; delete result.fragment; return result; });
}
export function selectCandidates(rows) {
  const groups = new Map();
  for (const row of rows) {
    if (!(row.position > 3 && row.position <= 20 && (row.impressions >= 30 || row.clicks >= 3))) continue;
    const group = groups.get(row.url) || { url: row.url, queries: [], clicks: 0, impressions: 0, priorityScore: 0 };
    group.queries.push(row); group.clicks += row.clicks; group.impressions += row.impressions;
    // Ranking heuristic only. This is neither search volume nor a probability of reaching #1.
    const proximity = row.position <= 10 ? (11 - row.position) / 8 : 0.1;
    group.priorityScore += (row.clicks + Math.sqrt(row.impressions)) * Math.max(0.1, proximity);
    groups.set(row.url, group);
  }
  return [...groups.values()].sort((a,b) => b.priorityScore - a.priorityScore).slice(0, 30)
    .map(g => ({ ...g, queries: g.queries.sort((a,b)=>b.clicks-a.clicks || b.impressions-a.impressions).slice(0, 12),
      priorityScore: +g.priorityScore.toFixed(2),
      status: 'needs_astra_serp_and_seasonality_review',
      scoreMeaning: 'screening heuristic, not predicted uplift or win probability' }));
}
/** @param {object} api @param {{startDate?:string,endDate?:string,maxPages?:number}} [options] */
export async function collectGsc(api, { startDate, endDate, maxPages = 4 } = {}) {
  const today = dateInZone(Date.now(), 'America/Los_Angeles');
  const probe = await api.searchanalytics.query({ siteUrl: SITE, requestBody: {
    startDate: shiftDay(today,-10), endDate: today, dimensions:['date'], dataState:'all', type:'web',
  }});
  const firstIncomplete = probe.data.metadata?.first_incomplete_date;
  const settledThrough = firstIncomplete ? shiftDay(firstIncomplete,-1) : shiftDay(today,-3);
  const settledSource = firstIncomplete ? 'GSC metadata' : 'conservative PT today minus 3; metadata unavailable';
  const end = endDate || settledThrough;
  if (end > settledThrough) throw new Error(`Requested end is not settled: ${end} > ${settledThrough}`);
  const start = startDate || shiftDay(end,-27);
  if (start > end || !/^\d{4}-\d{2}-\d{2}$/.test(start)) throw new Error('Invalid range');
  const base = {startDate:start,endDate:end,type:'web',dataState:'final',
    dimensionFilterGroups:[{filters:[{dimension:'country',operator:'equals',expression:'jpn'}]}]};
  const query = dimensions => api.searchanalytics.query({siteUrl:SITE,requestBody:{...base,dimensions,rowLimit:25000}});
  const [total, queries, pages] = await Promise.all([query([]),query(['query']),query(['page'])]);
  let raw = [], truncated = false;
  for (let i=0;i<maxPages;i++) {
    const res = await api.searchanalytics.query({siteUrl:SITE,requestBody:{...base,
      dimensions:['query','page','device'],rowLimit:25000,startRow:i*25000}});
    const batch = res.data.rows || []; raw.push(...batch);
    if (batch.length < 25000) break;
    if (i === maxPages-1) truncated = true;
  }
  const queryRows = queries.data.rows || [];
  const compact = compactQueryPages(raw);
  const summary = metric(total.data.rows?.[0]);
  return {source:'Google Search Console API',siteUrl:SITE,country:'jpn',searchType:'web',dateBasis:'America/Los_Angeles',
    startDate:start,endDate:end,settledThrough,settledSource,status:'ok',summary,
    coverage:{queryRows:queryRows.length,queryClicks:queryRows.reduce((s,r)=>s+r.clicks,0),
      totalClicks:summary?.clicks ?? null,queryPageRows:raw.length,paginationTruncated:truncated,
      note:'Anonymized/omitted queries and API internal limits remain; visible query rows are not all traffic. Fragment impressions are not summed.'},
    queries:queryRows.map(r=>({query:r.keys[0],...metric(r)})),
    pages:(pages.data.rows || []).filter(r=>!r.keys[0].includes('#')).map(r=>({url:r.keys[0],...metric(r)})),
    queryPages:compact,candidates:selectCandidates(compact)};
}
export async function collectGa4(google, credentials, propertyId, startDate, endDate) {
  if (!propertyId) return {status:'unavailable',reason:'GA4_PROPERTY_ID missing'};
  const auth = new google.auth.GoogleAuth({credentials,scopes:['https://www.googleapis.com/auth/analytics.readonly']});
  const api = google.analyticsdata({version:'v1beta',auth});
  try {
    const common = {property:propertyId.startsWith('properties/')?propertyId:`properties/${propertyId}`};
    const [landing, referrers] = await Promise.all([
      api.properties.runReport({...common,requestBody:{dateRanges:[{startDate,endDate}],
        dimensions:[{name:'landingPagePlusQueryString'}],metrics:[{name:'sessions'},{name:'engagedSessions'},{name:'keyEvents'}],
        dimensionFilter:{filter:{fieldName:'landingPagePlusQueryString',stringFilter:{matchType:'BEGINS_WITH',value:'/articles/'}}},limit:1000}}),
      api.properties.runReport({...common,requestBody:{dateRanges:[{startDate,endDate}],
        dimensions:[{name:'sessionSource'},{name:'landingPagePlusQueryString'}],metrics:[{name:'sessions'},{name:'keyEvents'}],
        dimensionFilter:{filter:{fieldName:'sessionSource',stringFilter:{matchType:'PARTIAL_REGEXP',value:'(chatgpt|perplexity|copilot|gemini|claude|chat\\.openai)'}}},limit:1000}}),
    ]);
    return {status:'ok',startDate,endDate,dateBasis:landing.data.metadata?.timeZone || 'property timezone unverified',
      landingPages:landing.data.rows || [],aiReferrals:referrers.data.rows || [],
      note:'AI referrals do not measure all citations or Google AI Overviews. keyEvents is not verified affiliate revenue.'};
  } catch(error) { return {status:'error',reason:error.message}; }
}
export async function main(args=process.argv.slice(2)) {
  const flag = name => {const i=args.indexOf(name);return i<0?undefined:args[i+1];};
  const root=path.resolve(flag('--root') || seoRoot());
  const env=flag('--env-file');
  if (env) process.loadEnvFile(env);
  const credentials=JSON.parse(process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS || '{}');
  if (!credentials.client_email || !credentials.private_key) throw new Error('Project Google service account credentials unavailable');
  const {google}=await import('googleapis');
  const auth=new google.auth.GoogleAuth({credentials,scopes:['https://www.googleapis.com/auth/webmasters.readonly']});
  const api=google.webmasters({version:'v3',auth});
  const current=await collectGsc(api,{startDate:flag('--start'),endDate:flag('--end')});
  const days=Math.round((Date.parse(`${current.endDate}T12:00:00Z`)-Date.parse(`${current.startDate}T12:00:00Z`))/86400000)+1;
  const previous=await collectGsc(api,{startDate:shiftDay(current.startDate,-days),endDate:shiftDay(current.startDate,-1)});
  const ga4=await collectGa4(google,credentials,process.env.GA4_PROPERTY_ID,current.startDate,current.endDate);
  const result={schemaVersion:1,collectedAt:new Date().toISOString(),operationTimezone:'Asia/Tokyo',current,previous,ga4};
  if(args.includes('--write')) {
    fs.mkdirSync(path.join(root,'metrics'),{recursive:true});
    const file=path.join(root,'metrics',`${current.startDate}_${current.endDate}.json`);
    const write=(p)=>{const tmp=`${p}.${process.pid}.tmp`;fs.writeFileSync(tmp,JSON.stringify(result,null,2)+'\n',{mode:0o600});fs.renameSync(tmp,p);};
    write(file);write(path.join(root,'metrics','latest.json'));
  }
  console.log(JSON.stringify({range:[current.startDate,current.endDate],summary:current.summary,
    previous:previous.summary,coverage:current.coverage,candidates:current.candidates.slice(0,5).map(c=>({url:c.url,score:c.priorityScore})),ga4:ga4.status},null,2));
  return result;
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) main().catch(e=>{console.error(e.message);process.exitCode=1;});
