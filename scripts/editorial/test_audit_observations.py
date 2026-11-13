import unittest
from post_publication_audit import _merchant_observation
class AuditObservationTests(unittest.TestCase):
 def test_public_url_only_and_bounded_title(self):
  p={'id':'p1','brand':'SOTO','categoryId':'burner','name':'SOTO ST-310'}
  v=_merchant_observation('destination.0.amazon',p,'ST-310','SOTO ST-310 stove '+('x'*1000),'https://www.amazon.co.jp/dp/B012345678?token=secret#frag',True)
  self.assertEqual(v['finalPage'],'https://www.amazon.co.jp/dp/B012345678');self.assertLessEqual(len(v['title']),512)
  self.assertTrue(v['modelFound']);self.assertTrue(v['brandFound']);self.assertTrue(v['routeMatched']);self.assertNotIn('secret',str(v))
 def test_missing_identity_is_observation_not_authority(self):
  v=_merchant_observation('destination.0.amazon',{'id':'p1','brand':'SOTO','name':'SOTO ST-310','categoryId':'burner'},'ST-310','shop home','https://www.amazon.co.jp/',False)
  self.assertFalse(v['modelFound']);self.assertFalse(v['brandFound']);self.assertFalse(v['routeMatched']);self.assertFalse(v['identityMatched'])
 def test_no_userinfo_and_controls(self):
  v=_merchant_observation('x',{'id':'p','brand':'B','name':'B M1'},'M1','a\n\t b','https://username:password@example.com/a?q=s',True)
  self.assertEqual(v['finalPage'],'https://example.com/a');self.assertEqual(v['title'],'a b')
 def test_full_audit_retains_verdict_and_observations(self):
  from test_post_publication_audit import AuditTests,FakeCatalog,fixture
  result=AuditTests().run_audit()
  self.assertTrue(result['passed']);self.assertEqual(len(result['merchantObservations']),2)
  _,html=fixture();cat=FakeCatalog(html);cat.merchant='<title>SOTO ST-330 stove</title>'
  result=AuditTests().run_audit(catalog=cat)
  self.assertEqual(result['status'],'failed');self.assertFalse(result['merchantObservations'][0]['modelFound'])

 def test_total_diagnostic_budget_preserves_verdict(self):
  import json
  from post_publication_audit import _with_merchant_observations
  base={'passed':True,'status':'passed','checks':[],'issues':[]}
  result=_with_merchant_observations(base,[{'title':'日'*512,'finalPage':'x'*2048}]*40)
  self.assertTrue(result['passed']);self.assertTrue(result['merchantObservationsTruncated'])
  self.assertLess(len(json.dumps(result).encode()),9000);self.assertEqual(base['checks'],result['checks'])
  crowded=dict(base,checks=['x'*60000]);self.assertEqual(_with_merchant_observations(crowded,[{'a':1}]),crowded)
