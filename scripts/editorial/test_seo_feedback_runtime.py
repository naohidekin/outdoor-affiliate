"""Offline runtime/report integration; no model or external-service calls."""
import json
import copy
from unittest.mock import Mock
import unittest

from analytics import _context
from test_analytics import snapshot, NOW
import test_runtime
from seo_feedback import build_feedback
from test_seo_feedback import (NOW as FEEDBACK_NOW, OWNER,
                               analytics as feedback_analytics, job, receipts)


class SeoFeedbackRuntimeTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown

    def prepare(self):
        root = self.runtime.root / 'metrics-source'
        (root / 'metrics').mkdir(parents=True)
        self.runtime.config['seoStateRoot'] = str(root)
        value = snapshot()
        (root / 'metrics' / 'latest.json').write_text(json.dumps(value))
        context = _context(value, NOW)
        self.runtime.analytics.load_context = Mock(return_value=context)
        return context

    def test_refresh_is_program_only_and_unchanged_evidence_is_not_rewritten(self):
        context = self.prepare()
        self.models.draft = Mock(side_effect=AssertionError('no model calls'))
        self.models.research = Mock(side_effect=AssertionError('no model calls'))
        first = self.runtime._refresh_seo_feedback([], context, NOW)
        path = self.runtime.root / 'seo-feedback' / 'latest.json'
        original = path.read_bytes()
        stat = path.stat().st_mtime_ns
        later = NOW.replace(minute=5)
        second = self.runtime._refresh_seo_feedback([], context, later)
        self.assertEqual(first['semanticSha256'], second['semanticSha256'])
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(stat, path.stat().st_mtime_ns)
        report = json.loads((self.runtime.root / 'analytics/seo/latest.json').read_text())
        self.assertIn('GSC:', report['text'])
        self.assertEqual(context['collectedAt'], report['collectedAt'])
        self.assertNotIn('private@example', json.dumps(report))
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)

    def test_feedback_handoff_preserves_explicit_waiting_and_no_causal_claim(self):
        context = self.prepare()
        self.runtime._refresh_seo_feedback([], context, NOW)
        handed = self.runtime._analytics_context()
        self.assertEqual([], handed['priorPublicationFeedback']['rows'])
        self.assertFalse(handed['priorPublicationFeedback']['causalAttribution'])
        self.assertEqual(context['evidence'], handed['evidence'])
        self.assertEqual([], self.runtime.ledger.list_jobs())

    def test_owner_report_uses_current_jobs_without_counting_failed_quality(self):
        context = self.prepare()
        ready = dict(id='ready', stage='review', revision='ready-revision',
                     approval=None, publication=None, astraReview={
                         'passed': True, 'issues': [], 'reviewedBy': 'Astra',
                         'evidence': {'independentReview': True},
                         'fingerprint': 'ready-revision'})
        failed = dict(id='failed', stage='review', revision='failed-revision',
                      approval=None, publication=None, astraReview=None)

        self.runtime._refresh_seo_feedback([ready, failed], context, NOW)
        report = json.loads((self.runtime.root / 'analytics/seo/latest.json').read_text())

        self.assertIn('品質確認済み・本人承認前: 記事1件・SNS0件', report['text'])
        self.assertNotIn('記事2件', report['text'])

    def test_large_analysis_export_keeps_selected_evidence_without_losing_canonical_context(self):
        context = self.prepare()
        context['evidence']['current']['searchDemand'] = {
            'status': 'available', 'groups': [{'fixture': 'x' * 70000}],
            'coverage': {'marketDemand': False}}
        original = copy.deepcopy(context)
        handed = self.runtime._analytics_context()
        source = self.runtime.root / 'metrics-source/editorial-insights/latest.json'
        exported = json.loads(source.read_text())
        self.assertEqual('ok', exported['status'])
        self.assertEqual('selected_improvement_urls_only', exported['evidenceProjection'])
        self.assertEqual(original['opportunities'], exported['opportunities'])
        self.assertEqual(original, handed)
        self.assertLessEqual(len(source.read_bytes()), 65536)
        self.assertEqual([], exported['evidence']['current']['searchDemand']['groups'])

    @staticmethod
    def _published(index):
        value = job()
        url = 'https://camp-gear-lab.com/articles/target-' + str(index)
        value['id'] = 'revision-' + str(index).zfill(2)
        value['theme']['slug'] = 'target-' + str(index)
        value['publication']['url'] = url
        value['revisionContext']['baseArticle']['slug'] = 'target-' + str(index)
        value['revisionContext']['analysisBinding']['targetUrl'] = url
        return value

    def test_eleventh_published_target_outside_legacy_projection_is_measured(self):
        jobs = [self._published(index) for index in range(11)]
        for value in jobs:
            _, index_key = receipts(self.runtime.root, value)
            index_path = self.runtime.root / 'index-tracking' / (index_key + '.json')
            index_receipt = json.loads(index_path.read_text())
            index_receipt['url'] = value['publication']['url']
            index_path.write_text(json.dumps(index_receipt))
        projected = feedback_analytics()
        leaders = [{"url": 'https://camp-gear-lab.com/articles/leader-' + str(index),
                    "clicks": 10, "impressions": 1000 - index,
                    "ctr": .01, "position": 3.0} for index in range(30)]
        projected['evidence']['current']['pages'] = copy.deepcopy(leaders)
        projected['evidence']['previous']['pages'] = copy.deepcopy(leaders)
        raw = {'schemaVersion': 1, 'collectedAt': projected['collectedAt'],
               'current': copy.deepcopy(projected['evidence']['current']),
               'previous': copy.deepcopy(projected['evidence']['previous'])}
        target = jobs[-1]['publication']['url']
        raw['current']['pages'].append(
            {'url': target, 'clicks': 5, 'impressions': 125, 'ctr': .04, 'position': 7.0})
        raw['previous']['pages'].append(
            {'url': target, 'clicks': 2, 'impressions': 100, 'ctr': .02, 'position': 7.0})

        feedback = build_feedback(jobs, self.runtime.root, projected, FEEDBACK_NOW,
                                  owner_id=OWNER, metrics_snapshot=raw)

        self.assertEqual(10, len(feedback['rows']))
        self.assertTrue(all(row['status'] == 'waiting' for row in feedback['rows']))
        self.assertEqual('revision-10', feedback['planningRows'][0]['jobId'])
        self.assertEqual('postchange_performance_measured',
                         feedback['planningRows'][0]['status'])

    def test_three_waiting_report_rows_do_not_hide_measured_planning_row(self):
        waiting = [{'jobId': 'waiting-' + str(index), 'revision': 'a' * 64,
                    'targetUrl': 'https://camp-gear-lab.com/articles/waiting-' + str(index),
                    'status': 'waiting', 'reason': 'page_measurement_missing',
                    'workflow': {'status': 'publication_observed'},
                    'measurement': {'status': 'waiting'}, 'sourceEvidence': {}}
                   for index in range(3)]
        measured = {'jobId': 'measured', 'revision': 'b' * 64,
                    'targetUrl': 'https://camp-gear-lab.com/articles/measured',
                    'status': 'postchange_performance_measured',
                    'reason': 'complete_nonoverlapping_page_periods',
                    'workflow': {'status': 'reanalysis_observed'},
                    'measurement': {'status': 'measured_postchange_performance',
                                    'effect': 'not_causally_attributed'},
                    'sourceEvidence': {}}
        path = self.runtime.root / 'seo-feedback/latest.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'summary': {}, 'rows': waiting + [measured],
                                    'planningRows': [measured]}))
        self.prepare()

        handed = self.runtime._analytics_context()

        self.assertEqual(['measured'], [row['jobId'] for row in
                                        handed['priorPublicationFeedback']['rows']])
        self.assertFalse(handed['priorPublicationFeedback']['causalAttribution'])


if __name__ == '__main__':
    unittest.main()
