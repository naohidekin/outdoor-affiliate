"""Runtime integration for the bounded existing-improvement preparation hook."""
import unittest
from unittest.mock import Mock, patch

from dispatcher import DeterministicDispatcher
from test_existing_update_preparation import (NOW, CatalogFake as SourceCatalog,
                                              analytics, article, product)
import test_runtime


class ExistingImprovementRuntimeTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.live = {'articles': [article()], 'products': [product()],
                     'categories': [], 'clicks': []}

    def tearDown(self):
        test_runtime.RuntimeTests.tearDown(self)

    def _enable(self):
        self.runtime.config['existingImprovementsEnabled'] = True

    def test_disabled_hook_does_not_read_metrics_or_full_catalog(self):
        self.runtime.analytics.load_context = Mock(
            side_effect=AssertionError('metrics must not be read'))
        self.runtime.catalog.catalog = Mock(
            side_effect=AssertionError('catalog must not be read'))
        self.assertEqual({'status': 'disabled'},
                         self.runtime._prepare_existing_improvement(NOW))

    def test_no_opportunity_is_durable_and_skips_research_on_later_ticks(self):
        self._enable()
        context = analytics()
        context['opportunities'] = []
        self.runtime.analytics.load_context = Mock(return_value=context)
        self.runtime.catalog.catalog = Mock(return_value=self.live)
        with patch('runtime.daily_metrics_due', return_value=True), \
                patch('daily_metrics.require_fresh_daily_metrics'):
            first = self.runtime._prepare_existing_improvement(NOW)
            second = self.runtime._prepare_existing_improvement(NOW)
        self.assertEqual(first, second)
        self.assertEqual('hold', first['status'])
        self.assertIn('no_eligible_growth_candidate', first['sourceHoldReasons'])
        self.runtime.analytics.load_context.assert_called_once()
        self.runtime.catalog.catalog.assert_called_once()
        self.assertEqual([], self.runtime.ledger.list_jobs())

    def test_unfresh_daily_snapshot_never_loads_analytics_or_catalog(self):
        self._enable()
        self.runtime.analytics.load_context = Mock(
            side_effect=AssertionError('analytics freshness gate must run first'))
        self.runtime.catalog.catalog = Mock(
            side_effect=AssertionError('catalog freshness gate must run first'))
        with patch('runtime.daily_metrics_due', return_value=True), \
                patch('daily_metrics.require_fresh_daily_metrics',
                      side_effect=ValueError('daily_metrics_not_fresh')):
            result = self.runtime._prepare_existing_improvement(NOW)
        self.assertEqual({'status': 'waiting_daily_metrics'}, result)
        self.assertIsNone(self.runtime.ledger.existing_improvement_receipt(
            self.runtime.ledger.production_schedule.period_key(NOW)))

    def test_queued_revision_is_visible_to_existing_dispatcher(self):
        self._enable()
        source = SourceCatalog()
        source.catalog = Mock(return_value=self.live)
        self.runtime.catalog = source
        self.runtime.analytics.load_context = Mock(return_value=analytics())
        self.runtime.config['executionPolicy'] = {
            'mode': 'deterministic', 'suspended': False,
            'exceptions': {'autoAI': False}}
        with patch('runtime.daily_metrics_due', return_value=True), \
                patch('daily_metrics.require_fresh_daily_metrics'):
            prepared = self.runtime._prepare_existing_improvement(NOW)
        self.assertEqual('queued', prepared['status'])
        plan = DeterministicDispatcher(self.runtime).plan(NOW)
        self.assertIn({'kind': 'produce_revision',
                       'jobId': prepared['revisionJobId']}, plan['actions'])
        job = self.runtime.ledger.get_job(prepared['revisionJobId'])
        self.assertEqual('candidate', job['stage'])
        self.assertIsNone(job['approval'])
        self.assertIsNone(job['publication'])

    def test_generic_target_keeps_full_revision_baseline_but_only_public_summary(self):
        self._enable()
        generic = article()
        generic.update(id='article-generic-existing', slug='generic-firepit-guide',
                       title='Generic existing guide',
                       content='PRIVATE_FULL_BASELINE_BODY_MARKER')
        target = analytics()
        target['opportunities'][0]['url'] = (
            'https://camp-gear-lab.com/articles/' + generic['slug'])
        target['opportunities'][0]['ga4']['path'] = '/articles/' + generic['slug']
        for page in target['evidence']['current']['pages']:
            if page['url'].endswith('/firepit-beginner-guide'):
                page['url'] = target['opportunities'][0]['url']
        live = {'articles': [generic], 'products': [product()],
                'categories': [], 'clicks': []}
        source = SourceCatalog()
        source.catalog = Mock(return_value=live)
        self.runtime.catalog = source
        self.runtime.analytics.load_context = Mock(return_value=target)
        with patch('runtime.daily_metrics_due', return_value=True), \
                patch('daily_metrics.require_fresh_daily_metrics'):
            prepared = self.runtime._prepare_existing_improvement(NOW)
        self.assertEqual('queued', prepared['status'])
        self.assertEqual(generic['id'], prepared['selectedId'])

        context = self.runtime._context()
        self.assertEqual([generic], context['revisionArticles'])
        summary = next(item for item in context['articles'] if item['id'] == generic['id'])
        self.assertEqual({'id', 'slug', 'title', 'categoryId', 'productIds', 'status'},
                         set(summary))
        self.assertNotIn('content', summary)
        self.assertNotIn('PRIVATE_FULL_BASELINE_BODY_MARKER', repr(context['articles']))


if __name__ == '__main__':
    unittest.main()
