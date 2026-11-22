"""Finite replacement/hold and inherited budgets, offline and without public writes."""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from ledger import canonical
from model_budget import BudgetHold
from runtime import atomic
import supplemental_reselection as replacement
from supplemental_topics import load_batch
from test_supplemental_topics import product
import test_runtime


class ReselectionTests(unittest.TestCase):
    tearDown = test_runtime.RuntimeTests.tearDown

    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        clock = patch('supplemental_reselection.datetime', test_runtime.LegacyFixtureDateTime)
        clock.start(); self.addCleanup(clock.stop)
        self.config.update(executionPolicy={'mode': 'deterministic', 'suspended': False}, supplementalApparelEnabled=True)
        self.old_manifest = load_batch(Path(__file__).with_name('supplemental-winter-depth-20261122.json'))
        self.old_manifest['notBefore'] = '2026-11-22T09:00:00+09:00'
        self.old_path = self.runtime.root / 'old-manifest.json'
        atomic(self.old_path, self.old_manifest)
        self.config['supplementalApparelBatchManifest'] = str(self.old_path)
        slot = self.old_manifest['slots'][1]
        theme = {k: v for k, v in slot.items() if k != 'slot'}
        self.old = self.runtime.ledger.create_supplemental_candidate(theme, replacement.BATCH, 2, '0' * 64,
                       social_eligible_period=self.old_manifest['socialEligiblePeriod'])
        self.runtime._make_article(self.old, self.runtime._context())
        req = self.slack.deliveries[-1][1]
        with self.runtime.ledger._tx() as db:
            saved_req = json.loads(db.execute('SELECT data FROM requests WHERE id=?', (req['request_id'],)).fetchone()[0])
        event = dict(req['payload'], **self.scope, event_id='real-rejection', action_id='camp_review_reject',
                     card_ts=saved_req['card_ts'])
        self.old = self.runtime.ledger.decide(event, self.scope)
        pin = patch.object(replacement, 'SKIN', self.old['id'])
        pin.start(); self.addCleanup(pin.stop)
        self.hold = dict(kind='owner_requested_hold_and_reselection', articleId=self.old['id'],
                         revision=self.old['revision'], observedStage='rejected', ownerInstruction='肌着は保留、再選定',
                         ownerPublicationApproval=False, ownerSNSApproval=False)
        atomic(self.runtime.root / replacement.HOLD, self.hold)
        self.evidence = dict(source='codex', thread_id='owner-thread', message_id='new-instruction',
                             text='肌着を保留し、残り2枠と合わせMontbell中心の計3枠を再選定')
        self.new = copy.deepcopy(self.old_manifest)
        self.products = []
        for number, slot in enumerate(self.new['slots'], 1):
            p = product('montbell-new-' + str(number)); self.products.append(p)
            slot.update(productIds=[p['id']], slug='new-montbell-' + str(number),
                        title='Montbell topic ' + str(number), categoryId='wear',
                        query='new query ' + str(number), selectionReason='owner scoped verified selection')
        self.new_path = self.runtime.root / 'new-manifest.json'; atomic(self.new_path, self.new)
        self.context = self.runtime._context(); self.context.update(products=self.products, articles=[])
        self.runtime._context = Mock(side_effect=lambda: copy.deepcopy(self.context))
        self.original = self.history()
        self.writes.clear(); self.slack.deliveries.clear()

    def history(self):
        with self.runtime.ledger._tx() as db:
            return {table: db.execute(query, (self.old['id'],)).fetchall() for table, query in (
                ('job', 'SELECT data FROM jobs WHERE id=?'),
                ('requests', 'SELECT id,kind,data FROM requests WHERE job_id=?'),
                ('usage', 'SELECT * FROM model_budget_reservations WHERE article_id=?'),
                ('decisions', "SELECT id,data FROM decisions WHERE data LIKE '%'||?||'%'"))}

    def prepare(self):
        return replacement.prepare(self.runtime, self.new_path, 'U', self.evidence)

    def apply(self):
        return replacement.apply(self.runtime, self.prepare())

    def reserve(self, id, count=1):
        for _ in range(count):
            with self.runtime.model_budget.scope(id, 'draft', now=test_runtime.LegacyFixtureDateTime.now(replacement.JST)):
                rid = self.runtime.model_budget.reserve({'model': 'offline', 'max_tokens': 1, 'messages': []})
                self.runtime.model_budget.settle(rid, usage={'input_tokens': 0, 'output_tokens': 0})

    def test_prepare_is_readonly_apply_preserves_old_and_connects_normal_producer(self):
        plan = self.prepare()
        self.assertEqual(self.original, self.history())
        result = replacement.apply(self.runtime, plan)
        new = self.runtime.ledger.get_job(result['newJobId'])
        self.assertNotEqual(self.old['id'], new['id'])
        self.assertEqual((replacement.BATCH, 2, 96), (new['batchId'], new['batchSlot'], new['batchCallCap']))
        self.assertEqual(self.old['id'], self.runtime._budget_article_id(new['id']))
        self.assertEqual(self.new, self.runtime._supplemental_manifest())
        self.assertEqual(self.original, self.history())
        self.assertEqual([], self.writes); self.assertEqual([], self.slack.deliveries)
        self.runtime._make_article = Mock()
        self.runtime.produce_supplemental(job_id=new['id'])
        self.runtime._make_article.assert_called_once()
        self.assertEqual(new['id'], self.runtime._make_article.call_args.args[0]['id'])
        with self.assertRaises(ValueError): replacement.apply(self.runtime, plan)

    def fill_remaining_slots(self):
        from supplemental_topics import resolve_batch
        manifest = self.runtime._supplemental_manifest()
        resolved = resolve_batch(manifest, self.context, [], test_runtime.LegacyFixtureDateTime.now(replacement.JST))
        for slot in (resolved['slots'][0], resolved['slots'][2]):
            self.runtime.ledger.create_supplemental_candidate(slot['theme'], replacement.BATCH, slot['slot'],
                slot['sourceBinding'], social_eligible_period=manifest['socialEligiblePeriod'])

    def test_exact_three_current_slots_four_history_rows_and_no_general_rejected_exemption(self):
        result = self.apply(); self.fill_remaining_slots()
        self.assertEqual(4, len(self.runtime.ledger.list_jobs()))
        self.assertEqual(3, len(self.runtime.ledger.active_supplemental_jobs(replacement.BATCH)))
        with self.assertRaises(ValueError): self.runtime.ledger.create_candidate({'slug': 'fourth-pending'})
        with self.runtime.ledger._tx() as db:
            other = copy.deepcopy(self.old); other['id'] = 'unrelated-rejected'; other['batchSlot'] = 1
            db.execute('INSERT INTO jobs VALUES (?,?)', (other['id'], canonical(other)))
        with self.assertRaises(ValueError): self.runtime.ledger.active_supplemental_jobs(replacement.BATCH)
        with self.assertRaises(ValueError): self.reserve(self.old['id'])

    def test_old_article32_consumption_is_inherited(self):
        self.reserve(self.old['id'], 30)
        result = self.apply(); new = self.runtime.ledger.get_job(result['newJobId'])
        self.reserve(self.runtime._budget_article_id(new['id']), 2)
        with self.assertRaises(BudgetHold) as caught: self.reserve(self.runtime._budget_article_id(new['id']))
        self.assertEqual('article_calls_cap', caught.exception.reason_code)

    def test_batch96_counts_old_and_all_current_slots_without_double_count(self):
        self.reserve(self.old['id'], 32)
        result = self.apply(); self.fill_remaining_slots()
        for job in self.runtime.ledger.active_supplemental_jobs(replacement.BATCH):
            if job['id'] != result['newJobId']: self.reserve(self.runtime._budget_article_id(job['id']), 32)
        with self.assertRaises(BudgetHold) as caught: self.reserve(self.old['id'])
        self.assertEqual('batch_calls_cap', caught.exception.reason_code)
        self.assertEqual(96, self.runtime._supplemental_health(test_runtime.LegacyFixtureDateTime.now(replacement.JST))['modelCallsUsed'])

    def test_hold_blocks_old_approval_delivery_production_and_social_without_overwrites(self):
        for operation in (lambda: self.runtime.deliver(self.old['id']),
                          lambda: self.runtime._make_article(self.old, self.context),
                          lambda: self.runtime.make_social(self.old),
                          lambda: self.runtime.publish_social(self.old),
                          lambda: self.runtime.publish_buffer_social(self.old),
                          lambda: self.runtime.prepare_social_handoff(self.old),
                          lambda: self.runtime.ledger.set_stage(self.old['id'], 'candidate'),
                          lambda: self.runtime.ledger.claim_effect(self.old['id'], 'publish'),
                          lambda: self.runtime.ledger.approve_from_codex(self.old['id'], self.old['revision'], 'U',
                              dict(self.evidence, text=f"publish {self.old['id']} {self.old['revision']}"))):
            with self.assertRaisesRegex(ValueError, 'owner_hold'): operation()
        self.assertEqual(self.original, self.history()); self.assertEqual([], self.writes)

    def test_stale_manifest_hold_job_or_plan_cannot_apply(self):
        plan = self.prepare()
        changed = copy.deepcopy(self.new); changed['notBefore'] = '2026-11-23T09:00:00+09:00'
        atomic(self.new_path, changed)
        with self.assertRaises(ValueError): replacement.apply(self.runtime, plan)
        atomic(self.new_path, self.new)
        bad = dict(plan, budgetArticleId='fresh-budget')
        with self.assertRaises(ValueError): replacement.apply(self.runtime, bad)
        atomic(self.runtime.root / replacement.HOLD, dict(self.hold, revision='0' * 64))
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(self.original, self.history())

    def test_unknown_effect_and_reserved_usage_do_not_apply(self):
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (self.old['id'], 'publish', 'unknown', '{}'))
        with self.assertRaises(ValueError): self.prepare()
        with self.runtime.ledger._tx() as db: db.execute('DELETE FROM effects')
        with self.runtime.model_budget.scope(self.old['id'], 'draft'):
            self.runtime.model_budget.reserve({'model': 'offline', 'max_tokens': 1, 'messages': []})
        with self.assertRaises(ValueError): self.prepare()

    def test_known_unrelated_manager_is_retained_related_and_unknown_hold(self):
        from test_revision_workflow import baseline, spec
        other = self.runtime.ledger.request_revision(spec(baseline()))
        raw = json.dumps({'status': 'requires_reconciliation', 'action': {'job_id': other['id']}, 'old': 'keep'}, indent=2)
        with self.runtime.ledger._tx() as db: db.execute('INSERT INTO meta VALUES (?,?)', ('editorial_manager:old', raw))
        self.apply()
        with self.runtime.ledger._tx() as db:
            self.assertEqual(raw, db.execute('SELECT value FROM meta WHERE key=?', ('editorial_manager:old',)).fetchone()[0])
        for record in ({'status': 'executing', 'action': {'job_id': other['id']}},
                       {'status': 'evaluating'}, {'status': 'requires_reconciliation'},
                       {'status': 'requires_reconciliation', 'action': {'job_id': self.old['id']}},
                       {'status': 'requires_reconciliation', 'action': {'job_id': 'new-montbell-2'}},
                       {'status': 'requires_reconciliation', 'action': {'job_id': 'missing'}}):
            with self.assertRaisesRegex(ValueError, 'manager'):
                with self.runtime.ledger._tx() as db:
                    db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(record), 'editorial_manager:old'))
                    replacement._snapshots(db, self.old['id'], self.new)

    def test_only_replacement_source_ready_is_required_but_all_topics_must_be_chosen(self):
        self.context['products'] = [self.products[1]]
        value = self.apply()
        self.assertEqual(value['newJobId'], self.runtime.ledger.active_supplemental_jobs(replacement.BATCH)[0]['id'])

    def test_unselected_or_unready_replacement_cannot_be_prepared(self):
        manifest = copy.deepcopy(self.new); manifest['slots'][0]['title'] = None
        atomic(self.new_path, manifest)
        with self.assertRaises(ValueError): self.prepare()
        atomic(self.new_path, self.new)
        self.context['products'] = [self.products[0], self.products[2]]
        with self.assertRaises(ValueError): self.prepare()

    def test_period128_preserved_across_replacement(self):
        self.reserve(self.old['id'], 3)
        self.apply()
        for index, count in enumerate((32, 32, 32, 29)):
            self.reserve('other-article-' + str(index), count)
        with self.assertRaises(BudgetHold) as caught: self.reserve(self.old['id'])
        self.assertEqual('period_calls_cap', caught.exception.reason_code)

    def test_shared_alias_reports_actual_new_calls_separately_and_no_double_cost(self):
        from usage_cost_report import usage_cost_report, usage_cost_summary
        self.reserve(self.old['id'], 5)
        value = self.apply(); new_id = value['newJobId']
        self.reserve(self.runtime._budget_article_id(new_id), 2)
        calls = [dict(responseId='old-paid', articleId=self.old['id'], actualModel='fixture', stage='draft',
                      usage={'input_tokens': 500, 'output_tokens': 50}, actualUSD=0.5),
                 dict(responseId='new-paid', articleId=new_id, actualModel='fixture', stage='draft',
                      usage={'input_tokens': 100, 'output_tokens': 10}, actualUSD=0.1)]
        now = test_runtime.LegacyFixtureDateTime.now(replacement.JST)
        atomic(self.runtime.root / 'usage/reselection-fixture.json', {'at': now.isoformat(), 'calls': calls})
        kwargs = dict(kind='production', now=now, article_ids=[new_id], batch_call_cap=96)
        result = usage_cost_report(self.runtime.root, self.config, **kwargs)
        self.assertEqual(1, result['totals']['calls'])
        self.assertEqual(0.1, result['costs']['actualUSD']['value'])
        self.assertEqual({new_id: self.old['id']}, result['budgetAliases'])
        self.assertEqual(7, result['batchBudget']['used'])
        shared = result['budget']['sharedArticleBudgets'][new_id]
        self.assertEqual(25, shared['totals']['remaining']['calls'])
        self.assertIn('Montbell topic 2', shared['articleLabel'])
        self.assertEqual(1, len(result['budget']['articles']))
        text = usage_cost_summary(self.runtime.root, self.config, **kwargs)
        self.assertIn('旧保留記事分を含む共有枠', text)
        both = usage_cost_report(self.runtime.root, self.config, **dict(kwargs, article_ids=[self.old['id'], new_id]))
        self.assertEqual(2, both['totals']['calls'])
        self.assertAlmostEqual(0.6, both['costs']['actualUSD']['value'])
        self.assertEqual(7, both['batchBudget']['used'])

    def test_pending_three_and_changed_receipt_do_not_open_extra_slots(self):
        for index in range(3): self.runtime.ledger.create_candidate({'slug': 'unrelated-pending-' + str(index)})
        plan = self.prepare()
        with self.assertRaises(ValueError): replacement.apply(self.runtime, plan)
        self.assertEqual(self.original, self.history())
        with self.runtime.ledger._tx() as db:
            self.assertIsNone(db.execute('SELECT value FROM meta WHERE key=?', (replacement.KEY,)).fetchone())

    def test_alias_tamper_or_unbound_fourth_history_is_not_a_budget_authority(self):
        from usage_cost_report import usage_cost_report
        value = self.apply(); new_id = value['newJobId']
        with self.runtime.ledger._tx() as db:
            job = self.runtime.ledger._get(db, new_id); job['budgetArticleId'] = 'fresh-budget'
            db.execute('UPDATE jobs SET data=? WHERE id=?', (canonical(job), new_id))
        with self.assertRaises(ValueError): self.runtime._budget_article_id(new_id)
        data = usage_cost_report(self.runtime.root, self.config, kind='production',
            now=test_runtime.LegacyFixtureDateTime.now(replacement.JST), article_ids=[new_id], batch_call_cap=96)
        self.assertEqual('requires_reconciliation', data['budget']['status'])
        self.assertEqual('requires_reconciliation', data['batchBudget']['status'])

    def test_manager_unknown_or_undefined_status_holds_known_terminal_only_passes(self):
        key = 'editorial_manager:status-repro'
        for status in ('unknown', 'in_flight', 'unrecognized', '', None, 0, [], {}):
            raw = json.dumps({'status': status, 'action': {'job_id': 'unrelated'}})
            with self.subTest(status=status):
                with self.runtime.ledger._tx() as db:
                    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, raw))
                with self.assertRaisesRegex(ValueError, 'manager'): self.prepare()
                with self.runtime.ledger._tx() as db:
                    self.assertEqual(raw, db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        for status in ('completed', 'blocked', 'stale', 'input_limit', 'budget_exhausted',
                       'provider_failed', 'invalid_decision'):
            with self.runtime.ledger._tx() as db:
                db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps({'status': status}), key))
            self.prepare()
        self.assertEqual(self.original, self.history())

    def test_unfiltered_weekly_monthly_use_current_topic_label_keep_actual_job_costs(self):
        from usage_cost_report import usage_cost_report, usage_cost_summary
        self.reserve(self.old['id'], 5)
        new_id = self.apply()['newJobId']
        calls = [dict(responseId='old-week-month', articleId=self.old['id'], actualModel='fixture', stage='draft',
                      usage={'input_tokens': 500, 'output_tokens': 50}, actualUSD=0.5),
                 dict(responseId='new-week-month', articleId=new_id, actualModel='fixture', stage='draft',
                      usage={'input_tokens': 100, 'output_tokens': 10}, actualUSD=0.1)]
        path = self.runtime.root / 'usage/week-month.json'
        atomic(path, {'at': '2026-11-22T10:00:00+09:00', 'calls': calls})
        original = path.read_bytes()
        for kind, now in (('weekly', datetime(2026, 11, 27, 12, tzinfo=replacement.JST)),
                          ('monthly', datetime(2026, 12, 1, 12, tzinfo=replacement.JST))):
            with self.subTest(kind=kind):
                data = usage_cost_report(self.runtime.root, self.config, kind=kind, now=now)
                self.assertIsNone(data['articleFilter'])
                self.assertEqual({new_id: self.old['id']}, data['budgetAliases'])
                self.assertEqual(2, data['totals']['calls'])
                self.assertAlmostEqual(0.6, data['costs']['actualUSD']['value'])
                shared = data['budget']['sharedArticleBudgets'][new_id]
                self.assertEqual(self.old['id'], shared['budgetArticleId'])
                self.assertEqual(32, shared['totals']['remaining']['calls'])  # Current period differs from cost window.
                self.assertEqual(1, len(data['budget']['articles']))
                self.assertIn('Montbell topic 2', data['budget']['articleLabels'][self.old['id']])
                text = usage_cost_summary(self.runtime.root, self.config, kind=kind, now=now)
                self.assertIn('Montbell topic 2', text)
                self.assertIn('旧保留記事分を含む共有', text)
                self.assertIn('元job ID帰属', text)
                self.assertIn('実API job ' + new_id, text)
                self.assertIn('共有予算ID ' + self.old['id'], text)
                self.assertNotIn('記事予算 ' + self.old['theme']['title'], text)
                only_new = usage_cost_report(self.runtime.root, self.config, kind=kind, now=now, article_ids=[new_id])
                self.assertEqual(1, only_new['totals']['calls'])
                self.assertEqual(0.1, only_new['costs']['actualUSD']['value'])
                self.assertEqual(original, path.read_bytes())


if __name__ == '__main__':
    unittest.main()
