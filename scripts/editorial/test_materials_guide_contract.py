"""One owner-bound materials guide never grants a general mixed-apparel route."""
import copy
import unittest
from urllib.parse import quote

from apparel_identity import apparel_contract, public_binding
from ledger import fingerprint
from quality import inspect_bundle
from test_quality import bundle as base_bundle
from materials_guide_contract import (ARTICLE_ID, FIELD, REQUIRED_STATEMENT,
                                      build_materials_guide_contract,
                                      bind_materials_guide_contract)


def fixture():
    value = base_bundle()
    products, refs, images = [], [], []
    for model, kind, weight, asin in [('1101493', 'down', '130g', 'B000000001'),
                                      ('1101539', 'active-layer', '229g', 'B000000002')]:
        pid = 'apparel-montbell-' + model
        maker = 'https://webshop.montbell.jp/goods/disp.php?product_id=' + model
        merchant = 'https://item.rakuten.co.jp/shop/' + model + '/'
        image = 'https://webshop.montbell.jp/common/images/product/prod_k/k_' + model + '_bk.jpg'
        product = {'id': pid, 'name': model + " Men's", 'brand': 'mont-bell', 'categoryId': 'wear',
            'specs': {'model': model, 'apparelClass': kind, 'gender': "Men's",
                      'weight': weight, 'optionState': 'selectable',
                      'amazonOptionState': 'fixed', 'amazonVariant': asin,
                      'amazonColor': 'BK', 'amazonSize': 'M', 'rakutenOptionState': 'selectable'},
            'imageUrl': image, 'amazonUrl': 'https://www.amazon.co.jp/dp/' + asin + '?tag=camp78-22',
            'affiliateUrl': 'https://hb.afl.rakuten.co.jp/ichiba/owner/?pc=' + quote(merchant, safe='')}
        contract = apparel_contract(product)
        maker_binding = dict(contract, colors=['BK'], sizes=['M'], imageUrls=[image],
                             sourceKind='montbell-product-dom')
        refs.append({'productId': pid, 'kind': 'manufacturer', 'url': maker,
                     'checkedAt': '2026-11-22T06:00:00+09:00', 'apparelBinding': maker_binding})
        for channel, url in [('amazon', product['amazonUrl']), ('rakuten', merchant)]:
            binding = dict(contract, colors=['BK'], sizes=['M'], imageUrls=[image],
                sourceKind=channel + '-primary-product-dom', merchantChannel=channel,
                merchantOptionState='fixed' if channel == 'amazon' else 'selectable')
            if channel == 'amazon':
                binding.update(merchantVariant=asin, merchantColor='BK', merchantSize='M')
            refs.append({'productId': pid, 'kind': 'purchase', 'channel': channel, 'url': url,
                         'checkedAt': '2026-11-22T06:00:00+09:00', 'apparelBinding': public_binding(binding)})
        products.append(product)
        images.append({'productId': pid, 'url': image, 'verified': True,
                       'apparelBinding': copy.deepcopy(maker_binding)})
    value.update(products=products, references=refs, images=images)
    ids = [p['id'] for p in products]
    value['article'].update(id=ARTICLE_ID, slug='down-synthetic-guide', title='ダウンと化繊中綿の選び方',
        categoryId='wear', productIds=ids, content='## 選び方\n' + REQUIRED_STATEMENT + '\n\n'
        '{{comparison:' + ','.join(ids) + '}}\n' + '\n'.join('{{product:' + p + '}}' for p in ids)
        + '\n[設営](/articles/setup) [撤収](/articles/cleanup)')
    value['brief']['format'] = 'guide'
    projection = []
    for product in products:
        item = {k: product.get(k) for k in ('id','name','brand','categoryId','specs','imageUrl','affiliateUrl','amazonUrl')}
        item['apparelContract'] = apparel_contract(product)
        projection.append(item)
    job = {'id': ARTICLE_ID, 'kind': 'supplemental_article', 'batchId': 'apparel-2026-11-22',
           'batchSlot': 3, 'batchCallCap': 96, 'sourceBinding': fingerprint(projection),
           'theme': {k: copy.deepcopy(value['article'][k]) for k in ('slug','title','categoryId','productIds')}}
    checks = dict(facts=True, images=True, affiliate=True)
    gathered = {'products': copy.deepcopy(products), 'references': copy.deepcopy(refs),
                'checks': checks, 'evidence': {'products': [dict(productId=p['id'], **checks) for p in products]}}
    return job, gathered, value


