"""Partial contract failures are quarantined, never repaired or reclassified."""
import copy
import json
import unittest
from unittest.mock import patch

from ledger import fingerprint
from models import Models, ModelError, ModelOutcomeUnknown
from test_models import ENV, Fake, response
from test_topic_selection import proposal
from topic_selection import TopicSelectionError
import test_research_contract_recovery as fixtures


class CandidateIsolationModelTests(unittest.TestCase):
    def context(self):
        return {'catalog': [{'id': 'known-product'}], 'categories': [{'id': 'camp-howto'}],
                'existingArticles': [{'id': 'known-article'}]}

    def test_partial_preserves_valid_json_and_same_memberships_with_safe_metadata(self):
        good = proposal('known-good', '既存仕様から選ぶには？', productIds=['known-product'])
        bad = [dict(good, slug='bad-overlap', overlapArticleIds=['known-article']),
               dict(good, slug='bad-product', productIds=['unknown-product']),
               dict(good, slug='bad-category', categoryId='unknown-category')]
        original = {'proposals': [bad[0], good, bad[1], bad[2]]}
        before = copy.deepcopy(original)
        raw = response(original)
        raw['id'] = 'partial-response'
        fake = Fake(raw)
        artifacts = []
        model = Models(ENV, fake, artifact_sink=artifacts.append)
        result = model.research_mixed(self.context())
        self.assertEqual([good], result['proposals'])
        self.assertEqual(before, original)
        self.assertEqual([0, 2, 3], [r['index'] for r in result['contractRejections']])
        self.assertEqual(['proposal_contract', 'proposal_product_route', 'proposal_contract'],
                         [r['reason'] for r in result['contractRejections']])
        self.assertEqual(4, result['rawProposalCount'])
        self.assertEqual('partial-response', result['responseId'])
        self.assertEqual(original, json.loads(artifacts[0]['content']))
        self.assertEqual(1, len(fake.calls))
        self.assertEqual(1, len(model.usage))

    def test_all_valid_keeps_existing_return_shape(self):
        raw = {'proposals': [proposal('good-one', '準備の選び方は？'), proposal('good-two', '保管はどうする？')]}
        fake = Fake(response(raw))
        self.assertEqual(raw, Models(ENV, fake).research_mixed(self.context()))
        self.assertEqual(1, len(fake.calls))

    def test_all_invalid_is_one_response_then_existing_exception(self):
        raw = {'proposals': [proposal('bad-' + str(i), '準備の選び方は？',
                                      overlapArticleIds=['known-article']) for i in range(7)]}
        fake = Fake(response(raw))
        with self.assertRaisesRegex(TopicSelectionError, '^proposal_contract$'):
            Models(ENV, fake).research_mixed(self.context())
        self.assertEqual(1, len(fake.calls))

    def test_malformed_candidate_is_quarantined_but_batch_bounds_stay_strict(self):
        good = proposal('good-one', '準備の選び方は？')
        raw = {'proposals': [dict(good, sourceIds=[{}]), good]}
        result = Models(ENV, Fake(response(raw))).research_mixed(self.context())
        self.assertEqual([good], result['proposals'])
        self.assertEqual('proposal_contract_type', result['contractRejections'][0]['reason'])
        for proposals in ([], [good] * 10):
            with self.assertRaisesRegex(TopicSelectionError, 'one_to_nine'):
                Models(ENV, Fake(response({'proposals': proposals}))).research_mixed(self.context())


class CandidateIsolationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ResearchContractRecoveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        # Isolated temp normal-production fixture, not the spent native repair.
        self.f.marker.unlink()
        self.artifacts = []
        self.f.rt.models.artifact_sink = self.artifacts.append
        # Shared positive fixtures must carry matched PT query evidence, not a generic GSC token.
        demand = [s for s in self.f.context['editorialSignals'] if s['kind'] == 'own_site_query_demand']
        self.assertEqual(3, len(demand))
        self.assertTrue(all(s['period']['dateBasis'] == 'America/Los_Angeles' for s in demand))
        self.assertNotIn('synthetic-private-demand-canary', json.dumps(self.f.context))

    def set_response(self, proposals):
        value = response({'proposals': proposals})
        value['id'] = 'new-partial-response'
        self.f.request.results = [value]

    def test_partial_three_valid_one_invalid_makes_three_slots_and_keeps_qa_path(self):
        good = copy.deepcopy(self.f.proposals)
        bad = dict(good[0], slug='contradictory-overlap', overlapArticleIds=['known-article'])
        self.f.context['existingArticles'] = [{'id': 'known-article'}]
        self.set_response(good + [bad])
        snapshot = self.f.root / 'research-contexts' / (fixtures.recovery.PERIOD + '.json')
        original_transport = self.f.rt.models.request
        def transport(*args):
            self.assertEqual(self.f.context, json.loads(snapshot.read_text()))
            return original_transport(*args)
        self.f.rt.models.request = transport
        self.assertEqual(3, len(self.f.produce()['articles']))
        self.assertEqual(1, len(self.f.request.calls))
        marker = json.loads(self.f.marker.read_text())
        receipt = json.loads((self.f.root / 'period-receipts' / (fixtures.recovery.PERIOD + '.json')).read_text())
        for saved in (marker, receipt):
            self.assertEqual(4, saved['rawProposalCount'])
            self.assertEqual('new-partial-response', saved['responseId'])
            self.assertEqual([{'index': 3, 'slug': 'contradictory-overlap', 'reason': 'proposal_contract'}], saved['contractRejections'])
            self.assertEqual(fingerprint(self.f.context), saved['researchContextSha256'])
        self.assertEqual(good, marker['proposals'])
        self.assertTrue(all(j['stage'] == 'review' and j['approval'] is None for j in self.f.rt.ledger.list_jobs()))
        self.assertEqual(4, len(json.loads(self.artifacts[0]['content'])['proposals']))

    def test_seven_rejected_two_without_own_evidence_hold_with_zero_eligibility(self):
        good = copy.deepcopy(self.f.proposals[:2])
        for p in good:
            p['sourceIds'] = p['sourceIds'][1:]  # No own GSC/GA4 evidence; never invent it.
        bad = [dict(good[0], slug='overlap-' + str(i), overlapArticleIds=['known-article']) for i in range(7)]
        self.f.context['existingArticles'] = [{'id': 'known-article'}]
        self.set_response(bad + good)
        result = self.f.produce()
        self.assertEqual('blocked', result['status'])
        self.assertEqual(0, result['eligibleCount'])
        receipt = json.loads((self.f.root / 'period-receipts' / (fixtures.recovery.PERIOD + '.json')).read_text())
        self.assertEqual(9, receipt['rawProposalCount'])
        self.assertEqual(7, len(receipt['contractRejections']))
        self.assertEqual(2, receipt['proposalCount'])
        self.assertEqual([], self.f.rt.ledger.list_jobs())
        self.assertEqual(1, len(self.f.request.calls))

    def test_all_invalid_stops_after_one_call_with_snapshot_and_no_auto_retry(self):
        p = self.f.proposals[0]
        self.set_response([
            dict(p, proposedAction='new', overlapArticleIds=['unsupplied-article']),
            dict(p, selectionReason='あ' * 601),
            dict(p, selectionReason='い' * 565)])
        result = self.f.produce()
        self.assertEqual({'status':'blocked', 'reason':'research_contract_rejected',
                          'articles':[], 'retryable':False}, result)
        marker = json.loads(self.f.marker.read_text())
        self.assertEqual('research_contract_rejected', marker['status'])
        self.assertIs(True, marker['requestOccurred'])
        self.assertEqual('new-partial-response', marker['responseId'])
        self.assertEqual(3, marker['rawProposalCount'])
        self.assertEqual([['overlap_id_not_in_supplied_articles', 'new_has_overlap'],
                          ['selectionReason_over_500'], ['selectionReason_over_500']],
                         [item['details'] for item in marker['contractRejections']])
        self.assertEqual(fingerprint(self.f.context), marker['researchContextSha256'])
        self.assertTrue((self.f.root / 'research-contexts' / (fixtures.recovery.PERIOD + '.json')).exists())
        self.assertFalse((self.f.root / 'period-receipts' / (fixtures.recovery.PERIOD + '.json')).exists())
        self.assertEqual(result, self.f.produce())
        self.assertEqual(1, len(self.f.request.calls))
        self.assertEqual([], self.f.rt.ledger.list_jobs())

    def test_transport_failure_keeps_original_unknown_and_is_not_retried(self):
        with patch.object(self.f.rt.models, 'request', side_effect=TimeoutError('unknown')) as transport:
            with self.assertRaisesRegex(ModelOutcomeUnknown, 'unknown'):
                self.f.produce()
            self.assertEqual('in_flight', json.loads(self.f.marker.read_text())['status'])
            with self.assertRaisesRegex(ValueError, 'reconciliation'):
                self.f.produce()
        self.assertEqual(1, transport.call_count)

    def test_partial_research_does_not_bypass_normal_article_quality_failure(self):
        good = copy.deepcopy(self.f.proposals)
        bad = dict(good[0], intent='not an enum')
        self.set_response(good + [bad])
        with patch('runtime.require_fresh_daily_metrics'), \
                patch('runtime.collect_primary_sources', return_value=self.f.feed), \
                patch.object(self.f.rt, '_research_context', return_value=self.f.context), \
                patch.object(self.f.rt, '_make_article', side_effect=ValueError('article_structure_or_affiliate_failed')) as qa:
            result = self.f.rt.produce(limit=99)
        self.assertEqual(3, qa.call_count)
        self.assertTrue(all(row['status'] == 'blocked' and row['reason'] == 'article_structure_or_affiliate_failed'
                            for row in result['articles']))
        self.assertEqual(1, len(self.f.request.calls))
        self.assertTrue(all(j['stage'] == 'error' and j['approval'] is None and j['publication'] is None
                            for j in self.f.rt.ledger.list_jobs()))
        self.assertEqual([], self.f.rt.slack.deliveries)

    def test_new_snapshot_does_not_erase_a_previous_context(self):
        from runtime import atomic
        previous = {'catalog': [{'id': 'previous-catalog-id'}], 'existingArticles': []}
        snapshot = self.f.root / 'research-contexts' / (fixtures.recovery.PERIOD + '.json')
        atomic(snapshot, previous)
        self.f.produce()
        archived = snapshot.with_name(fixtures.recovery.PERIOD + '-' + fingerprint(previous) + '.json')
        self.assertEqual(previous, json.loads(archived.read_text()))
        self.assertEqual(self.f.context, json.loads(snapshot.read_text()))

    def test_secret_context_is_not_saved_or_sent(self):
        self.f.context['accidental'] = ENV['ANTHROPIC_API_KEY']
        with self.assertRaisesRegex(ModelError, 'Sensitive data blocked'):
            self.f.produce()
        self.assertFalse((self.f.root / 'research-contexts' / (fixtures.recovery.PERIOD + '.json')).exists())
        self.assertEqual([], self.f.request.calls)


if __name__ == '__main__':
    unittest.main()
