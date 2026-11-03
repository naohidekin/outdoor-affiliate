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

    @staticmethod
    def with_card(b):
        b = copy.deepcopy(b)
        manifest = dict(url='https://img.example/card.png', sha256='a' * 64, size=1200,
                        contentType='image/png', width=1200, height=630,
                        templateVersion='test-v1', sources=[])
        b['article'].setdefault('generationMeta', {})['socialCard'] = manifest
        b['images'].append(dict(manifest, role='social-card', verified=True))
        return b

    def test_card_build_is_opt_in_and_precedes_render_review_and_stage(self):
        class Cards:
            def build(inner, b):
                self.assertIn('content', b['article'])
                return self.with_card(b)
        self.runtime.social_cards = Cards()
        self.config['socialCardsEnabled'] = True
        seen = []
        self.runtime.renderer = lambda b, j: (seen.append(copy.deepcopy(b)) or {'passed': True, 'clicksVerified': True})
        self.runtime.produce()
        self.assertEqual(len(seen), 3)
        for job in self.runtime.ledger.list_jobs():
            self.assertEqual(job['bundle']['images'][-1]['role'], 'social-card')
            self.assertIn('socialCard', job['bundle']['article']['generationMeta'])
        self.assertEqual([x[0] for x in self.writes], ['stage'] * 3)

    def test_enabled_card_build_failure_never_renders_or_stages(self):
        self.config['socialCardsEnabled'] = True
        class Cards:
            def build(inner, b):
                return b
        self.runtime.social_cards = Cards()
        with patch.object(self.runtime, 'renderer') as render:
            self.runtime.produce()
            render.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_social_uses_only_bound_card_and_requires_public_meta_readback(self):
        job = self.published_job()
        job['bundle'] = self.with_card(job['bundle'])
        with patch.object(self.models, 'social') as generate:
            with self.assertRaisesRegex(ValueError, 'social_card_public_readback_missing'):
                self.runtime.make_social(job)
            generate.assert_not_called()
        job['publication']['readback']['socialCard'] = job['bundle']['article']['generationMeta']['socialCard']
        with patch.object(self.models, 'review', wraps=self.models.review) as review, patch.object(self.runtime.ledger, 'record_social'), patch.object(self.runtime, 'deliver'):
            self.runtime.make_social(job)
        self.assertEqual(review.call_args.args[0]['proposal']['images'], [job['bundle']['images'][-1]])
        job['bundle']['images'].pop()
        with self.assertRaisesRegex(ValueError, 'social_card_evidence_missing'):
            self.runtime.make_social(job)

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

    def test_social_review_receives_proposal_surface_and_independent_format_evidence(self):
        job = self.published_job()
        with patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.make_social(job)
        checks = review.call_args.args[1]
        self.assertEqual(checks['reviewKind'], 'social')
        self.assertEqual(checks['publicationReadback'], job['publication'])
        proof = checks['independentSocialFormat']
        self.assertEqual(proof['platform'], 'x')
        self.assertEqual(proof['weightedLength'], sum(1 if ord(c) < 128 else 2 for c in '新記事です。'))
        self.assertEqual(proof['maxWeightedLength'], 280)
        self.assertTrue(all(proof[k] for k in ('formatVerified', 'imagesVerified', 'urlBindingVerified')))
        self.assertIn('not the source article browser', proof['surface'])

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

    def test_existing_medical_gate_blocks_faq_risk_before_slack_or_db(self):
        unsafe = bundle()
        unsafe['faqs'] = unsafe['article']['faqs']
        unsafe['article']['faqs'][0]['answer'] = '低温やけどと凍傷について。'
        with patch.object(self.models, 'draft', return_value=unsafe):
            self.runtime.produce(limit=1)
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)

    def test_research_counts_only_recent_aware_clicks_and_labels_metric(self):
        now = datetime.now(JST)
        context = {'products': [], 'articles': [], 'queuedThemes': [], 'instructions': '', 'clicks': [
            {'clickedAt': (now - timedelta(days=days)).isoformat(), 'pagePath': '/a', 'store': 'rakuten'}
            for days in (1, 60, -1)] + [{'clickedAt': '2026-11-03T12:00:00', 'pagePath': '/a', 'store': 'rakuten'}]}
        result = self.runtime._research_context(context)
        self.assertEqual([{'article': '/a', 'store': 'rakuten', 'clicks': 1}], result['merchantClicks'])
        self.assertIn('not purchases', result['observation']['metric'])

    def test_analytics_context_exports_separate_period_bound_existing_improvements(self):
        root = Path(self.tmp.name) / 'seo'
        root.mkdir()
        (root / 'backlog.json').write_text('legacy backlog')
        (root / 'experiments.json').write_text('legacy experiments')
        self.config['seoStateRoot'] = str(root)
        analytics = {'schemaVersion': 1, 'status': 'ok', 'collectedAt': datetime.now(JST).isoformat(),
            'evidence': {'current': {'startDate': '2026-10-01', 'endDate': '2026-10-28',
                'dateBasis': 'America/Los_Angeles', 'siteUrl': 'https://camp-gear-lab.com/',
                'country': 'jpn', 'searchType': 'web', 'summary': {'clicks': 3}},
                'previous': None, 'ga4': None},
            'opportunities': [{'action': 'improve_existing', 'url': 'https://camp-gear-lab.com/articles/a'}],
            'uncertainty': ['Seasonality unverified'], 'provenance': {'source': 'sanitized metrics'}}
        context = dict(products=[], articles=[], queuedThemes=[], instructions='', clicks=[])
        with patch.object(self.runtime.analytics, 'load_context', return_value=analytics):
            researched = self.runtime._research_context(context)
        self.assertEqual(researched['analytics'], analytics)
        self.assertIn('not become a new duplicate article', researched['instructions'])
        self.assertIn('not seasonal-demand evidence', researched['instructions'])
        private = self.runtime.root / 'analytics/improvements/latest.json'
        exported = root / 'editorial-insights/latest.json'
        self.assertEqual(json.loads(private.read_text()), json.loads(exported.read_text()))
        queue = json.loads(exported.read_text())
        self.assertEqual(queue['evidence'], analytics['evidence'])
        self.assertEqual(queue['status'], 'ok')
        self.assertEqual((root / 'backlog.json').read_text(), 'legacy backlog')
        self.assertEqual((root / 'experiments.json').read_text(), 'legacy experiments')
        with patch.object(self.runtime.analytics, 'load_context', return_value=dict(analytics,
                status='unavailable', collectedAt=None, opportunities=[])):
            self.runtime._analytics_context()
        self.assertEqual(json.loads(exported.read_text())['status'], 'unavailable')
        self.assertEqual(json.loads(exported.read_text())['opportunities'], [])

    def test_report_failure_is_visible_without_changing_approval_or_publication(self):
        self.config.update(generationEnabled=False, publicationEnabled=False, reportsEnabled=True)
        before = self.runtime.ledger.list_jobs()
        with patch.object(self.runtime.reporter, 'tick', return_value=[
                {'kind': 'weekly', 'status': 'requires_reconciliation'}]) as report:
            result = self.runtime.tick()
        self.assertEqual(result['status'], 'attention')
        self.assertTrue(result['reportAttention'])
        report.assert_called_once()
        self.assertEqual(self.runtime.ledger.list_jobs(), before)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.slack.deliveries, [])

    def test_reports_disabled_default_and_tick_due_receipts_prevent_repeat(self):
        self.config.update(generationEnabled=False, publicationEnabled=False)
        with patch.object(self.runtime.reporter, 'tick') as report:
            self.runtime.tick()
            report.assert_not_called()
        self.config['reportsEnabled'] = True
        self.runtime.reporter.config['reportsEnabled'] = True
        # Thu 20 JST, also after this month's day-5 slot. Monthly collector is
        # stubbed, never a provider call; unavailable data is a warning only.
        now = datetime(2026, 11, 12, 20, tzinfo=JST)
        with patch('runtime.datetime', wraps=datetime) as clock, patch.object(self.slack, 'notice',
                return_value={'verified': True, 'message_ts': '1793700000.123456'}) as send:
            clock.now.return_value = now
            self.runtime.tick()
            self.runtime.tick()
        self.assertEqual(send.call_count, 3)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.slack.deliveries, [])
        self.assertFalse(list((self.runtime.root / 'deliveries').glob('*')))

    def test_candidate_correction_keeps_id_week_slot_and_event(self):
        job = self.runtime.ledger.create_candidate({'slug': 'correction', 'title': '実測'})
        fixed = self.runtime.ledger.revise_candidate(job['id'], '仕様の調査候補', '実測は未実施')
        self.assertEqual(job['week'], fixed['week'])
        self.assertEqual(job['id'], fixed['id'])
        self.assertEqual(1, len(self.runtime.ledger.list_jobs()))
        self.runtime.ledger.save_bundle(job['id'], bundle())
        with self.assertRaises(ValueError):
            self.runtime.ledger.revise_candidate(job['id'], '別内容', '勝手な変更')

    def auto_social_job(self):
        source = bundle()
        source['images'][0].update(sha256='a' * 64, size=10)
        with patch.object(self.models, 'draft', return_value=source):
            job = self.published_job()
        self.config.update(targetAccountId='123', socialPostingEnabled=False)
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        self.approve(job)
        self.runtime.consume()
        return self.runtime.ledger.get_job(job['id'])

    @staticmethod
    def social_receipt(job):
        proposal = job['social']['proposal']
        return dict(verified=True, status='verified', fingerprint=job['social']['revision'], accountId='123',
            mainId='111', replyId='222', readback={
                'main': dict(verified=True, id='111', authorId='123', text=proposal['text'],
                             mediaKeys=['3_333'], replyTo=None),
                'reply': dict(verified=True, id='222', authorId='123', text=proposal['replyText'],
                              mediaKeys=[], replyTo='111'),
                'media': {'verified': True, 'items': [{'mediaId': '333', 'mediaKey': '3_333', 'sha256': 'a' * 64}]}})

    def test_auto_mode_account_are_assigned_before_review_not_model_metadata(self):
        job = self.published_job()
        self.config['targetAccountId'] = '123'
        with patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.make_social(job)
        proposal = review.call_args.args[0]['proposal']
        self.assertEqual(proposal['deliveryMode'], 'auto_x')
        self.assertEqual(proposal['targetAccountId'], '123')
        saved = self.runtime.ledger.get_job(job['id'])['social']
        self.assertEqual(saved['revision'], __import__('ledger').fingerprint(proposal))
        self.assertEqual(saved['review']['fingerprint'], saved['revision'])

    def test_disabled_auto_approval_waits_auth_without_handoff_notice_or_publisher(self):
        job = self.auto_social_job()
        before = copy.deepcopy(job['social']['approval'])
        with patch.object(self.runtime, 'publish_social') as publish:
            notices = len(self.slack.notices)
            for _ in range(2):
                result = self.runtime.tick()
                self.assertTrue(any(r.get('status') == 'waiting_auth' and r.get('reason') == 'social_posting_disabled'
                                    for r in result['results']))
            publish.assert_not_called()
        self.assertEqual(len(self.slack.notices), notices)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['social']['approval'], before)
        self.assertFalse((self.runtime.root / 'social-outbox').exists())
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_approved')

    def test_legacy_manual_approval_never_autoposts_or_makes_manual_handoff_from_tick(self):
        job = self.published_job()
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        self.approve(job)
        self.runtime.consume()
        self.config.update(targetAccountId='123', socialPostingEnabled=True)
        with patch.object(self.runtime, 'publish_social') as publish:
            result = self.runtime.tick()
            publish.assert_not_called()
        self.assertTrue(any(r.get('reason') == 'legacy_social_requires_mode_migration' for r in result['results']))
        self.assertFalse((self.runtime.root / 'social-outbox').exists())

    def test_runtime_migration_requires_fixed_target_no_model_call_or_send(self):
        job = self.published_job()
        self.runtime.make_social(job)
        self.config['targetAccountId'] = '123'
        before_deliveries = len(self.slack.deliveries)
        with patch.object(self.models, 'review') as review:
            with self.assertRaisesRegex(ValueError, 'social_target_mismatch'):
                self.runtime.enable_social_autopost(job['id'], '999')
            migrated = self.runtime.enable_social_autopost(job['id'], '123')
            review.assert_not_called()
        self.assertEqual(migrated['stage'], 'social_review')
        self.assertEqual(len(self.slack.deliveries), before_deliveries)
        self.assertIsNone(migrated['social']['approval'])

    def test_x_success_is_recorded_once_and_health_contains_verified_urls(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class Publisher:
            calls = 0
            def publish(inner, current):
                inner.calls += 1
                return self.social_receipt(current)
        publisher = Publisher()
        self.runtime.social_publisher = publisher
        with patch.object(self.slack, 'notice', return_value={'verified': True, 'message_ts': '1793700000.123456'}) as notify:
            first = self.runtime.tick()
            self.runtime.tick()
        self.assertEqual(publisher.calls, 1)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_posted')
        social = next(j for j in first['articles'] if j['id'] == job['id'])['social']
        self.assertEqual(social['publication']['mainUrl'], 'https://x.com/i/web/status/111')
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM effects WHERE kind='social'").fetchone()[0], 0)

    def test_crash_after_x_success_before_ledger_resumes_publisher_journal(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class JournalPublisher:
            calls = 0
            writes = 0
            receipt = None
            def publish(inner, current):
                inner.calls += 1
                if inner.receipt is None:
                    inner.writes += 1
                    inner.receipt = self.social_receipt(current)
                return copy.deepcopy(inner.receipt)
        publisher = JournalPublisher()
        self.runtime.social_publisher = publisher
        with patch.object(self.runtime.ledger, 'record_social_publication', side_effect=RuntimeError('local crash')):
            self.runtime.tick()
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_approved')
        with patch.object(self.slack, 'notice', return_value={'verified': True, 'message_ts': '1793700000.123456'}):
            self.runtime.tick()
        self.assertEqual(publisher.calls, 2)
        self.assertEqual(publisher.writes, 1)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_posted')

    def test_posted_notification_unknown_does_not_repost_x_or_resend_notice(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class Publisher:
            calls = 0
            def publish(inner, current):
                inner.calls += 1
                return self.social_receipt(current)
        publisher = Publisher()
        self.runtime.social_publisher = publisher
        sent = []
        def notice(text):
            if text.startswith('【X投稿確認済み】'):
                sent.append(text)
                raise TimeoutError('Slack result unknown')
            return {'verified': True, 'message_ts': '1793700000.123456'}
        with patch.object(self.slack, 'notice', side_effect=notice):
            for _ in range(3):
                self.runtime.tick()
        self.assertEqual(len(sent), 1)
        self.assertEqual(publisher.calls, 1)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_posted')
        marker = self.runtime.root / 'social-posted-notices' / (job['social']['revision'] + '.json')
        self.assertEqual(json.loads(marker.read_text())['status'], 'in_flight')

    def test_auth_failure_and_changed_target_never_record_social_publication(self):
        job = self.auto_social_job()
        self.config['socialPostingEnabled'] = True
        class Publisher:
            calls = 0
            def publish(inner, current):
                inner.calls += 1
                raise ValueError('x_account_mismatch')
        publisher = Publisher()
        self.runtime.social_publisher = publisher
        self.config['targetAccountId'] = '999'
        with self.assertRaises(ValueError):
            self.runtime.publish_social(job)
        self.assertEqual(publisher.calls, 0)
        self.config['targetAccountId'] = '123'
        with self.assertRaisesRegex(ValueError, 'x_account_mismatch'):
            self.runtime.publish_social(job)
        self.assertEqual(self.runtime.ledger.get_job(job['id'])['stage'], 'social_approved')
        self.assertNotIn('publication', self.runtime.ledger.get_job(job['id'])['social'])


if __name__ == '__main__':
    unittest.main()
