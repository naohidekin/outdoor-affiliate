from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import tempfile
import unittest

from supplemental_topics import load_batch, resolve_batch


JST = timezone(timedelta(hours=9))


def product(id):
    return {
        'id': id, 'name': 'Montbell Sample', 'brand': 'mont-bell',
        'categoryId': 'wear', 'imageUrl': 'https://img.example/item.png',
        'affiliateUrl': 'https://affiliate.example/item',
        'amazonUrl': 'https://amazon.example/item',
        'specs': {'apparelClass': 'down', 'model': '1101493', 'gender': 'unisex',
                  'fabric': 'nylon', 'weight': '300g', 'optionState': 'selectable'},
    }


def manifest():
    value = {
        'schemaVersion': 1, 'batchId': 'apparel-2026-11-16',
        'kind': 'supplemental_article_batch',
        'notBefore': '2026-11-16T09:00:00+09:00',
        'socialEligiblePeriod': '2026-11-20', 'maxArticles': 3,
        'batchCallCap': 96, 'status': 'awaiting_verified_source',
        'apparelPolicy': {'version': 1, 'requirements': ['strict apparel identity'],
                          'missingEvidence': 'hold', 'researchScope': {
                              'classes': ['down', 'base-layer', 'fleece'],
                              'comparison': ['cross-brand', 'same-position'],
                              'claims': 'verified evidence only'}},
        'slots': [
            {'slot': n, 'productIds': [f'apparel-montbell-{code}'],
             'slug': None, 'title': None, 'categoryId': None,
             'query': None, 'selectionReason': None}
            for n, code in enumerate(('1101493', '1107704', '1114881'), 1)
        ],
    }
    return value


class SupplementalTopicsTests(unittest.TestCase):
    def test_not_due_does_not_require_catalog(self):
        value = resolve_batch(manifest(), None, [], datetime(2026, 11, 16, 8, 59, tzinfo=JST))
        self.assertEqual('not_due', value['status'])

    def test_slots_resolve_independently_and_bind_exact_live_source(self):
        value = manifest()
        value['slots'][0].update(slug='warm-down', title='Warm down', categoryId='wear',
                                 query='winter down', selectionReason='verified winter layer')
        source = product('apparel-montbell-1101493')
        result = resolve_batch(value, {'products': [source], 'articles': []}, [],
                               datetime(2026, 11, 16, 9, tzinfo=JST))
        self.assertEqual(['ready', 'source_hold', 'source_hold'],
                         [slot['status'] for slot in result['slots']])
        self.assertEqual([source['id']], result['slots'][0]['theme']['productIds'])
        self.assertRegex(result['slots'][0]['sourceBinding'], r'^[a-f0-9]{64}$')
        self.assertEqual('partial', result['status'])

    def test_missing_destination_bad_identity_and_duplicate_theme_hold(self):
        value = manifest()
        for slot in value['slots']:
            slot.update(slug='same', title='Same', categoryId='wear', query='same',
                        selectionReason='same')
        value['slots'][1].update(slug='other', title='Other', query='other')
        products = [product(slot['productIds'][0]) for slot in value['slots']]
        products[0]['amazonUrl'] = ''
        products[1]['brand'] = 'unverified-brand'
        result = resolve_batch(value, {'products': products, 'articles': []}, [],
                               datetime(2026, 11, 16, 9, tzinfo=JST))
        self.assertEqual(['missing_required_destination', 'apparel_identity_invalid',
                          'duplicate_theme'], [slot['reason'] for slot in result['slots']])

    def test_duplicate_slug_or_title_independently_holds_before_sources(self):
        value = manifest()
        for index, slot in enumerate(value['slots'], 1):
            slot.update(slug=f'wear-{index}', title=f'Wear {index}', categoryId='wear',
                        query=f'winter wear {index}', selectionReason='verified fixture')
        value['slots'][0].update(slug=' SAME-SLUG ', title='Different title')
        value['slots'][1].update(slug='different-slug', title='Ｓａｍｅ　Ｔｉｔｌｅ')
        catalog = {'products': [product(slot['productIds'][0]) for slot in value['slots']],
                   'articles': [{'slug': 'same-slug', 'title': 'Published title'}]}
        queued = [{'slug': 'queued-other', 'title': 'same title'}]
        result = resolve_batch(value, catalog, queued,
                               datetime(2026, 11, 16, 9, tzinfo=JST))
        self.assertEqual(['duplicate_theme', 'duplicate_theme', 'ready'],
                         [slot['reason'] if slot['status'] == 'source_hold' else 'ready'
                          for slot in result['slots']])

    def test_manifest_is_strict_and_loads_from_configured_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'batch.json'
            path.write_text(json.dumps(manifest()))
            self.assertEqual('apparel-2026-11-16', load_batch(path)['batchId'])
            bad = copy.deepcopy(manifest())
            bad['extra'] = True
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                load_batch(path)


if __name__ == '__main__':
    unittest.main()
