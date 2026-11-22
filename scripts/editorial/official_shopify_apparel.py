"""Offline, fail-closed maker evidence for three observed Shopify products.

No transport or merchant support. Mixed-model variant roots are held in full.
Only literal JSON is decoded; embedded JavaScript is never evaluated.
"""
from html.parser import HTMLParser
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit


_MODELS = {
    'X000010878': ('https://arcteryx.jp/products/beta-jacket-m', 9110038216935,
                   'ベータ ジャケット メンズ', 'Arcteryx'),
    'X000010854': ('https://arcteryx.jp/products/beta-sl-jacket-m', 9110037987559,
                   'ベータ SL ジャケット メンズ', 'Arcteryx'),
    'MIV01248': ('https://www.millet.jp/products/miv01248', 10914878095644,
                'ドライナミック メッシュ NS クルー', 'ミレー公式オンライストア'),
}
_VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


class _Page(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': '', 'attrs': {}, 'children': []}
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'children': []}
        self.stack[-1]['children'].append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1]['children'].append(data)


def _walk(node):
    yield node
    for child in node['children']:
        if isinstance(child, dict):
            yield from _walk(child)


def _text(node):
    return ''.join(c if isinstance(c, str) else _text(c) for c in node['children'])


def _one(values):
    if len(values) != 1:
        raise ValueError('ambiguous or absent primary structure')
    return values[0]


