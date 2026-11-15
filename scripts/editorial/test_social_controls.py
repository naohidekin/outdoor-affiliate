"""Article progress must not consume or wait for independently paused SNS work."""
import copy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dispatcher import DeterministicDispatcher, social_feature_enabled
from production_schedule import ProductionSchedule, JST
import test_runtime


class SocialControlTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown
    approve = test_runtime.RuntimeTests.approve

    def test_paused_social_does_not_starve_next_friday_articles(self):
        config = dict(self.config, executionPolicy={'mode': 'deterministic', 'suspended': False},
                      generationEnabled=True, socialPostingEnabled=False, socialReviewEnabled=True)
        schedule = ProductionSchedule(dict(weekday=4, hour=9, effectiveFrom='2026-11-13',
                                          initialProductionAt='2026-11-08T00:00:00+09:00'))
        for stage in ('social_review', 'social_approved', 'published'):
            jobs = [{'id': 'old', 'stage': stage, 'kind': 'article', 'week': '2026-11-13',
                     'publication': {'verified': True},
                     'social': None if stage == 'published' else {'proposal': {'deliveryMode': 'auto_x'}}}]
            runtime = SimpleNamespace(config=config, root=self.runtime.root,
                ledger=SimpleNamespace(list_jobs=lambda: copy.deepcopy(jobs), production_schedule=schedule))
            dispatcher = DeterministicDispatcher(runtime)
            with patch.object(dispatcher, '_state', return_value=({}, [])), \
                    patch.object(dispatcher, '_delivery_needed', return_value=(False, None)):
                result = dispatcher.plan(datetime(2026, 11, 20, 9, tzinfo=JST))
            self.assertEqual([{'kind': 'produce', 'jobId': None}], result['actions'], stage)

    def test_paused_social_review_does_not_redeliver_cards(self):
        self.config.update(executionPolicy={'mode': 'deterministic', 'suspended': False},
                           generationEnabled=False, socialReviewEnabled=False)
        job = {'id': 'pending-social', 'stage': 'social_review', 'publication': {'verified': True}}
        dispatcher = DeterministicDispatcher(self.runtime)
        with patch.object(self.runtime.ledger, 'list_jobs', return_value=[job]), \
                patch.object(dispatcher, '_delivery_needed', side_effect=AssertionError('social delivery')):
            self.assertEqual([], dispatcher.plan(datetime.now(JST))['actions'])
        with patch.object(self.slack, 'deliver') as send:
            with self.assertRaisesRegex(ValueError, 'social_review_disabled'):
                self.runtime.deliver('pending-social', 'social')
            send.assert_not_called()

    def test_article_wait_still_blocks_new_period_when_publication_disabled(self):
        self.config.update(executionPolicy={'mode': 'deterministic', 'suspended': False},
                           generationEnabled=True, publicationEnabled=False)
        job = {'id': 'article', 'stage': 'approved', 'publication': None}
        with patch.object(self.runtime.ledger, 'list_jobs', return_value=[job]):
            self.assertEqual([], DeterministicDispatcher(self.runtime).plan(
                datetime.now(JST))['actions'])

    def test_social_generation_requires_its_own_explicit_deterministic_flag(self):
        self.config['executionPolicy'] = {'mode': 'deterministic', 'suspended': False}
        with patch.object(self.models, 'social') as generate:
            with self.assertRaisesRegex(ValueError, 'social_generation_disabled'):
                self.runtime.make_social({})
            generate.assert_not_called()
        self.assertFalse(social_feature_enabled(self.config, 'socialGenerationEnabled'))
        self.config['socialGenerationEnabled'] = True
        self.assertTrue(social_feature_enabled(self.config, 'socialGenerationEnabled'))
        self.config['socialGenerationEnabled'] = 'true'
        with self.assertRaises(ValueError):
            social_feature_enabled(self.config, 'socialGenerationEnabled')

    def test_article_consumer_preserves_signed_social_event_bytes(self):
        published = test_runtime.RuntimeTests.published_job(self)
        self.runtime.make_social(published)
        social_job = self.runtime.ledger.get_job(published['id'])
        self.approve(social_job)
        spool = Path(self.config['spoolDir'])
        social_path = next(spool.glob('*.json'))
        original = social_path.read_bytes()
        self.config['generationEnabled'] = True
        self.runtime.produce(limit=1)
        article = next(j for j in self.runtime.ledger.list_jobs() if j['stage'] == 'review')
        self.approve(article)
        self.config.update(executionPolicy={'mode': 'deterministic', 'suspended': False},
                           socialReviewEnabled=False)
        self.assertEqual(1, self.runtime.consume())
        self.assertEqual(original, social_path.read_bytes())
        self.assertEqual('social_review', self.runtime.ledger.get_job(published['id'])['stage'])
        self.assertIsNone(self.runtime.ledger.get_job(published['id'])['social']['approval'])
        self.assertEqual('approved', self.runtime.ledger.get_job(article['id'])['stage'])
        self.config['socialReviewEnabled'] = True
        self.assertEqual(1, self.runtime.consume())
        self.assertEqual('social_approved', self.runtime.ledger.get_job(published['id'])['stage'])


if __name__ == '__main__':
    unittest.main()
