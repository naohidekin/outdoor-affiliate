"""Synthetic contracts for the owner-only review path; no external calls."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from manual_review import ManualReview, _ScopedRuntime
from runtime import Runtime


ALLOWED_SOCIAL = (
    'article-8baa356ebcdfb7a27ae7235f',
    'article-a3aecafc99811088f6d1e98c',
)


class RuntimeDouble:
    def __init__(self, jobs=()):
        self.jobs = [copy.deepcopy(job) for job in jobs]
        self.ledger = SimpleNamespace(
            list_jobs=lambda: copy.deepcopy(self.jobs),
            get_job=lambda id: copy.deepcopy(next(job for job in self.jobs if job['id'] == id)))
        self.calls = []

    def _require_running(self):
        return None

    def request_revisions(self, specs):
        self.calls.append(('request_revisions', copy.deepcopy(specs)))
        return {'status': 'queued'}

    def _context(self):
        self.calls.append(('_context',))
        return {'source': 'bounded'}

    def _make_article(self, job, context):
        self.prepared_job = copy.deepcopy(job)
        self.calls.append(('_make_article', job['id'], context))
        return {'status': 'awaiting_astra_review'}

    def deliver(self, id, kind='article'):
        self.calls.append(('deliver', id, kind))
        return {'status': 'delivered'}


class ManualReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env = self.base / 'env'
        self.env.write_text('')
        self.config_path = self.base / 'config.json'
        self.config = {
            'stateRoot': str(self.base / 'state'),
            'envFile': str(self.env),
            'repo': str(Path(__file__).resolve().parents[2]),
            'spoolDir': str(self.base / 'spool'),
            'slack': {'user_id': 'OWNER'},
            'executionPolicy': {'mode': 'deterministic', 'suspended': True},
            'generationEnabled': False,
            'publicationEnabled': False,
            'catalogCorrectionsPublicationEnabled': False,
            'postPublicationAuditEnabled': False,
            'indexTrackingEnabled': False,
            'socialPostingEnabled': False,
            'socialCardsEnabled': True,
            'reportsEnabled': False,
            'editorialManager': {'enabled': False},
        }
        self.write_config()

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def review_with(self, runtime):
        review = ManualReview.__new__(ManualReview)
        review._runtime = runtime
        return review

    def revision_job(self, id='revision-one', target='article-024', stage='candidate', **extra):
        job = {'id': id, 'kind': 'article_revision', 'stage': stage,
               'revisionContext': {'baseArticle': {'id': target}},
               'approval': None, 'publication': None}
        job.update(extra)
        return job

    def test_constructor_requires_exact_stopped_configuration_without_rewriting_it(self):
        original = self.config_path.read_bytes()
        sentinel = object()
        with patch('manual_review._ScopedRuntime', return_value=sentinel):
            review = ManualReview(self.config_path)
        self.assertIs(review._runtime, sentinel)
        self.assertEqual(original, self.config_path.read_bytes())

        for field, value in (('publicationEnabled', True), ('socialPostingEnabled', True)):
            changed = copy.deepcopy(self.config)
            changed[field] = value
            self.config_path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                ManualReview(self.config_path)
        changed = copy.deepcopy(self.config)
        changed['executionPolicy']['suspended'] = False
        self.config_path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            ManualReview(self.config_path)
        for field in ('generationEnabled', 'catalogCorrectionsPublicationEnabled',
                      'postPublicationAuditEnabled', 'indexTrackingEnabled',
                      'reportsEnabled'):
            changed = copy.deepcopy(self.config)
            changed[field] = True
            self.config_path.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaises(ValueError):
                ManualReview(self.config_path)
        changed = copy.deepcopy(self.config)
        changed['editorialManager']['enabled'] = True
        self.config_path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            ManualReview(self.config_path)
        changed = copy.deepcopy(self.config)
        changed['socialCardsEnabled'] = False
        self.config_path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            ManualReview(self.config_path)
        changed = copy.deepcopy(self.config)
        changed['telegramEnabled'] = True
        self.config_path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            ManualReview(self.config_path)

    def test_scoped_guard_checks_original_digest_and_rejects_bulk_or_publish_entrypoints(self):
        digest = hashlib.sha256(self.config_path.read_bytes()).hexdigest()
        runtime = _ScopedRuntime(
            self.config, self.config_path, digest,
            models=SimpleNamespace(usage=[]), catalog=SimpleNamespace(), slack=SimpleNamespace(),
            renderer=lambda *_: None, analytics=SimpleNamespace(), reporter=SimpleNamespace())
        runtime._require_running()
        for method, args in ((runtime.tick, ()), (runtime.produce, ()), (runtime.consume, ()),
                             (runtime.publish_social, ({'id': 'x'},)), (runtime.make_social, ({'id': 'x'},))):
            with self.subTest(method=method.__name__), self.assertRaises(ValueError):
                method(*args)
        with self.assertRaises(ValueError):
            runtime.publisher('stage', {'id': 'x'})
        with self.assertRaisesRegex(ValueError, 'manual_review_entrypoint_forbidden'):
            runtime._publish('stage', {'id': 'x'})
        self.config['generationEnabled'] = True
        self.write_config()
        with self.assertRaisesRegex(ValueError, 'manual_review_config_changed'):
            runtime._require_running()

    def test_regular_runtime_remains_suspended(self):
        original = copy.deepcopy(self.config)
        runtime = Runtime(
            self.config, models=SimpleNamespace(usage=[]), catalog=SimpleNamespace(),
            slack=SimpleNamespace(), renderer=lambda *_: None,
            publisher=lambda *_: None, analytics=SimpleNamespace(), reporter=SimpleNamespace())
        with self.assertRaisesRegex(ValueError, 'execution_suspended'):
            runtime._require_running()
        self.assertEqual(original, self.config)
        self.assertTrue(self.config['executionPolicy']['suspended'])
        self.assertTrue(all(self.config[field] is False for field in (
            'generationEnabled', 'publicationEnabled', 'catalogCorrectionsPublicationEnabled',
            'postPublicationAuditEnabled', 'indexTrackingEnabled', 'socialPostingEnabled',
            'reportsEnabled')))
        self.assertTrue(self.config['socialCardsEnabled'])
        self.assertNotIn('telegramEnabled', self.config)
        self.assertFalse(self.config['editorialManager']['enabled'])

    def test_queue_revision_allows_only_two_base_articles_and_uses_existing_runtime_path(self):
        runtime = RuntimeDouble()
        review = self.review_with(runtime)
        spec = {'baseArticle': {'id': 'article-005'}}
        self.assertEqual({'status': 'queued'}, review.queue_revision(spec))
        self.assertEqual([('request_revisions', [spec])], runtime.calls)
        with self.assertRaises(ValueError):
            review.queue_revision({'baseArticle': {'id': 'article-002'}})
        self.assertEqual(1, len(runtime.calls))

    def test_prepare_revision_requires_one_unapproved_unpublished_candidate_for_target(self):
        job = self.revision_job(_source='owner-manual-review',
                                docRoles=['source', 'review-specification'])
        other = self.revision_job(id='revision-other')
        other['revisionContext']['baseArticle']['id'] = 'article-005'
        runtime = RuntimeDouble([job, other])
        review = self.review_with(runtime)
        self.assertEqual({'status': 'awaiting_astra_review'}, review.prepare_revision(job['id']))
        self.assertEqual([('_context',), ('_make_article', job['id'], {'source': 'bounded'})], runtime.calls)
        self.assertEqual('owner-manual-review', runtime.prepared_job['_source'])
        self.assertEqual(['source', 'review-specification'], runtime.prepared_job['docRoles'])

        rejected = (
            self.revision_job(target='article-002'),
            self.revision_job(stage='review'),
            self.revision_job(approval={'action': 'approved'}),
            self.revision_job(publication={'verified': True}),
        )
        for invalid in rejected:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.review_with(RuntimeDouble([invalid])).prepare_revision(invalid['id'])

        duplicate = self.revision_job(id='revision-duplicate')
        with self.assertRaises(ValueError):
            self.review_with(RuntimeDouble([job, duplicate])).prepare_revision(job['id'])

    def test_deliver_review_is_limited_to_target_revisions_or_two_existing_social_reviews(self):
        revision = self.revision_job(stage='review')
        social = [{'id': id, 'stage': 'social_review', 'kind': 'article',
                   'approval': None, 'publication': {'verified': True},
                   'social': {'approval': None, 'publication': None}}
                  for id in ALLOWED_SOCIAL]
        runtime = RuntimeDouble([revision, *social])
        review = self.review_with(runtime)
        review.deliver_review(revision['id'])
        for job in social:
            review.deliver_review(job['id'])
        self.assertEqual([('deliver', revision['id'], 'article'),
                          *[('deliver', job['id'], 'social') for job in social]], runtime.calls)

        for job in (self.revision_job(target='article-002', stage='review'),
                    {'id': 'article-other', 'stage': 'social_review', 'social': {}},
                    {'id': ALLOWED_SOCIAL[0], 'stage': 'social_approved', 'social': {}}):
            with self.subTest(job=job), self.assertRaises(ValueError):
                self.review_with(RuntimeDouble([job])).deliver_review(job['id'])

    def test_delivery_reconciliation_error_is_not_retried_or_converted(self):
        job = self.revision_job(stage='review')
        runtime = RuntimeDouble([job])
        def stop(*_args, **_kwargs):
            runtime.calls.append(('deliver_attempt',))
            raise ValueError('delivery_requires_reconciliation')
        runtime.deliver = stop
        with self.assertRaisesRegex(ValueError, 'delivery_requires_reconciliation'):
            self.review_with(runtime).deliver_review(job['id'])
        self.assertEqual([('deliver_attempt',)], runtime.calls)


if __name__ == '__main__':
    unittest.main()
