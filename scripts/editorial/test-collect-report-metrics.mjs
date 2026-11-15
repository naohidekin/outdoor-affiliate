import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { collectDaily, collectMonthly, monthPeriods } from './collect-report-metrics.mjs';

const now = '2026-03-05T20:00:00+09:00';
const env = { GOOGLE_CREDENTIALS: JSON.stringify({ client_email: 'test@invalid.example', private_key: 'test-key-never-output' }), GA4_PROPERTY_ID: '123' };
function deps() {
  const calls = [];
  const google = { options(value) { calls.push(['options', value]); },
    auth: { GoogleAuth: class { constructor(options) { calls.push(['auth', options.scopes]); } } },
    webmasters(options) { calls.push(['webmasters', options.version]); return {}; } };
  return { calls, google,
    async collectGsc(api, period) {
      calls.push(['gsc', period]);
      return { status: 'ok', ...period, settledThrough: '2026-03-02', dateBasis: 'America/Los_Angeles', summary: null };
    },
    async collectGa4(g, creds, property, startDate, endDate) {
      calls.push(['ga4', startDate, endDate]);
      return { status: 'ok', startDate, endDate, dateBasis: 'Asia/Tokyo', landingPages: [], aiReferrals: [] };
    } };
}

test('calendar months retain unequal lengths and JST month boundary', () => {
  assert.deepEqual(monthPeriods('2026-02', now), {
    current: { startDate: '2026-02-01', endDate: '2026-02-28' },
    previous: { startDate: '2026-01-01', endDate: '2026-01-31' } });
  assert.equal(monthPeriods('2024-02', '2024-03-01T00:00:00+09:00').current.endDate, '2024-02-29');
  assert.equal(monthPeriods('2026-12', '2026-12-31T15:00:00Z').current.endDate, '2026-12-31');
  assert.throws(() => monthPeriods('2026-03', now));
  assert.throws(() => monthPeriods('2026-13', now));
});

test('collects GSC and GA4 for both complete calendar periods without writes', async () => {
  const injected = deps();
  const result = await collectMonthly({ seoRepo: '/configured/seo', month: '2026-02', now }, env, injected);
  assert.equal(result.collectedAt, '2026-03-05T20:00:00.000+09:00');
  assert.equal(result.current.startDate, '2026-02-01');
  assert.equal(result.previous.startDate, '2026-01-01');
  assert.equal(result.ga4.endDate, '2026-02-28');
  assert.equal(result.previousGa4.endDate, '2026-01-31');
  assert.deepEqual(injected.calls.filter(c => c[0] === 'ga4').map(c => c.slice(1)), [
    ['2026-02-01', '2026-02-28'], ['2026-01-01', '2026-01-31']]);
  assert.deepEqual(injected.calls.find(c => c[0] === 'options')[1], { timeout: 45000, retry: false });
  assert.doesNotMatch(JSON.stringify(result), /test-key-never-output|test@invalid/);
});

test('unsettled GSC or wrong period fails closed', async () => {
  for (const patch of [{ settledThrough: '2026-02-27' }, { endDate: '2026-02-27' }, { status: 'error' }]) {
    const injected = deps(), original = injected.collectGsc;
    injected.collectGsc = async (...args) => ({ ...await original(...args), ...patch });
    await assert.rejects(collectMonthly({ seoRepo: '/configured/seo', month: '2026-02', now }, env, injected), /monthly_gsc_unsettled/);
  }
});

test('GA4 unknown timezone, transient error or incomplete period stays explicitly unavailable', async () => {
  for (const patch of [{ dateBasis: 'unverified' }, { status: 'error', reason: 'RAW_PRIVATE_ERROR' },
                        { endDate: '2026-02-27' }]) {
    const injected = deps(), original = injected.collectGa4;
    injected.collectGa4 = async (...args) => ({ ...await original(...args), ...patch });
    const result = await collectMonthly({ seoRepo: '/configured/seo', month: '2026-02', now }, env, injected);
    assert.equal(result.ga4.status, 'unavailable');
    assert.equal(result.previousGa4.status, 'unavailable');
    assert.doesNotMatch(JSON.stringify(result), /RAW_PRIVATE_ERROR/);
  }
  const result = await collectMonthly({ seoRepo: '/configured/seo', month: '2026-02', now: '2026-03-01T00:00:00+09:00' }, env, deps());
  assert.equal(result.ga4.status, 'unavailable');
});

