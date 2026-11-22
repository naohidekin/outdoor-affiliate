"""Sanitized structures and values observed in the 2026-11-22 maker pages."""
import copy
import hashlib
import json
import unittest
from official_shopify_apparel import inspect_official_shopify as inspect

CASES = [
    ('X000010878', 'https://arcteryx.jp/products/beta-jacket-m', 9110038216935,
     'ベータ ジャケット メンズ', 'Arcteryx', "Arc'teryx", 'Vitality', 'XS', 'X00001087808140',
     52770019705063, 'F26_X000010878_018562_Beta_Jacket_Vitality_Men_M_Transp.webp?v=1790815240'),
    ('X000010854', 'https://arcteryx.jp/products/beta-sl-jacket-m', 9110037987559,
     'ベータ SL ジャケット メンズ', 'Arcteryx', "Arc'teryx", 'Ultima', 'XS', 'X00001085405140',
     52770020655335, 'F26_X000010854_002744_Beta_SL_Jacket_Ultima_Men_M_Transp.webp?v=1790815241'),
    ('MIV01248', 'https://www.millet.jp/products/miv01248', 10914878095644,
     'ドライナミック メッシュ NS クルー', 'ミレー公式オンライストア', 'Millet', 'OLIVE | N8781', 'S-M',
     'MIV01248-N8781-S-M', 54350927266076, 'MIV01248_N8781_01.jpg?v=1787807693'),
]
FABRIC = 'DRYNAMIC MESH ポリプロピレン66% ナイロン28% ポリウレタン6%'


def fixture(c):
    model, url, pid, title, vendor, brand, color, size, sku, vid, filename = c
    image = '//' + url.split('/')[2] + '/cdn/shop/files/' + filename
    p = dict(brand=brand, categoryId='hardshell' if model.startswith('X') else 'base-layer',
             specs=dict(model=model, gender='メンズ', optionState='selectable'))
    r = dict(id=pid, title=title, handle=url.rsplit('/', 1)[1], vendor=vendor,
             tags=[model], options=['Color', 'Size'] if model.startswith('X') else ['カラー', 'サイズ'],
             images=[image], variants=[dict(id=vid, sku=sku, option1=color, option2=size,
                 option3=None, options=[color, size], featured_image=dict(
                     product_id=pid, variant_ids=[vid], src=image))],
             description='<p class="descript-name">素材</p><p class="body">' + FABRIC +
                         '</p><p class="descript-name">重量</p><p class="body">100g</p>')
    return p, r


def page(c, r, title=None):
    model, url, pid, expected = c[:4]
    title = expected if title is None else title
    head = '<link rel="canonical" href="' + url + '">'
    if model.startswith('X'):
        return head + '<div id="shopify-section-product-template"><h1 class="product-single__title">' + title + \
            '</h1><script type="application/json" id="ProductJson-product-template">' + json.dumps(r) + '</script></div>'
    return head + '<product-rerender id="product-info-' + str(pid) + '-template--main">' + \
        '<h1 class="product-meta__title">' + title + '（メンズ）</h1><div class="product-key">miv01248</div>' + \
        '</product-rerender><script id="back-in-stock-helper-embedded">var _BISConfig = {};' + \
        '_BISConfig.product = ' + json.dumps(r) + '; _BISConfig.product.variants[0]["oos"] = false;</script>'


