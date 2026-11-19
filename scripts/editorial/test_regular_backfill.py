"""Offline regular selection persistence, slot limits and diagnostic flushing."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch

import test_runtime as fixture
from runtime import JST, atomic
from regular_backfill import backfill, load_selection


NOW = datetime(2026, 11, 16, 10, tzinfo=JST)
PERIOD = '2026-11-13'
THEMES = [{'slug': 'pool-' + str(i), 'title': 'Selected ' + str(i)} for i in range(3)]


class RegularBackfillTests(unittest.TestCase):
    tearDown = fixture.RuntimeTests.tearDown

    def setUp(self):
        fixture.RuntimeTests.setUp(self)
        fixture.RuntimeTests.configure_production_schedule(self)

    def save_selection(self, themes=THEMES, period=PERIOD, **fields):
        atomic(self.runtime.root / 'production-attempts' / (period + '.json'),
               {'status': 'generated', 'period': period, 'themes': themes, **fields})

    def produce(self, at=NOW, **kwargs):
        with patch('runtime.datetime') as clock:
            clock.now.return_value = at
            return self.runtime.produce(**kwargs)

    def old_pending(self, count=2, kind=None):
        jobs = []
        for index in range(count):
            job = self.runtime.ledger.create_candidate({'slug': 'old-' + str(index)},
                datetime(2026, 11, 9, 10, tzinfo=JST))
            with self.runtime.ledger._tx() as db:
                job.update(stage='error')
                if kind:
                    job['kind'] = kind
                self.runtime.ledger._put(db, job, 'fixture')
            jobs.append(job)
        return jobs

    def release(self, job):
        with self.runtime.ledger._tx() as db:
            current = self.runtime.ledger._get(db, job['id'])
            current.update(publication={'verified': True}, stage='published')
            self.runtime.ledger._put(db, current, 'fixture')

    def test_saved_three_backfill_real_vacancies_without_research_after_restart(self):
        old = self.old_pending(kind='supplemental_article')
        self.save_selection()
        with patch.object(self.models, 'research', side_effect=AssertionError('research')), \
                patch('runtime.require_fresh_daily_metrics', side_effect=AssertionError('new research gate')), \
                patch.object(self.runtime, '_make_article', side_effect=lambda job, _: self.runtime.ledger.set_stage(job['id'], 'review')):
            first = self.produce(limit=99)
            self.assertEqual(1, len(first['articles']))
            first_job = self.runtime.ledger.get_job(first['articles'][0]['id'])
            self.assertIsNone(first_job['approval'])
            self.assertIsNone(first_job['publication'])
            self.assertEqual([], self.produce(limit=99)['articles'])
            self.release(old[0])
            fixture.RuntimeTests.configure_production_schedule(self)
            with patch.object(self.runtime, '_make_article', side_effect=lambda job, _: self.runtime.ledger.set_stage(job['id'], 'review')):
                self.assertEqual(1, len(self.produce(limit=99)['articles']))
                self.release(old[1])
                self.assertEqual(1, len(self.produce(limit=99)['articles']))
                for job in self.runtime.ledger.list_jobs():
                    if job['week'] == PERIOD:
                        self.release(job)
                self.assertEqual('idle', self.produce(limit=99)['status'])
        regular_jobs = [j for j in self.runtime.ledger.list_jobs() if j['week'] == PERIOD]
        self.assertEqual([theme['slug'] for theme in THEMES], [j['theme']['slug'] for j in regular_jobs])
        self.assertEqual(3, len(regular_jobs))

    def test_new_research_persists_full_selection_with_only_one_free_slot(self):
        self.old_pending()
        with patch.object(self.models, 'research', return_value={'themes': THEMES}) as research, \
                patch.object(self.runtime, '_make_article', side_effect=lambda job, _: self.runtime.ledger.set_stage(job['id'], 'review')):
            self.assertEqual(1, len(self.produce(limit=99)['articles']))
        research.assert_called_once()
        self.assertEqual(THEMES, load_selection(self.runtime.root, PERIOD))

    def test_mixed_selection_persists_three_bound_themes_and_backfills_without_ai(self):
        from test_topic_selection import feed, proposal
        self.old_pending()
        proposals = [proposal('bound-' + str(index), 'テントを乾燥して保管する手順') for index in range(3)]
        selection = {'status': 'selected', 'holdReason': None, 'eligibleCount': 3, 'unfilled': 0,
                     'selected': proposals, 'decisions': [dict(proposal=theme, status='selected',
                         reason='deterministic_priority_with_soft_variety') for theme in proposals]}
        at = datetime(2026, 11, 20, 10, tzinfo=JST)
        with patch('runtime.collect_primary_sources', return_value=feed()) as collect, \
                patch.object(self.runtime, '_research_context', return_value={'editorialSignals': []}), \
                patch.object(self.models, 'research_mixed', create=True,
                             return_value={'proposals': proposals}) as research, \
                patch('runtime.select_proposals', return_value=selection) as select, \
                patch.object(self.runtime, '_make_article', side_effect=lambda job, _: self.runtime.ledger.set_stage(job['id'], 'review')):
            self.assertEqual(1, len(self.produce(at, limit=99)['articles']))
            saved = load_selection(self.runtime.root, '2026-11-20')
            self.assertEqual(3, len(saved))
            self.assertTrue(all(theme.get('nonProductContract') for theme in saved))
            old = self.runtime.ledger.list_jobs()[0]
            self.release(old)
            self.assertEqual(1, len(self.produce(at, limit=99)['articles']))
        collect.assert_called_once()
        research.assert_called_once()
        select.assert_called_once()

    def test_legacy_mixed_receipt_restores_exact_selected_public_source_bindings(self):
        from test_topic_selection import feed, proposal
        from topic_selection import bind_nonproduct_theme
        period = '2026-11-20'
        proposals = [proposal('legacy-' + str(index), 'テントを乾燥して保管する手順') for index in range(3)]
        atomic(self.runtime.root / 'production-attempts' / (period + '.json'),
               {'status': 'generated', 'selection': 'selected', 'proposals': proposals})
        receipt = {'period': period, 'status': 'selected', 'selectedSlugs': [p['slug'] for p in proposals],
                   'decisions': [dict(proposal=p, status='selected') for p in proposals]}
        receipt_path = self.runtime.root / 'period-receipts' / (period + '.json')
        atomic(receipt_path, receipt)
        atomic(self.runtime.root / 'public-sources' / (period + '.json'), feed())
        self.assertEqual([bind_nonproduct_theme(p, feed()) for p in proposals],
                         load_selection(self.runtime.root, period))
        receipt['selectedSlugs'].reverse()
        atomic(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
            load_selection(self.runtime.root, period)

    def test_failed_or_rejected_selected_slot_is_consumed_not_replaced(self):
        self.save_selection()
        backfill(self.runtime.ledger, PERIOD, THEMES, NOW)
        jobs = self.runtime.ledger.list_jobs()
        for job, stage in zip(jobs, ('error', 'held', 'rejected')):
            self.runtime.ledger.set_stage(job['id'], stage)
        before = self.runtime.ledger.list_jobs()
        self.assertEqual('idle', self.produce()['status'])
        self.assertEqual(before, self.runtime.ledger.list_jobs())
        self.assertEqual([], backfill(self.runtime.ledger, PERIOD, THEMES, NOW))

    def test_unknown_publication_does_not_release_shared_pending_slot(self):
        old = self.old_pending(3)
        with self.runtime.ledger._tx() as db:
            job = self.runtime.ledger._get(db, old[0]['id'])
            job['publication'] = {'verified': False, 'status': 'unknown'}
            self.runtime.ledger._put(db, job, 'fixture')
        self.save_selection()
        self.assertEqual([], backfill(self.runtime.ledger, PERIOD, THEMES, NOW))
        with patch.object(self.runtime, '_context', side_effect=AssertionError('context')):
            self.assertEqual('idle', self.produce()['status'])

    def test_unknown_effect_cannot_be_bypassed_by_new_slot(self):
        old = self.old_pending(1)[0]
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (old['id'], 'publish', 'unknown', '{}'))
        self.assertEqual([], backfill(self.runtime.ledger, PERIOD, THEMES, NOW))

    def test_selection_and_slot_creation_are_atomic_under_failure_and_concurrency(self):
        with patch.object(self.runtime.ledger, '_put', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                backfill(self.runtime.ledger, PERIOD, THEMES, NOW)
        self.assertEqual([], self.runtime.ledger.list_jobs())
        with self.runtime.ledger._tx() as db:
            self.assertIsNone(db.execute('SELECT value FROM meta WHERE key=?', ('regular_selection:v1:' + PERIOD,)).fetchone())
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: backfill(self.runtime.ledger, PERIOD, THEMES, NOW), range(2)))
        self.assertEqual(3, sum(map(len, result)))
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))

    def test_changed_selection_conflicts_and_consumed_missing_job_is_not_recreated(self):
        backfill(self.runtime.ledger, PERIOD, THEMES, NOW)
        changed = copy.deepcopy(THEMES)
        changed[0]['title'] = 'replacement'
        with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
            backfill(self.runtime.ledger, PERIOD, changed, NOW)
        missing_id = self.runtime.ledger.list_jobs()[0]['id']
        with self.runtime.ledger._tx() as db:
            db.execute('DELETE FROM jobs WHERE id=?', (missing_id,))
        with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
            backfill(self.runtime.ledger, PERIOD, THEMES, NOW)

    def test_rollover_does_not_consume_previous_pool_or_repeat_its_research(self):
        self.save_selection()
        self.old_pending(2)
        backfill(self.runtime.ledger, PERIOD, THEMES, NOW)
        for job in self.runtime.ledger.list_jobs():
            self.release(job)
        new_themes = [dict(theme, slug='next-' + theme['slug']) for theme in THEMES]
        self.save_selection(new_themes, '2026-11-20')
        with patch.object(self.models, 'research', side_effect=AssertionError('research')), \
                patch.object(self.runtime, '_make_article', side_effect=lambda job, _: self.runtime.ledger.set_stage(job['id'], 'review')):
            self.assertEqual('idle', self.produce(datetime(2026, 11, 20, 8, 59, tzinfo=JST))['status'])
            result = self.produce(datetime(2026, 11, 20, 9, tzinfo=JST), limit=99)
        self.assertEqual(3, len(result['articles']))
        self.assertEqual(1, sum(j['week'] == PERIOD for j in self.runtime.ledger.list_jobs()))
        with self.assertRaisesRegex(ValueError, 'production not due'):
            backfill(self.runtime.ledger, PERIOD, THEMES, datetime(2026, 11, 20, 9, tzinfo=JST))

    def test_unknown_research_receipt_never_repeats_or_changes(self):
        path = self.runtime.root / 'production-attempts' / (PERIOD + '.json')
        atomic(path, {'status': 'in_flight', 'themes': THEMES})
        before = path.read_bytes()
        with patch.object(self.models, 'research', side_effect=AssertionError('research')):
            with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
                self.produce()
        self.assertEqual(before, path.read_bytes())
        self.assertEqual([], self.runtime.ledger.list_jobs())

    def test_flags_and_suspension_precede_backfill_and_diagnostics(self):
        self.save_selection()
        self.config['generationEnabled'] = False
        self.assertEqual('disabled', self.produce()['status'])
        self.config['generationEnabled'] = True
        self.config['executionPolicy'] = {'mode': 'deterministic', 'suspended': True}
        with self.assertRaisesRegex(ValueError, 'execution_suspended'):
            self.produce()
        self.assertEqual([], self.runtime.ledger.list_jobs())

    def test_review_diagnostics_flush_success_and_failure_without_usage(self):
        records = [{'responseId': response_id, 'articleId': 'fixture', 'rawPassed': passed,
                    'criteria': [], 'rawScore': 8, 'actualMean': 7, 'normalizedPassed': False,
                    'normalizedScore': 7, 'issues': [], 'observations': [], 'contractIssues': []}
                   for response_id, passed in (('response-pass', True), ('response-failed', False))]
        self.models.review_diagnostics = copy.deepcopy(records)
        self.runtime._save_usage()
        self.assertEqual([], self.models.review_diagnostics)
        for record in records:
            path = self.runtime.root / 'review-diagnostics' / (hashlib.sha256(record['responseId'].encode()).hexdigest() + '.json')
            self.assertEqual(record, json.loads(path.read_text()))
        self.models.review_diagnostics = copy.deepcopy(records)
        with patch('runtime.atomic', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.runtime._save_usage()
        self.assertEqual(records, self.models.review_diagnostics)

    def test_adapter_without_diagnostics_does_not_create_a_phantom_mock_queue(self):
        self.runtime.models = Mock(usage=[])
        self.runtime._save_usage()
        self.assertNotIn('review_diagnostics', self.runtime.models._mock_children)
        self.assertFalse((self.runtime.root / 'review-diagnostics').exists())

    def test_failed_review_still_flushes_its_diagnostic_before_produce_returns(self):
        self.save_selection()
        record = {'responseId': 'review-failure', 'normalizedPassed': False, 'contractIssues': ['mean mismatch']}
        self.models.review_diagnostics = []
        def fail_review(*_):
            self.models.review_diagnostics.append(record)
            raise ValueError('review failed')
        with patch.object(self.runtime, '_make_article', side_effect=fail_review):
            result = self.produce(limit=1)
        self.assertEqual('blocked', result['articles'][0]['status'])
        self.assertEqual([], self.models.review_diagnostics)
        path = self.runtime.root / 'review-diagnostics' / (hashlib.sha256(record['responseId'].encode()).hexdigest() + '.json')
        self.assertEqual(record, json.loads(path.read_text()))
