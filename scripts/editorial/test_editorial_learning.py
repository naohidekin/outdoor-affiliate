"""Offline post-publication learning contracts; no provider or network calls."""
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import editorial_learning as learning
from editorial_learning import build_receipt, load_editorial_learnings, store_receipt, JST
from reporting import Reporter
from test_analytics import snapshot

REVISION = 'a' * 64
SOURCE = 'b' * 64
URL = 'https://camp-gear-lab.com/articles/stove'
NOW = datetime(2026, 11, 5, 20, tzinfo=JST)


def evidence(start='2026-10-01', end='2026-10-28', ga_start=None,
             gsc_basis='America/Los_Angeles', ga_basis='Asia/Tokyo'):
    return {
        'current': {'status': 'ok', 'startDate': start, 'endDate': end,
                    'dateBasis': gsc_basis, 'settledThrough': end,
                    'pages': [{'url': URL, 'clicks': 4.0, 'impressions': 80.0,
                               'ctr': .05, 'position': 7.0}]},
        'ga4': {'status': 'ok', 'startDate': ga_start or start, 'endDate': end,
                'dateBasis': ga_basis, 'coverageVerified': True,
                'landingPages': [{'path': '/articles/stove', 'sessions': 12.0,
                                  'engagedSessions': 8.0, 'keyEvents': 1.0}]},
    }


def published_job(at='2026-09-30T12:00:00+09:00'):
    return {
        'id': 'article-one', 'revision': REVISION, 'stage': 'published',
        'theme': {'nonProductContract': {'sourceReceiptSha256': SOURCE}},
        'review': {'passed': True, 'scoringVersion': 2},
        'publication': {'verified': True, 'revision': REVISION, 'at': at, 'url': URL,
                        'readback': {'verified': True, 'fingerprint': REVISION}},
        'bundle': {
            'articleReviewScoring': {'version': 2},
            'article': {'title': 'ストーブの確認手順', 'slug': 'stove',
                        'content': ('導入の非公開本文は投影しない。\n'
                                    '## 品番を確認する\n- 表示を見る\n'
                                    '## 部品を照合する\n1. 品番を控える\n'),
                        'faqs': [{'question': '確認方法は？', 'answer': '公式表示を見る。'}],
                        'generationMeta': {'editorialContext': {
                            'sourceReceiptSha256': SOURCE}}},
        },
    }


def another_job(slug, marker, at='2026-09-30T12:00:00+09:00'):
    job = published_job(at)
    revision, source = marker * 64, marker.upper() * 64
    job.update(id='article-' + slug, revision=revision)
    job['publication'].update(revision=revision,
                              url='https://camp-gear-lab.com/articles/' + slug)
    job['publication']['readback']['fingerprint'] = revision
    job['bundle']['article'].update(slug=slug, title=slug)
    job['bundle']['article']['generationMeta']['editorialContext']['sourceReceiptSha256'] = source.lower()
    return job


class SlackFake:
    def __init__(self):
        self.messages = []

    def notice(self, text):
        self.messages.append(text)
        return {'verified': True, 'message_ts': '1793700000.123456'}


