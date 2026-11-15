#!/usr/bin/env node
// Read-only monthly collector. No env files, canonical SEO writes or raw errors.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const DAY = 86400000;
const jstDay = now => new Date(new Date(now).getTime() + 9 * 3600000).toISOString().slice(0, 10);
const jstStamp = now => new Date(new Date(now).getTime() + 9 * 3600000).toISOString().replace('Z', '+09:00');
const dateInZone = (now, zone) => {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: zone,
    year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(now))
    .filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
};
const shift = (day, days) => new Date(Date.parse(day + 'T12:00:00Z') + days * DAY).toISOString().slice(0, 10);

export function monthPeriods(month, now = new Date()) {
  if (!/^\d{4}-(?:0[1-9]|1[0-2])$/.test(month || '')) throw new Error('monthly_period_invalid');
  const today = jstDay(now);
  const last = shift(today.slice(0, 7) + '-01', -1);
  if (month !== last.slice(0, 7)) throw new Error('monthly_previous_calendar_month_required');
  const start = month + '-01', previousEnd = shift(start, -1);
  return { current: { startDate: start, endDate: last },
    previous: { startDate: previousEnd.slice(0, 7) + '-01', endDate: previousEnd } };
}

function validGsc(data, period) {
  if (!data || data.status !== 'ok' || data.startDate !== period.startDate ||
      data.endDate !== period.endDate || typeof data.settledThrough !== 'string' ||
      data.settledThrough < period.endDate) throw new Error('monthly_gsc_unsettled');
  return data;
}

function safeGa4(data, period, now) {
  if (!data || data.status !== 'ok' || data.startDate !== period.startDate || data.endDate !== period.endDate)
    return { status: 'unavailable', reason: 'GA4 period data unavailable' };
  try {
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: data.dateBasis,
      year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(now));
    // GA4 has no GSC-style completeness metadata. Keep a conservative 3-day
    // lag in its verified property timezone; do not claim global coverage.
    if (data.dateBasis === undefined || period.endDate > shift(today, -3))
      throw new Error('unsettled');
  } catch {
    return { status: 'unavailable', reason: 'GA4 timezone or settled period unavailable' };
  }
  const { reason, ...safe } = data;
  return safe;
}

export async function collectMonthly({ seoRepo, month, now = new Date() }, env = process.env, injected = null) {
  const periods = monthPeriods(month, now);
  if (typeof seoRepo !== 'string' || !path.isAbsolute(seoRepo)) throw new Error('monthly_repository_required');
  let google, collectGsc, collectGa4;
  if (injected) ({ google, collectGsc, collectGa4 } = injected);
  else {
    ({ collectGsc, collectGa4 } = await import(pathToFileURL(path.join(seoRepo, 'scripts/seo/metrics.mjs')).href));
    ({ google } = createRequire(path.join(seoRepo, 'package.json'))('googleapis'));
  }
  let credentials;
  try { credentials = JSON.parse(env.INDEXING_CREDENTIALS || env.GOOGLE_CREDENTIALS || '{}'); }
  catch { throw new Error('monthly_credentials_unavailable'); }
  if (!credentials.client_email || !credentials.private_key) throw new Error('monthly_credentials_unavailable');
  google.options({ timeout: 45000, retry: false });
  const auth = new google.auth.GoogleAuth({ credentials, scopes: ['https://www.googleapis.com/auth/webmasters.readonly'] });
  const api = google.webmasters({ version: 'v3', auth });
  const [current, previous, ga4, previousGa4] = await Promise.all([
    collectGsc(api, periods.current), collectGsc(api, periods.previous),
    collectGa4(google, credentials, env.GA4_PROPERTY_ID, periods.current.startDate, periods.current.endDate),
    collectGa4(google, credentials, env.GA4_PROPERTY_ID, periods.previous.startDate, periods.previous.endDate),
  ]);
  const result = { schemaVersion: 1, collectedAt: jstStamp(now), operationTimezone: 'Asia/Tokyo',
    current: validGsc(current, periods.current), previous: validGsc(previous, periods.previous),
    ga4: safeGa4(ga4, periods.current, now), previousGa4: safeGa4(previousGa4, periods.previous, now) };
  const encoded = JSON.stringify(result);
  if (Buffer.byteLength(encoded) > 4 * 1024 * 1024 ||
      [credentials.private_key, credentials.client_email].some(secret => secret && encoded.includes(secret)))
    throw new Error('monthly_snapshot_rejected');
  return result;
}

