"""Offline deterministic dispatcher contracts."""
from datetime import datetime
import json
import sqlite3
import unittest

from dispatcher import DeterministicDispatcher, buffer_social_eligible, execution_policy
from runtime import JST
import test_runtime


NOW = datetime(2026, 11, 11, 10, tzinfo=JST)


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config['executionPolicy'] = {
            'mode': 'deterministic', 'suspended': False,
            'exceptions': {'autoAI': False},
        }

    tearDown = test_runtime.RuntimeTests.tearDown

    def plan(self):
        return DeterministicDispatcher(self.runtime).plan(NOW)

    def test_policy_is_opt_in_strict_and_defaults_exception_ai_off(self):
        self.assertIsNone(execution_policy({}))
        self.assertEqual(False, execution_policy({
            'executionPolicy': {'mode': 'deterministic', 'suspended': False}
        }).auto_ai_exceptions)
        invalid = [
            None, {}, {'mode': 'legacy', 'suspended': False},
            {'mode': 'deterministic', 'suspended': 0},
            {'mode': 'deterministic', 'suspended': False, 'exceptions': None},
            {'mode': 'deterministic', 'suspended': False, 'exceptions': {'autoAI': 'false'}},
            {'mode': 'deterministic', 'suspended': False, 'exceptions': {'autoAI': True}},
            {'mode': 'deterministic', 'suspended': False, 'unknown': True},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid executionPolicy'):
                execution_policy({'executionPolicy': value})

    def test_existing_candidate_is_selected_once_without_manager_or_wait_ai(self):
        first = self.runtime.ledger.create_candidate({'slug': 'first', 'title': 'First'}, now=NOW)
        self.runtime.ledger.create_candidate({'slug': 'second', 'title': 'Second'}, now=NOW)
        plan = self.plan()
        self.assertEqual([{'kind': 'produce', 'jobId': first['id']}], plan['actions'])
        self.assertEqual([], plan['blocked'])
        self.assertFalse(plan['exceptionAI'])

    def test_review_delivery_and_approval_wait_do_not_schedule_generation(self):
        reviewed = self.runtime.ledger.create_candidate({'slug': 'reviewed', 'title': 'Reviewed'}, now=NOW)
        from wise_contract import load_policy
        policy = load_policy()
        current_bundle = __import__('test_quality').bundle()
        current_bundle['wisePolicy'] = policy['id']
        self.runtime.ledger.save_bundle(reviewed['id'], current_bundle)
        reviewed = self.runtime.ledger.get_job(reviewed['id'])
        review = {'passed': True, 'score': 8.5, 'model': 'upper', 'issues': [],
            'wisePolicy': policy['id'], 'wiseScores':dict(w=3,i=3,s=3,e=3,ai=3,sense=3),
                  'fingerprint': reviewed['revision'],
                  'evidence': {k: True for k in ('facts', 'images', 'affiliate', 'medical', 'render')},
                  'polish': {'model': 'gemini-3.8-flash', 'validated': True}}
        self.runtime.ledger.record_review(reviewed['id'], reviewed['revision'], review)
        plan = self.plan()
        self.assertEqual([{'kind': 'deliver', 'jobId': reviewed['id'], 'deliveryKind': 'article'}], plan['actions'])
        self.assertNotIn('produce', {action['kind'] for action in plan['actions']})

    def test_delivered_review_does_not_block_an_existing_candidate(self):
        reviewed = self.runtime.ledger.create_candidate({'slug': 'delivered', 'title': 'Delivered'}, now=NOW)
        from wise_contract import load_policy
        policy = load_policy()
        current_bundle = __import__('test_quality').bundle()
        current_bundle['wisePolicy'] = policy['id']
        self.runtime.ledger.save_bundle(reviewed['id'], current_bundle)
        reviewed = self.runtime.ledger.get_job(reviewed['id'])
        self.runtime.ledger.record_review(reviewed['id'], reviewed['revision'], {
            'passed': True, 'score': 8.5, 'model': 'upper', 'issues': [],
            'wisePolicy': policy['id'], 'wiseScores':dict(w=3,i=3,s=3,e=3,ai=3,sense=3),
            'fingerprint': reviewed['revision'],
            'evidence': {k: True for k in ('facts', 'images', 'affiliate', 'medical', 'render')},
            'polish': {'model': 'gemini-3.8-flash', 'validated': True},
        })
        self.runtime.deliver(reviewed['id'])
        candidate = self.runtime.ledger.create_candidate({'slug': 'next', 'title': 'Next'}, now=NOW)
        self.assertEqual([{'kind': 'produce', 'jobId': candidate['id']}], self.plan()['actions'])

    def test_historical_social_posted_does_not_block_due_period_generation(self):
        historical = self.runtime.ledger.create_candidate({'slug': 'posted', 'title': 'Posted'}, now=NOW)
        job = self.runtime.ledger.get_job(historical['id'])
        job.update(stage='social_posted', publication={'verified': True},
                   social={'revision': 'r', 'publication': {'verified': True}})
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            db.execute('UPDATE jobs SET data=? WHERE id=?',
                       (json.dumps(job, sort_keys=True, separators=(',', ':')), job['id']))
        marker = self.runtime.root / 'social-posted-notices/r.json'
        marker.parent.mkdir(mode=0o700)
        marker.write_text('{"status":"verified"}')
        self.assertEqual([{'kind': 'produce', 'jobId': None}], self.plan()['actions'])

    def test_astra_waiting_review_does_not_deliver_or_starve_existing_candidate(self):
        for kind in ('catalog_correction', 'article_revision'):
            with self.subTest(kind=kind):
                with sqlite3.connect(self.runtime.ledger.db_path) as db:
                    db.execute('DELETE FROM jobs')
                reviewed = self.runtime.ledger.create_candidate(
                    {'slug': 'astra-' + kind, 'title': 'Astra wait'}, now=NOW)
                from wise_contract import load_policy
                policy = load_policy()
                current_bundle = __import__('test_quality').bundle()
                current_bundle['wisePolicy'] = policy['id']
                self.runtime.ledger.save_bundle(reviewed['id'], current_bundle)
                reviewed = self.runtime.ledger.get_job(reviewed['id'])
                self.runtime.ledger.record_review(reviewed['id'], reviewed['revision'], {
                    'passed': True, 'score': 8.5, 'model': 'upper', 'issues': [],
            'wisePolicy': policy['id'], 'wiseScores':dict(w=3,i=3,s=3,e=3,ai=3,sense=3),
                    'fingerprint': reviewed['revision'],
                    'evidence': {k: True for k in ('facts', 'images', 'affiliate', 'medical', 'render')},
                    'polish': {'model': 'gemini-3.8-flash', 'validated': True},
                })
                reviewed = self.runtime.ledger.get_job(reviewed['id'])
                if kind == 'article_revision':
                    reviewed['kind'] = kind
                else:
                    reviewed['catalogCorrectionContext'] = {'kind': kind}
                with sqlite3.connect(self.runtime.ledger.db_path) as db:
                    db.execute('UPDATE jobs SET data=? WHERE id=?',
                               (json.dumps(reviewed, sort_keys=True, separators=(',', ':')),
                                reviewed['id']))
                candidate = self.runtime.ledger.create_candidate(
                    {'slug': 'next-' + kind, 'title': 'Next'}, now=NOW)
                self.assertEqual([{'kind': 'produce', 'jobId': candidate['id']}],
                                 self.plan()['actions'])
                self.assertEqual([], self.slack.deliveries)

    def test_unknown_effect_blocks_only_its_job(self):
        blocked = self.runtime.ledger.create_candidate({'slug': 'blocked', 'title': 'Blocked'}, now=NOW)
        ready = self.runtime.ledger.create_candidate({'slug': 'ready', 'title': 'Ready'}, now=NOW)
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)',
                       (blocked['id'], 'publish', 'unknown', '{}'))
        plan = self.plan()
        self.assertEqual([{'kind': 'produce', 'jobId': ready['id']}], plan['actions'])
        self.assertEqual([{'jobId': blocked['id'], 'reason': 'effect_requires_reconciliation'}],
                         plan['blocked'])

    def test_unknown_manager_execution_blocks_all_progress_without_mutating_receipt(self):
        job = self.runtime.ledger.create_candidate({'slug': 'blocked-manager', 'title': 'Blocked'}, now=NOW)
        receipt = {'status': 'executing', 'action': {'job_id': job['id']}}
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            db.execute('INSERT INTO meta VALUES (?,?)',
                       ('editorial_manager:unknown', json.dumps(receipt)))
        plan = self.plan()
        self.assertEqual([], plan['actions'])
        self.assertEqual([{'jobId': job['id'], 'reason': 'manager_execution_requires_reconciliation'}],
                         plan['blocked'])
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            saved = json.loads(db.execute(
                "SELECT value FROM meta WHERE key='editorial_manager:unknown'").fetchone()[0])
        self.assertEqual(receipt, saved)

    def test_suspended_plan_has_no_actions(self):
        self.runtime.ledger.create_candidate({'slug': 'suspended', 'title': 'Suspended'}, now=NOW)
        self.config['executionPolicy']['suspended'] = True
        self.assertEqual({'mode': 'deterministic', 'status': 'suspended', 'actions': [],
                          'blocked': [], 'exceptionAI': False}, self.plan())

    def test_regular_period_has_priority_then_supplemental_lane_is_separate(self):
        self.config['supplementalApparelEnabled'] = True
        test_runtime.RuntimeTests.configure_production_schedule(self)
        due = datetime(2026, 11, 16, 9, tzinfo=JST)
        plan = DeterministicDispatcher(self.runtime).plan(due)
        self.assertEqual([{'kind': 'produce', 'jobId': None}], plan['actions'])
        for index in range(3):
            job = self.runtime.ledger.create_candidate({'slug': f'regular-{index}'}, now=due)
            self.runtime.ledger.set_stage(job['id'], 'rejected')
        plan = DeterministicDispatcher(self.runtime).plan(due)
        self.assertEqual([{'kind': 'produce_supplemental', 'jobId': None}], plan['actions'])

    def test_supplemental_social_waits_for_bound_november_twentieth_route(self):
        self.config['bufferSocialStartPeriod'] = '2026-11-20'
        job = {'kind': 'supplemental_article', 'week': '2026-11-13',
               'socialEligiblePeriod': '2026-11-20'}
        self.assertFalse(buffer_social_eligible(
            job, self.config, datetime(2026, 11, 19, 23, 59, tzinfo=JST)))
        self.assertTrue(buffer_social_eligible(
            job, self.config, datetime(2026, 11, 20, 0, 0, tzinfo=JST)))

    def test_owner_waiting_does_not_block_next_supplemental_slot_after_regular_three(self):
        self.config['supplementalApparelEnabled'] = True
        test_runtime.RuntimeTests.configure_production_schedule(self)
        due = datetime(2026,11,16,9,tzinfo=JST)
        for index in range(2):
            job = self.runtime.ledger.create_candidate({'slug':f'closed-{index}'},
                                                        now='2026-11-13T09:00:00+09:00')
            self.runtime.ledger.set_stage(job['id'],'rejected')
        reviewed = self.runtime.ledger.create_candidate(
            {'slug':'waiting-owner','title':'Waiting'},now='2026-11-13T09:00:00+09:00')
        from wise_contract import load_policy
        policy = load_policy()
        current_bundle = __import__('test_quality').bundle(); current_bundle['wisePolicy']=policy['id']
        self.runtime.ledger.save_bundle(reviewed['id'],current_bundle)
        reviewed = self.runtime.ledger.get_job(reviewed['id'])
        self.runtime.ledger.record_review(reviewed['id'],reviewed['revision'],{
            'passed':True,'score':8.5,'model':'upper','issues':[],
            'wisePolicy':policy['id'],'wiseScores':dict(w=3,i=3,s=3,e=3,ai=3,sense=3),
            'fingerprint':reviewed['revision'],
            'evidence':{key:True for key in ('facts','images','affiliate','medical','render')},
            'polish':{'model':'gemini-3.8-flash','validated':True}})
        self.runtime.deliver(reviewed['id'])
        self.assertEqual([{'kind':'produce_supplemental','jobId':None}],
                         DeterministicDispatcher(self.runtime).plan(due)['actions'])


if __name__ == '__main__':
    unittest.main()