class MaterialsGuideTests(unittest.TestCase):
    def test_runtime_bound_exact_guide_passes_without_changing_classes_or_inputs(self):
        job, gathered, value = fixture()
        before = copy.deepcopy((job, gathered, value))
        value[FIELD] = build_materials_guide_contract(job, gathered, value)
        self.assertTrue(inspect_bundle(value)['passed'], inspect_bundle(value))
        self.assertEqual(['down', 'active-layer'], [p['specs']['apparelClass'] for p in value['products']])
        value.pop(FIELD)
        self.assertEqual(before, (job, gathered, value))

    def test_mixed_pair_without_contract_remains_rejected(self):
        _, _, value = fixture()
        self.assertIn('apparel: comparison must contain apparel of one explicit position only',
                      inspect_bundle(value)['failures'])

    def test_wrong_job_batch_slot_binding_or_unverified_gather_cannot_build(self):
        for change in ('job','batch','slot','binding','checks','detail','manufacturer','amazon','rakuten'):
            job, gathered, value = fixture()
            if change == 'job': job['id'] = 'other'
            elif change == 'batch': job['batchId'] = 'apparel-2026-11-16'
            elif change == 'slot': job['batchSlot'] = 2
            elif change == 'binding': job['sourceBinding'] = 'a' * 64
            elif change == 'checks': gathered['checks']['affiliate'] = False
            elif change == 'detail': gathered['evidence']['products'][0]['facts'] = False
            else:
                gathered['references'] = [r for r in gathered['references'] if not
                    (r['productId'].endswith('1101539') and
                     (r.get('kind') == change or r.get('channel') == change))]
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_materials_guide_contract(job, gathered, value)

    def test_tampered_contract_entity_products_refs_or_mode_never_grants_exception(self):
        for change in ('malformed','article','job','product','reference','mode','ranking',
                       'missing_statement','hidden_statement','coded_statement'):
            job, gathered, value = fixture()
            value[FIELD] = build_materials_guide_contract(job, gathered, value)
            if change == 'malformed': value[FIELD] = {'kind': 'self_granted'}
            elif change == 'article': value['article']['id'] = 'other'
            elif change == 'job': value[FIELD]['job']['batchSlot'] = 1
            elif change == 'product': value['products'][0]['specs']['gender'] = "Women's"
            elif change == 'reference': value['references'][0]['apparelBinding']['weight'] = '999g'
            elif change == 'mode': value['brief']['format'] = 'comparison'
            elif change == 'ranking': value['article']['content'] += '\n{{ranking:' + ','.join(value['article']['productIds']) + '}}'
            elif change == 'missing_statement': value['article']['content'] = value['article']['content'].replace(REQUIRED_STATEMENT,'')
            elif change == 'hidden_statement': value['article']['content'] = value['article']['content'].replace(REQUIRED_STATEMENT,'<!--' + REQUIRED_STATEMENT + '-->')
            elif change == 'coded_statement': value['article']['content'] = value['article']['content'].replace(REQUIRED_STATEMENT,'```\n' + REQUIRED_STATEMENT + '\n```')
            result = inspect_bundle(value)
            with self.subTest(change=change):
                self.assertFalse(result['passed'], result)
                self.assertTrue(any(f.startswith('materials_guide:') for f in result['failures']), result)

    def test_only_owner_target_is_bound_and_preexisting_model_contract_is_rejected(self):
        job, gathered, value = fixture()
        with self.assertRaises(ValueError):
            bind_materials_guide_contract(job, gathered, dict(value, **{FIELD: {'kind':'self_granted'}}))
        other = dict(job, id='other')
        self.assertIsNone(bind_materials_guide_contract(other, gathered, value))
        self.assertNotIn(FIELD, value)
        bind_materials_guide_contract(job, gathered, value)
        self.assertTrue(inspect_bundle(value)['passed'])
        bind_materials_guide_contract(job, gathered, value)
        self.assertTrue(inspect_bundle(value)['passed'])

    def test_runtime_final_hook_builds_contract_before_gate_without_any_model_or_card_call(self):
        from runtime import Runtime
        class PreviewReached(Exception):
            pass
        for wrong_job in (False, True):
            job, gathered, value = fixture()
            value['article']['content'] += '\n' + 'テスト用の説明。' * 400
            if wrong_job:
                job['id'] = 'other'
            runtime = object.__new__(Runtime)
            runtime.config = {'socialCardsEnabled': False}
            runtime._require_running = lambda: None
            runtime._wise_context = lambda context: context
            def renderer(*args):
                raise PreviewReached()
            runtime.renderer = renderer
            with self.subTest(wrong_job=wrong_job):
                if wrong_job:
                    with self.assertRaisesRegex(ValueError, 'article_structure_or_affiliate_failed'):
                        runtime._finish_article_review(job, {}, gathered, value, {}, {}, {}, {})
                    self.assertNotIn(FIELD, value)
                else:
                    with self.assertRaises(PreviewReached):
                        runtime._finish_article_review(job, {}, gathered, value, {}, {}, {}, {})
                    self.assertTrue(inspect_bundle(value)['passed'])

    def test_disclosure_in_details_never_counts_as_visible_even_when_open(self):
        for opening in ('<details>', '<details open>'):
            job, gathered, value = fixture()
            value['article']['content'] = value['article']['content'].replace(
                REQUIRED_STATEMENT, opening + '\n' + REQUIRED_STATEMENT + '\n</details>')
            with self.subTest(opening=opening), self.assertRaisesRegex(ValueError, 'visible'):
                build_materials_guide_contract(job, gathered, value)

    def test_observed_unsupported_claims_are_rejected_despite_visible_disclaimer(self):
        observed = [
            '止まっている時間が長いならダウン、登り下りで汗をかくなら化繊中綿。',
            '止まっている時間が長い・持ち運び重視ならダウンのプラズマ1000。',
            '登り下りで汗をかきながら着たままでいたいなら、化繊中綿のU.L.サーマラップ。',
            '休憩や停滞が長くて、ザックに小さく収めて持ち運びたいならダウン。',
            '脇・肩・腕を少し厚めにしているのは、設計の違いとして受け取れます。',
            'これは特定のサイズ・個体の実測ではなく平均値です。',
            'いずれも平均値・目安で、サイズやパッキングにより前後する可能性があります。',
            '収納サイズも、きれいに畳んだ場合の目安と考えます。',
            'ザックに入れて非常用に持つ運用なら、収納性の高いダウンが効いてきます。',
            'ザックの隙間に放り込んで「保険」として持つなら、プラズマ1000。',
        ]
        for location in ('content', 'faq', 'conclusion'):
            for claim in observed:
                job, gathered, value = fixture()
                value[FIELD] = build_materials_guide_contract(job, gathered, value)
                if location == 'content':
                    value['article']['content'] += '\n' + claim
                elif location == 'faq':
                    value['article']['faqs'][0]['answer'] = claim
                else:
                    value['brief']['conclusion'] = claim
                with self.subTest(location=location, claim=claim):
                    result = inspect_bundle(value)
                    self.assertFalse(result['passed'], result)
                    self.assertTrue(any('unsupported materials guide claim' in f for f in result['failures']), result)
                    with self.assertRaisesRegex(ValueError, 'unsupported materials guide claim'):
                        build_materials_guide_contract(job, gathered, value)

    def test_source_bounded_replacements_and_unconfirmed_average_basis_are_safe(self):
        job, gathered, value = fixture()
        value['article']['content'] += ('\n身頃と脇・肩・腕では、公式に記載されたデニールが異なります。'
            '\n「平均重量」は重量の表記です。収納サイズは公式に記載された寸法・容量です。'
            '\n平均の算出対象・方法、含有物は今回の根拠では未確認です。'
            '\nザックに入れて携行するときは、今回のダウンの製品の収納サイズが判断材料になります。')
        value['brief']['conclusion'] = ('携行時の軽さと収納サイズ重視ならダウンのプラズマ1000、'
            'ストップ＆ゴーを繰り返す登山を想定するなら、その用途を公式が挙げるU.L.サーマラップ。')
        value[FIELD] = build_materials_guide_contract(job, gathered, value)
        self.assertTrue(inspect_bundle(value)['passed'], inspect_bundle(value))


if __name__ == '__main__':
    unittest.main()
