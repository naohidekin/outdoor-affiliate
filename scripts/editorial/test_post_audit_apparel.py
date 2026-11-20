"""Fresh apparel primary DOM must match the approved merchant binding offline."""
import copy
import hashlib
import html
import json
import unittest
from unittest.mock import patch
from urllib.parse import quote

from apparel_identity import inspect_apparel_page, public_binding
from post_publication_audit import PostPublicationAudit
import test_post_publication_audit as fixture


Z_TITLE = ('【楽天市場】モンベル 衣類 メンズ アンダーウエア L ポリエステル ライトグレー '
           'ZEO-LINE Middle Weght Round Neck RL1107704LGY mont-bell：RINRE （リンレ）')
C_TITLE = ('【楽天市場】モンベル mont-bell シャミース ジャケット メンズ #1114881 '
           'フリース ブラック BK グレー GY ダークグリーン DGN S M L XL 登山')


def setup_case(model):
    job, public_html = fixture.fixture()
    product = job['bundle']['products'][0]
    z = model == '1107704'
    product.update(name=("モンベル ジオライン M.W.ラウンドネックシャツ Men's" if z else
                         "モンベル シャミース ジャケット Men's"), brand='mont-bell', categoryId='wear',
        specs={'model': model, 'gender': "Men's", 'apparelClass': 'base-layer' if z else 'fleece',
               'optionState': 'selectable', 'material': 'ポリエステル', 'weight': '159g' if z else '262g',
               'rakutenOptionState': 'fixed' if z else 'selectable',
               'amazonOptionState': 'fixed', 'amazonVariant': 'B0DP4DNB51' if z else 'B0G75V4CC5',
               'amazonColor': 'ライトグレー' if z else 'グレー', 'amazonSize': 'L'})
    if z:
        product['specs'].update(rakutenVariant='fascino:rl1107704lgy', rakutenColor='ライトグレー', rakutenSize='L')
    sku = 'fascino:rl1107704lgy' if z else 'alice00:00brd5003'
    raku = 'https://item.rakuten.co.jp/' + sku.replace(':', '/') + '/'
    amazon = 'https://www.amazon.co.jp/dp/' + product['specs']['amazonVariant']
    product['affiliateUrl'] = 'https://hb.afl.rakuten.co.jp/ichiba/owner/shop?pc=' + quote(raku, safe='')
    product['amazonUrl'] = amazon + '?tag=owner-22'
    title = Z_TITLE if z else C_TITLE
    raku_html = ('<title>' + html.escape(title) + '</title><link rel="canonical" href="' + raku + '">'
        '<div itemscope itemtype="https://schema.org/Product">'
        '<meta itemprop="name" content="' + html.escape(title, quote=True) + '">'
        '<meta itemprop="sku" content="' + sku + '">'
        '<meta itemprop="image" content="https://tshop.r10s.jp/' + sku.replace(':', '/') + '.jpg"></div>')
    if not z:
        selectors = {'variantSelectors': [
            {'label': 'カラー', 'values': [{'value': c} for c in ('ブラック', 'グレー', 'ダークグリーン')]},
            {'label': 'サイズ', 'values': [{'value': s} for s in ('S', 'M', 'L', 'XL')]}]}
        raku_html += '<script>var data=' + json.dumps({'itemInfoSku': selectors}, ensure_ascii=False) + ';</script>'
    color = product['specs']['amazonColor']
    a_title = 'モンベル メンズ ' + model + ' (カラー：' + color + ')(サイズ：L)'
    amazon_html = ('<title>' + a_title + '</title><link rel="canonical" href="' + amazon + '">'
        '<span id="productTitle">' + a_title + '</span>'
        '<input name="ASIN" value="' + product['specs']['amazonVariant'] + '">'
        '<img id="landingImage" alt="モンベル メンズ ' + model + '" src="https://m.media-amazon.com/' + model + '.jpg">')
    refs = []
    for channel, url, source in (('rakuten', raku, raku_html), ('amazon', amazon, amazon_html)):
        binding = inspect_apparel_page(product, url, source, source_role='purchase', channel=channel)
        assert binding is not None, channel
        refs.append({'productId': product['id'], 'kind': 'purchase', 'channel': channel,
                     'url': url, 'apparelBinding': public_binding(binding)})
    job['bundle']['references'] = refs
    return job, public_html, {'rakuten': (raku, raku_html), 'amazon': (amazon, amazon_html)}


