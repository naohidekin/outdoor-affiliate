"""Read-only recovery planning against temporary ledgers; no providers or publication."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import supplemental_pair_recovery as recovery

from ledger import Ledger, fingerprint
from runtime import JST, atomic
from stage_journal import StageJournal
from supplemental_topics import resolve_batch
from test_supplemental_topics import manifest, product
from test_quality import bundle


class PairRecoveryTests(unittest.TestCase):
    SLOT = 2
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'state'
        self.now = datetime.now(JST)
        self.ledger = Ledger(self.root, 'owner')
        self.journal = StageJournal(self.ledger)
        batch = manifest()
        batch['slots'][self.SLOT - 1].update(slug=list(recovery.JOBS.values())[self.SLOT - 2]['slug'], title='Plasma', categoryId='wear',
                                query='winter plasma', selectionReason='verified fixture')
        products = [product(batch['slots'][self.SLOT - 1]['productIds'][0])]
        merchant = bundle()['products'][0]
        products[0].update(affiliateUrl=merchant['affiliateUrl'], amazonUrl=merchant['amazonUrl'])
        products[0]['specs'].update(rakutenOptionState='selectable', amazonOptionState='selectable')
        snapshot = {'checkedAt': self.now.isoformat(), 'products': products, 'articles': []}
        slot = resolve_batch(batch, snapshot, [], self.now)['slots'][self.SLOT - 1]
        self.job = self.ledger.create_supplemental_candidate(slot['theme'], batch['batchId'], self.SLOT,
            slot['sourceBinding'], social_eligible_period='2026-11-20', now=self.now)
        with self.ledger._tx() as db:
            db.execute('DELETE FROM jobs WHERE id=?', (self.job['id'],))
            self.job.update(id=list(recovery.JOBS)[self.SLOT - 2], week='2026-11-13')
            self.ledger._put(db, self.job, 'fixture')
        self.batch_path = self.base / 'batch.json'
        self.snapshot = self.base / 'current-source.json'
        self.config = self.base / 'config.json'
        atomic(self.batch_path, batch)
        atomic(self.snapshot, snapshot)
        atomic(self.config, {'stateRoot': str(self.root), 'supplementalApparelBatchManifest': str(self.batch_path)})
        self.source = bundle()
        self.source['brief']['format'] = 'guide'
        self.source['products'] = products
        self.source['article'].update(id=self.job['id'], slug=slot['theme']['slug'], content='Old unsupported claim')
        inputs = {'dependencies': {'protocol': 'old'}, 'schemaVersion': 1}
        with self.assertRaises(ValueError):
            self.journal.run(self.job['id'], 'draft', inputs, self.fail_operation)
        initial = self.journal.key(self.job['id'], 'draft', inputs)
        corrected = {'dependencies': {'protocol': 'corrected'}, 'schemaVersion': 1}
        self.journal.retry_corrected_failed(self.job['id'], 'draft', initial, corrected, lambda: self.source)
        self.polished = {'model': 'gemini-3.8-flash', 'content': 'Old unsupported claim'}
        self.journal.run(self.job['id'], 'polish', inputs,
                         lambda: {'polished': self.polished, 'preservation': {'passed': True}})
        with self.assertRaises(ValueError):
            self.journal.run(self.job['id'], 'final_review', inputs, self.fail_operation)
        self.old_key = self.journal.key(self.job['id'], 'final_review', inputs)
        self.ledger.set_stage(self.job['id'], 'error', {'reason': 'final_review_failed'})
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
        atomic(self.proposed, {'kind': 'correction-plan', 'approvedWritingBrief': {'purpose': 'Correct sourced claims'}})
        self.proof = self.base / 'source-proof.json'
        self.write_proof()
        self.fresh = self.base / 'fresh-research.json'
        self.fresh.write_bytes((self.root / 'research' / (self.job['id'] + '.json')).read_bytes())
        historical = json.loads(self.fresh.read_text())
        historical['evidence']['products'][0]['checkedAt'] = (self.now - timedelta(days=3)).isoformat()
        atomic(self.root / 'research' / (self.job['id'] + '.json'), historical)
        pins = copy.deepcopy(recovery.JOBS)
        pins[self.job['id']].update(final=self.old_key, directory=fingerprint(self.source),
            source=hashlib.sha256((self.artifacts / 'source.json').read_bytes()).hexdigest(),
            candidate=hashlib.sha256((self.artifacts / 'candidate.json').read_bytes()).hexdigest())
        for name, value in [('OWNER_DATE', self.now.date().isoformat()), ('JOBS', pins),
                            ('CONFIG_SHA', hashlib.sha256(self.config.read_bytes()).hexdigest())]:
            patcher = patch.object(recovery, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.ledger._tx() as db:
            db.execute('INSERT INTO meta VALUES (?,?)',
                ('supplemental_manual_recovery:v1:plasma-20261117', '{"status":"completed","attempts":1}'))
    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def fail_operation():
        raise ValueError('HTTP 400')

    def write_proof(self):
        import hashlib
        atomic(self.proof, {'jobId': self.job['id'], 'sourceBinding': self.job['sourceBinding'],
            'proposedCandidateSha256': hashlib.sha256(self.proposed.read_bytes()).hexdigest(),
            'corrections': [{'removed': 'Old unsupported claim', 'replacement': 'Corrected sourced claim',
                             'sources': ['https://maker.example/verified']}],
        })

    def prepare(self):
        from supplemental_pair_recovery import prepare
        return prepare(self.config, self.job['id'], self.old_key, self.proposed, self.proof,
                       self.snapshot, self.fresh, now=self.now)

    def execution_fixture(self, response_error=None, review_mean=8):
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
        gathered = json.loads(self.fresh.read_text())
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

    def test_prepare_readonly_with_historical_stale_evidence(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual([], self.prepare()['blockers'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_normal_pipeline_preserves_plasma_and_history_and_claims_once(self):
        rt, plan, grant, request = self.execution_fixture()
        with self.ledger._tx() as db:
            old = dict(db.execute('SELECT key,value FROM meta'))
        result = recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual('delivered', result['status'])
        self.assertEqual(3, len(request.calls))
        self.assertEqual([('stage', self.job['id'])], self.published)
        self.assertEqual(1, len(self.slack.deliveries))
        job = self.ledger.get_job(self.job['id'])
        self.assertEqual('review', job['stage'])
        self.assertIsNone(job['approval'])
        self.assertIsNone(job['publication'])
        with self.ledger._tx() as db:
            for key, value in old.items():
                self.assertEqual(value, db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            self.assertEqual([('draft',), ('polish',), ('final_review',)],
                db.execute('SELECT stage FROM model_budget_reservations').fetchall())
        new = [r for r in self.journal.status(job_id=self.job['id'])['records'] if 'owner_oneoff' in r['stage']]
        self.assertEqual(3, len(new))
        self.assertTrue(all(r['attempts'] == r['maxAttempts'] == 1 for r in new))
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual(3, len(request.calls))

    def test_wrong_grant_job_config_and_failed_key_rejected(self):
        for grant in (None, {}, {'reference': 'wrong'}):
            with self.assertRaises(ValueError):
                recovery.execute(None, self.prepare(), owner_grant=grant)
        with self.assertRaises(ValueError):
            recovery.prepare(self.config, 'arbitrary', self.old_key, self.proposed,
                self.proof, self.snapshot, self.fresh)
        old = self.old_key
        self.old_key = 'wrong'
        with self.assertRaises(ValueError):
            self.prepare()
        self.old_key = old
        self.config.write_text(self.config.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'exact_config'):
            self.prepare()

    def test_stale_future_or_changed_fresh_evidence_rejected(self):
        for change in ('stale', 'future', 'products'):
            original = self.fresh.read_bytes()
            value = json.loads(original)
            if change == 'products':
                value['products'][0]['name'] = 'Changed'
            else:
                value['evidence']['products'][0]['checkedAt'] = (self.now + timedelta(hours=1)
                    if change == 'future' else self.now - timedelta(days=3)).isoformat()
            atomic(self.fresh, value)
            with self.assertRaises(ValueError):
                self.prepare()
            self.fresh.write_bytes(original)

    def test_manifest_tamper_before_claim(self):
        rt, plan, grant, request = self.execution_fixture()
        self.proposed.write_text(self.proposed.read_text() + ' ')
        with self.assertRaises(ValueError):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)
        with self.ledger._tx() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM meta WHERE key=?',
                (recovery.receipt_key(self.job['id']),)).fetchone())

    def test_budget_cap_unchanged(self):
        rt, plan, grant, request = self.execution_fixture()
        with rt.model_budget.scope(self.job['id'], 'draft'):
            for _ in range(32):
                rt.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
        from model_budget import BudgetHold
        with self.assertRaises(BudgetHold):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)

    def test_low_grade_has_no_reroll_or_delivery(self):
        rt, plan, grant, request = self.execution_fixture(review_mean=6)
        with self.assertRaisesRegex(ValueError, 'final_review_failed'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], self.published)
        self.assertEqual([], self.slack.deliveries)
        self.assertEqual(3, len(request.calls))
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(rt, plan, owner_grant=grant)

    def test_crash_claim_durable(self):
        rt, plan, grant, request = self.execution_fixture()
        with patch.object(rt.catalog, 'catalog', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                recovery.execute(rt, plan, owner_grant=grant)
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)

    def test_publish_social_approval_and_other_job_forbidden(self):
        rt, plan, grant, request = self.execution_fixture()
        view = recovery._PairRuntime(rt, plan, {'content': 'old'})
        for method in ('tick', 'consume', '_publish', 'publish_social', 'publish_buffer_social',
                       'approve_from_codex', 'retry', 'make_social', 'produce'):
            with self.assertRaisesRegex(ValueError, 'forbidden'):
                getattr(view, method)()
        with self.assertRaisesRegex(ValueError, 'publish_forbidden'):
            view.publisher('publish', self.job)
        with self.assertRaisesRegex(ValueError, 'delivery_forbidden'):
            view.deliver(self.job['id'], 'social')
        with self.assertRaisesRegex(ValueError, 'stage_forbidden'):
            view._run_model_stage({'id': 'other'}, 'draft', {}, lambda: None, 'claude-sonnet-4-6')
        self.assertEqual([], request.calls)


class ChameeceRecoveryTests(PairRecoveryTests):
    SLOT = 3


if __name__ == '__main__':
    unittest.main()
