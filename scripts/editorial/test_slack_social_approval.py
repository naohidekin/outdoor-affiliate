"""Offline original-Slack-message approval; no transport or live state."""
import copy
import json
import unittest
from ledger import fingerprint
from test_codex_social_approval import CodexSocialApprovalTests, SCOPE
from slack_social_approval import approve_social_from_slack_message

class SlackSocialApprovalTests(CodexSocialApprovalTests):
    # Reuse isolated fixture helpers, not inherited Codex tests.
    def setUp(self):
        super().setUp()
        other=copy.deepcopy(self.job);other['id']='article-second';self.save(other)
        self.ids=[self.job['id'],other['id']]
        self.scope=dict(SCOPE)
        items=[dict(item=n, **self.directive(j)) for n,j in zip([4,5],[self.job,other])]
        display='\n\n'.join(j['social']['proposal']['text']+'\n'+j['social']['proposal']['replyText']+'\n'+'\n'.join(x['url'] for x in j['social']['proposal']['images']) for j in [self.job,other])
        self.ev={'source':'slack_owner_message','scope':self.scope,'message_ts':'10.1','text':'上の２記事はGO','observed_at':'2026-11-13T11:00:00+09:00','context':{'message_ts':'9.1','text':display,'items':items,'interveningMessages':[],'threadReadThroughTs':'10.1','threadObservationReference':'offline-complete-thread-readback'},'absence':{'checked_at':'2026-11-13T10:59:00+09:00','articleIds':self.ids,'regularPublisher':True,'savedAlternateRoute':True,'publicPlatform':True,'evidenceReferences':['offline-public-profile-and-ledgers-observation']}}
    def apply(self,ev=None):
        return approve_social_from_slack_message(self.ledger,ev or self.ev,self.scope)
    def test_batch_exact_and_no_effect_preserves_delivery_unknown(self):
        marker=self.root/'deliveries'/'unknown.json';marker.parent.mkdir(exist_ok=True);marker.write_text('{"status":"in_flight"}')
        result=self.apply();self.assertEqual([j['stage'] for j in result],['social_approved']*2)
        self.assertEqual(marker.read_text(),'{"status":"in_flight"}')
        before=self.state();self.apply();self.assertEqual(before,self.state())
        self.assertFalse((self.root/'social-publications').exists())
    def test_rejects_changed_binding_context_owner_and_unknown_atomically(self):
        cases=[]
        for key,val in [('source','codex'),('text','OK'),('message_ts','8.1')]:
            e=copy.deepcopy(self.ev);e[key]=val;cases.append(e)
        e=copy.deepcopy(self.ev);e['scope']['user_id']='other';cases.append(e)
        e=copy.deepcopy(self.ev);e['context']['items'][1]['revision']='0'*64;cases.append(e)
        e=copy.deepcopy(self.ev);e['context']['text']='shown';cases.append(e)
        e=copy.deepcopy(self.ev);e['absence']['savedAlternateRoute']=False;cases.append(e)
        e=copy.deepcopy(self.ev);e['absence']['publicPlatform']=False;cases.append(e)
        for e in cases:
            before=self.state()
            with self.assertRaises(ValueError):self.apply(e)
            self.assertEqual(before,self.state())
        folder=self.root/'social-publications';folder.mkdir();(folder/(self.job['social']['revision']+'.json')).write_text('{}')
        before=self.state()
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(before,self.state())

    def test_same_owner_message_cannot_bind_different_context(self):
        self.apply();before=self.state();e=copy.deepcopy(self.ev)
        e['context']['message_ts']='9.2'
        with self.assertRaises(ValueError):self.apply(e)
        self.assertEqual(before,self.state())

    def test_second_item_existing_publication_rejects_whole_batch(self):
        job=self.ledger.get_job(self.ids[1]);job['social']['publication']={'verified':True};self.save(job)
        before=self.state()
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(before,self.state())


    def test_intervening_two_article_publication_prompt_is_ambiguous(self):
        e=copy.deepcopy(self.ev)
        e['context']['interveningMessages']=[{'message_ts':'9.9','text':'【記事のGO待ち】US1900 / UK4075'}]
        before=self.state()
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.apply(e)
        self.assertEqual(before,self.state())


# Do not run inherited Codex tests twice under this subclass.
for name in list(vars(CodexSocialApprovalTests)):
    if name.startswith('test_') and name not in vars(SlackSocialApprovalTests):
        setattr(SlackSocialApprovalTests,name,None)