export async function collectDaily({ seoRepo, now = new Date() }, env = process.env, injected = null) {
  if (typeof seoRepo !== 'string' || !path.isAbsolute(seoRepo)) throw new Error('daily_repository_required');
  let google, collectGsc, collectGa4;
  if (injected) ({ google, collectGsc, collectGa4 } = injected);
  else {
    ({ collectGsc, collectGa4 } = await import(pathToFileURL(path.join(seoRepo, 'scripts/seo/metrics.mjs')).href));
    ({ google } = createRequire(path.join(seoRepo, 'package.json'))('googleapis'));
  }
  let credentials;
  try { credentials = JSON.parse(env.INDEXING_CREDENTIALS || env.GOOGLE_CREDENTIALS || '{}'); }
  catch { throw new Error('daily_credentials_unavailable'); }
  if (!credentials.client_email || !credentials.private_key) throw new Error('daily_credentials_unavailable');
  google.options({ timeout: 45000, retry: false });
  const auth = new google.auth.GoogleAuth({ credentials, scopes: ['https://www.googleapis.com/auth/webmasters.readonly'] });
  const api = google.webmasters({ version: 'v3', auth });
  const current = await collectGsc(api, {});
  const ptToday = dateInZone(now, 'America/Los_Angeles');
  const currentAgeDays = Math.round((Date.parse(`${ptToday}T12:00:00Z`) -
    Date.parse(`${current?.endDate}T12:00:00Z`)) / DAY);
  if (!current || current.status !== 'ok' || typeof current.startDate !== 'string' ||
      typeof current.endDate !== 'string' || current.settledThrough !== current.endDate ||
      current.dateBasis !== 'America/Los_Angeles' ||
      currentAgeDays < 1 || currentAgeDays > 11 ||
      shift(current.startDate, 27) !== current.endDate) throw new Error('daily_gsc_unavailable');
  const previousPeriod = { startDate: shift(current.startDate, -28), endDate: shift(current.startDate, -1) };
  const [previous, rawGa4, rawPreviousGa4] = await Promise.all([
    collectGsc(api, previousPeriod),
    collectGa4(google, credentials, env.GA4_PROPERTY_ID, current.startDate, current.endDate),
    collectGa4(google, credentials, env.GA4_PROPERTY_ID, previousPeriod.startDate, previousPeriod.endDate),
  ]);
  validGsc(previous, previousPeriod);
  if (previous.dateBasis !== 'America/Los_Angeles') throw new Error('daily_gsc_unavailable');
  const ga4 = safeGa4(rawGa4, { startDate: current.startDate, endDate: current.endDate }, now);
  const previousGa4 = safeGa4(rawPreviousGa4, previousPeriod, now);
  if (ga4.status !== 'ok' || previousGa4.status !== 'ok' || ga4.dateBasis !== previousGa4.dateBasis)
    throw new Error('daily_ga4_unavailable');
  const result = { schemaVersion: 1, collectionKind: 'daily', collectedAt: jstStamp(now),
    operationTimezone: 'Asia/Tokyo', current, previous, ga4, previousGa4 };
  const encoded = JSON.stringify(result);
  if (Buffer.byteLength(encoded) > 4 * 1024 * 1024 ||
      [credentials.private_key, credentials.client_email].some(secret => secret && encoded.includes(secret)))
    throw new Error('daily_snapshot_rejected');
  return result;
}

export async function main() {
  let kind = 'monthly';
  try {
    const raw = fs.readFileSync(0, 'utf8');
    if (Buffer.byteLength(raw) > 16384) throw new Error('input');
    const input = JSON.parse(raw); kind = input?.kind === 'daily' ? 'daily' : 'monthly';
    if (!input || Object.keys(input).some(key => !['seoRepo', 'month', 'now', 'kind'].includes(key))) throw new Error('input');
    console.log(JSON.stringify(input.kind === 'daily' ? await collectDaily(input) : await collectMonthly(input)));
  } catch {
    console.log(JSON.stringify({ error: kind + '_collection_unavailable' }));
    process.exitCode = 1;
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
