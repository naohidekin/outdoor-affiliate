"""Owner-authorized article v2: advisory aggregate, frozen v1, evidence-bound feedback."""
import copy
import unittest
from review_scoring import VERSION, VERSION_V1, calculate, verify_review, verdict, validate_feedback, resolve_feedback, select_feedback
from test_models import bundle, FLAGS

class V2ScoringTests(unittest.TestCase):
    def review(self, b=None, value=2):
        b=b or bundle()
        from models import article_review_schema
        active=article_review_schema(b)['properties']['criteria']['required']
        result=dict(criteria=dict.fromkeys(active,value),wiseScores=dict(w=2,i=2,s=2,e=2,ai=3,sense=2),
                    issues=[],improvementFeedback=[],hardChecks={'structure':True},**FLAGS)
        if value < 7.5:
            result['improvementFeedback']=[{'criterion':'wise_s','location':{'kind':'paragraph','index':0},'quote':b['article']['content'].split('\n\n')[0][:20], 'anchor':'grounded concern','nextAction':'Explain the actual reader decision more concretely.'}]
        wire=[{key:value for key,value in item.items() if key != 'location'} for item in result['improvementFeedback']]
        result['improvementFeedback'],result['feedbackValidation']=select_feedback(wire,b,result['criteria'])
        result.update(calculate(result['criteria'],b));result['passed']=verdict(result,result['calculation'])
        return b,result
    def test_low_advisory_passes_with_all_hard_gates(self):
        b,r=self.review();self.assertLess(r['score'],7.5);self.assertFalse(r['calculation']['thresholdMet'])
        self.assertTrue(r['passed']);verify_review(r,b)
        for changes in ({'facts':False},{'hardChecks':{'structure':False}},{'wiseScores':dict(r['wiseScores'],ai=2)},{'issues':['Unsupported fact']}):
            changed=dict(r,**changes);self.assertFalse(verdict(changed,r['calculation']))
    def test_deterministic_word_count_and_no_ai_score(self):
        b,r=self.review();self.assertNotIn('word_count',r['criteria']);self.assertEqual(10,r['calculation']['wordCount']['score'])
        for count in (2999,5001):
            bad=copy.deepcopy(b);bad['article']['content']='文'*count
            with self.assertRaises(ValueError):calculate(r['criteria'],bad)
        with self.assertRaises(ValueError):calculate(dict(r['criteria'],word_count=10),b)
    def test_v1_formula_and_verdict_are_unchanged(self):
        from review_scoring import CRITERIA_FIELDS
        b=bundle();criteria=dict.fromkeys(CRITERIA_FIELDS,7)
        r=dict(criteria=criteria,wiseScores=dict(w=2,i=2,s=2,e=2,ai=3,sense=2),issues=[],**FLAGS)
        r.update(calculate(criteria,b,version=VERSION_V1));r['passed']=False
        self.assertEqual(7,r['score']);self.assertNotIn('aggregateRole',r['calculation']);verify_review(r,b)
        with self.assertRaises(ValueError):verify_review(dict(r,passed=True),b)
        self.assertNotEqual(VERSION_V1,VERSION)
    def test_feedback_quote_location_limits_and_types(self):
        b=bundle();quote=b['article']['content'].split('\n\n')[0][:20]
        item={'criterion':'wise_s','location':{'kind':'paragraph','index':0},'quote':quote,'anchor':'grounded concern','nextAction':'Connect the cited weight to a documented choice.'}
        validate_feedback([item],b)
        b['article']['faqs']=[dict(q) for q in b['article']['faqs']]; b['article']['faqs'][0]['answer']='固有の回答で重さを説明します。'
        faq=dict(item,location={'kind':'faq_answer','index':0},quote=b['article']['faqs'][0]['answer'])
        validate_feedback([faq],b)
        for bad in ([dict(item,quote='not in article')],[dict(item,location={'kind':'paragraph','index':True})], [dict(item,criterion='score')],[dict(item,nextAction='x'*401)], [item]*7):
            with self.assertRaises(ValueError):validate_feedback(bad,b)

    def test_wire_location_is_resolved_programmatically_and_ambiguity_rejected(self):
        b=bundle(); wire={'criterion':'wise_s','quote':b['article']['content'].split('\n\n')[0][:20],
                          'anchor':'grounded concern','nextAction':'Explain the documented choice.'}
        stored=resolve_feedback([wire],b);self.assertEqual({'kind':'paragraph','index':0},stored[0]['location'])
        self.assertNotIn('location',wire)
        for bad in (dict(wire,location={'kind':'paragraph','index':0}),dict(wire,quote='missing quote'),dict(wire,quote='検証済みの説明です。')):
            with self.assertRaises(ValueError):resolve_feedback([bad],b)
        b['article']['faqs']=[dict(q) for q in b['article']['faqs']]; b['article']['faqs'][0]['answer']='固有のFAQ回答です。'
        faq=resolve_feedback([dict(wire,quote='固有のFAQ回答です。')],b)
        self.assertEqual({'kind':'faq_answer','index':0},faq[0]['location'])
        b['article']['content']+='\n\n固有のFAQ回答です。'
        with self.assertRaises(ValueError):resolve_feedback([dict(wire,quote='固有のFAQ回答です。')],b)

    def test_v2_low_advisory_is_admitted_by_ledger_but_v1_cannot_be_upgraded(self):
        from ledger import valid_review, fingerprint
        b,r=self.review();b['articleReviewScoring']={'version':VERSION}
        r.update(evidence=dict(FLAGS),fingerprint=fingerprint(b),polish={'model':'gemini-3.8-flash','validated':True})
        valid_review(r,fingerprint(b),b)
        self.assertEqual('hard_checks_and_owner_floors',r['admissionMode'])
        for field in ('admissionMode','scoringVersion','calculation','improvementFeedback','feedbackValidation'):
            bad=copy.deepcopy(r);bad.pop(field)
            with self.assertRaises(ValueError):valid_review(bad,fingerprint(b),b)
        old=copy.deepcopy(b);old['articleReviewScoring']={'version':VERSION_V1}
        with self.assertRaises(ValueError):valid_review(r,fingerprint(old),old)

    def test_all_existing_format_bounds_and_shared_constant_agree(self):
        from review_scoring import ARTICLE_LENGTHS, CRITERIA_FIELDS
        from models import ARTICLE_LENGTHS as model_bounds
        self.assertEqual(model_bounds,ARTICLE_LENGTHS)
        for format_name,(low,high) in ARTICLE_LENGTHS.items():
            b=bundle();b['brief']['format']=format_name
            criteria={key:5 for key in CRITERIA_FIELDS if key!='word_count'}
            for count in (low,high):
                b['article']['content']='文'*count
                self.assertEqual(10,calculate(criteria,b)['calculation']['wordCount']['score'])
            for count in (low-1,high+1):
                b['article']['content']='文'*count
                with self.assertRaises(ValueError):calculate(criteria,b)

    def test_model_wire_feedback_resolves_without_changing_raw_and_schema_is_fatal(self):
        from models import Models, ModelError, article_review_schema, SOCIAL_REVIEW_SCHEMA
        from test_models import ENV, Fake, response, article_review_value
        import json
        b=bundle();wire=article_review_value(value=5);artifacts=[]
        raw=copy.deepcopy(wire)
        fake=Fake(response(wire));model=Models(ENV,fake,artifact_sink=artifacts.append)
        result=model.review(b,dict(editorialRules='v2',evidence=FLAGS,structural={'passed':True}))
        self.assertTrue(result['passed']);self.assertLess(result['score'],7.5)
        self.assertIn('location',result['improvementFeedback'][0]);self.assertEqual(raw,json.loads(artifacts[0]['content']))
        schema=article_review_schema(b)
        self.assertNotIn('word_count',schema['properties']['criteria']['properties'])
        self.assertNotIn('location',schema['properties']['improvementFeedback']['items']['properties'])
        self.assertNotIn('improvementFeedback',SOCIAL_REVIEW_SCHEMA['properties']);self.assertIn('passed',SOCIAL_REVIEW_SCHEMA['required'])
        for change in ({'location':{'kind':'paragraph','index':0}},):
            invalid=copy.deepcopy(raw);invalid['improvementFeedback'][0].update(change);fake=Fake(response(invalid))
            with self.assertRaises(ModelError):Models(ENV,fake).review(b,dict(editorialRules='v2',evidence=FLAGS,structural={'passed':True}))
            self.assertEqual(1,len(fake.calls))
        invalid=copy.deepcopy(raw);invalid['criteria']['word_count']=10
        with self.assertRaises(ModelError):Models(ENV,Fake(response(invalid))).review(b,dict(editorialRules='v2',evidence=FLAGS,structural={'passed':True}))

    def test_low_feedback_deficiency_is_advisory_and_commercial_criteria_are_allowed(self):
        from models import article_review_schema
        b=bundle();fields=article_review_schema(b)['properties']['criteria']['required']
        wire={'criterion':'wise_s','quote':b['article']['content'].split('\n\n')[0][:20],
              'anchor':'source-grounded relevance','nextAction':'Clarify this actual decision.'}
        stored=resolve_feedback([wire],b);criteria=dict.fromkeys(fields,8);criteria['faq']=4
        validate_feedback(stored,b,criteria)
        for key in ('affiliate_links','comparison_table'):
            self.assertIn(key,article_review_schema(b)['properties']['improvementFeedback']['items']['properties']['criterion']['enum'])
            criteria=dict.fromkeys(fields,8);criteria[key]=4
            stored=resolve_feedback([dict(wire,criterion=key)],b);validate_feedback(stored,b,criteria)
        from nonproduct_contract_fixture import fixture
        n=fixture()['bundle'];n['brief']={'format':'guide'};n['article']['content']+='\n\n'+ '根拠ある説明。'*450
        self.assertNotIn('affiliate_links',article_review_schema(n)['properties']['improvementFeedback']['items']['properties']['criterion']['enum'])
        with self.assertRaises(ValueError):resolve_feedback([dict(wire,criterion='affiliate_links',quote='図解です。')],n)

