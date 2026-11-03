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
            p = found[0]
            return '\n*掲載商品：' + escape(p['name']) + '*\n' + _merchants(p) + '\n'
        label = '比較商品' if kind == 'comparison' else '掲載商品'
        return '\n*' + label + '：' + '・'.join(escape(p['name']) for p in found) + '*\n' + '\n'.join(
            escape(p['name']) + '：' + _merchants(p) for p in found) + '\n'

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
            body += '\n\n*掲載商品：' + escape(p['name']) + '*\n' + _merchants(p)
    return body


def social_body(proposal):
    return _inline(proposal['text']) + '\n\n*リンク用返信*\n' + _inline(proposal['replyText'])
