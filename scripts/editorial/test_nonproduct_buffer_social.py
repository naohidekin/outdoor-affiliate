"""Offline contracts for reusing one verified owned nonproduct eyecatch in Buffer SNS."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import Mock

from buffer_publisher import BufferPublisher
from ledger import canonical, fingerprint, owned_article_social_image, valid_social_images
from runtime import atomic
import test_runtime


class NonproductBufferSocialTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config.update(
            executionPolicy={'mode': 'deterministic', 'suspended': False,
                             'exceptions': {'autoAI': False}},
            socialGenerationEnabled=True,
            socialReviewEnabled=True,
            socialPostingEnabled=False,
            bufferPostingEnabled=False,
            bufferSocialStartPeriod='2026-11-20',
            buffer={'organizationId': 'org_verified', 'channelId': 'channel_verified',
                    'xAccountId': '123', 'schedulingPolicy': 'next_available_slot',
                    'maxOutstanding': 3, 'duePollIntervalSeconds': 1800,
                    'maxDuePolls': 3})

    def tearDown(self):
        test_runtime.RuntimeTests.tearDown(self)

    def approve(self, job, user='U'):
        return test_runtime.RuntimeTests.approve(self, job, user)

    def _save(self, job):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            db.execute('UPDATE jobs SET data=? WHERE id=?',
                       (json.dumps(job, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':')), job['id']))

    def _job(self):
        job = test_runtime.RuntimeTests.published_job(self)
        bundle = test_runtime.nonproduct_bundle()
        revision = fingerprint(bundle)
        context = bundle['article']['generationMeta']['editorialContext']
        image = bundle['images'][0]
        route = {'status': 'not_applicable', 'measured': False,
                 'sponsoredCtaCount': 0, 'reason': 'verified_nonproduct_article',
                 'verifiedBy': 'deterministic_contract_v1'}
        job.update(week='2026-11-20', stage='published', bundle=bundle,
                   revision=revision, social=None)
        job['publication'] = {
            'verified': True, 'revision': revision,
            'url': 'https://camp-gear-lab.com/articles/' + bundle['article']['slug'],
            'readback': {
                'verified': True, 'fingerprint': revision, 'productIds': [],
                'editorialContext': copy.deepcopy(context),
                'commercialRoute': route,
                'imageProofs': [{key: image[key] for key in
                                 ('id', 'url', 'sha256', 'size', 'contentType')}],
            },
        }
        self._save(job)
        key = fingerprint({'id': job['id'], 'revision': revision,
                           'publication': job['publication']})
        atomic(self.runtime.root / 'post-publication-audits' / (key + '.json'), {
            'schemaVersion': 1, 'status': 'success', 'id': job['id'],
            'revision': revision, 'auditKey': key, 'publication': job['publication'],
            'attempts': [], 'startedAt': '2026-11-20T10:00:00+09:00',
            'completedAt': '2026-11-20T10:00:00+09:00', 'nextAttemptAt': None,
            'action': None, 'result': {'passed': True, 'status': 'passed', 'issues': [],
                'checks': [
                    {'name': 'public_title', 'status': 'passed'},
                    {'name': 'approved_body', 'status': 'passed'},
                    {'name': 'desktop.merchant', 'status': 'not_applicable',
                     'reason': 'verified_nonproduct_article'},
                    {'name': 'mobile.merchant', 'status': 'not_applicable',
                     'reason': 'verified_nonproduct_article'},
                ]},
        })
        return self.runtime.ledger.get_job(job['id'])

    def test_generation_uses_exact_owned_eyecatch_without_mutating_article(self):
        job = self._job()
        before_bundle = copy.deepcopy(job['bundle'])
        before_publication = canonical(job['publication']).encode()
        before_revision = job['revision']

        self.runtime.make_social(job)

        current = self.runtime.ledger.get_job(job['id'])
        proposal = current['social']['proposal']
        image, binding = owned_article_social_image(current)
        self.assertEqual([image], proposal['images'])
        self.assertEqual(binding, proposal['supplementalArticleImage'])
        self.assertEqual(before_bundle, current['bundle'])
        self.assertEqual(before_publication, canonical(current['publication']).encode())
        self.assertEqual(before_revision, current['revision'])
        self.assertNotIn('socialCard', current['bundle']['article']['generationMeta'])
        self.assertEqual('eyecatch', proposal['images'][0]['role'])
        valid_social_images(current, proposal)

    def test_buffer_requires_new_owner_approval_and_accepts_exact_binding(self):
        job = self._job()
        self.runtime.make_social(job)
        current = self.runtime.ledger.get_job(job['id'])
        publisher = BufferPublisher(self.config, {}, client=Mock())
        with self.assertRaisesRegex(ValueError, 'social_approval_required'):
            publisher._validate(current)

        self.approve(current)
        self.assertEqual(1, self.runtime.consume())
        approved = self.runtime.ledger.get_job(current['id'])
        social = approved['social']
        self.assertEqual('social_approved', approved['stage'])
        proposal, revision = publisher._validate(approved)
        self.assertEqual(social['proposal'], proposal)
        self.assertEqual(social['revision'], revision)

    def test_binding_or_nonproduct_evidence_change_fails_closed(self):
        job = self._job()
        self.runtime.make_social(job)
        current = self.runtime.ledger.get_job(job['id'])
        proposal = current['social']['proposal']
        mutations = [
            lambda value: value['supplementalArticleImage']['imageSha256s'].__setitem__(0, '0' * 64),
            lambda value: value['images'][0].update(role='social-card'),
            lambda value: value['images'][0].update(ownership='merchant'),
            lambda value: value['images'][0].update(depictsRealProduct=True),
            lambda value: value['images'].append(copy.deepcopy(value['images'][0])),
            lambda value: value.update(deliveryMode='manual'),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(proposal)
            mutation(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                valid_social_images(current, changed)

        changed_job = copy.deepcopy(current)
        changed_job['publication']['readback']['imageProofs'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'owned article image evidence invalid'):
            owned_article_social_image(changed_job)

        for url in ('https://other.example/articles/tent-dry',
                    'https://camp-gear-lab.com:443/articles/tent-dry',
                    'https://camp-gear-lab.com/articles/tent-dry?preview=1',
                    'https://user@camp-gear-lab.com/articles/tent-dry'):
            changed_job = copy.deepcopy(current)
            changed_job['publication']['url'] = url
            with self.subTest(url=url), self.assertRaisesRegex(
                    ValueError, 'owned article image publication binding invalid'):
                owned_article_social_image(changed_job)


if __name__ == '__main__':
    unittest.main()