class OfficialShopifyTests(unittest.TestCase):
    def test_actual_arc_legacy_sku_families_in_one_primary_root_remain_held(self):
        # Both legacy SKU families were observed inside the actual ProductJson,
        # not scraped from a recommendation card. Do not cherry-pick current rows.
        for c, legacy in ((CASES[0], 'X00001000417140'), (CASES[1], 'X00001044404140')):
            p,r=fixture(c)
            old=copy.deepcopy(r['variants'][0])
            old.update(id=old['id']+1,sku=legacy)
            r['variants'].append(old)
            self.assertIsNone(inspect(p,c[1],page(c,r)))
            p['specs'].update(optionState='fixed',color=c[6],size=c[7])
            self.assertIsNone(inspect(p,c[1],page(c,r)))

    def test_public_entrypoint_and_retained_binding_integration(self):
        from apparel_identity import inspect_apparel_page, binding_matches_product, public_binding
        for c in CASES:
            p, r = fixture(c)
            image = 'https:' + r['images'][0]
            binding = inspect_apparel_page(p, c[1], page(c, r), image)
            self.assertEqual(inspect(p, c[1], page(c, r), image), binding)
            retained = public_binding(binding)
            self.assertTrue(binding_matches_product(retained, p))
            self.assertFalse(binding_matches_product(retained, p, channel='rakuten'))
            for key, wrong in [('model', 'OTHER123'), ('gender', 'ウィメンズ')]:
                changed = copy.deepcopy(p)
                changed['specs'][key] = wrong
                self.assertFalse(binding_matches_product(retained, changed))
            r['variants'][0]['sku'] = 'OTHER123'
            self.assertIsNone(inspect_apparel_page(p, c[1], page(c, r), image))

    def test_primary_excerpt_is_source_text_separate_from_requested_facts(self):
        c = CASES[2]
        p, r = fixture(c)
        # Observed body/heading layout; source sentences are copied, not rewritten.
        intro = '気温の高い季節や薄手のレイヤーに合わせやすいノースリーブタイプ。'
        r['description'] = ('<div class="product-description-box"><p class="body">' + intro +
                            '</p><p class="body">究極のドライ感。価格5,830円。送料無料。</p>' +
                            '<p class="descript-name">装備</p><p class="body">' +
                            '・水分を含まないポリプロピレンを使用。<br>・消臭糸使用</p>' +
                            r['description'] + '<p class="body">関連商品を購入</p></div>')
        b = inspect(p, c[1], page(c, r))
        excerpt = b['manufacturerExcerpt']
        expected = intro + '\n・水分を含まないポリプロピレンを使用。\n・消臭糸使用'
        self.assertEqual(expected, excerpt['text'])
        self.assertEqual({'sourceUrl', 'model', 'text', 'excerptSHA256', 'scope'}, set(excerpt))
        self.assertEqual((c[1], c[0]), (excerpt['sourceUrl'], excerpt['model']))
        self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(), excerpt['excerptSHA256'])
        unsafe = copy.deepcopy(r)
        unsafe['description'] += '<div class="related"><p class="body">Other product facts</p></div>'
        self.assertNotIn('manufacturerExcerpt', inspect(p, c[1], page(c, unsafe)))
        p['specs'].update(fabric=FABRIC, weight='100g')
        self.assertEqual(excerpt, inspect(p, c[1], page(c, r))['manufacturerExcerpt'])
        p['specs']['weight'] = '1000g'
        self.assertIsNone(inspect(p, c[1], page(c, r)))
        del p['specs']['weight']
        r['vendor'] = 'related maker'
        self.assertIsNone(inspect(p, c[1], page(c, r)))

    def test_catalog_wiring_carries_exact_primary_excerpt(self):
        from catalog import Catalog
        from test_catalog import PNG, response
        c = CASES[2]
        p, r = fixture(c)
        p.update(id='observed-millet-fixture', name=c[3], imageUrl='https:' + r['images'][0])
        r['description'] = '<p class="body">・消臭糸使用</p>' + r['description']
        calls = []
        def fetch(url, headers, timeout):
            calls.append((url, headers))
            if url == p['imageUrl']:
                return response(PNG, 'image/png')
            self.assertEqual(c[1], url)
            self.assertIn('Chrome/', headers.get('User-Agent', ''))
            self.assertEqual('ja-JP,ja;q=0.9', headers.get('Accept-Language'))
            return response(page(c, r))
        result = Catalog({}, fetch, {p['id']: [c[1]]}).gather(
            {'productIds': [p['id']]}, {'products': [p]})
        maker = [ref for ref in result['references'] if ref['kind'] == 'manufacturer']
        description = [ref for ref in result['references'] if ref['kind'] == 'manufacturer-description']
        self.assertEqual(1, len(maker))
        self.assertEqual(1, len(description))
        ref = description[0]
        self.assertEqual('official-shopify-product', maker[0]['apparelBinding']['sourceKind'])
        self.assertEqual((p['id'], c[1], c[1], c[0]),
                         (ref['productId'], ref['url'], ref['sourceUrl'], ref['model']))
        self.assertEqual('・消臭糸使用', ref['text'])
        self.assertEqual(hashlib.sha256(ref['text'].encode()).hexdigest(), ref['excerptSHA256'])
        self.assertEqual(maker[0]['checkedAt'], ref['checkedAt'])
        self.assertTrue(ref['conditions'])
        self.assertTrue(calls)

    def test_exact_models_public_bindings(self):
        for c in CASES:
            with self.subTest(model=c[0]):
                p, r = fixture(c)
                image = 'https:' + r['images'][0]
                b = inspect(p, c[1], page(c, r), image)
                self.assertIsNotNone(b)
                self.assertEqual(c[0], b['model'])
                self.assertEqual([c[6]], b['colors'])
                self.assertEqual([c[7]], b['sizes'])
                self.assertEqual([image], b['imageUrls'])
                self.assertEqual(c[1], b['sourceUrl'])
                self.assertEqual('official-shopify-product', b['sourceKind'])

    def test_wrong_model_gender_vendor_primary_gender_and_missing_sku(self):
        for c in CASES:
            for mode in ('model', 'gender', 'class', 'vendor', 'primary-gender', 'title', 'missing-sku'):
                p, r = fixture(c)
                title = None
                if mode == 'model': p['specs']['model'] = 'X000010004'
                if mode == 'gender': p['specs']['gender'] = 'ウィメンズ'
                if mode == 'class': p['categoryId'] = 'fleece'
                if mode == 'vendor': r['vendor'] = 'unrelated merchant'
                if mode == 'primary-gender': title = 'ウィメンズ'
                if mode == 'title': r['title'] = 'Related product'
                if mode == 'missing-sku': del r['variants'][0]['sku']
                with self.subTest(model=c[0], mode=mode):
                    self.assertIsNone(inspect(p, c[1], page(c, r, title)))

    def test_canonical_final_url_missing_structure_multiple_roots(self):
        for c in CASES:
            p, r = fixture(c)
            h = page(c, r)
            for bad in (h.replace('rel="canonical"', 'rel="alternate"'),
                        h.replace('href="' + c[1], 'href="https://example.com/related'),
                        h + '<link rel="canonical" href="' + c[1] + '">',
                        h + h[h.index('>') + 1:], '<header>Arcteryx Millet メンズ ' + c[0] + '</header>'):
                self.assertIsNone(inspect(p, c[1], bad))
            for url in (c[1] + '?variant=1', c[1] + '/', c[1].replace('https:', 'http:'),
                        'https://merchant.example/products/' + r['handle']):
                self.assertIsNone(inspect(p, url, h))

    def test_related_mixed_variants_rejected_even_for_fixed_matching_variant(self):
        for c in CASES:
            p, r = fixture(c)
            other = copy.deepcopy(r['variants'][0])
            other.update(id=other['id'] + 1, sku='X00001000417140', option1='Related', options=['Related', c[7]])
            r['variants'].append(other)
            self.assertIsNone(inspect(p, c[1], page(c, r)))
            p['specs'].update(optionState='fixed', color=c[6], size=c[7])
            self.assertIsNone(inspect(p, c[1], page(c, r)))
            _, r = fixture(c)
            r['handle'] = 'related-model'
            self.assertIsNone(inspect(p, c[1], page(c, r)))

    def test_fixed_pair_and_image_binding(self):
        for c in CASES:
            p, r = fixture(c)
            p['specs'].update(optionState='fixed', color=c[6], size=c[7])
            b = inspect(p, c[1], page(c, r))
            self.assertIsNotNone(b)
            self.assertEqual(c[8], b['sourceVariant'])
            self.assertIsNone(inspect(p, c[1], page(c, r), 'https://images.example/related.jpg'))
            p['specs']['size'] = 'Unobserved'
            self.assertIsNone(inspect(p, c[1], page(c, r)))
            p['specs']['size'] = c[7]
            for mode in ('product-id', 'variant-id', 'missing-image', 'options', 'other-model'):
                bad = copy.deepcopy(r)
                v = bad['variants'][0]
                if mode == 'product-id': v['featured_image']['product_id'] += 1
                if mode == 'variant-id': v['featured_image']['variant_ids'] = []
                if mode == 'missing-image': v['featured_image']['src'] += '&width=200'
                if mode == 'options': v['options'] = ['Other', c[7]]
                if mode == 'other-model':
                    bad['images'] = [bad['images'][0].replace(c[0], 'OTHER123')]
                    v['featured_image']['src'] = bad['images'][0]
                with self.subTest(model=c[0], mode=mode):
                    self.assertIsNone(inspect(p, c[1], page(c, bad)))

    def test_optional_exact_facts_no_shipping_weight_inference(self):
        c = CASES[2]
        p, r = fixture(c)
        p['specs'].update(fabric=FABRIC, weight='100g')
        self.assertIsNotNone(inspect(p, c[1], page(c, r)))
        for key, wrong in [('fabric', 'polyester'), ('weight', '1000g')]:
            bad = copy.deepcopy(p)
            bad['specs'][key] = wrong
            r['variants'][0]['weight'] = 1000
            self.assertIsNone(inspect(bad, c[1], page(c, r)))
        r['description'] = ''
        self.assertIsNone(inspect(p, c[1], page(c, r)))
        c = CASES[0]
        p, r = fixture(c)
        p['specs']['weight'] = '375g'
        self.assertIsNone(inspect(p, c[1], page(c, r)))

    def test_selectable_image_mismatch_and_missing_variants(self):
        for c in CASES:
            p, r = fixture(c)
            self.assertIsNone(inspect(p, c[1], page(c, r), 'https://example.com/wrong.jpg'))
            r['variants'] = []
            self.assertIsNone(inspect(p, c[1], page(c, r)))

    def test_related_title_or_product_json_outside_primary_is_not_identity(self):
        c = CASES[0]
        p, r = fixture(c)
        h = page(c, r)
        # Right title elsewhere must not repair a contradictory primary heading.
        wrong = page(c, r, title='ウィメンズ')
        wrong += '<h1 class="product-single__title">' + c[3] + '</h1>'
        self.assertIsNone(inspect(p, c[1], wrong))
        # A ProductJson in a related area cannot be promoted into the main region.
        h = h.replace('<script type="application/json"', '</div><script type="application/json"')
        self.assertIsNone(inspect(p, c[1], h))

    def test_duplicate_json_fields_and_missing_millet_primary_model_hold(self):
        for c in CASES:
            p, r = fixture(c)
            h = page(c, r).replace('"vendor":', '"vendor": "unrelated", "vendor":', 1)
            self.assertIsNone(inspect(p, c[1], h))
        c = CASES[2]
        p, r = fixture(c)
        self.assertIsNone(inspect(p, c[1], page(c, r).replace('class="product-key"', 'class="related-key"')))


if __name__ == '__main__':
    unittest.main()
