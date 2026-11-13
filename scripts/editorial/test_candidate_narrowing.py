"""Offline narrowing contract; synthetic evidence, no network or live state."""
import copy
import unittest
from test_catalog_correction_runtime import CatalogCorrectionRuntimeTests

class CandidateNarrowingTests(CatalogCorrectionRuntimeTests):
    def make_narrow(self):
        job = self.runtime.ledger.create_candidate(dict(slug='narrow',categoryId='tent',productIds=['tent-a','tent-b'],title='old'))
        theme = dict(job['theme'],productIds=['tent-a'],title='new',query='query',selectionReason='verified subset')
        return job,theme,self.raw()

    def test_narrow_preserves_identity_and_attaches_binding(self):
        job,theme,raw=self.make_narrow()
        got=self.runtime.ledger.narrow_candidate_products(job['id'],theme,raw)
        self.assertEqual((job['id'],job['week'],job['created_at']),(got['id'],got['week'],got['created_at']))
        self.assertEqual(theme,got['theme'])
        self.assertEqual(raw['candidateProducts'],got['catalogCorrectionContext']['candidateProducts'])
        self.assertIsNone(got['approval']);self.assertIsNone(got['bundle'])
        self.assertEqual(1,len(self.runtime.ledger.list_jobs()))

    def test_empty_extra_duplicate_same_and_reorder_rejected(self):
        job,theme,raw=self.make_narrow()
        for ids in ([],['other'],['tent-a','tent-a'],['tent-a','tent-b'],['tent-b','tent-a']):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                self.runtime.ledger.narrow_candidate_products(job['id'],dict(theme,productIds=ids),raw)
        self.assertEqual(job,self.runtime.ledger.get_job(job['id']))

    def test_identity_context_and_authority_rejected(self):
        job,theme,raw=self.make_narrow()
        for field,value in [('slug','other'),('categoryId','other'),('approval',True)]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.runtime.ledger.narrow_candidate_products(job['id'],dict(theme,**{field:value}),raw)
        bad=copy.deepcopy(raw);bad['candidateProducts'][0]['id']='other'
        with self.assertRaises(ValueError):self.runtime.ledger.narrow_candidate_products(job['id'],theme,bad)
        with self.runtime.ledger._tx() as db:db.execute('INSERT INTO effects VALUES (?,?,?,?)',(job['id'],'stage','failed','{}'))
        with self.assertRaises(ValueError):self.runtime.ledger.narrow_candidate_products(job['id'],theme,raw)

    def test_staged_and_reviewed_rejected(self):
        job,theme,raw=self.make_narrow()
        for key,value in [('bundle',{}),('review',{}),('approval',{}),('publication',{}),('social',{})]:
            with self.runtime.ledger._tx() as db:
                changed=copy.deepcopy(job);changed[key]=value;self.runtime.ledger._put(db,changed,'test')
            with self.subTest(key=key),self.assertRaises(ValueError):self.runtime.ledger.narrow_candidate_products(job['id'],theme,raw)

    def test_existing_binding_baseline_cannot_change(self):
        job,theme,raw=self.make_narrow()
        # A previously attached correction keeps its immutable catalog baseline.
        from catalog_corrections import validated_context
        with self.runtime.ledger._tx() as db:
            changed=copy.deepcopy(job);changed['catalogCorrectionContext']=validated_context(raw)
            self.runtime.ledger._put(db,changed,'test')
        bad=copy.deepcopy(raw)
        bad['baseProducts'][0]['name']='different baseline'
        with self.assertRaises(ValueError):self.runtime.ledger.narrow_candidate_products(job['id'],theme,bad)
        got=self.runtime.ledger.narrow_candidate_products(job['id'],theme,raw)
        self.assertEqual(raw['baseProducts'],got['catalogCorrectionContext']['baseProducts'])

    def test_scope_and_snapshot_validation(self):
        job,theme,raw=self.make_narrow()
        for field in ('imageUrl','affiliateUrl'):
            bad=copy.deepcopy(raw);bad['candidateProducts'][0][field]='https://example.test/changed'
            bad['candidateProducts'][0]['updatedAt']=bad['baseProducts'][0]['updatedAt']
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.runtime.ledger.narrow_candidate_products(job['id'],theme,bad)
        bad=copy.deepcopy(raw);bad['candidateProducts'][0]['categoryId']='other'
        with self.assertRaises(ValueError):self.runtime.ledger.narrow_candidate_products(job['id'],theme,bad)
        with self.runtime.ledger._tx() as db:
            changed=copy.deepcopy(job);changed['kind']='article_revision';self.runtime.ledger._put(db,changed,'test')
        with self.assertRaises(ValueError):self.runtime.ledger.narrow_candidate_products(job['id'],theme,raw)

if __name__=='__main__':unittest.main()