class EditorialLearningTests(unittest.TestCase):
    def test_measured_receipt_binds_publication_source_and_separates_hypothesis(self):
        receipt = build_receipt('weekly', '2026-11-02', evidence(), [published_job()], NOW)
        self.assertEqual('measured_observations', receipt['status'])
        row = receipt['observations'][0]
        self.assertEqual(REVISION, row['article']['revision'])
        self.assertEqual(SOURCE, row['article']['sourceReceiptSha256'])
        self.assertEqual('page', row['measurement']['gsc']['metricScope'])
        self.assertEqual('same_dates_different_timezones_partial',
                         row['measurement']['comparability'])
        self.assertEqual('not_causally_attributed', row['measurement']['effect'])
        self.assertEqual('unverified', row['editorialHypothesis']['status'])
        self.assertEqual('gsc_page_impressions_same_period_full_revision',
                         row['samePeriodPeerRank']['basis'])
        encoded = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn('導入の非公開本文', encoded)
        self.assertNotIn('verifiedAuthorFacts', encoded)

    def test_unpublished_missing_row_and_post_period_publication_are_not_zero_reactions(self):
        unpublished = published_job()
        unpublished['publication']['verified'] = False
        missing = evidence()
        missing['current']['pages'] = []
        missing['ga4']['landingPages'] = []
        after = published_job('2026-10-31T12:00:00+09:00')
        for label, jobs, data in (('unpublished', [unpublished], evidence()),
                                  ('missing', [published_job()], missing),
                                  ('after_period', [after], evidence())):
            with self.subTest(label=label):
                receipt = build_receipt('weekly', '2026-11-02', data, jobs, NOW)
                self.assertEqual('no_measured_observations', receipt['status'])
                self.assertEqual([], receipt['observations'])
                self.assertNotIn('"impressions": 0', json.dumps(receipt))

    def test_unpublished_job_does_not_hide_measured_published_peer(self):
        unpublished = {'id': 'new-job', 'revision': None, 'publication': None,
                       'bundle': None, 'theme': {'title': '未公開'}}
        receipt = build_receipt('weekly', '2026-11-02', evidence(),
                                [unpublished, published_job()], NOW)
        self.assertEqual('measured_observations', receipt['status'])
        self.assertEqual([URL], [row['article']['url'] for row in receipt['observations']])
        encoded = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn('未公開', encoded)

    def test_period_timezone_and_overlapping_version_remain_partial_and_unattributed(self):
        data = evidence(ga_start='2026-10-02')
        receipt = build_receipt('weekly', '2026-11-02', data,
                                [published_job('2026-10-15T12:00:00+09:00')], NOW)
        row = receipt['observations'][0]
        self.assertEqual('overlap_unattributed', row['measurement']['gsc']['versionWindow'])
        self.assertEqual('overlap_unattributed', row['measurement']['ga4']['versionWindow'])
        self.assertEqual('different_periods_partial', row['measurement']['comparability'])
        self.assertTrue(row['measurement']['ga4']['coverageVerified'])
        self.assertIsNone(row['samePeriodPeerRank'])

    def test_peer_rank_is_only_full_revision_gsc_same_window_and_preserves_zero(self):
        data = evidence()
        jobs = [published_job(), another_job('zero', 'c'), another_job('missing', 'd'),
                another_job('overlap', 'e', '2026-10-15T12:00:00+09:00'),
                another_job('ga-only', 'f')]
        data['current']['pages'] += [
            {'url': 'https://camp-gear-lab.com/articles/zero', 'clicks': 0.0,
             'impressions': 0.0, 'ctr': 0.0, 'position': 0.0},
            {'url': 'https://camp-gear-lab.com/articles/missing', 'clicks': 1.0,
             'impressions': None, 'ctr': None, 'position': None},
            {'url': 'https://camp-gear-lab.com/articles/overlap', 'clicks': 20.0,
             'impressions': 999.0, 'ctr': .02, 'position': 2.0},
        ]
        data['ga4']['landingPages'].append(
            {'path': '/articles/ga-only', 'sessions': 500.0,
             'engagedSessions': 400.0, 'keyEvents': 20.0})
        receipt = build_receipt('weekly', '2026-11-02', data, jobs, NOW)
        rows = {row['article']['url'].rsplit('/', 1)[-1]: row for row in receipt['observations']}
        self.assertEqual((1, 2), (rows['stove']['samePeriodPeerRank']['rank'],
                                 rows['stove']['samePeriodPeerRank']['ofMeasuredPublishedPages']))
        self.assertEqual((2, 2), (rows['zero']['samePeriodPeerRank']['rank'],
                                 rows['zero']['samePeriodPeerRank']['ofMeasuredPublishedPages']))
        for slug in ('missing', 'overlap', 'ga-only'):
            self.assertIsNone(rows[slug]['samePeriodPeerRank'])

    def test_append_only_receipts_and_projection_require_source_and_quality_gates(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = build_receipt('weekly', '2026-11-02', evidence(), [published_job()], NOW)
            self.assertEqual('created', store_receipt(folder, receipt)['status'])
            later = build_receipt('weekly', '2026-11-02', evidence(), [published_job()],
                                  NOW.replace(hour=21))
            self.assertEqual(receipt['receiptContentSha256'], later['receiptContentSha256'])
            self.assertNotEqual(receipt['generatedAt'], later['generatedAt'])
            self.assertEqual('unchanged', store_receipt(folder, later)['status'])
            projected = load_editorial_learnings(folder)
            self.assertEqual(1, len(projected))
            self.assertIn('Never convert', projected[0]['use'])
            self.assertEqual('advisory_only', projected[0]['qualityGate']['aggregateScoreUse'])
            unsafe = copy.deepcopy(receipt)
            unsafe['metricSourceSha256'] = 'c' * 64
            unsafe['observations'][0]['qualityGate']['reviewPassed'] = False
            unsafe['observations'][0]['article']['url'] = 'https://camp-gear-lab.com/articles/other'
            unsafe['receiptContentSha256'] = learning._hash(learning._receipt_content(unsafe))
            store_receipt(folder, unsafe)
            self.assertEqual(1, len(load_editorial_learnings(folder)))

    def test_projection_reconstructs_allowlisted_fields_from_local_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = build_receipt('weekly', '2026-11-02', evidence(), [published_job()], NOW)
            row = receipt['observations'][0]
            row['verifiedAuthorFacts'] = ['must not cross']
            row['article']['privateBody'] = 'must not cross'
            row['measurement']['causalConclusion'] = 'proven'
            receipt['receiptContentSha256'] = learning._hash(learning._receipt_content(receipt))
            store_receipt(folder, receipt)
            projected = load_editorial_learnings(folder)
            encoded = json.dumps(projected)
            for forbidden in ('verifiedAuthorFacts', 'privateBody', 'causalConclusion', 'must not cross'):
                self.assertNotIn(forbidden, encoded)
            self.assertEqual('not_causally_attributed', projected[0]['measurement']['effect'])

    def test_report_hook_writes_learning_without_extra_notice_or_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seo = root / 'seo' / 'metrics'
            seo.mkdir(parents=True)
            data = snapshot()
            data['collectedAt'] = NOW.isoformat()
            (seo / 'latest.json').write_text(json.dumps(data))
            slack = SlackFake()
            config = {'stateRoot': str(root / 'private'), 'seoStateRoot': str(root / 'seo'),
                      'reportsEnabled': True}
            reporter = Reporter(config, slack)
            with patch('editorial_learning.build_receipt', wraps=build_receipt) as build:
                result = reporter.send('weekly', jobs=[published_job()], now=NOW, manual=True)
            self.assertEqual('verified', result['status'])
            self.assertEqual(1, len(slack.messages))
            build.assert_called_once()
            receipts = list((root / 'private/postpublication-learning/weekly/2026-11-02').glob('*.json'))
            self.assertEqual(1, len(receipts))
            marker = json.loads((root / 'private/reports/weekly/2026-11-02.json').read_text())
            self.assertEqual('created', marker['learning']['status'])

    def test_monthly_hook_uses_existing_collector_and_additive_learning_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = snapshot('2026-10-01', '2026-10-31')
            data['collectedAt'] = NOW.isoformat()
            data['previous'].update(startDate='2026-09-01', endDate='2026-09-30')
            slack = SlackFake()
            reporter = Reporter({'stateRoot': str(root / 'private'), 'reportsEnabled': True},
                                slack, collector=lambda *_: data)
            result = reporter.send('monthly', jobs=[published_job()], now=NOW, manual=True)
            self.assertEqual('verified', result['status'])
            self.assertEqual(1, len(slack.messages))
            receipts = list((root / 'private/postpublication-learning/monthly/2026-10').glob('*.json'))
            self.assertEqual(1, len(receipts))
            self.assertEqual('measured_observations', json.loads(receipts[0].read_text())['status'])

    def test_runtime_context_and_writer_gathering_receive_bounded_learning_wire(self):
        # Reuse the production Runtime with only in-process fakes; no provider/API exists.
        from test_runtime import RuntimeTests
        case = RuntimeTests(methodName='runTest')
        case.setUp()
        try:
            receipt = build_receipt('weekly', '2026-11-02', evidence(), [published_job()], NOW)
            store_receipt(case.runtime.root, receipt)
            context = case.runtime._context()
            self.assertEqual(1, len(context['editorialLearnings']))
            with patch.object(case.models, 'draft', wraps=case.models.draft) as draft:
                case.runtime.produce(limit=1)
            gathered = draft.call_args.args[1]
            self.assertEqual(context['editorialLearnings'], gathered['editorialLearnings'])
            self.assertNotIn('verifiedAuthorFacts', gathered['editorialLearnings'][0])
        finally:
            case.tearDown()


if __name__ == '__main__':
    unittest.main()
