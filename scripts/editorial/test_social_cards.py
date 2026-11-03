"""Offline source, renderer and immutable-storage contract checks."""
import copy
import hashlib
import struct
import unittest
import zlib

from social_cards import SocialCards, _heading


def png(width, height):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    raw = (b'\x00' + b'\x10\x20\x30' * width) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


SOURCE = png(2, 2)
CARD = png(1200, 630)
ENV = {'SUPABASE_URL': 'https://db.example.com', 'SUPABASE_SERVICE_ROLE_KEY': 'test-only'}


class FakeCatalog:
    def __init__(self, source=SOURCE, public=CARD):
        self.source, self.public, self.urls = source, public, []

    def request(self, url, *_):
        self.urls.append(url)
        body = self.public if 'storage/v1/object/public/' in url else self.source
        return {'body': body, 'headers': {'content-type': 'image/png'}}


def fixture():
    return {'article': {'title': '実物を比較', 'categoryId': 'burner', 'productIds': ['a']},
            'products': [{'id': 'a', 'name': '実物A', 'imageUrl': 'https://maker.example.com/a.png'}],
            'images': [{'productId': 'a', 'url': 'https://maker.example.com/a.png', 'verified': True,
                        'sha256': hashlib.sha256(SOURCE).hexdigest(), 'size': len(SOURCE), 'contentType': 'image/png'}]}


class SocialCardTests(unittest.TestCase):
    def make(self, *, catalog=None, renderer=None, storage=None, env=None):
        def stored(data, path):
            sha = hashlib.sha256(data).hexdigest()
            return {'verified': True, 'path': path, 'sha256': sha, 'size': len(data),
                    'url': ENV['SUPABASE_URL'] + '/storage/v1/object/public/editorial-social-cards/' + path}
        return SocialCards({}, env or ENV, catalog or FakeCatalog(),
                           renderer or (lambda spec, path: {'bytes': CARD, 'evidence': {'displayText': spec['heading']}}),
                           storage or stored)

    def test_build_deepcopies_and_binds_exact_source_and_final_card(self):
        original = fixture()
        before = copy.deepcopy(original)
        specs = []
        result = self.make(renderer=lambda spec, path: specs.append(spec) or
                           {'bytes': CARD, 'evidence': {'displayText': spec['heading']}}).build(original)
        self.assertEqual(original, before)
        self.assertEqual(specs[0]['products'][0]['name'], '実物A')
        self.assertTrue(specs[0]['products'][0]['dataUrl'].startswith('data:image/png;base64,'))
        manifest = result['article']['generationMeta']['socialCard']
        self.assertEqual(result['images'][-1]['sha256'], manifest['sha256'])
        self.assertEqual(manifest['rendererEvidence']['displayText'], '実物を比較')
        self.assertEqual(manifest['sources'], [{'productId': 'a', 'sha256': before['images'][0]['sha256']}])
        self.assertEqual((manifest['width'], manifest['height'], manifest['contentType']), (1200, 630, 'image/png'))
        self.assertEqual(result['article'].get('eyecatch'), None)

    def test_unverified_missing_ambiguous_or_mutated_source_stops_before_store(self):
        calls = []
        card = self.make(storage=lambda *_: calls.append(1))
        for mutation in (lambda b: b['images'][0].update(verified=False),
                         lambda b: b['images'][0].update(sha256='0' * 64),
                         lambda b: b['images'].append(copy.deepcopy(b['images'][0])),
                         lambda b: b['products'][0].update(imageUrl='https://other.example/a.png')):
            b = fixture(); mutation(b)
            with self.assertRaises(ValueError): card.build(b)
        with self.assertRaisesRegex(ValueError, 'social_card_source_mismatch'):
            self.make(catalog=FakeCatalog(source=png(3, 2)), storage=lambda *_: calls.append(1)).build(fixture())
        self.assertEqual(calls, [])

    def test_invalid_final_format_and_public_readback_fail_closed(self):
        for output in (SOURCE, b'not a png', png(1200, 631)):
            with self.assertRaisesRegex(ValueError, 'social_card_png_invalid'):
                self.make(renderer=lambda *_: {'bytes': output, 'evidence': {}}).build(fixture())
        with self.assertRaisesRegex(ValueError, 'social_card_storage_unverified'):
            self.make(catalog=FakeCatalog(public=SOURCE)).build(fixture())
        with self.assertRaisesRegex(ValueError, 'social_card_storage_unverified'):
            self.make(storage=lambda *_: {'verified': False}).build(fixture())

    def test_no_rebinding_or_unconfigured_credentials(self):
        b = fixture(); b['article']['generationMeta'] = {'socialCard': {'url': 'old'}}
        with self.assertRaisesRegex(ValueError, 'social_card_already_bound'):
            self.make().build(b)
        with self.assertRaisesRegex(ValueError, 'social_card_storage_unconfigured'):
            self.make(env={'SUPABASE_URL': ENV['SUPABASE_URL']}).build(fixture())

    def test_actual_node_renderer_contract_with_offline_storage(self):
        catalog = FakeCatalog(public=b'')
        def stored(data, path):
            catalog.public = data
            return {'verified': True, 'path': path, 'sha256': hashlib.sha256(data).hexdigest(),
                    'size': len(data), 'url': ENV['SUPABASE_URL'] +
                    '/storage/v1/object/public/editorial-social-cards/' + path}
        result = SocialCards({}, ENV, catalog=catalog, storage=stored).build(fixture())
        manifest = result['article']['generationMeta']['socialCard']
        self.assertEqual(manifest['sha256'], hashlib.sha256(catalog.public).hexdigest())
        self.assertEqual(manifest['rendererEvidence']['displayText']['heading'], '実物を比較')
        self.assertIn('layout', manifest['rendererEvidence'])
        self.assertIn('sourceCrops', manifest['rendererEvidence'])
        self.assertNotIn('outputPath', manifest['rendererEvidence'])

    def test_one_separator_uses_exact_suffix_and_products_stay_separate(self):
        self.assertEqual(_heading('製品A｜購入前の確認点'), '購入前の確認点')
        self.assertEqual(_heading('製品A｜中間｜確認点'), '製品A｜中間｜確認点')
        self.assertEqual(_heading('製品A｜'), '製品A｜')
        b = fixture(); b['article']['title'] = '実物A｜購入前の確認点'
        specs = []
        result = self.make(renderer=lambda spec, path: specs.append(spec) or
                           {'bytes': CARD, 'evidence': {'displayText': spec['heading']}}).build(b)
        self.assertEqual(specs[0]['title'], '実物A｜購入前の確認点')
        self.assertEqual(specs[0]['heading'], '購入前の確認点')
        self.assertEqual(specs[0]['products'][0]['name'], '実物A')
        self.assertEqual(result['article']['generationMeta']['socialCard']['rendererEvidence']['displayText'], '購入前の確認点')


if __name__ == '__main__':
    unittest.main()
