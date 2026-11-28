"""Offline typed-absence flow; no clinical advice, provider, or publication."""
import copy
import unittest
from unittest.mock import patch
from inherited_advice import TEMPLATE_FILES
from slack import Slack
import test_slack as slack_fixtures
import test_revision_workflow as revision_fixtures


def absence(slug):
    return {'schemaVersion': 1, 'kind': 'no_inherited_medical_advice', 'slug': slug,
            'selector': 'main article #article-reading-content aside[aria-label="医師からのアドバイス"]',
            'matchCount': 0, 'medicalAdviceMapStatus': 'slug_absent_from_static_literal_map',
            'medicalAdviceMapSha256': 'a' * 64,
            'templateFiles': {name: 'a' * 64 for name in TEMPLATE_FILES},
            'clinicalReverified': False, 'unchanged': True}


class InheritedAbsenceFlowTests(unittest.TestCase):
    def test_absent_advice_does_not_create_empty_medical_approval_message(self):
        fixture = slack_fixtures.SlackTests('test_inherited_plain_text_disables_emoji_conversion_and_rejects_readback_changes')
        fixture.setUp()
        client = Slack(fixture.config, call=fixture.call)
        job = {'id': 'test-revision', 'kind': 'article_revision',
               'bundle': {'article': {'title': '表示テスト', 'slug': 'test-article', 'content': '本文'},
                          'products': [], 'images': [],
                          'inheritedPresentationContext': absence('test-article')},
               'revisionContext': {'changeSummary': '表示確認'}}
        request = {'request_id': 'test-request', 'article_id': job['id'],
                   'manifest_hash': 'test-hash', 'nonce': 'test-value'}
        with patch.object(client, 'post', return_value={'verified': True, 'message_ts': '1793000000.123456'}) as post:
            client.deliver(job, request)
        text = str(post.call_args_list)
        self.assertNotIn('医師から一言', text)
        self.assertIn('camp_review_approve', text)

    def test_runtime_records_absence_without_inventing_a_medical_dom_hash(self):
        fixture = revision_fixtures.RevisionWorkflowTests('test_revision_request_separate_identity_and_caps_unchanged')
        fixture.setUp()
        try:
            base = revision_fixtures.baseline()
            job = fixture.request(base)
            fixture.fake_evidence()
            original = fixture.runtime.renderer
            def render(bundle, current):
                result = copy.deepcopy(original(bundle, current))
                result['inheritedPresentationContext'] = absence(bundle['article']['slug'])
                return result
            fixture.runtime.renderer = render
            fixture.runtime._make_article(job, fixture.context(base))
            saved = fixture.runtime.ledger.get_job(job['id'])
            self.assertEqual('review', saved['stage'])
            self.assertEqual('not_applicable', saved['review']['inheritedAdviceApplicability'])
            self.assertNotIn('inheritedAdviceDomSha256', saved['review'])
            self.assertIsNone(saved['approval'])
            self.assertIsNone(saved['publication'])
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
