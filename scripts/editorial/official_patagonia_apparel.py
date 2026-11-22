"""Exact 40275 primary DOM plus linked ProductGroup evidence; no fetching.

Accepts actual rendered HTML, never a search snippet or a rebuilt product node.
Colour-level schema does not prove a fixed colour/size SKU, so fixed is held.
"""
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

from official_shopify_apparel import _Page, _walk, _text, _one, _json


R1_URL = 'https://www.patagonia.jp/product/mens-r1-air-fleece-midlayer-jacket/40275.html'
R1_TITLE = 'メンズ・R1 エア・ジャケット'


def _class(node, value):
    return value in (node['attrs'].get('class') or '').split()


def _active(node):
    attrs = node['attrs']
    return not ('hidden' in attrs or attrs.get('aria-hidden') == 'true'
                or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attrs.get('style') or '', re.I))


def _visible_walk(node):
    if (not _active(node) or node['tag'] in ('script', 'style', 'template', 'aside', 'nav')
            or ('data-pid' in node['attrs'] and node['attrs']['data-pid'] != '40275')):
        return
    yield node
    for child in node['children']:
        if isinstance(child, dict):
            yield from _visible_walk(child)


def _visible_text(node):
    if (not _active(node) or node['tag'] in ('script', 'style', 'template', 'aside', 'nav')
            or ('data-pid' in node['attrs'] and node['attrs']['data-pid'] != '40275')):
        return ''
    return ''.join(c if isinstance(c, str) else _visible_text(c) for c in node['children'])


def _photo(url, code):
    if not isinstance(url, str) or re.search(r'[\s\\\x00-\x1f\x7f]', url):
        return False
    p = urlsplit(url)
    return bool(p.scheme == 'https' and p.netloc == 'dis.patagonia.jp' and not p.fragment
                and re.fullmatch(r'/dw/image/v2/BDJB_PRD/on/demandware.static/-/Sites-patagonia-master/'
                    r'default/dw[0-9a-f]+/images/hi-res/40275_' + re.escape(code) + r'\.jpg', p.path))


