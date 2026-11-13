"""Synthetic offline review operator tests; no live models or publishing."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from ledger import fingerprint
from test_quality import bundle
from fixed_price_review import validate_fixed_candidate, verify_polish_reuse, prepare_fixed_price_review

class FixedPriceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.b=bundle();self.b['article'].update(categoryId='tent',status='draft',publishedAt=None);self.b['products'][0].update(categoryId='tent',price=2750,rating=3.5,updatedAt='2026-11-13T01:00:00+00:00')
  from catalog_corrections import validated_context
  raw=dict(baseProducts=copy.deepcopy(self.b['products']),candidateProducts=copy.deepcopy(self.b['products']),changeSummary='initial')
  self.b['catalogCorrectionContext']=validated_context(raw)
  self.job=dict(id='test-job',theme=dict(productIds=[self.b['products'][0]['id']],categoryId=self.b['products'][0]['categoryId']),bundle=self.b,revision=fingerprint(self.b),catalogCorrectionContext=self.b['catalogCorrectionContext'],publication=None,approval=None)
  self.new=copy.deepcopy(self.b)
  for p in self.new['products']:p.update(price=0,rating=0,updatedAt='2026-11-13T02:00:00+00:00')
  raw['candidateProducts']=copy.deepcopy(self.new['products']);raw['changeSummary']='hide unsupported numbers'
  self.new['catalogCorrectionContext']=validated_context(raw)
  self.c=dict(expectedRevision=self.job['revision'],bundle=self.new,candidateRevision=fingerprint(self.new),articleId='test-job')
 def tearDown(self):self.tmp.cleanup()
 def artifact(self):
  source=copy.deepcopy(self.b);directory=self.root/'research'/'artifacts'/'test-job'/fingerprint(source);directory.mkdir(parents=True)
  (directory/'source.json').write_text(json.dumps({'kind':'source','bundle':source}))
  (directory/'candidate.json').write_text(json.dumps({'kind':'candidate','candidate':{'content':self.b['article']['content'],'model':'gemini-3.8-flash','usage':{'model':'gemini-3.8-flash'}}}))
  return directory
 def test_candidate_accepts_only_nontext_zero_changes(self):
  validate_fixed_candidate(self.job,self.c)
  for target in ('content','image','price','baseline','revision'):
   c=copy.deepcopy(self.c)
   if target=='content':c['bundle']['article']['content']+=' changed'
   if target=='image':c['bundle']['images']=[]
   if target=='price':c['bundle']['products'][0]['price']=123
   if target=='baseline':c['bundle']['catalogCorrectionContext']['baseProducts'][0]['price']=123
   if target=='revision':c['expectedRevision']='bad'
   with self.subTest(target=target),self.assertRaises(ValueError):validate_fixed_candidate(self.job,c)
 def test_polish_exact_body_and_provenance(self):
  p=self.artifact();proof=verify_polish_reuse(self.root,self.job,p,self.new)
  self.assertTrue(proof['reused']);self.assertEqual('gemini-3.8-flash',proof['model'])
  new=copy.deepcopy(self.new);new['article']['content']+=' changed'
  with self.assertRaises(ValueError):verify_polish_reuse(self.root,self.job,p,new)
  with self.assertRaises(ValueError):verify_polish_reuse(self.root,self.job,self.root,new)

 def runtime(self):
  rt=Mock();rt.root=self.root;rt.ledger.get_job.return_value=copy.deepcopy(self.job)
  rt.catalog.gather.return_value={'checks':dict(facts=True,images=True,affiliate=True),'images':[dict(x,verified=True) for x in self.new['images']],'evidence':{}}
  rt.renderer.return_value={'passed':True,'clicksVerified':{'desktop':['https://example.test/verified'],'mobile':['https://example.test/verified']}}
  rt._medical.return_value={'passed':True};rt.models.polish.return_value={'content':self.new['article']['content'],'model':'gemini-3.8-flash','usage':{'model':'gemini-3.8-flash','synthetic':True}};rt.models.review.return_value={'passed':True,'score':8.5}
  return rt
 def run_operator(self,rt):
  path=self.root/'candidate.json';path.write_text(json.dumps(self.c))
  with patch('fixed_price_review.inspect_bundle',return_value={'passed':True}):
   return prepare_fixed_price_review(rt,'test-job',path,self.artifact(),{'products':self.c['bundle']['catalogCorrectionContext']['baseProducts'],'editorialRules':'rules'})
 def test_fresh_operator_never_writes_drafts_or_reuses_review(self):
  rt=self.runtime();rt.ledger.get_job.return_value['theme']['selectionReason']='public reason EDITORIAL RECOVERY REQUIREMENTS private comment';result=self.run_operator(rt)
  self.assertTrue(result['requiresIndependentReview']);self.assertFalse(result['polishProof']['reused']);self.assertTrue(result['polishProof']['newModelCall'])
  self.assertEqual(fingerprint(self.new),result['review']['fingerprint'])
  rt.models.review.assert_called_once();self.assertEqual('public reason',rt.models.review.call_args[0][1]['approvedTheme']['selectionReason']);rt.models.draft.assert_not_called();rt.models.polish.assert_called_once()
  rt.ledger.save_bundle.assert_not_called();rt.ledger.record_review.assert_not_called();rt.deliver.assert_not_called()
  self.assertEqual(2,rt._save_usage.call_count)
 def test_source_fail_prevents_model_call(self):
  rt=self.runtime();rt.catalog.gather.return_value['checks']['images']=False
  with self.assertRaises(ValueError):self.run_operator(rt)
  rt.models.review.assert_not_called()
 def test_render_fail_prevents_model_call(self):
  rt=self.runtime();rt.renderer.return_value['clicksVerified']['mobile']=[]
  with self.assertRaises(ValueError):self.run_operator(rt)
  rt.models.review.assert_not_called()
 def test_model_failure_preserves_usage_no_write(self):
  rt=self.runtime();rt.models.review.side_effect=ValueError('test provider failure')
  with self.assertRaises(ValueError):self.run_operator(rt)
  self.assertEqual(2,rt._save_usage.call_count);rt.ledger.save_bundle.assert_not_called()
 def test_repair_record_reuse_is_exact_and_script_pinned(self):
  repair=self.root/'repair';repair.mkdir();final=repair/'final.json';result=repair/'result.json';script=repair/'run.py'
  script.write_text('# synthetic trusted script')
  import hashlib
  job=copy.deepcopy(self.job);job['review']={'fingerprint':job['revision'],'polish':{'model':'gemini-3.8-flash','validated':True}}
  final.write_text(json.dumps(job));result.write_text(json.dumps({'status':'awaiting_astra_review','revision':job['revision'],'published':False,'bodyCharacters':len(self.new['article']['content'])}))
  evidence={'finalRecord':str(final),'resultRecord':str(result),'script':str(script),'expectedScriptSha256':hashlib.sha256(script.read_bytes()).hexdigest()}
  proof=verify_polish_reuse(self.root,self.job,evidence,self.new);self.assertTrue(proof['reused']);self.assertFalse(proof['newModelCall'])
  script.write_text('changed')
  with self.assertRaises(ValueError):verify_polish_reuse(self.root,self.job,evidence,self.new)

 def test_fresh_polish_change_stops_without_review_or_retry(self):
  rt=self.runtime();rt.models.polish.return_value['content']+=' changed'
  with self.assertRaisesRegex(ValueError,'changed fixed body'):self.run_operator(rt)
  rt.models.polish.assert_called_once();rt.models.review.assert_not_called()
  self.assertEqual(1,rt._save_usage.call_count)
  files=list((self.root/'fixed-display-reviews').rglob('polish-output.json'));self.assertEqual(1,len(files))
  self.assertTrue(json.loads(files[0].read_text())['content'].endswith(' changed'))
  path=self.root/'candidate.json'
  with self.assertRaisesRegex(ValueError,'already attempted'):
   prepare_fixed_price_review(rt,'test-job',path,None,{'products':self.c['bundle']['catalogCorrectionContext']['baseProducts'],'editorialRules':'rules'})
  rt.models.polish.assert_called_once()
 def test_fresh_polish_provider_failure_keeps_intent_and_usage(self):
  rt=self.runtime();rt.models.polish.side_effect=ValueError('provider failed')
  with self.assertRaises(ValueError):self.run_operator(rt)
  self.assertEqual(1,rt._save_usage.call_count);rt.models.review.assert_not_called()
  self.assertEqual(1,len(list((self.root/'fixed-display-reviews').rglob('polish-intent.json'))))
