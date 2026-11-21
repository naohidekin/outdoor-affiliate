"""Bounded second supplemental apparel batch; synthetic fixtures only."""
from datetime import datetime, timezone, timedelta
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ledger import Ledger
from model_budget import DEFAULTS, ModelBudget
from production_schedule import ProductionSchedule
from supplemental_topics import approved_batch_binding, resolve_batch, validate_batch
import test_runtime


JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 22, 10, tzinfo=JST)
OLD = 'apparel-2026-11-16'
NEW = 'apparel-2026-11-22'
SOCIAL_PERIOD = '2026-11-20'


def product(product_id, model='1101493'):
    return {'id': product_id, 'name': 'Verified apparel', 'brand': 'mont-bell',
            'categoryId': 'wear', 'imageUrl': 'https://img.example/item.png',
            'affiliateUrl': 'https://affiliate.example/item',
            'amazonUrl': 'https://amazon.example/item',
            'specs': {'apparelClass': 'fleece', 'model': model, 'gender': 'unisex',
                      'fabric': 'polyester', 'weight': '300g',
                      'optionState': 'selectable'}}


def manifest(batch_id=NEW, social_period=SOCIAL_PERIOD):
    slots = []
    for slot in range(1, 4):
        slots.append({'slot': slot, 'productIds': [f'apparel-new-{slot}'],
                      'slug': f'new-wear-{slot}', 'title': f'New wear {slot}',
                      'categoryId': 'wear', 'query': f'wear query {slot}',
                      'selectionReason': 'owner authorized verified apparel comparison'})
    return {'schemaVersion': 1, 'batchId': batch_id,
            'kind': 'supplemental_article_batch',
            'notBefore': '2026-11-22T09:00:00+09:00',
            'socialEligiblePeriod': social_period, 'maxArticles': 3,
            'batchCallCap': 96, 'status': 'awaiting_verified_source',
            'apparelPolicy': {'version': 1,
                'requirements': ['strict apparel identity'], 'missingEvidence': 'hold',
                'researchScope': {'classes': ['fleece', 'base-layer', 'down'],
                                  'comparison': ['cross-brand', 'same-position'],
                                  'claims': 'verified evidence only'}},
            'slots': slots}


def theme(slug):
    return {'slug': slug, 'title': slug, 'categoryId': 'wear',
            'query': slug, 'selectionReason': 'verified owner-authorized batch',
            'productIds': ['apparel-' + slug]}