def _objects(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _json(text):
    return json.loads(text, object_pairs_hook=_objects)


def _image(url, canonical, model):
    if not isinstance(url, str):
        return None
    absolute = urljoin(canonical, url)
    parsed, primary = urlsplit(absolute), urlsplit(canonical)
    if (parsed.scheme != 'https' or parsed.netloc != primary.netloc or parsed.fragment
            or not parsed.path.startswith('/cdn/shop/files/')
            or not re.search(r'(?<![A-Za-z0-9])' + re.escape(model) + r'(?![A-Za-z0-9])', parsed.path)
            or not re.search(r'\.(?:jpg|jpeg|png|webp)$', parsed.path, re.I)):
        return None
    return absolute


def _facts(description):
    if not isinstance(description, str):
        return {}
    paragraphs = [n for n in _walk(_Page(description).root) if n['tag'] == 'p']
    result = {}
    for left, right in zip(paragraphs, paragraphs[1:]):
        label = _text(left).strip()
        if label in ('素材', '重量') and 'descript-name' in left['attrs'].get('class', '').split():
            key = {'素材': 'fabric', '重量': 'weight'}[label]
            if key in result:
                raise ValueError('ambiguous primary fact')
            result[key] = _text(right).strip()
    return result


def _description_excerpt(root, canonical, model):
    """Copy bounded source sentences, never generate or rewrite article prose."""
    if model != 'MIV01248' or not isinstance(root.get('description'), str):
        return None
    doc = _Page(root['description']).root
    nodes = list(_walk(doc))[1:]
    if not nodes or any(n['tag'] not in ('div', 'p', 'br') for n in nodes):
        return None
    wrappers = [n for n in nodes if n['tag'] == 'div']
    if (len(wrappers) > 1 or any(n['attrs'].get('class') != 'product-description-box'
                                for n in wrappers)):
        return None
    lines = []
    for n in nodes:
        if n['tag'] != 'p':
            continue
        classes = n['attrs'].get('class', '').split()
        if classes == ['descript-name']:
            label = _text(n).strip()
            if label in ('素材', '重量'):
                break  # Facts remain subject to their own exact contract checks.
            if label != '装備':
                break  # Do not cross into related/promotional sections.
            continue
        if classes != ['body'] or any(c['tag'] != 'br' for c in _walk(n) if c is not n):
            return None
        text = ''.join(c if isinstance(c, str) else '\n' for c in n['children'])
        for part in re.split(r'(?<=。)|\n', text):
            part = part.strip()
            if part and not re.search(r'究極|次世代|必須|優れ|快適|おすすめ|人気|セール|価格|送料|関連|購入|sale|price|related|recommend|buy|shipping|coupon|[¥￥$]|\d[\d,]*円|OFF', part, re.I):
                lines.append(part)
    text = '\n'.join(lines)
    if not text:
        return None
    return dict(sourceUrl=canonical, model=model, text=text,
                excerptSHA256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                scope='Verified MIV01248 root.description p.body sentences before material/weight; promotional and price sentences omitted; source wording retained')


def inspect_official_shopify(product, page_url, html, image_url=None):
    """Return an apparel public binding, or None (HOLD) on incomplete evidence."""
    # Deferred import keeps this usable as apparel_identity's optional fallback.
    from apparel_identity import apparel_contract, ApparelIdentityError, _norm
    try:
        contract = apparel_contract(product)
        model = contract['model']
        if model not in _MODELS or not isinstance(html, str):
            return None
        canonical, product_id, title, vendor = _MODELS[model]
        arc = model.startswith('X')
        brands = ("arc'teryx", 'arc’teryx', 'arcteryx', 'アークテリクス') if arc else ('millet', 'ミレー')
        if (_norm(contract['brand']) not in brands or
                contract['class'] != ('hardshell' if arc else 'base-layer') or
                _norm(contract['gender']) not in ('men', "men's", 'male', 'メンズ') or page_url != canonical):
            return None
        nodes = list(_walk(_Page(html).root))
        links = [n['attrs'].get('href') for n in nodes if n['tag'] == 'link'
                 and 'canonical' in n['attrs'].get('rel', '').split()]
        if links != [canonical]:
            return None
        if arc:
            primary = _one([n for n in nodes if n['attrs'].get('id') == 'shopify-section-product-template'])
            local = list(_walk(primary))
            heading = _one([n for n in local if n['tag'] == 'h1'
                            and 'product-single__title' in n['attrs'].get('class', '').split()])
            if _text(heading).strip() != title:
                return None
            scripts = [n for n in nodes if n['tag'] == 'script'
                       and n['attrs'].get('id', '').startswith('ProductJson-')]
            script = _one(scripts)
            if script not in local or script['attrs'].get('id') != 'ProductJson-product-template' or script['attrs'].get('type') != 'application/json':
                return None
            root = _json(_text(script))
        else:
            primary = _one([n for n in nodes if n['tag'] == 'product-rerender'
                            and n['attrs'].get('id', '').startswith('product-info-')])
            if not primary['attrs'].get('id', '').startswith('product-info-' + str(product_id) + '-'):
                return None
            local = list(_walk(primary))
            headings = [n for n in local if n['tag'] in ('h1', 'h2')
                        and 'product-meta__title' in n['attrs'].get('class', '').split()]
            keys = [n for n in local if 'product-key' in n['attrs'].get('class', '').split()]
            if not headings or any(_text(n).strip() != title + '（メンズ）' for n in headings):
                return None
            if not keys or any(_text(n).strip().upper() != model for n in keys):
                return None
            script = _one([n for n in nodes if n['tag'] == 'script'
                           and n['attrs'].get('id') == 'back-in-stock-helper-embedded'])
            body = _text(script)
            markers = list(re.finditer(r'_BISConfig\.product\s*=\s*', body))
            marker = _one(markers)
            root, end = json.JSONDecoder(object_pairs_hook=_objects).raw_decode(body[marker.end():])
            if not body[marker.end() + end:].lstrip().startswith(';'):
                return None
        if (not isinstance(root, dict) or root.get('id') != product_id or root.get('vendor') != vendor
                or root.get('title') != title or root.get('handle') != canonical.rsplit('/', 1)[1]
                or root.get('options') != (['Color', 'Size'] if arc else ['カラー', 'サイズ'])
                or (arc and (not isinstance(root.get('tags'), list) or model not in root['tags']))):
            return None
        variants = root.get('variants')
        if not isinstance(variants, list) or not variants or not isinstance(root.get('images'), list):
            return None
        seen = set()
        for v in variants:
            if (not isinstance(v, dict) or type(v.get('id')) is not int
                    or v['id'] <= 0 or v['id'] in seen):
                return None
            seen.add(v['id'])
            color, size, sku = v.get('option1'), v.get('option2'), v.get('sku')
            if not all(isinstance(s, str) and s.strip() for s in (color, size, sku)):
                return None
            if v.get('options') != [color, size] or v.get('option3') is not None:
                return None
            # Every variant must prove the model: never cherry-pick a mixed root.
            if arc:
                if not re.fullmatch(re.escape(model) + r'\d{5}', sku):
                    return None
            else:
                code = re.fullmatch(r'.+ \| (N\d{4})', color)
                if not code or sku != model + '-' + code[1] + '-' + size:
                    return None
        facts = _facts(root.get('description')) if not arc else {}
        if any(_norm(facts.get(k, '')) != _norm(contract[k]) for k in ('fabric', 'weight') if k in contract):
            return None
        selected = variants
        if contract['optionState'] == 'fixed':
            selected = [v for v in variants if v['option1'] == contract['color'] and v['option2'] == contract['size']]
            v = _one(selected)
            photo = v.get('featured_image')
            if (not isinstance(photo, dict) or photo.get('product_id') != product_id
                    or v['id'] not in photo.get('variant_ids', [])):
                return None
            images = [_image(photo.get('src'), canonical, model)]
            if images[0] is None or images[0] not in [urljoin(canonical, u) for u in root['images'] if isinstance(u, str)]:
                return None
        else:
            images = list(dict.fromkeys(u for raw in root['images'] for u in [_image(raw, canonical, model)] if u))
        if not images or (image_url is not None and image_url not in images):
            return None
        result = dict(contract, colors=sorted({v['option1'] for v in selected}),
                      sizes=sorted({v['option2'] for v in selected}), imageUrls=images,
                      sourceUrl=canonical, sourceKind='official-shopify-product')
        if contract['optionState'] == 'fixed':
            result['sourceVariant'] = selected[0]['sku']
        excerpt = _description_excerpt(root, canonical, model)
        if excerpt:
            result['manufacturerExcerpt'] = excerpt
        return result
    except (ApparelIdentityError, ValueError, TypeError, KeyError, RecursionError):
        return None