test('CLI failure emits only safe fixed error with no credential reflection', () => {
  const result = spawnSync(process.execPath, ['scripts/editorial/collect-report-metrics.mjs'], {
    input: JSON.stringify({ seoRepo: '/does/not/exist', month: '2026-02', now }),
    env: { PATH: process.env.PATH, GOOGLE_CREDENTIALS: 'never-reflect-test-secret' }, encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.deepEqual(JSON.parse(result.stdout), { error: 'monthly_collection_unavailable' });
  assert.equal(result.stderr, '');
});

test('daily collection uses latest settled 28 days plus contiguous previous 28 days', async () => {
  const injected = deps();
  injected.collectGsc = async (api, period = {}) => {
    const resolved = period.startDate ? period : { startDate: '2026-10-20', endDate: '2026-11-16' };
    injected.calls.push(['gsc', resolved]);
    return { status: 'ok', ...resolved, settledThrough: '2026-11-16',
      dateBasis: 'America/Los_Angeles', summary: null };
  };
  const result = await collectDaily(
    { seoRepo: '/configured/seo', now: '2026-11-20T08:05:00+09:00' }, env, injected);
  assert.deepEqual([result.current.startDate, result.current.endDate], ['2026-10-20', '2026-11-16']);
  assert.deepEqual([result.previous.startDate, result.previous.endDate], ['2026-09-22', '2026-10-19']);
  assert.deepEqual([result.ga4.startDate, result.ga4.endDate], ['2026-10-20', '2026-11-16']);
  assert.deepEqual([result.previousGa4.startDate, result.previousGa4.endDate], ['2026-09-22', '2026-10-19']);
  assert.equal(result.collectionKind, 'daily');
  assert.deepEqual(injected.calls.find(c => c[0] === 'options')[1], { timeout: 45000, retry: false });
});

test('daily collection rejects unavailable GA4 and never reflects raw errors', async () => {
  for (const ga4 of [
    { status: 'error', reason: 'RAW_PRIVATE_ERROR' },
    { status: 'ok', dateBasis: 'not/a-zone', landingPages: [], aiReferrals: [] },
  ]) {
    const injected = deps();
    injected.collectGsc = async (api, period = {}) => ({ status: 'ok',
      ...(period.startDate ? period : { startDate: '2026-10-20', endDate: '2026-11-16' }),
      settledThrough: '2026-11-16', dateBasis: 'America/Los_Angeles', summary: null });
    injected.collectGa4 = async (g, c, p, startDate, endDate) => ({ ...ga4, startDate, endDate });
    await assert.rejects(
      collectDaily({ seoRepo: '/configured/seo', now: '2026-11-20T08:05:00+09:00' }, env, injected),
      /daily_ga4_unavailable/);
  }
});

test('daily CLI failure emits only its fixed safe error', () => {
  const result = spawnSync(process.execPath, ['scripts/editorial/collect-report-metrics.mjs'], {
    input: JSON.stringify({ kind: 'daily', seoRepo: '/does/not/exist', now }),
    env: { PATH: process.env.PATH, GOOGLE_CREDENTIALS: 'RAW_PRIVATE_ERROR' }, encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.deepEqual(JSON.parse(result.stdout), { error: 'daily_collection_unavailable' });
  assert.equal(result.stderr, '');
});

test('daily rejects valid wrong GSC timezone and mixed GA4 property timezones', async () => {
  const setup = () => {
    const injected = deps();
    injected.collectGsc = async (api, period = {}) => ({ status: 'ok',
      ...(period.startDate ? period : { startDate: '2026-10-20', endDate: '2026-11-16' }),
      settledThrough: '2026-11-16', dateBasis: 'America/Los_Angeles', summary: null });
    return injected;
  };
  const wrongGsc = setup(), originalGsc = wrongGsc.collectGsc;
  wrongGsc.collectGsc = async (...args) => ({ ...await originalGsc(...args), dateBasis: 'Asia/Tokyo' });
  await assert.rejects(collectDaily(
    { seoRepo: '/configured/seo', now: '2026-11-20T08:05:00+09:00' }, env, wrongGsc),
  /daily_gsc_unavailable/);
  const mixedGa4 = setup(); let call = 0;
  mixedGa4.collectGa4 = async (g, c, p, startDate, endDate) => ({ status: 'ok', startDate, endDate,
    dateBasis: call++ ? 'America/Los_Angeles' : 'Asia/Tokyo', landingPages: [], aiReferrals: [] });
  await assert.rejects(collectDaily(
    { seoRepo: '/configured/seo', now: '2026-11-20T08:05:00+09:00' }, env, mixedGa4),
  /daily_ga4_unavailable/);
});

test('daily rejects current GSC older than 11 PT days or behind settledThrough', async () => {
  for (const current of [
    { startDate: '2026-10-19', endDate: '2026-11-15', settledThrough: '2026-11-16' },
    { startDate: '2026-09-20', endDate: '2026-10-17', settledThrough: '2026-10-17' },
  ]) {
    const injected = deps();
    injected.collectGsc = async (api, period = {}) => ({ status: 'ok',
      ...(period.startDate ? period : current), settledThrough: period.startDate ? period.endDate : current.settledThrough,
      dateBasis: 'America/Los_Angeles', summary: null });
    await assert.rejects(collectDaily(
      { seoRepo: '/configured/seo', now: '2026-11-20T08:05:00+09:00' }, env, injected),
    /daily_gsc_unavailable/);
  }
});
