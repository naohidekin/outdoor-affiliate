"""Contract-level flow tests; synthetic data never contacts a provider or merchant."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from runtime import Runtime, atomic, JST
from test_quality import bundle


class ModelsFake:
    def __init__(self):
        self.usage = []
        self.fail_polish = False

    def research(self, context):
        return {'themes': [{'slug': 'new-{}'.format(i), 'title': '新記事{}'.format(i)} for i in range(3)]}

    def draft(self, theme, context):
        b = bundle()
        b['brief']['externalSafe'] = True
        return b

    def polish(self, source, brief):
        return {'content': source + ('\n## 勝手な見出し' if self.fail_polish else ''), 'model': 'gemini-3.8-flash'}

    def review(self, b, checks):
        return {'passed': True, 'score': 8.5, 'model': 'upper', 'issues': [], 'evidence': checks}

    def social(self, b, url):
        return {'text': '新記事です。', 'replyText': url, 'url': url, 'images': b['images'], 'platform': 'x'}


class CatalogFake:
    def catalog(self):
        return {'articles': [], 'products': [], 'categories': [], 'clicks': []}

    def gather(self, theme, context):
        return {'catalog': bundle()['products'], 'references': bundle()['references'],
                'checks': {k: True for k in ('facts', 'images', 'affiliate')}}


class SlackFake:
    def _call(self, method, data):
        return {'ok': True}

    def __init__(self):
        self.deliveries, self.notices = [], []

    def deliver(self, job, req):
        self.deliveries.append((job, req))
        return [{'verified': True}], '1793000000.123456'

    def notice(self, text):
        self.notices.append(text)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = base / 'env'
        self.env.write_text('AMAZON_PARTNER_TAG=camp78-22\n')
        self.scope = dict(team_id='T', app_id='A', user_id='U', channel_id='C', thread_ts='1793000000.000001')
        self.config = {'stateRoot': str(base / 'private'), 'envFile': str(self.env),
                       'repo': str(Path(__file__).resolve().parents[2]), 'slack': self.scope,
                       'spoolDir': str(base / 'spool'), 'generationEnabled': True, 'publicationEnabled': True}
        Path(self.config['spoolDir']).mkdir(mode=0o700)
        self.models, self.slack, self.writes = ModelsFake(), SlackFake(), []

        def publish(action, job):
            self.writes.append((action, job['revision']))
            return {'verified': True, 'url': 'https://camp-gear-lab.com/articles/' + job['theme']['slug'],
                    'readback': {'verified': True, 'fingerprint': job['revision']}}
        self.runtime = Runtime(self.config, models=self.models, catalog=CatalogFake(), slack=self.slack,
            renderer=lambda b, j: {'passed': True, 'clicksVerified': {'desktop': [1], 'mobile': [1]}}, publisher=publish)

    def tearDown(self):
        self.tmp.cleanup()

    def approve(self, job, user='U'):
        req = self.slack.deliveries[-1][1]
        if req['article_id'] != job['id']:
            req = next(r for j, r in self.slack.deliveries if j['id'] == job['id'])
        event = dict(req['payload'], **self.scope)
        event.update(user_id=user, event_id='event-' + req['request_id'],
                     action_id='camp_review_approve', message_ts='1793000000.123456')
        atomic(Path(self.config['spoolDir']) / (req['request_id'] + '.json'), event)

    def test_three_drafts_then_only_owner_approved_version_publishes(self):
        result = self.runtime.produce()
        self.assertEqual(3, len(result['articles']))
        self.assertEqual(['stage'] * 3, [a for a, _ in self.writes])
        self.assertEqual(3, len(self.slack.deliveries))
        self.assertTrue(all(j['approval'] is None for j in self.runtime.ledger.list_jobs()))
        self.config['generationEnabled'] = False
        job = self.runtime.ledger.list_jobs()[0]
        self.approve(job)
        self.runtime.tick()
        self.assertEqual(1, [a for a, _ in self.writes].count('publish'))
        self.runtime.tick()
        self.assertEqual(1, [a for a, _ in self.writes].count('publish'))
        self.assertTrue(any(r['kind'] == 'social' for _, r in self.slack.deliveries))

    def test_foreign_owner_never_publishes(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        self.approve(next(j for j in self.runtime.ledger.list_jobs() if j['bundle']), user='other')
        self.runtime.tick()
        self.assertNotIn('publish', [a for a, _ in self.writes])

    def test_changed_image_invalidates_delivered_approval(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        self.approve(job)
        changed = copy.deepcopy(job['bundle'])
        changed['images'][0]['url'] = 'https://images.example.com/new.jpg'
        self.runtime.ledger.save_bundle(job['id'], changed, job['revision'])
        self.runtime.tick()
        self.assertNotIn('publish', [a for a, _ in self.writes])

    def test_failed_protected_polish_never_reaches_slack_or_draft_db(self):
        self.models.fail_polish = True
        self.runtime.produce(limit=1)
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)
        self.assertEqual(1, sum(j['stage'] == 'error' for j in self.runtime.ledger.list_jobs()))

    def test_unknown_publish_is_not_retried_after_restart(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        self.approve(next(j for j in self.runtime.ledger.list_jobs() if j['bundle']))
        attempts = []
        def lost(action, job):
            attempts.append(action)
            raise TimeoutError('unknown')
        self.runtime.publisher = lost
        self.runtime.tick()
        self.runtime.tick()
        self.assertEqual(['publish'], attempts)

    def test_delivery_uncertainty_never_auto_resends(self):
        self.runtime.produce(limit=1)
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        # Re-delivery of an already-read-back article is a no-op.
        self.assertEqual('already_delivered', self.runtime.deliver(job['id'])['status'])
        self.assertEqual(1, len(self.slack.deliveries))

    def published_job(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        self.approve(job)
        self.runtime.tick()
        return self.runtime.ledger.get_job(job['id'])

    def test_bad_spool_is_quarantined_and_valid_approval_continues(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job = next(j for j in self.runtime.ledger.list_jobs() if j['bundle'])
        spool = Path(self.config['spoolDir'])
        (spool / '000-broken.json').write_text('{')
        (spool / '001-array.json').write_text('[]')
        self.approve(job)
        result = self.runtime.tick()
        self.assertEqual(1, result['decisions'])
        self.assertEqual('published', self.runtime.ledger.get_job(job['id'])['stage'])
        self.assertEqual(2, len(list((spool / 'editorial-quarantine').glob('*.json'))))

    def test_expired_verified_delivery_gets_new_nonce_and_old_card_is_invalid(self):
        self.runtime.produce(limit=1)
        job, old = self.slack.deliveries[-1]
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            row = json.loads(db.execute('SELECT data FROM requests WHERE id=?', (old['request_id'],)).fetchone()[0])
            row['expires_at'] = (datetime.now(JST) - timedelta(seconds=1)).isoformat()
            db.execute('UPDATE requests SET data=? WHERE id=?', (json.dumps(row), old['request_id']))
        self.assertEqual('delivered', self.runtime.deliver(job['id'])['status'])
        new = self.slack.deliveries[-1][1]
        self.assertNotEqual(old['nonce'], new['nonce'])
        event = dict(old['payload'], **self.scope, event_id='expired-card', action_id='camp_review_approve', card_ts='1793000000.123456')
        with self.assertRaises(ValueError):
            self.runtime.ledger.decide(event, self.scope)

    def test_unknown_delivery_stays_attention_and_notice_is_not_repeated(self):
        self.runtime.produce(limit=1)
        self.config['generationEnabled'] = False
        job, req = self.slack.deliveries[-1]
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            row = json.loads(db.execute('SELECT data FROM requests WHERE id=?', (req['request_id'],)).fetchone()[0])
            row['status'] = 'created'
            row['expires_at'] = (datetime.now(JST) - timedelta(days=1)).isoformat()
            db.execute('UPDATE requests SET data=? WHERE id=?', (json.dumps(row), req['request_id']))
        for _ in range(2):
            self.assertEqual('attention', self.runtime.tick()['status'])
        self.assertEqual(1, len(self.slack.deliveries))
        self.assertEqual(1, len(self.slack.notices))
        health = json.loads((self.runtime.root / 'health.json').read_text())
        self.assertEqual('attention', health['status'])

    def test_social_new_claim_image_and_url_never_become_review_evidence(self):
        job = self.published_job()
        for change in ({'text': 'この製品は900gです。'}, {'replyText': 'https://evil.example/other'},
                       {'images': [{'url': 'https://evil.example/image.png', 'verified': True}]}):
            with self.subTest(change=change):
                proposal = self.models.social(job['bundle'], job['publication']['url'])
                proposal.update(change)
                with patch.object(self.models, 'social', return_value=proposal), patch.object(self.models, 'review') as review:
                    with self.assertRaises(ValueError):
                        self.runtime.make_social(job)
                    review.assert_not_called()

    def test_social_binding_rejects_unverified_or_stale_publication(self):
        job = self.published_job()
        for mutation in ({'verified': False}, {'readback': {'verified': True, 'fingerprint': 'stale'}}):
            changed = copy.deepcopy(job)
            changed['publication'].update(mutation)
            with patch.object(self.models, 'social') as generate:
                with self.assertRaises(ValueError):
                    self.runtime.make_social(changed)
                generate.assert_not_called()

    def test_article_original_and_candidate_saved_and_original_sent_to_review(self):
        source = bundle()['article']['content']
        with patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.produce(limit=1)
        checks = review.call_args.args[1]
        self.assertEqual(source, checks['sourceContent'])
        artifacts = list((self.runtime.root / 'research' / 'artifacts').rglob('*.json'))
        self.assertEqual(2, len(artifacts))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in artifacts))
        self.assertEqual({'source', 'candidate'}, {json.loads(p.read_text())['kind'] for p in artifacts})

    def test_health_has_state_and_real_review_model_without_private_payload(self):
        job = self.published_job()
        health = self.runtime.tick()
        summary = next(a for a in health['articles'] if a['id'] == job['id'])
        self.assertEqual({'model': 'upper', 'score': 8.5, 'passed': True}, summary['review'])
        self.assertTrue(summary['publication']['verified'])
        self.assertEqual('approved', summary['approval']['action'])
        self.assertEqual('social_review', summary['social']['status'])
        encoded = json.dumps(health)
        self.assertNotIn('nonce', encoded)
        self.assertNotIn(job['bundle']['article']['content'], encoded)

    def test_preflight_preservation_failure_never_writes_ready(self):
        self.models.fail_polish = True
        with self.assertRaises(ValueError):
            self.runtime.preflight()
        self.assertFalse((self.runtime.root / 'preflight.json').exists())

    def test_source_failure_retries_same_slot_without_more_candidates(self):
        with patch.object(self.runtime.catalog, 'gather', return_value={'checks': {'facts': False}}):
            self.runtime.produce(limit=1)
        failed = next(j for j in self.runtime.ledger.list_jobs() if j['stage'] == 'error')
        self.assertTrue(self.runtime.retry(failed['id'])['sameWeeklySlot'])
        self.runtime.produce()
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        self.assertEqual('review', self.runtime.ledger.get_job(failed['id'])['stage'])

    def test_failed_research_is_not_billed_again_on_each_tick(self):
        with patch.object(self.models, 'research', side_effect=ValueError('provider_unavailable')) as call:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    self.runtime.produce()
        self.assertEqual(1, call.call_count)

    def test_final_review_receives_product_specific_evidence(self):
        gathered = self.runtime.catalog.gather({}, {})
        gathered['evidence'] = {'products': [{'productId': 'p1', 'claims': [{'field': 'weight', 'verified': True}]}]}
        with patch.object(self.runtime.catalog, 'gather', return_value=gathered), patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.produce(limit=1)
        self.assertEqual(gathered['evidence'], review.call_args.args[1]['source'])


if __name__ == '__main__':
    unittest.main()
