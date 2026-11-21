"""Normal polish accepts only safe actual edits; no retries or fabricated usage."""
import copy
import unittest
from unittest.mock import patch
from models import Models, ModelError
from test_models import ENV, Fake, Budget, brief, response

class PolishSelectionTests(unittest.TestCase):
    def source(self):
        return '\n\n'.join(['対象の表示を確かめます。'*40]*8)
    def edits(self):
        return [{'index':i,'text':'表示を対象に合わせて読みます。'*35} for i in range(7)]+[{'index':7,'text':'手元で一目で分かります。'*40}]
    def test_seven_safe_edits_rejected_whole_numeric_edit_one_real_usage(self):
        source=self.source();raw={'edits':self.edits()};artifacts=[];budget=Budget();fake=Fake(response(raw,gemini=True))
        model=Models(ENV,fake,budget=budget,artifact_sink=artifacts.append);result=model.polish(source,brief())
        self.assertEqual(list(range(7)),result['polishSelection']['acceptedIndices'])
        self.assertEqual([{'index':7,'reason':'protected_content_introduced'}],result['polishSelection']['rejected'])
        self.assertEqual(source.split('\n\n')[7],result['content'].split('\n\n')[7])
        self.assertEqual('partial',result['polishSelection']['outcome']);self.assertFalse(result['polishSelection']['rawResponseAccepted'])
        self.assertEqual(1,len(fake.calls));self.assertEqual(1,len(model.usage));self.assertEqual(1,len(budget.holds));self.assertEqual(1,len(budget.settlements))
        import json
        self.assertEqual(raw,json.loads(artifacts[0]['content']))
    def test_wire_schema_type_duplicate_and_out_of_range_remain_fatal(self):
        for edits in ([{'index':0,'text':'x'},{'index':0,'text':'y'}],[{'index':True,'text':'x'}],
                      [{'index':8,'text':'x'}],[{'index':-1,'text':'x'}],[{'index':0,'text':None}],
                      [{'index':0,'text':'x','extra':'bad'}]):
            fake=Fake(response({'edits':edits},gemini=True))
            with self.assertRaises(ModelError):Models(ENV,fake).polish(self.source(),brief())
            self.assertEqual(1,len(fake.calls))
    def test_too_short_candidate_retains_entire_valid_source(self):
        source='対象の表示を確かめます。'*270
        result=Models(ENV,Fake(response({'edits':[{'index':0,'text':'表示を確認します。'}]},gemini=True))).polish(source,brief())
        self.assertEqual(source,result['content']);self.assertEqual([],result['polishSelection']['acceptedIndices'])
        self.assertEqual('whole_candidate_length_out_of_bounds',result['polishSelection']['rejected'][0]['reason'])
        self.assertEqual('no_changes_after_rejection',result['polishSelection']['outcome'])
    def test_global_preservation_failure_rejects_all_selected_edits(self):
        with patch('models.inspect_polish',return_value={'passed':False}):
            result=Models(ENV,Fake(response({'edits':self.edits()[:7]},gemini=True))).polish(self.source(),brief())
        self.assertEqual(self.source(),result['content']);self.assertEqual([],result['polishSelection']['acceptedIndices'])
        self.assertEqual(7,len(result['polishSelection']['rejected']))
    def test_outside_source_range_and_network_errors_have_no_content_fallback(self):
        fake=Fake()
        with self.assertRaises(ModelError):Models(ENV,fake).polish('short source',brief())
        self.assertEqual([],fake.calls)
        from test_models import http
        fake=Fake(http(401))
        with self.assertRaises(ModelError):Models(ENV,fake).polish(self.source(),brief())
        self.assertEqual(1,len(fake.calls))

    def test_sns_short_text_keeps_legacy_strict_behavior_without_article_bounds(self):
        fake=Fake(response({'edits':[{'index':0,'text':'読みやすい案内です。'}]},gemini=True))
        result=Models(ENV,fake).polish('短い案内です。',brief(),article=False)
        self.assertEqual('読みやすい案内です。',result['content']);self.assertEqual(1,len(fake.calls))
        bad=Fake(response({'edits':[{'index':0,'text':'一目で分かる案内です。'}]},gemini=True))
        with self.assertRaises(ModelError):Models(ENV,bad).polish('短い案内です。',brief(),article=False)
        self.assertEqual(1,len(bad.calls))

if __name__=='__main__':unittest.main()
