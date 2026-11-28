"""Offline tests for the one-shot independent Astra review adapter."""
from contextlib import contextmanager
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import independent_article_review as review_adapter
from dispatcher import DeterministicDispatcher
from ledger import fingerprint
from model_budget import BudgetHold
from stage_journal import StageBlocked, StageJournal, StageUnknown
import test_catalog_correction_runtime as correction_fixture


class FakeLedger:
    def __init__(self, job):
        self.job = copy.deepcopy(job)
        self.recorded = []

    def get_job(self, job_id):
        if job_id != self.job['id']:
            raise KeyError(job_id)
        return copy.deepcopy(self.job)

    def record_astra_review(self, job_id, revision, review):
        if job_id != self.job['id'] or revision != self.job['revision']:
            raise ValueError('revision mismatch')
        self.job['astraReview'] = copy.deepcopy(review)
        self.recorded.append(copy.deepcopy(review))
        return self.get_job(job_id)


class FakeJournal:
    def __init__(self):
        self.records = {}
        self.usage = []

    @staticmethod
    def key(job_id, stage, inputs):
        raw = json.dumps([job_id, stage, inputs], sort_keys=True,
                         ensure_ascii=False, separators=(',', ':')).encode()
        return hashlib.sha256(raw).hexdigest()

    def run(self, job_id, stage, inputs, operation, *, max_attempts=2):
        assert max_attempts == 1
        key = self.key(job_id, stage, inputs)
        record = self.records.get(key)
        if record:
            if record['status'] == 'succeeded':
                return copy.deepcopy(record['output'])
            if record['status'] == 'in_flight':
                raise StageUnknown('unknown', stage_key=key)
            raise StageBlocked('failed', stage_key=key)
        self.records[key] = {'status': 'in_flight', 'maxAttempts': max_attempts}
        try:
            output = operation()
        except StageUnknown:
            raise
        except Exception:
            self.records[key]['status'] = 'failed'
            raise
        self.records[key].update(status='succeeded', output=copy.deepcopy(output))
        return copy.deepcopy(output)

    def record_usage(self, job_id, stage, key, records, *, reason):
        self.usage.append(copy.deepcopy(records))


class FakeBudget:
    def __init__(self):
        self.reserved = []
        self.settled = []
        self.hold = None

    @contextmanager
    def scope(self, article_id, stage):
        self.scope_value = (article_id, stage)
        yield

    def reserve(self, payload, model=None):
        if self.hold:
            raise self.hold
        self.reserved.append((copy.deepcopy(payload), model))
        return 'reservation-1'

    def settle(self, reservation, usage=None, outcome='success'):
        self.settled.append((reservation, copy.deepcopy(usage), outcome))


