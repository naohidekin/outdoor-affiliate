"""Offline known-response repair; real budget, schema and normal producer."""
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import research_contract_recovery as recovery
from ledger import JST, fingerprint
from models import Models, ModelOutcomeUnknown
from runtime import Runtime, atomic
from test_models import ENV, Fake, response
from test_runtime import CatalogFake, SlackFake
from test_topic_selection import proposal

NOW = datetime(2026, 11, 20, 10, tzinfo=JST)
class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 20, 10, tzinfo=JST)
        return value if tz is None else value.astimezone(tz)


class ResearchContractRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        env = base / 'env'
        env.write_text('AMAZON_PARTNER_TAG=camp78-22\n')
        self.config = {'stateRoot': str(base / 'state'), 'repo': str(Path(__file__).resolve().parents[2]),
            'envFile': str(env), 'spoolDir': str(base / 'spool'),
            'slack': dict(team_id='T', app_id='A', user_id='owner', channel_id='C', thread_ts='1.1'),
            'generationEnabled': True, 'publicationEnabled': False,
            'productionSchedule': dict(weekday=4, hour=9, effectiveFrom='2026-11-13',
                initialProductionAt='2026-11-08T00:00:00+09:00')}
        Path(self.config['spoolDir']).mkdir()
        self.path = base / 'config.json'
        atomic(self.path, self.config)
        topics = [('tent-dry', '雨撤収した幕を乾かすには？', ['汚れを落とす', '乾燥場所', '保管確認']),
                  ('layering', '重ね着の順番は？', ['肌着', '中間着', '上着']),
                  ('sleeping-bag-care', '寝袋を乾燥して保管するには？', ['汚れ確認', '乾燥', '保管'])]
        self.proposals = [proposal(slug, q, 90-i, outline=heads, sourceIds=['gsc:fixture', 'public:' + str(i)])
                          for i, (slug, q, heads) in enumerate(topics)]
        self.feed = {'status': 'verified', 'sources': [dict(id='public:' + str(i),
            scope=scope, receiptSha256=str(i) * 64) for i, scope in
            enumerate(('tent-care', 'layering-concept-only', 'camp-care'))], 'illustrations': []}
        self.context = {'catalog': [], 'categories': [{'id': 'camp-howto'}], 'existingArticles': [],
            'editorialSignals': [{'id': 'gsc:fixture', 'kind': 'gsc'},
                *[{'id': s['id'], 'kind': 'public_reference'} for s in self.feed['sources']]]}
        answer = response({'proposals': self.proposals})
        answer['id'] = 'repaired-research-response'
        self.request = Fake(answer)
        self.rt = Runtime(self.config, models=Models(ENV, self.request), catalog=CatalogFake(),
            slack=SlackFake(), publisher=lambda *_: self.fail('publication forbidden'))
        self.root = self.rt.root
        self.marker = self.root / 'production-attempts' / (recovery.PERIOD + '.json')
        atomic(self.marker, {'status': 'in_flight', 'at': NOW.replace(hour=9, minute=2).isoformat()})
        bad = [proposal('old-proposal-' + str(i), '以前の案です。', intent='free text intent') for i in range(6)]
        self.artifact = self.root / 'model-artifacts' / (hashlib.sha256(recovery.RESPONSE_ID.encode()).hexdigest() + '.json')
        atomic(self.artifact, {'responseId': recovery.RESPONSE_ID, 'model': 'claude-sonnet-4-6',
            'content': json.dumps({'proposals': bad}, ensure_ascii=False),
            'usage': {'input_tokens': 128983, 'output_tokens': 3807}})
        with self.rt.model_budget.scope('research:' + recovery.PERIOD, 'research', now=NOW):
            old = self.rt.model_budget.reserve({'model': 'claude-sonnet-4-6', 'max_tokens': 16384, 'messages': []})
            self.rt.model_budget.settle(old, usage={'input_tokens': 128983, 'output_tokens': 3807}, response_id=recovery.RESPONSE_ID)
        for target, value in [('research_contract_recovery.CONFIG_SHA', hashlib.sha256(self.path.read_bytes()).hexdigest()),
                              ('research_contract_recovery.ARTIFACT_SHA', hashlib.sha256(self.artifact.read_bytes()).hexdigest()),
                              ('research_contract_recovery.datetime', Frozen), ('runtime.datetime', Frozen), ('model_budget.datetime', Frozen)]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def prepare(self):
        return recovery.prepare(self.path, hashlib.sha256(self.marker.read_bytes()).hexdigest(),
                                hashlib.sha256(self.artifact.read_bytes()).hexdigest(), now=NOW)
    def arm(self):
        plan = self.prepare()
        grant = dict(reference=recovery.AUTHORIZATION, answer=recovery.OWNER_ANSWER, manifestSha256=fingerprint(plan))
        recovery.arm(self.path, plan, owner_grant=grant, now=NOW)
        return plan
    def produce(self):
        with patch('runtime.require_fresh_daily_metrics'), patch('runtime.collect_primary_sources', return_value=self.feed), \
                patch.object(self.rt, '_research_context', return_value=self.context), \
                patch.object(self.rt, '_make_article', side_effect=lambda j, c: self.rt.ledger.set_stage(j['id'], 'review')):
            return self.rt.produce(limit=99)
    def receipt(self):
        with self.rt.ledger._tx() as db:
            return json.loads(db.execute('SELECT value FROM meta WHERE key=?', (recovery.KEY,)).fetchone()[0])

    def test_readonly_prepare_returns_only_intent_field_failures_not_old_proposals(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        plan = self.prepare()
        self.assertEqual(['proposals.' + str(i) + '.intent' for i in range(6)], plan['firstFailure']['invalidFields'])
        self.assertNotIn('free text intent', json.dumps(plan))
        self.assertNotIn('old-proposal', json.dumps(plan))
        self.assertFalse(plan['firstFailure']['diagnosis']['onlyErrorProven'])
        self.assertEqual('unverified', plan['firstFailure']['diagnosis']['oldCategoryMembership'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_normal_producer_consumes_once_and_preserves_first_failure_budget_and_three_slots(self):
        original = self.marker.read_bytes()
        with self.rt.ledger._tx() as db:
            budget = tuple(db.execute('SELECT * FROM model_budget_reservations').fetchone())
        self.arm()
        self.assertEqual(3, len(self.produce()['articles']))
        self.assertEqual(1, len(self.request.calls))
        self.assertEqual(original, (self.root / 'research-contract-recovery' / recovery.PERIOD / 'first-marker.json').read_bytes())
        self.assertEqual('completed', self.receipt()['status'])
        self.assertEqual(1, self.receipt()['repairsUsed'])
        self.assertEqual(3, len(self.rt.ledger.list_jobs()))
        self.assertTrue(all(j['approval'] is None and j['publication'] is None for j in self.rt.ledger.list_jobs()))
        with self.rt.ledger._tx() as db:
            rows = db.execute('SELECT * FROM model_budget_reservations ORDER BY rowid').fetchall()
            self.assertEqual(budget, tuple(rows[0]))
            self.assertEqual(2, len(rows))
            self.assertTrue(all(row[3] == 'research:' + recovery.PERIOD for row in rows))
        self.produce()
        self.assertEqual(1, len(self.request.calls))
        self.assertIn('output_config', self.request.calls[0][2])

    def test_unknown_and_known_contract_failure_do_not_restore_right(self):
        self.arm()
        self.request.results[0] = ModelOutcomeUnknown('fixture unknown')
        with self.assertRaises(ModelOutcomeUnknown):
            self.produce()
        self.assertEqual('held', self.receipt()['status'])
        self.assertEqual(1, self.receipt()['repairsUsed'])
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            self.produce()
        self.assertEqual(1, len(self.request.calls))

    def test_other_defects_and_any_valid_intent_are_not_this_known_failure(self):
        original = self.artifact.read_bytes()
        for mutation in ('intent', 'priority', 'sourceIds', 'extra'):
            value = json.loads(original)
            raw = json.loads(value['content'])
            if mutation == 'intent':
                raw['proposals'][0]['intent'] = 'informational'
            elif mutation == 'priority':
                raw['proposals'][0]['priority'] = 999
            elif mutation == 'sourceIds':
                raw['proposals'][0]['sourceIds'] = []
            else:
                raw['proposals'][0]['unexpected'] = True
            value['content'] = json.dumps(raw)
            atomic(self.artifact, value)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.prepare()
        self.artifact.write_bytes(original)
        self.assertEqual([], self.request.calls)

    def test_wrong_hash_unknown_budget_selection_and_existing_jobs_rejected(self):
        plan = self.prepare()
        with self.assertRaises(ValueError):
            recovery.prepare(self.path, '0' * 64, plan['firstFailure']['artifactSha256'], now=NOW)
        with self.rt.ledger._tx() as db:
            db.execute("UPDATE model_budget_reservations SET status='unknown'")
        with self.assertRaisesRegex(ValueError, 'budget_response_binding'):
            self.prepare()
        with self.rt.ledger._tx() as db:
            db.execute("UPDATE model_budget_reservations SET status='settled'")
            db.execute('INSERT INTO meta VALUES (?,?)', ('regular_selection:v1:' + recovery.PERIOD, '{}'))
        with self.assertRaisesRegex(ValueError, 'no_selection'):
            self.prepare()
        with self.rt.ledger._tx() as db:
            db.execute('DELETE FROM meta WHERE key=?', ('regular_selection:v1:' + recovery.PERIOD,))
        self.rt.ledger.create_candidate({'slug': 'already-created'}, now=NOW)
        with self.assertRaisesRegex(ValueError, 'no_jobs'):
            self.prepare()

    def test_same_response_id_with_unknown_category_and_new_caller_sha_fails_fixed_pin(self):
        original = self.artifact.read_bytes()
        artifact = json.loads(original)
        content = json.loads(artifact['content'])
        content['proposals'][0]['categoryId'] = 'unknown-category-forged-after-response'
        artifact['content'] = json.dumps(content)
        atomic(self.artifact, artifact)
        with self.assertRaisesRegex(ValueError, 'exact_known_response'):
            self.prepare()  # Supplies the mutant's new SHA; the fixed native pin rejects it.
        self.assertEqual([], self.request.calls)
        self.assertEqual('in_flight', json.loads(self.marker.read_text())['status'])
        self.artifact.write_bytes(original)

    def test_forged_ready_marker_cannot_call_models(self):
        atomic(self.marker, {'status': 'retry_ready', 'period': recovery.PERIOD, 'recoveryKey': recovery.KEY})
        with self.assertRaisesRegex(ValueError, 'receipt_missing'):
            self.produce()
        self.assertEqual([], self.request.calls)

    def test_second_contract_failure_is_known_but_does_not_grant_another_repair(self):
        self.arm()
        value = response({'proposals': [dict(p, intent='still invalid') for p in self.proposals]})
        value['id'] = 'second-known-contract-response'
        self.request.results[0] = value
        with self.assertRaisesRegex(ValueError, 'proposal_contract'):
            self.produce()
        self.assertEqual('held', self.receipt()['status'])
        self.assertEqual([], self.rt.ledger.list_jobs())
        with self.rt.ledger._tx() as db:
            outcomes = db.execute('SELECT status,outcome FROM model_budget_reservations').fetchall()
        self.assertEqual([('settled', 'success'), ('settled', 'success')], outcomes)
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            self.produce()
        self.assertEqual(1, len(self.request.calls))

    def test_period_budget_cap_before_new_request_holds_without_refunding_right(self):
        self.arm()
        for i in range(127):
            with self.rt.model_budget.scope('maintenance:fixture-' + str(i), 'fixture'):
                key = self.rt.model_budget.reserve({'model': 'fixture', 'max_tokens': 1, 'messages': []})
                self.rt.model_budget.settle(key, usage={'input_tokens': 0, 'output_tokens': 0},
                                            response_id='fixture-' + str(i))
        result = self.produce()
        self.assertFalse(result['retryable'])
        self.assertEqual([], self.request.calls)
        self.assertEqual('held', self.receipt()['status'])
        self.assertEqual(1, self.receipt()['repairsUsed'])
        self.assertFalse(json.loads(self.marker.read_text())['requestMayHaveOccurred'])

    def test_two_carried_pending_jobs_allow_only_one_new_shared_slot(self):
        self.arm()
        for i in range(2):
            job = self.rt.ledger.create_candidate({'slug': 'carry-' + str(i)}, now=datetime(2026, 11, 13, 10, tzinfo=JST))
            self.rt.ledger.set_stage(job['id'], 'review')
        result = self.produce()
        self.assertEqual(1, len(result['articles']))
        self.assertEqual(1, len(self.request.calls))
        self.assertEqual(3, len(self.rt.ledger.list_jobs()))
        self.assertEqual('generated', json.loads(self.marker.read_text())['status'])
        self.assertEqual(3, len(json.loads(self.marker.read_text())['themes']))

    def test_full_pending_guard_does_not_spend_or_call_repair(self):
        self.arm()
        for i in range(3):
            job = self.rt.ledger.create_candidate({'slug': 'carry-' + str(i)}, now=datetime(2026, 11, 13, 10, tzinfo=JST))
            self.rt.ledger.set_stage(job['id'], 'review')
        self.assertEqual('idle', self.produce()['status'])
        self.assertEqual([], self.request.calls)
        self.assertEqual(0, self.receipt()['repairsUsed'])

    def test_duplicate_consume_and_wrong_owner_reference_are_rejected(self):
        plan = self.prepare()
        with self.assertRaisesRegex(ValueError, 'owner_instruction'):
            recovery.arm(self.path, plan, owner_grant={}, now=NOW)
        self.arm()
        marker = json.loads(self.marker.read_text())
        self.assertEqual(recovery.KEY, recovery.consume(self.rt, recovery.PERIOD, marker))
        with self.assertRaisesRegex(ValueError, 'already_consumed'):
            recovery.consume(self.rt, recovery.PERIOD, marker)
        self.assertEqual(1, self.receipt()['repairsUsed'])
        self.assertEqual([], self.request.calls)

if __name__ == '__main__':
    unittest.main()
