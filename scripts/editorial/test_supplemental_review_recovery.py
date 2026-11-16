"""Read-only recovery planning against temporary ledgers; no providers or publication."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import plistlib

from ledger import Ledger, fingerprint
from runtime import JST, atomic
from stage_journal import StageJournal
from supplemental_topics import resolve_batch
from test_supplemental_topics import manifest, product
from test_quality import bundle


class SupplementalReviewRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'state'
        self.now = datetime.now(JST)
        self.ledger = Ledger(self.root, 'owner')
        self.journal = StageJournal(self.ledger)
        batch = manifest()
        batch['slots'][0].update(slug='plasma1000-1101493-layering-guide', title='Plasma', categoryId='wear',
                                query='winter plasma', selectionReason='verified fixture')
        products = [product(batch['slots'][0]['productIds'][0])]
        merchant = bundle()['products'][0]
        products[0].update(affiliateUrl=merchant['affiliateUrl'], amazonUrl=merchant['amazonUrl'])
        products[0]['specs'].update(rakutenOptionState='selectable', amazonOptionState='selectable')
        snapshot = {'checkedAt': self.now.isoformat(), 'products': products, 'articles': []}
        slot = resolve_batch(batch, snapshot, [], self.now)['slots'][0]
        self.job = self.ledger.create_supplemental_candidate(slot['theme'], batch['batchId'], 1,
            slot['sourceBinding'], social_eligible_period='2026-11-20', now=self.now)
        self.batch_path = self.base / 'batch.json'
        self.snapshot = self.base / 'current-source.json'
        self.config = self.base / 'config.json'
        atomic(self.batch_path, batch)
        atomic(self.snapshot, snapshot)
        atomic(self.config, {'stateRoot': str(self.root), 'supplementalApparelBatchManifest': str(self.batch_path)})
        self.source = bundle()
        self.source['products'] = products
        self.source['article'].update(id=self.job['id'], slug=slot['theme']['slug'], content='Old unsupported claim')
        inputs = {'dependencies': {'protocol': 'old'}, 'schemaVersion': 1}
        with self.assertRaises(ValueError):
            self.journal.run(self.job['id'], 'draft', inputs, self.fail)
        initial = self.journal.key(self.job['id'], 'draft', inputs)
        corrected = {'dependencies': {'protocol': 'corrected'}, 'schemaVersion': 1}
        self.journal.retry_corrected_failed(self.job['id'], 'draft', initial, corrected, lambda: self.source)
        self.polished = {'model': 'gemini-3.8-flash', 'content': 'Old unsupported claim'}
        self.journal.run(self.job['id'], 'polish', inputs,
                         lambda: {'polished': self.polished, 'preservation': {'passed': True}})
        with self.assertRaises(ValueError):
            self.journal.run(self.job['id'], 'final_review', inputs, self.fail)
        with self.assertRaises(ValueError):
            self.journal.retry_failed(self.job['id'], 'final_review', inputs, self.fail)
        self.old_key = self.journal.key(self.job['id'], 'final_review', inputs)
        self.ledger.set_stage(self.job['id'], 'error', {'reason': 'ModelError'})
        self.artifacts = self.root / 'research' / 'artifacts' / self.job['id'] / fingerprint(self.source)
        atomic(self.artifacts / 'source.json', {'kind': 'source', 'bundle': self.source})
        atomic(self.artifacts / 'candidate.json', {'kind': 'candidate', 'candidate': self.polished})
        atomic(self.root / 'research' / (self.job['id'] + '.json'), {
            'products': products, 'catalog': products, 'productIds': slot['theme']['productIds'],
            'images': self.source['images'], 'references': self.source['references'],
            'checks': {'facts': True, 'images': True, 'affiliate': True},
            'evidence': {'products': [{'productId': products[0]['id'], 'checkedAt': self.now.isoformat()}]},
        })
        self.proposed = self.base / 'proposed-candidate.json'
        atomic(self.proposed, {'kind': 'candidate', 'candidate': {'content': 'Corrected sourced claim'}})
        self.proof = self.base / 'source-proof.json'
        self.write_proof()
        import supplemental_review_recovery as recovery
        pins = {'JOB_ID': self.job['id'], 'FINAL_KEY': self.old_key,
                'CONFIG_SHA': hashlib.sha256(self.config.read_bytes()).hexdigest(),
                'SOURCE_DIR': fingerprint(self.source),
                'SOURCE_SHA': hashlib.sha256((self.artifacts / 'source.json').read_bytes()).hexdigest(),
                'CANDIDATE_SHA': hashlib.sha256((self.artifacts / 'candidate.json').read_bytes()).hexdigest()}
        for name, value in pins.items():
            patcher = patch.object(recovery, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        diagnostic_dir = self.root / recovery.DIAGNOSTIC_DIR
        atomic(diagnostic_dir / 'provider-diagnostic.json', {'httpStatus': 400,
            'providerCategory': 'invalid_request_error', 'reasonClass': 'schema',
            'requestedModel': 'claude-sonnet-4-6'})
        (diagnostic_dir / 'operation.plist').write_bytes(plistlib.dumps({'ProgramArguments': [
            'python', '--job-id', self.job['id'], '--input-key', self.old_key,
            '--stage', 'final_review', '--state-root', str(self.root)]}))

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def fail():
        raise ValueError('HTTP 400')

    def write_proof(self):
        import hashlib
        atomic(self.proof, {'jobId': self.job['id'], 'sourceBinding': self.job['sourceBinding'],
            'proposedCandidateSha256': hashlib.sha256(self.proposed.read_bytes()).hexdigest(),
            'corrections': [{'removed': 'Old unsupported claim', 'replacement': 'Corrected sourced claim',
                             'sources': ['https://maker.example/verified']}],
        })

    def prepare(self):
        from supplemental_review_recovery import prepare
        return prepare(self.config, self.job['id'], self.old_key, self.proposed, self.proof,
                       self.snapshot, now=self.now)

    def test_prepare_pins_proposal_and_requires_new_gemini_and_owner_grant_without_mutation(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.prepare()
        self.assertEqual('held_for_owner_decision', result['status'])
        self.assertTrue(result['bodyChanged'])
        self.assertTrue(result['required']['newGemini'])
        self.assertTrue(result['required']['ownerGrant'])
        self.assertTrue(result['required']['independentSourceReview'])
        self.assertEqual([], result['blockers'])
        self.assertEqual({'articleCalls': 32, 'periodCalls': 128, 'batchCalls': 96}, result['caps'])
        self.assertNotIn('ownerAuthorizationReference', result)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_unchanged_body_is_held_for_unsupported_claim_correction(self):
        atomic(self.proposed, {'kind': 'candidate', 'candidate': {'content': self.polished['content']}})
        self.write_proof()
        result = self.prepare()
        self.assertIn('unsupported_claim_corrections_required', result['blockers'])
        self.assertTrue(result['required']['ownerGrant'])

    def test_stale_future_or_changed_source_is_reported_without_repairing_it(self):
        for change in ('stale', 'future', 'products'):
            snapshot = json.loads(self.snapshot.read_text())
            if change == 'products':
                snapshot['products'][0]['name'] = 'Different canonical product'
            else:
                snapshot['checkedAt'] = (self.now + timedelta(hours=1) if change == 'future'
                                         else self.now - timedelta(hours=7)).isoformat()
            atomic(self.snapshot, snapshot)
            with self.subTest(change=change):
                self.assertTrue(self.prepare()['blockers'])

    def test_proposal_proof_binding_and_artifact_integrity_fail_closed(self):
        self.proposed.write_text(self.proposed.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'proposal_proof_binding'):
            self.prepare()
        self.write_proof()
        candidate = copy.deepcopy(self.polished)
        candidate['content'] = 'Tampered stored polish'
        atomic(self.artifacts / 'candidate.json', {'kind': 'candidate', 'candidate': candidate})
        with self.assertRaisesRegex(ValueError, 'pinned_original_artifacts_required'):
            self.prepare()

    def test_other_batch_bundle_and_wrong_failed_key_are_rejected(self):
        self.old_key = 'stage_journal:v1:wrong'
        with self.assertRaises(ValueError):
            self.prepare()
        with self.ledger._tx() as db:
            job = self.ledger._get(db, self.job['id'])
            job['bundle'] = {}
            self.ledger._put(db, job, 'fixture')
        with self.assertRaises(ValueError):
            self.prepare()

    def execution_fixture(self, response_error=None, review_mean=8):
        import supplemental_review_recovery as recovery
        from runtime import Runtime
        from models import Models, CRITERIA_FIELDS
        from test_models import bundle as writer_bundle, writer_response, response, Fake, ENV, REVIEW
        from test_runtime import SlackFake
        from apparel_identity import apparel_contract, merchant_contract
        config = json.loads(self.config.read_text())
        env = self.base / 'env'
        env.write_text('AMAZON_PARTNER_TAG=camp78-22\n')
        config.update(repo=str(Path(__file__).resolve().parents[2]), envFile=str(env),
                      slack=dict(team_id='T', app_id='A', user_id='owner', channel_id='C', thread_ts='1.1'),
                      spoolDir=str(self.base / 'spool'), generationEnabled=True, publicationEnabled=True)
        Path(config['spoolDir']).mkdir()
        atomic(self.config, config)
        patcher = patch.object(recovery, 'CONFIG_SHA', hashlib.sha256(self.config.read_bytes()).hexdigest())
        patcher.start()
        self.addCleanup(patcher.stop)
        gathered = json.loads((self.root / 'research' / (self.job['id'] + '.json')).read_text())
        product = gathered['products'][0]
        gathered['images'] = [{'productId': product['id'], 'url': product['imageUrl'], 'verified': True,
                              'apparelBinding': dict(apparel_contract(product), sourceKind='json-ld-product',
                                  colors=['BK'], sizes=['S'], imageUrls=[product['imageUrl']])}]
        binding = gathered['images'][0]['apparelBinding']
        gathered['references'] = [{'url': 'https://maker.example/verified', 'checkedAt': self.now.isoformat(),
                                  'productId': product['id'], 'kind': 'manufacturer', 'apparelBinding': binding}]
        for channel in ('rakuten', 'amazon'):
            gathered['references'].append({'url': 'https://merchant.example/' + channel,
                'checkedAt': self.now.isoformat(), 'productId': product['id'], 'kind': 'purchase',
                'channel': channel, 'apparelBinding': dict(binding, **merchant_contract(product, channel),
                    sourceKind=channel + '-primary-product-dom')})
        gathered['existingArticles'] = [{'slug': slug} for slug in ('setup', 'pack')]
        data = writer_bundle()
        data['article'].update(slug=self.job['theme']['slug'], categoryId='wear',
            productIds=[product['id']], title='Plasma source guide',
            content=data['article']['content'].replace('tent-a', product['id']))
        data['brief']['protected'] = ['{{product:' + product['id'] + '}}']
        upper = dict(REVIEW, wiseScores=dict(w=3,i=3,s=3,e=3,ai=3,sense=3),
                     criteria=dict.fromkeys(CRITERIA_FIELDS, review_mean), observations=[], evidence={'summary': 'Checked'})
        answers = [writer_response(data), response({'edits': []}, gemini=True), response(upper)]
        for i, value in enumerate(answers):
            value['id'] = 'new-owner-response-' + str(i)
        if response_error:
            answers[0] = response_error
        request = Fake(*answers)
        class Catalog:
            def catalog(inner):
                return json.loads(self.snapshot.read_text())
            def gather(inner, theme, context):
                return copy.deepcopy(gathered)
        self.slack = SlackFake()
        self.published = []
        runtime = Runtime(config, models=Models(ENV, request), catalog=Catalog(), slack=self.slack,
            renderer=lambda *_: {'passed': True, 'clicksVerified': {'desktop': [1], 'mobile': [1]}},
            publisher=lambda action, job: self.published.append((action, job['id'])))
        plan = self.prepare()
        grant = {'reference': recovery.AUTHORIZATION, 'answer': recovery.OWNER_ANSWER,
                 'jobId': self.job['id'], 'manifestSha256': fingerprint(plan)}
        return runtime, plan, grant, request

    def test_granted_executor_runs_real_models_and_normal_gates_once_without_touching_old_stages(self):
        import supplemental_review_recovery as recovery
        runtime, plan, grant, request = self.execution_fixture()
        with self.ledger._tx() as db:
            old = dict(db.execute("SELECT key,value FROM meta WHERE key LIKE 'stage_journal:v1:%'"))
        result = recovery.execute(runtime, plan, owner_grant=grant)
        self.assertEqual(3, len(request.calls))
        self.assertEqual('review', self.ledger.get_job(self.job['id'])['stage'])
        self.assertIsNone(self.ledger.get_job(self.job['id'])['approval'])
        self.assertIsNone(self.ledger.get_job(self.job['id'])['publication'])
        self.assertEqual([('stage', self.job['id'])], self.published)
        self.assertEqual(1, len(self.slack.deliveries))
        with self.ledger._tx() as db:
            for key, value in old.items():
                self.assertEqual(value, db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            receipt = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (recovery.RECEIPT_KEY,)).fetchone()[0])
            budget = db.execute('SELECT article_id,stage FROM model_budget_reservations').fetchall()
        self.assertEqual('completed', receipt['status'])
        self.assertEqual([(self.job['id'], s) for s in ('draft', 'polish', 'final_review')], budget)
        new = [r for r in self.journal.status(job_id=self.job['id'])['records'] if 'owner_oneoff' in r['stage']]
        self.assertEqual(3, len(new))
        self.assertTrue(all(r['maxAttempts'] == r['attempts'] == r['responseReceiptCount'] == 1 for r in new))
        with self.assertRaises(ValueError):
            recovery.execute(runtime, plan, owner_grant=grant)
        self.assertEqual(3, len(request.calls))

    def test_crash_claim_is_durable_and_cannot_be_rerun_after_restart(self):
        import supplemental_review_recovery as recovery
        runtime, plan, grant, request = self.execution_fixture()
        with patch.object(runtime.catalog, 'catalog', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                recovery.execute(runtime, plan, owner_grant=grant)
        self.assertEqual([], request.calls)
        with self.ledger._tx() as db:
            record = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (recovery.RECEIPT_KEY,)).fetchone()[0])
        self.assertEqual('requires_reconciliation', record['status'])
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(runtime, plan, owner_grant=grant)

    def test_new_model_failure_preserves_actual_safe_reason_and_historical_failure(self):
        import supplemental_review_recovery as recovery
        from test_models import http
        runtime, plan, grant, request = self.execution_fixture(response_error=http(400))
        with self.assertRaises(Exception):
            recovery.execute(runtime, plan, owner_grant=grant)
        error = self.ledger.get_job(self.job['id'])['error']
        self.assertEqual('provider_http_400', error['reason'])
        self.assertEqual({'reason': 'ModelError'}, error['originalFailure'])
        self.assertEqual(1, len(request.calls))
        new = [r for r in self.journal.status(job_id=self.job['id'])['records'] if 'owner_oneoff' in r['stage']]
        self.assertEqual([('failed', 1, 1)], [(r['status'], r['attempts'], r['maxAttempts']) for r in new])
        with self.assertRaises(ValueError):
            recovery.execute(runtime, plan, owner_grant=grant)
        self.assertEqual(1, len(request.calls))

    def test_review_pass_assertion_cannot_bypass_local_eleven_score_mean(self):
        import supplemental_review_recovery as recovery
        runtime, plan, grant, request = self.execution_fixture(review_mean=6)
        with self.assertRaises(ValueError):
            recovery.execute(runtime, plan, owner_grant=grant)
        job = self.ledger.get_job(self.job['id'])
        self.assertEqual('error', job['stage'])
        self.assertEqual('final_review_failed', job['error']['reason'])
        self.assertEqual({'reason': 'ModelError'}, job['error']['originalFailure'])
        self.assertEqual([], self.published)
        self.assertEqual([], self.slack.deliveries)
        self.assertEqual(3, len(request.calls))

    def test_existing_article_budget_remains_32_even_with_owner_grant(self):
        import supplemental_review_recovery as recovery
        runtime, plan, grant, request = self.execution_fixture()
        with runtime.model_budget.scope(self.job['id'], 'draft'):
            for _ in range(32):
                runtime.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
        from model_budget import BudgetHold
        with self.assertRaises(BudgetHold):
            recovery.execute(runtime, plan, owner_grant=grant)
        self.assertEqual([], request.calls)
        self.assertEqual('model_budget_hold', self.ledger.get_job(self.job['id'])['error']['reason'])

    def test_gui_lock_busy_does_not_claim_or_call_models(self):
        import supplemental_review_recovery as recovery
        import fcntl
        runtime, plan, grant, request = self.execution_fixture()
        with (self.root / 'runtime.flock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual({'status': 'busy', 'executed': False},
                             recovery.execute(runtime, plan, owner_grant=grant))
        self.assertEqual([], request.calls)
        with self.ledger._tx() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM meta WHERE key=?', (recovery.RECEIPT_KEY,)).fetchone())

    def test_execute_refuses_missing_or_unbound_owner_grant_before_any_runtime_use(self):
        import supplemental_review_recovery as recovery
        from types import SimpleNamespace
        for grant in (None, {}, {'reference': 'arbitrary-string'}):
            with self.subTest(grant=grant), self.assertRaises(ValueError):
                recovery.execute(SimpleNamespace(), self.prepare(), owner_grant=grant)

    def test_execute_is_not_a_generic_other_slot_or_config_cap_bypass(self):
        import supplemental_review_recovery as recovery
        plan = self.prepare()
        plan['jobId'] = 'other-job'
        grant = {'reference': recovery.AUTHORIZATION, 'answer': recovery.OWNER_ANSWER,
                 'jobId': plan['jobId'], 'manifestSha256': fingerprint(plan)}
        with self.assertRaises(ValueError):
            recovery.execute(None, plan, owner_grant=grant)


if __name__ == '__main__':
    unittest.main()