class AdvisoryFeedbackSelectionTests(unittest.TestCase):
    def test_selection_raw_preserved_revalidated_and_no_admission_gate(self):
        from models import Models
        from test_models import ENV, Fake, response, article_review_value
        import json
        b=bundle(); raw=article_review_value(value=5);valid=raw['improvementFeedback'][0]
        raw['improvementFeedback']=[valid,dict(valid,quote='missing Markdown-stripped quote')]
        artifacts=[];fake=Fake(response(raw))
        result=Models(ENV,fake,artifact_sink=artifacts.append).review(b,dict(editorialRules='v2',evidence=FLAGS,structural={'passed':True}))
        self.assertTrue(result['passed']);self.assertEqual(1,len(fake.calls))
        self.assertEqual(raw,json.loads(artifacts[0]['content']))
        self.assertEqual([0],result['feedbackValidation']['acceptedIndices'])
        self.assertEqual('partial',result['feedbackValidation']['status']);verify_review(result,b)
        for invalid in (None, [], 'partial'):
            bad=copy.deepcopy(result);bad['feedbackValidation']=invalid
            with self.assertRaises(ValueError):verify_review(bad,b)
        bad=copy.deepcopy(result);bad.pop('feedbackValidation')
        with self.assertRaises(ValueError):verify_review(bad,b)
        mutated=copy.deepcopy(result);mutated['feedbackValidation']['acceptedIndices']=[1]
        with self.assertRaises(ValueError):verify_review(mutated,b)
        for changes in ({},{'facts':False},{'wiseScores':dict(raw['wiseScores'],ai=2)}):
            wire=copy.deepcopy(raw);wire.update(changes);wire['improvementFeedback']=[dict(valid,quote='absent')]
            outcome=Models(ENV,Fake(response(wire))).review(b,dict(editorialRules='v2',evidence=FLAGS,structural={'passed':True}))
            self.assertEqual(not bool(changes),outcome['passed']);self.assertEqual([],outcome['improvementFeedback'])
            self.assertEqual('rejected',outcome['feedbackValidation']['status'])
            self.assertTrue(outcome['feedbackValidation']['missingLowCriteria']);verify_review(outcome,b)

    def test_wire_types_fatal_and_ambiguity_quarantined(self):
        from review_scoring import select_feedback
        b=bundle();wire={'criterion':'wise_s','quote':'absent','anchor':'specific concern','nextAction':'Clarify this decision.'}
        for change in ({'quote':3},{'anchor':None},{'extra':True},{'criterion':'word_count'}):
            with self.assertRaises(ValueError):select_feedback([dict(wire,**change)],b,{'wise_s':5})
        b['article']['content']+='\n\nduplicate quote\n\nduplicate quote'
        selected,meta=select_feedback([dict(wire,quote='duplicate quote')],b,{'wise_s':5})
        self.assertEqual([],selected);self.assertEqual('quote_ambiguous',meta['rejected'][0]['reason'])

if __name__=='__main__':unittest.main()
