"""Offline SNS supplement, immutable publication and partial-effect transition contracts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from ledger import fingerprint, valid_social_images, valid_image_refresh, REFRESH_NOTICE
from runtime import Runtime
from social_publisher import SocialPublisher
from slack import Slack
from test_social_publisher import approved_job, Fetcher, XFake


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        env = base / 'env'
        env.write_text('')
        self.config = dict(stateRoot=str(base / 'state'), envFile=str(env),
                           repo=str(Path(__file__).resolve().parents[2]), socialPostingEnabled=False,
                           targetAccountId='123', slack=dict(user_id='owner', team_id='T', app_id='A',
                           channel_id='C', thread_ts='1.0'))
        self.models, self.slack = Mock(), Mock()
        self.models.review.return_value = dict(passed=True, score=8.5, model='claude-sonnet-4-6')
        self.runtime = Runtime(self.config, models=self.models, slack=self.slack, catalog=Fetcher())
        self.runtime._medical = lambda _: {'passed': True}
        self.job = approved_job()
        self.job.update(id='article-test', theme={'slug': 'test'}, week='test', error=None)
        image = self.job['bundle']['images'][0]
        image['productId'] = 'p1'
        self.job['bundle']['article'].update(productIds=['p1'], content='新しい記事を公開しました。')
        self.job['bundle']['products'] = [dict(id='p1', name='商品', imageUrl=image['url'])]
        self.job['revision'] = fingerprint(self.job['bundle'])
        self.job['publication'].update(revision=self.job['revision'], readback=dict(verified=True, fingerprint=self.job['revision']))
        self.job['social']['revision'] = fingerprint(self.job['social']['proposal'])
        self.job['social']['review']['fingerprint'] = self.job['social']['revision']
        self.job['social']['approval']['revision'] = self.job['social']['revision']
        self.job['review'] = copy.deepcopy(self.job['social']['review'])
        self.old_revision = self.job['social']['revision']
        with self.runtime.ledger._tx() as db:
            self.runtime.ledger._put(db, self.job, 'fixture')
        self.rendered = copy.deepcopy(self.job['bundle'])
        manifest = {k: v for k, v in image.items() if k not in ('verified', 'productId')}
        manifest.update(width=1200, height=630, templateVersion='lake-sky-social-card-v2',
                        sources=[dict(productId='p1', sha256=image['sha256'])],
                        rendererEvidence=dict(contentHash='c' * 64, renderEngine='test', fontFamily='test', layout={},
                            displayText=dict(title='Approved', heading='Approved', productNames=['商品']),
                            sourceCrops=[dict(productId='p1', sha256=image['sha256'])]))
        self.rendered['article']['generationMeta'] = {'socialCard': manifest}
        self.rendered['images'].append(dict(manifest, role='social-card', verified=True))

    def tearDown(self):
        self.tmp.cleanup()

    def refresh(self, **kwargs):
        return self.runtime.refresh_social_images(self.job['id'], self.rendered,
            expected_social_revision=self.old_revision, **kwargs)

    def partial(self):
        folder = self.runtime.root / 'social-publications'
        folder.mkdir(mode=0o700)
        self.marker = folder / (self.old_revision + '.json')
        state = dict(revision=self.old_revision, proposalFingerprint=self.old_revision, account='123',
                     phase='mainread', pending=None, mainId='111',
                     uploads=[dict(sha256=self.job['bundle']['images'][0]['sha256'], mediaKey='3_333')])
        self.marker.write_text(json.dumps(state))
        self.marker.chmod(0o600)
        return dict(id='111', authorId='123', text=self.job['social']['proposal']['text'],
                    urls=[], mediaKeys=['3_333'], replyTo=None, textMatchesApproval=False)

    def test_hold_and_refresh_invalidate_old_requests_and_preserve_article_and_gemini(self):
        request = self.runtime.ledger.create_request(self.job['id'], 'social')
        held = self.runtime.hold_social_refresh(self.job['id'], expected_social_revision=self.old_revision)
        self.assertEqual(held['social']['approval'], self.job['social']['approval'])
        self.assertEqual(held['stage'], 'social_held')
        updated = self.refresh()
        self.assertEqual(updated['bundle'], self.job['bundle'])
        self.assertEqual(updated['publication'], self.job['publication'])
        self.assertEqual(updated['revision'], self.job['revision'])
        self.assertEqual(updated['stage'], 'social_review')
        self.assertIsNone(updated['social']['approval'])
        self.assertEqual(updated['socialHistory'][0]['social'], self.job['social'])
        self.assertEqual(updated['social']['proposal']['text'], self.job['social']['proposal']['text'])
        self.models.polish.assert_not_called()
        self.models.social.assert_not_called()
        self.models.review.assert_called_once()
        self.slack.deliver.assert_not_called()
        payload = json.dumps(self.models.review.call_args.args, ensure_ascii=False)
        self.assertNotIn('user_id', payload)
        self.assertNotIn('mainReadback', payload)
        self.assertNotIn('request_id', payload)
        self.assertTrue(self.models.review.call_args.args[1]['publicationReadback']['verified'])
        with self.runtime.ledger._tx() as db:
            saved = json.loads(db.execute('SELECT data FROM requests WHERE id=?', (request['request_id'],)).fetchone()[0])
        self.assertEqual(saved['status'], 'invalidated')
        publisher = SocialPublisher(dict(self.config, socialPostingEnabled=True), {}, client=Mock())
        with self.assertRaisesRegex(ValueError, 'social_approval_required'):
            publisher.publish(updated)
        publisher.client.assert_not_called()

    def test_partial_effect_archived_verbatim_no_reply_and_old_flag_ignored(self):
        main = self.partial()
        original = self.marker.read_bytes()
        self.runtime.hold_social_refresh(self.job['id'], expected_social_revision=self.old_revision)
        updated = self.refresh(prior_main_readback=main)
        self.assertEqual(self.marker.read_bytes(), original)
        history = updated['socialHistory'][0]
        self.assertEqual(history['mainReadback'], main)
        self.assertEqual(history['journal'], json.loads(original))
        self.assertNotIn('publication', history['social'])
        self.assertEqual(updated['social']['proposal']['approvalNotice'], REFRESH_NOTICE)
        self.assertEqual(updated['social']['proposal']['priorPostUrl'], 'https://x.com/i/web/status/111')
        payload = json.dumps(self.models.review.call_args.args)
        self.assertNotIn('textMatchesApproval', payload)
        self.assertNotIn('uploads', payload)
        self.assertNotIn('approval', payload.replace('approvalNotice', 'notice'))

    def test_partial_effect_cannot_be_silently_replaced(self):
        self.partial()
        with self.assertRaisesRegex(ValueError, 'held'):
            self.refresh()
        current = self.runtime.ledger.get_job(self.job['id'])
        self.assertEqual(current['social'], self.job['social'])
        proposal = dict(self.job['social']['proposal'], text='changed')
        review = dict(self.job['social']['review'], fingerprint=fingerprint(proposal))
        with self.assertRaisesRegex(ValueError, 'explicit reconciliation'):
            self.runtime.ledger.record_social(self.job['id'], proposal, review)

    def test_mismatched_readback_rejected_and_journal_unchanged(self):
        main = self.partial()
        original = self.marker.read_bytes()
        self.runtime.hold_social_refresh(self.job['id'], expected_social_revision=self.old_revision)
        for key, value in [('authorId', '999'), ('text', 'changed'), ('mediaKeys', ['wrong']), ('id', '999')]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'existing main'):
                self.refresh(prior_main_readback=dict(main, **{key: value}))
        self.assertEqual(self.marker.read_bytes(), original)
        self.assertEqual(self.runtime.ledger.get_job(self.job['id'])['social'], self.job['social'])

    def test_bundle_mutation_is_rejected_before_model(self):
        self.rendered['article']['content'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'changed_article_or_sources'):
            self.refresh()
        self.models.review.assert_not_called()

    def test_source_manifest_title_crop_and_revision_fail_closed(self):
        updated = self.refresh()
        proposal = updated['social']['proposal']
        for field in ('articleRevision', 'source', 'title', 'crop', 'card'):
            bad = copy.deepcopy(proposal)
            manifest = bad['supplementalCard']['manifest']
            if field == 'articleRevision':
                bad['supplementalCard']['articleRevision'] = '0' * 64
            elif field == 'source':
                manifest['sources'][0]['sha256'] = '0' * 64
            elif field == 'title':
                manifest['rendererEvidence']['displayText']['title'] = 'Changed'
            elif field == 'crop':
                manifest['rendererEvidence']['sourceCrops'][0]['sha256'] = '0' * 64
            else:
                bad['images'][0]['sha256'] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                valid_social_images(self.job, bad)

    def test_failed_or_non_claude_review_cannot_record(self):
        for final in (dict(passed=False, score=8.5, model='claude-sonnet-4-6'),
                      dict(passed=True, score=8.5, model='gemini-3.8-flash')):
            self.models.review.return_value = final
            with self.assertRaises(ValueError):
                self.refresh()
            self.assertEqual(self.runtime.ledger.get_job(self.job['id'])['social'], self.job['social'])

    def test_stale_revision_and_enabled_hold_rejected(self):
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.runtime.refresh_social_images(self.job['id'], self.rendered, expected_social_revision='old')
        self.config['socialPostingEnabled'] = True
        with self.assertRaisesRegex(ValueError, 'posting_hold'):
            self.runtime.hold_social_refresh(self.job['id'], expected_social_revision=self.old_revision)

    def test_new_approval_can_validate_supplement_without_public_og(self):
        updated = self.refresh()
        updated['stage'] = 'social_approved'
        updated['social']['approval'] = dict(self.job['social']['approval'], revision=updated['social']['revision'])
        publisher = SocialPublisher(dict(self.config, socialPostingEnabled=True), {})
        self.assertEqual(publisher._validate(updated)[1], updated['social']['revision'])
        self.assertNotIn('socialCard', updated['publication']['readback'])
        self.assertNotIn('socialCard', updated['bundle']['article'].get('generationMeta', {}))

    def test_real_new_approval_required_and_shared_ledger_accepts_exact_media(self):
        updated = self.refresh()
        request = self.runtime.ledger.create_request(self.job['id'], 'social')
        scope = self.config['slack']
        self.runtime.ledger.mark_delivered(request['request_id'], scope, '2.0')
        event = dict(request['payload'], **scope, event_id='fresh-event',
                     action_id='camp_review_approve', card_ts='2.0')
        self.runtime.ledger.decide(event, scope)
        approved = self.runtime.ledger.get_job(self.job['id'])
        x = XFake()
        publisher = SocialPublisher(dict(self.config, socialPostingEnabled=True), {}, client=x, fetcher=Fetcher())
        evidence = publisher.publish(approved)
        posted = self.runtime.ledger.record_social_publication(self.job['id'], approved['social']['revision'], evidence)
        self.assertEqual(posted['stage'], 'social_posted')
        self.assertEqual(posted['bundle'], self.job['bundle'])
        self.assertEqual(posted['publication'], self.job['publication'])
        self.assertEqual(posted['socialHistory'], updated['socialHistory'])
        self.assertEqual([action for action, _ in x.calls].count('maincreate'), 1)

    def test_image_only_transition_rejects_changed_text_reply_target_or_polish(self):
        updated = self.refresh()
        for field in ('text', 'replyText', 'targetAccountId', 'polish'):
            proposal = copy.deepcopy(updated['social']['proposal'])
            review = copy.deepcopy(updated['social']['review'])
            if field == 'polish':
                review['polish'] = dict(model='gemini-3.8-flash', validated=True, fabricated=True)
            else:
                proposal[field] = 'changed'
            with self.subTest(field=field), self.assertRaises(ValueError):
                valid_image_refresh(self.job['social'], proposal, review)

    def test_slack_approval_shows_prior_post_notice_and_link(self):
        main = self.partial()
        self.runtime.hold_social_refresh(self.job['id'], expected_social_revision=self.old_revision)
        updated = self.refresh(prior_main_readback=main)
        slack = Slack(dict(self.config, socialPostingEnabled=True))
        slack.post = Mock(return_value={'verified': True, 'message_ts': '2.0'})
        request = dict(kind='social', request_id='r', article_id=self.job['id'], manifest_hash=updated['social']['revision'], nonce='n')
        slack.deliver(updated, request)
        text = slack.post.call_args.args[0]
        self.assertIn(REFRESH_NOTICE, text)
        self.assertIn('https://x.com/i/web/status/111', text)
        self.assertNotIn('復旧待ち', text)


if __name__ == '__main__':
    unittest.main()