class JournalLedger:
    """Minimal real SQLite authority for exercising StageJournal._operate."""
    def __init__(self, root):
        self.db_path = Path(root) / 'journal.sqlite3'
        with sqlite3.connect(self.db_path) as db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')

    @contextmanager
    def _tx(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()

    @staticmethod
    def _event(*_args, **_kwargs):
        return None


class FakeRuntime:
    def __init__(self, job):
        self.config = {
            'independentReviewEnabled': True,
            'editorialManager': {'command': ['pinned-managed-command']},
            'repo': '/not/read/in/tests',
        }
        self.ledger = FakeLedger(job)
        self.stage_journal = FakeJournal()
        self.model_budget = FakeBudget()
        self.flushes = 0

    def _budget_article_id(self, job_id):
        return 'article-budget:' + job_id

    def _flush_budget_notifications(self):
        self.flushes += 1


def fixture_job():
    bundle = {
        'article': {
            'id': 'article-public', 'slug': 'safe-slug', 'title': 'Safe title',
            'content': 'A source-bound public claim.', 'excerpt': 'Excerpt',
            'metaDescription': 'Description', 'faqs': [], 'tags': ['safe'],
            'categoryId': 'tent', 'productIds': ['p1'], 'author': 'OWNER SECRET',
        },
        'brief': {
            'purpose': 'Compare evidence', 'audience': 'Readers',
            'conclusion': 'Use verified facts', 'headings': [], 'facts': ['fact'],
            'numbers': [], 'links': [], 'requiredExpressions': [], 'protected': [],
            'tone': 'plain', 'length': 'bounded', 'cta': 'check', 'format': 'comparison',
        },
        'products': [{'id': 'p1', 'name': 'Item', 'brand': 'Brand',
                      'privateNote': 'PRIVATE PRODUCT NOTE'}],
        'images': [{'id': 'i1', 'url': 'https://example.test/image.jpg', 'verified': True,
                    'localPath': '/private/image'}],
        'references': [{'url': 'https://example.test/source', 'title': 'Source',
                        'text': 'Literal source claim.',
                        'auth': 'SECRET'}],
        'revisionContext': {'privateBase': {'ownerIdentity': 'OWNER-123'}},
    }
    revision = fingerprint(bundle)
    return {
        'id': 'revision-job', 'kind': 'article_revision', 'stage': 'review',
        'bundle': bundle, 'revision': revision, 'approval': None, 'publication': None,
        'review': {'passed': True, 'fingerprint': revision,
                   'evidence': {key: True for key in
                                ('facts', 'images', 'affiliate', 'medical', 'render')}},
        'revisionContext': {
            'privateBase': {'ownerIdentity': 'OWNER-123'},
            'analysisBinding': {'sourceProof': {'checks': {
                'facts': True, 'images': True, 'affiliate': True}}},
        },
        'nonce': 'NONCE-SECRET',
    }


def response(job, *, passed=True, issues=None, usage=True):
    return {
        'requestedModel': 'gpt-6-astra', 'actualModel': None,
        'usage': {'input_tokens': 100, 'output_tokens': 20} if usage else None,
        'actualInvoiceUsd': None,
        'decision': {
            'stateFingerprint': 'a' * 64, 'summary': 'raw summary not persisted',
            'actions': [{
                'action': 'quality_review', 'jobId': job['id'],
                'revision': job['revision'], 'passed': passed,
                'issues': [] if issues is None else issues,
            }],
        },
    }


class IndependentReviewTests(unittest.TestCase):
    def setUp(self):
        self.job = fixture_job()
        self.runtime = FakeRuntime(self.job)
        self.validation = patch.multiple(
            review_adapter, valid_review=lambda *_: None,
            require_current_review=lambda *_: None)
        self.validation.start()

    def tearDown(self):
        self.validation.stop()

    def test_one_call_records_pass_and_existing_review_is_cached(self):
        with patch.object(review_adapter.manager_cli, 'call', return_value=response(self.job)) as call:
            first = review_adapter.ensure_review(self.runtime, self.job)
            second = review_adapter.ensure_review(self.runtime, self.job)
        self.assertEqual(('passed', True), (first['status'], first['called']))
        self.assertEqual(('passed', False), (second['status'], second['called']))
        call.assert_called_once()
        self.assertEqual(16384, self.runtime.model_budget.reserved[0][0]['max_tokens'])
        self.assertEqual(180, call.call_args.kwargs['timeout'])
        self.assertFalse(self.runtime.ledger.job['astraReview']['evidence']
                         ['independentReview']['outputCapEnforced'])
        self.assertNotIn('approval', self.runtime.ledger.job['astraReview'])
        self.assertNotIn('raw summary', json.dumps(self.runtime.ledger.job['astraReview']))

    def test_known_failure_is_cached_and_never_grants_owner_approval(self):
        issue = {'code': 'unsupported_claim', 'location': 'article.content',
                 'detail': 'Claim lacks supplied support'}
        with patch.object(review_adapter.manager_cli, 'call', return_value=response(
                self.job, passed=False, issues=[issue])) as call:
            first = review_adapter.ensure_review(self.runtime, self.job)
            second = review_adapter.ensure_review(self.runtime, self.job)
        self.assertEqual('failed', first['status'])
        self.assertEqual('failed', second['status'])
        call.assert_called_once()
        self.assertEqual([], self.runtime.ledger.recorded)
        self.assertIsNone(self.runtime.ledger.job.get('approval'))

    def test_refusal_and_missing_usage_remain_unknown_without_repeat(self):
        for provider in (ValueError('refused'), response(self.job, usage=False)):
            runtime = FakeRuntime(self.job)
            side_effect = provider if isinstance(provider, Exception) else None
            with self.subTest(provider=type(provider).__name__), patch.object(
                    review_adapter.manager_cli, 'call', side_effect=side_effect,
                    return_value=None if side_effect else provider) as call:
                first = review_adapter.ensure_review(runtime, self.job)
                second = review_adapter.ensure_review(runtime, self.job)
            self.assertEqual('unknown', first['status'])
            self.assertEqual('unknown', second['status'])
            call.assert_called_once()
            self.assertEqual('unknown', runtime.model_budget.settled[0][2])
            self.assertEqual([], runtime.ledger.recorded)

    def test_real_stage_journal_keeps_unknown_terminal_on_later_ticks(self):
        with tempfile.TemporaryDirectory() as folder:
            self.runtime.stage_journal = StageJournal(JournalLedger(folder))
            with patch.object(review_adapter.manager_cli, 'call',
                              side_effect=ValueError('refused')) as call:
                first = review_adapter.ensure_review(self.runtime, self.job)
                second = review_adapter.ensure_review(self.runtime, self.job)
            self.assertEqual(('unknown', True), (first['status'], first['called']))
            self.assertEqual(('unknown', False), (second['status'], second['called']))
            call.assert_called_once()
            records = self.runtime.stage_journal.status(
                job_id=self.job['id'], stage=review_adapter.STAGE)['records']
            self.assertEqual(1, len(records))
            self.assertEqual(('in_flight', 1, 1),
                             (records[0]['status'], records[0]['attempts'],
                              records[0]['maxAttempts']))
            self.assertEqual('unknown', self.runtime.model_budget.settled[0][2])

    def test_changed_revision_after_response_is_stale(self):
        def mutate(*_args, **_kwargs):
            result = response(self.job)
            self.runtime.ledger.job['bundle']['article']['title'] = 'Changed concurrently'
            self.runtime.ledger.job['revision'] = fingerprint(self.runtime.ledger.job['bundle'])
            return result
        with patch.object(review_adapter.manager_cli, 'call', side_effect=mutate):
            status = review_adapter.ensure_review(self.runtime, self.job)
        self.assertEqual('stale', status['status'])
        self.assertEqual([], self.runtime.ledger.recorded)

    def test_stale_caller_revision_and_false_quality_flag_block_before_provider(self):
        stale = copy.deepcopy(self.job)
        stale['revision'] = '0' * 64
        with patch.object(review_adapter.manager_cli, 'call') as call:
            status = review_adapter.ensure_review(self.runtime, stale)
        self.assertEqual('stale', status['status'])
        call.assert_not_called()

        self.runtime.ledger.job['review']['evidence']['facts'] = False
        with patch.object(review_adapter.manager_cli, 'call') as call:
            status = review_adapter.ensure_review(self.runtime, self.job)
        self.assertEqual('blocked', status['status'])
        call.assert_not_called()

    def test_budget_hold_is_cached_without_transport(self):
        self.runtime.model_budget.hold = BudgetHold(
            reason_code='article_calls_cap', budget_scope='article', dimension='calls',
            cap=32, projected=33, article_id='article-budget:revision-job',
            stage='independent_review', period_key='2026-11-27', event_id='event')
        with patch.object(review_adapter.manager_cli, 'call') as call:
            first = review_adapter.ensure_review(self.runtime, self.job)
            second = review_adapter.ensure_review(self.runtime, self.job)
        self.assertEqual('budget_hold', first['status'])
        self.assertEqual('budget_hold', second['status'])
        call.assert_not_called()

    def test_snapshot_is_allowlisted_and_schema_has_exact_action_shape(self):
        captured = {}
        def inspect_call(command, snapshot, prompt, schema, timeout):
            captured.update(snapshot=copy.deepcopy(snapshot), schema=copy.deepcopy(schema))
            return response(self.job)
        with patch.object(review_adapter.manager_cli, 'call', side_effect=inspect_call):
            review_adapter.ensure_review(self.runtime, self.job)
        raw = json.dumps(captured['snapshot'], ensure_ascii=False)
        for secret in ('OWNER SECRET', 'OWNER-123', 'NONCE-SECRET',
                       'PRIVATE PRODUCT NOTE', '/private/image'):
            self.assertNotIn(secret, raw)
        action = captured['schema']['properties']['actions']['items']
        self.assertEqual({'action', 'jobId', 'revision', 'passed', 'issues'},
                         set(action['properties']))
        self.assertFalse(action['additionalProperties'])

    def test_real_reviewed_job_keeps_semantic_source_shape(self):
        path = Path('/tmp/camp-down-reviewed-job-20261128.json')
        if not path.exists():
            self.skipTest('local reviewed fixture unavailable')
        job = json.loads(path.read_text())
        snapshot = review_adapter._public_snapshot(job)
        public = snapshot['publicBundle']
        self.assertEqual(job['bundle']['brief']['reader'], public['brief']['reader'])
        self.assertEqual(job['bundle']['brief']['style'], public['brief']['style'])
        self.assertEqual(len(job['bundle']['references']), len(public['references']))
        for source, projected in zip(job['bundle']['references'], public['references']):
            for key in ('text', 'conditions', 'scope', 'model', 'productId',
                        'sourceUrl', 'excerptSHA256', 'apparelBinding'):
                if key in source:
                    self.assertEqual(source[key], projected[key])
        raw = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn('catalogCorrectionContext', raw)
        self.assertNotIn('baseProducts', raw)
        self.assertLessEqual(len(json.dumps(snapshot, ensure_ascii=False,
                                            sort_keys=True, separators=(',', ':')).encode()),
                             review_adapter.MAX_SNAPSHOT_BYTES)


class RuntimeIntegrationTests(unittest.TestCase):
    """Exercise Main's finish, deliver and dispatcher wiring with real state APIs."""
    setUp = correction_fixture.CatalogCorrectionRuntimeTests.setUp
    tearDown = correction_fixture.CatalogCorrectionRuntimeTests.tearDown
    raw = correction_fixture.CatalogCorrectionRuntimeTests.raw
    candidate = correction_fixture.CatalogCorrectionRuntimeTests.candidate
    attach = correction_fixture.CatalogCorrectionRuntimeTests.attach
    context = correction_fixture.CatalogCorrectionRuntimeTests.context
    produce = correction_fixture.CatalogCorrectionRuntimeTests.produce

    def configure_independent_review(self):
        self.config['independentReviewEnabled'] = True
        self.config['editorialManager'] = {'command': ['synthetic-managed-astra']}

    @staticmethod
    def source_complete_bundle(original):
        def build():
            value = original()
            for item in value['references']:
                item['text'] = 'Synthetic literal official-source evidence.'
                item['productId'] = 'tent-a'
            return value
        return build

    @staticmethod
    def passed_response(_command, snapshot, _prompt, _schema, timeout):
        if timeout != 180:
            raise AssertionError('bounded timeout changed')
        return {
            'requestedModel': 'gpt-6-astra', 'actualModel': None,
            'usage': {'input_tokens': 101, 'output_tokens': 17},
            'actualInvoiceUsd': None,
            'decision': {
                'stateFingerprint': 'a' * 64, 'summary': 'safe',
                'actions': [{
                    'action': 'quality_review', 'jobId': snapshot['articleId'],
                    'revision': snapshot['revision'], 'passed': True, 'issues': [],
                }],
            },
        }

    def test_real_finish_and_deliver_invoke_one_call_and_record_actual_usage(self):
        self.configure_independent_review()
        original = correction_fixture.bundle
        with patch.object(correction_fixture, 'bundle',
                          side_effect=self.source_complete_bundle(original)), \
                patch.object(review_adapter.manager_cli, 'call',
                             side_effect=self.passed_response) as call:
            job = self.produce()
            again = self.runtime.deliver(job['id'])
        call.assert_called_once()
        self.assertEqual('already_delivered', again['status'])
        saved = self.runtime.ledger.get_job(job['id'])
        self.assertIsNone(saved['approval'])
        self.assertTrue(saved['astraReview']['passed'])
        receipt = saved['astraReview']['evidence']['independentReview']
        self.assertIsNone(receipt['actualModel'])
        self.assertIsNone(receipt['actualInvoiceUsd'])
        self.assertEqual(1, len(self.slack.deliveries))
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            row = db.execute('''SELECT status,stage,reserved_output_tokens,
                actual_input_tokens,actual_output_tokens FROM model_budget_reservations
                WHERE stage=?''', (review_adapter.STAGE,)).fetchone()
        self.assertEqual(('settled', review_adapter.STAGE, 16384, 101, 17), row)

    def test_unknown_finish_dispatches_delivery_without_recall_or_duplicate_notice(self):
        self.configure_independent_review()
        self.config['executionPolicy'] = {
            'mode': 'deterministic', 'suspended': False,
            'exceptions': {'autoAI': False},
        }
        original = correction_fixture.bundle
        with patch.object(correction_fixture, 'bundle',
                          side_effect=self.source_complete_bundle(original)), \
                patch.object(review_adapter.manager_cli, 'call',
                             side_effect=ValueError('provider refused')) as call:
            job = self.produce()
            plan = DeterministicDispatcher(self.runtime).plan(
                datetime(2026, 11, 11, 10, tzinfo=__import__('runtime').JST))
            again = self.runtime.deliver(job['id'])
        call.assert_called_once()
        self.assertEqual('awaiting_astra_review', again['status'])
        self.assertEqual('unknown', again['qualityStatus'])
        self.assertIn({'kind': 'deliver', 'jobId': job['id'],
                       'deliveryKind': 'article'}, plan['actions'])
        self.assertEqual(1, len(self.slack.notices))
        self.assertEqual([], self.slack.deliveries)
        self.assertIsNone(self.runtime.ledger.get_job(job['id']).get('approval'))
        marker = self.runtime.root / 'independent-review-notices' / (job['revision'] + '.json')
        self.assertEqual('completed', json.loads(marker.read_text())['status'])
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            row = db.execute('''SELECT status,actual_input_tokens,actual_output_tokens
                FROM model_budget_reservations WHERE stage=?''',
                             (review_adapter.STAGE,)).fetchone()
        self.assertEqual(('unknown', None, None), row)


if __name__ == '__main__':
    unittest.main()
