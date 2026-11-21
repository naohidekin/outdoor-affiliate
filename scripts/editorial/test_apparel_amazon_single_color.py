"""Amazon size-only twister may use one independently scoped primary color fact."""
import html
import json
import unittest

from apparel_identity import inspect_apparel_page


ASIN = 'B09L6W6NFJ'
URL = 'https://www.amazon.co.jp/dp/' + ASIN


def product():
    return {
        'id': 'base-layer-montbell-1107654',
        'name': "Super Merino Wool M.W. Round Neck Shirt Men's",
        'brand': 'mont-bell',
        'categoryId': 'base-layer',
        'specs': {
            'model': '1107654', 'apparelClass': 'base-layer', 'gender': "Men's",
            'optionState': 'selectable', 'amazonOptionState': 'fixed',
            'amazonVariant': ASIN, 'amazonColor': 'ブラック', 'amazonSize': 'M',
        },
        'imageUrl': 'https://webshop.montbell.jp/images/1107654-bk.jpg',
    }


def state(*, selected_asin=ASIN, second_selected=False, color_state=None,
          extra_dimension=None):
    sizes = [{'defaultAsin': selected_asin, 'dimensionValueState': 'SELECTED',
              'dimensionValueDisplayText': 'M'}]
    if second_selected:
        sizes.append({'defaultAsin': 'B09L6W5FKV', 'dimensionValueState': 'SELECTED',
                      'dimensionValueDisplayText': 'L'})
    dimensions = {'size_name': sizes}
    if color_state is not None:
        dimensions['color_name'] = color_state
    if extra_dimension is not None:
        dimensions['style_name'] = extra_dimension
    return {'sortedDimValuesForAllDims': dimensions}


def source(*, twister=None, colors=('ブラック',), primary=True,
           recommendation_color=None, hidden_asin=ASIN):
    descriptor = html.escape(json.dumps(
        {'key': 'desktop-twister-sort-filter-data'}), quote=True)
    rows = ''.join(
        '<tr><th class="voyager-ns-desktop-table-label">カラー</th>'
        f'<td class="voyager-ns-desktop-table-value">{color}</td></tr>'
        for color in colors)
    primary_table = ('<div id="voyagerNorthstarBTF">'
                     '<div id="voyagerNorthstarATFData_feature_div">'
                     '<table class="a-keyvalue voyager-ns-desktop-table">'
                     + rows + '</table></div></div>') if primary else ''
    recommendation = ('<aside id="recommendations"><table class="voyager-ns-desktop-table">'
                      '<tr><th>カラー</th><td>' + recommendation_color
                      + '</td></tr></table></aside>') if recommendation_color else ''
    title = "[モンベル] ブラック インナー Men's #1107654"
    return ('<html><body id="dp"><div id="dp-container">'
            '<link rel="canonical" href="https://www.amazon.co.jp/item/dp/B0CXTB3RD2">'
            f'<span id="productTitle">{title}</span>'
            f'<input type="hidden" name="ASIN" value="{hidden_asin}">'
            '<img id="landingImage" alt="[モンベル] Men&#39;s #1107654" '
            'data-old-hires="https://m.media-amazon.com/images/I/exact.jpg">'
            f'<script type="a-state" data-a-state="{descriptor}">'
            f'{json.dumps(twister if twister is not None else state())}</script>'
            + primary_table + recommendation + '</div></body></html>')


class AmazonSinglePrimaryColorTests(unittest.TestCase):
    def inspect(self, body):
        return inspect_apparel_page(product(), URL, body,
                                    source_role='purchase', channel='amazon')

    def test_observed_size_only_twister_binds_one_primary_color_fact(self):
        binding = self.inspect(source())
        self.assertIsNotNone(binding)
        self.assertEqual((ASIN, ['ブラック'], ['M']),
                         (binding['merchantVariant'], binding['colors'], binding['sizes']))
        self.assertEqual('amazon-primary-product-dom', binding['sourceKind'])

    def test_selected_size_must_bind_exactly_one_matching_asin(self):
        for body in (source(twister=state(selected_asin='B09L6W5FKV')),
                     source(twister=state(second_selected=True)),
                     source(hidden_asin='B09L6W5FKV')):
            with self.subTest(body=body[:80]):
                self.assertIsNone(self.inspect(body))

    def test_present_but_malformed_color_dimension_never_uses_dom_fallback(self):
        malformed = [{'dimensionValueState': 'SELECTED',
                      'dimensionValueDisplayText': 'ブラック'}]
        self.assertIsNone(self.inspect(source(twister=state(color_state=malformed))))

    def test_unrelated_recommendation_or_title_color_is_not_primary_evidence(self):
        body = source(primary=False, recommendation_color='ブラック')
        self.assertIsNone(self.inspect(body))

    def test_absent_or_conflicting_primary_color_facts_fail_closed(self):
        for colors in ((), ('レッド',), ('ブラック / レッド',),
                       ('ブラック', 'レッド')):
            with self.subTest(colors=colors):
                self.assertIsNone(self.inspect(source(colors=colors)))

    def test_any_other_unresolved_twister_dimension_is_ambiguous(self):
        unresolved = [{'dimensionValueState': 'AVAILABLE',
                       'defaultAsin': 'B000000000',
                       'dimensionValueDisplayText': '長袖'}]
        self.assertIsNone(self.inspect(source(
            twister=state(extra_dimension=unresolved))))


if __name__ == '__main__':
    unittest.main()
