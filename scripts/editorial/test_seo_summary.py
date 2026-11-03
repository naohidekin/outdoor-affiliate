"""Bounded offline summary contracts; no network, model bodies or source logs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from seo_summary import build_seo_summary, summary, JST

NOW = datetime(2026, 11, 3, 21, tzinfo=JST)


class SeoSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.seo = Path(self.tmp.name) / 'seo'
        self.editorial = Path(self.tmp.name) / 'editorial'
        (self.seo / 'reports').mkdir(parents=True)
        (self.editorial / 'usage').mkdir(parents=True)

    def report(self, day, text, suffix='astra'):
        p = self.seo / 'reports' / f'agent-campgearlab-seo-{day}-{suffix}.md'
        p.write_text(text)
        return p

    def usage(self, runs):
        (self.seo / 'usage.json').write_text(json.dumps(dict(runs=runs)))

    def run_record(self, at, kind='operations', model='gpt-6-astra'):
        return dict(startedAt=at, finishedAt=at, kind=kind, models=[dict(model=model,
            inputTokens=100, cachedInputTokens=30, outputTokens=20,
            codexCreditsEstimate=1.5, apiUsdEstimate=.02)],
            codexCreditsEstimate=1.5, actualUsd=None)

    def build(self, kind='weekly', now=NOW):
        return build_seo_summary(self.seo, self.editorial, kind, now)

    def test_scoped_weekly_latest_three_and_labeled_excerpts_only(self):
        for day in ('2026-10-27', '2026-10-28', '2026-10-30', '2026-11-01', '2026-11-03', '2026-11-04'):
            self.report(day, f'# Astra\n## 実施内容\n施策{day}\n## 判断理由\n未確定期間を避けた\n'
                '## 結果・欠測\nGA4は欠測\n## 次の作業\n確定後に確認\n## 過去実験\n99999 clicks\n')
        (self.seo / 'reports' / 'weekly-2026-11-03.md').write_text('DO NOT COPY')
        result = self.build()
        for day in ('2026-10-30', '2026-11-01', '2026-11-03'):
            self.assertIn('施策' + day, result)
        self.assertNotIn('施策2026-10-28', result)
        self.assertNotIn('施策2026-11-04', result)
        self.assertNotIn('99999', result)
        self.assertNotIn('DO NOT COPY', result)
        for label in ('実施内容', '判断理由', '結果・欠測', '次の作業'):
            self.assertIn(label, result)
        self.assertIn('2026-10-28〜2026-11-03', result)

    def test_monthly_calendar_and_aware_usage_jst_boundary(self):
        self.report('2026-10-01', '**実施内容**: 月初の確認\n**翌週方針**: 確定を待つ')
        self.report('2026-09-30', '実施内容: 前月外')
        self.report('2026-11-01', '実施内容: 当月外')
        self.usage([self.run_record('2026-09-30T15:00:00Z'),
                    self.run_record('2026-10-31T14:59:59Z'),
                    self.run_record('2026-10-31T15:00:00Z')])
        result = self.build('monthly')
        self.assertIn('2026-10-01〜2026-10-31', result)
        self.assertIn('月初の確認', result)
        self.assertNotIn('前月外', result)
        self.assertNotIn('当月外', result)
        self.assertIn('入力200', result)
        self.assertIn('credits推定3', result)

    def test_aggregates_by_kind_model_and_keeps_cost_units_distinct(self):
        self.usage([self.run_record('2026-11-01T10:00:00+09:00'),
                    self.run_record('2026-11-02T10:00:00+09:00'),
                    self.run_record('2026-11-02T10:00:00+09:00', 'implementation', 'gpt-6-sol')])
        (self.editorial / 'usage' / 'a.json').write_text(json.dumps(dict(at=NOW.isoformat(),
            calls=[dict(responseId='msg_privateid', model='claude-sonnet-4-6', input=12, output=5,
                        usage=dict(cache_read_input_tokens=3), actualUSD=None)], actualInvoiceUsd=None)))
        result = self.build()
        self.assertIn('operations / gpt-6-astra', result)
        self.assertIn('入力200', result)
        self.assertIn('implementation / gpt-6-sol', result)
        self.assertIn('編集運用・復旧 / claude-sonnet-4-6', result)
        self.assertIn('入力12', result)
        self.assertIn('キャッシュ入力3', result)
        self.assertIn('API比較推定', result)
        self.assertIn('実費ではない', result)
        self.assertIn('実請求USD: 未確認', result)
        self.assertNotIn('msg_privateid', result)

    def test_unknown_dates_missing_numbers_and_missing_roots_are_not_zero(self):
        self.usage([self.run_record(None), self.run_record('2026-11-01T10:00:00')])
        result = self.build()
        self.assertIn('期間未配分', result)
        self.assertNotIn('入力200', result)
        self.assertIn('記録なし', result)
        result = build_seo_summary(None, None, 'weekly', NOW)
        self.assertIn('記録なし', result)
        self.assertNotIn('実行なし', result)
        self.assertNotIn('実請求USD: 0', result)

    def test_invalid_files_oversized_symlinks_safe_and_output_bounded(self):
        self.report('2026-11-03', '## 実施内容\n' + 'あ' * 6000 + '\n## 判断理由\n理由')
        self.report('2026-11-02', 'x' * (128 * 1024 + 1))
        self.report('2026-99-99', '実施内容: 不正日付')
        (self.seo / 'usage.json').write_text('{bad json')
        (self.editorial / 'usage' / 'bad.json').write_text('[]')
        self.report('2026-11-01', '実施内容: /Users/person/private/key.json exp-secret-id ' + 'a' * 64 + '\n'
                    '判断理由: sourcePaths /tmp/private.log\n結果・欠測: api_key=SECRET_VALUE\n次の作業: 記録確認')
        outside = Path(self.tmp.name) / 'outside'
        outside.write_text('実施内容: SYMLINK_SECRET')
        (self.seo / 'reports' / 'agent-campgearlab-seo-2026-10-31-link.md').symlink_to(outside)
        result = self.build()
        self.assertLessEqual(len(result), 4500)
        self.assertIn('省略', result)
        for private in ('/Users/', '/tmp/', 'SECRET_VALUE', 'exp-secret-id', 'a' * 64, 'SYMLINK_SECRET'):
            self.assertNotIn(private, result)

    def test_finish_preferred_start_fallback_future_excluded_and_missing_partial(self):
        first = self.run_record('2026-10-01T12:00:00+09:00')
        first['finishedAt'] = '2026-11-01T12:00:00+09:00'
        second = self.run_record('2026-11-02T12:00:00+09:00')
        second['finishedAt'] = None
        second['models'][0].update(inputTokens=None, codexCreditsEstimate=None, apiUsdEstimate=None)
        self.usage([first, second, self.run_record('2026-11-04T00:00:00+09:00')])
        result = self.build()
        self.assertIn('入力100', result)
        self.assertIn('既知分', result)
        self.assertNotIn('入力300', result)

    def test_entry_and_usage_file_limits_and_untrusted_model_names(self):
        for i in range(40):
            self.report('2026-11-03', '実施内容: 同日の記録' + str(i), str(i))
            (self.editorial / 'usage' / f'{i:03}.json').write_text(json.dumps(dict(at=NOW.isoformat(),
                calls=[dict(model='/Users/private/model', input=1, output=2)])))
        result = self.build()
        self.assertLessEqual(len(result), 4500)
        self.assertNotIn('/Users/', result)
        self.assertIn('省略', result)
        self.assertIn('入力28', result)

    def test_usage_never_follows_sourcepaths_or_displays_provider_bodies(self):
        outside = Path(self.tmp.name) / 'raw-secret.log'
        outside.write_text('NEVER_READ_RAW_SECRET')
        run = self.run_record(NOW.isoformat())
        run['sourcePaths'] = [str(outside)]
        run['models'][0]['content'] = 'NEVER_RENDER_MODEL_BODY'
        self.usage([run])
        text = self.build()
        self.assertNotIn('NEVER_', text)
        self.assertNotIn('raw-secret', text)
        self.assertIn('入力100', text)

    def test_monthly_leap_and_year_boundary(self):
        self.report('2024-02-29', '実施内容: うるう月の確認')
        text = self.build('monthly', datetime(2024, 3, 1, 0, 1, tzinfo=JST))
        self.assertIn('2024-02-01〜2024-02-29', text)
        self.assertIn('うるう月の確認', text)
        text = self.build('monthly', datetime(2027, 1, 1, 0, 1, tzinfo=JST))
        self.assertIn('2026-12-01〜2026-12-31', text)

    def test_inline_sections_stop_at_blank_but_headed_sections_keep_paragraphs(self):
        self.report('2026-11-03', '実施内容: 当日の変更\n同じ段落の補足\n\n'
            '全実験: 87654件\nサイト全体: 98765 clicks\n\n判断理由: 確定待ち\n\n'
            '週次記事: 77777件\n判断理由: 追加確認\n全実験: 66666件\n## 結果・欠測\n第一段落\n\n第二段落も結果\n'
            '## 無関係な見出し\nEXCLUDED\n')
        text = self.build()
        for expected in ('当日の変更', '同じ段落の補足', '第一段落', '第二段落も結果'):
            self.assertIn(expected, text)
        for excluded in ('87654', '98765', '77777', '66666', 'EXCLUDED'):
            self.assertNotIn(excluded, text)

    def test_quoted_urls_including_encoded_query_are_omitted_entirely(self):
        self.report('2026-11-03', '実施内容: 確認 https://example.com/path%3Ftoken%3DENCODED_SECRET\n'
            '判断理由: https%3A%2F%2Fexample.com%2Fpath%3Fkey%3DENCODED_SECRET2\n'
            '結果: [公式](https://example.com/a?secret=PLAIN_SECRET)\n')
        text = self.build()
        for value in ('https', 'ENCODED_SECRET', 'PLAIN_SECRET', 'example.com'):
            self.assertNotIn(value, text)
        self.assertIn('URL省略', text)

    def test_monthly_twelve_dated_judgments_with_explicit_omitted_count(self):
        for i in range(1, 15):
            self.report(f'2026-10-{i:02}', f'実施内容: 作業{i:02}\n判断理由: 理由{i:02}\n結果: 結果{i:02}')
        text = self.build('monthly')
        for i in range(3, 15):
            self.assertIn(f'2026-10-{i:02}', text)
            self.assertIn(f'作業{i:02}', text)
        self.assertNotIn('作業01', text)
        self.assertIn('2件省略', text)
        self.assertLessEqual(len(text), 6000)

    def test_wrapper_slots_and_invalid_clock(self):
        text = summary(dict(seoStateRoot=str(self.seo), stateRoot=str(self.editorial)), 'weekly', NOW)
        for rule in ('月・木14時', '水曜9時', '月曜20時', '木曜20時', '毎月5日20時'):
            self.assertIn(rule, text)
        with self.assertRaises(ValueError):
            self.build('daily')
        with self.assertRaises(ValueError):
            self.build(now=NOW.replace(tzinfo=None))


if __name__ == '__main__':
    unittest.main()
