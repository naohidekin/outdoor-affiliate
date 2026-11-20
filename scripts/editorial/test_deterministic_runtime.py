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
                    lambda: self.runtime._finish_article_review(None, None, None, None, None, None, None, None),
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

    def corrected_fixture(self):
        from datetime import datetime
        from supplemental_topics import resolve_batch
        from test_supplemental_topics import manifest, product
        from runtime import JST
        value = manifest()
        value['slots'][2].update(slug='repair-third', title='Repair third', categoryId='wear',
                                query='winter third', selectionReason='verified fixture')
        context = {'products': [product(value['slots'][2]['productIds'][0])], 'articles': []}
        now = datetime(2026, 11, 17, 9, tzinfo=JST)
        slot = resolve_batch(value, context, [], now)['slots'][2]
        job = self.runtime.ledger.create_supplemental_candidate(
            slot['theme'], value['batchId'], 3, slot['sourceBinding'],
            social_eligible_period='2026-11-20', now=now)
        inputs = {'theme': job['theme'], 'dependencies': {'implementation': 'old'}, 'schemaVersion': 1}
        from models import ModelError
        with self.assertRaises(ModelError):
            self.runtime.stage_journal.run(job['id'], 'draft', inputs,
                lambda: (_ for _ in ()).throw(ModelError('Two to three distinct internal article links required')))
        self.runtime.ledger.set_stage(job['id'], 'error',
            {'reason': 'Two to three distinct internal article links required'})
        self.config['supplementalApparelEnabled'] = True
        return job, self.runtime.stage_journal.key(job['id'], 'draft', inputs), value, context

    def test_corrected_retry_reaches_review_with_current_sources_and_real_hashes(self):
        job, old, manifest, context = self.corrected_fixture()
        with patch.object(self.runtime, '_supplemental_manifest', return_value=manifest), \
                patch.object(self.runtime.catalog, 'catalog', return_value=context), \
                patch.object(self.runtime.catalog, 'gather', wraps=self.runtime.catalog.gather) as gather, \
                patch.object(self.models, 'draft', wraps=self.models.draft) as draft, \
                patch.object(self.runtime, '_run_model_stage', wraps=self.runtime._run_model_stage) as stages, \
                patch.object(self.runtime, 'consume', side_effect=AssertionError('consume')), \
                patch.object(self.runtime, 'tick', side_effect=AssertionError('tick')):
            result = self.runtime.retry_corrected_stage(job['id'], 'draft', old)
        self.assertEqual('awaiting_approval', result['articles'][0]['status'])
        saved = self.runtime.ledger.get_job(job['id'])
        self.assertEqual('review', saved['stage'])
        self.assertIsNone(saved['approval'])
        self.assertIsNone(saved['publication'])
        self.assertEqual(1, len(self.slack.deliveries))
        self.assertTrue(all(action == 'stage' for action, _ in self.writes))
        self.assertEqual((1, 1), (gather.call_count, draft.call_count))
        records = self.runtime.stage_journal.status(job_id=job['id'], stage='draft')['records']
        self.assertEqual([1, 2], sorted(r['attempts'] for r in records))
        draft_inputs = next(call.args[2] for call in stages.call_args_list if call.args[1] == 'draft')
        import hashlib
        from pathlib import Path
        expected_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                           for name in ('models.py', 'quality.py', 'review_scoring.py', 'writing_prompts.py')}
        self.assertEqual(expected_hashes, draft_inputs['dependencies']['routes']['implementationHashes'])
        successor = next(r for r in records if r.get('predecessorKey') == old)
        dependencies = json.dumps(draft_inputs['dependencies'], sort_keys=True, ensure_ascii=False,
                                  separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(hashlib.sha256(dependencies).hexdigest(), successor['dependencyHash'])
        self.assertEqual(1, len(self.runtime.ledger.list_jobs()))
        with self.assertRaises((ValueError, __import__('stage_journal').StageBlocked)):
            self.runtime.retry_corrected_stage(job['id'], 'draft', old)

    def test_corrected_nonprogress_keeps_error_and_never_schedules_natural_retry(self):
        job, old, manifest, context = self.corrected_fixture()
        unrelated = self.runtime.ledger.create_candidate({'slug': 'unrelated', 'title': 'Unrelated'})
        for mode in ('source_hold', 'changed_binding', 'exception'):
            live = copy.deepcopy(context)
            if mode == 'source_hold':
                live['products'] = []
            elif mode == 'changed_binding':
                live['products'][0]['name'] = 'Changed source'
            with self.subTest(mode=mode), \
                    patch.object(self.runtime, '_supplemental_manifest', return_value=manifest), \
                    patch.object(self.runtime.catalog, 'catalog',
                        side_effect=OSError('private details') if mode == 'exception' else None,
                        return_value=live), \
                    patch.object(self.models, 'draft', side_effect=AssertionError('must not call')):
                try:
                    self.runtime.retry_corrected_stage(job['id'], 'draft', old)
                except OSError:
                    pass
            saved = self.runtime.ledger.get_job(job['id'])
            self.assertEqual('error', saved['stage'])
            self.assertNotIn('private details', str(saved['error']))
            self.assertEqual('candidate', self.runtime.ledger.get_job(unrelated['id'])['stage'])
            self.assertEqual(1, len(self.runtime.stage_journal.status(job_id=job['id'])['records']))
            with self.runtime.ledger._tx() as db:
                self.assertIsNone(db.execute("SELECT value FROM meta WHERE key='runtime_retry_candidate'").fetchone())

    def test_corrected_new_failure_keeps_actual_cause_and_original_as_history(self):
        job, old, manifest, context = self.corrected_fixture()
        original = self.runtime.ledger.get_job(job['id'])['error']
        with patch.object(self.runtime, '_supplemental_manifest', return_value=manifest), \
                patch.object(self.runtime.catalog, 'catalog', return_value=context), \
                patch.object(self.runtime.catalog, 'gather', side_effect=ValueError('source_unverified')):
            result = self.runtime.retry_corrected_stage(job['id'], 'draft', old)
        self.assertEqual('source_unverified', result['articles'][0]['reason'])
        saved = self.runtime.ledger.get_job(job['id'])
        self.assertEqual('error', saved['stage'])
        self.assertEqual('source_unverified', saved['error']['reason'])
        self.assertIn('at', saved['error'])
        self.assertEqual(original, saved['error']['originalFailure'])
        self.assertEqual(1, len(self.runtime.stage_journal.status(job_id=job['id'])['records']))

    def test_corrected_reserved_failure_keeps_budget_cause_and_failed_lineage(self):
        job, old, manifest, context = self.corrected_fixture()
        with patch.object(self.runtime, '_supplemental_manifest', return_value=manifest), \
                patch.object(self.runtime.catalog, 'catalog', return_value=context), \
                patch.object(self.models, 'draft', side_effect=ValueError('model_budget_hold')):
            result = self.runtime.retry_corrected_stage(job['id'], 'draft', old)
        saved = self.runtime.ledger.get_job(job['id'])
        self.assertEqual('model_budget_hold', saved['error']['reason'])
        self.assertEqual('model_budget_hold', result['articles'][0]['reason'])
        records = self.runtime.stage_journal.status(job_id=job['id'], stage='draft')['records']
        self.assertEqual([('failed', 1), ('failed', 2)],
                         sorted((r['status'], r['attempts']) for r in records))
        self.assertEqual([], self.slack.deliveries)
        with self.assertRaises((ValueError, __import__('stage_journal').StageBlocked)):
            self.runtime.retry_corrected_stage(job['id'], 'draft', old)

    def test_corrected_scope_rejects_other_jobs_stages_errors_and_nonempty_outputs(self):
        job, old, _, _ = self.corrected_fixture()
        job = self.runtime.ledger.get_job(job['id'])
        records = self.runtime.stage_journal.status(job_id=job['id'], stage='draft')['records']
        changes = ({'kind': 'article_revision'}, {'batchId': 'different'},
                   {'stage': 'candidate'}, {'bundle': {}}, {'bundle': {'article': {}}},
                   {'approval': {}}, {'publication': {}},
                   {'approval': {'revision': 'old'}}, {'publication': {'verified': False}},
                   {'error': {'reason': 'unrelated_failure'}})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.runtime.validate_corrected_retry(dict(job, **change), 'draft', old, records)
        with self.assertRaises(ValueError):
            self.runtime.validate_corrected_retry(job, 'polish', old, records)
        self.config['executionPolicy']['suspended'] = True
        with self.assertRaisesRegex(ValueError, 'execution_suspended'):
            self.runtime.retry_corrected_stage(job['id'], 'draft', old)

    def assert_corrected_budget_hold(self, scope):
        from datetime import datetime
        from runtime import JST
        from model_budget import BudgetHold
        job, old, _, _ = self.corrected_fixture()
        budget = self.runtime.model_budget
        payload = {'model': 'fixture', 'max_tokens': 1, 'messages': []}
        if scope == 'article':
            seeds = [(job['id'], 32, None)]
        elif scope == 'period':
            seeds = [('other-' + str(i), 32, None) for i in range(4)]
        else:
            # Batch calls span production periods; article/period totals do not.
            prior = datetime(2026, 10, 1, 9, tzinfo=JST)
            seeds = [(job['id'], 32, prior)]
            for slot in (1, 2):
                sibling = self.runtime.ledger.create_supplemental_candidate(
                    dict(job['theme'], slug='sibling-' + str(slot)), job['batchId'], slot,
                    job['sourceBinding'], social_eligible_period='2026-11-20')
                seeds.append((sibling['id'], 32, prior))
        for article, calls, now in seeds:
            with budget.scope(article, 'draft', now):
                for _ in range(calls):
                    budget.reserve(payload)
        self.runtime._explicit_stage_retry = {'jobId': job['id'], 'stage': 'draft',
                                               'inputKey': old, 'corrected': True}
        inputs = {'theme': job['theme'], 'dependencies': {'routes': self.runtime._model_routes()},
                  'schemaVersion': 1}
        with self.assertRaises(BudgetHold) as caught:
            self.runtime._run_model_stage(job, 'draft', inputs,
                lambda: budget.reserve(payload), 'fixture')
        self.assertEqual(scope + '_calls_cap', caught.exception.reason_code)
        self.assertEqual(job['id'], caught.exception.article_id)
        self.assertEqual({'article': 32, 'period': 128, 'batch': 96}[scope], caught.exception.cap)
        with self.runtime.ledger._tx() as db:
            count = db.execute('SELECT count(*) FROM model_budget_reservations').fetchone()[0]
        self.assertEqual({'article': 32, 'period': 128, 'batch': 96}[scope], count)
        records = self.runtime.stage_journal.status(job_id=job['id'], stage='draft')['records']
        successor = next(r for r in records if r.get('predecessorKey') == old)
        self.assertEqual(('failed', 2, 2),
                         (successor['status'], successor['attempts'], successor['maxAttempts']))

    def test_corrected_retry_retains_article_32_call_cap(self):
        self.assert_corrected_budget_hold('article')

    def test_corrected_retry_retains_period_128_call_cap(self):
        self.assert_corrected_budget_hold('period')

    def test_corrected_retry_retains_lifetime_batch_96_call_cap(self):
        self.assert_corrected_budget_hold('batch')

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

    def test_draft_key_ignores_duplicate_illustration_clock_but_keeps_all_source_proofs(self):
        image = {'id': 'illustration:owned', 'checkedAt': 'first', 'sha256': 'a' * 64,
                 'compositionSha256': 'b' * 64, 'referenceIds': ['public:source'],
                 'rendererEvidence': {'contentHash': 'c' * 64, 'sourceReceiptSha256': 'd' * 64,
                                      'displayText': {'title': '固定タイトル'}, 'networkRequests': 0}}
        source = {'images': [copy.deepcopy(image)], 'references': [{'url': 'https://maker.example/source',
                  'checkedAt': 'first', 'excerpt': '固定された一次資料', 'receiptSha256': 'e' * 64}],
                  'evidence': {'ownedIllustrations': [copy.deepcopy(image)]}}
        before = copy.deepcopy(source)
        def key(value):
            return self.runtime.stage_journal.key('job', 'draft', {
                'dependencies': {'source': self.runtime._source_dependencies(value)}, 'schemaVersion': {'stage': 1}})
        original = key(source)
        same = copy.deepcopy(source)
        same['images'][0]['checkedAt'] = 'second'
        same['evidence']['ownedIllustrations'][0]['checkedAt'] = 'second'
        same['references'][0]['checkedAt'] = 'second'
        self.assertEqual(original, key(same))
        self.assertEqual(before, source)
        changes = [lambda v: v['images'][0].update(sha256='f' * 64),
                   lambda v: v['references'][0].update(excerpt='別の一次資料'),
                   lambda v: v['references'][0].update(receiptSha256='f' * 64),
                   lambda v: v['evidence']['ownedIllustrations'][0].update(compositionSha256='f' * 64),
                   lambda v: v['evidence']['ownedIllustrations'][0]['rendererEvidence'].update(contentHash='f' * 64),
                   lambda v: v['evidence']['ownedIllustrations'][0]['rendererEvidence'].update(sourceReceiptSha256='f' * 64)]
        for change in changes:
            changed = copy.deepcopy(same)
            change(changed)
            self.assertNotEqual(original, key(changed))

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
