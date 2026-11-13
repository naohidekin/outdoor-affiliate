import copy,unittest
from publication_display_gate import build_prewrite_plan

class PrewriteDisplayTests(unittest.TestCase):
 def inputs(self):
  job={'id':'j','kind':'article','bundle':None,'revision':None,'theme':{'productIds':['p']}}
  product={'id':'p','price':100,'rating':4,'updatedAt':'2026-11-13T00:00:00+00:00'}
  gathered={'products':[product],'evidence':{'products':[{'productId':'p','unverifiedFields':['price','rating']}]}}
  return job,gathered
 def test_proposal_only_no_mutation(self):
  j,g=self.inputs();old=copy.deepcopy(g);p=build_prewrite_plan(j,g)
  self.assertEqual('correction_required',p['status']);self.assertEqual(g,old)
  self.assertEqual({'price':0,'rating':0},p['proposals'][0]['proposedDisplayChanges'])
  self.assertFalse(p['approved']);self.assertFalse(p['applied']);self.assertIn('非表示',p['zeroMeaning'])
 def test_absent_unverified_field_is_not_verified_price(self):
  j,g=self.inputs();g['evidence']['products'][0]['unverifiedFields']=[]
  self.assertEqual('correction_required',build_prewrite_plan(j,g)['status'])
 def test_safe_zero_is_not_verified_price(self):
  j,g=self.inputs();g['products'][0].update(price=0,rating=0)
  p=build_prewrite_plan(j,g);self.assertEqual('display_safe',p['status']);self.assertFalse(p['priceVerified'])
 def test_invalid_numbers_and_structure_fail(self):
  for bad in ('100',-1,float('nan'),float('inf'),True,None):
   j,g=self.inputs();g['products'][0]['price']=bad
   with self.subTest(bad=bad),self.assertRaises(ValueError):build_prewrite_plan(j,g)
  j,g=self.inputs();g['evidence']['products']=[]
  with self.assertRaises(ValueError):build_prewrite_plan(j,g)
 def test_revision_and_existing_bundle_untouched(self):
  for changes in ({'kind':'article_revision'},{'bundle':{}},{'revision':'existing'}):
   j,g=self.inputs();j.update(changes)
   self.assertEqual({'status':'not_applicable'},build_prewrite_plan(j,g))

from unittest.mock import Mock,patch
import test_runtime
from datetime import datetime
from runtime import JST

class PrewriteIntegrationTests(unittest.TestCase):
 setUp=test_runtime.RuntimeTests.setUp
 tearDown=test_runtime.RuntimeTests.tearDown
 def test_only_affected_candidate_errors_no_writer_or_repeated_work(self):
  self.runtime.config['prewriteDisplayGateEnabled']=True
  job,g=PrewriteDisplayTests().inputs();g['checks']=dict(facts=True,images=True,affiliate=True)
  self.runtime.catalog.gather=Mock(return_value=g)
  self.runtime._context=Mock(return_value={'products':g['products'],'editorialRules':'rules'})
  self.models.draft=Mock(side_effect=AssertionError('must not call writer'))
  with patch('runtime.datetime') as clock:
   clock.now.return_value=datetime(2026,11,13,9,tzinfo=JST)
   j=self.runtime.ledger.create_candidate({'slug':'blocked','title':'T','productIds':['p']},clock.now.return_value)
   first=self.runtime.produce();self.assertEqual('blocked',first['articles'][0]['status'])
   self.assertEqual('error',self.runtime.ledger.get_job(j['id'])['stage'])
   self.assertEqual('idle',self.runtime.produce()['status'])
  self.models.draft.assert_not_called();self.runtime.catalog.gather.assert_called_once()
  self.assertEqual([],self.writes);self.assertEqual([],self.slack.deliveries)
  files=list((self.runtime.root/'display-correction-proposals').rglob('*.json'));self.assertEqual(1,len(files))
 def test_unrelated_existing_pipeline_default_unchanged(self):
  self.assertIsNot(self.runtime.config.get('prewriteDisplayGateEnabled'),True)
