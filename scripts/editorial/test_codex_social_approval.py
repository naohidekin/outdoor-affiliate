"""Offline trusted-operator approval contracts; no provider, Slack, or X calls."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from ledger import Ledger, fingerprint
from test_social_publisher import approved_job

SOTO_ID = 'article-42db462e1ce17ce82afb36ed'
SOTO_REVISION = '732c338b9c0cab5b9b5eaa6e591e26555f67b1b1846f6fd3918c5f21ef5fb24c'
SOTO_TEXT = 'SOTOのX投稿はもう行ってください。これはもう気にせずに。'
SCOPE = dict(team_id='T', app_id='A', user_id='owner', channel_id='C', thread_ts='1.0')


class CodexSocialApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'private'
        self.ledger = Ledger(self.root, 'owner', target_account_id='123')
        self.job = approved_job()
        self.job.update(id='article-test', theme={'slug': 'test'}, week='2026-11-06', error=None,
                        approval={'unchanged': 'article approval'}, review={'unchanged': 'article review'},
                        socialHistory=[{'unchanged': 'historical social'}], stage='social_review')
        self.job['social']['approval'] = None
        self.save(self.job)
        req = self.ledger.create_request(self.job['id'], 'social')
        self.delivered = self.ledger.mark_delivered(req['request_id'],
            {'scope': dict(SCOPE, bot_user_id='BOT'), 'parts': [{'verified': True, 'message_ts': '2.0'}]}, '2.0')
        self.job = self.ledger.hold_social_refresh(self.job['id'],
            expected_social_revision=self.job['social']['revision'])
        self.evidence = dict(source='codex', thread_id='offline-owner-thread',
            observed_at='2026-11-08T22:46:00+09:00',
            text=f"post {self.job['id']} {self.job['social']['revision']}",
            directive=self.directive(self.job))

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, job):
        with self.ledger._tx() as db:
            self.ledger._put(db, copy.deepcopy(job), 'fixture')

    @staticmethod
    def directive(job):
        proposal = job['social']['proposal']
        return dict(article_id=job['id'], revision=job['social']['revision'],
                    targetAccountId=proposal['targetAccountId'], textHash=fingerprint(proposal['text']),
                    imageSha256s=[i['sha256'] for i in proposal['images']], replyText=proposal['replyText'])

    def approve(self, **changes):
        args = dict(id=self.job['id'], revision=self.job['social']['revision'],
                    actor='owner', evidence=self.evidence)
        args.update(changes)
        return self.ledger.approve_social_from_codex(**args)

    def state(self):
        with sqlite3.connect(self.ledger.db_path) as db:
            return tuple(db.iterdump())

    def test_approval_preserves_article_history_delivery_and_has_no_effect(self):
        approved = self.approve()
        self.assertEqual('social_approved', approved['stage'])
        for key in ('bundle', 'revision', 'approval', 'publication', 'review', 'socialHistory'):
            self.assertEqual(self.job[key], approved[key])
        for key in ('proposal', 'revision', 'review'):
            self.assertEqual(self.job['social'][key], approved['social'][key])
        approval = approved['social']['approval']
        self.assertEqual('approved', approval['action'])
        self.assertEqual('owner', approval['user_id'])
        self.assertEqual(self.job['social']['revision'], approval['revision'])
        self.assertEqual('codex', approval['source'])
        self.assertEqual(self.evidence, approval['evidence'])
        self.assertNotIn('message_id', approval['evidence'])
        self.assertIn('thread', approval['evidenceLimitations'])
        self.assertTrue(approval['request_id'].startswith('codex-social-'))
        with sqlite3.connect(self.ledger.db_path) as db:
            saved = json.loads(db.execute('SELECT data FROM requests WHERE id=?',
                (self.delivered['request_id'],)).fetchone()[0])
            self.assertEqual('invalidated', saved.pop('status'))
            original = dict(self.delivered)
            original.pop('status')
            self.assertEqual(original, saved)
            self.assertEqual(0, db.execute('SELECT count(*) FROM effects').fetchone()[0])
            self.assertEqual(0, db.execute('SELECT count(*) FROM decisions').fetchone()[0])
            self.assertEqual(1, db.execute("SELECT count(*) FROM events WHERE kind='codex_social_approval'").fetchone()[0])
        self.assertFalse((self.root / 'social-publications').exists())
        self.assertFalse((self.root / 'social-outbox').exists())

    def test_exact_replay_is_noop_and_changed_evidence_or_stage_is_rejected(self):
        approved = self.approve()
        before = self.state()
        self.assertEqual(approved, self.approve())
        self.assertEqual(before, self.state())
        changed = dict(self.evidence, observed_at='2026-11-08T22:47:00+09:00')
        with self.assertRaises(ValueError):
            self.approve(evidence=changed)
        self.assertEqual(before, self.state())
        self.ledger.hold_social_refresh(self.job['id'],
            expected_social_revision=self.job['social']['revision'])
        with self.assertRaises(ValueError):
            self.approve()

    def test_wrong_actor_revision_and_message_fail_without_mutation(self):
        for changes in ({'actor': 'other'}, {'revision': '0' * 64},
                        *[{'evidence': dict(self.evidence, text=text)} for text in
                          ('approved', 'post article-other ' + self.job['social']['revision'],
                           'publish ' + self.job['id'] + ' ' + self.job['social']['revision'], SOTO_TEXT)]):
            with self.subTest(changes=changes):
                before = self.state()
                with self.assertRaises(ValueError):
                    self.approve(**changes)
                self.assertEqual(before, self.state())

    def test_missing_or_fabricated_message_evidence_is_rejected(self):
        for change in ({'source': 'slack'}, {'thread_id': ''}, {'observed_at': ''},
                       {'observed_at': '2026-11-08T22:46:00'}, {'message_id': 'invented'},
                       {'directive': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.approve(evidence=dict(self.evidence, **change))

    def test_directive_must_match_exact_proposal(self):
        for key, value in (('article_id', 'other'), ('revision', '0' * 64), ('targetAccountId', '999'),
                           ('textHash', '0' * 64), ('imageSha256s', ['0' * 64]),
                           ('replyText', 'https://evil.example/'), ('extra', True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.approve(evidence=dict(self.evidence,
                    directive=dict(self.evidence['directive'], **{key: value})))

    def test_configured_account_required_and_runtime_wires_it(self):
        for account in (None, '999'):
            ledger = Ledger(self.root, 'owner', target_account_id=account)
            with self.subTest(account=account), self.assertRaises(ValueError):
                ledger.approve_social_from_codex(self.job['id'], self.job['social']['revision'],
                    'owner', self.evidence)
        from runtime import Runtime
        env = Path(self.tmp.name) / 'env'
        env.write_text('')
        runtime = Runtime(dict(stateRoot=str(self.root), envFile=str(env),
            targetAccountId='123', slack=SCOPE))
        self.assertEqual('social_approved', runtime.ledger.approve_social_from_codex(
            self.job['id'], self.job['social']['revision'], 'owner', self.evidence)['stage'])

    def test_stage_review_publication_fingerprint_and_images_are_revalidated(self):
        mutations = [lambda j: j.update(stage='social_posted'),
            lambda j: j['social']['review'].update(passed=False),
            lambda j: j['social']['review'].update(fingerprint='wrong'),
            lambda j: j['publication'].update(verified=False),
            lambda j: j['publication']['readback'].update(fingerprint='wrong'),
            lambda j: j['social']['proposal'].update(text='changed'),
            lambda j: j['social']['proposal'].update(replyText='https://evil.example/'),
            lambda j: j['social']['proposal'].update(platform='threads'),
            lambda j: j['social'].update(publication={'verified': True}),
            lambda j: j['social'].update(approval={'action': 'approved'}),
            lambda j: j['social']['proposal']['images'][0].update(sha256='0' * 64)]
        for mutation in mutations:
            job = copy.deepcopy(self.job)
            mutation(job)
            self.save(job)
            before = self.state()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.approve()
            self.assertEqual(before, self.state())

    def test_missing_or_wrong_delivery_never_approves(self):
        with self.ledger._tx() as db:
            db.execute('DELETE FROM requests')
        with self.assertRaises(ValueError):
            self.approve()

    def test_full_runtime_scope_accepts_extra_bot_field_without_changing_delivery(self):
        self.assertEqual(SCOPE, self.delivered['scope'])
        self.assertEqual(dict(SCOPE, bot_user_id='BOT'), self.delivered['parts']['scope'])
        before = copy.deepcopy(self.delivered)
        self.assertEqual('social_approved', self.approve()['stage'])
        with self.ledger._tx() as db:
            saved = json.loads(db.execute('SELECT data FROM requests WHERE id=?',
                (before['request_id'],)).fetchone()[0])
            event = json.loads(db.execute("SELECT data FROM events WHERE job_id=? AND kind='delivered'",
                (self.job['id'],)).fetchone()[0])
        self.assertEqual(before, event)
        self.assertEqual(before['parts'], saved['parts'])
        self.assertEqual(before['card_ts'], saved['card_ts'])
        self.assertEqual(before['manifest_hash'], saved['manifest_hash'])

    def test_legacy_delivery_without_optional_bot_scope_still_approves(self):
        request = self.ledger.create_request(self.job['id'], 'social')
        self.ledger.mark_delivered(request['request_id'], SCOPE, '3.0')
        self.ledger.hold_social_refresh(self.job['id'],
            expected_social_revision=self.job['social']['revision'])
        self.assertEqual('social_approved', self.approve()['stage'])

    def test_each_mandatory_scope_key_must_match_even_when_full_parts_match_event(self):
        # Matching full parts/event alone must not authorize the wrong mandatory scope.
        for key in SCOPE:
            for missing in (False, True):
                changed = copy.deepcopy(self.delivered)
                if missing:
                    changed['parts']['scope'].pop(key)
                else:
                    changed['parts']['scope'][key] = 'mismatch'
                with self.ledger._tx() as db:
                    db.execute('UPDATE requests SET data=? WHERE id=?',
                        (json.dumps(changed), changed['request_id']))
                    self.ledger._event(db, self.job['id'], 'delivered', changed)
                before = self.state()
                with self.subTest(key=key, missing=missing), self.assertRaises(ValueError):
                    self.approve()
                self.assertEqual(before, self.state())

    def test_optional_scope_field_still_must_match_the_actual_delivery_event(self):
        changed = copy.deepcopy(self.delivered)
        changed['parts']['scope']['bot_user_id'] = 'another-bot'
        with self.ledger._tx() as db:
            db.execute('UPDATE requests SET data=? WHERE id=?',
                (json.dumps(changed), changed['request_id']))
        before = self.state()
        with self.assertRaises(ValueError):
            self.approve()
        self.assertEqual(before, self.state())

    def test_corrupted_delivery_or_only_created_request_is_not_evidence(self):
        original = copy.deepcopy(self.delivered)
        for changes in ({'manifest_hash': '0' * 64}, {'card_ts': ''}, {'parts': None},
                        {'scope': dict(SCOPE, user_id='other')}, {'card_ts': 'invented'}):
            changed = dict(original, **changes)
            with self.ledger._tx() as db:
                db.execute('UPDATE requests SET data=? WHERE id=?',
                           (json.dumps(changed), original['request_id']))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.approve()
        # A fresh undelivered request has no delivery event, even if the proposal is current.
        with self.ledger._tx() as db:
            db.execute('DELETE FROM requests')
        self.ledger.create_request(self.job['id'], 'social')
        with self.assertRaises(ValueError):
            self.approve()

    def test_changed_proposal_even_with_fresh_review_must_have_exact_delivery_and_binding(self):
        for field, value in (('targetAccountId', '999'), ('text', 'changed'),
                             ('url', 'https://evil.example/'), ('replyText', 'https://evil.example/')):
            job = copy.deepcopy(self.job)
            job['social']['proposal'][field] = value
            revision = fingerprint(job['social']['proposal'])
            job['social']['revision'] = revision
            job['social']['review']['fingerprint'] = revision
            self.save(job)
            evidence = dict(self.evidence, text=f"post {job['id']} {revision}",
                            directive=self.directive(job))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.approve(revision=revision, evidence=evidence)
        self.save(self.job)

    def test_social_review_can_be_approved_and_tick_never_infers_owner_instruction(self):
        from runtime import Runtime
        from unittest.mock import patch
        env = Path(self.tmp.name) / 'env'
        env.write_text('')
        spool = Path(self.tmp.name) / 'spool'
        spool.mkdir(mode=0o700)
        runtime = Runtime(dict(stateRoot=str(self.root), envFile=str(env), spoolDir=str(spool),
            targetAccountId='123', slack=SCOPE))
        with patch.object(runtime.ledger, 'approve_social_from_codex',
                          side_effect=AssertionError('tick must never approve')):
            runtime.tick()
        self.assertIsNone(runtime.ledger.get_job(self.job['id'])['social']['approval'])
        job = copy.deepcopy(self.job)
        job['stage'] = 'social_review'
        self.save(job)
        self.assertEqual('social_approved', self.approve()['stage'])

    def test_current_journal_outbox_and_any_social_effect_require_reconciliation(self):
        revision = self.job['social']['revision']
        for folder in ('social-publications', 'social-outbox'):
            path = self.root / folder / (revision + '.json')
            path.parent.mkdir(mode=0o700)
            path.write_text('{"status":"unknown"}')
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                self.approve()
            self.assertEqual(before, path.read_bytes())
            path.unlink()
        for status in ('in_flight', 'unknown', 'failed', 'success'):
            with self.ledger._tx() as db:
                db.execute('INSERT OR REPLACE INTO effects VALUES (?,?,?,?)',
                           (self.job['id'], 'social', status, '{}'))
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.approve()

    def test_explicit_cli_only_records_approval(self):
        env = Path(self.tmp.name) / 'env'
        env.write_text('')
        config = Path(self.tmp.name) / 'config.json'
        config.write_text(json.dumps(dict(stateRoot=str(self.root), envFile=str(env),
            targetAccountId='123', slack=SCOPE)))
        evidence = Path(self.tmp.name) / 'evidence.json'
        evidence.write_text(json.dumps(self.evidence))
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('runtime.py')),
            '--config', str(config), 'approve-social-from-codex', '--id', self.job['id'],
            '--revision', self.job['social']['revision'], '--evidence-file', str(evidence)],
            capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual('social_approved', value['status'])
        self.assertIs(False, value['posted'])
        self.assertFalse((self.root / 'social-publications').exists())

    def test_exact_soto_instruction_binding_is_pinned(self):
        from ledger import valid_codex_social_instruction
        valid_codex_social_instruction(SOTO_ID, SOTO_REVISION, SOTO_TEXT)
        for id, revision, text in (('article-other', SOTO_REVISION, SOTO_TEXT),
                                   (SOTO_ID, '0' * 64, SOTO_TEXT),
                                   (SOTO_ID, SOTO_REVISION, SOTO_TEXT + ' extra')):
            with self.subTest(id=id, revision=revision), self.assertRaises(ValueError):
                valid_codex_social_instruction(id, revision, text)
