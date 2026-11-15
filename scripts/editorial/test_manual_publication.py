"""Offline contracts for the two fixed manual publication operations."""
import copy
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from ledger import FLAGS, JST, Ledger, canonical, fingerprint as ledger_fingerprint
from manual_publication import ManualPublication, TARGETS
from runtime import Runtime, atomic


FIRST, SECOND = tuple(TARGETS)
SCOPE = {'team_id': 'T', 'app_id': 'A', 'user_id': 'OWNER',
         'channel_id': 'C', 'thread_ts': '1794686700.000001'}


class LedgerFake:
    def __init__(self, jobs):
        self.jobs = {job['id']: copy.deepcopy(job) for job in jobs}
        self.owner_id = 'OWNER'
        self.decision_calls = []
        self.decision_rows = {}
        self.claims = []
        self.effects = []
        self.publications = []
        self.requests = {}
        self.claim_result = True

    class RequestDB:
        def __init__(self, requests, decisions):
            self.requests = requests
            self.decisions = decisions

        def execute(self, sql, params):
            if 'FROM decisions' in sql:
                decision = self.decisions.get(params[0])
                row = None if decision is None else (json.dumps(decision),)
                return SimpleNamespace(fetchone=lambda: row)
            request = self.requests.get(params[0])
            row = None if request is None else (
                request['job_id'], request['kind'], json.dumps(request['data']))
            return SimpleNamespace(fetchone=lambda: row)

    def _tx(self):
        return nullcontext(self.RequestDB(self.requests, self.decision_rows))

    def get_job(self, job_id):
        return copy.deepcopy(self.jobs[job_id])

    def decide(self, event, scope):
        self.decision_calls.append((copy.deepcopy(event), copy.deepcopy(scope)))
        job = self.jobs[event['article_id']]
        job['stage'] = 'approved'
        job['approval'] = {'action': 'approved', 'user_id': scope['user_id'],
                           'revision': event['manifest_hash'],
                           'request_id': event['request_id']}
        self.decision_rows[event['event_id']] = {
            'event': copy.deepcopy(event), 'result': copy.deepcopy(job)}
        return copy.deepcopy(job)

    def claim_effect(self, job_id, kind):
        self.claims.append((job_id, kind))
        return self.claim_result

    def record_publication(self, job_id, revision, result):
        self.publications.append((job_id, revision, copy.deepcopy(result)))

    def finish_effect(self, job_id, kind, result):
        self.effects.append((job_id, kind, copy.deepcopy(result)))


class AuditorFake:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def check(self, job):
        self.calls.append(copy.deepcopy(job))
        if isinstance(self.result, BaseException):
            raise self.result
        return copy.deepcopy(self.result)


class ManualPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        self.root.mkdir(mode=0o700)
        self.spool = Path(self.tmp.name) / 'spool'
        self.spool.mkdir(mode=0o700)
        self.lock = (self.root / 'runtime.flock').open('a')
        self.config = {
            'stateRoot': str(self.root), 'spoolDir': str(self.spool),
            'slack': copy.deepcopy(SCOPE), 'executionPolicy': {'suspended': True},
            'generationEnabled': False, 'publicationEnabled': False,
            'socialPostingEnabled': False, 'postPublicationAuditEnabled': False,
        }

    def tearDown(self):
        self.lock.close()
        self.tmp.cleanup()

    def job(self, job_id=FIRST, stage='approved', published=False):
        target = TARGETS[job_id]
        revision = target['revision']
        review = {'score': 8.5, 'passed': True, 'fingerprint': revision,
                  'evidence': {flag: True for flag in FLAGS},
                  'polish': {'model': 'gemini-3.8-flash', 'validated': True}}
        job = {
            'id': job_id, 'kind': 'article_revision', 'stage': stage,
            'revision': revision, 'bundle': {'exact': revision},
            'revisionContext': {'baseArticle': {'id': target['baseId']}},
            'approval': {'action': 'approved', 'user_id': 'OWNER', 'revision': revision},
            'review': review,
            'astraReview': {'passed': True, 'issues': [], 'reviewedBy': 'Astra',
                            'evidence': {'scope': 'exact'}, 'fingerprint': revision},
            'publication': None,
        }
        if published:
            job['stage'] = 'published'
            job['publication'] = {
                'verified': True, 'revision': revision,
                'url': 'https://camp-gear-lab.com/articles/test',
                'at': '2026-11-15T05:00:00+09:00',
                'readback': {'verified': True, 'fingerprint': revision},
            }
        return job

    def publication(self, jobs, auditor=None):
        runtime = SimpleNamespace(
            root=self.root, config=copy.deepcopy(self.config), env={},
            ledger=LedgerFake(jobs), post_auditor=auditor,
            _require_running=lambda: None)
        value = ManualPublication.__new__(ManualPublication)
        value._runtime = runtime
        value._runtime_lock = self.lock
        return value, runtime

    def hold_lock(self):
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def event(self, job_id):
        target = TARGETS[job_id]
        return {**SCOPE, 'article_id': job_id, 'manifest_hash': target['revision'],
                'message_ts': target['cardTs'], 'action_id': 'camp_review_approve',
                'request_id': 'request-' + job_id, 'nonce': 'secret',
                'event_id': 'event-' + job_id}

    def delivered_request(self, event, kind='article', status='delivered'):
        return {'job_id': event['article_id'], 'kind': kind, 'data': {
            'kind': kind, 'status': status, 'article_id': event['article_id'],
            'manifest_hash': event['manifest_hash'], 'card_ts': event['message_ts'],
            'scope': copy.deepcopy(SCOPE), 'nonce': event['nonce'],
        }}

    def bind_authority(self, runtime, job_id=FIRST):
        event = self.event(job_id)
        target = TARGETS[job_id]
        job = runtime.ledger.jobs[job_id]
        job['approval']['request_id'] = event['request_id']
        processed = self.spool / 'editorial-processed'
        processed.mkdir(mode=0o700, exist_ok=True)
        event_path = processed / (job_id + '.json')
        atomic(event_path, event)
        event_hash = hashlib.sha256(event_path.read_bytes()).hexdigest()
        runtime.ledger.requests[event['request_id']] = self.delivered_request(
            event, status='decided')
        decided_event = copy.deepcopy(event)
        decided_event['card_ts'] = event['message_ts']
        runtime.ledger.decision_rows[event['event_id']] = {
            'event': decided_event, 'result': copy.deepcopy(job)}
        atomic(self.root / 'manual-publication-authority' / (job_id + '.json'), {
            'schemaVersion': 1, 'jobId': job_id, 'revision': target['revision'],
            'cardTs': target['cardTs'], 'requestId': event['request_id'],
            'eventId': event['event_id'], 'eventHash': event_hash,
            'scope': copy.deepcopy(SCOPE),
        })

    def test_requires_caller_held_exact_root_flock(self):
        publication, _ = self.publication([self.job()])
        with self.assertRaisesRegex(ValueError, 'root_flock_required'):
            publication.accept_slack_approval(FIRST)

    def test_review_capabilities_are_explicitly_forbidden(self):
        publication, _ = self.publication([self.job()])
        for method in ('queue_revision', 'prepare_revision', 'complete_review', 'deliver_review'):
            with self.subTest(method=method), self.assertRaisesRegex(
                    ValueError, 'review_entrypoint_forbidden'):
                getattr(publication, method)('forbidden')

    def test_accepts_only_exact_spool_event_and_preserves_other_files(self):
        publication, runtime = self.publication([self.job(FIRST, stage='review'),
                                                 self.job(SECOND, stage='review')])
        files = {
            '005.json': self.event(FIRST),
            '024.json': self.event(SECOND),
            'social-a.json': {'kind': 'social', 'article_id': FIRST},
            'social-b.json': {'kind': 'social', 'article_id': SECOND},
        }
        for name, value in files.items():
            atomic(self.spool / name, value)
        runtime.ledger.requests[files['005.json']['request_id']] = self.delivered_request(
            files['005.json'])
        self.hold_lock()
        with patch('manual_publication.fingerprint', return_value=TARGETS[FIRST]['revision']):
            result = publication.accept_slack_approval(FIRST)
        self.assertEqual('approved', result['status'])
        self.assertEqual(1, len(runtime.ledger.decision_calls))
        decided = runtime.ledger.decision_calls[0][0]
        self.assertEqual(TARGETS[FIRST]['cardTs'], decided['card_ts'])
        self.assertFalse((self.spool / '005.json').exists())
        self.assertTrue((self.spool / 'editorial-processed' / '005.json').exists())
        self.assertEqual({'024.json', 'social-a.json', 'social-b.json'},
                         {path.name for path in self.spool.glob('*.json')})

    def test_approved_replay_accepts_decided_request_only_to_finish_spool_move(self):
        publication, runtime = self.publication([self.job(FIRST, stage='approved')])
        event = self.event(FIRST)
        atomic(self.spool / 'replay.json', event)
        runtime.ledger.requests[event['request_id']] = self.delivered_request(
            event, status='decided')
        self.hold_lock()
        with patch('manual_publication.fingerprint', return_value=TARGETS[FIRST]['revision']):
            result = publication.accept_slack_approval(FIRST)
        self.assertEqual('approved', result['status'])
        self.assertTrue((self.spool / 'editorial-processed' / 'replay.json').exists())

    def test_approval_rejects_published_state_or_non_article_request_before_decide(self):
        for state, kind in (('published', 'article'), ('review', 'social')):
            job = self.job(FIRST, stage=state, published=state == 'published')
            publication, runtime = self.publication([job])
            event = self.event(FIRST)
            atomic(self.spool / (state + '.json'), event)
            runtime.ledger.requests[event['request_id']] = self.delivered_request(event, kind)
            self.hold_lock()
            with self.subTest(state=state, kind=kind), \
                    patch('manual_publication.fingerprint',
                          return_value=TARGETS[FIRST]['revision']), \
                    self.assertRaises(ValueError):
                publication.accept_slack_approval(FIRST)
            self.assertEqual([], runtime.ledger.decision_calls)
            for path in self.spool.glob('*.json'):
                path.unlink()

    def test_publish_uses_runtime_pipeline_and_exact_effect_lifecycle(self):
        publication, runtime = self.publication([self.job()])
        self.bind_authority(runtime)
        self.hold_lock()
        original_config = copy.deepcopy(runtime.config)
        result = {'verified': True, 'revision': TARGETS[FIRST]['revision'],
                  'url': 'https://camp-gear-lab.com/articles/single-burner-ranking',
                  'readback': {'verified': True, 'fingerprint': TARGETS[FIRST]['revision']}}
        with patch('manual_publication.fingerprint', return_value=TARGETS[FIRST]['revision']), \
                patch.object(Runtime, '_publish', autospec=True, return_value=result) as publish:
            saved = publication.publish_revision(FIRST)
        self.assertEqual('published', saved['status'])
        publish.assert_called_once()
        self.assertEqual('publish-revision', publish.call_args.args[1])
        self.assertEqual([(FIRST, 'publish')], runtime.ledger.claims)
        self.assertEqual('success', runtime.ledger.effects[0][2]['status'])
        self.assertEqual(original_config, runtime.config)

    def test_unknown_publication_is_preserved_and_never_retried(self):
        publication, runtime = self.publication([self.job()])
        self.bind_authority(runtime)
        self.hold_lock()
        error = ValueError('unknown')
        error.diagnostic = {'phase': 'article_readback'}
        with patch('manual_publication.fingerprint', return_value=TARGETS[FIRST]['revision']), \
                patch.object(Runtime, '_publish', autospec=True, side_effect=error) as publish:
            with self.assertRaises(ValueError):
                publication.publish_revision(FIRST)
            runtime.ledger.claim_result = False
            with self.assertRaisesRegex(ValueError, 'effect_requires_reconciliation'):
                publication.publish_revision(FIRST)
        self.assertEqual(1, publish.call_count)
        self.assertEqual('unknown', runtime.ledger.effects[0][2]['status'])

    def test_single_target_audit_saves_standard_receipt_and_respects_due_time(self):
        auditor = AuditorFake({'passed': False, 'status': 'unverified',
                               'checks': [{'name': 'public', 'status': 'unverified',
                                           'reason': 'public_get_unavailable'}]})
        publication, runtime = self.publication([self.job(published=True)], auditor)
        self.hold_lock()
        key = lambda value: (TARGETS[FIRST]['revision']
                             if isinstance(value, dict) and 'exact' in value else 'a' * 64)
        with patch('manual_publication.fingerprint', side_effect=key):
            first = publication.audit_revision(FIRST)
            second = publication.audit_revision(FIRST)
        self.assertEqual('unverified', first['status'])
        self.assertEqual(1, first['attempts'])
        self.assertEqual(1, len(auditor.calls))
        self.assertEqual(first['receipt'], second['receipt'])
        receipt = json.loads(Path(first['receipt']).read_text())
        self.assertEqual((datetime.now(JST) + timedelta(minutes=30)).date(),
                         datetime.fromisoformat(receipt['nextAttemptAt']).date())
        self.assertFalse(runtime.config['postPublicationAuditEnabled'])

    def test_audit_retries_only_when_due_and_stops_after_three(self):
        auditor = AuditorFake({'passed': False, 'status': 'failed', 'checks': []})
        publication, _ = self.publication([self.job(published=True)], auditor)
        self.hold_lock()
        key = lambda value: (TARGETS[FIRST]['revision']
                             if isinstance(value, dict) and 'exact' in value else 'b' * 64)
        with patch('manual_publication.fingerprint', side_effect=key):
            result = publication.audit_revision(FIRST)
            for expected in (2, 3):
                receipt = Path(result['receipt'])
                saved = json.loads(receipt.read_text())
                saved['nextAttemptAt'] = (datetime.now(JST) - timedelta(seconds=1)).isoformat()
                atomic(receipt, saved)
                result = publication.audit_revision(FIRST)
                self.assertEqual(expected, result['attempts'])
            publication.audit_revision(FIRST)
        self.assertEqual(3, len(auditor.calls))
        self.assertIsNone(result['nextAttemptAt'])

    def test_audit_rejects_illegal_or_corrupt_history_without_retry(self):
        mutations = {
            'illegal_status': lambda value: value.update(status='surprise'),
            'pending_nonempty': lambda value: value.update(status='pending'),
            'pending_three': lambda value: value.update(
                status='pending', attempts=value['attempts'] * 3),
            'malformed_attempt': lambda value: value.update(
                status='unverified', attempts=[{'status': 'unverified'}]),
        }
        self.hold_lock()
        for index, (name, mutate) in enumerate(mutations.items()):
            auditor = AuditorFake({'passed': False, 'status': 'unverified', 'checks': []})
            publication, _ = self.publication([self.job(published=True)], auditor)
            audit_key = format(index + 12, '064x')
            key = lambda value, audit_key=audit_key: (
                TARGETS[FIRST]['revision']
                if isinstance(value, dict) and 'exact' in value else audit_key)
            with patch('manual_publication.fingerprint', side_effect=key):
                first = publication.audit_revision(FIRST)
                receipt = Path(first['receipt'])
                saved = json.loads(receipt.read_text())
                mutate(saved)
                atomic(receipt, saved)
                with self.subTest(case=name), self.assertRaisesRegex(
                        ValueError, 'audit_reconciliation_required'):
                    publication.audit_revision(FIRST)
            self.assertEqual(1, len(auditor.calls))


class RealLedgerManualPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        self.root.mkdir(mode=0o700)
        self.spool = Path(self.tmp.name) / 'spool'
        self.spool.mkdir(mode=0o700)
        self.lock = (self.root / 'runtime.flock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.ledger = Ledger(self.root, 'OWNER')
        self.config = {'spoolDir': str(self.spool),
                       'slack': {**copy.deepcopy(SCOPE), 'bot_user_id': 'BOT'},
                       'publicationEnabled': False, 'socialPostingEnabled': False,
                       'postPublicationAuditEnabled': False}
        runtime = SimpleNamespace(root=self.root, config=self.config, env={},
                                  ledger=self.ledger, post_auditor=None,
                                  _require_running=lambda: None)
        self.publication = ManualPublication.__new__(ManualPublication)
        self.publication._runtime = runtime
        self.publication._runtime_lock = self.lock

    def tearDown(self):
        self.lock.close()
        self.tmp.cleanup()

    @contextmanager
    def integrity(self):
        exact = lambda value: (value['exact'] if isinstance(value, dict) and 'exact' in value
                               else ledger_fingerprint(value))
        with patch('manual_publication.fingerprint', side_effect=exact), \
                patch('ledger.fingerprint', side_effect=exact), \
                patch('revisions.validate_revision_bundle', return_value=None):
            yield

    def seed(self, job_id):
        target = TARGETS[job_id]
        revision = target['revision']
        request_id = 'request-' + job_id
        job = {
            'id': job_id, 'kind': 'article_revision', 'stage': 'review',
            'revision': revision, 'bundle': {'exact': revision},
            'revisionContext': {'baseArticle': {'id': target['baseId']}},
            'theme': {'slug': target['baseId']}, 'approval': None, 'publication': None,
            'social': None, 'error': None,
            'review': {'score': 8.5, 'passed': True, 'fingerprint': revision,
                       'evidence': {flag: True for flag in FLAGS},
                       'polish': {'model': 'gemini-3.8-flash', 'validated': True}},
            'astraReview': {'passed': True, 'issues': [], 'reviewedBy': 'Astra',
                            'evidence': {'exact': True}, 'fingerprint': revision},
        }
        payload = {'request_id': request_id, 'article_id': job_id,
                   'manifest_hash': revision, 'nonce': 'nonce-' + job_id}
        request = {**payload, 'kind': 'article', 'payload': payload,
                   'status': 'delivered',
                   'expires_at': (datetime.now(JST) + timedelta(hours=1)).isoformat(),
                   'scope': copy.deepcopy(SCOPE), 'card_ts': target['cardTs'],
                   'parts': {'scope': copy.deepcopy(SCOPE)}}
        with self.ledger._tx() as db:
            self.ledger._put(db, job, 'test_seed')
            db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                       (request_id, job_id, 'article', canonical(request)))
        event = {**payload, **SCOPE, 'event_id': 'event-' + job_id,
                 'action_id': 'camp_review_approve', 'message_ts': target['cardTs']}
        path = self.spool / (job_id + '.json')
        atomic(path, event)
        return path, event

    def test_real_ledger_rejects_wrong_nonce_and_wrong_card(self):
        first_path, first = self.seed(FIRST)
        first['nonce'] = 'wrong'
        atomic(first_path, first)
        second_path, second = self.seed(SECOND)
        second['message_ts'] = '1794686800.000000'
        atomic(second_path, second)
        with self.integrity():
            with self.assertRaises(ValueError):
                self.publication.accept_slack_approval(FIRST)
            with self.assertRaises(ValueError):
                self.publication.accept_slack_approval(SECOND)
        self.assertTrue(first_path.exists())
        self.assertTrue(second_path.exists())
        self.assertFalse((self.root / 'manual-publication-authority' / (FIRST + '.json')).exists())

    def test_real_ledger_replays_archive_crash_and_rejects_event_collision(self):
        first_path, _ = self.seed(FIRST)
        with self.integrity(), patch.object(Path, 'rename', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                self.publication.accept_slack_approval(FIRST)
        self.assertEqual('approved', self.ledger.get_job(FIRST)['stage'])
        self.assertTrue(first_path.exists())
        with self.integrity():
            self.publication.accept_slack_approval(FIRST)
        self.assertTrue((self.spool / 'editorial-processed' / first_path.name).exists())

        second_path, second = self.seed(SECOND)
        with self.integrity(), patch.object(Path, 'rename', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                self.publication.accept_slack_approval(SECOND)
        second['nonce'] = 'collision'
        atomic(second_path, second)
        with self.integrity(), self.assertRaisesRegex(ValueError, 'event id collision'):
            self.publication.accept_slack_approval(SECOND)
        self.assertTrue(second_path.exists())

    def test_real_ledger_two_jobs_partial_unknown_never_duplicates_publish(self):
        for job_id in (FIRST, SECOND):
            self.seed(job_id)
        with self.integrity():
            for job_id in (FIRST, SECOND):
                self.publication.accept_slack_approval(job_id)
            first_result = {'verified': True,
                            'url': 'https://camp-gear-lab.com/articles/single-burner-ranking',
                            'readback': {'verified': True,
                                         'fingerprint': TARGETS[FIRST]['revision']}}
            unknown = ValueError('publication_result_unknown')
            unknown.diagnostic = {'phase': 'article_readback'}
            with patch.object(Runtime, '_publish', autospec=True,
                              side_effect=[first_result, unknown]) as publisher:
                self.publication.publish_revision(FIRST)
                with self.assertRaises(ValueError):
                    self.publication.publish_revision(SECOND)
                with self.assertRaisesRegex(ValueError, 'effect_requires_reconciliation'):
                    self.publication.publish_revision(SECOND)
            self.assertEqual(2, publisher.call_count)
        self.assertEqual('published', self.ledger.get_job(FIRST)['stage'])
        self.assertEqual('approved', self.ledger.get_job(SECOND)['stage'])
        with self.ledger._tx() as db:
            effects = dict(db.execute('SELECT job_id,status FROM effects').fetchall())
        self.assertEqual('success', effects[FIRST])
        self.assertEqual('unknown', effects[SECOND])


if __name__ == '__main__':
    unittest.main()
