"""Pure extraction from exact official firepit HTML scopes.

No network, environment, ledger, persistence, prices, or merchant authority.
Callers must first obtain HTML through their safe HTTPS transport. A None
result stays blocked. Product JSON-LD can corroborate an exact visible official
identity; metadata alone or retailer titles can never supply that identity.
"""
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit


def _excluded(node):
    marker = ' '.join((node.attrs.get('id', ''), node.attrs.get('class', '')))
    return (node.tag in ('nav', 'aside', 'footer') or node.attrs.get('role') == 'navigation'
            or bool(re.search(r'related|recommend|cross.?sell|upsell|sponsored|reviews?', marker, re.I)))


class _Node:
    def __init__(self, tag='', attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []

    def has(self, value):
        return value in self.attrs.get('class', '').split()

    def walk(self):
        if _excluded(self):
            return
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def text(self):
        if _excluded(self) or self.tag in ('script', 'style', 'template', 'noscript'):
            return ''
        if self.tag == 'br':
            return '\n'
        return ''.join(c.text() if isinstance(c, _Node) else c for c in self.children)


class _Tree(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def _nodes(root, predicate):
    def walk(node):
        if _excluded(node) or node.tag in ('script', 'style', 'template', 'noscript'):
            return
        if predicate(node):
            yield node
        for child in node.children:
            if isinstance(child, _Node):
                yield from walk(child)
    return list(walk(root))


def _one(root, predicate):
    nodes = _nodes(root, predicate)
    if len(nodes) != 1:
        raise ValueError('primary_scope_ambiguous')
    return nodes[0]


def _flat(text):
    return ' '.join(text.split())


def extract_primary(product, url, html):
    """Return exact normalized fields and bound image URLs, or None.

    Interface: {model, specs:{label:value}, imageUrls:[], scope, sourceUrl}.
    Values retain units, conditions, bundle scope, and separate body/total mass.
    These observations do not constitute image byte validation or approval.
    """
    try:
        if not isinstance(html, str) or len(html.encode('utf-8')) > 8 * 1024 * 1024:
            return None
        p = urlsplit(url)
        if p.scheme != 'https' or p.username is not None or p.password is not None or p.port not in (None, 443) or p.fragment:
            return None
        root, pid = _Tree(html).root, product['id']
        model = product.get('specs', {}).get('型番')
        fields, images = {}, []
        if pid == 'fp-002' and product.get('brand', '').casefold() in ('uniflame', 'ユニフレーム'):
            if p.hostname != 'www.uniflame.co.jp' or p.path != '/product/683040' or p.query or model != '683040':
                return None
            scope = _one(root, lambda n: n.tag == 'article' and n.attrs.get('id') == 'product')
            item = _one(scope, lambda n: n.attrs.get('id') == 'item')
            if _flat(_one(item, lambda n: n.has('item-code')).text()) != 'No.683040' or _flat(_one(item, lambda n: n.has('item-name')).text()) != 'ファイアグリル':
                return None
            specs = _one(scope, lambda n: n.tag == 'ul' and n.has('item-spec'))
            for dl in _nodes(specs, lambda n: n.tag == 'dl'):
                key = _flat(_one(dl, lambda n: n.tag == 'dt').text())
                if key in fields:
                    return None
                fields[key] = _flat(_one(dl, lambda n: n.tag == 'dd').text())
            galleries = _nodes(scope, lambda n: n.attrs.get('id') == 'visualWrap')
            if len(galleries) > 1:
                return None
            images = [n.attrs.get('src', '') for n in _nodes(galleries[0], lambda n: n.tag == 'img')] if galleries else []
            # Main product photo and its declared responsive variants belong to
            # this already-validated No.683040 article, never to adjacent cards.
            wrappers = _nodes(scope, lambda n: n.attrs.get('id') == 'itemWrap')
            if len(wrappers) > 1:
                return None
            if wrappers:
                main_gallery = _nodes(wrappers[0], lambda n: n.has('item-image'))
                if len(main_gallery) > 1:
                    return None
                if main_gallery:
                    for image in _nodes(main_gallery[0], lambda n: n.tag == 'img'):
                        images.append(image.attrs.get('src', ''))
                        for candidate in image.attrs.get('srcset', '').split(','):
                            parts = candidate.split()
                            if len(parts) == 2 and re.fullmatch(r'[1-9][0-9]*w', parts[1]):
                                images.append(parts[0])
            selector = 'article#product #item; article#product ul.item-spec dl'
        elif pid == 'fp-001' and product.get('brand', '').casefold() in ('picogrill', 'ピコグリル'):
            if p.hostname != 'www.picogrill.ch' or p.path != '/grill/PICOGRILL-398.html' or p.query != 'language=jp' or model != '0398.SP':
                return None
            scope = _one(root, lambda n: n.has('product-info-default'))
            codes = _nodes(scope, lambda n: n.has('model-number-text'))
            titles = _nodes(scope, lambda n: n.tag == 'h1' and n.has('product-info-title-desktop'))
            if not codes or any(_flat(n.text()) != '0398.SP' for n in codes) or len(titles) != 1 or _flat(titles[0].text()) != 'ピコグリル 398':
                return None
            description = _one(scope, lambda n: n.has('product-info-description'))
            spec = _one(description, lambda n: n.has('tab-body') and n.has('active'))
            labels = ('人数', '商品内容', '重量', 'サイズ', '材質', '調理')
            lines = [line.strip() for line in spec.text().splitlines() if line.strip()]
            for label in labels:
                if lines.count(label) != 1:
                    return None
                start = lines.index(label) + 1
                stop = next((i for i in range(start, len(lines)) if lines[i] in labels + ('特徴',)), len(lines))
                fields[label] = _flat(' '.join(lines[start:stop]))
            galleries = _nodes(scope, lambda n: n.attrs.get('id') == 'image-collection-container')
            if len(galleries) > 1:
                return None
            images = [n.attrs.get('src', '') for n in _nodes(galleries[0], lambda n: n.tag == 'img')] if galleries else []
            selector = '.product-info-default .model-number-text; .product-info-description .tab-body.active'
        elif pid == 'fp-004' and product.get('brand', '').casefold() == 'tokyocamp':
            if p.hostname != 'shop.tokyocamp.ooo' or p.path != '/items/51325629' or p.query or model != 'HAKOSUKA':
                return None
            scope = _one(root, lambda n: n.attrs.get('data-parts') == 'item-detail')
            title = _one(scope, lambda n: n.tag == 'h2' and any(c.startswith('item-detail_itemTitle_') for c in n.attrs.get('class', '').split()))
            if _flat(title.text()) != 'TokyoCamp焚火台"HAKOSUKA"':
                return None
            description = _one(scope, lambda n: n.tag == 'p' and any(c.startswith('item-detail_description_') for c in n.attrs.get('class', '').split()))
            details = re.findall(r'【商品詳細】([^※]+)', description.text())
            if len(details) != 1:
                return None
            for part in details[0].split('・'):
                if not part.strip():
                    continue
                label, value = part.split('：', 1)
                if label.strip() in fields:
                    return None
                fields[label.strip()] = _flat(value)
            if fields.get('付属品') != '本体、収納ケース' or fields.get('素材') != 'ステンレス':
                return None
            images = [n.attrs.get('src', '') for n in _nodes(scope, lambda n: n.tag == 'img')]
            selector = '[data-parts="item-detail"] h2[class^="item-detail_itemTitle_"]; p[class^="item-detail_description_"]'
        elif pid == 'fp-005' and product.get('brand', '').casefold() in ('solo stove', 'ソロストーブ'):
            official = 'https://store.upioutdoor.com/products/solo-stove-ranger-kit-2'
            title_text = 'SOLO STOVE RANGER KIT 2.0 / ソロストーブ レンジャーキット 2.0'
            if url != official or model != 'SSRAN-SD-2':
                return None
            main = _one(root, lambda n: n.attrs.get('id') == 'main')
            product_scope = _one(main, lambda n: n.attrs.get('data-section-type') == 'product-single')
            title = _one(product_scope, lambda n: n.tag == 'h1' and n.has('product-single__title'))
            if _flat(title.text()) != title_text:
                return None
            metadata = []
            for node in root.walk():
                if node.tag == 'script' and node.attrs.get('type') == 'application/ld+json':
                    value = json.loads(''.join(c for c in node.children if isinstance(c, str)))
                    if isinstance(value, dict) and value.get('@type') == 'Product':
                        metadata.append(value)
            if len(metadata) != 1 or any(metadata[0].get(k) != v for k, v in (
                    ('name', title_text), ('url', official), ('sku', 'SSRAN-SD-2'))):
                return None
            specs = _one(main, lambda n: n.has('spec-area'))
            for item in _nodes(specs, lambda n: n.has('spec-item')):
                label = _flat(_one(item, lambda n: n.tag == 'h4' and n.has('spec-item__heading')).text())
                if label == '関連記事':
                    continue
                if label in fields:
                    return None
                fields[label] = _flat(_one(item, lambda n: n.tag == 'p' and n.has('spec-item__text')).text())
            if fields.get('内容') != '本体、レンジャー専用スタンド、収納袋、日本語説明書':
                return None
            images = [n.attrs.get('src', '') for n in _nodes(product_scope, lambda n: n.tag == 'img' and n.has('media-gallery__image'))]
            selector = '#main section[data-section-type="product-single"] h1.product-single__title; #main .spec-area .spec-item'
        else:
            return None
        if not fields or any(not value for value in fields.values()):
            return None
        # Images must be actual product-gallery images, never social/logo metadata.
        image_base = url
        bases = _nodes(root, lambda n: n.tag == 'base' and 'href' in n.attrs)
        if len(bases) > 1:
            return None
        if bases:
            base = urlsplit(urljoin(url, bases[0].attrs['href']))
            if base.scheme != 'https' or base.hostname != p.hostname or base.username is not None or base.password is not None or base.port not in (None, 443):
                return None
            image_base = base.geturl()
        clean = []
        for source in images:
            absolute = urljoin(image_base, source)
            image = urlsplit(absolute)
            if image.scheme == 'https' and image.username is None and image.password is None and image.port in (None, 443):
                if pid == 'fp-004' and (image.hostname != 'baseec-img-mng.akamaized.net' or not image.path.startswith('/images/item/origin/')):
                    continue
                if pid in ('fp-001', 'fp-002') and image.hostname != p.hostname:
                    continue
                if pid == 'fp-005' and (image.hostname != p.hostname or not image.path.startswith('/cdn/shop/')):
                    continue
                if absolute not in clean:
                    clean.append(absolute)
        return {'model': model, 'specs': fields, 'imageUrls': clean, 'scope': selector, 'sourceUrl': url}
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def merchant_primary(html):
    """Product detail evidence, excluding navigation and adjacent products."""
    root = _Tree(html).root
    sections = _nodes(root, lambda n: n.has('item_desc') or n.has('normal_reserve_item_number')
                      or n.attrs.get('id') in ('feature-bullets', 'productOverview_feature_div',
                          'productDetails_techSpec_section_1', 'productDetails_detailBullets_sections1',
                          'detailBullets_feature_div', 'productDescription'))
    if not sections:
        sections = _nodes(root, lambda n: n.tag == 'main')
    return ' '.join(_flat(n.text()) for n in sections)


def fixed_amazon_identity(pid, model, url, html, html_title):
    """Narrow fallback for observed fixed products; no page-wide brand/model proof."""
    tents = {'tent-f03': 'TP-671R', 'tent-f06': 'TP-259', 'tent-f-landlock-x': 'TP-672'}
    if pid not in tents and pid != 'fp-004':
        return None
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.amazon.co.jp':
        return None
    if pid in tents and model != tents[pid]:
        return None
    if pid == 'fp-004' and (model != 'HAKOSUKA' or parsed.path.rstrip('/') != '/dp/B08CZWJ7P8'):
        return None
    root = _Tree(html).root
    compact = lambda text: re.sub(r'\s+', '', text).casefold()
    def exact_model(text):
        normalized = re.sub(r'[-‐‑–—－\s]', '', text).casefold()
        target = re.sub(r'[-\s]', '', model).casefold()
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(target) + r'(?![a-z0-9])', normalized))
    titles = [_flat(n.text()) for n in _nodes(root, lambda n: n.attrs.get('id') == 'productTitle'
              and n.tag in ('span', 'h1')) if _flat(n.text())]
    if len(titles) != 1:
        return None
    title = titles[0]
    brand_names = ('snowpeak', 'スノーピーク') if pid in tents else ('tokyocamp',)
    brand_exact = lambda value: compact(value) in ('snowpeak', 'スノーピーク', 'snowpeak(スノーピーク)', 'snowpeak（スノーピーク）') if pid in tents else compact(value) == 'tokyocamp'
    sections = _nodes(root, lambda n: n.attrs.get('id') in (
        'productOverview_feature_div', 'productDetails_expanderTables_depthRightSections',
        'productDetails_techSpec_section_1'))
    rows = []
    for section in sections:
        for row in _nodes(section, lambda n: n.tag == 'tr'):
            cells = [_flat(n.text()) for n in row.children if isinstance(n, _Node) and n.tag in ('th', 'td')]
            if len(cells) == 2:
                rows.append(cells)
    brands = [value for key, value in rows if key in ('ブランド', 'ブランド名', 'Brand')]
    if brands and not all(brand_exact(value) for value in brands):
        return None
    brand_ok = any(name in compact(html_title) for name in brand_names) or bool(brands)
    if not brand_ok:
        # Exact store byline is allowed only inside its fixed primary node.
        bylines = [_flat(n.text()) for n in _nodes(root, lambda n: n.attrs.get('id') == 'bylineInfo')]
        brand_ok = len(bylines) == 1 and brand_exact(re.sub(r'^(?:ブランド[:：]\s*)', '', bylines[0]))
    if not brand_ok:
        return None
    if pid in tents:
        if re.search(r'グランドシート|インナー|フライシート|ルーフシート|マット|ポール|フレーム|ケース|バッグ|ペグ|ロープ|交換|互換|専用|replacement|compatible|ground.?sheet|footprint|carrying', title + ' ' + html_title, re.I):
            return None
        expected_name = 'ランドネストシェルター' if pid == 'tent-f06' else 'ランドロック'
        if expected_name not in compact(title):
            return None
        models = [value for key, value in rows if key in ('品番・型番', '型番', 'メーカー型番', '商品モデル番号', 'Item model number')]
        normalize_model = lambda text: re.sub(r'[-‐‑–—－\s]', '', text).casefold()
        if any(normalize_model(value) != normalize_model(model) for value in models):
            return None
        if not exact_model(title) or not exact_model(html_title):
            return None
    else:
        if not any(name in compact(title) for name in brand_names) or not re.search(r'焚き?火台', title):
            return None
        if re.search(r'チタン|titanium|ケースのみ|本体なし|交換|互換', title + ' ' + html_title, re.I):
            return None
        models = [value for key, value in rows if key in ('品番・型番', '型番', 'メーカー型番')]
        if 'HAKOSUKA' not in models or any(value not in ('HAKOSUKA', 'HAKOSUKA01') for value in models):
            return None
    return {'scope': '#productTitle + primary labeled brand/model rows', 'model': model,
            'brandValues': brands, 'productTitle': title}