class Supplemental20261122Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        self.ledger = Ledger(self.root, 'owner')

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_two_approved_batches_share_exact_bounds(self):
        for batch_id in (OLD, NEW):
            self.assertEqual({'batchId': batch_id, 'maxArticles': 3,
                              'batchCallCap': 96,
                              'socialEligiblePeriod': SOCIAL_PERIOD},
                             approved_batch_binding(batch_id))
        self.assertEqual(NEW, validate_batch(manifest())['batchId'])
        for bad in ('apparel-2026-11-23', 'outdoor-arbitrary'):
            with self.subTest(batch=bad), self.assertRaisesRegex(
                    ValueError, 'invalid supplemental bounds'):
                validate_batch(manifest(bad))
        malformed = manifest()
        malformed['batchId'] = []
        with self.assertRaisesRegex(ValueError, 'invalid supplemental bounds'):
            validate_batch(malformed)
        with self.assertRaisesRegex(ValueError, 'invalid supplemental bounds'):
            validate_batch(manifest(NEW, '2026-11-27'))

    def test_new_manifest_resolves_with_existing_strict_apparel_sources(self):
        value = manifest()
        catalog = {'products': [product(slot['productIds'][0], f'110149{slot["slot"]}')
                                for slot in value['slots']], 'articles': []}
        result = resolve_batch(value, catalog, [], NOW)
        self.assertEqual(('ready', 3, NEW),
                         (result['status'], result['readyCount'], result['batchId']))

    def test_old_job_is_unchanged_and_same_slot_is_independent_across_batches(self):
        old = self.ledger.create_supplemental_candidate(
            theme('old-one'), OLD, 1, 'a' * 64,
            social_eligible_period=SOCIAL_PERIOD, now=NOW)
        self.ledger.set_stage(old['id'], 'rejected')
        old_before = copy.deepcopy(self.ledger.get_job(old['id']))
        new = self.ledger.create_supplemental_candidate(
            theme('new-one'), NEW, 1, 'b' * 64,
            social_eligible_period=SOCIAL_PERIOD, now=NOW)
        self.assertEqual((NEW, 1, 96),
                         (new['batchId'], new['batchSlot'], new['batchCallCap']))
        self.assertEqual(old_before, self.ledger.get_job(old['id']))
        with self.assertRaisesRegex(ValueError, 'supplemental slot conflict'):
            self.ledger.create_supplemental_candidate(
                theme('new-one'), NEW, 1, 'c' * 64,
                social_eligible_period=SOCIAL_PERIOD, now=NOW)

    def test_wrong_period_and_global_pending_cap_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'invalid supplemental batch slot'):
            self.ledger.create_supplemental_candidate(
                theme('arbitrary'), 'apparel-2026-11-23', 1, '0' * 64,
                social_eligible_period=SOCIAL_PERIOD, now=NOW)
        with self.assertRaisesRegex(ValueError, 'invalid supplemental social period'):
            self.ledger.create_supplemental_candidate(
                theme('wrong-period'), NEW, 1, 'a' * 64,
                social_eligible_period='2026-11-27', now=NOW)
        self.ledger.create_supplemental_candidate(
            theme('old-pending'), OLD, 1, 'b' * 64,
            social_eligible_period=SOCIAL_PERIOD, now=NOW)
        for slot in (1, 2):
            self.ledger.create_supplemental_candidate(
                theme(f'new-{slot}'), NEW, slot, str(slot) * 64,
                social_eligible_period=SOCIAL_PERIOD, now=NOW)
        with self.assertRaisesRegex(ValueError, 'pending cap reached'):
            self.ledger.create_supplemental_candidate(
                theme('new-3'), NEW, 3, '3' * 64,
                social_eligible_period=SOCIAL_PERIOD, now=NOW)

    def test_model_budget_keeps_32_article_128_period_and_separate_96_batches(self):
        self.assertEqual((32, 128),
                         (DEFAULTS['article']['calls'], DEFAULTS['period']['calls']))
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            for batch_id, article_id in ((OLD, 'old-budget'), (NEW, 'new-budget')):
                job = {'id': article_id, 'kind': 'supplemental_article',
                       'batchId': batch_id, 'batchCallCap': 96}
                db.execute('INSERT INTO jobs VALUES (?,?)',
                           (article_id, json.dumps(job, separators=(',', ':'))))
        budget = ModelBudget(self.root, ProductionSchedule())
        with sqlite3.connect(self.root / 'ledger.sqlite3') as db:
            old = budget._batch_call_scope(db, {'articleId': 'old-budget'})
            new = budget._batch_call_scope(db, {'articleId': 'new-budget'})
        self.assertEqual({'id': OLD, 'cap': 96, 'calls': 0}, old)
        self.assertEqual({'id': NEW, 'cap': 96, 'calls': 0}, new)


class SupplementalRuntimeBatchIsolationTests(unittest.TestCase):
    def setUp(self):
        test_runtime.RuntimeTests.setUp(self)
        self.config['supplementalApparelEnabled'] = True

    def tearDown(self):
        test_runtime.RuntimeTests.tearDown(self)

    def _catalog(self, value):
        first = value['slots'][0]
        return {'products': [product(first['productIds'][0])], 'articles': []}

    def test_old_batch_title_or_query_blocks_new_batch_even_with_new_slug(self):
        value = manifest()
        old_theme = theme('old-unique-slug')
        old_theme.update(title=value['slots'][0]['title'], query=value['slots'][0]['query'])
        old = self.runtime.ledger.create_supplemental_candidate(
            old_theme, OLD, 1, 'a' * 64,
            social_eligible_period=SOCIAL_PERIOD, now=NOW)
        self.runtime.ledger.set_stage(old['id'], 'rejected')
        with patch.object(self.runtime, '_supplemental_manifest', return_value=value), \
                patch.object(self.runtime.catalog, 'catalog', return_value=self._catalog(value)), \
                patch.object(self.runtime, '_make_article') as make:
            result = self.runtime.produce_supplemental(now=NOW)
        make.assert_not_called()
        self.assertEqual('source_hold', result['status'])
        marker = json.loads((self.runtime.root / 'supplemental-batches'
                             / f'{NEW}.json').read_text())
        self.assertEqual('duplicate_theme', marker['slots'][0]['reason'])

    def test_current_batch_candidate_does_not_conflict_with_its_own_theme(self):
        value = manifest()
        catalog = self._catalog(value)
        first = resolve_batch(value, catalog, [], NOW)['slots'][0]
        job = self.runtime.ledger.create_supplemental_candidate(
            first['theme'], NEW, 1, first['sourceBinding'],
            social_eligible_period=SOCIAL_PERIOD, now=NOW)
        with patch.object(self.runtime, '_supplemental_manifest', return_value=value), \
                patch.object(self.runtime.catalog, 'catalog', return_value=catalog), \
                patch.object(self.runtime, '_make_article') as make:
            result = self.runtime.produce_supplemental(now=NOW)
        make.assert_called_once_with(job, catalog)
        self.assertEqual([{'id': job['id'], 'status': 'awaiting_approval'}],
                         result['articles'])


if __name__ == '__main__':
    unittest.main()
