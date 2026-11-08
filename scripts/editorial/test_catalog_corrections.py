"""Offline immutable new-article product correction contracts."""
import copy
import unittest
from ledger import fingerprint
from catalog_corrections import validated_context, validate_context, validate_bundle, validate_live_context


def raw():
    old = dict(id='p1', categoryId='tent', name='Tent', specs={'weight': 'wrong'},
               createdAt='2026-01-01T00:00:00+09:00', updatedAt='2026-09-01T00:00:00+09:00',
               sourceApi='real-catalog', yahooUrl='https://shopping.yahoo.co.jp/search?p=tent')
    new = dict(copy.deepcopy(old), specs={'weight': '350g'}, updatedAt='2026-11-08T12:00:00+09:00')
    return dict(baseProducts=[old], candidateProducts=[new], changeSummary='メーカー仕様に訂正')


class CorrectionTests(unittest.TestCase):
    def test_snapshot_hashes_and_no_input_mutation(self):
        value = raw(); prior = copy.deepcopy(value)
        ctx = validated_context(value)
        self.assertEqual(value, prior)
        self.assertEqual(validate_context(ctx), ctx)
        self.assertEqual(ctx['productPatches'][0]['baseHash'], fingerprint(value['baseProducts'][0]))
        self.assertEqual(ctx['productPatches'][0]['candidateHash'], fingerprint(value['candidateProducts'][0]))
        value['candidateProducts'][0]['name'] = 'mutated'
        self.assertEqual(ctx['candidateProducts'][0]['name'], 'Tent')

    def test_strict_and_protected_fields(self):
        for field, value in [('id', 'other'), ('categoryId', 'other'), ('createdAt', 'later'),
                             ('sourceApi', 'made-up'), ('yahooUrl', None), ('updatedAt', '2026-11-08T12:00:00')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                data = raw(); data['candidateProducts'][0][field] = value; validated_context(data)
        for mode in ['extra', 'missing', 'timestamp', 'empty', 'duplicate']:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                data = raw()
                if mode == 'extra': data['source'] = 'invented'
                if mode == 'missing': del data['candidateProducts'][0]['name']
                if mode == 'timestamp': data['candidateProducts'][0]['updatedAt'] = data['baseProducts'][0]['updatedAt']
                if mode == 'empty': data['baseProducts'] = data['candidateProducts'] = []
                if mode == 'duplicate':
                    data['baseProducts'] *= 2; data['candidateProducts'] *= 2
                validated_context(data)

    def test_yahoo_removal_and_tampered_derived_hash(self):
        data = raw(); data['candidateProducts'][0]['yahooUrl'] = ''
        ctx = validated_context(data)
        self.assertEqual(ctx['productPatches'][0]['fields']['yahooUrl'], '')
        ctx['productPatches'][0]['baseHash'] = '0' * 64
        with self.assertRaises(ValueError): validate_context(ctx)

    def test_bundle_and_live_baseline_binding(self):
        ctx = validated_context(raw())
        job = dict(kind='article', theme=dict(categoryId='tent', productIds=['p1']), catalogCorrectionContext=ctx)
        bundle = dict(article=dict(id='article-new', slug='new', categoryId='tent', productIds=['p1'], status='draft', publishedAt=None),
                      products=ctx['candidateProducts'], catalogCorrectionContext=copy.deepcopy(ctx))
        validate_bundle(job, bundle)
        validate_live_context(ctx, copy.deepcopy(ctx['baseProducts']))
        for mode in ['products', 'theme', 'revision', 'context', 'published']:
            j, b = copy.deepcopy(job), copy.deepcopy(bundle)
            if mode == 'products': b['products'][0]['name'] = 'substitution'
            if mode == 'theme': j['theme']['productIds'] = ['other']
            if mode == 'revision': j['kind'] = 'article_revision'
            if mode == 'context': b['catalogCorrectionContext']['changeSummary'] += 'changed'
            if mode == 'published': b['article']['status'] = 'published'
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_bundle(j, b)
        live = copy.deepcopy(ctx['baseProducts']); live[0]['specs'] = {'weight': 'drift'}
        with self.assertRaises(ValueError): validate_live_context(ctx, live)

    def test_slack_body_contains_full_product_diff(self):
        from presentation import article_body
        ctx = validated_context(raw())
        text = article_body(dict(article=dict(content='本文'), products=ctx['candidateProducts'], catalogCorrectionContext=ctx))
        for value in ['この記事の承認で、下記の商品情報も更新します。同じ商品を掲載する既存記事にも反映されます。', 'wrong', '350g', 'メーカー仕様に訂正']:
            self.assertIn(value, text)

    def test_slack_hides_zero_price_rating_and_technical_identifiers(self):
        from presentation import article_body
        data = raw()
        for key in ('price', 'rating'):
            data['baseProducts'][0][key] = 10
            data['candidateProducts'][0][key] = 0
        data['baseProducts'][0]['imageUrl'] = 'https://images.example/old.jpg'
        data['candidateProducts'][0]['imageUrl'] = 'https://images.example/new.jpg'
        ctx = validated_context(data)
        text = article_body(dict(article=dict(content='本文'), products=[], catalogCorrectionContext=ctx))
        self.assertIn('参考価格/評価の数値を表示せず販売店で確認', text)
        self.assertIn('https://images.example/old.jpg', text)
        self.assertIn('https://images.example/new.jpg', text)
        for value in ['p1', 'updatedAt', 'baseHash', '¥0', '無料']:
            self.assertNotIn(value, text)


if __name__ == '__main__': unittest.main()
