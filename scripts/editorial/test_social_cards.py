"""Offline source, renderer and immutable-storage contract checks."""
import copy
import hashlib
from pathlib import Path
from unittest.mock import patch
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


class EditorialIllustrationTests(unittest.TestCase):
    def make(self):
        catalog = FakeCatalog(public=b'')
        def stored(data, path):
            catalog.public = data
            return {'verified': True, 'path': path, 'sha256': hashlib.sha256(data).hexdigest(),
                    'size': len(data), 'url': ENV['SUPABASE_URL'] +
                    '/storage/v1/object/public/editorial-social-cards/' + path}
        return SocialCards({}, ENV, catalog=catalog, storage=stored), catalog

    @staticmethod
    def theme(title):
        return {'title': title, 'outline': ['表示を確認', '条件を照合', '対象を探す']}

    @staticmethod
    def node_result(script, payload):
        assert script == 'render-editorial-card.mjs'
        Path(payload['outputPath']).write_bytes(CARD)
        return {'passed': True, 'evidencePassed': True, 'version': 'editorial-illustration-v1',
            'width': 1200, 'height': 630, 'networkRequests': 0, 'bytes': len(CARD),
            'pngSha256': hashlib.sha256(CARD).hexdigest(), 'contentHash': 'c' * 64,
            'sourceIds': payload['sourceIds'], 'sourceReceiptSha256': payload['sourceReceiptSha256'],
            'displayText': {'title': payload['title'], 'heading': payload['heading'],
                'steps': payload['steps'], 'badge': 'キャンプのヒント',
                'disclaimer': 'Camp Gear Lab編集部の図解', 'brand': 'Camp Gear Lab'},
            'layout': {}, 'renderer': {'engine': 'fixture', 'platform': 'fixture', 'fontFamily': 'fixture'}}

    def test_question_suffix_is_exact_without_mutating_title_or_product_heading(self):
        references = [{'id': 'public:thermos-product-parts'}]
        titles = [('コールマン化繊寝袋は洗える？タグとアイコンで判断する', 'タグとアイコンで判断する'),
                  ('サーモスの交換部品はどう探す？品番と色名から検索する', '品番と色名から検索する'),
                  ('部品はどれ？品番の確認？適合を調べる', '品番の確認？適合を調べる'),
                  ('部品はどれ？', '部品はどれ？'), ('製品A｜購入前の確認点', '購入前の確認点'),
                  ('Which part? Check the label', 'Which part? Check the label')]
        for title, expected in titles:
            card, _ = self.make()
            theme = self.theme(title)
            before = copy.deepcopy(theme)
            with self.subTest(title=title), patch.object(card, '_node', side_effect=self.node_result) as node:
                result = card.build_editorial_illustration(theme, references, 'a' * 64)
            payload = node.call_args.args[1]
            self.assertEqual(title, payload['title'])
            self.assertEqual(expected, payload['heading'])
            self.assertEqual(before, theme)
            self.assertEqual(references[0]['id'], result['referenceIds'][0])
            self.assertEqual('Camp Gear Lab', result['rendererEvidence']['displayText']['brand'])
        self.assertEqual('製品A？購入前の確認点', _heading('製品A？購入前の確認点'))

    def test_editorial_brand_and_source_binding_must_exactly_match(self):
        for field in ('brand', 'sourceIds', 'sourceReceiptSha256'):
            card, catalog = self.make()
            def node(script, payload):
                value = self.node_result(script, payload)
                if field == 'brand':
                    value['displayText']['brand'] = 'Other brand'
                elif field == 'sourceIds':
                    value['sourceIds'] = ['public:other']
                else:
                    value['sourceReceiptSha256'] = '0' * 64
                return value
            with self.subTest(field=field), patch.object(card, '_node', side_effect=node):
                with self.assertRaisesRegex(ValueError, 'editorial_card_render_evidence_invalid'):
                    card.build_editorial_illustration(self.theme('部品はどれ？表示を確認'),
                        [{'id': 'public:thermos-product-parts'}], 'a' * 64)
            self.assertEqual([], catalog.urls)

    def test_actual_js_editorial_contract_preserves_title_and_exact_source_binding(self):
        from ledger import fingerprint
        card, catalog = self.make()
        title = 'コールマンの化繊寝袋は洗える？表示を確認する'
        theme = self.theme(title)
        references = [{'id': 'public:coleman-synthetic-wash', 'receiptSha256': 'a' * 64}]
        source_hash = fingerprint([r['receiptSha256'] for r in references])
        before = copy.deepcopy((theme, references))
        result = card.build_editorial_illustration(theme, references, source_hash)
        evidence = result['rendererEvidence']
        self.assertEqual(title, evidence['displayText']['title'])
        self.assertEqual('表示を確認する', evidence['displayText']['heading'])
        self.assertEqual('Camp Gear Lab', evidence['displayText']['brand'])
        self.assertEqual([r['id'] for r in references], evidence['sourceIds'])
        self.assertEqual(source_hash, evidence['sourceReceiptSha256'])
        self.assertEqual(0, evidence['networkRequests'])
        self.assertEqual(hashlib.sha256(catalog.public).hexdigest(), result['sha256'])
        self.assertEqual(before, (theme, references))
        self.assertEqual(evidence['contentHash'], result['compositionSha256'])


    def test_actual_js_selected_pole_five_steps_through_fake_storage(self):
        from ledger import fingerprint
        card, catalog = self.make()
        title = 'テントポールの手入れ｜継ぎ目とグロメットの汚れを残さず収納するには'
        theme = {'title': title, 'outline': ['幕体とは分けて金属部の汚れを見る', 'ポールは土を落として乾燥を確認',
            '継ぎ目とグロメットを確認する', '防錆の案内はメーカーの対象を守る', '収納前に残す確認事項']}
        references = [{'id': 'public:coleman-care',
                       'receiptSha256': 'd981e4c3c9df4d75b3b8fc34cad5081bcb59ba9ecce1412b90f62dd357ee303f'}]
        binding = fingerprint([r['receiptSha256'] for r in references])
        before = copy.deepcopy((theme, references))
        result = card.build_editorial_illustration(theme, references, binding)
        evidence = result['rendererEvidence']
        self.assertEqual(title, evidence['displayText']['title'])
        self.assertEqual(_heading(title), evidence['displayText']['heading'])
        self.assertEqual(theme['outline'], [s['text'] for s in evidence['displayText']['steps']])
        self.assertEqual(5, len(evidence['layout']['stepCards']))
        self.assertTrue(all(s['textBox']['lines'] and s['numberBox']['lines']
                            for s in evidence['layout']['stepCards']))
        self.assertEqual(['public:coleman-care'], evidence['sourceIds'])
        self.assertEqual(binding, evidence['sourceReceiptSha256'])
        self.assertEqual(0, evidence['networkRequests'])
        self.assertEqual(hashlib.sha256(catalog.public).hexdigest(), result['sha256'])
        self.assertEqual(evidence['contentHash'], result['compositionSha256'])
        self.assertEqual(before, (theme, references))


if __name__ == '__main__':
    unittest.main()
