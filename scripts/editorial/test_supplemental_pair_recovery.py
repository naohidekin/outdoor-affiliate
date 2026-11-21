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
        upper = dict({key: value for key, value in REVIEW.items() if key not in ('score', 'passed')},
                     wiseScores=dict(w=3,i=3,s=3,e=3,ai=(3 if review_mean>=7.5 else 2),sense=3),
                     criteria=dict.fromkeys([k for k in CRITERIA_FIELDS if k!='word_count'], review_mean), improvementFeedback=([{'criterion':'wise_s','quote':data['article']['content'].split('\n\n')[0][:20],'anchor':'evidence-grounded problem','nextAction':'Explain the concrete reader decision.'}] if review_mean<7.5 else []), observations=[], evidence={'summary': 'Checked'})
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


class SourceOnlyRecoveryTests(PairRecoveryTests):
    def source_fixture(self, mean=8):
        from test_models import Fake
        from models import CRITERIA_FIELDS
        rt, original, old_grant, first = self.execution_fixture(review_mean=6)
        answers = copy.deepcopy(first.results)
        # Mark the previous generation's prose and brief, not fresh sources.
        old_writer = json.loads(first.results[0]['content'][0]['text'])
        old_writer['article']['content'] += '\nLEGACY_BODY_SENTINEL'
        old_writer['brief']['purpose'] = 'LEGACY_BRIEF_SENTINEL'
        first.results[0]['content'][0]['text'] = json.dumps(old_writer)
        with self.assertRaisesRegex(ValueError, 'final_review_failed'):
            recovery.execute(rt, original, owner_grant=old_grant)
        previous_prefix = 'owner_oneoff:' + recovery.AUTHORIZATION + ':'
        records = self.journal.status(job_id=self.job['id'])['records']
        failed = next(r for r in records if r['stage'] == previous_prefix + 'final_review')
        artifact = next(p.parent for p in (self.root / 'research' / 'artifacts' / self.job['id']).glob('*/source.json')
                        if 'LEGACY_BODY_SENTINEL' in p.read_text())
        pins = copy.deepcopy(recovery.SOURCE_ONLY_JOBS)
        pins[self.job['id']] = dict(final=failed['stageKey'], directory=artifact.name,
            source=hashlib.sha256((artifact / 'source.json').read_bytes()).hexdigest(),
            candidate=hashlib.sha256((artifact / 'candidate.json').read_bytes()).hexdigest())
        patcher = patch.object(recovery, 'SOURCE_ONLY_JOBS', pins)
        patcher.start()
        self.addCleanup(patcher.stop)
        atomic(self.proposed, {'kind': 'correction-plan',
                              'approvedWritingBrief': {'purpose': 'FRESH_BRIEF_SENTINEL'}})
        self.write_proof()
        plan = recovery.prepare(self.config, self.job['id'], failed['stageKey'], self.proposed,
            self.proof, self.snapshot, self.fresh, phase='source_only')
        for i, answer in enumerate(answers):
            answer['id'] = 'source-only-response-' + str(i)
        upper = json.loads(answers[2]['content'][0]['text'])
        upper['criteria'] = dict.fromkeys([k for k in CRITERIA_FIELDS if k!='word_count'], mean)
        upper['wiseScores']['ai'] = 3 if mean>=7.5 else 2
        upper['improvementFeedback'] = ([{'criterion':'wise_s','quote':json.loads(answers[0]['content'][0]['text'])['article']['content'].split('\n\n')[0][:20],'anchor':'grounded concern','nextAction':'Explain the concrete source-bound choice.'}] if mean<7.5 else [])
        answers[2]['content'][0]['text'] = json.dumps(upper)
        request = Fake(*answers)
        rt.models.request = request
        grant = dict(reference=recovery.SOURCE_ONLY_AUTHORIZATION, answer=recovery.SOURCE_ONLY_ANSWER,
                     jobId=self.job['id'], manifestSha256=fingerprint(plan))
        return rt, plan, grant, request, old_grant

    def test_source_only_normal_pipeline_has_no_legacy_context_and_preserves_history(self):
        rt, plan, grant, request, _ = self.source_fixture()
        with self.ledger._tx() as db:
            old = dict(db.execute('SELECT key,value FROM meta'))
        self.assertEqual('delivered', recovery.execute(rt, plan, owner_grant=grant)['status'])
        self.assertEqual(3, len(request.calls))
        payloads = json.dumps(request.calls, ensure_ascii=False)
        self.assertIn('FRESH_BRIEF_SENTINEL', payloads)
        self.assertNotIn('LEGACY_BODY_SENTINEL', payloads)
        self.assertNotIn('LEGACY_BRIEF_SENTINEL', payloads)
        with self.ledger._tx() as db:
            for key, value in old.items():
                self.assertEqual(value, db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            self.assertEqual(6, db.execute('SELECT count(*) FROM model_budget_reservations').fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual(3, len(request.calls))

    def test_source_only_cross_grant_and_unknown_phase_denied(self):
        rt, plan, grant, request, old_grant = self.source_fixture()
        old_grant['manifestSha256'] = fingerprint(plan)
        for bad_plan, bad_grant in [(plan, old_grant), (dict(plan, phase='arbitrary'), grant),
                                    (dict(plan, phase='original'), grant)]:
            with self.assertRaises(ValueError):
                recovery.execute(None, bad_plan, owner_grant=bad_grant)
        self.assertEqual([], request.calls)

    def test_source_only_budget_and_low_quality_have_no_extra_retry(self):
        rt, plan, grant, request, _ = self.source_fixture(mean=6)
        with self.assertRaisesRegex(ValueError, 'final_review_failed'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], self.published)
        self.assertEqual([], self.slack.deliveries)
        self.assertEqual(3, len(request.calls))
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(rt, plan, owner_grant=grant)

    def test_source_only_requires_intact_prior_claim_and_failed_stage(self):
        rt, plan, grant, request, _ = self.source_fixture()
        old_key = recovery.receipt_key(self.job['id'])
        with self.ledger._tx() as db:
            raw = db.execute('SELECT value FROM meta WHERE key=?', (old_key,)).fetchone()[0]
            value = json.loads(raw)
            value['status'] = 'completed'
            db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(value), old_key))
        with self.assertRaisesRegex(ValueError, 'previous_grant_failed_quality_required'):
            recovery.execute(rt, plan, owner_grant=grant)
        with self.ledger._tx() as db:
            db.execute('UPDATE meta SET value=? WHERE key=?', (raw, old_key))
            key = plan['oldFailedKey']
            record = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            record['attempts'] = 2
            db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(record), key))
        with self.assertRaisesRegex(ValueError, 'exact_failed_review_required'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)
        with self.ledger._tx() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM meta WHERE key=?',
                (recovery.receipt_key(self.job['id'], 'source_only'),)).fetchone())

    def test_source_only_existing_budget_still_holds(self):
        rt, plan, grant, request, _ = self.source_fixture()
        with rt.model_budget.scope(self.job['id'], 'draft'):
            for _ in range(29):
                rt.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
        from model_budget import BudgetHold
        with self.assertRaises(BudgetHold):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)


