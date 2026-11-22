"""Sanitized observed FUM0422 structure; no network, prices or availability claims."""
import copy
import hashlib
import json
import unittest

from apparel_identity import (inspect_apparel_page, claim_binding, public_binding,
                              binding_matches_product, _brand_matches, _brand_matches_in_text,
                              _amazon_primary_model_matches, _exact_token, apparel_contract)


URL = ('https://www.finetrack.com/c/wear-drylayer/wear-drylayer-basic/'
       'wear-drylayer-basic-men/FUM0422')
IMAGE = ('https://finetrack.itembox.cloud/product/005/000000000524/'
         '000000000524-01.jpg?size=l&t=20240712091418&w=NTUw')
THUMB = IMAGE.replace('size=l', 'size=xs').replace('w=NTUw', 'w=MTAw')
WEARING_IMAGE = ('https://finetrack.itembox.cloud/product/005/000000000524/'
                 '000000000524-11.jpg?size=l&w=NTUw&t=20240321151606')
TITLE = 'ドライレイヤーベーシックＴ'


def product():
    return dict(id='fum0422', brand='finetrack', name=TITLE, categoryId='base-layer',
                imageUrl=IMAGE, specs=dict(model='FUM0422', gender="Men's",
                    material='ポリエステル100%', weight='46g', optionState='selectable'))


def group():
    return {'@context': 'https://schema.org', '@type': 'ProductGroup', '@id': URL,
            'url': URL, 'name': TITLE, 'productGroupID': '524',
            'brand': {'@type': 'Brand', 'name': 'finetrack'},
            'hasVariant': [
                {'@type': 'Product', '@id': URL + '#SBK', 'productID': '524h1v1',
                 'sku': '524h1v1', 'gtin13': '4573406384235', 'color': 'ブラック',
                 'size': 'S', 'name': TITLE + ' S ブラック',
                 'image': THUMB.replace('&', '&amp;').replace('=', '&#x3D;')},
                {'@type': 'Product', '@id': URL + '#MBK', 'productID': '524h2v1',
                 'sku': '524h2v1', 'gtin13': '4573406384242', 'color': 'ブラック',
                 'size': 'M', 'name': TITLE + ' M ブラック', 'image': THUMB}]}


def fixture(root=None):
    # Exact observed selectors and primary summary's nested two-div fact rows.
    return '''<html><head><link rel="canonical" href="URL"></head>
<body id="fs_ProductDetails" class="fs-body-product fs-body-product-FUM0422">
<form id="fs_form"><div class="fs-l-productLayout fs-system-product" data-product-id="524">
<div class="fs-c-productCarouselMainImage__carousel" id="fs_productCarouselMainImage">
<figure class="fs-c-productCarouselMainImage__image" aria-hidden="true">
<img src="IMAGE" alt="FUM0422-BK"></figure></div>
<div class="fs-c-productNumber"><span class="fs-c-productNumber__number">FUM0422</span></div>
<h1 class="fs-c-productNameHeading"><span class="fs-c-productNameHeading__name">TITLE</span></h1>
<div class="fs-c-productMarks"><span class="c-label--mens fs-c-productMark__mark">
<span class="fs-c-productMark__label">MEN&#x27;S</span></span>
<span class="fs-c-productMark__label">返品交換OK</span></div></div></form>
<div class="l-container"><div class="pro-detailOutline">
<h2 class="pro-detailHeading" data-en="Detail">商品詳細</h2>
<div><div><div>
<div><div>重量</div><div>46g</div></div>
<div><div>素材</div><div>ポリエステル100%</div></div>
</div></div></div><div class="ftdl-detail">詳細の広告文は抽出しない</div></div></div>
<aside>関連商品 KUM04E1 WOMEN'S 素材別物 重量999g</aside>
<script type="application/ld+json">JSON</script></body></html>'''.replace(
        'URL', URL).replace('IMAGE', IMAGE.replace('&', '&amp;')).replace(
        'TITLE', TITLE).replace('JSON', json.dumps(root if root is not None else group(), ensure_ascii=False))