class ApparelAuditTests(unittest.TestCase):
    def audit(self, job, public_html, pages):
        calls = []
        class Catalog:
            def request(self, url, headers=None, **kwargs):
                calls.append(url)
                if url == fixture.SITE:
                    return {'url': url, 'status': 200, 'headers': {'content-type': 'text/html'}, 'body': public_html.encode()}
                if url == job['bundle']['products'][0]['imageUrl']:
                    return {'url': url, 'status': 200, 'headers': {'content-type': 'image/png'}, 'body': fixture.PNG}
                channel = 'amazon' if 'amazon.co.jp' in url else 'rakuten'
                final, body = pages[channel]
                return {'url': final, 'status': 200, 'headers': {'content-type': 'text/html; charset=utf-8'}, 'body': body.encode()}
        audit = PostPublicationAudit({'repo': '/unused'}, fixture.ENV, catalog=Catalog())
        with patch.object(audit, '_browser', return_value={'checks': [
                {'name': name, 'status': 'passed', 'reason': 'viewport_verified'} for name in ('desktop', 'mobile')]}):
            result = audit.check(job)
        self.assertTrue(calls)
        return result

    def decision(self, result, channel):
        return next(check for check in result['checks'] if check['name'] == 'destination.0.' + channel)

    def test_actual_sku_and_selectable_titles_pass_only_with_current_primary_dom(self):
        for model in ('1107704', '1114881'):
            job, public_html, pages = setup_case(model)
            before = copy.deepcopy(job)
            result = self.audit(job, public_html, pages)
            self.assertTrue(result['passed'], result['issues'])
            self.assertEqual(before, job)
            for channel in ('rakuten', 'amazon'):
                observation = next(o for o in result['merchantObservations'] if o['name'].endswith(channel))
                self.assertTrue(observation['primaryBindingVerified'])
                self.assertEqual(hashlib.sha256(pages[channel][1].encode()).hexdigest(), observation['primaryResponseSHA256'])
                self.assertEqual(model, observation['primaryBinding']['model'])

    def test_old_receipt_or_title_alone_never_substitutes_for_current_evidence(self):
        for model in ('1107704', '1114881'):
            for channel in ('rakuten', 'amazon'):
                job, public_html, pages = setup_case(model)
                url, source = pages[channel]
                title = 'モンベル メンズ ' + model + ' フリース アンダーウエア L'
                pages[channel] = (url, '<title>' + title + '</title>')
                result = self.audit(job, public_html, pages)
                self.assertEqual('unverified', self.decision(result, channel)['status'])

    def test_missing_duplicate_or_inconsistent_approved_binding_never_passes(self):
        for mode in ('missing', 'duplicate', 'invalid', 'wrong_page'):
            job, public_html, pages = setup_case('1114881')
            ref = job['bundle']['references'][0]
            if mode == 'missing':
                job['bundle']['references'].pop(0)
            elif mode == 'duplicate':
                job['bundle']['references'].append(copy.deepcopy(ref))
            elif mode == 'invalid':
                ref['apparelBinding']['model'] = '1114883'
            else:
                ref['url'] = 'https://item.rakuten.co.jp/another/item/'
            result = self.audit(job, public_html, pages)
            self.assertEqual('unverified', self.decision(result, 'rakuten')['status'])

    def test_wrong_fixed_color_size_gender_and_sku_are_not_accepted(self):
        replacements = [('ライトグレー', 'ブラック'), ('アンダーウエア L', 'アンダーウエア M'),
                        ('メンズ', 'レディース'), ('fascino:rl1107704lgy', 'fascino:rl1114881gy')]
        for old, new in replacements:
            job, public_html, pages = setup_case('1107704')
            url, source = pages['rakuten']
            pages['rakuten'] = (url, source.replace(old, new))
            result = self.audit(job, public_html, pages)
            self.assertNotEqual('passed', self.decision(result, 'rakuten')['status'])

    def test_changed_current_selectable_options_fail_against_approved_binding(self):
        for old, new in (('ブラック', 'ブルー'), ('XL', 'XXL')):
            job, public_html, pages = setup_case('1114881')
            url, source = pages['rakuten']
            pages['rakuten'] = (url, source.replace(old, new))
            result = self.audit(job, public_html, pages)
            self.assertEqual('failed', self.decision(result, 'rakuten')['status'])

    def test_changed_current_primary_image_binding_does_not_reuse_old_receipt(self):
        job, public_html, pages = setup_case('1114881')
        url, source = pages['amazon']
        pages['amazon'] = (url, source.replace('/1114881.jpg', '/1114881-other.jpg'))
        result = self.audit(job, public_html, pages)
        self.assertEqual('failed', self.decision(result, 'amazon')['status'])
        observation = next(o for o in result['merchantObservations'] if o['name'].endswith('amazon'))
        self.assertFalse(observation['primaryBindingVerified'])

    def test_amazon_wrong_asin_color_size_and_gender_cannot_pass(self):
        for old, new in (('B0G75V4CC5', 'B0DP4DNB51'), ('グレー', 'ブラック'),
                         ('サイズ：L', 'サイズ：M'), ('メンズ', 'レディース')):
            job, public_html, pages = setup_case('1114881')
            url, source = pages['amazon']
            pages['amazon'] = (url, source.replace(old, new))
            result = self.audit(job, public_html, pages)
            self.assertNotEqual('passed', self.decision(result, 'amazon')['status'])

    def test_route_asin_and_affiliate_tag_checks_remain_mandatory(self):
        for channel, final in (('rakuten', 'https://item.rakuten.co.jp/other/item/'),
                               ('amazon', 'https://www.amazon.co.jp/dp/B0DP4DNB51'),
                               ('amazon', 'https://www.amazon.co.jp/dp/B0G75V4CC5?tag=wrong-22')):
            job, public_html, pages = setup_case('1114881')
            pages[channel] = (final, pages[channel][1])
            self.assertEqual('failed', self.decision(self.audit(job, public_html, pages), channel)['status'])


if __name__ == '__main__':
    unittest.main()
