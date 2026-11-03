"""Offline contracts using the production Google collector's snapshot shape."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from analytics import Analytics, JST, build_report

NOW = datetime(2026, 11, 3, 1, tzinfo=JST)
URL = 'https://camp-gear-lab.com/articles/stove'


def snapshot(start='2026-10-01', end='2026-10-28'):
    current = dict(status='ok', siteUrl='https://camp-gear-lab.com/', country='jpn', searchType='web',
                   dateBasis='America/Los_Angeles', startDate=start, endDate=end, settledThrough='2026-10-31',
                   summary=dict(clicks=0, impressions=100, ctr=0, position=8),
                   pages=[dict(url=URL, clicks=0, impressions=100, ctr=0, position=8)],
                   queries=[dict(query='private@example.com')], queryPages=[], candidates=[])
    previous = copy.deepcopy(current)
    previous.update(startDate='2026-09-03', endDate='2026-09-30')
    ga4 = dict(status='ok', startDate=start, endDate=end, dateBasis='Asia/Tokyo',
               landingPages=[dict(dimensionValues=[dict(value='/articles/stove?email=private@example.com')],
                                  metricValues=[dict(value='0'), dict(value='0'), dict(value='0')])], aiReferrals=[])
    return dict(schemaVersion=1, collectedAt=NOW.isoformat(), current=current, previous=previous, ga4=ga4)


def load(data, now=NOW):
    with tempfile.TemporaryDirectory() as root:
        folder = Path(root) / 'metrics'
        folder.mkdir()
        (folder / 'latest.json').write_text(json.dumps(data))
        return Analytics(dict(seoStateRoot=root, analyticsRoot='/unused')).load_context(now)


class AnalyticsTests(unittest.TestCase):
    def test_real_shape_sanitized_and_matched(self):
        data = snapshot()
        data['current']['pages'][0]['url'] += '?token=secret#fragment'
        context = load(data)
        self.assertEqual(context['status'], 'ok')
        option = context['opportunities'][0]
        self.assertEqual(option['action'], 'improve_existing')
        self.assertEqual(option['url'], URL)
        self.assertEqual(option['ga4']['sessions'], 0)
        self.assertEqual(option['cannibalizationCheck'], 'required')
        text = json.dumps(context)
        for forbidden in ('private@example', 'secret', '?token', 'queries', 'fragment'):
            self.assertNotIn(forbidden, text)

    def test_missing_future_and_stale_collection(self):
        for instant in (None, (NOW + timedelta(seconds=1)).isoformat(),
                        (NOW - timedelta(hours=72, seconds=1)).isoformat(), 'invalid'):
            data = snapshot()
            data['collectedAt'] = instant
            self.assertEqual(load(data)['status'], 'unavailable')
        data['collectedAt'] = (NOW - timedelta(hours=72)).isoformat()
        self.assertEqual(load(data)['status'], 'ok')

    def test_missing_file_and_bad_json(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(Analytics(dict(seoStateRoot=root)).load_context(NOW)['status'], 'unavailable')
        self.assertEqual(load([])['status'], 'unavailable')

    def test_periods_future_unsettled_and_pt_boundary(self):
        data = snapshot()
        data['current'].update(startDate='2026-10-06', endDate='2026-11-02', settledThrough='2026-11-02')
        # It is Nov 2 in PT: that day's data is not complete, despite Nov 3 JST.
        self.assertIsNone(load(data)['evidence']['current'])
        data['current']['endDate'] = '2026-11-01'
        data['current']['settledThrough'] = '2026-11-01'
        self.assertIsNotNone(load(data)['evidence']['current'])
        data['current']['settledThrough'] = '2026-10-31'
        self.assertIsNone(load(data)['evidence']['current'])

    def test_nonfinite_missing_and_zero_not_conflated(self):
        data = snapshot()
        data['current']['summary'] = dict(clicks=0, impressions=float('inf'), ctr=float('nan'))
        summary = load(data)['evidence']['current']['summary']
        self.assertEqual(summary['clicks'], 0)
        self.assertIsNone(summary['impressions'])
        self.assertIsNone(summary['position'])
        text = build_report(data, now=NOW)['text']
        self.assertIn('前期0のため増減率なし', text)
        self.assertIn('未取得', text)
        self.assertNotIn('nan', text)

    def test_urls_drop_unsafe_and_cross_origin(self):
        for url in ('javascript:alert(1)', 'https://user:pass@example.com/articles/a',
                    'https://127.0.0.1/articles/a', 'https://evil.example/articles/a',
                    'https://camp-gear-lab.com/articles/a%0Ainjection',
                    'https://camp-gear-lab.com/articles/person%40example.com',
                    'https://camp-gear-lab.com/articles/a%3Ftoken=secret',
                    'https://camp-gear-lab.com/articles/a%253Ftoken=secret',
                    'https://camp-gear-lab.com/articles/a%23secret'):
            data = snapshot()
            data['current']['pages'][0]['url'] = url
            self.assertEqual(load(data)['opportunities'], [])

    def test_encoded_delimiters_never_cross_analytics_boundary(self):
        for encoded in ('%3Ftoken=secret', '%253Ftoken=secret', '%23secret'):
            data = snapshot()
            data['current']['pages'][0]['url'] = URL + encoded
            data['ga4']['landingPages'][0]['dimensionValues'][0]['value'] = '/articles/stove' + encoded
            data['ga4']['aiReferrals'] = [dict(
                dimensionValues=[dict(value='chatgpt.com'), dict(value='/articles/stove' + encoded)],
                metricValues=[dict(value='2'), dict(value='0')])]
            report = build_report(data, now=NOW)
            self.assertEqual(report['opportunities'], [])
            self.assertEqual(report['evidence']['ga4']['landingPages'], [])
            self.assertEqual(report['evidence']['ga4']['aiReferrals'], [])
            self.assertNotIn('secret', json.dumps(report))
        data = snapshot()
        data['current']['pages'][0]['url'] = URL + '?token=secret'
        self.assertEqual(build_report(data, now=NOW)['opportunities'][0]['url'], URL)

    def test_weekly_label_coverage_and_missing_revenue(self):
        report = build_report(snapshot(), jobs=[dict(stage='awaiting_approval'), dict(stage='social_review')], now=NOW)
        self.assertIn('直近28日', report['title'])
        self.assertIn('取得した記事入口の合計: 0', report['text'])
        self.assertIn('未接続', report['text'])
        self.assertIn('承認待ち: 記事1件・SNS1件', report['text'])
        self.assertNotIn('サイト全体セッション', report['text'])
        self.assertNotIn('/Users/', report['text'])
        self.assertIn('平均掲載順位:', report['text'])
        self.assertIn('・平均順位', report['text'])
        self.assertIn('改善案は上位モデルの審査待ち', report['text'])

    def test_monthly_requires_exact_calendar_and_compares_prior_month(self):
        rolling = build_report(snapshot(), kind='monthly', now=NOW)
        self.assertIsNone(rolling['evidence']['current'])
        self.assertEqual(rolling['opportunities'], [])
        data = snapshot(end='2026-10-31')
        data['previous'].update(startDate='2026-09-01', endDate='2026-09-30')
        data['previousGa4'] = copy.deepcopy(data['ga4'])
        data['previousGa4'].update(startDate='2026-09-01', endDate='2026-09-30')
        report = build_report(data, kind='monthly', now=NOW)
        self.assertIn('2026年10月', report['title'])
        self.assertIn('比較期間: 2026-09-01〜2026-09-30', report['text'])
        self.assertIsNotNone(report['evidence']['current'])
        self.assertIn('GA4比較は', report['text'])  # Partial article coverage cannot prove changes.

    def test_jst_month_boundary_and_leap_year(self):
        now = datetime(2024, 3, 1, 0, 1, tzinfo=JST)
        data = snapshot('2024-02-01', '2024-02-29')
        data['collectedAt'] = now.isoformat()
        data['current']['settledThrough'] = '2024-02-29'
        # Feb 29 still in progress PT: rejected even though month completed JST.
        report = build_report(data, kind='monthly', now=now)
        self.assertIn('2024年02月', report['title'])
        self.assertIsNone(report['evidence']['current'])

    def test_unknown_timezone_and_unmatched_ga4(self):
        data = snapshot()
        data['ga4']['dateBasis'] = 'property timezone unverified'
        data['ga4']['startDate'] = '2026-10-02'
        context = load(data)
        self.assertIsNone(context['opportunities'][0]['ga4'])
        self.assertIn('タイムゾーン未検証', ' '.join(context['uncertainty']))

    def test_bounded_deterministic_order_no_mutation(self):
        data = snapshot()
        data['current']['pages'] = [dict(url=URL + str(i), impressions=100, clicks=1, ctr=.01, position=8) for i in range(1500)]
        before = copy.deepcopy(data)
        first = build_report(data, now=NOW)
        self.assertEqual(first, build_report(data, now=NOW))
        self.assertEqual(data, before)
        self.assertEqual(len(first['opportunities']), 3)
        self.assertLessEqual(len(first['evidence']['current']['pages']), 30)

    def test_candidate_sample_without_page_does_not_become_site_total(self):
        data = snapshot()
        data['current']['pages'] = []
        data['current']['candidates'] = [dict(url=URL, clicks=700, impressions=9999,
            queries=[dict(query='secret person', clicks=1, impressions=40, ctr=.025, position=7)])]
        option = load(data)['opportunities'][0]
        self.assertEqual(option['gsc']['impressions'], 40)
        self.assertEqual(option['gsc']['metricScope'], 'query_page_sample')
        self.assertNotIn('secret person', json.dumps(option))

    def test_verified_monthly_ga4_comparison_and_explicit_argument(self):
        data = snapshot(end='2026-10-31')
        data['ga4']['coverage'] = dict(verified=True, complete=True, scope='site')
        old = copy.deepcopy(data['ga4'])
        old.update(startDate='2026-09-01', endDate='2026-09-30')
        data['previousGa4'] = dict(status='error')
        report = build_report(data, previous_ga4=old, kind='monthly', now=NOW)
        self.assertIn('GA4比較: 2026-09-01〜2026-09-30', report['text'])
        self.assertIn('前期0のため増減率なし', report['text'])
        self.assertEqual(report['evidence']['previousGa4']['sessions'], 0)

    def test_stale_period_missing_metrics_and_malformed_rows(self):
        data = snapshot('2026-08-01', '2026-08-28')
        self.assertIsNone(load(data)['evidence']['current'])
        data = snapshot()
        data['current']['summary'] = []
        data['ga4']['landingPages'][0]['metricValues'][2]['value'] = 'NaN'
        ga4 = load(data)['evidence']['ga4']
        self.assertEqual(ga4['sessions'], 0)
        self.assertIsNone(ga4['landingPages'][0]['keyEvents'])
        data['ga4']['landingPages'].append(None)
        self.assertEqual(load(data)['status'], 'ok')

    def test_unknown_job_status_is_not_zero(self):
        text = build_report(snapshot(), jobs=[dict(status='pending')], now=NOW)['text']
        self.assertIn('状態未確認', text)
        self.assertIn('未承認の公開なし', text)

    def test_ai_referrals_are_sanitized_not_citations(self):
        data = snapshot()
        data['ga4']['aiReferrals'] = [dict(
            dimensionValues=[dict(value='chatgpt.com'), dict(value='/articles/stove?token=secret')],
            metricValues=[dict(value='2'), dict(value='0')])]
        report = build_report(data, now=NOW)
        self.assertEqual(report['evidence']['ga4']['aiReferrals'][0]['sessions'], 2)
        self.assertNotIn('secret', json.dumps(report))
        self.assertIn('引用数・AI回答への掲載数ではありません', report['text'])

    def test_invalid_kind_and_naive_clock(self):
        with self.assertRaises(ValueError):
            build_report(snapshot(), kind='daily', now=NOW)
        with self.assertRaises(ValueError):
            load(snapshot(), NOW.replace(tzinfo=None))


if __name__ == '__main__':
    unittest.main()