def inspect_official_patagonia(product, page_url, html, image_url=None):
    from apparel_identity import apparel_contract, ApparelIdentityError, _norm, _nodes, _types
    try:
        contract = apparel_contract(product)
        if (page_url != R1_URL or contract['model'] != '40275' or contract['class'] != 'fleece'
                or _norm(contract['brand']) not in ('patagonia', 'パタゴニア')
                or _norm(contract['gender']) not in ("men's", 'men', 'メンズ')
                or contract['optionState'] != 'selectable' or not isinstance(html, str)
                or len(html.encode('utf-8')) > 3 * 1024 * 1024):
            return None
        document = _Page(html).root
        nodes = list(_walk(document))
        canonicals = [n['attrs'].get('href') for n in nodes if n['tag'] == 'link'
                      and 'canonical' in (n['attrs'].get('rel') or '').split()]
        if canonicals != [R1_URL]:
            return None
        primary = _one([n for n in nodes if _class(n, 'product-detail') and _class(n, 'page-pdp')])
        if primary['attrs'].get('data-pid') != '40275' or not any(n is primary for n in _visible_walk(document)):
            return None
        local = list(_visible_walk(primary))
        heading = _one([n for n in local if n['tag'] == 'h1' and n['attrs'].get('id') == 'product-title'])
        if _visible_text(heading).strip() != R1_TITLE:
            return None
        numbers = [n for n in local if n['tag'] == 'span' and re.fullmatch(
            r'\|\s*製品番号\s+40275', _visible_text(n).strip())]
        _one(numbers)
        documents = [_json(_text(n)) for n in nodes if n['tag'] == 'script'
                     and n['attrs'].get('type') == 'application/ld+json']
        structured = [n for d in documents for n in _nodes(d) if isinstance(n, dict)]
        group = _one([n for n in structured if 'productgroup' in _types(n)])
        if (group.get('@id') != '#40275' or group.get('productGroupID') != '40275'
                or group.get('url') != R1_URL or group.get('name') != R1_TITLE
                or group.get('brand') != {'@type': 'Brand', 'name': 'Patagonia'}
                or group.get('variesBy') != ['https://schema.org/color'] or group.get('hasVariant')):
            return None
        swatches = [n for n in local if n['tag'] == 'button' and _class(n, 'product-swatch')]
        codes, names = [], []
        for n in swatches:
            a = n['attrs']; code, name = a.get('data-color'), a.get('data-caption')
            if (not isinstance(code, str) or not re.fullmatch(r'[A-Z]{3,4}', code)
                    or not isinstance(name, str) or not name or code in codes
                    or a.get('data-attr-value') != code or a.get('data-attr') != code
                    or a.get('aria-label') != 'カラー ' + name):
                return None
            codes.append(code); names.append(name)
        if not codes or len(set(names)) != len(names) or set(group.get('color', [])) != set(codes):
            return None
        labels = [n for n in local if n['tag'] == 'label' and _class(n, 'pdp-size-select')]
        sizes = []
        for n in labels:
            a = n['attrs']; size = a.get('data-size')
            url = urlsplit(a.get('data-size-url', '')); q = parse_qs(url.query)
            radio = _one([c for c in _walk(n) if c['tag'] == 'input' and c['attrs'].get('name') == 'size'])
            if (size not in ('XS', 'S', 'M', 'L', 'XL', 'XXL') or size in sizes
                    or a.get('data-attr-value') != size or radio['attrs'].get('value') != size
                    or radio['attrs'].get('id') != 'size-' + size or a.get('for') != 'size-' + size
                    or url.scheme != 'https' or url.netloc != 'www.patagonia.jp'
                    or url.path != '/on/demandware.store/Sites-patagonia-jp-Site/ja_JP/Product-Variation'
                    or url.fragment or not set(q) <= {'pid', 'dwvar_40275_size', 'dwvar_40275_color', 'quantity'}
                    or q.get('pid') != ['40275'] or q.get('dwvar_40275_size') != [size]
                    or len(q.get('dwvar_40275_color', [])) != 1
                    or q['dwvar_40275_color'][0] not in codes
                    or ('quantity' in q and q['quantity'] != ['1'])):
                return None
            sizes.append(size)
        if not sizes:
            return None  # A size chart alone is not an actual product selector.
        variants = [n for n in structured if 'product' in _types(n)
                    and n.get('isVariantOf', {}).get('@id') == '#40275']
        seen, images = set(), []
        for n in variants:
            sku = n.get('sku', ''); code = sku[6:] if isinstance(sku, str) else None
            offer = n.get('offers'); name = n.get('color')
            if (not isinstance(sku, str) or not sku.startswith('40275-')
                    or code not in codes or code in seen or n.get('mpn') != sku
                    or name != names[codes.index(code)] or n.get('name') != R1_TITLE + ' - ' + name
                    or not isinstance(offer, dict) or offer.get('image') != n.get('image')
                    or offer.get('url') != R1_URL + '?dwvar_40275_color=' + code
                    or not _photo(n.get('image'), code)):
                return None
            images.append(n['image']); seen.add(code)
        if seen != set(codes) or not any(_photo(group.get('image'), code) for code in codes):
            return None
        # Prove both facts in the same primary product accordions, not reviews.
        features = _one([n for n in local if n['attrs'].get('id') == 'collapsible-1'])
        weights = []
        for n in _visible_walk(features):
            if n['tag'] == 'li':
                headings = [h for h in _visible_walk(n) if h['tag'] == 'h3']
                if len(headings) == 1 and _visible_text(headings[0]).strip() == '重さ':
                    weights.append(_visible_text(_one([p for p in _visible_walk(n)
                        if p['tag'] == 'p' and _class(p, 'content-feature__description')])).strip())
        material_region = _one([n for n in local if n['attrs'].get('id') == 'collapsible-2'])
        # This accordion can be collapsed; it is still explicitly primary facts.
        materials = [n for n in _visible_walk(material_region) if n['tag'] == 'p'
                     and _class(n, 'content-feature__description')]
        facts = {'weight': _one(weights), 'fabric': _visible_text(_one(materials)).strip()}
        if not all(facts.values()) or any(_norm(facts[k]) != _norm(contract[k])
                                         for k in facts if k in contract):
            return None
        if image_url is not None and image_url not in images:
            return None
        description = group.get('description')
        if (not isinstance(description, str) or not description or len(description) > 1800
                or not any(_norm(_visible_text(n)) == _norm(description) for n in local if n['tag'] == 'article')):
            return None
        result = dict(contract, **{k: v for k, v in facts.items() if k not in contract},
                      colors=names, sizes=sizes, imageUrls=images, sourceUrl=R1_URL,
                      sourceKind='patagonia-primary-product-dom')
        result['manufacturerExcerpt'] = dict(text=description, sourceUrl=R1_URL, model='40275',
            excerptSHA256=hashlib.sha256(description.encode()).hexdigest(),
            scope='Exact primary 40275 article matching ProductGroup.description; no reviews')
        return result
    except (ApparelIdentityError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None
