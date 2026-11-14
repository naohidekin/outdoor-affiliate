"""Synthetic contracts for the owner-only review path; no external calls."""
import copy
from contextlib import nullcontext
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from manual_review import ManualReview, REVIEW_SUPPLEMENT_CLAIMS, _ScopedRuntime
from ledger import JST, fingerprint
from revisions import EDIT_FIELDS, validated_context
from runtime import Runtime, atomic
from stage_journal import StageJournal
from test_quality import bundle
from test_revision_workflow import baseline, spec


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


class CompleteReviewJournal:
    def __init__(self, records, outputs):
        self.records = records
        self.outputs = outputs

    key = staticmethod(StageJournal.key)

    def status(self, *, job_id=None, stage=None):
        return {'records': [copy.deepcopy(self.records[stage])]}

    def _load(self, _db, key):
        return key

    def _existing(self, record, key):
        if record != key or key not in self.outputs:
            raise AssertionError('unexpected stage output lookup')
        return copy.deepcopy(self.outputs[key])


class CompleteReviewRuntime:
    def __init__(self, root, repo, job, context, routes):
        self.root = root
        self.config = {'repo': str(repo)}
        self.env = {'AMAZON_PARTNER_TAG': 'camp78-22'}
        self.job = copy.deepcopy(job)
        self.context = copy.deepcopy(context)
        self.routes = copy.deepcopy(routes)
        self.finished = []
        self.usage_saves = 0
        self.ledger = SimpleNamespace(
            get_job=lambda id: copy.deepcopy(self.job),
            _tx=lambda: nullcontext(None))

    def _require_running(self):
        return None

    def request_revisions(self, _specs):
        return {'jobs': [{'id': self.job['id']}]}

    def _context(self):
        return copy.deepcopy(self.context)

    def _model_routes(self):
        return copy.deepcopy(self.routes)

    _source_dependencies = staticmethod(Runtime._source_dependencies)

    def _finish_article_review(self, *args):
        self.finished.append(copy.deepcopy(args))
        return {'status': 'awaiting_astra_review'}

    def _save_usage(self):
        self.usage_saves += 1


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
        self.complete_fixture_count = 0
        self.write_config()

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def review_with(self, runtime):
        review = ManualReview.__new__(ManualReview)
        review._runtime = runtime
        return review

    def complete_review_fixture(self, target='article-024'):
        self.complete_fixture_count += 1
        slug = 'firepit-beginner-guide' if target == 'article-024' else 'single-burner-ranking'
        base = baseline(target, slug)
        if target == 'article-024':
            base['productIds'] = ['fp-003']
        request = spec(base)
        request['baseProducts'][0]['amazonUrl'] = ''
        request['candidateProducts'][0]['amazonUrl'] = ''
        revision_context = validated_context(request)
        job = {
            'id': f'revision-complete-{self.complete_fixture_count}',
            'kind': 'article_revision', 'stage': 'error',
            'error': {'reason': 'article_structure_or_affiliate_failed'},
            'theme': {'slug': base['slug'], 'title': base['title'],
                      'categoryId': base['categoryId'],
                      'productIds': list(revision_context['targetProductIds'])},
            'revisionContext': revision_context,
            'bundle': None, 'review': None, 'approval': None, 'publication': None,
        }
        draft = bundle()
        draft['article']['tags'] = []
        draft['products'] = copy.deepcopy(revision_context['candidateProducts'])
        source_bundle = copy.deepcopy(draft)
        article = copy.deepcopy(base)
        article.update({key: draft['article'][key] for key in EDIT_FIELDS})
        article.update(author=draft['article']['author'],
                       productIds=list(revision_context['targetProductIds']))
        source_bundle.update(article=article, revisionContext=copy.deepcopy(revision_context))
        source_bundle['brief']['protected'] = list(dict.fromkeys(
            source_bundle['brief'].get('protected', []) + revision_context['verifiedAuthorFacts']))
        source_bundle['affiliateConfig'] = {'amazonPartnerTag': 'camp78-22'}
        checked = datetime.now(JST).isoformat()
        products = copy.deepcopy(revision_context['candidateProducts'])
        gathered = {
            'checks': {'facts': True, 'images': True, 'affiliate': True},
            'productIds': list(revision_context['targetProductIds']),
            'products': copy.deepcopy(products), 'catalog': copy.deepcopy(products),
            'evidence': {'products': [
                {'productId': product['id'], 'checkedAt': checked} for product in products
            ]},
        }
        polished = {'model': 'gemini-3.8-flash',
                    'content': source_bundle['article']['content']}
        polish_output = {'polished': copy.deepcopy(polished),
                         'preservation': {'passed': True, 'failures': []}}
        source = {'kind': 'source', 'bundle': copy.deepcopy(source_bundle)}
        candidate = {'kind': 'candidate', 'candidate': copy.deepcopy(polished)}
        artifact_dir = self.base / 'state' / 'research' / 'artifacts' / job['id'] / fingerprint(source_bundle)
        atomic(artifact_dir / 'source.json', source)
        atomic(artifact_dir / 'candidate.json', candidate)
        atomic(self.base / 'state' / 'research' / (job['id'] + '.json'), gathered)
        editorial_rules = {'rule': 'synthetic-review'}
        routes = {'draft': {'requested': 'writer'}, 'polish': {'requested': 'polisher'},
                  'final_review': {'requested': 'reviewer'}}
        runtime = CompleteReviewRuntime(
            self.base / 'state', Path(__file__).resolve().parents[2], job,
            {'editorialRules': editorial_rules}, routes)
        gathered_inputs = copy.deepcopy(gathered)
        gathered_inputs.update({
            'CLAUDE': editorial_rules,
            'SKILL': (Path(runtime.config['repo']) / 'SKILL.md').read_text(),
        })
        source_dependencies = runtime._source_dependencies(gathered_inputs)
        draft_inputs = {
            'theme': copy.deepcopy(job['theme']),
            'dependencies': {
                'source': source_dependencies, 'routes': routes,
                'revisionContext': copy.deepcopy(revision_context),
                'catalogCorrectionContext': None,
            },
            'schemaVersion': {'stage': 1, 'input': 'theme+verified-source',
                              'output': 'article+brief'},
        }
        polish_inputs = {
            'content': source_bundle['article']['content'],
            'brief': copy.deepcopy(source_bundle['brief']),
            'dependencies': {
                'sourceBundle': runtime._source_dependencies(source_bundle),
                'verifiedSource': source_dependencies, 'routes': routes,
            },
            'schemaVersion': {'stage': 1, 'input': 'exact-source+brief',
                              'output': 'polish+preservation'},
        }
        draft_key = StageJournal.key(job['id'], 'draft', draft_inputs)
        polish_key = StageJournal.key(job['id'], 'polish', polish_inputs)
        runtime.stage_journal = CompleteReviewJournal(
            {'draft': {'status': 'succeeded', 'stageKey': draft_key},
             'polish': {'status': 'succeeded', 'stageKey': polish_key}},
            {draft_key: draft, polish_key: polish_output})
        purchase_evidence = [{
            'productId': products[0]['id'], 'channel': 'amazon', 'status': 'NA',
            'reason': '対象型番の取扱いを確認できない', 'checkedAt': checked,
            'reviewedBy': 'owner',
        }]
        return runtime, purchase_evidence

    @staticmethod
    def review_supplement(checked_at=None):
        return {
            'url': 'https://snowpeak-ec.s3.amazonaws.com/sys-master/AmazonS3Images/hd3/h39/'
                   '8879616065566/ST-032RS_manual.pdf',
            'model': 'ST-032RS', 'productId': 'fp-003',
            'sha256': '27b1c4c6f9bda381548f5bc269417748c005827816913bc8564dd55dfda4c5cb',
            'size': 191121, 'contentType': 'application/pdf',
            'checkedAt': checked_at or datetime.now(JST).isoformat(),
            'reviewedBy': 'Astra',
            'claims': list(REVIEW_SUPPLEMENT_CLAIMS),
        }

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

    def test_complete_review_reuses_only_exact_successful_draft_and_polish_inputs(self):
        runtime, purchase_evidence = self.complete_review_fixture()
        result = self.review_with(runtime).complete_review(runtime.job['id'], purchase_evidence)
        self.assertEqual({'status': 'awaiting_astra_review'}, result)
        self.assertEqual(1, len(runtime.finished))
        self.assertEqual(1, runtime.usage_saves)
        source_dependencies = runtime.finished[0][-1]
        self.assertEqual(runtime.context['editorialRules'], source_dependencies['CLAUDE'])
        self.assertEqual((Path(runtime.config['repo']) / 'SKILL.md').read_text(),
                         source_dependencies['SKILL'])

    def test_complete_review_denies_succeeded_record_with_mismatched_stage_key(self):
        for stage in ('draft', 'polish'):
            runtime, purchase_evidence = self.complete_review_fixture()
            runtime.stage_journal.records[stage]['stageKey'] = '0' * 64
            with self.subTest(stage=stage), self.assertRaisesRegex(
                    ValueError, 'manual_review_stage_key_mismatch'):
                self.review_with(runtime).complete_review(runtime.job['id'], purchase_evidence)
            self.assertEqual([], runtime.finished)
            self.assertEqual(0, runtime.usage_saves)

    def test_complete_review_binds_verified_024_supplement_only_to_final_review(self):
        runtime, purchase_evidence = self.complete_review_fixture()
        supplement = self.review_supplement()
        original_outputs = copy.deepcopy(runtime.stage_journal.outputs)
        result = self.review_with(runtime).complete_review(
            runtime.job['id'], purchase_evidence, supplement)
        self.assertEqual({'status': 'awaiting_astra_review'}, result)
        gathered = runtime.finished[0][2]
        source_dependencies = runtime.finished[0][-1]
        self.assertEqual([supplement], gathered['evidence']['reviewSupplements'])
        self.assertEqual([supplement], source_dependencies['evidence']['reviewSupplements'])
        self.assertEqual(original_outputs, runtime.stage_journal.outputs)
        self.assertNotIn('reviewSupplements', runtime.finished[0][4])
        persisted = json.loads((runtime.root / 'research' / (runtime.job['id'] + '.json')).read_text())
        self.assertNotIn('reviewSupplements', persisted['evidence'])

    def test_complete_review_rejects_wrong_target_hash_or_stale_supplement(self):
        cases = []
        runtime, evidence = self.complete_review_fixture(target='article-005')
        cases.append(('target', runtime, evidence, self.review_supplement()))
        runtime, evidence = self.complete_review_fixture()
        wrong_hash = self.review_supplement()
        wrong_hash['sha256'] = '0' * 64
        cases.append(('hash', runtime, evidence, wrong_hash))
        runtime, evidence = self.complete_review_fixture()
        stale = self.review_supplement((datetime.now(JST) - timedelta(hours=6, seconds=1)).isoformat())
        cases.append(('stale', runtime, evidence, stale))
        for name, checked_at in (('none', None), ('naive', '2026-11-15T04:57:00')):
            runtime, evidence = self.complete_review_fixture()
            invalid_time = self.review_supplement()
            invalid_time['checkedAt'] = checked_at
            cases.append((name, runtime, evidence, invalid_time))
        for name, runtime, purchase_evidence, supplement in cases:
            with self.subTest(case=name), self.assertRaisesRegex(
                    ValueError, 'manual_review_supplement_invalid'):
                self.review_with(runtime).complete_review(
                    runtime.job['id'], purchase_evidence, supplement)
            self.assertEqual([], runtime.finished)


if __name__ == '__main__':
    unittest.main()
