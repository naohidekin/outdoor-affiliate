import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { collectMonthly, monthPeriods } from './collect-report-metrics.mjs';

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
