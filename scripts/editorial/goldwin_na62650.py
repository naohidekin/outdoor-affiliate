"""Offline manufacturer extraction for the observed Goldwin NA62650 page.

No JS evaluation, transport, catalogue mutation or generic Goldwin support.
Only the exact manufacturer route is wired; merchant identity remains separate.
"""
import re
from urllib.parse import urlsplit

from apparel_identity import (ApparelIdentityError, apparel_contract, _norm,
                              _FinetrackDOM, _ft_inside, _ft_class, _ft_text)

URL = 'https://www.goldwin.co.jp/ap/item/i/m/NA62650'
FABRIC = '＜身生地＞Polartec 300 Micro（ポリエステル100％）＜別布＞Recycled Taslan Nylon Cloth（ナイロン100％）'
WEIGHT = '約710g（Lサイズ）'
_COLORS = {'AW18': ('FK', 'フォッシルアイボリー×ブラック'),
           'BC16': ('SK', 'サミットゴールド×ブラック'),
           'V901': ('K', 'ブラック'), 'W239': ('Z', 'ミックスグレー')}
_SIZES = {'S', 'M', 'L', 'XL', 'XXL'}
_ALT = 'THE NORTH FACE(ザ・ノース・フェイス) ｜デナリジャケット（メンズ）'


def _one(values):
    if len(values) != 1:
        raise ValueError('missing or ambiguous primary DOM')
    return values[0]


def _photo(value):
    if not isinstance(value, str) or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return None
    value = 'https:' + value if value.startswith('//') else value
    p = urlsplit(value)
    if (p.scheme != 'https' or p.netloc != 'itemimg.goldwin.co.jp' or p.query or p.fragment
            or not re.fullmatch(r'/itemimg/GDW01/A0GDW0001QCX/02_(?:AW18|BC16|V901|W239)(?:-750)?\.jpg', p.path)):
        return None
    return value


def retained_options_match(binding):
    """Check this model's retained options/photos without extending the projection."""
    colors, sizes = binding.get('colors'), binding.get('sizes')
    color_codes = {value[1]: code for code, value in _COLORS.items()}
    if (not isinstance(colors, list) or not colors
            or any(not isinstance(v, str) or v not in color_codes for v in colors)
            or len(set(colors)) != len(colors)
            or not isinstance(sizes, list) or not sizes
            or any(not isinstance(v, str) or v not in _SIZES for v in sizes)
            or len(set(sizes)) != len(sizes)):
        return False
    if 'imageUrls' in binding:
        images = binding['imageUrls']
        expected = {'https://itemimg.goldwin.co.jp/itemimg/GDW01/A0GDW0001QCX/02_'
                    + color_codes[color] + '.jpg' for color in colors}
        if (not isinstance(images, list) or not images
                or any(not isinstance(v, str) for v in images)
                or len(set(images)) != len(images) or set(images) != expected):
            return False
    return True


def inspect_goldwin_na62650(product, page_url, html, image_url=None):
    """Prove selectable manufacturer facts/options only; selected SKU stays unknown."""
    try:
        c = apparel_contract(product)
        if (page_url != URL or not isinstance(html, str) or c['model'] != 'NA62650'
                or c['class'] != 'fleece' or _norm(c['gender']) not in ("men's", 'メンズ', 'male')
                or _norm(c['brand']) not in ('the north face', 'thenorthface', 'ザ・ノース・フェイス', 'ザノースフェイス')
                or c['optionState'] != 'selectable'):
            return None
        p = _FinetrackDOM(html)
        canonical = [n['attrs'].get('href') for n in p.nodes if n['tag'] == 'link'
                     and n['attrs'].get('rel') == 'canonical']
        body = _one([n for n in p.nodes if n['tag'] == 'body'])
        main = _one([n for n in p.nodes if n['attrs'].get('id') == 'item_detail'])
        if canonical != [URL] or body['attrs'].get('id') != 'A0GDW0001QCX' or not _ft_inside(main, body):
            return None
        local = [n for n in p.nodes if _ft_inside(n, main)]
        if main['hidden'] or not main['closed']:
            return None

        def by_class(cls):
            return [n for n in local if _ft_class(n, cls)]

        def text(cls):
            node = _one(by_class(cls))
            if node['hidden'] or not node['closed']:
                raise ValueError('nonvisible fact')
            return _ft_text(node)

        if (text('item_detail_productname') != 'デナリジャケット（メンズ）'
                or text('item_detail_mkcode') != 'NA62650'
                or text('item_detail_sex') != 'メンズ' or text('item_detail_category') != 'フリース'):
            return None
        table = _one(by_class('item_detail_table'))
        if table['hidden'] or not table['closed']:
            return None
        facts, label = {}, None
        for n in local:
            if not _ft_inside(n, table) or n['tag'] not in ('dt', 'dd'):
                continue
            if n['hidden'] or not n['closed']:
                return None
            if n['tag'] == 'dt':
                if label is not None:
                    return None
                label = _ft_text(n)
            else:
                if not label or label in facts:
                    return None
                facts[label], label = _ft_text(n), None
        if label is not None or facts.get('Fabric') != FABRIC or facts.get('Weight') != WEIGHT:
            return None
        if any(_norm(c[k]) != _norm(v) for k, v in (('fabric', FABRIC), ('weight', WEIGHT)) if k in c):
            return None
        right = _one([n for n in local if n['attrs'].get('id') == 'item_detail_right'])
        selectors = _one([n for n in local if n['attrs'].get('id') == 'select_color_size_area'])
        left = _one([n for n in local if n['attrs'].get('id') == 'item_detail_left'])
        if (not _ft_inside(selectors, right) or any(n['hidden'] or not n['closed'] for n in (right, selectors, left))):
            return None
        colors, sizes, images = [], [], []
        for n in local:
            if n['tag'] != 'input' or not _ft_inside(n, selectors):
                continue
            a = n['attrs']
            if _ft_class(n, 'cart_color_radio'):
                code = a.get('value')
                if (n['hidden'] or a.get('name') != 'color' or code not in _COLORS
                        or (a.get('dispcolorcode'), a.get('vcbname')) != _COLORS[code]
                        or a['vcbname'] in colors):
                    return None
                colors.append(a['vcbname'])
                slides = [s for s in local if _ft_inside(s, left) and _ft_class(s, 'variationImg')
                          and s['attrs'].get('data-vcbcode') == code]
                slide = _one(slides)
                if slide['hidden'] or not slide['closed']:
                    return None
                img = _one([im for im in local if im['tag'] == 'img' and _ft_inside(im, slide)])
                if img['hidden'] or img['attrs'].get('alt') != _ALT:
                    return None
                photo = _photo(img['attrs'].get('bigimage'))
                if photo != 'https://itemimg.goldwin.co.jp/itemimg/GDW01/A0GDW0001QCX/02_' + code + '.jpg':
                    return None
                images.append(photo)
            elif _ft_class(n, 'cart_size_radio'):
                size = a.get('vcaname')
                if n['hidden'] or a.get('name') != 'size' or size not in _SIZES or size in sizes:
                    return None
                sizes.append(size)
        if (not colors or not sizes or set(colors) != set(facts.get('Color', '').split('、'))
                or set(sizes) != set(facts.get('Size', '').split('、'))
                or (image_url is not None and image_url not in images)):
            return None
        return dict(c, fabric=FABRIC, weight=WEIGHT, colors=colors, sizes=sizes,
                    imageUrls=images, sourceUrl=URL, sourceKind='goldwin-na62650-primary-dom')
    except (ApparelIdentityError, ValueError, TypeError, KeyError, RecursionError):
        return None
