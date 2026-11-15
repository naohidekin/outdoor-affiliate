"""Real budget integration with synthetic providers; no service calls."""
import copy
import unittest
from unittest.mock import patch
import test_runtime
from models import Models
from test_models import Fake, response, THEMES
from runtime import Runtime


class RuntimeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_runtime.RuntimeTests('runTest')
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_measured_calls_share_article_budget_across_input_changes(self):
        f = self.fixture
        f.config['modelBudget'] = {'article': {'calls': 1, 'inputTokens': 2000000,
            'outputTokens': 262144}}
        fake = Fake(response(THEMES), response(THEMES))
        models = Models({'ANTHROPIC_API_KEY': 'test-only'}, request=fake)
        runtime = Runtime(f.config, models=models, catalog=f.runtime.catalog, slack=f.slack,
                          renderer=f.runtime.renderer, publisher=f.runtime.publisher)
        runtime._measured_model_call('article-test', 'research', 'test',
                                     lambda: models.research({'source': 'first'}))
        with self.assertRaisesRegex(Exception, 'model_budget_hold'):
            runtime._measured_model_call('article-test', 'research', 'test',
                                         lambda: models.research({'source': 'changed'}))
        self.assertEqual(1, len(fake.calls))
        self.assertEqual([], f.writes)

    def test_default_models_are_budgeted_and_stop_never_sends_notices(self):
        f = self.fixture
        f.config['executionPolicy'] = {'mode': 'deterministic', 'suspended': True,
                                      'exceptions': {'autoAI': False}}
        runtime = Runtime(f.config, catalog=f.runtime.catalog, slack=f.slack)
        self.assertIs(runtime.model_budget, runtime.models.budget)
        with self.assertRaisesRegex(ValueError, 'execution_suspended'):
            runtime._measured_model_call('article-test', 'draft', 'test', lambda: None)
        self.assertEqual([], f.slack.notices)

    def test_cached_stage_does_not_reserve_another_call(self):
        f = self.fixture
        f.config['modelBudget'] = {'article': {'calls': 1}}
        fake = Fake(response(THEMES))
        models = Models({'ANTHROPIC_API_KEY': 'test-only'}, request=fake)
        runtime = Runtime(f.config, models=models, catalog=f.runtime.catalog, slack=f.slack)
        inputs = {'content': 'verified', 'dependencies': {}, 'schemaVersion': 1}
        operation = lambda: models.research({'same': 'input'})
        first = runtime._run_model_stage({'id': 'article-cache'}, 'draft', inputs, operation, 'test')
        second = runtime._run_model_stage({'id': 'article-cache'}, 'draft', inputs, operation, 'test')
        self.assertEqual(first, second)
        self.assertEqual(1, len(fake.calls))

    def test_budget_notice_unknown_delivery_is_not_resent(self):
        f = self.fixture
        f.config['modelBudget'] = {'article': {'calls': 1}}
        fake = Fake(response(THEMES))
        models = Models({'ANTHROPIC_API_KEY': 'test-only'}, request=fake)
        runtime = Runtime(f.config, models=models, catalog=f.runtime.catalog, slack=f.slack)
        runtime._measured_model_call('article-limit', 'draft', 'test', lambda: models.research({}))
        with self.assertRaisesRegex(Exception, 'model_budget_hold'):
            runtime._measured_model_call('article-limit', 'draft', 'test', lambda: models.research({}))
        before = list(f.slack.notices)
        self.assertTrue(any('工程保留' in text for text in before))
        runtime._flush_budget_notifications()
        self.assertEqual(before, f.slack.notices)
        self.assertEqual([], f.writes)

    def test_new_revision_jobs_of_same_url_share_article_budget(self):
        runtime = self.fixture.runtime
        with runtime.ledger._tx() as db:
            runtime.ledger._put(db, {'id': 'article-original', 'theme': {'slug': 'same-url'}, 'publication': {'verified': True}, 'stage': 'published'}, 'fixture')
            runtime.ledger._put(db, {'id': 'revision-new', 'kind': 'article_revision', 'theme': {'slug': 'same-url'},
                'revisionContext': {'baseArticle': {'slug': 'same-url'}}}, 'fixture')
        self.assertEqual(runtime._budget_article_id('article-original'),
                         runtime._budget_article_id('revision-new'))

    def test_budget_hold_remains_attention_without_generic_duplicate_notice(self):
        f = self.fixture
        f.config['generationEnabled'] = False
        job = f.runtime.ledger.create_candidate({'slug': 'budget-held', 'title': '保留記事'})
        f.runtime.ledger.set_stage(job['id'], 'error', {'reason': 'model_budget_hold'})
        result = f.runtime.tick()
        self.assertEqual('attention', result['status'])
        self.assertEqual([], f.slack.notices)

    def test_requested_period_budget_hold_reports_cause_and_task_cost(self):
        from datetime import datetime
        from runtime import JST
        f = self.fixture
        f.config['modelBudget'] = {'article': {'calls': 1}}
        f.config['productionVerificationPeriod'] = '2026-11-20'
        f.configure_production_schedule()
        runtime = f.runtime
        with runtime.model_budget.scope('fixture-article', 'draft', datetime(2026,11,20,10,tzinfo=JST)):
            runtime.model_budget.reserve({'max_tokens':100,'messages':[]})
            with self.assertRaisesRegex(Exception,'model_budget_hold'):
                runtime.model_budget.reserve({'max_tokens':100,'messages':[]})
        with patch('usage_cost_report.usage_cost_summary', return_value='TASK_ONLY_COST_AND_BUDGET') as summary:
            runtime._flush_budget_notifications()
        hold = next(text for text in f.slack.notices if '工程保留' in text)
        self.assertIn('原因（確定）',hold)
        self.assertIn('TASK_ONLY_COST_AND_BUDGET',hold)
        self.assertEqual('2026-11-20',summary.call_args.kwargs['period_key'])
        self.assertEqual('production',summary.call_args.kwargs['kind'])

    def test_requested_period_failure_has_one_detailed_notice_without_generic_duplicate(self):
        from datetime import datetime
        from runtime import JST
        f = self.fixture
        f.config['generationEnabled'] = False
        f.config['productionVerificationPeriod'] = '2026-11-20'
        f.configure_production_schedule()
        runtime=f.runtime
        job=runtime.ledger.create_candidate({'slug':'failure-fixture','title':'確認用記事'},
            now=datetime(2026,11,20,9,tzinfo=JST))
        runtime.ledger.set_stage(job['id'],'error',{'reason':'source_product_image_or_affiliate_verification_incomplete'})
        with patch('runtime.datetime') as clock, patch('usage_cost_report.usage_cost_summary',return_value='TASK_COST_AND_REMAINING'):
            clock.now.return_value=datetime(2026,11,20,10,tzinfo=JST)
            result=runtime.tick()
        self.assertEqual('blocked',result['productionVerification']['status'])
        self.assertEqual('attention',result['status'])
        self.assertEqual(1,len(f.slack.notices))
        self.assertIn('TASK_COST_AND_REMAINING',f.slack.notices[0])
        self.assertEqual([],f.writes)
