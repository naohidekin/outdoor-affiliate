"""Readable, bounded Slack rendering of an already approved editorial bundle."""
import re
from urllib.parse import urlsplit


def escape(text):
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _link(url, label):
    if url.startswith('/') and not url.startswith('//'):
        url = 'https://camp-gear-lab.com' + url
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password or any(c in url for c in '<>|\n\r'):
        return escape(label) + '（' + escape(url) + '）'
    return '<' + escape(url) + '|' + escape(label).replace('|', '｜') + '>'


def _inline(text):
    # Parse only the small Markdown subset used in approved articles. All
    # remaining angle brackets are escaped, so text cannot forge Slack links.
    tokens = []
    pattern = re.compile(r'\[([^\]\n]+)\]\(|\*\*([^*\n]+)\*\*')
    pos = 0
    for match in pattern.finditer(str(text)):
        if match.start() < pos:
            continue
        end = match.end()
        url = None
        if match.group(1) is not None:
            depth = 1
            for i in range(end, len(text)):
                if text[i] == '\n':
                    break
                if text[i] == '(':
                    depth += 1
                elif text[i] == ')':
                    depth -= 1
                    if depth == 0:
                        url, end = text[match.end():i], i + 1
                        break
            if url is None:
                continue
        tokens.append(escape(text[pos:match.start()]))
        if match.group(1) is not None:
            tokens.append(_link(url, match.group(1)))
        else:
            tokens.append('*' + escape(match.group(2)) + '*')
        pos = end
    tokens.append(escape(text[pos:]))
    return ''.join(tokens)


def _merchants(product):
    links = []
    for label, key in (('楽天', 'affiliateUrl'), ('Amazon', 'amazonUrl'), ('Yahoo!', 'yahooUrl')):
        if product.get(key):
            links.append(_link(product[key], label))
    return ' ・ '.join(links)


SPEC_LABELS = {'weight': '重量', 'capacity': '容量', 'size': 'サイズ', 'dimensions': 'サイズ',
               'material': '素材', 'opening': '口径', 'runtime': '連続使用時間', 'brightness': '明るさ',
               'waterproof': '防水性能', 'power': '電源'}
SPEC_PRIORITY = {
    'tent': ['定員', '重量', 'サイズ', '収納サイズ', '耐水圧'],
    'cooler': ['容量', '重量', 'サイズ', '保冷力', '電源'],
    'sleeping-bag': ['快適温度', '対応温度', '重量', '収納サイズ', '素材'],
    'light': ['明るさ', '連続点灯時間', '電源', '防水性能', '重量'],
    'fan': ['電源', '連続使用時間', '重量', 'サイズ'],
    'insect-repellent': ['有効成分', '対象害虫', '対象年齢', '種別'],
}


def _specs(product, limit=None):
    # Mirror getProductSpecs: Japanese keys take precedence over API aliases.
    raw = product.get('specs') or {}
    if not isinstance(raw, dict):
        return []
    values = {}
    for name, item in sorted(raw.items(), key=lambda pair: bool(SPEC_LABELS.get(str(pair[0]).strip()))):
        original = str(name).strip()
        label = SPEC_LABELS.get(original, original)
        value = str(item).strip() if item is not None else ''
        if (not label or not value or re.fullmatch(r'(?:[-—–]+|null|undefined|n/?a)', value, re.I)
                or re.fullmatch(r'[a-z_\s]+', label, re.I) and original not in SPEC_LABELS):
            continue
        values.setdefault(label, value)
    priority = SPEC_PRIORITY.get(product.get('categoryId'), ['重量', 'サイズ', '素材', '容量'])
    ordered = sorted(values.items(), key=lambda pair: priority.index(pair[0]) if pair[0] in priority else len(priority))
    return ordered if limit is None else ordered[:limit]


def _panel(product, kind, rank=None):
    lines = []
    if rank is not None:
        lines.append(str(rank) + '位')
    if product.get('brand'):
        lines.append(escape(product['brand']))
    lines.append('*掲載商品：' + escape(product['name']) + '*')
    if kind in ('product', 'ranking') and product.get('description'):
        lines.append(escape(product['description']))
    specs = _specs(product, 3 if kind == 'product' else None) if kind in ('product', 'comparison') else []
    lines.extend(escape(label) + '：' + escape(value) for label, value in specs)
    price = product.get('price')
    if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
        lines.append('参考価格：¥' + format(price, ','))
    elif kind == 'comparison':
        lines.append('参考価格：販売店で確認')
    links = _merchants(product)
    if links:
        lines.append(links)
    return '\n'.join(lines)