class ChameeceSourceOnlyRecoveryTests(SourceOnlyRecoveryTests):
    SLOT = 3


class CompletionRecoveryTests(SourceOnlyRecoveryTests):
    def completion_fixture(self, mean=8):
        rt, source_plan, source_grant, request, _ = self.source_fixture(mean=6)
        self.completion_answers = copy.deepcopy(request.results)
        with self.assertRaisesRegex(ValueError, 'final_review_failed'):
            recovery.execute(rt, source_plan, owner_grant=source_grant)
        return self.next_completion(rt, 1, mean)

    def next_completion(self, rt, sequence, mean=8):
        from test_models import Fake
        from models import CRITERIA_FIELDS
        job = self.ledger.get_job(self.job['id'])
        previous_key = job['error']['ownerRecoveryReceipt']
        with self.ledger._tx() as db:
            receipt = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (previous_key,)).fetchone()[0])
        namespace = 'owner_oneoff:' + receipt['ownerGrant']['reference'] + ':'
        if receipt.get('planSha256'):
            namespace += receipt['planSha256'] + ':'
        records = self.journal.status(job_id=self.job['id'])['records']
        draft = next(r for r in records if r['stage'] in (namespace + 'draft', namespace + 'literal_correction'))
        failed = next(r for r in records if r['stage'] == namespace + 'final_review')
        with self.ledger._tx() as db:
            draft = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (draft['stageKey'],)).fetchone()[0])
        artifact = next(p.parent for p in (self.root / 'research' / 'artifacts' / self.job['id']).glob('*/source.json')
                        if json.loads(p.read_text())['bundle']['article']['content'] == draft['output']['article']['content'])
        self.proposed = self.base / ('completion-' + str(sequence) + '-proposal.json')
        self.proof = self.base / ('completion-' + str(sequence) + '-proof.json')
        atomic(self.proposed, {'kind': 'correction-plan', 'approvedWritingBrief': {
            'purpose': 'Repair purchase anchors and clarify buyer choices ' + str(sequence)},
            'completionPlan': {'diagnosis': {'scoringInconsistency': 'No threshold exemption; eleven-score mean applies',
                'bodyQuality': 'Purchase links and concrete buying explanations need correction'},
                'changes': [{'target': 'purchase_links',
                    'change': 'Use exact canonical tracked destinations and explain confirmed variants ' + str(sequence)}]}})
        self.write_proof()
        proof = json.loads(self.proof.read_text())
        proof['historicalArtifacts'] = dict(directory=artifact.name,
            source=hashlib.sha256((artifact / 'source.json').read_bytes()).hexdigest(),
            candidate=hashlib.sha256((artifact / 'candidate.json').read_bytes()).hexdigest())
        atomic(self.proof, proof)
        plan = recovery.prepare(self.config, self.job['id'], failed['stageKey'], self.proposed,
            self.proof, self.snapshot, self.fresh, phase='completion')
        answers = copy.deepcopy(self.completion_answers)
        for i, answer in enumerate(answers):
            answer['id'] = 'completion-' + str(sequence) + '-response-' + str(i)
        writer = json.loads(answers[0]['content'][0]['text'])
        writer['article']['content'] += '\n新しい購入先の確認事項を説明します。' + str(sequence)
        answers[0]['content'][0]['text'] = json.dumps(writer)
        upper = json.loads(answers[2]['content'][0]['text'])
        upper['criteria'] = dict.fromkeys([k for k in CRITERIA_FIELDS if k!='word_count'], mean)
        upper['wiseScores']['ai'] = 3 if mean>=7.5 else 2
        upper['improvementFeedback'] = ([{'criterion':'wise_s','quote':json.loads(answers[0]['content'][0]['text'])['article']['content'].split('\n\n')[0][:20],'anchor':'grounded concern','nextAction':'Explain the concrete source-bound choice.'}] if mean<7.5 else [])
        answers[2]['content'][0]['text'] = json.dumps(upper)
        request = Fake(*answers)
        rt.models.request = request
        grant = dict(reference=recovery.COMPLETION_AUTHORIZATION, answer=recovery.COMPLETION_ANSWER,
                     jobId=self.job['id'], manifestSha256=fingerprint(plan))
        return rt, plan, grant, request

    def literal_fixture(self, mean=8, faq_only=False):
        rt, first_plan, first_grant, request = self.completion_fixture(mean=6)
        writer = json.loads(request.results[0]['content'][0]['text'])
        writer['article']['content'] += '\n根拠のない保証を加えた説明です。'
        writer['article']['faqs'][0]['answer'] += '仕様で保証されない説明です。'
        request.results[0]['content'][0]['text'] = json.dumps(writer)
        original_brief = copy.deepcopy(writer['brief'])
        prior_brief = json.loads(self.proposed.read_text())['approvedWritingBrief']
        with self.assertRaisesRegex(ValueError, 'final_review_failed'):
            recovery.execute(rt, first_plan, owner_grant=first_grant)
        rt, _, _, next_request = self.next_completion(rt, 2, mean)
        proposal = json.loads(self.proposed.read_text())
        proposal['approvedWritingBrief'] = prior_brief  # A deletion need not rebrief the writer.
        atomic(self.proposed, proposal)
        proof = json.loads(self.proof.read_text())
        proof['proposedCandidateSha256'] = hashlib.sha256(self.proposed.read_bytes()).hexdigest()
        atomic(self.proof, proof)
        pins = proof['historicalArtifacts']
        artifact = self.root / 'research' / 'artifacts' / self.job['id'] / pins['directory']
        article = json.loads((artifact / 'source.json').read_text())['bundle']['article']
        article['content'] = json.loads((artifact / 'candidate.json').read_text())['candidate']['content']
        replacements = [{'path': 'article.faqs.0.answer', 'old': '仕様で保証されない説明です。', 'new': '', 'count': 1}]
        if not faq_only:
            replacements.append({'path': 'article.content', 'old': '根拠のない保証を加えた説明です。', 'new': '', 'count': 1})
        correction = {'jobId': self.job['id'], 'sourceBinding': self.job['sourceBinding'],
            'candidateArtifactSha256': pins['candidate'], 'articleSha256': fingerprint(article),
            'replacements': replacements}
        self.correction = self.base / 'literal-correction.json'
        atomic(self.correction, correction)
        previous = self.ledger.get_job(self.job['id'])['error']['ownerRecoveryReceipt']
        with self.ledger._tx() as db:
            prior = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (previous,)).fetchone()[0])
        stage = 'owner_oneoff:' + recovery.COMPLETION_AUTHORIZATION + ':' + prior['planSha256'] + ':final_review'
        key = next(r['stageKey'] for r in self.journal.status(job_id=self.job['id'])['records'] if r['stage'] == stage)
        plan = recovery.prepare(self.config, self.job['id'], key, self.proposed, self.proof,
            self.snapshot, self.fresh, phase='completion', correction_path=self.correction)
        next_request.results.pop(0)  # No writer invocation is permitted in this mode.
        grant = dict(reference=recovery.COMPLETION_AUTHORIZATION, answer=recovery.COMPLETION_ANSWER,
                     jobId=self.job['id'], manifestSha256=fingerprint(plan))
        return rt, plan, grant, next_request, original_brief, article

    def test_source_bound_upper_editor_body_and_faq_use_no_new_writer(self):
        rt, _, _, request, original_brief, article = self.literal_fixture()
        correction = json.loads(self.correction.read_text())
        changed = copy.deepcopy(article)
        changed['content'] = article['content'].replace('根拠のない保証を加えた説明です。',
                                                        '購入前に記載された選択肢を確認します。')
        changed['faqs'][0]['answer'] = article['faqs'][0]['answer'].replace('仕様で保証されない説明です。', '')
        binding = {'writingBriefSha256': fingerprint(json.loads(self.proposed.read_text())['approvedWritingBrief']),
                   'freshResearchSha256': hashlib.sha256(self.fresh.read_bytes()).hexdigest(),
                   'sourceProofSha256': hashlib.sha256(self.proof.read_bytes()).hexdigest()}
        correction.update(mode='upper_editor_candidate', upperEditorReview=dict(binding,
            reviewedBy='Astra', candidateArticleSha256=fingerprint(changed)), replacements=[
                {'path': 'article.content', 'old': article['content'], 'new': changed['content'], 'count': 1},
                {'path': 'article.faqs.0.answer', 'old': article['faqs'][0]['answer'],
                 'new': changed['faqs'][0]['answer'], 'count': 1}])
        atomic(self.correction, correction)
        with self.ledger._tx() as db:
            records = [json.loads(raw) for raw, in db.execute("SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
        final = next(r for r in records if r.get('stage', '').endswith(':final_review')
                     and r.get('jobId') == self.job['id'] and r.get('stage', '').startswith(
                         'owner_oneoff:' + recovery.COMPLETION_AUTHORIZATION))
        plan = recovery.prepare(self.config, self.job['id'], final['stageKey'], self.proposed,
            self.proof, self.snapshot, self.fresh, phase='completion', correction_path=self.correction)
        grant = dict(reference=recovery.COMPLETION_AUTHORIZATION, answer=recovery.COMPLETION_ANSWER,
                     jobId=self.job['id'], manifestSha256=fingerprint(plan))
        before = copy.deepcopy(correction)
        self.assertEqual('delivered', recovery.execute(rt, plan, owner_grant=grant)['status'])
        self.assertEqual(2, len(request.calls))
        self.assertEqual(changed['content'], self.ledger.get_job(self.job['id'])['bundle']['article']['content'])
        self.assertEqual(before, json.loads(self.correction.read_text()))
        for field in ('writingBriefSha256', 'freshResearchSha256', 'sourceProofSha256'):
            bad_binding = dict(binding, **{field: '0' * 64})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'upper_editor_source_review_binding'):
                recovery._literal_candidate(correction, self.job, article, original_brief,
                    correction['candidateArtifactSha256'], upper_binding=bad_binding)
        bad = copy.deepcopy(correction)
        bad['replacements'][0]['old'] = '根拠のない保証を加えた説明です。'
        with self.assertRaisesRegex(ValueError, 'whole_field_replacement'):
            recovery._literal_candidate(bad, self.job, article, original_brief,
                correction['candidateArtifactSha256'], upper_binding=binding)

    def test_literal_repair_calls_only_real_gemini_and_final_preserving_writer_and_history(self):
        rt, plan, grant, request, brief, article = self.literal_fixture()
        with self.ledger._tx() as db:
            before = dict(db.execute('SELECT key,value FROM meta'))
            calls_before = db.execute('SELECT count(*) FROM model_budget_reservations').fetchone()[0]
        self.assertEqual('delivered', recovery.execute(rt, plan, owner_grant=grant)['status'])
        self.assertEqual(2, len(request.calls))
        archived = json.loads((self.root / 'manual-operations' / '20261120-pair-completion'
                               / self.job['id'] / plan['planSha256'] / 'correction-input.json').read_text())
        self.assertEqual(plan['sha256']['correction'], archived['inputSha256'])
        self.assertEqual(json.loads(self.correction.read_text()), archived['plan'])
        self.assertIn('gemini', request.calls[0][2]['model'])
        self.assertIn('claude', request.calls[1][2]['model'])
        saved = self.ledger.get_job(self.job['id'])['bundle']['article']
        self.assertNotIn('根拠のない保証を加えた説明です。', saved['content'])
        self.assertNotIn('仕様で保証されない説明です。', saved['faqs'][0]['answer'])
        with self.ledger._tx() as db:
            for key, value in before.items():
                self.assertEqual(value, db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            self.assertEqual(calls_before + 2, db.execute('SELECT count(*) FROM model_budget_reservations').fetchone()[0])
            local = [json.loads(v) for v, in db.execute("SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")
                     if json.loads(v).get('stage', '').endswith(':literal_correction')]
        self.assertEqual(1, len(local))
        self.assertEqual(brief, local[0]['output']['brief'])
        self.assertEqual(0, local[0].get('responseReceiptCount', 0))
        self.assertEqual(1, local[0]['attempts'])
        self.assertIsNone(self.ledger.get_job(self.job['id'])['approval'])
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(rt, plan, owner_grant=grant)

    def test_second_local_plan_preserves_original_writer_after_known_quality_failure(self):
        rt, first, grant, request, _, _ = self.literal_fixture(mean=6)
        with self.assertRaisesRegex(ValueError, 'final_review_failed'):
            recovery.execute(rt, first, owner_grant=grant)
        rt, proposed_plan, _, next_request = self.next_completion(rt, 3)
        pins = proposed_plan['historicalArtifacts']
        artifact = self.root / 'research' / 'artifacts' / self.job['id'] / pins['directory']
        article = json.loads((artifact / 'source.json').read_text())['bundle']['article']
        article['content'] = json.loads((artifact / 'candidate.json').read_text())['candidate']['content']
        correction = {'jobId': self.job['id'], 'sourceBinding': self.job['sourceBinding'],
            'candidateArtifactSha256': pins['candidate'], 'articleSha256': fingerprint(article),
            'replacements': [{'path': 'article.content', 'old': '検証済みの説明です。' * 350,
                              'new': '検証済みの説明です。' * 349, 'count': 1}]}
        path = self.base / 'second-literal.json'
        atomic(path, correction)
        plan = recovery.prepare(self.config, self.job['id'], proposed_plan['oldFailedKey'], self.proposed,
            self.proof, self.snapshot, self.fresh, phase='completion', correction_path=path)
        self.assertEqual(first['writerProvenance'], plan['writerProvenance'])
        next_request.results.pop(0)
        grant = dict(reference=recovery.COMPLETION_AUTHORIZATION, answer=recovery.COMPLETION_ANSWER,
                     jobId=self.job['id'], manifestSha256=fingerprint(plan))
        self.assertEqual('delivered', recovery.execute(rt, plan, owner_grant=grant)['status'])
        self.assertEqual(2, len(next_request.calls))

    def test_literal_faq_only_change_is_not_an_unchanged_article_reroll(self):
        rt, plan, grant, request, _, article = self.literal_fixture(faq_only=True)
        self.assertEqual('delivered', recovery.execute(rt, plan, owner_grant=grant)['status'])
        self.assertEqual(article['content'], self.ledger.get_job(self.job['id'])['bundle']['article']['content'])
        self.assertEqual(2, len(request.calls))

    def test_literal_plan_wrong_counts_paths_hashes_and_new_claims_are_rejected(self):
        rt, plan, grant, request, brief, article = self.literal_fixture()
        correction = json.loads(self.correction.read_text())
        for change in ('count', 'path', 'hash', 'new_fact', 'partial_number', 'brief_conflict'):
            value = copy.deepcopy(correction)
            if change == 'count':
                value['replacements'][0]['count'] = 2
            elif change == 'path':
                value['replacements'][0]['path'] = 'products.0.name'
            elif change == 'hash':
                value['articleSha256'] = '0' * 64
            elif change == 'new_fact':
                value['replacements'][0]['new'] = '完全防水で安全です。'
            elif change == 'partial_number':
                value['replacements'] = [{'path': 'article.content', 'old': '159g', 'new': '59g', 'count': 1}]
            else:
                brief = dict(brief, protected=['仕様で保証されない説明です。'])
            with self.subTest(change=change), self.assertRaises(ValueError):
                recovery._literal_candidate(value, self.job, article, brief, correction['candidateArtifactSha256'])
        self.correction.write_text(self.correction.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'pinned_manifest_changed'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)

    def test_completion_success_preserves_every_closed_claim_and_source_only_inputs(self):
        rt, plan, grant, request = self.completion_fixture()
        self.assertEqual('ready_for_budgeted_completion', plan['status'])
        with self.ledger._tx() as db:
            before = dict(db.execute('SELECT key,value FROM meta'))
        self.assertEqual('delivered', recovery.execute(rt, plan, owner_grant=grant)['status'])
        self.assertEqual(3, len(request.calls))
        self.assertEqual(1, len(self.slack.deliveries))
        self.assertNotIn('LEGACY_BODY_SENTINEL', json.dumps(request.calls))
        self.assertNotIn('LEGACY_BRIEF_SENTINEL', json.dumps(request.calls))
        writer_payload = json.dumps(request.calls[0])
        self.assertIn('Pinned diagnosis and required corrections', writer_payload)
        self.assertIn('No threshold exemption; eleven-score mean applies', writer_payload)
        self.assertIn('Purchase links and concrete buying explanations need correction', writer_payload)
        self.assertIn('Use exact canonical tracked destinations and explain confirmed variants 1', writer_payload)
        with self.ledger._tx() as db:
            for key, value in before.items():
                self.assertEqual(value, db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        self.assertIsNone(self.ledger.get_job(self.job['id'])['approval'])
        self.assertIsNone(self.ledger.get_job(self.job['id'])['publication'])
        with self.assertRaisesRegex(ValueError, 'already_claimed'):
            recovery.execute(rt, plan, owner_grant=grant)

    def test_completion_known_quality_failure_allows_a_different_plan_once(self):
        rt, plan, grant, request = self.completion_fixture(mean=6)
        with self.assertRaisesRegex(ValueError, 'final_review_failed'):
            recovery.execute(rt, plan, owner_grant=grant)
        key = recovery.receipt_key(self.job['id'], 'completion', plan_sha=plan['planSha256'])
        with self.ledger._tx() as db:
            self.assertEqual('failed_known', json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])['status'])
        with self.assertRaisesRegex(ValueError, 'same_plan_or_brief'):
            recovery.prepare(self.config, self.job['id'], plan['oldFailedKey'], self.proposed,
                self.proof, self.snapshot, self.fresh, phase='completion')
        rt, second, second_grant, second_request = self.next_completion(rt, 2)
        self.assertNotEqual(plan['planSha256'], second['planSha256'])
        self.assertEqual('delivered', recovery.execute(rt, second, owner_grant=second_grant)['status'])
        self.assertEqual(3, len(second_request.calls))

    def test_completion_unknown_outcome_stops_other_plans(self):
        rt, plan, grant, request = self.completion_fixture()
        with patch.object(rt.catalog, 'catalog', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                recovery.execute(rt, plan, owner_grant=grant)
        with self.assertRaisesRegex(ValueError, 'known_previous_failure|unknown_claim|previous_receipt'):
            recovery.prepare(self.config, self.job['id'], plan['oldFailedKey'], self.proposed,
                self.proof, self.snapshot, self.fresh, phase='completion')
        self.assertEqual([], request.calls)

    def test_pair_view_owns_its_diagnostic_list(self):
        rt, plan, grant, request = self.completion_fixture()
        rt.models.review_diagnostics = [{'prior': 'retain'}]
        view = recovery._PairRuntime(rt, plan, self.polished)
        self.assertEqual([], view.models.review_diagnostics)
        self.assertIsNot(view.models.review_diagnostics, rt.models.review_diagnostics)
        view.models.review_diagnostics.append({'new': 'isolated'})
        self.assertEqual([{'prior': 'retain'}], rt.models.review_diagnostics)

    def test_completion_cannot_send_historical_body_to_grader(self):
        rt, plan, grant, request = self.completion_fixture()
        view = recovery._PairRuntime(rt, plan, self.polished)
        view._executed_stages = {'draft', 'polish'}
        with self.ledger._tx() as db:
            historical = [json.loads(raw) for raw, in db.execute(
                "SELECT value FROM meta WHERE key LIKE 'stage_journal:v1:%'")]
        old_body = next(r['output']['polished']['content'] for r in historical
                        if r.get('status') == 'succeeded' and r.get('stage') == 'polish')
        inputs = {'bundle': {'article': {'content': old_body}},
                  'dependencies': {'qualityFlags': {'facts': True}, 'structural': {'passed': True}}}
        with self.assertRaisesRegex(ValueError, 'same_body_grader_reroll'):
            view._run_model_stage(self.job, 'final_review', inputs, lambda: self.fail('grader called'),
                                  'claude-sonnet-4-6')
        self.assertEqual([], request.calls)

    def test_completion_still_charges_existing_budget(self):
        rt, plan, grant, request = self.completion_fixture()
        with rt.model_budget.scope(self.job['id'], 'draft'):
            for i in range(26):
                reservation = rt.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
                rt.model_budget.settle(reservation, usage={'input_tokens': 0, 'output_tokens': 0},
                                       response_id='settled-completion-fixture-' + str(i))
        from model_budget import BudgetHold
        with self.assertRaises(BudgetHold):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)

    def test_completion_unknown_budget_is_not_reusable(self):
        rt, plan, grant, request = self.completion_fixture()
        with rt.model_budget.scope(self.job['id'], 'draft'):
            rt.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
        with self.assertRaisesRegex(ValueError, 'unknown_budget'):
            recovery.execute(rt, plan, owner_grant=grant)
        self.assertEqual([], request.calls)


class ChameeceCompletionRecoveryTests(CompletionRecoveryTests):
    SLOT = 3


if __name__ == '__main__':
    unittest.main()
