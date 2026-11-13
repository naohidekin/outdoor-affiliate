import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from ledger import Ledger,fingerprint
from catalog_corrections import validated_context
from test_ledger import NOW
class DisplaySuppressionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'private';self.l=Ledger(self.root,'owner')
  p=dict(id='p',categoryId='light',price=2750,rating=0,updatedAt='2026-11-01T00:00:00+00:00',createdAt='2026-01-01T00:00:00+00:00',name='Light',imageUrl='https://example.test/a.png',specs={'model':'UK-4075'},affiliateUrl='https://example.test/buy')
  self.ctx=validated_context(dict(baseProducts=[p],candidateProducts=[copy.deepcopy(p)],changeSummary='source checked'))
  j=self.l.create_candidate(dict(slug='light',categoryId='light',productIds=['p']),NOW);self.l.attach_catalog_correction(j['id'],{k:self.ctx[k] for k in ['baseProducts','candidateProducts','changeSummary']})
  b=dict(article=dict(id=j['id'],categoryId='light',productIds=['p'],status='draft',publishedAt=None,content='fixed body'),products=[p],images=[{'url':p['imageUrl']}],brief={'text':'fixed'},references=['source'],catalogCorrectionContext=self.ctx)
  self.job=self.l.save_bundle(j['id'],b);self.b=copy.deepcopy(b);new=copy.deepcopy(p);new.update(price=0,updatedAt='2026-11-13T00:00:00+00:00');self.b['products']=[new];self.b['catalogCorrectionContext']=validated_context(dict(baseProducts=[p],candidateProducts=[new],changeSummary='未検証価格を非表示'))
 def tearDown(self):self.tmp.cleanup()
 def apply(self,b=None,rev=None):return self.l.suppress_unverified_product_display(self.job['id'],b or self.b,expected_revision=rev or self.job['revision'])
 def dump(self):
  with sqlite3.connect(self.l.db_path) as c:return tuple(c.iterdump())
 def test_exact_price_only_and_audit_and_old_review_invalidation(self):
  with self.l._tx() as db:
   j=self.l._get(db,self.job['id']);j['review']={'prior':'review'};j['astraReview']={'prior':'astra'};self.l._put(db,j,'fixture')
  with self.l._tx() as db:db.execute('insert into requests values(?,?,?,?)',('old-request',self.job['id'],'article',json.dumps({'status':'created','kind':'article','manifest_hash':self.job['revision']})))
  out=self.apply();self.assertEqual('draft',out['stage']);self.assertEqual(self.b,out['bundle']);self.assertIsNone(out['review']);self.assertIsNone(out['astraReview']);self.assertIsNone(out['approval'])
  with sqlite3.connect(self.l.db_path) as db:
   self.assertEqual('invalidated',json.loads(db.execute('select data from requests').fetchone()[0])['status'])
   old=json.loads(db.execute("select data from events where kind='display_suppression_previous'").fetchone()[0]);self.assertEqual(self.job['bundle'],old['job']['bundle'])
  before=self.dump()
  with self.assertRaises(ValueError):self.apply()
  self.assertEqual(before,self.dump())
 def test_rejects_body_image_link_baseline_and_nonzero_price_atomic(self):
  for change in ['body','image','link','base','price','bool','timestamp']:
   b=copy.deepcopy(self.b)
   if change=='body':b['article']['content']='other'
   if change=='image':b['images'][0]['url']='other'
   if change=='base':b['catalogCorrectionContext']['baseProducts'][0]['price']=1
   if change in ['link','price','bool','timestamp']:
    p=b['products'][0]
    if change=='link':p['affiliateUrl']='https://other.test'
    if change=='price':p['price']=100
    if change=='bool':p['price']=False
    if change=='timestamp':p['updatedAt']='2026-10-01T00:00:00+00:00'
    b['catalogCorrectionContext']=validated_context({**{k:b['catalogCorrectionContext'][k] for k in ['baseProducts','changeSummary']},'candidateProducts':b['products']})
   before=self.dump()
   with self.assertRaises(ValueError):self.apply(b)
   self.assertEqual(before,self.dump())
 def test_current_approval_effect_and_journal_block(self):
  for mode in ['approval','effect','journal']:
   with self.subTest(mode=mode):
    if mode=='approval':
     with self.l._tx() as db:
      j=self.l._get(db,self.job['id']);j['approval']={'action':'approved'};self.l._put(db,j,'fixture')
    elif mode=='effect':
     with self.l._tx() as db:db.execute('insert into effects values(?,?,?,?)',(self.job['id'],'publish','failed','{}'))
    else:
     p=self.root/'catalog-corrections';p.mkdir();(p/(self.job['revision']+'.json')).write_text('{}')
    before=self.dump()
    with self.assertRaises(ValueError):self.apply()
    self.assertEqual(before,self.dump())
    if mode=='approval':
     with self.l._tx() as db:
      j=self.l._get(db,self.job['id']);j['approval']=None;self.l._put(db,j,'fixture')
    elif mode=='effect':
     with self.l._tx() as db:db.execute('delete from effects')
