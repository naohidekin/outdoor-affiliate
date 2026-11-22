"""SNS-only compatibility never upgrades articles or mutates approved records."""
import copy
from pathlib import Path
import tempfile
import unittest

from ledger import Ledger, fingerprint
from runtime import Runtime
from social_policy_compat import (LEGACY_APPROVED_SOCIAL_POLICY_ID,
                                  require_approved_social_review)
from wise_contract import load_policy


SCORES = dict(w=3, i=3, s=3, e=3, ai=3, sense=3)


def approved_job(policy_id=None):
    policy_id = policy_id or load_policy()['id']
    proposal = {'text': '承認済みSNS本文', 'deliveryMode': 'manual',
                'platform': 'x', 'wisePolicy': policy_id}
    revision = fingerprint(proposal)
    review = {
        'passed': True, 'score': 8.0, 'fingerprint': revision,
        'wisePolicy': policy_id, 'wiseScores': dict(SCORES),
        'evidence': {key: True for key in ('facts', 'images', 'affiliate', 'medical', 'render')},
        'polish': {'model': 'gemini-3.8-flash', 'validated': True},
    }
    return {
        'id': 'article-social-compat', 'stage': 'social_approved',
        'bundle': {'article': {'title': '互換性確認'}},
        'social': {
            'proposal': proposal, 'revision': revision, 'review': review,
            'approval': {'action': 'approved', 'revision': revision,
                         'user_id': 'owner', 'request_id': 'request-fixed'},
        },
    }


class SocialPolicyCompatibilityTests(unittest.TestCase):
    def test_current_and_fixed_legacy_exact_approvals_pass_without_mutation(self):
        for policy_id, expected in (
                (load_policy()['id'], 'current'),
                (LEGACY_APPROVED_SOCIAL_POLICY_ID, 'legacy_approved_social_only')):
            job = approved_job(policy_id)
            before = copy.deepcopy(job)
            result = require_approved_social_review(job, 'owner')
            self.assertEqual(expected, result['compatibility'])
            self.assertEqual(before, job)

    def test_unknown_mixed_unapproved_changed_or_failed_floor_is_rejected(self):
        cases = []
        unknown = approved_job('f' * 64)
        cases.append(unknown)
        mixed = approved_job(LEGACY_APPROVED_SOCIAL_POLICY_ID)
        mixed['social']['review']['wisePolicy'] = load_policy()['id']
        cases.append(mixed)
        unapproved = approved_job(LEGACY_APPROVED_SOCIAL_POLICY_ID)
        unapproved['social']['approval'] = None
        cases.append(unapproved)
        changed = approved_job(LEGACY_APPROVED_SOCIAL_POLICY_ID)
        changed['social']['proposal']['text'] += '変更'
        cases.append(changed)
        below = approved_job(LEGACY_APPROVED_SOCIAL_POLICY_ID)
        below['social']['review']['wiseScores']['ai'] = 2
        cases.append(below)
        for job in cases:
            with self.subTest(job=job):
                with self.assertRaisesRegex(ValueError, 'approved_social_policy_review_required'):
                    require_approved_social_review(job, 'owner')

    def test_article_shaped_record_cannot_use_social_compatibility(self):
        article = {'stage': 'awaiting_approval', 'bundle': {'wisePolicy': LEGACY_APPROVED_SOCIAL_POLICY_ID},
                   'review': {'wisePolicy': LEGACY_APPROVED_SOCIAL_POLICY_ID}}
        with self.assertRaisesRegex(ValueError, 'approved_social_policy_review_required'):
            require_approved_social_review(article, 'owner')

    def test_manual_handoff_accepts_only_exact_approved_legacy_revision(self):
        job = approved_job(LEGACY_APPROVED_SOCIAL_POLICY_ID)
        before = copy.deepcopy(job)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime.__new__(Runtime)
            runtime.root = Path(tmp)
            runtime.ledger = Ledger(runtime.root, 'owner')
            runtime.config = {'slack': {'user_id': 'owner'}}
            runtime._require_running = lambda: None
            notices = []
            runtime.slack = type('SlackFake', (), {'notice': lambda self, text: notices.append(text)})()
            runtime.prepare_social_handoff(job)
            marker = runtime.root / 'social-outbox' / (job['social']['revision'] + '.json')
            self.assertTrue(marker.is_file())
            self.assertEqual(1, len(notices))
        self.assertEqual(before, job)


if __name__ == '__main__':
    unittest.main()
