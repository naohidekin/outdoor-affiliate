"""Offline plans: pending social AI must not starve authorized article work."""
from datetime import datetime
import json
import unittest

from dispatcher import DeterministicDispatcher
from runtime import JST
import test_runtime

NOW = datetime(2026, 11, 22, 10, tzinfo=JST)


class DispatcherArticlePriorityTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config.update(executionPolicy={'mode': 'deterministic', 'suspended': False},
                           socialGenerationEnabled=True, supplementalApparelEnabled=True)
        self.social = self.save('published-social-needed', 'published', publication={'verified': True})
        # Real due checks, with all three regular period slots already consumed.
        self.period = self.runtime.ledger.production_schedule.period_key(NOW)
        for i in range(3):
            self.save('closed-regular-' + str(i), 'rejected', week=self.period)

    tearDown = test_runtime.RuntimeTests.tearDown

    def save(self, id, stage, **extra):
        job = dict(id=id, stage=stage, week='2026-10-30', social=None,
                   publication=None, priority=1, theme={'slug': id}, revision=None)
        job.update(extra)
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, job, 'synthetic_priority_fixture')
        return job

    def plan(self):
        return DeterministicDispatcher(self.runtime).plan(NOW)

    def assert_action(self, kind, job_id=None, **extra):
        self.assertEqual([dict(kind=kind, jobId=job_id, **extra)], self.plan()['actions'])
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)

    def test_due_supplemental_precedes_published_job_social_ai(self):
        self.assertTrue(self.runtime.supplemental_due(NOW))
        self.assert_action('produce_supplemental')
        self.assertEqual(self.social, self.runtime.ledger.get_job(self.social['id']))

    def test_no_article_work_retains_social_generation(self):
        self.config['supplementalApparelEnabled'] = False
        self.assert_action('make_social', self.social['id'])

    def test_candidate_revision_regular_and_supplemental_precede_social_ai(self):
        for kind, action in [('article_revision', 'produce_revision'),
                             ('new_article', 'produce'), ('supplemental_article', 'produce_supplemental')]:
            job = self.save('candidate', 'candidate', kind=kind)
            self.assert_action(action, job['id'])
            self.save('candidate', 'rejected', kind=kind)

    def test_due_regular_vacancy_precedes_social_ai(self):
        self.save('closed-regular-2', 'rejected', week='2026-10-30')
        self.assert_action('produce')

    def test_publication_and_social_delivery_effects_stay_first(self):
        self.config.update(socialReviewEnabled=True, socialPostingEnabled=True, bufferPostingEnabled=True)
        modes = [('approved', {}, 'publish', {}),
                 ('social_review', {}, 'deliver', {'deliveryKind': 'social'}),
                 ('social_approved', {'social': {'proposal': {'deliveryMode': 'auto_x'}}}, 'publish_social', {}),
                 ('social_approved', {'social': {'proposal': {'deliveryMode': 'buffer_x'}}}, 'publish_buffer_social', {})]
        for stage, extra, action, detail in modes:
            with self.subTest(stage=stage, action=action):
                self.save('true-effect', stage, **extra)
                self.assert_action(action, 'true-effect', **detail)
        self.config['publicationEnabled'] = False
        self.save('true-effect', 'approved')
        self.assertNotIn('publish', [a['kind'] for a in self.plan()['actions']])

    def test_valid_article_review_delivery_stays_first(self):
        from wise_contract import load_policy
        from test_quality import bundle
        policy = load_policy()
        job = self.save('reviewed-priority', 'candidate')
        value = bundle()
        value['wisePolicy'] = policy['id']
        job = self.runtime.ledger.save_bundle(job['id'], value)
        self.runtime.ledger.record_review(job['id'], job['revision'], {
            'passed': True, 'score': 8.5, 'model': 'upper', 'issues': [],
            'wisePolicy': policy['id'], 'wiseScores': dict(w=3, i=3, s=3, e=3, ai=3, sense=3),
            'fingerprint': job['revision'],
            'evidence': {k: True for k in ('facts', 'images', 'affiliate', 'medical', 'render')},
            'polish': {'model': 'gemini-3.8-flash', 'validated': True}})
        self.assert_action('deliver', job['id'], deliveryKind='article')

    def test_disabled_generation_keeps_social_or_no_work_per_own_flag(self):
        self.save('candidate', 'candidate', kind='supplemental_article')
        self.config['generationEnabled'] = False
        self.assert_action('make_social', self.social['id'])
        self.config['socialGenerationEnabled'] = False
        self.assertEqual([], self.plan()['actions'])
        self.config['generationEnabled'] = True
        self.assert_action('produce_supplemental', 'candidate')

    def test_pending_three_does_not_become_four(self):
        for i in range(3):
            self.save('pending-' + str(i), 'held')
        self.assert_action('make_social', self.social['id'])

    def test_unknown_job_is_not_produced_and_manager_unknown_blocks_all(self):
        job = self.save('uncertain', 'candidate', kind='article_revision')
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (job['id'], 'publish', 'unknown', '{}'))
        self.config['supplementalApparelEnabled'] = False
        self.assert_action('make_social', self.social['id'])
        self.assertEqual([{'jobId': job['id'], 'reason': 'effect_requires_reconciliation'}], self.plan()['blocked'])
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO meta VALUES (?,?)', ('editorial_manager:unknown',
                json.dumps({'status': 'executing', 'action': {'jobId': job['id']}})))
        self.assertEqual([], self.plan()['actions'])

    def test_owner_waiting_article_branch_also_prefers_supplemental_then_social(self):
        self.save('owner-waiting', 'approved')
        self.config['publicationEnabled'] = False
        self.assert_action('produce_supplemental')
        self.config['supplementalApparelEnabled'] = False
        self.assert_action('make_social', self.social['id'])

    def test_suspended_still_has_no_actions(self):
        self.config['executionPolicy']['suspended'] = True
        self.assertEqual([], self.plan()['actions'])
        self.assertEqual('suspended', self.plan()['status'])


if __name__ == '__main__':
    unittest.main()