class FinetrackPrimaryDOMTests(unittest.TestCase):
    def test_observed_wearing_example_is_selectable_primary_gallery_only(self):
        node = '<figure class="fs-c-productCarouselMainImage__image" aria-hidden="true"><img src="' + WEARING_IMAGE.replace('&', '&amp;') + '" alt=""></figure>'
        html = fixture().replace('</figure></div>', '</figure>' + node + '</div>', 1)
        binding = self.inspect(html, image=WEARING_IMAGE)
        self.assertIsNotNone(binding)
        self.assertEqual('primary-product-wearing-example', binding['imageScope'])
        self.assertEqual(WEARING_IMAGE, binding['imageScopeUrl'])
        self.assertIn(WEARING_IMAGE, binding['imageUrls'])
        self.assertTrue(binding_matches_product(public_binding(binding), product()))
        unscoped = public_binding(binding)
        del unscoped['imageScope']
        del unscoped['imageScopeUrl']
        self.assertFalse(binding_matches_product(unscoped, product()))
        for row in binding['manufacturerVariants']:
            self.assertNotIn(WEARING_IMAGE, row['imageUrls'])
        # Exact observed query and primary membership; no inferred files or URLs.
        self.assertIsNone(self.inspect(image=WEARING_IMAGE))
        moved = fixture().replace('<aside>', '<aside>' + node)
        self.assertIsNone(self.inspect(moved, image=WEARING_IMAGE))
        related_gallery = '<div id="fs_productCarouselMainImage">' + node + '</div>'
        self.assertIsNone(self.inspect(fixture().replace('<aside>', '<aside>' + related_gallery), image=WEARING_IMAGE))
        for bad in (WEARING_IMAGE.replace('524-11', '525-11'),
                    WEARING_IMAGE.replace('-11.jpg', '-10.jpg'),
                    WEARING_IMAGE.replace('size=l', 'size=xl'), WEARING_IMAGE + '&extra=1'):
            self.assertIsNone(self.inspect(html.replace(WEARING_IMAGE.replace('&', '&amp;'), bad.replace('&', '&amp;')), image=bad))
            self.assertIsNone(self.inspect(html, image=bad))
        self.assertIsNone(self.inspect(html.replace('>FUM0422</span>', '>KUM04E1</span>'), image=WEARING_IMAGE))
        self.assertIsNone(self.inspect(html.replace('<img src="' + WEARING_IMAGE.replace('&', '&amp;'), '<img hidden src="' + WEARING_IMAGE.replace('&', '&amp;')), image=WEARING_IMAGE))
        self.assertIsNone(self.inspect(html.replace('</figure></div>', '</figure>' + node + '</div>', 1), image=WEARING_IMAGE))
        fixed = product()
        fixed['specs'].update(optionState='fixed', color='ブラック', size='S')
        self.assertIsNone(self.inspect(html, current=fixed, image=WEARING_IMAGE))
        fixed_binding = self.inspect(html, current=fixed)
        self.assertIsNotNone(fixed_binding)
        self.assertNotIn(WEARING_IMAGE, fixed_binding['imageUrls'])
        self.assertNotIn('imageScope', fixed_binding)
        forged = public_binding(fixed_binding)
        forged.update(imageScope='primary-product-wearing-example', imageScopeUrl=WEARING_IMAGE)
        self.assertFalse(binding_matches_product(forged, fixed))
        unscoped_fixed = public_binding(fixed_binding)
        unscoped_fixed['imageUrls'] = [WEARING_IMAGE]
        self.assertFalse(binding_matches_product(unscoped_fixed, fixed))

    def test_amazon_finetrack_parenthetical_slash_separator_is_model_specific(self):
        contract = apparel_contract(product())
        title = '[ファイントラック] ドライレイヤーベーシックＴ(メンズ)/FUM0422'
        self.assertFalse(_exact_token(title, 'FUM0422'))
        for text in (title, title.replace('(メンズ)/FUM0422', '（メンズ）／ＦＵＭ０４２２')):
            self.assertTrue(_amazon_primary_model_matches(text, contract))
        for text in (title + '-OD', title + 'A', title + '/extra', title + '.jpg',
                     title.replace('/FUM0422', '/XFUM0422'),
                     title.replace('/FUM0422', '/pathprefixFUM0422'),
                     title.replace('(メンズ)', '(related)'),
                     title.replace('(メンズ)', ''), title.replace('FUM0422', 'FUM04220')):
            self.assertFalse(_amazon_primary_model_matches(text, contract), text)
        for changes in ({'brand': 'MILLET'}, {'brand': "Arc'teryx"}, {'model': 'FUM0423'},
                        {'gender': "Women's"}):
            other = dict(contract, **changes)
            text = title.replace('FUM0422', other['model'])
            self.assertFalse(_amazon_primary_model_matches(text, other))

    def test_amazon_separator_preserves_child_and_fixed_option_validation(self):
        from test_apparel_amazon_single_color import source
        current = product()
        asin = 'B085FTS8VR'
        current['specs'].update(amazonOptionState='fixed', amazonVariant=asin,
                                amazonColor='BK', amazonSize='S')
        dimensions = {'sortedDimValuesForAllDims': {
            'size_name': [{'defaultAsin': asin, 'dimensionValueState': 'SELECTED',
                           'dimensionValueDisplayText': 'S'}],
            'color_name': [{'defaultAsin': asin, 'dimensionValueState': 'SELECTED',
                            'dimensionValueDisplayText': 'BK'}]}}
        title = '[ファイントラック] ドライレイヤーベーシックＴ(メンズ)/FUM0422'
        body = source(twister=dimensions, hidden_asin=asin).replace(
            "[モンベル] ブラック インナー Men's #1107654", title).replace(
            '[モンベル] Men&#39;s #1107654', title)
        url = 'https://www.amazon.co.jp/dp/' + asin
        def inspect(html, p=current):
            return inspect_apparel_page(p, url, html, source_role='purchase', channel='amazon')
        binding = inspect(body)
        self.assertIsNotNone(binding)
        self.assertEqual((asin, ['BK'], ['S']),
                         (binding['merchantVariant'], binding['colors'], binding['sizes']))
        for suffix in ('-OD', 'X', '/other'):
            self.assertIsNone(inspect(body.replace('FUM0422', 'FUM0422' + suffix)))
            bad_title = title + suffix
            self.assertIsNone(inspect(body.replace('id="productTitle">' + title,
                                                   'id="productTitle">' + bad_title)))
            self.assertIsNone(inspect(body.replace('alt="' + title + '"',
                                                   'alt="' + bad_title + '"')))
        for field, value in (('amazonVariant', 'B085G79Q2H'), ('amazonColor', 'PA'),
                             ('amazonSize', 'M'), ('amazonOptionState', 'selectable')):
            other = copy.deepcopy(current)
            other['specs'][field] = value
            self.assertIsNone(inspect(body, other))

    def test_approved_brand_aliases_match_both_helpers_without_fuzzy_names(self):
        groups = (('finetrack', 'ファイントラック'), ('MILLET', 'ミレー'),
                  ("Arc'teryx", 'Arc’teryx', 'arcteryx', 'アークテリクス'))
        for aliases in groups:
            for expected in aliases:
                for actual in aliases:
                    self.assertTrue(_brand_matches(actual, expected))
                    self.assertTrue(_brand_matches_in_text('[' + actual + '] 商品 FUM0422', expected))
                for bad in ('fake' + aliases[0], aliases[0] + 'ish', 'unrelated'):
                    self.assertFalse(_brand_matches(bad, expected))
                    self.assertFalse(_brand_matches_in_text('[' + bad + '] 商品', expected))
                for bad in ('偽' + aliases[-1], aliases[-1] + '風'):
                    self.assertFalse(_brand_matches_in_text('[' + bad + '] 商品', expected))
        self.assertTrue(_brand_matches_in_text(
            '[ファイントラック] ドライレイヤーベーシックＴ(メンズ)/FUM0422', 'finetrack'))
        for actual, expected in (('fine track', 'finetrack'), ('Milletish', 'ミレー'),
                                 ('Arcteryxx', 'アークテリクス'), ('ファイントラツク', 'finetrack')):
            self.assertFalse(_brand_matches(actual, expected))
            self.assertFalse(_brand_matches_in_text('[' + actual + '] 商品', expected))

    def inspect(self, html=None, current=None, image=IMAGE, url=URL):
        return inspect_apparel_page(current or product(), url, fixture() if html is None else html, image)

    def test_observed_primary_facts_variants_and_retained_binding(self):
        binding = self.inspect()
        self.assertIsNotNone(binding)
        self.assertEqual(('FUM0422', "Men's", 'ポリエステル100%', '46g'),
                         tuple(binding[k] for k in ('model', 'gender', 'fabric', 'weight')))
        self.assertEqual(['ブラック'], binding['colors'])
        self.assertEqual(['M', 'S'], binding['sizes'])
        self.assertEqual(['524h1v1', '524h2v1'], [r['sku'] for r in binding['manufacturerVariants']])
        self.assertEqual('4573406384235', binding['manufacturerVariants'][0]['gtin13'])
        self.assertIn(IMAGE, binding['imageUrls'])
        self.assertIn(THUMB, binding['imageUrls'])
        self.assertTrue(binding_matches_product(public_binding(binding), product()))
        self.assertIsNotNone(claim_binding(binding, 'material', 'ポリエステル100%'))
        self.assertIsNone(claim_binding(binding, 'weight', '999g'))
        excerpt = binding['manufacturerExcerpt']
        self.assertEqual(hashlib.sha256(excerpt['text'].encode()).hexdigest(), excerpt['excerptSHA256'])
        self.assertNotIn('広告', excerpt['text'])
        self.assertNotIn('KUM04E1', excerpt['text'])
        self.assertNotIn('manufacturerExcerpt', public_binding(binding))

    def test_exact_url_host_canonical_model_and_primary_scope(self):
        for url in (URL + '?x=1', URL + '/', URL.replace('www.', ''),
                    URL.replace('finetrack.com', 'finetrack.com.example'),
                    URL.replace('FUM0422', 'KUM04E1')):
            with self.subTest(url=url):
                self.assertIsNone(self.inspect(url=url))
        for old, new in (('rel="canonical"', 'rel="alternate"'),
                         ('href="' + URL, 'href="' + URL + '0'),
                         ('>FUM0422</span>', '>KUM04E1</span>'),
                         ('data-product-id="524"', 'data-product-id="525"'),
                         ('class="fs-l-productLayout', 'class="unrelated'),
                         ('class="pro-detailOutline"', 'class="related"'),
                         ('id="fs_ProductDetails"', 'id="unrelated"')):
            with self.subTest(old=old):
                self.assertIsNone(self.inspect(fixture().replace(old, new)))

    def test_missing_wrong_hidden_or_conflicting_primary_facts_fail_closed(self):
        for old, new in (("MEN&#x27;S", "WOMEN&#x27;S"), ('46g', '47g'),
                         ('ポリエステル100%', 'ナイロン100%'),
                         ('>重量</div>', '>参考重量</div>'),
                         ('>素材</div>', '>関連素材</div>'),
                         ('class="c-label--mens', 'hidden class="c-label--mens'),
                         ('>46g</div>', ' hidden>46g</div>')):
            with self.subTest(old=old):
                self.assertIsNone(self.inspect(fixture().replace(old, new)))
        current = product()
        current['specs']['gender'] = "Women's"
        self.assertIsNone(self.inspect(current=current))
        missing = fixture().replace('<div><div>素材</div><div>ポリエステル100%</div></div>', '')
        unrelated = '<div><div>素材</div><div>ポリエステル100%</div></div>'
        self.assertIsNone(self.inspect(missing.replace('関連商品 KUM04E1', unrelated + '関連商品 KUM04E1')))
        current = product()
        del current['specs']['material']
        self.assertIsNone(self.inspect(missing, current=current))
        current = product()
        del current['specs']['weight']
        self.assertIsNone(self.inspect(fixture().replace('46g', '999g'), current=current))

    def test_multiple_groups_and_primary_regions_are_ambiguous(self):
        for extra in ('<script type="application/ld+json">' + json.dumps(group()) + '</script>',
                      '<div class="fs-l-productLayout" data-product-id="524"></div>',
                      '<div class="pro-detailOutline"></div>',
                      '<link rel="canonical" href="' + URL + '">'):
            self.assertIsNone(self.inspect(fixture().replace('</body>', extra + '</body>')))

    def test_child_identity_must_belong_to_exact_group_and_option(self):
        for changes in ({'@id': URL.replace('FUM0422', 'KUM04E1') + '#SBK'},
                        {'model': 'KUM04E1'}, {'gender': "Women's"},
                        {'productID': '525h1v1'}, {'sku': '525h1v1'},
                        {'gtin13': '4573406384230'}, {'color': 'ペイルグレー'},
                        {'size': ''}, {'size': 'M'}, {'url': URL + '0'},
                        {'name': '関連商品 S ブラック'}, {'brand': {'name': 'Other'}},
                        {'hasVariant': [{'@type': 'Product'}]}):
            root = group()
            root['hasVariant'][0].update(changes)
            with self.subTest(changes=changes):
                self.assertIsNone(self.inspect(fixture(root)))
        root = group()
        root['hasVariant'].append(copy.deepcopy(root['hasVariant'][0]))
        self.assertIsNone(self.inspect(fixture(root)))
        for changes in ({'productGroupID': '525'}, {'model': 'KUM04E1'},
                        {'gender': "Women's"}, {'material': '別物'},
                        {'url': URL + '0'}, {'@id': URL + '#other'}):
            root = group()
            root.update(changes)
            self.assertIsNone(self.inspect(fixture(root)))

    def test_missing_gtin_is_explicit_and_never_fabricated(self):
        root = group()
        child = root['hasVariant'][1]
        child.update({'@id': URL + '#XXPA', 'sku': '524h5v2', 'productID': '524h5v2',
                      'size': 'XXL', 'color': 'ペイルグレー', 'name': TITLE + ' XXL ペイルグレー',
                      'image': THUMB.replace('01.jpg', '03.jpg').replace('091418', '091420')})
        del child['gtin13']
        html = fixture(root).replace('</figure>', '</figure><figure>'
            '<img alt="FUM0422-PA" src="' + IMAGE.replace('01.jpg', '03.jpg').replace('091418', '091420')
            + '"></figure>', 1)
        binding = self.inspect(html)
        row = binding['manufacturerVariants'][1]
        self.assertNotIn('gtin13', row)
        self.assertEqual(['gtin13'], row['missingFields'])
        root = group()
        root['hasVariant'][0]['gtin13'], root['hasVariant'][1]['gtin13'] = (
            root['hasVariant'][1]['gtin13'], root['hasVariant'][0]['gtin13'])
        self.assertIsNone(self.inspect(fixture(root)))
        root = group()
        del root['hasVariant'][1]['gtin13']
        self.assertIsNone(self.inspect(fixture(root)))

    def test_images_require_exact_decoded_url_or_primary_gallery_proof(self):
        self.assertIsNotNone(self.inspect(image=IMAGE.replace('&', '&amp;')))
        for image in (IMAGE.replace('01.jpg', '03.jpg'), IMAGE + '&extra=1',
                      '\n' + IMAGE, IMAGE + '\t',
                      IMAGE.replace('size=l', 'size=xl'), IMAGE.replace('524/', '525/')):
            self.assertIsNone(self.inspect(image=image))
        root = group()
        root['hasVariant'][0]['image'] = THUMB.replace('01.jpg', '03.jpg')
        self.assertIsNone(self.inspect(fixture(root)))
        for old, new in (('alt="FUM0422-BK"', 'alt="KUM04E1-BK"'),
                         ('<img src=', '<img hidden src='),
                         ('id="fs_productCarouselMainImage"', 'id="recommendations"')):
            self.assertIsNone(self.inspect(fixture().replace(old, new)))

    def test_fixed_variant_has_only_its_own_options_and_images(self):
        current = product()
        current['specs'].update(optionState='fixed', color='ブラック', size='S')
        binding = self.inspect(current=current)
        self.assertEqual('524h1v1', binding['sourceVariant'])
        self.assertEqual(['S'], binding['sizes'])
        self.assertEqual(1, len(binding['manufacturerVariants']))
        self.assertTrue(binding_matches_product(public_binding(binding), current))
        for changes in ({'size': 'XL'}, {'color': 'ペイルグレー'}, {'color': ''}):
            bad = copy.deepcopy(current)
            bad['specs'].update(changes)
            self.assertIsNone(self.inspect(current=bad))

    def test_related_jsonld_never_supplies_missing_primary_evidence(self):
        extra = '<script type="application/ld+json">' + json.dumps({
            '@type': 'Product', 'url': URL, 'model': 'FUM0422', 'gender': "Men's",
            'brand': {'name': 'finetrack'}, 'color': 'ブラック', 'size': 'S',
            'material': 'ポリエステル100%', 'weight': '46g', 'image': IMAGE}) + '</script>'
        html = fixture().replace('>FUM0422</span>', '>KUM04E1</span>')
        self.assertIsNone(self.inspect(html.replace('</body>', extra + '</body>')))
        self.assertIsNone(inspect_apparel_page(product(), URL, fixture(), IMAGE,
                                              source_role='purchase', channel='rakuten'))

    def test_valueless_attributes_do_not_crash_or_prove_missing_fields(self):
        self.assertIsNotNone(self.inspect(fixture().replace('<aside>', '<aside class>')))
        self.assertIsNone(self.inspect(fixture().replace('class="c-label--mens fs-c-productMark__mark"', 'class')))


if __name__ == '__main__':
    unittest.main()
