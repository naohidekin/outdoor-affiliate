"""Bounded second supplemental apparel batch; synthetic fixtures only."""
from datetime import datetime, timezone, timedelta
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from apparel_identity import apparel_contract
from ledger import Ledger, fingerprint
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


def source_projection(value):
    projected = [{key: value.get(key) for key in
                  ('id', 'name', 'brand', 'categoryId', 'specs', 'imageUrl',
                   'affiliateUrl', 'amazonUrl')}]
    projected[0]['apparelContract'] = apparel_contract(value)
    return projected


def name_correction_receipt(article_id, old_source, new_source):
    return {
        'kind': 'supplemental_source_name_correction_v1',
        'articleId': article_id,
        'batchId': NEW,
        'oldSource': old_source,
        'newSource': new_source,
        'sourceProof': {
            'verified': True,
            'kind': 'manufacturer_primary_name_correction',
            'productId': 'apparel-montbell-1107654',
            'canonicalName': "モンベル スーパーメリノウール M.W. ラウンドネックシャツ Men's",
            'model': '1107654',
            'gender': "Men's",
            'sourceUrl': 'https://webshop.montbell.jp/goods/disp.php?product_id=1107654',
            'sourceSha256': 'a' * 64,
            'nameCorrectionReceiptSha256': 'b' * 64,
        },
    }


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

    def _name_correction_job(self, *, batch=NEW):
        old_product = product('apparel-montbell-1107654', '1107654')
        old_product['name'] = 'Malformed manufacturer title plus navigation'
        old_product['specs']['gender'] = "Men's"
        old_source = source_projection(old_product)
        corrected = copy.deepcopy(old_product)
        corrected['name'] = ("モンベル スーパーメリノウール M.W. "
                             "ラウンドネックシャツ Men's")
        new_source = source_projection(corrected)
        job_theme = theme('merino-name-correction')
        job_theme['productIds'] = [old_product['id']]
        job = self.ledger.create_supplemental_candidate(
            job_theme, batch, 1, fingerprint(old_source),
            social_eligible_period=SOCIAL_PERIOD, now=NOW)
        job = self.ledger.set_stage(job['id'], 'error', {'reason': 'source name malformed'})
        return job, old_source, new_source

    def test_name_correction_rebinds_only_untouched_new_batch_source(self):
        job, old_source, new_source = self._name_correction_job()
        before = copy.deepcopy(job)
        receipt = name_correction_receipt(job['id'], old_source, new_source)

        changed = self.ledger.rebind_supplemental_source_for_name_correction(
            job['id'], fingerprint(old_source), fingerprint(new_source), receipt)

        self.assertEqual(fingerprint(new_source), changed['sourceBinding'])
        self.assertEqual([{'kind': receipt['kind'],
                           'oldSourceBinding': fingerprint(old_source),
                           'newSourceBinding': fingerprint(new_source),
                           'receiptFingerprint': fingerprint(receipt)}],
                         changed['sourceBindingHistory'])
        ignored = {'sourceBinding', 'sourceBindingHistory', 'updated_at'}
        self.assertEqual({key: value for key, value in before.items() if key not in ignored},
                         {key: value for key, value in changed.items() if key not in ignored})
        with sqlite3.connect(self.ledger.db_path) as db:
            events = [json.loads(row[0]) for row in db.execute(
                "SELECT data FROM events WHERE job_id=? AND kind='name_source_correction'",
                (job['id'],))]
        self.assertEqual(1, len(events))
        self.assertEqual(fingerprint(old_source), events[0]['sourceBindingHistory'][0]['oldSourceBinding'])

    def test_name_correction_rebind_rejects_wrong_scope_or_proof(self):
        cases = ('old_batch', 'changed_product_field', 'binding_conflict',
                 'unverified_proof', 'request_exists')
        for case in cases:
            with self.subTest(case=case):
                root = Path(self.tmp.name) / case
                ledger = Ledger(root, 'owner')
                old_product = product('apparel-montbell-1107654', '1107654')
                old_product.update(name='Malformed manufacturer title plus navigation')
                old_product['specs']['gender'] = "Men's"
                old_source = source_projection(old_product)
                corrected = copy.deepcopy(old_product)
                corrected['name'] = ("モンベル スーパーメリノウール M.W. "
                                     "ラウンドネックシャツ Men's")
                new_source = source_projection(corrected)
                batch = OLD if case == 'old_batch' else NEW
                job_theme = theme('merino-' + case)
                job_theme['productIds'] = [old_product['id']]
                job = ledger.create_supplemental_candidate(
                    job_theme, batch, 1, fingerprint(old_source),
                    social_eligible_period=SOCIAL_PERIOD, now=NOW)
                job = ledger.set_stage(job['id'], 'error', {'reason': 'source name malformed'})
                receipt = name_correction_receipt(job['id'], old_source, new_source)
                expected = fingerprint(old_source)
                if case == 'changed_product_field':
                    receipt['newSource'][0]['brand'] = 'changed-brand'
                elif case == 'binding_conflict':
                    expected = 'c' * 64
                elif case == 'unverified_proof':
                    receipt['sourceProof']['verified'] = False
                elif case == 'request_exists':
                    with sqlite3.connect(ledger.db_path) as db:
                        db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                                   ('request', job['id'], 'article', '{}'))
                with self.assertRaises(ValueError):
                    ledger.rebind_supplemental_source_for_name_correction(
                        job['id'], expected, fingerprint(new_source), receipt)


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

    def test_new_batch_internal_link_failure_uses_one_existing_corrected_attempt(self):
        from models import ModelError
        value = manifest()
        catalog = self._catalog(value)
        first = resolve_batch(value, catalog, [], NOW)['slots'][0]
        job = self.runtime.ledger.create_supplemental_candidate(
            first['theme'], NEW, 1, first['sourceBinding'],
            social_eligible_period=SOCIAL_PERIOD, now=NOW)
        inputs = {'theme': job['theme'], 'dependencies': {'implementation': 'old'},
                  'schemaVersion': 1}
        with self.assertRaises(ModelError):
            self.runtime.stage_journal.run(job['id'], 'draft', inputs,
                lambda: (_ for _ in ()).throw(
                    ModelError('Unknown or self internal article link')))
        key = self.runtime.stage_journal.key(job['id'], 'draft', inputs)
        self.runtime.ledger.set_stage(job['id'], 'error',
            {'reason': 'Unknown or self internal article link'})
        records = self.runtime.stage_journal.status(job_id=job['id'], stage='draft')['records']
        self.runtime.validate_corrected_retry(
            self.runtime.ledger.get_job(job['id']), 'draft', key, records)
        usage_before = copy.deepcopy(self.models.usage)
        with self.assertRaisesRegex(ValueError, 'local_contract_revalidation_required'):
            self.runtime.retry_corrected_stage(job['id'], 'draft', key)
        self.assertEqual(usage_before, self.models.usage)
        corrected = copy.deepcopy(inputs)
        corrected['dependencies']['existingArticles'] = [{'slug': 'related-published'}]
        result = self.runtime.stage_journal.retry_corrected_failed(
            job['id'], 'draft', key, corrected,
            lambda: {'validated': True, 'noNewModelCall': True})
        self.assertEqual({'validated': True, 'noNewModelCall': True}, result)
        records = self.runtime.stage_journal.status(job_id=job['id'], stage='draft')['records']
        self.assertEqual([('failed', 1, 2), ('succeeded', 2, 2)],
                         sorted((record['status'], record['attempts'], record['maxAttempts'])
                                for record in records))
        self.assertEqual(key, next(record for record in records
                                   if record['attempts'] == 2)['predecessorKey'])
        self.assertEqual(usage_before, self.models.usage)
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            self.assertEqual(0, db.execute(
                'SELECT count(*) FROM model_budget_reservations').fetchone()[0])

    def test_corrected_error_allowlists_remain_batch_specific(self):
        record = {'stageKey': 'k', 'jobId': 'job', 'stage': 'draft',
                  'status': 'failed', 'attempts': 1, 'maxAttempts': 2}
        base = {'id': 'job', 'kind': 'supplemental_article', 'batchCallCap': 96,
                'stage': 'error', 'bundle': None, 'approval': None, 'publication': None}
        for batch, reason in (
                (NEW, 'Article length outside existing SKILL limits'),
                (OLD, 'Unknown or self internal article link')):
            with self.subTest(batch=batch, reason=reason), self.assertRaises(ValueError):
                self.runtime.validate_corrected_retry(
                    dict(base, batchId=batch, error={'reason': reason}),
                    'draft', 'k', [record])


if __name__ == '__main__':
    unittest.main()
