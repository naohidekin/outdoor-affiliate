"""Offline integration tests for deterministic runtime progression."""
import copy
import json
from unittest.mock import patch
import unittest

import test_runtime
from runtime import Runtime


class DeterministicRuntimeTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config['executionPolicy'] = {
            'mode': 'deterministic', 'suspended': False,
            'exceptions': {'autoAI': False},
        }

    tearDown = test_runtime.RuntimeTests.tearDown

    def test_invalid_policy_fails_closed_during_runtime_initialization(self):
        config = dict(self.config, executionPolicy={'mode': 'deterministic', 'suspended': 'false'})
        with self.assertRaisesRegex(ValueError, 'invalid executionPolicy'):
            Runtime(config, models=self.models, catalog=self.runtime.catalog, slack=self.slack,
                    renderer=self.runtime.renderer, publisher=self.runtime.publisher,
                    analytics=self.runtime.analytics, reporter=self.runtime.reporter)

    def test_suspended_tick_returns_before_every_external_or_mutating_boundary(self):
        self.config['executionPolicy']['suspended'] = True
        boundaries = ('consume', '_post_publication_audits', '_produce_requested_revision',
                      '_evaluate_manager', 'produce', 'deliver', 'make_social',
                      'publish_social', 'notify_social_posted', '_analytics_context')
        patches = [patch.object(self.runtime, name, side_effect=AssertionError(name))
                   for name in boundaries]
        started = [item.start() for item in patches]
        try:
            self.assertEqual({'status': 'suspended', 'mode': 'deterministic'}, self.runtime.tick())
        finally:
            for item in patches:
                item.stop()
        self.assertTrue(all(mock.call_count == 0 for mock in started))
        self.assertFalse((self.runtime.root / 'health.json').exists())

    def test_suspended_direct_runtime_commands_fail_before_any_effect(self):
        self.config['executionPolicy']['suspended'] = True
        with patch.object(self.runtime.catalog, 'catalog', side_effect=AssertionError('catalog')) as catalog, \
                patch.object(self.models, 'draft', side_effect=AssertionError('model')) as model, \
                patch.object(self.slack, 'deliver', side_effect=AssertionError('slack')) as slack, \
                patch.object(self.runtime, 'publisher', side_effect=AssertionError('publisher')) as publisher:
            for operation in (
                    lambda: self.runtime.produce(limit=1),
                    lambda: self.runtime.deliver('any'),
                    lambda: self.runtime.retry_stage('any', 'draft', 'stage_journal:v1:any'),
                    lambda: self.runtime.publish_social({'id': 'any'}),
                    lambda: self.runtime._make_article({'id': 'any'}, {}),
                    lambda: self.runtime._run_model_stage(
                        {'id': 'any'}, 'draft', {'dependencies': {}, 'schemaVersion': 1},
                        lambda: model(), 'requested'),
                    lambda: self.runtime._measured_model_call(
                        'any', 'draft', 'requested', lambda: model()),
                    lambda: self.runtime._evaluate_manager(
                        __import__('datetime').datetime.now(__import__('runtime').JST))):
                with self.assertRaisesRegex(ValueError, 'execution_suspended'):
                    operation()
        self.assertTrue(all(item.call_count == 0 for item in (catalog, model, slack, publisher)))

    def test_deterministic_tick_never_calls_manager_or_legacy_branch(self):
        job = self.runtime.ledger.create_candidate({'slug': 'deterministic', 'title': 'Deterministic'})
        self.config['editorialManager'] = {'enabled': True}
        with patch.object(self.runtime, '_evaluate_manager', side_effect=AssertionError('manager')) as manager, \
                patch.object(self.runtime, 'produce', return_value={'status': 'completed'}) as produce:
            result = self.runtime.tick()
        manager.assert_not_called()
        produce.assert_called_once_with(limit=1)
        self.assertEqual(job['id'], result['dispatch']['actions'][0]['jobId'])

    def test_dispatch_unknown_manager_and_effect_make_health_attention_once(self):
        self.config['generationEnabled'] = False
        job = self.runtime.ledger.create_candidate({'slug': 'unknown', 'title': 'Unknown'})
        cases = (
            ('manager', lambda db: db.execute('INSERT INTO meta VALUES (?,?)',
                ('editorial_manager:fixtureunknown', json.dumps({
                    'status': 'requires_reconciliation',
                    'action': {'job_id': job['id']}})))),
            ('effect', lambda db: db.execute('INSERT INTO effects VALUES (?,?,?,?)',
                (job['id'], 'publish', 'unknown', '{}'))),
        )
        for name, setup in cases:
            with self.subTest(name=name):
                with self.runtime.ledger._tx() as db:
                    db.execute("DELETE FROM meta WHERE key LIKE 'editorial_manager:%'")
                    db.execute('DELETE FROM effects')
                    setup(db)
                before = len(self.slack.notices)
                first = self.runtime.tick()
                second = self.runtime.tick()
                self.assertEqual('attention', first['status'])
                self.assertEqual('attention', second['status'])
                self.assertEqual(1, len(first['dispatch']['blocked']))
                self.assertTrue(any(item.get('status') == 'attention'
                                    and 'requires_reconciliation' in item.get('reason', '')
                                    for item in first['results']))
                self.assertEqual(before + 1, len(self.slack.notices))

    def test_render_failure_retry_reuses_ai_stages_but_regathers_and_rerenders(self):
        rendered = []
        def render(bundle, job):
            rendered.append(copy.deepcopy(bundle))
            if len(rendered) == 1:
                raise ValueError('render failed')
            return {'passed': True, 'clicksVerified': {'desktop': True, 'mobile': True}}
        self.runtime.renderer = render
        with patch.object(self.runtime.catalog, 'gather', wraps=self.runtime.catalog.gather) as gather, \
                patch.object(self.models, 'draft', wraps=self.models.draft) as draft, \
                patch.object(self.models, 'polish', wraps=self.models.polish) as polish, \
                patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.produce(limit=1)
            failed = next(job for job in self.runtime.ledger.list_jobs() if job['stage'] == 'error')
            self.runtime.retry(failed['id'])
            self.runtime.produce(limit=1)
        self.assertEqual(2, gather.call_count)
        self.assertEqual(2, len(rendered))
        self.assertEqual(1, draft.call_count)
        self.assertEqual(1, polish.call_count)
        self.assertEqual(1, review.call_count)
        self.assertEqual('review', self.runtime.ledger.get_job(failed['id'])['stage'])

    def test_delivery_failure_retry_restores_review_without_redraft(self):
        with patch.object(self.models, 'draft', wraps=self.models.draft) as draft, \
                patch.object(self.models, 'polish', wraps=self.models.polish) as polish, \
                patch.object(self.models, 'review', wraps=self.models.review) as review, \
                patch.object(self.runtime, 'deliver', side_effect=ValueError('delivery failed')):
            self.runtime.produce(limit=1)
        failed = next(job for job in self.runtime.ledger.list_jobs() if job['stage'] == 'error')
        self.assertIsNotNone(failed['bundle'])
        self.assertIsNotNone(failed['review'])
        self.assertEqual('review', self.runtime.retry(failed['id'])['status'])
        self.assertEqual((1, 1, 1), (draft.call_count, polish.call_count, review.call_count))

    def test_rejected_polish_is_failed_and_only_explicit_retry_repairs_it(self):
        self.models.fail_polish = True
        with patch.object(self.models, 'draft', wraps=self.models.draft) as draft, \
                patch.object(self.models, 'polish', wraps=self.models.polish) as polish:
            self.runtime.produce(limit=1)
            failed = next(job for job in self.runtime.ledger.list_jobs() if job['stage'] == 'error')
            record = self.runtime.stage_journal.status(job_id=failed['id'], stage='polish')['records'][0]
            self.assertEqual('failed', record['status'])
            self.runtime.retry(failed['id'])
            self.runtime.produce(limit=1)
            self.assertEqual(1, polish.call_count)
            self.models.fail_polish = False
            result = self.runtime.retry_stage(failed['id'], 'polish', record['stageKey'])
        self.assertEqual('completed', result['status'])
        self.assertEqual(1, draft.call_count)
        self.assertEqual(2, polish.call_count)
        self.assertEqual('review', self.runtime.ledger.get_job(failed['id'])['stage'])

    def test_failed_final_review_is_not_cached_as_success(self):
        failed_review = {'passed': False, 'score': 2, 'model': 'upper', 'issues': ['fix']}
        with patch.object(self.models, 'review', return_value=failed_review):
            self.runtime.produce(limit=1)
        job = next(item for item in self.runtime.ledger.list_jobs() if item['stage'] == 'error')
        record = self.runtime.stage_journal.status(job_id=job['id'], stage='final_review')['records'][0]
        self.assertEqual('failed', record['status'])
        self.assertEqual(1, record['attempts'])

    def test_review_key_ignores_only_known_clocks_and_preview_paths(self):
        source = __import__('test_quality').bundle()
        source['images'][0]['checkedAt'] = 'first'
        source['references'][0]['checkedAt'] = 'first'
        preview = {'passed': True, 'desktop': '/tmp/one.png', 'mobile': '/tmp/two.png',
                   'observedAt': 'first', 'clicksVerified': {'desktop': [1], 'mobile': [1]}}
        def inputs(bundle, rendered):
            return {'bundle': self.runtime._source_dependencies(bundle),
                    'checks': self.runtime._review_dependencies({'preview': rendered}),
                    'dependencies': {'renderer': self.runtime._review_dependencies(rendered)},
                    'schemaVersion': {'stage': 1}}
        first = inputs(source, preview)
        same = copy.deepcopy(source)
        same['images'][0]['checkedAt'] = 'second'
        same['references'][0]['checkedAt'] = 'second'
        same_preview = dict(preview, desktop='/private/changed.png', mobile='/private/mobile.png',
                            observedAt='second')
        key = self.runtime.stage_journal.key('job', 'final_review', first)
        self.assertEqual(key, self.runtime.stage_journal.key(
            'job', 'final_review', inputs(same, same_preview)))
        changed_click = copy.deepcopy(same_preview)
        changed_click['clicksVerified']['desktop'] = []
        self.assertNotEqual(key, self.runtime.stage_journal.key(
            'job', 'final_review', inputs(same, changed_click)))
        changed_body = copy.deepcopy(same)
        changed_body['article']['content'] += ' changed'
        self.assertNotEqual(key, self.runtime.stage_journal.key(
            'job', 'final_review', inputs(changed_body, same_preview)))
        changed_card = copy.deepcopy(same)
        changed_card['images'][0]['sha256'] = 'b' * 64
        self.assertNotEqual(key, self.runtime.stage_journal.key(
            'job', 'final_review', inputs(changed_card, same_preview)))

    def test_retry_review_checkpoint_refuses_unknown_effect_or_delivery(self):
        with patch.object(self.runtime, 'deliver', side_effect=ValueError('delivery failed')):
            self.runtime.produce(limit=1)
        job = next(item for item in self.runtime.ledger.list_jobs() if item['stage'] == 'error')
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)',
                       (job['id'], 'publish', 'unknown', '{}'))
        with self.assertRaisesRegex(ValueError, 'effect_requires_reconciliation'):
            self.runtime.retry(job['id'])
        self.assertEqual('error', self.runtime.ledger.get_job(job['id'])['stage'])

    def test_measured_stage_usage_records_receipt_and_file_attribution_once(self):
        job = self.runtime.ledger.create_candidate({'slug': 'usage', 'title': 'Usage'})
        inputs = {'payload': 'value', 'dependencies': {'route': 'fixed'},
                  'schemaVersion': {'stage': 1}}
        def operation():
            self.models.usage.append({
                'responseId': 'response-1', 'model': 'actual-model', 'input': 4,
                'output': 2, 'usage': {'input_tokens': 4, 'output_tokens': 2},
                'actualUSD': None,
            })
            return {'ok': True}
        self.runtime._run_model_stage(job, 'draft', inputs, operation, 'requested-model')
        self.runtime._run_model_stage(job, 'draft', inputs, operation, 'requested-model')
        stage = self.runtime.stage_journal.status(job_id=job['id'], stage='draft')
        self.assertEqual(1, stage['byStage']['draft']['responseReceipts'])
        self.assertEqual(1, stage['byStage']['draft']['hits'])
        self.runtime._save_usage()
        calls = json.loads(next((self.runtime.root / 'usage').glob('*.json')).read_text())['calls']
        self.assertEqual('draft', calls[0]['stage'])
        self.assertEqual('initial', calls[0]['reason'])
        self.assertEqual('requested-model', calls[0]['requestedModel'])
        self.assertEqual('actual-model', calls[0]['actualModel'])


if __name__ == '__main__':
    unittest.main()
