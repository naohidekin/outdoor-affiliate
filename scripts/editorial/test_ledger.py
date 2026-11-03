"""Offline contract tests; evidence below is synthetic test data only."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ledger', Path(__file__).with_name('ledger.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Ledger = mod.Ledger
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 2, 10, tzinfo=JST)
SCOPE = dict(team_id='T', app_id='A', user_id='U', channel_id='C', thread_ts='1.0')


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'private'
        self.ledger = Ledger(self.root, 'U')
        self.bundle = dict(article={'title': 'Title', 'body': 'Body'}, products=[{'url': 'https://example.test/p'}],
                           images=[{'sha256': 'test-image'}], brief={'goal': 'test'}, references=['https://example.test/r'])

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, slug='test', now=NOW):
        job = self.ledger.create_candidate({'slug': slug, 'title': 'Test'}, now)
        return self.ledger.save_bundle(job['id'], self.bundle)

    def review(self, job):
        return dict(passed=True, score=8, evidence={key: True for key in ('facts', 'images', 'affiliate', 'medical', 'render')},
                    polish={'model': 'gemini-3.8-flash', 'validated': True}, fingerprint=job['revision'])

    def request(self, job, kind='article'):
        if kind == 'article':
            self.ledger.record_review(job['id'], job['revision'], self.review(job))
        req = self.ledger.create_request(job['id'], kind, NOW)
        self.ledger.mark_delivered(req['request_id'], SCOPE, '2.0')
        return req

    def event(self, req, **changes):
        event = dict(req['payload'], **SCOPE, event_id='event-' + req['request_id'], action_id='camp_review_approve', card_ts='2.0')
        event.update(changes)
        return event

    def approved(self):
        job = self.draft()
        req = self.request(job)
        self.ledger.decide(self.event(req), SCOPE, NOW)
        return self.ledger.get_job(job['id'])

    def test_caps_idempotent_restart_and_pending(self):
        job = self.draft()
        self.assertEqual(job['id'], self.ledger.create_candidate({'slug': 'test'}, NOW)['id'])
        for slug in ('two', 'three'):
            self.ledger.create_candidate({'slug': slug}, NOW)
        restart = Ledger(self.root, 'U')
        with self.assertRaises(ValueError):
            restart.create_candidate({'slug': 'four'}, NOW)
        with self.assertRaises(ValueError):
            restart.create_candidate({'slug': 'four'}, NOW + timedelta(days=7))
        restart.set_stage(job['id'], 'rejected')
        with self.assertRaises(ValueError):
            restart.create_candidate({'slug': 'four'}, NOW)
        restart.create_candidate({'slug': 'four'}, NOW + timedelta(days=7))
        self.assertEqual(4, len(restart.list_jobs()))

    def test_jst_week_and_aware_dates(self):
        utc = datetime(2026, 11, 1, 15, tzinfo=timezone.utc)
        job = self.ledger.create_candidate({'slug': 'boundary'}, utc)
        self.assertEqual('2026-11-02', job['week'])
        req = self.request(self.ledger.save_bundle(job['id'], self.bundle))
        self.assertEqual(NOW + timedelta(days=7), datetime.fromisoformat(req['expires_at']))
        with self.assertRaises(ValueError):
            self.ledger.create_candidate({'slug': 'naive'}, datetime(2026, 11, 2))

    def test_bundle_changes_invalidate_all_approvals(self):
        for index, field in enumerate(('images', 'products', 'references', 'article')):
            with self.subTest(field=field):
                ledger = self.ledger
                job = self.draft(field, NOW + timedelta(days=7 * (index // 3)))
                req = self.request(job)
                ledger.decide(self.event(req), SCOPE, NOW)
                changed = copy.deepcopy(self.bundle)
                changed[field] = {'changed': 'new link/title/product/image'}
                new = ledger.save_bundle(job['id'], changed, job['revision'])
                self.assertNotEqual(job['revision'], new['revision'])
                self.assertEqual('draft', new['stage'])
                self.assertIsNone(new['review'])
                self.assertIsNone(new['approval'])
                with self.assertRaises(ValueError):
                    ledger.decide(self.event(req, event_id='old'), SCOPE, NOW)
                ledger.set_stage(job['id'], 'rejected')

    def test_review_requirements_and_revision(self):
        job = self.draft()
        for flag in ('facts', 'images', 'affiliate', 'medical', 'render'):
            review = self.review(job)
            review['evidence'][flag] = False
            with self.assertRaises(ValueError):
                self.ledger.record_review(job['id'], job['revision'], review)
        for changes in ({'score': 7.49}, {'passed': False}, {'fingerprint': 'old'}, {'polish': {'model': 'other', 'validated': True}}):
            with self.assertRaises(ValueError):
                self.ledger.record_review(job['id'], job['revision'], dict(self.review(job), **changes))
        with self.assertRaises(ValueError):
            self.ledger.create_request(job['id'], now=NOW)
        with self.assertRaises(ValueError):
            self.ledger.save_bundle(job['id'], self.bundle, 'old')

    def test_scope_owner_nonce_expiry_card_and_duplicate(self):
        job = self.draft()
        req = self.request(job)
        for changes in ({'user_id': 'foreign'}, {'nonce': 'bad'}, {'nonce': '不正'}, {'manifest_hash': 'bad'}, {'card_ts': 'old'}, {'action_id': 'approve'}):
            with self.assertRaises(ValueError):
                self.ledger.decide(self.event(req, **changes), SCOPE, NOW)
        for key in SCOPE:
            scope = dict(SCOPE)
            scope.pop(key)
            with self.assertRaises(ValueError):
                self.ledger.decide(self.event(req), scope, NOW)
        with self.assertRaises(ValueError):
            self.ledger.decide(self.event(req), SCOPE, NOW + timedelta(days=7))
        self.ledger.decide(self.event(req), SCOPE, NOW)
        before = self.ledger.get_job(job['id'])
        self.ledger.decide(self.event(req), SCOPE, NOW)
        self.assertEqual(before, self.ledger.get_job(job['id']))
        with self.assertRaises(ValueError):
            Ledger(self.root, 'foreign')

    def test_delivery_required_and_replaced_request(self):
        job = self.draft()
        self.ledger.record_review(job['id'], job['revision'], self.review(job))
        old = self.ledger.create_request(job['id'], now=NOW)
        with self.assertRaises(ValueError):
            self.ledger.decide(self.event(old), SCOPE, NOW)
        self.ledger.mark_delivered(old['request_id'], SCOPE, '2.0')
        self.request(job)
        with self.assertRaises(ValueError):
            self.ledger.decide(self.event(old), SCOPE, NOW)

    def test_effect_unknown_and_restart_refuse_retry(self):
        job = self.approved()
        self.assertTrue(self.ledger.claim_effect(job['id'], 'publish'))
        self.assertFalse(Ledger(self.root, 'U').claim_effect(job['id'], 'publish'))
        self.ledger.finish_effect(job['id'], 'publish', {'status': 'unknown'})
        self.assertFalse(Ledger(self.root, 'U').claim_effect(job['id'], 'publish'))
        with self.assertRaises(ValueError):
            self.ledger.finish_effect(job['id'], 'publish', {'status': 'success'})

    def test_publication_and_social_separate_approval(self):
        job = self.approved()
        with self.assertRaises(ValueError):
            self.ledger.record_publication(job['id'], job['revision'], {'verified': True})
        evidence = {'verified': True, 'url': 'https://example.test/article', 'readback': {'verified': True, 'fingerprint': job['revision']}}
        self.ledger.record_publication(job['id'], job['revision'], evidence)
        social = {'text': 'Post', 'url': evidence['url']}
        review = self.review({'revision': mod.fingerprint(social)})
        self.ledger.record_social(job['id'], social, review)
        req = self.request(job, 'social')
        self.ledger.decide(self.event(req), SCOPE, NOW)
        self.assertEqual('social_approved', self.ledger.get_job(job['id'])['stage'])
        social['text'] = 'Changed'
        self.ledger.record_social(job['id'], social, self.review({'revision': mod.fingerprint(social)}))
        with self.assertRaises(ValueError):
            self.ledger.decide(self.event(req, event_id='stale-social'), SCOPE, NOW)
        self.assertIsNone(self.ledger.get_job(job['id'])['social']['approval'])

    def test_fingerprint_is_json_only_and_never_reads_paths(self):
        value = {'path': '/private/secret', 'file_path': '/dev/zero',
                 'nested': [{'local_path': 'relative', 'source_path': '/missing',
                             'image_path': '/tmp/image', 'article_path': '/tmp/article'}]}
        expected = hashlib.sha256(mod.canonical(value).encode('utf-8')).hexdigest()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected file read')):
            self.assertEqual(expected, mod.fingerprint(value))
            self.bundle['extra'] = value
            job = self.draft()
            req = self.request(job)
            self.ledger.decide(self.event(req), SCOPE, NOW)
        self.assertEqual('approved', self.ledger.get_job(job['id'])['stage'])

    def test_catalog_image_sha_change_invalidates_approval(self):
        self.bundle['images'] = [{'url': 'https://images.example.com/image.jpg', 'sha256': 'a' * 64}]
        job = self.approved()
        self.bundle['images'][0]['sha256'] = 'b' * 64
        changed = self.ledger.save_bundle(job['id'], self.bundle)
        self.assertNotEqual(job['revision'], changed['revision'])
        self.assertIsNone(changed['approval'])
        self.assertIsNone(changed['review'])
        self.assertEqual('draft', changed['stage'])

    def test_published_and_social_approved_jobs_are_protected(self):
        job = self.approved()
        evidence = {'verified': True, 'url': 'https://example.test/article',
                    'readback': {'verified': True, 'fingerprint': job['revision']}}
        self.ledger.record_publication(job['id'], job['revision'], evidence)

        def check_protected():
            before = self.ledger.get_job(job['id'])
            with sqlite3.connect(self.ledger.db_path) as db:
                events_before = db.execute('SELECT count(*) FROM events').fetchone()[0]
            changed = copy.deepcopy(self.bundle)
            changed['article']['title'] = 'Changed published title'
            for bundle in (self.bundle, changed):
                with self.assertRaises(ValueError):
                    self.ledger.save_bundle(job['id'], bundle, job['revision'])
            for stage in ('candidate', 'draft', 'review', 'held', 'rejected', 'error', 'published', 'social_approved'):
                with self.assertRaises(ValueError):
                    self.ledger.set_stage(job['id'], stage)
            self.assertEqual(before, self.ledger.get_job(job['id']))
            with sqlite3.connect(self.ledger.db_path) as db:
                self.assertEqual(events_before, db.execute('SELECT count(*) FROM events').fetchone()[0])

        check_protected()
        proposal = {'text': 'Post', 'url': evidence['url']}
        self.ledger.record_social(job['id'], proposal, self.review({'revision': mod.fingerprint(proposal)}))
        req = self.request(job, 'social')
        self.ledger.decide(self.event(req), SCOPE, NOW)
        self.assertEqual('social_approved', self.ledger.get_job(job['id'])['stage'])
        check_protected()

    def test_root_permissions_and_immutable_events(self):
        self.assertEqual(0o700, self.root.stat().st_mode & 0o777)
        self.assertEqual(0o600, self.ledger.db_path.stat().st_mode & 0o777)
        parent_mode = Path(self.tmp.name).stat().st_mode
        for root in ('relative', '/', str(Path.home()), str(Path(__file__).parent / 'state')):
            with self.assertRaises(ValueError):
                Ledger(root, 'U')
        self.assertEqual(parent_mode, Path(self.tmp.name).stat().st_mode)
        self.draft()
        with sqlite3.connect(self.ledger.db_path) as db:
            self.assertGreater(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
            for sql in ('DELETE FROM events', "UPDATE events SET kind='bad'"):
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute(sql)

    def test_concurrent_caps_and_claim(self):
        def candidate(index):
            try:
                return Ledger(self.root, 'U').create_candidate({'slug': str(index)}, NOW)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = [job for job in pool.map(candidate, range(6)) if job]
        self.assertEqual(3, len(jobs))
        job = self.ledger.save_bundle(jobs[0]['id'], self.bundle)
        req = self.request(job)
        self.ledger.decide(self.event(req), SCOPE, NOW)
        with ThreadPoolExecutor(max_workers=6) as pool:
            claims = list(pool.map(lambda _: Ledger(self.root, 'U').claim_effect(job['id'], 'publish'), range(6)))
        self.assertEqual(1, sum(claims))

    def test_reopening_rejected_cannot_exceed_pending_cap(self):
        job = self.draft()
        self.ledger.set_stage(job['id'], 'rejected')
        for index in range(3):
            self.ledger.create_candidate({'slug': str(index)}, NOW + timedelta(days=7))
        with self.assertRaises(ValueError):
            self.ledger.set_stage(job['id'], 'draft')
        self.assertEqual('rejected', self.ledger.get_job(job['id'])['stage'])

    def test_json_copy_canonical_and_failed_retry(self):
        job = self.approved()
        same = dict(reversed(list(self.bundle.items())))
        self.assertEqual(job['revision'], self.ledger.save_bundle(job['id'], same)['revision'])
        same['article'] = {'body': 'Mutated return/input'}
        self.assertEqual('Title', self.ledger.get_job(job['id'])['bundle']['article']['title'])
        self.assertTrue(self.ledger.claim_effect(job['id'], 'publish'))
        self.ledger.finish_effect(job['id'], 'publish', {'status': 'failed'})
        self.assertTrue(self.ledger.claim_effect(job['id'], 'publish'))
        self.ledger.finish_effect(job['id'], 'publish', {'status': 'success'})
        self.assertFalse(self.ledger.claim_effect(job['id'], 'publish'))

    def test_reject_hold_and_social_prerequisite(self):
        for index, (action, stage) in enumerate((('camp_review_reject', 'rejected'), ('camp_review_hold', 'held'))):
            job = self.draft(str(index))
            req = self.request(job)
            result = self.ledger.decide(self.event(req, action_id=action), SCOPE, NOW)
            self.assertEqual(stage, result['stage'])
            self.assertIsNone(result['approval'])
            with self.assertRaises(ValueError):
                self.ledger.claim_effect(job['id'], 'publish')
            with self.assertRaises(ValueError):
                self.ledger.create_request(job['id'], 'social', NOW)

    def test_existing_parents_and_insecure_roots_are_not_chmodded(self):
        parent = Path(self.tmp.name) / 'parent'
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        child = Ledger(parent / 'child', 'U')
        self.assertEqual(0o755, parent.stat().st_mode & 0o777)
        self.assertEqual(0o700, child.root.stat().st_mode & 0o777)
        with self.assertRaises(ValueError):
            Ledger(parent, 'U')
        self.assertEqual(0o755, parent.stat().st_mode & 0o777)
        child.db_path.chmod(0o644)
        with self.assertRaises(ValueError):
            Ledger(child.root, 'U')
        self.assertEqual(0o644, child.db_path.stat().st_mode & 0o777)

    def codex_evidence(self, job):
        return dict(source='codex', thread_id='chat-1', message_id='message-1',
                    text=f"記事 {job['id']} 版 {job['revision']} を公開してください")

    def test_codex_approval_publication_and_immutable_event(self):
        job = self.draft()
        req = self.request(job)
        evidence = self.codex_evidence(job)
        result = self.ledger.approve_from_codex(job['id'], job['revision'], 'U', evidence)
        approval = result['approval']
        self.assertEqual('approved', result['stage'])
        self.assertEqual('codex', approval['source'])
        self.assertEqual('U', approval['user_id'])
        self.assertEqual(job['revision'], approval['revision'])
        self.assertEqual(evidence, approval['evidence'])
        self.assertRegex(approval['request_id'], r'^codex-[0-9a-f]{64}$')
        self.assertEqual(timedelta(hours=9), datetime.fromisoformat(approval['at']).utcoffset())
        evidence['text'] = 'Mutated input'
        self.assertNotEqual(evidence, self.ledger.get_job(job['id'])['approval']['evidence'])
        with self.assertRaises(ValueError):
            self.ledger.decide(self.event(req), SCOPE, NOW)
        with sqlite3.connect(self.ledger.db_path) as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM events WHERE kind='codex_approval'").fetchone()[0])
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM events WHERE kind='codex_approval'")
        self.assertTrue(self.ledger.claim_effect(job['id'], 'publish'))
        self.ledger.record_publication(job['id'], job['revision'], {
            'verified': True, 'url': 'https://example.test/article',
            'readback': {'verified': True, 'fingerprint': job['revision']}})
        self.ledger.finish_effect(job['id'], 'publish', {'status': 'success'})
        with self.assertRaises(ValueError):
            self.ledger.approve_from_codex(job['id'], job['revision'], 'U', self.codex_evidence(job))

    def test_codex_approval_actor_revision_review_and_text_required(self):
        job = self.draft()
        with self.assertRaises(ValueError):
            self.ledger.approve_from_codex(job['id'], job['revision'], 'U', self.codex_evidence(job))
        self.ledger.record_review(job['id'], job['revision'], self.review(job))
        for actor, revision in (('foreign', job['revision']), ('U', '0' * 64)):
            with self.assertRaises(ValueError):
                self.ledger.approve_from_codex(job['id'], revision, actor, self.codex_evidence(job))
        evidence = self.codex_evidence(job)
        invalid = [None, {}, dict(evidence, source='slack'), dict(evidence, thread_id=' '),
                   dict(evidence, message_id=''), dict(evidence, text='公開してください'),
                   dict(evidence, text=f"{job['id']} {job['revision']} 公開しないでください"),
                   dict(evidence, text=f"{job['id']} {job['revision']} 公開していいですか？"),
                   dict(evidence, text=f"記事 {job['id']} 版 {job['revision']} を公開してください。ただしまだ承認しません")]
        for item in invalid:
            with self.subTest(evidence=item), self.assertRaises(ValueError):
                self.ledger.approve_from_codex(job['id'], job['revision'], 'U', item)
        self.assertIsNone(self.ledger.get_job(job['id'])['approval'])
        changed = copy.deepcopy(self.bundle)
        changed['article']['title'] = 'New revision'
        self.ledger.save_bundle(job['id'], changed)
        with self.assertRaises(ValueError):
            self.ledger.approve_from_codex(job['id'], job['revision'], 'U', evidence)

    def test_codex_duplicate_and_effect_pending_rejected(self):
        job = self.draft()
        self.ledger.record_review(job['id'], job['revision'], self.review(job))
        self.ledger.approve_from_codex(job['id'], job['revision'], 'U', self.codex_evidence(job))
        before = self.ledger.get_job(job['id'])
        with self.assertRaises(ValueError):
            Ledger(self.root, 'U').approve_from_codex(job['id'], job['revision'], 'U', self.codex_evidence(job))
        self.assertEqual(before, self.ledger.get_job(job['id']))
        self.ledger.record_review(job['id'], job['revision'], self.review(job))
        for kind, status in (('publish', 'in_flight'), ('publication', 'unknown'), ('schedule', 'pending'), ('publish', 'success')):
            with self.subTest(kind=kind, status=status):
                with sqlite3.connect(self.ledger.db_path) as db:
                    db.execute('DELETE FROM effects')
                    db.execute('INSERT INTO effects VALUES (?,?,?,?)', (job['id'], kind, status, '{}'))
                with self.assertRaises(ValueError):
                    self.ledger.approve_from_codex(job['id'], job['revision'], 'U', self.codex_evidence(job))

    def test_codex_approval_concurrent_single_winner(self):
        job = self.draft()
        self.ledger.record_review(job['id'], job['revision'], self.review(job))

        def approve(index):
            evidence = dict(self.codex_evidence(job), message_id=f'message-{index}')
            try:
                Ledger(self.root, 'U').approve_from_codex(job['id'], job['revision'], 'U', evidence)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(1, sum(pool.map(approve, range(6))))
        with sqlite3.connect(self.ledger.db_path) as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM events WHERE kind='codex_approval'").fetchone()[0])

    def test_codex_existing_slack_approval_and_schedule_stage_rejected(self):
        job = self.approved()
        with self.assertRaises(ValueError):
            self.ledger.approve_from_codex(job['id'], job['revision'], 'U', self.codex_evidence(job))
        self.ledger.record_review(job['id'], job['revision'], self.review(job))
        for stage in ('publishing', 'scheduled', 'schedule_pending', 'publication_pending'):
            with self.subTest(stage=stage):
                raw = self.ledger.get_job(job['id'])
                raw['stage'] = stage
                with sqlite3.connect(self.ledger.db_path) as db:
                    db.execute('UPDATE jobs SET data=? WHERE id=?', (mod.canonical(raw), job['id']))
                with self.assertRaises(ValueError):
                    self.ledger.approve_from_codex(job['id'], job['revision'], 'U', self.codex_evidence(job))

    def test_codex_approval_english_directive_and_corrupt_bundle(self):
        job = self.draft()
        self.ledger.record_review(job['id'], job['revision'], self.review(job))
        evidence = self.codex_evidence(job)
        evidence['text'] = f"publish {job['id']} {job['revision']}"
        with sqlite3.connect(self.ledger.db_path) as db:
            raw = copy.deepcopy(job)
            raw['review'] = self.review(job)
            raw['bundle']['article']['title'] = 'Unbound mutation'
            db.execute('UPDATE jobs SET data=? WHERE id=?', (mod.canonical(raw), job['id']))
        with self.assertRaises(ValueError):
            self.ledger.approve_from_codex(job['id'], job['revision'], 'U', evidence)
        self.bundle['article']['title'] = 'Repaired draft'
        job = self.ledger.save_bundle(job['id'], self.bundle)
        self.ledger.record_review(job['id'], job['revision'], self.review(job))
        evidence['text'] = f"publish {job['id']} {job['revision']}"
        self.assertEqual('approved', self.ledger.approve_from_codex(job['id'], job['revision'], 'U', evidence)['stage'])

    def test_protected_stages_cannot_bypass_gates(self):
        job = self.draft()
        for stage in ('approved', 'published', 'social_approved', 'APPROVED'):
            with self.assertRaises(ValueError):
                self.ledger.set_stage(job['id'], stage)

    def social_pending(self):
        image = dict(url='https://images.example/image.jpg', sha256='a' * 64, verified=True, size=10)
        self.bundle['images'] = [image]
        job = self.approved()
        url = 'https://camp-gear-lab.com/articles/test'
        self.ledger.record_publication(job['id'], job['revision'],
            dict(verified=True, url=url, readback={'verified': True, 'fingerprint': job['revision']}))
        proposal = dict(text='広告 公開仕様の調査です。', replyText=url, url=url, images=[image], platform='x')
        review = self.review({'revision': mod.fingerprint(proposal)})
        return self.ledger.record_social(job['id'], proposal, review)

    def auto_social_approved(self):
        job = self.social_pending()
        job = self.ledger.enable_social_autopost(job['id'], '123')
        req = self.request(job, 'social')
        return self.ledger.decide(self.event(req), SCOPE, NOW)

    def social_readback(self, job):
        proposal = job['social']['proposal']
        return dict(status='verified', verified=True, fingerprint=job['social']['revision'], accountId='123',
            mainId='111', replyId='222', readback={
                'main': dict(verified=True, id='111', authorId='123', text=proposal['text'],
                             mediaKeys=['3_333'], replyTo=None, urls=[]),
                'reply': dict(verified=True, id='222', authorId='123', text='https://t.co/short',
                              urls=[{'url': 'https://t.co/short', 'expanded_url': proposal['replyText'],
                                     'start': 0, 'end': len('https://t.co/short')}],
                              mediaKeys=[], replyTo='111'),
                'media': {'verified': True, 'items': [{'mediaId': '333', 'mediaKey': '3_333', 'sha256': 'a' * 64}]}})

    def test_mode_migration_preserves_content_review_and_invalidates_old_approval(self):
        job = self.social_pending()
        old_request = self.request(job, 'social')
        approved = self.ledger.decide(self.event(old_request), SCOPE, NOW)
        old = copy.deepcopy(approved['social'])
        migrated = self.ledger.enable_social_autopost(job['id'], '123')
        social = migrated['social']
        self.assertEqual(migrated['stage'], 'social_review')
        self.assertIsNone(social['approval'])
        self.assertNotEqual(social['revision'], old['revision'])
        self.assertEqual({k: v for k, v in social['proposal'].items() if k not in ('deliveryMode', 'targetAccountId')}, old['proposal'])
        self.assertEqual(social['modeTransition']['originalProposal'], old['proposal'])
        self.assertEqual(social['modeTransition']['originalContentReview'], old['review'])
        self.assertFalse(social['modeTransition']['modelRerun'])
        self.assertEqual(social['review']['score'], old['review']['score'])
        self.assertEqual(social['review']['fingerprint'], social['revision'])
        self.assertEqual(migrated['publication'], approved['publication'])
        with self.assertRaises(ValueError):
            self.ledger.decide(self.event(old_request, event_id='new-after-migration'), SCOPE, NOW)
        with self.assertRaises(ValueError):
            self.ledger.enable_social_autopost(job['id'], '999')
        with sqlite3.connect(self.ledger.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='social_mode_migrated'").fetchone()[0], 1)
            self.assertEqual(json.loads(db.execute('SELECT data FROM requests WHERE id=?',
                (old_request['request_id'],)).fetchone()[0])['status'], 'invalidated')

    def test_mode_migration_refuses_any_social_effect_or_handoff_or_publisher_journal(self):
        job = self.social_pending()
        for mode in ('effect_failed', 'effect_unknown', 'handoff', 'journal'):
            with self.subTest(mode=mode):
                if mode.startswith('effect'):
                    with sqlite3.connect(self.ledger.db_path) as db:
                        db.execute('INSERT INTO effects VALUES (?,?,?,?)',
                            (job['id'], 'social', mode.split('_')[1], '{}'))
                else:
                    folder = self.root / ('social-outbox' if mode == 'handoff' else 'social-publications')
                    folder.mkdir(exist_ok=True)
                    (folder / (job['social']['revision'] + '.json')).write_text('{}')
                before = self.ledger.get_job(job['id'])
                with self.assertRaises(ValueError):
                    self.ledger.enable_social_autopost(job['id'], '123')
                self.assertEqual(self.ledger.get_job(job['id']), before)
                with sqlite3.connect(self.ledger.db_path) as db:
                    db.execute('DELETE FROM effects WHERE job_id=? AND kind=?', (job['id'], 'social'))
                if not mode.startswith('effect'):
                    (folder / (job['social']['revision'] + '.json')).unlink()

    def test_mode_migration_requires_valid_target_and_original_review(self):
        job = self.social_pending()
        for target in ('', '0', '0123', 'abc', 123, '9' * 21):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.ledger.enable_social_autopost(job['id'], target)
        with sqlite3.connect(self.ledger.db_path) as db:
            bad = copy.deepcopy(job)
            bad['social']['review']['passed'] = False
            db.execute('UPDATE jobs SET data=? WHERE id=?', (mod.canonical(bad), job['id']))
        with self.assertRaises(ValueError):
            self.ledger.enable_social_autopost(job['id'], '123')

    def test_social_publication_requires_exact_account_text_reply_and_media_proof(self):
        job = self.auto_social_approved()
        evidence = self.social_readback(job)
        mutations = [lambda e: e.update(verified=False), lambda e: e.update(fingerprint='old'),
            lambda e: e.update(accountId='999'), lambda e: e.update(mainId='555'),
            lambda e: e['readback']['main'].update(authorId='999'),
            lambda e: e['readback']['main'].update(text='Changed'),
            lambda e: e['readback']['main'].update(verified=False),
            lambda e: e['readback']['reply'].update(replyTo='555'),
            lambda e: e['readback']['reply']['urls'][0].update(expanded_url='https://evil.example'),
            lambda e: e['readback']['media'].update(verified=False),
            lambda e: e['readback']['media']['items'][0].update(sha256='b' * 64),
            lambda e: e['readback']['main'].update(mediaKeys=['3_999']),
            lambda e: e['readback']['reply'].update(mediaKeys=['3_333'])]
        for mutation in mutations:
            altered = copy.deepcopy(evidence)
            mutation(altered)
            with self.assertRaises(ValueError):
                self.ledger.record_social_publication(job['id'], job['social']['revision'], altered)
            self.assertEqual(self.ledger.get_job(job['id'])['stage'], 'social_approved')
        posted = self.ledger.record_social_publication(job['id'], job['social']['revision'], evidence)
        self.assertEqual(posted['stage'], 'social_posted')
        self.assertEqual(posted['social']['publication']['mainUrl'], 'https://x.com/i/web/status/111')
        self.assertEqual(posted['social']['publication']['replyUrl'], 'https://x.com/i/web/status/222')
        self.assertEqual(Ledger(self.root, 'U').record_social_publication(job['id'], job['social']['revision'], evidence), posted)
        for action in (lambda: self.ledger.enable_social_autopost(job['id'], '123'),
                       lambda: self.ledger.record_social(job['id'], job['social']['proposal'], job['social']['review']),
                       lambda: self.ledger.create_request(job['id'], 'social')):
            with self.assertRaises(ValueError):
                action()

    def test_social_publication_rejects_unapproved_or_legacy_manual_authority(self):
        job = self.social_pending()
        req = self.request(job, 'social')
        legacy = self.ledger.decide(self.event(req), SCOPE, NOW)
        with self.assertRaises(ValueError):
            self.ledger.record_social_publication(job['id'], legacy['social']['revision'], self.social_readback(legacy))
        migrated = self.ledger.enable_social_autopost(job['id'], '123')
        with self.assertRaises(ValueError):
            self.ledger.record_social_publication(job['id'], migrated['social']['revision'], self.social_readback(migrated))

    def test_exact_x_generated_media_suffix_requires_terminal_span_same_post_and_media_key(self):
        expected = '広告 変更しない本文'
        short = 'https://t.co/photo'
        post = dict(id='111', text=expected + ' ' + short, mediaKeys=['3_333'], urls=[dict(
            url=short, expanded_url='https://x.com/camp_gear_lab/status/111/photo/1',
            start=len(expected) + 1, end=len(expected + ' ' + short), media_key='3_333')])
        self.assertTrue(mod.exact_x_text(post, expected))
        mutations = [lambda p: p.update(text='Changed ' + p['text']),
            lambda p: p['urls'][0].update(start=0), lambda p: p['urls'][0].update(end=1),
            lambda p: p['urls'][0].update(media_key='3_999'),
            lambda p: p['urls'][0].update(expanded_url='https://x.com/camp_gear_lab/status/999/photo/1'),
            lambda p: p['urls'][0].update(expanded_url='https://x.com/camp_gear_lab/status/111/photo/2'),
            lambda p: p['urls'][0].update(expanded_url='https://evil.example/camp_gear_lab/status/111/photo/1'),
            lambda p: p['urls'][0].update(expanded_url='https://x.com/camp_gear_lab/status/111/photo/1?x=1'),
            lambda p: p.update(text=short + ' ' + expected), lambda p: p.update(mediaKeys=[])]
        for mutation in mutations:
            changed = copy.deepcopy(post)
            mutation(changed)
            with self.subTest(changed=changed):
                self.assertFalse(mod.exact_x_text(changed, expected))

    def test_verified_social_publication_accepts_proven_x_generated_image_suffix(self):
        job = self.auto_social_approved()
        evidence = self.social_readback(job)
        main = evidence['readback']['main']
        expected = main['text']
        main['text'] += ' https://t.co/photo'
        main['urls'] = [dict(url='https://t.co/photo',
            expanded_url='https://x.com/camp_gear_lab/status/111/photo/1',
            start=len(expected) + 1, end=len(main['text']), media_key='3_333')]
        posted = self.ledger.record_social_publication(job['id'], job['social']['revision'], evidence)
        self.assertEqual(posted['stage'], 'social_posted')
        self.assertEqual(posted['social']['publication']['readback']['main']['text'], main['text'])


if __name__ == '__main__':
    unittest.main()
