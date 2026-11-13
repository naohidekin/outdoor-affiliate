"""Stage-level measured usage reporting stays bounded, local, and non-billing."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from seo_summary import JST, build_seo_summary, stage_usage_summary


NOW = datetime(2026, 11, 3, 21, tzinfo=JST)


class StageUsageSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'editorial'
        (self.root / 'usage').mkdir(parents=True)

    def usage_file(self, name, at, calls, **extra):
        payload = {'at': at, 'calls': calls, **extra}
        (self.root / 'usage' / name).write_text(json.dumps(payload))

    def test_deduplicates_response_ids_and_reports_stage_model_missing_and_zero(self):
        draft = dict(responseId='same-response', articleId='article-private', stage='draft',
                     reason='initial', requestedModel='claude-opus-4-8',
                     actualModel='claude-sonnet-4-6', model='claude-sonnet-4-6',
                     input=12, output=0, usage={}, actualUSD=None)
        self.usage_file('a.json', NOW.isoformat(), [
            draft,
            dict(responseId='missing-fields', articleId='article-private', stage='polish',
                 reason='initial', requestedModel='gemini-3.8-flash', actualModel=None,
                 model='gemini-3.8-flash', input=None, output=None, usage={}, actualUSD=None),
            dict(responseId='not-a-stage', stage='publish', actualModel='claude-sonnet-4-6',
                 input=999, output=999, actualUSD=999),
        ], actualInvoiceUsd=999)
        self.usage_file('b.json', NOW.isoformat(), [draft])

        text = stage_usage_summary(self.root, now=NOW)

        self.assertIn('既存使用量の工程別内訳', text)
        self.assertIn('draft / claude-sonnet-4-6', text)
        self.assertIn('呼出1件', text)
        self.assertIn('入力12', text)
        self.assertIn('出力0', text)
        self.assertIn('polish / 実モデル未確認', text)
        self.assertIn('入力未確認', text)
        self.assertIn('実モデル欠測1件', text)
        self.assertIn('実請求USD未確認', text)
        self.assertIn('追加費用ではありません', text)
        for absent in ('999', 'same-response', 'article-private', 'gemini-3.8-flash'):
            self.assertNotIn(absent, text)

    def test_weekly_and_monthly_use_inclusive_jst_period_boundaries(self):
        calls = lambda response: [dict(responseId=response, stage='research',
            actualModel='claude-sonnet-4-6', input=1, output=2,
            usage={'cache_read_input_tokens': 0}, actualUSD=0)]
        self.usage_file('weekly-start.json', '2026-10-28T00:00:00+09:00', calls('weekly-start'))
        self.usage_file('before-week.json', '2026-10-27T23:59:59+09:00', calls('before-week'))
        self.usage_file('future.json', '2026-11-03T21:00:01+09:00', calls('future'))
        weekly = stage_usage_summary(self.root, now=NOW)
        self.assertIn('2026-10-28〜2026-11-03', weekly)
        self.assertIn('呼出1件', weekly)
        self.assertIn('キャッシュ入力0', weekly)
        self.assertIn('実請求USD0', weekly)

        self.usage_file('month-start.json', '2026-10-01T00:00:00+09:00', calls('month-start'))
        self.usage_file('month-end.json', '2026-10-31T23:59:59+09:00', calls('month-end'))
        monthly = stage_usage_summary(self.root, kind='monthly', now=NOW)
        self.assertIn('2026-10-01〜2026-10-31', monthly)
        self.assertIn('呼出4件', monthly)

    def test_reads_only_bounded_usage_files_and_never_follows_credential_or_raw_paths(self):
        secret = Path(self.tmp.name) / 'credentials.env'
        secret.write_text('SECRET_THAT_MUST_NOT_BE_READ')
        self.usage_file('safe.json', NOW.isoformat(), [dict(
            responseId='safe', stage='social', actualModel='claude-sonnet-4-6',
            input=3, output=4, usage={}, actualUSD=None,
            sourcePaths=[str(secret)], providerBody='SECRET_THAT_MUST_NOT_BE_RENDERED')])
        (self.root / 'usage' / 'credential-link.json').symlink_to(secret)
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path == secret:
                raise AssertionError('credential file was accessed')
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', guarded_open):
            text = stage_usage_summary(self.root, now=NOW)

        self.assertIn('social / claude-sonnet-4-6', text)
        self.assertNotIn('SECRET_', text)
        self.assertLessEqual(len(text), 1600)

    def test_weekly_and_monthly_seo_summaries_include_breakdown_without_replacing_totals(self):
        seo = Path(self.tmp.name) / 'seo'
        (seo / 'reports').mkdir(parents=True)
        (seo / 'usage.json').write_text(json.dumps({'runs': []}))
        self.usage_file('stage.json', NOW.isoformat(), [dict(
            responseId='stage', stage='final_review', actualModel='claude-sonnet-4-6',
            model='claude-sonnet-4-6', input=8, output=2, usage={}, actualUSD=None)])

        weekly = build_seo_summary(seo, self.root, 'weekly', NOW)
        self.assertIn('編集運用・復旧 / claude-sonnet-4-6: 入力8', weekly)
        self.assertIn('final_review / claude-sonnet-4-6', weekly)
        self.assertIn('既存使用量の工程別内訳', weekly)

        self.usage_file('monthly.json', '2026-10-15T12:00:00+09:00', [dict(
            responseId='monthly', stage='draft', actualModel='claude-opus-4-8',
            model='claude-opus-4-8', input=5, output=1, usage={}, actualUSD=None)])
        monthly = build_seo_summary(seo, self.root, 'monthly', NOW)
        self.assertIn('編集運用・復旧 / claude-opus-4-8: 入力5', monthly)
        self.assertIn('draft / claude-opus-4-8', monthly)


if __name__ == '__main__':
    unittest.main()