def article_body(bundle):
    article = bundle['article']
    products = {p['id']: p for p in bundle.get('products', [])}
    displayed = set()

    def shortcode(match):
        kind = match.group(1)
        if kind == 'youtube':
            video, *rest = match.group(2).split('|')
            if not re.fullmatch(r'[A-Za-z0-9_-]{6,20}', video):
                raise ValueError('presentation_video_invalid')
            caption = rest[0].strip() if rest else ''
            return '\n' + _link('https://www.youtube.com/watch?v=' + video, caption or 'YouTube動画') + '\n'
        ids = match.group(2).split(',')
        found = [products.get(pid.strip()) for pid in ids]
        if any(p is None for p in found):
            raise ValueError('presentation_product_unknown')
        if kind == 'price':
            if len(found) != 1:
                raise ValueError('presentation_product_unknown')
            price = found[0].get('price')
            return (format(price, ',') + '円') if isinstance(price, (int, float)) and price > 0 else ''
        displayed.update(p['id'] for p in found)
        if kind == 'product':
            return '\n' + _panel(found[0], 'product') + '\n'
        label = '比較商品' if kind == 'comparison' else '掲載商品'
        return '\n*' + label + '*\n' + '\n\n'.join(
            _panel(p, kind, i if kind == 'ranking' else None) for i, p in enumerate(found, 1)) + '\n'

    # Marker placeholders are expanded after Markdown conversion so generated
    # Slack link syntax is never escaped or mistaken for source Markdown.
    markers = []
    def mark(match):
        markers.append(shortcode(match))
        return '\x01' + str(len(markers) - 1) + '\x02'

    source = re.sub(r'\{\{(product|comparison|ranking|price|youtube):([^}]+)\}\}', mark, article['content'])
    if re.search(r'\{\{[^}]*\}\}', source):
        raise ValueError('presentation_shortcode_unhandled')
    lines = []
    source_lines = source.splitlines()
    index = 0
    while index < len(source_lines):
        line = source_lines[index]
        if (index + 1 < len(source_lines) and '|' in line and
                re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*', source_lines[index + 1])):
            headers = [h.strip() for h in line.strip().strip('|').split('|')]
            index += 2
            first_row = index
            while index < len(source_lines) and '|' in source_lines[index]:
                cells = [c.strip() for c in source_lines[index].strip().strip('|').split('|')]
                if len(cells) != len(headers):
                    break
                lines.append('• ' + ' ・ '.join('*' + _inline(h) + '*: ' + _inline(c) for h, c in zip(headers, cells)))
                index += 1
            if index == first_row:
                lines.append(' ・ '.join(_inline(h) for h in headers))
            continue
        heading = re.match(r'^\s{0,3}#{1,6}\s+(.+?)\s*$', line)
        bullet = re.match(r'^\s*[-*+]\s+(.+)$', line)
        numbered = re.match(r'^\s*(\d+)\.\s+(.+)$', line)
        if heading:
            rendered = '*' + _inline(heading.group(1)) + '*'
        elif bullet:
            rendered = '• ' + _inline(bullet.group(1))
        elif numbered:
            rendered = numbered.group(1) + '. ' + _inline(numbered.group(2))
        else:
            rendered = _inline(line)
        lines.append(rendered)
        index += 1
    body = '\n'.join(lines)
    for marker_index, panel in enumerate(markers):
        body = body.replace('\x01' + str(marker_index) + '\x02', panel)
    # The page renders structured FAQs unless the same Q/A is already inline.
    missing = [q for q in article.get('faqs', []) if q['question'] not in article['content'] or q['answer'] not in article['content']]
    if missing:
        body += '\n\n*よくある質問*\n' + '\n'.join('*Q. ' + _inline(q['question']) + '*\nA. ' + _inline(q['answer']) for q in missing)
    for p in bundle.get('products', []):
        if p['id'] not in displayed:
            body += '\n\n' + _panel(p, 'ranking')
    if 'catalogCorrectionContext' in bundle:
        from catalog_corrections import validate_context
        ctx = validate_context(bundle['catalogCorrectionContext'])
        body += '\n\n*商品情報の訂正*\nこの記事の承認で、下記の商品情報も更新します。同じ商品を掲載する既存記事にも反映されます。\n' + escape(ctx['changeSummary'])
        originals = {p['id']: p for p in ctx['baseProducts']}
        labels = {'name': '商品名', 'brand': 'ブランド', 'specs': '仕様', 'imageUrl': '商品写真',
                  'affiliateUrl': '楽天の購入リンク', 'amazonUrl': 'Amazonの購入リンク', 'yahooUrl': 'Yahoo!の購入リンク',
                  'price': '参考価格', 'description': '商品説明', 'rating': '評価', 'availability': '販売状況'}
        def value_text(key, value):
            if key in ('price', 'rating'):
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                    return '参考価格/評価の数値を表示せず販売店で確認'
                return ('¥' + format(value, ',')) if key == 'price' else escape(value)
            if key in ('imageUrl', 'affiliateUrl', 'amazonUrl', 'yahooUrl'):
                return _link(value, value) if value else '表示しない'
            return escape(value) if value is not None and value != '' else '記載なし'
        for patch in ctx['productPatches']:
            old = originals[patch['id']]
            body += '\n\n*' + escape(old.get('name', '商品')) + '*'
            for key, value in patch['fields'].items():
                if key == 'updatedAt':
                    continue
                if key == 'specs' and isinstance(old[key], dict) and isinstance(value, dict):
                    for spec in dict.fromkeys([*old[key], *value]):
                        if old[key].get(spec) != value.get(spec):
                            body += '\n仕様・' + escape(SPEC_LABELS.get(spec, spec)) + '：' + value_text(spec, old[key].get(spec)) + ' → ' + value_text(spec, value.get(spec))
                else:
                    body += '\n' + labels.get(key, '商品情報') + '：' + value_text(key, old[key]) + ' → ' + value_text(key, value)
    return body


def social_body(proposal):
    return _inline(proposal['text']) + '\n\n*リンク用返信*\n' + _inline(proposal['replyText'])
