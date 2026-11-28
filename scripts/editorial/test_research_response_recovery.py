"""Bounded recurring recovery for one fully received all-invalid research response."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ledger import JST, fingerprint
from models import Models, ModelOutcomeUnknown
import research_response_recovery as recovery
from runtime import Runtime, atomic
from test_models import ENV, Fake, response
from test_research_contract_recovery import matched_selection_fixture
from test_runtime import CatalogFake, SlackFake


class ResearchResponseRecoveryTests(unittest.TestCase):
    PERIOD = '2026-11-27'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        env = base / 'env'
        env.write_text('AMAZON_PARTNER_TAG=camp78-22\n')
        self.config = {'stateRoot': str(base / 'state'),
            'repo': str(Path(__file__).resolve().parents[2]), 'envFile': str(env),
            'spoolDir': str(base / 'spool'),
            'slack': dict(team_id='T', app_id='A', user_id='owner', channel_id='C', thread_ts='1.1'),
            'generationEnabled': True, 'publicationEnabled': False,
            'researchResponseRecoveryEnabled': True,
            'productionSchedule': dict(weekday=4, hour=9, effectiveFrom='2026-11-13',
                initialProductionAt='2026-11-08T00:00:00+09:00')}
        Path(self.config['spoolDir']).mkdir()
        self.config_path = base / 'config.json'
        atomic(self.config_path, self.config)
        self.proposals, self.feed, self.context = matched_selection_fixture()
        self.bad = [dict(self.proposals[0], proposedAction='new',
                         overlapArticleIds=['unknown-article']),
                    dict(self.proposals[1], selectionReason='a' * 501),
                    dict(self.proposals[2], overlapRationale='b' * 501)]
        self.invalid = response({'proposals': self.bad})
        self.invalid['id'] = 'fixture-invalid-response'
        self.valid = response({'proposals': self.proposals})
        self.valid['id'] = 'fixture-repaired-response'
        self.request = Fake(self.invalid, self.valid)
        self.rt = self.runtime(self.request)
        class Frozen27(datetime):
            @classmethod
            def now(cls, tz=None):
                value = cls(2026, 11, 27, 10, tzinfo=JST)
                return value if tz is None else value.astimezone(tz)
        self.now = Frozen27.now(JST)
        for target, value in [('runtime.datetime', Frozen27), ('model_budget.datetime', Frozen27),
                              ('research_response_recovery.datetime', Frozen27)]:
            item = patch(target, value)
            item.start()
            self.addCleanup(item.stop)

    def runtime(self, request):
        models = Models(ENV, request)
        rt = Runtime(self.config, models=models, catalog=CatalogFake(), slack=SlackFake(),
                     publisher=lambda *_: self.fail('publication forbidden'))
        models.artifact_sink = lambda artifact: atomic(rt.root / 'model-artifacts' /
            (hashlib.sha256(artifact['responseId'].encode()).hexdigest() + '.json'), artifact)
        return rt

    def produce(self, rt=None):
        rt = rt or self.rt
        with patch('runtime.require_fresh_daily_metrics'), \
                patch('runtime.collect_primary_sources', return_value=self.feed), \
                patch.object(rt, '_research_context', return_value=self.context), \
                patch.object(rt, '_make_article', side_effect=lambda j, c: rt.ledger.set_stage(j['id'], 'review')):
            return rt.produce(limit=99)

    def marker(self):
        return self.rt.root / 'production-attempts' / (self.PERIOD + '.json')

    def receipt(self, rt=None):
        rt = rt or self.rt
        with rt.ledger._tx() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?',
                             (recovery.key(self.PERIOD),)).fetchone()
            return json.loads(row[0])

    def test_normal_first_failure_then_one_repair_survives_restart(self):
        first = self.produce()
        self.assertEqual({'status': 'blocked', 'reason': 'research_contract_repair_ready',
                          'articles': [], 'retryable': True}, first)
        self.assertEqual('retry_ready', json.loads(self.marker().read_text())['status'])
        archive = self.rt.root / 'research-response-recovery' / self.PERIOD
        archived = {name: (archive / name).read_bytes() for name in
                    ('first-marker.json', 'first-artifact.json', 'first-context.json')}

        restarted = self.runtime(self.request)
        self.rt = restarted
        result = self.produce(restarted)
        self.assertEqual(3, len(result['articles']))
        self.assertEqual(2, len(self.request.calls))
        self.assertEqual('completed', self.receipt(restarted)['status'])
        self.assertEqual(1, self.receipt(restarted)['repairsUsed'])
        self.assertEqual(3, len(restarted.ledger.list_jobs()))
        self.assertTrue(all(job['approval'] is None and job['publication'] is None
                            and job['social'] is None
                            for job in restarted.ledger.list_jobs()))
        self.assertEqual(archived, {name: (archive / name).read_bytes() for name in archived})
        self.produce(restarted)
        self.assertEqual(2, len(self.request.calls))
        prompt = self.request.calls[1][2]['messages'][0]['content']
        self.assertIn('repairFeedback', prompt)
        self.assertNotIn('unknown-article', prompt)
        self.assertNotIn('a' * 100, prompt)

    def test_second_invalid_response_is_terminal_across_restart(self):
        self.request.results[1] = response({'proposals': self.bad})
        self.request.results[1]['id'] = 'fixture-second-invalid-response'
        self.assertEqual('research_contract_repair_ready', self.produce()['reason'])
        self.rt = self.runtime(self.request)
        result = self.produce()
        self.assertEqual({'status': 'blocked', 'reason': 'research_contract_repair_exhausted',
                          'articles': [], 'retryable': False}, result)
        self.assertEqual('held', self.receipt()['status'])
        self.rt = self.runtime(self.request)
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            self.produce()
        self.assertEqual(2, len(self.request.calls))

    def test_unknown_transport_never_arms_or_retries(self):
        request = Fake(ModelOutcomeUnknown('fixture unknown'))
        self.rt = self.runtime(request)
        with self.assertRaises(ModelOutcomeUnknown):
            self.produce()
        self.assertEqual('in_flight', json.loads(self.marker().read_text())['status'])
        self.rt = self.runtime(request)
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            self.produce()
        self.assertEqual(1, len(request.calls))
        self.assertFalse((self.rt.root / 'research-response-recovery' / self.PERIOD).exists())

    def test_readonly_prepare_and_owner_arm_pin_exact_existing_evidence(self):
        self.assertEqual('research_contract_repair_ready', self.produce()['reason'])
        receipt = self.receipt()
        archive = self.rt.root / 'research-response-recovery' / self.PERIOD
        marker = archive / 'first-marker.json'
        artifact = archive / 'first-artifact.json'
        context = archive / 'first-context.json'
        # Remove only the automatically armed recovery record to model the existing 11/27 hold.
        with self.rt.ledger._tx() as db:
            db.execute('DELETE FROM meta WHERE key=?', (recovery.key(self.PERIOD),))
        self.marker().write_bytes(marker.read_bytes())
        for path in archive.iterdir():
            path.unlink()
        archive.rmdir()
        hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
                  [('marker', self.marker()),
                   ('artifact', self.rt.root / 'model-artifacts' /
                    (hashlib.sha256(self.invalid['id'].encode()).hexdigest() + '.json')),
                   ('context', self.rt.root / 'research-contexts' / (self.PERIOD + '.json'))]}
        before = {p: p.read_bytes() for p in self.rt.root.rglob('*') if p.is_file()}
        plan = recovery.prepare(self.config_path, period=self.PERIOD,
            response_id=self.invalid['id'], config_sha256=hashlib.sha256(self.config_path.read_bytes()).hexdigest(),
            marker_sha256=hashes['marker'], artifact_sha256=hashes['artifact'],
            context_sha256=hashes['context'], owner_reference='owner-20261128-recurring-research-repair', now=self.now)
        self.assertEqual(before, {p: p.read_bytes() for p in self.rt.root.rglob('*') if p.is_file()})
        grant = recovery.owner_grant(plan)
        original_marker = self.marker().read_bytes()
        atomic(self.marker(), {**json.loads(original_marker), 'drift': True})
        with self.assertRaisesRegex(ValueError, 'input_drift'):
            recovery.arm(self.config_path, plan, owner_grant=grant, now=self.now)
        self.assertFalse(archive.exists())
        self.marker().write_bytes(original_marker)
        self.assertEqual({'status': 'retry_ready', 'armed': True, 'period': self.PERIOD},
                         recovery.arm(self.config_path, plan, owner_grant=grant, now=self.now))
        self.assertEqual(hashes, {name: plan['firstFailure'][name + 'Sha256'] for name in hashes})
        self.assertEqual(receipt['feedback'], self.receipt()['feedback'])

    def test_archived_input_drift_fails_closed_without_another_call(self):
        self.assertEqual('research_contract_repair_ready', self.produce()['reason'])
        self.rt = self.runtime(self.request)
        context_path = self.rt.root / 'research-response-recovery' / self.PERIOD / 'first-context.json'
        context_path.write_bytes(context_path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'input_drift'):
            self.produce()
        self.assertEqual(1, len(self.request.calls))

    def test_full_pending_queue_does_not_consume_or_call_repair(self):
        self.assertEqual('research_contract_repair_ready', self.produce()['reason'])
        for index in range(3):
            job = self.rt.ledger.create_candidate({'slug': 'carry-' + str(index)}, now=self.now)
            self.rt.ledger.set_stage(job['id'], 'review')
        self.assertEqual('idle', self.produce()['status'])
        self.assertEqual(0, self.receipt()['repairsUsed'])
        self.assertEqual(1, len(self.request.calls))

    def test_period_budget_cap_consumes_once_without_new_request(self):
        self.assertEqual('research_contract_repair_ready', self.produce()['reason'])
        for index in range(127):
            with self.rt.model_budget.scope('maintenance:fixture-' + str(index), 'fixture', now=self.now):
                reservation = self.rt.model_budget.reserve(
                    {'model': 'fixture', 'max_tokens': 1, 'messages': []})
                self.rt.model_budget.settle(reservation,
                    usage={'input_tokens': 0, 'output_tokens': 0}, response_id='fixture-' + str(index))
        result = self.produce()
        self.assertEqual('weekly_research_requires_reconciliation', result['reason'])
        self.assertFalse(result['retryable'])
        self.assertEqual(1, self.receipt()['repairsUsed'])
        self.assertEqual('held', self.receipt()['status'])
        self.assertEqual(1, len(self.request.calls))


if __name__ == '__main__':
    unittest.main()
