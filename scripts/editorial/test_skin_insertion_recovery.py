"""Exact recovery using synthetic historical artifacts and fake providers only."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import skin_insertion_recovery as r
from apparel_identity import apparel_contract, merchant_contract
from ledger import fingerprint
from models import Models, ModelError
from model_budget import BudgetHold
from runtime import Runtime, JST, atomic
from supplemental_topics import load_batch, resolve_batch
from test_models import ENV, Fake, bundle, response, article_review_value, http
from test_quality import bundle as quality_bundle
from test_supplemental_20261122 import product
import test_runtime


class SkinRecoveryTests(unittest.TestCase):
    tearDown = test_runtime.RuntimeTests.tearDown

    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.root, self.base = self.runtime.root.resolve(), Path(self.tmp.name).resolve()
        self.now = datetime.now(JST)
        batch_path = Path(__file__).with_name('supplemental-winter-depth-20261122.json')
        batch = load_batch(batch_path)
        ids = batch['slots'][1]['productIds']
        products = [product(pid) for pid in ids]
        for p in products:
            p.update(affiliateUrl=quality_bundle()['products'][0]['affiliateUrl'],
                     amazonUrl=quality_bundle()['products'][0]['amazonUrl'], asin='B012345678')
            p['specs'].update(weight='2kg', rakutenOptionState='selectable', amazonOptionState='selectable')
        self.snapshot_data = {'products': products, 'articles': []}
        slot = resolve_batch(batch, self.snapshot_data, [], self.now)['slots'][1]
        self.config.update(stateRoot=str(self.root), supplementalApparelBatchManifest=str(batch_path),
                           executionPolicy={'mode': 'deterministic', 'suspended': False})
        self.config_path = self.base / 'config.json';atomic(self.config_path, self.config)
        self.fresh = dict(products=products, catalog=products, productIds=ids,
            references=bundle()['references'], existingArticles=[{'slug': s} for s in ('setup', 'pack')],
            images=[{'productId': p['id'], 'url': p['imageUrl'], 'verified': True} for p in products],
            checks=dict(facts=True, images=True, affiliate=True),
            evidence={'products': [{'productId': pid, 'checkedAt': self.now.isoformat()} for pid in ids]})
        self.fresh['references'] = []
        for p, image in zip(products, self.fresh['images']):
            binding = dict(apparel_contract(p), sourceKind='json-ld-product', colors=['BK'], sizes=['S'], imageUrls=[p['imageUrl']])
            image['apparelBinding'] = binding
            self.fresh['references'].append(dict(url='https://maker.example/item', checkedAt=self.now.isoformat(),
                productId=p['id'], kind='manufacturer', apparelBinding=binding))
            for channel in ('rakuten','amazon'):
                self.fresh['references'].append(dict(url='https://merchant.example/'+channel, checkedAt=self.now.isoformat(),
                    productId=p['id'], kind='purchase', channel=channel,
                    apparelBinding=dict(binding, **merchant_contract(p,channel), sourceKind=channel+'-primary-product-dom')))
        outer = self
        class Catalog:
            def catalog(self):return copy.deepcopy(outer.snapshot_data)
            def gather(self, theme, context):return copy.deepcopy(outer.fresh)
        self.calls = Fake()
        self.runtime = Runtime(self.config, models=Models(ENV, self.calls), catalog=Catalog(), slack=self.slack,
            renderer=lambda *_: {'passed': True, 'clicksVerified': {'desktop': [1], 'mobile': [1]}},
            publisher=lambda action, job: self.writes.append((action, job['id'])), clock=lambda:self.now)
        self.job = self.runtime.ledger.create_supplemental_candidate(slot['theme'], r.BATCH, 2,
            slot['sourceBinding'], social_eligible_period='2026-11-20', now=self.now)
        with self.runtime.ledger._tx() as db:
            db.execute('DELETE FROM jobs WHERE id=?', (self.job['id'],))
            self.job['id'] = r.JOB_ID
            self.runtime.ledger._put(db, self.job, 'synthetic_skin')
        j = self.runtime.stage_journal
        fail = lambda:(_ for _ in ()).throw(ModelError('Length repair changed protected identity, brief or facts'))
        inputs = {'dependencies': {'prompt': 'old'}, 'schemaVersion': 1}
        with self.assertRaises(ModelError):j.run(r.JOB_ID, 'draft', inputs, fail)
        key = j.key(r.JOB_ID, 'draft', inputs)
        with self.runtime.ledger._tx() as db:
            old = j._load(db, key);db.execute('DELETE FROM meta WHERE key=?', (key,))
            old['stageKey'] = r.OLD_KEY;j._save(db, r.OLD_KEY, old)
        changed = dict(inputs, dependencies={'prompt': 'changed'})
        with self.assertRaises(ModelError):j.retry_corrected_failed(r.JOB_ID, 'draft', r.OLD_KEY, changed, fail)
        j.record_usage(r.JOB_ID, 'draft', j.key(r.JOB_ID, 'draft', changed),
                       [{'responseId': 'paid-initial'}, {'responseId': 'paid-repair'}])
        self.runtime.ledger.set_stage(r.JOB_ID, 'error', {'reason': 'ModelError'})
        self.original = dict(article={k:v for k,v in bundle()['article'].items() if k!='id'}, brief=copy.deepcopy(bundle()['brief']))
        self.original['article'].update(slug=slot['theme']['slug'], categoryId='wear', productIds=ids)
        body = '広告\n## Choice\nWeight 2kg\n[設営](/articles/setup) [撤収](/articles/pack)\n'
        body += ''.join('{{product:'+pid+'}}\n' for pid in ids)+'{{comparison:'+','.join(ids)+'}}\n'
        body += 'この2つは素材の考え方が根本的に違います。\n\nその1パターンを買う形です。\n\n袖丈を見比べます。\n\n'
        body += ('根拠の説明を読みます。'*600)[:4994-len(body)]
        self.original['article']['content'] = body
        self.original['brief'].update(format='comparison', length='5000-8000', headings=['Choice'], protected=[])
        self.chosen = '普段よく着ている肌着の袖丈と見比べておくと、イメージしやすいです。'
        repair = copy.deepcopy(self.original)
        other = body.replace('この2つ','両者').replace('その1パターン','その組み合わせ')
        other = other.replace('袖丈を見比べます。','袖丈を見比べます。'+self.chosen)
        other += '補'*(5148-len(other))
        repair['article']['content'] = other
        names = tuple(hashlib.sha256(v.encode()).hexdigest() for v in ('paid-initial','paid-repair'))
        patcher=patch.object(r,'ARTIFACT_NAMES',names);patcher.start();self.addCleanup(patcher.stop)
        for n,rid,v in zip(names,('paid-initial','paid-repair'),(self.original,repair)):
            atomic(self.root/'model-artifacts'/(n+'.json'),dict(responseId=rid,model='claude-sonnet-4-6',content=json.dumps(v,ensure_ascii=False)))
        self.snapshot=self.base/'snapshot.json';atomic(self.snapshot,self.snapshot_data)
        self.source=self.base/'fresh.json';atomic(self.source,self.fresh)
        atomic(self.root/'research'/(r.JOB_ID+'.json'),self.fresh)
        atomic(self.root/r.AUTHORIZATION_PATH,{'ownerStatement':'今回に限り復旧を許可。記事のSlack承認まで。','publication':False,'snsReservation':False})
        paid=r.diagnose(self.root)
        selected=[i['id'] for i in paid['diagnosis']['insertions'] if self.chosen in i['text']]
        self.assertEqual(1,len(selected))
        self.corrected=copy.deepcopy(self.original)
        self.corrected['article']['content']=r.apply_selected(body,paid['diagnosis'],selected)
        self.review=self.base/'upper-review.json'
        atomic(self.review,dict(kind='skin_length_insertion_review_v1',jobId=r.JOB_ID,artifactSha256=paid['artifacts'],
            selectedInsertionIds=selected,reviewedBy='Astra',reviewReference='synthetic-upper-review',factsPreserved=True,
            meaningPreserved=True,styleReviewed=True,noNewFacts=True,candidateSha256=fingerprint(self.corrected)))

    def prepare(self):return r.prepare(self.config_path,self.review,self.snapshot,self.source)
    def grant(self,p):return dict(reference=r.AUTHORIZATION_PATH,action=r.ACTION,jobId=r.JOB_ID,
        authorizationSha256=p['sha256']['authorization'],manifestSha256=fingerprint(p))

    def test_prepare_readonly_selects_only_reviewed_insert_without_numeric_replacements(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        plan=self.prepare()
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        body=plan['corrected']['article']['content']
        self.assertIn('この2つ',body);self.assertIn('その1パターン',body);self.assertNotIn('両者',body)
        self.assertEqual(4994+len(self.chosen),len(body));self.assertGreaterEqual(len(body),5000)
        self.assertEqual([],self.calls.calls)

    def test_full_pipeline_uses_only_gemini_final_review_and_article_delivery(self):
        plan=self.prepare();expected=copy.deepcopy(self.corrected)
        expected.update(products=self.fresh['products'],images=self.fresh['images'],references=self.fresh['references'])
        final=article_review_value(expected)
        self.calls.results=[response({'edits':[]},gemini=True),response(final)]
        self.calls.results[1]['id']='skin-final'
        with self.runtime.ledger._tx() as db:old={k:v for k,v in db.execute("SELECT key,value FROM meta WHERE key LIKE 'stage_journal:v1:%'")}
        result=r.execute(self.runtime,plan,owner_grant=self.grant(plan))
        self.assertEqual('delivered',result['status']);self.assertEqual(2,len(self.calls.calls))
        self.assertEqual([('stage',r.JOB_ID)],self.writes);self.assertEqual(1,len(self.slack.deliveries))
        job=self.runtime.ledger.get_job(r.JOB_ID)
        self.assertEqual('review',job['stage']);self.assertIsNone(job['approval']);self.assertIsNone(job['publication'])
        with self.runtime.ledger._tx() as db:
            for k,v in old.items():self.assertEqual(v,db.execute('SELECT value FROM meta WHERE key=?',(k,)).fetchone()[0])
            self.assertEqual([(r.JOB_ID,'polish'),(r.JOB_ID,'final_review')],db.execute('SELECT article_id,stage FROM model_budget_reservations').fetchall())
        stages=[s for s in self.runtime.stage_journal.status(job_id=r.JOB_ID)['records'] if 'owner_oneoff:' in s['stage']]
        self.assertEqual(3,len(stages));self.assertTrue(all(s['attempts']==s['maxAttempts']==1 for s in stages))
        literal=next(s for s in stages if s['stage'].endswith(':literal_draft'))
        self.assertEqual(0,literal['responseReceiptCount'])
        with self.assertRaisesRegex(ValueError,'already_claimed'):r.execute(self.runtime,plan,owner_grant=self.grant(plan))

    def test_wrong_grants_or_changed_authorization_stop_before_calls(self):
        plan=self.prepare()
        for g in ({},dict(self.grant(plan),action='publish'),dict(self.grant(plan),jobId='other')):
            with self.assertRaises(ValueError):r.execute(self.runtime,plan,owner_grant=g)
        auth=self.root/r.AUTHORIZATION_PATH;auth.write_text(auth.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'pinned_plan_changed'):r.execute(self.runtime,plan,owner_grant=self.grant(plan))
        self.assertEqual([],self.calls.calls)

    def test_stale_and_unknown_stage_effect_budget_hold(self):
        stale=copy.deepcopy(self.fresh);stale['evidence']['products'][0]['checkedAt']=(self.now-timedelta(days=1)).isoformat()
        atomic(self.source,stale)
        with self.assertRaisesRegex(ValueError,'stale_or_future'):self.prepare()
        atomic(self.source,self.fresh)
        for status in ('unknown','in_flight'):
            with self.runtime.ledger._tx() as db:
                original=self.runtime.stage_journal._load(db,r.OLD_KEY);changed=dict(original,status=status)
                self.runtime.stage_journal._save(db,r.OLD_KEY,changed)
            with self.assertRaisesRegex(ValueError,'unknown_stage'):self.prepare()
            with self.runtime.ledger._tx() as db:self.runtime.stage_journal._save(db,r.OLD_KEY,original)
        with self.runtime.ledger._tx() as db:db.execute('INSERT INTO effects VALUES (?,?,?,?)',(r.JOB_ID,'publish','unknown','{}'))
        with self.assertRaisesRegex(ValueError,'unknown_effect'):self.prepare()
        with self.runtime.ledger._tx() as db:db.execute('DELETE FROM effects')
        with self.runtime.model_budget.scope(r.JOB_ID,'draft'):
            self.runtime.model_budget.reserve({'model':'fixture','max_tokens':1,'messages':[]})
        with self.assertRaisesRegex(ValueError,'unknown_budget'):self.prepare()

    def test_manager_scope_and_one_request_per_stage(self):
        self.assertFalse(r.manager_blocks({'status':'requires_reconciliation','action':{'job_id':'other'}}))
        self.assertTrue(r.manager_blocks({'status':'requires_reconciliation','action':{'jobId':r.JOB_ID}}))
        self.assertTrue(r.manager_blocks({'status':'executing','action':{'jobId':'other'}}))
        with self.runtime.ledger._tx() as db:db.execute('INSERT INTO meta VALUES (?,?)',('editorial_manager:old',json.dumps({'status':'requires_reconciliation','action':{'job_id':'other'}})))
        self.prepare()
        budget=r._OneRequestBudget(self.runtime.model_budget);budget.stage='polish'
        with self.runtime.model_budget.scope(r.JOB_ID,'polish'):
            reservation=budget.reserve({'model':'fixture','max_tokens':1,'messages':[]})
            budget.settle(reservation,usage={'input_tokens':0,'output_tokens':0})
            with self.assertRaisesRegex(ValueError,'one_request_per_stage'):budget.reserve({'model':'fixture','max_tokens':1,'messages':[]})

    def test_snapshot_order_is_irrelevant_but_duplicate_products_hold(self):
        expected=self.prepare()
        reversed_snapshot=copy.deepcopy(self.snapshot_data)
        reversed_snapshot['products'].reverse();atomic(self.snapshot,reversed_snapshot)
        current=self.prepare()
        self.assertEqual(expected['correctedSha256'],current['correctedSha256'])
        reversed_snapshot['products'].append(reversed_snapshot['products'][0])
        atomic(self.snapshot,reversed_snapshot)
        with self.assertRaises(ValueError):self.prepare()

    def test_provider_error_consumes_claim_without_request_retry(self):
        plan=self.prepare();self.calls.results=[http(503)]
        with patch('models.time.sleep'), self.assertRaisesRegex(ValueError,'one_request_per_stage'):
            r.execute(self.runtime,plan,owner_grant=self.grant(plan))
        self.assertEqual(1,len(self.calls.calls))
        self.assertEqual([],self.writes);self.assertEqual([],self.slack.deliveries)
        with self.assertRaisesRegex(ValueError,'already_claimed'):
            r.execute(self.runtime,plan,owner_grant=self.grant(plan))

    def test_existing_article_cap_stops_before_provider(self):
        payload={'model':'fixture','max_tokens':1,'messages':[]}
        with self.runtime.model_budget.scope(r.JOB_ID,'draft'):
            for _ in range(32):
                key=self.runtime.model_budget.reserve(payload)
                self.runtime.model_budget.settle(key,usage={'input_tokens':0,'output_tokens':0})
        plan=self.prepare()
        with self.assertRaises(BudgetHold) as error:
            r.execute(self.runtime,plan,owner_grant=self.grant(plan))
        self.assertEqual('article_calls_cap',error.exception.reason_code)
        self.assertEqual([],self.calls.calls)

    def test_suspended_and_forbidden_entrypoints_do_not_run(self):
        plan=self.prepare()
        view=r._SkinRuntime(self.runtime,plan)
        for method in ('tick','consume','produce','produce_supplemental','make_social','publish_social','publish_buffer_social','approve_from_codex'):
            with self.subTest(method=method),self.assertRaises(ValueError):getattr(view,method)()
        with self.assertRaises(ValueError):view._stage_only('publish',self.job)
        self.config['executionPolicy']['suspended']=True
        with self.assertRaisesRegex(ValueError,'execution_suspended'):
            r.execute(self.runtime,plan,owner_grant=self.grant(plan))
        self.assertEqual([],self.calls.calls)
