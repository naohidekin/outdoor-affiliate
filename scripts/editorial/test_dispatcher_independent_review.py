"""Dispatcher handling of exact negative independent-review receipts."""
from datetime import datetime
import json
import unittest

from dispatcher import DeterministicDispatcher
from runtime import JST
import test_runtime
from test_inherited_advice import context as inherited_context
import test_revision_workflow as revision_fixtures


NOW = datetime(2026, 11, 28, 23, 5, tzinfo=JST)


class DispatcherIndependentReviewTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config['executionPolicy'] = {
            'mode': 'deterministic', 'suspended': False,
            'exceptions': {'autoAI': False},
        }
        self.config['independentReviewEnabled'] = False
        original = self.runtime.renderer
        def render(bundle, job):
            value = original(bundle, job)
            value['inheritedPresentationContext'] = inherited_context(
                bundle['article']['slug'])
            return value
        self.runtime.renderer = render
        self.base = revision_fixtures.baseline('article-005', 'single-burner-ranking')
        self.reviewed = self.runtime.ledger.request_revision(
            revision_fixtures.spec(self.base), now=NOW)
        revision_fixtures.RevisionWorkflowTests.fake_evidence(self)
        self.runtime._make_article(
            self.reviewed,
            revision_fixtures.RevisionWorkflowTests.context(self, self.base))
        self.reviewed = self.runtime.ledger.get_job(self.reviewed['id'])
        self.assertEqual('review', self.reviewed['stage'])
        self.assertIsNone(self.reviewed.get('astraReview'))
        self.candidate = self.runtime.ledger.request_revision(
            revision_fixtures.spec(revision_fixtures.baseline(
                'article-024', 'firepit-beginner-guide')), now=NOW)
        self.config['independentReviewEnabled'] = True

    tearDown = test_runtime.RuntimeTests.tearDown

    def receipt(self, *, fingerprint_value=None, passed=False, issues=None):
        return {
            'kind': 'independent_article_review_v1',
            'fingerprint': fingerprint_value or self.reviewed['revision'],
            'passed': passed,
            'issues': ([{'code': 'unsupported_claim', 'location': '本文',
                         'detail': '根拠との不一致'}] if issues is None else issues),
            'requestedModel': 'gpt-6-astra', 'actualModel': 'fixture',
            'usage': {'input_tokens': 1, 'output_tokens': 1},
            'actualInvoiceUsd': None, 'outputCapEnforced': False,
            'reservedOutputTokens': 16384,
        }

    def save_receipt(self, value):
        inputs = {'revision': self.reviewed['revision'],
                  'dependencies': {'exactRevision': self.reviewed['revision']},
                  'schemaVersion': 1}
        self.runtime.stage_journal.run(
            self.reviewed['id'], 'independent_review', inputs,
            lambda: value, max_attempts=1)
        return self.runtime.stage_journal.key(
            self.reviewed['id'], 'independent_review', inputs)

    def plan(self):
        return DeterministicDispatcher(self.runtime).plan(NOW)

    def test_exact_negative_review_blocks_delivery_and_allows_next_revision(self):
        self.save_receipt(self.receipt())

        plan = self.plan()

        self.assertIn({'jobId': self.reviewed['id'],
                       'reason': 'independent_review_requires_correction'},
                      plan['blocked'])
        self.assertEqual([{'kind': 'produce_revision',
                           'jobId': self.candidate['id']}], plan['actions'])

    def test_different_revision_positive_or_empty_issue_does_not_create_hold(self):
        for value in (
                self.receipt(fingerprint_value='0' * 64),
                self.receipt(passed=True, issues=[]),
                self.receipt(issues=[])):
            with self.subTest(value=value):
                key = self.save_receipt(value)
                plan = self.plan()
                self.assertNotIn('independent_review_requires_correction',
                                 {item['reason'] for item in plan['blocked']})
                self.assertEqual('deliver', plan['actions'][0]['kind'])
                with self.runtime.ledger._tx() as db:
                    db.execute('DELETE FROM meta WHERE key=?', (key,))

    def test_tampered_output_hash_does_not_create_false_negative_hold(self):
        key = self.save_receipt(self.receipt())
        with self.runtime.ledger._tx() as db:
            record = json.loads(db.execute(
                'SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            record['outputHash'] = '0' * 64
            db.execute('UPDATE meta SET value=? WHERE key=?',
                       (json.dumps(record), key))

        plan = self.plan()

        self.assertNotIn('independent_review_requires_correction',
                         {item['reason'] for item in plan['blocked']})
        self.assertEqual('deliver', plan['actions'][0]['kind'])

    def test_unrelated_nonobject_or_noncanonical_records_do_not_block(self):
        invalid = {
            'jobId': self.reviewed['id'], 'stage': 'independent_review',
            'status': 'succeeded', 'outputHash': '0' * 64,
            'output': {'kind': 'independent_article_review_v1',
                       'fingerprint': self.reviewed['revision'],
                       'passed': False, 'issues': [{'detail': float('nan')}]},
        }
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO meta VALUES (?,?)',
                       ('stage_journal:v1:nonobject', json.dumps([])))
            db.execute('INSERT INTO meta VALUES (?,?)',
                       ('stage_journal:v1:noncanonical', json.dumps(invalid)))
            db.execute('INSERT INTO meta VALUES (?,?)',
                       ('stage_journal:v1:unknown', json.dumps({
                           'jobId': self.reviewed['id'],
                           'stage': 'independent_review',
                           'status': 'in_flight'})))

        plan = self.plan()

        self.assertNotIn('independent_review_requires_correction',
                         {item['reason'] for item in plan['blocked']})
        self.assertEqual('deliver', plan['actions'][0]['kind'])


if __name__ == '__main__':
    unittest.main()
