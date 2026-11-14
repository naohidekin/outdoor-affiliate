import copy
import unittest
import test_runtime
from test_revision_workflow import baseline, spec
from ledger import fingerprint


class RevisionRoundTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown

    def completed(self):
        before = baseline()
        old = self.runtime.ledger.request_revision(spec(before))
        after = copy.deepcopy(before)
        after.update(content=before['content'] + '\nRevision one.', updatedAt='2026-11-15T01:00:00+09:00')
        old['bundle'] = {'article': after}
        old['revision'] = fingerprint(old['bundle'])
        old['stage'] = 'published'
        old['approval'] = {'revision': old['revision'], 'action': 'approved', 'user_id': 'U'}
        old['publication'] = {'verified': True, 'revision': old['revision'],
            'remoteUpdatedAt': after['updatedAt'],
            'url': 'https://camp-gear-lab.com/articles/' + after['slug'],
            'readback': {'verified': True, 'fingerprint': old['revision']}}
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, old, 'fixture_completed')
        return old, after

    def test_next_live_baseline_gets_new_identity_and_prior_history_is_untouched(self):
        old, after = self.completed()
        new = self.runtime.ledger.request_revision(spec(after))
        self.assertNotEqual(old['id'], new['id'])
        self.assertEqual(new['stage'], 'candidate')
        self.assertIsNone(new['approval'])
        self.assertIsNone(new['publication'])
        self.assertEqual(old, self.runtime.ledger.get_job(old['id']))
        self.assertEqual(new['id'], self.runtime.ledger.request_revision(spec(after))['id'])
        changed = spec(after)
        changed['changeSummary'] = 'Another competing request'
        with self.assertRaises(ValueError):
            self.runtime.ledger.request_revision(changed)

    def test_unconfirmed_publication_owner_or_baseline_cannot_be_superseded(self):
        old, after = self.completed()
        for mutate in ('owner', 'readback', 'time', 'effect'):
            saved = copy.deepcopy(old)
            if mutate == 'owner':
                saved['approval']['user_id'] = 'OTHER'
            elif mutate == 'readback':
                saved['publication']['readback']['verified'] = False
            elif mutate == 'time':
                saved['publication']['remoteUpdatedAt'] = '2026-01-01T00:00:00+09:00'
            with self.runtime.ledger._tx() as db:
                self.runtime.ledger._put(db, saved, 'fixture_changed')
                if mutate == 'effect':
                    db.execute('INSERT INTO effects VALUES (?,?,?,?)', (old['id'], 'publish', 'unknown', '{}'))
            with self.assertRaises(ValueError):
                self.runtime.ledger.request_revision(spec(after))

    def test_codex_approval_uses_saved_evidence_binding_without_inventing_action(self):
        old, after = self.completed()
        evidence = {'source': 'codex', 'thread_id': 'thread', 'message_id': 'message',
                    'text': 'publish exact historical revision'}
        old['approval'].pop('action')
        old['approval'].update(source='codex', evidence=evidence,
            request_id='codex-' + fingerprint(dict(article_id=old['id'], revision=old['revision'], actor='U', evidence=evidence)))
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, old, 'fixture_codex')
        self.assertEqual(self.runtime.ledger.request_revision(spec(after))['stage'], 'candidate')

    def test_codex_action_does_not_bypass_bound_evidence(self):
        old, after = self.completed()
        old['approval'].update(source='codex', request_id='forged')
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, old, 'fixture_forged')
        with self.assertRaises(ValueError):
            self.runtime.ledger.request_revision(spec(after))

    def test_latest_is_timestamp_order_not_replaced_sqlite_row_order(self):
        old, after = self.completed()
        second = self.runtime.ledger.request_revision(spec(after))
        latest = copy.deepcopy(after)
        latest.update(content=after['content'] + '\nRevision two.', updatedAt='2026-11-15T02:00:00+09:00')
        second.update(bundle={'article': latest}, stage='published')
        second['revision'] = fingerprint(second['bundle'])
        second['approval'] = dict(old['approval'], revision=second['revision'])
        second['publication'] = dict(old['publication'], revision=second['revision'],
            remoteUpdatedAt=latest['updatedAt'], readback={'verified': True, 'fingerprint': second['revision']})
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, second, 'fixture_latest')
            self.runtime.ledger._put(db, old, 'fixture_old_replaced_later')
        self.assertEqual(self.runtime.ledger.request_revision(spec(latest))['stage'], 'candidate')
