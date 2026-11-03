"""Read-only public catalogue and conservative live evidence, Python stdlib only.

Injected fetcher(url, headers, timeout) returns {status, headers, body: bytes}.
It is a trusted transport boundary for offline tests. Production pins validated
DNS addresses per connection, validates every redirect, and never forwards API
credentials across redirects. No reviews, search snippets or invented claims
are included in writing context. Unsupported maker identity stays blocked.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
import struct
import zlib
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

JST = timezone(timedelta(hours=9))
PRODUCT_FIELDS = 'id,name,brand,price,image_url,affiliate_url,amazon_url,yahoo_url,category_id,specs,description,rating,created_at,updated_at,auto_added,added_by,added_at,source_api,availability'
ARTICLE_FIELDS = 'id,title,slug,category_id,content,excerpt,product_ids,status,faqs,meta_description,tags,created_at,updated_at,published_at,auto_generated,quality_score,scheduled_publish_date,generation_meta,eyecatch'
CATEGORY_FIELDS = 'id,name,slug,description,sort_order'
CLICK_FIELDS = 'product_id,store,page_path,clicked_at,placement'
ENV_KEYS = ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'BRAVE_API_KEY', 'RAKUTEN_APP_ID', 'RAKUTEN_ACCESS_KEY', 'RAKUTEN_AFFILIATE_ID', 'AMAZON_PARTNER_TAG')
MAKERS = {'soto': ('soto.shinfuji.co.jp',), 'snow peak': ('snowpeak.co.jp',),
          'スノーピーク': ('snowpeak.co.jp',), 'coleman': ('coleman.co.jp',),
          'コールマン': ('coleman.co.jp',), 'uniflame': ('uniflame.co.jp',),
          'ユニフレーム': ('uniflame.co.jp',), 'logos': ('logos.ne.jp',),
          'ロゴス': ('logos.ne.jp',), 'nanga': ('nanga.jp',), 'mont-bell': ('montbell.jp', 'montbell.com')}
MAX_BYTES = 8 * 1024 * 1024


class CatalogError(ValueError):
    pass


def safe_url(url, resolve=True):
    """Return parsed URL and public addresses. Never echo attacker input."""
    try:
        if not isinstance(url, str) or re.search(r'[\s\\\x00-\x1f\x7f]', url):
            raise ValueError()
        p = urlsplit(url)
        host = p.hostname
        if p.scheme != 'https' or not host or p.username is not None or p.password is not None or p.port not in (None, 443):
            raise ValueError()
        host = host.rstrip('.').lower()
        if host == 'localhost' or host.endswith(('.local', '.internal', '.localhost', '.lan', '.home', '.test', '.invalid')) or '%' in host:
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if re.fullmatch(r'(?:0x[\da-f]+|[\d]+)(?:\.(?:0x[\da-f]+|[\d]+))*', host):
                raise ValueError()
            ascii_host = host.encode('idna').decode('ascii')
            if '.' not in ascii_host or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', s) for s in ascii_host.split('.')):
                raise ValueError()
            addresses = sorted({r[4][0] for r in socket.getaddrinfo(ascii_host, 443, type=socket.SOCK_STREAM)}) if resolve else []
        else:
            addresses = [str(address)]
        for value in addresses:
            ip = ipaddress.ip_address(value)
            if not ip.is_global or (getattr(ip, 'ipv4_mapped', None) and not ip.ipv4_mapped.is_global) or getattr(ip, 'sixtofour', None) or getattr(ip, 'teredo', None):
                raise ValueError()
        if resolve and not addresses:
            raise ValueError()
        return p, addresses
    except Exception:
        raise CatalogError('unsafe or unreachable HTTPS destination') from None


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=20, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def model_matches(model, title):
    return bool(model and re.search(r'(?<![A-Za-z0-9_/-])' + re.escape(model) + r'(?![A-Za-z0-9_/-])', title, re.I))


def _model(product):
    specs = product.get('specs') or {}
    for key in ('model', 'modelNumber', '型番', '品番', 'モデル番号'):
        value = specs.get(key)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{2,}', value) and re.search(r'\d', value):
            return value
    codes = re.findall(r'(?<![\w-])(?=[A-Za-z\d-]*[A-Za-z])(?=[A-Za-z\d-]*\d)[A-Za-z\d]+(?:-[A-Za-z\d]+)+(?![\w-])', product.get('name', ''))
    return codes[0] if len(codes) == 1 else ''


def _decode_html(body, content_type):
    """Decode only supported web encodings; never silently replace identity bytes."""
    aliases = {'utf-8': 'utf-8', 'utf8': 'utf-8', 'euc-jp': 'euc_jp',
               'euc_jp': 'euc_jp', 'shift_jis': 'cp932', 'shift-jis': 'cp932',
               'sjis': 'cp932', 'windows-31j': 'cp932', 'cp932': 'cp932'}
    header = re.search(r'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', content_type, re.I)
    charset = header.group(1) if header else None
    if not charset:
        # HTML meta declarations are ASCII even on legacy Japanese pages.
        prefix = body[:4096].decode('ascii', errors='ignore')
        meta = re.search(r'<meta\b[^>]*charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', prefix, re.I)
        charset = meta.group(1) if meta else 'utf-8'
    encoding = aliases.get(charset.casefold())
    if not encoding:
        raise CatalogError('unsupported HTML charset')
    try:
        return body.decode(encoding)
    except UnicodeError:
        raise CatalogError('invalid HTML encoding') from None


class _Page(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.title, self.text, self.images = '', '', []
        self.in_title, self.skip = False, 0
        self.units, self.scopes, self.structured, self.dom = [], [], [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.dom.append((tag, attrs))
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if not self.skip and tag in ('tr', 'dl', 'li', 'p', 'td', 'th', 'dt', 'dd', 'h3', 'aside'):
            self.scopes.append({'kind': tag, 'parts': [], 'cells': [], 'asides': [],
                                'class': attrs.get('class', ''), 'ancestors': tuple(self.dom)})
        if tag == 'title':
            self.in_title = True
        if tag == 'img' and attrs.get('src'):
            self.images.append(attrs['src'])
        if tag == 'meta' and attrs.get('property') == 'og:image':
            self.images.append(attrs.get('content', ''))

    def handle_endtag(self, tag):
        if not self.skip:
            index = next((i for i in range(len(self.scopes) - 1, -1, -1) if self.scopes[i]['kind'] == tag), None)
            if index is not None:
                unit = self.scopes[index]
                del self.scopes[index:]
                unit['text'] = ' '.join(' '.join(unit.pop('parts')).split())
                if tag == 'aside':
                    for parent in reversed(self.scopes):
                        if parent['kind'] == 'dl':
                            parent['asides'].append(unit['text'])
                            break
                if tag in ('tr', 'dl', 'p'):
                    self.units.append(unit)
                if tag == 'dl':
                    self.structured.append(unit)
                elif tag == 'li' and any(s['kind'] == 'dl' and 'pd__specification' in s['class'] for s in self.scopes):
                    self.structured.append(unit)
                elif self.scopes:
                    self.scopes[-1]['cells'].append((tag, unit['text']))
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if tag == 'title':
            self.in_title = False
        index = next((i for i in range(len(self.dom) - 1, -1, -1) if self.dom[i][0] == tag), None)
        if index is not None:
            del self.dom[index:]

    def handle_data(self, data):
        if not self.skip:
            self.text += ' ' + data
            for scope in self.scopes:
                scope['parts'].append(data)
        if self.in_title:
            self.title += data


SPEC_LABELS = {'model': ('model', 'modelNumber', '型番', '品番', 'モデル番号', 'メーカー品番'),
               'weight': ('weight', '重量', '質量', '重さ'),
               'size': ('size', 'サイズ', '寸法', '製品サイズ'), 'capacity': ('capacity', '容量')}
def _pairs(unit):
    cells = unit['cells']
    if unit['kind'] == 'dl':
        return [(cells[n][1], cells[n + 1][1]) for n in range(len(cells) - 1)
                if cells[n][0] == 'dt' and cells[n + 1][0] == 'dd']
    if unit['kind'] == 'li':
        labels = [v for tag, v in cells if tag == 'h3']
        values = [v for tag, v in cells if tag == 'p']
        return [(labels[0], values[0])] if len(labels) == len(values) == 1 else []
    return []


def _has_ancestor(unit, tag, attr, value):
    return any(name == tag and value in (attrs.get(attr, '').split() if attr == 'class' else (attrs.get(attr),))
               for name, attrs in unit['ancestors'])


def _primary_units(page, brand):
    brand = brand.casefold()
    if brand == 'soto':
        spec_dls = [unit for unit in page.structured if unit['kind'] == 'dl'
                    and 'pd__specification' in unit['class'].split()
                    and _has_ancestor(unit, 'article', 'class', 'pdContents')
                    and _has_ancestor(unit, 'section', 'class', 'pdContents__info')]
        if len(spec_dls) != 1:
            return []
        return [unit for unit in page.structured if unit['kind'] == 'li'
                and _has_ancestor(unit, 'article', 'class', 'pdContents')
                and _has_ancestor(unit, 'section', 'class', 'pdContents__info')
                and _has_ancestor(unit, 'dl', 'class', 'pd__specification')]
    if brand in ('snow peak', 'スノーピーク'):
        return [unit for unit in page.structured if unit['kind'] == 'dl'
                and _has_ancestor(unit, 'div', 'id', 'tab-size')]
    if brand in ('uniflame', 'ユニフレーム'):
        return [unit for unit in page.structured if unit['kind'] == 'dl'
                and _has_ancestor(unit, 'article', 'id', 'product')
                and _has_ancestor(unit, 'ul', 'class', 'item-spec')]
    return []


def _structured_model_codes(units):
    model_labels = {label.casefold() for label in SPEC_LABELS['model']}
    return [(label.strip(), value.strip()) for unit in units
            for label, value in _pairs(unit) if label.strip().casefold() in model_labels]


def _primary_identity(page, model, brand):
    brand_names = {'snow peak', 'スノーピーク'} if brand.casefold() in ('snow peak', 'スノーピーク') else {brand.casefold()}
    if not any(name in page.title.casefold() for name in brand_names if name):
        return None
    units = _primary_units(page, brand)
    if brand.casefold() in ('soto', 'snow peak', 'スノーピーク', 'uniflame', 'ユニフレーム') and not units:
        return None
    model_codes = _structured_model_codes(units)
    if model_codes:
        matches = [(label, value) for label, value in model_codes if re.fullmatch(
            re.escape(model) + r'\s*(?:\([^()]*\)|（[^（）]*）)?', value.strip(), re.I)]
        if len(model_codes) != len(matches) or len(model_codes) != 1:
            return None
        return model_codes[0][0]
    return 'title' if model_matches(model, page.title) else None


def _spec_evidence(page, model, key, value, primary_identity=False, brand=None):
    """Match exact values in a known primary scope, or in one model-bound legacy unit."""
    labels = next((v for v in SPEC_LABELS.values() if key.casefold() in [x.casefold() for x in v]), None)
    if labels is None and re.search(r'[^\x00-\x7f]', key):
        labels = (key,)
    if labels is None:
        return None
    label_set = {s.casefold() for s in labels}
    units = _primary_units(page, brand or '') if primary_identity else []
    if primary_identity and (brand or '').casefold() in ('soto', 'snow peak', 'スノーピーク', 'uniflame', 'ユニフレーム') and not units:
        return None
    if primary_identity and units:
        model_codes = _structured_model_codes(units)
        if model_codes and (len(model_codes) != 1 or not re.fullmatch(
                re.escape(model) + r'\s*(?:\([^()]*\)|（[^（）]*）)?', model_codes[0][1], re.I)):
            return None
        matches = []
        soto_spec = (brand or '').casefold() == 'soto'
        for unit in units:
            pairs = _pairs(unit)
            if any(label.strip().casefold() in {s.casefold() for s in SPEC_LABELS['model']}
                   and not model_matches(model, source_value) for label, source_value in pairs):
                continue
            for label, source_value in pairs:
                if label.strip().rstrip(':：').casefold() not in label_set:
                    continue
                source_value = source_value.strip()
                exact = source_value == value.strip()
                if key.casefold() in {s.casefold() for s in SPEC_LABELS['model']}:
                    exact = bool(re.fullmatch(re.escape(value.strip()) + r'\s*(?:\([^()]*\)|（[^（）]*）)?', source_value, re.I))
                matches.append((unit, source_value, exact))
        if matches:
            if len(matches) != 1 or not matches[0][2]:
                return None
            unit, source_value, _ = matches[0]
            aside = [v for tag, v in unit['cells'] if tag == 'aside']
            if soto_spec:
                aside += [v for block in page.structured if block['kind'] == 'dl' and 'pd__specification' in block['class']
                          and _has_ancestor(block, 'article', 'class', 'pdContents')
                          and _has_ancestor(block, 'section', 'class', 'pdContents__info')
                          for v in block['asides']]
            return {'unit': unit['kind'], 'model': model, 'field': key, 'value': value,
                    'excerpt': unit['text'][:500], 'conditions': aside[:3]}
        if key.casefold() in {s.casefold() for s in SPEC_LABELS['model']} and value.casefold() == model.casefold():
            return {'unit': 'primary identity', 'model': model, 'field': key, 'value': value,
                    'excerpt': page.title[:300], 'conditions': []}
        return None
    for unit in page.units:
        text, kind = unit['text'], unit['kind']
        if len(text) > (240 if kind == 'p' else 500) or not model_matches(model, text):
            continue
        codes = re.findall(r'(?<![\w-])(?=[A-Za-z\d-]*[A-Za-z])(?=[A-Za-z\d-]*\d)[A-Za-z\d]+(?:-[A-Za-z\d]+)+(?![\w-])', text)
        codes += [code for code in re.findall(r'(?<![\w-])[A-Za-z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)*(?![\w-])', text) if re.search(r'\d', code)]
        if model.isdigit():
            codes += re.findall(r'(?<![\w.])\d{4,}(?![\w.])', text)
        if any(code.casefold() != model.casefold() for code in codes):
            continue
        pairs = []
        cells = unit['cells']
        if kind == 'dl':
            for n in range(len(cells) - 1):
                if cells[n][0] == 'dt' and cells[n + 1][0] == 'dd':
                    pairs.append((cells[n][1], cells[n + 1][1]))
        elif kind == 'tr':
            pairs = [(cells[n][1], cells[n + 1][1]) for n in range(len(cells) - 1)]
        else:
            # A paragraph must say e.g. "ST-310 weight: 350g". An unrelated
            # qualifier such as "packed weight" cannot satisfy "weight".
            body = re.sub(r'(?<![\w-])' + re.escape(model) + r'(?![\w-])', '', text, flags=re.I)
            if label_set == {s.casefold() for s in SPEC_LABELS['model']}:
                body = text
            for clause in re.split(r'[;；、。]', body):
                for label in labels:
                    match = re.fullmatch(r'\s*' + re.escape(label) + r'\s*[:：=]?\s*(.+?)\s*', clause, re.I)
                    if match:
                        pairs.append((label, match[1]))
        values = [v.strip() for label, v in pairs if label.strip().rstrip(':：').casefold() in label_set]
        if values == [value.strip()]:
            return {'unit': kind, 'model': model, 'field': key, 'value': value,
                    'excerpt': text[:500], 'conditions': []}
    return None


def _image_type(body):
    """Inspect downloaded binary structure, not URL suffix/Content-Type alone."""
    if body.startswith(b'\x89PNG\r\n\x1a\n'):
        try:
            offset, compressed, dimensions, ended = 8, bytearray(), None, False
            while offset + 12 <= len(body):
                size = int.from_bytes(body[offset:offset + 4], 'big')
                kind = body[offset + 4:offset + 8]
                data = body[offset + 8:offset + 8 + size]
                crc = body[offset + 8 + size:offset + 12 + size]
                if len(crc) != 4 or zlib.crc32(kind + data) != int.from_bytes(crc, 'big'):
                    return None
                if kind == b'IHDR':
                    if offset != 8 or size != 13:
                        return None
                    w, h, depth, color, method, filtering, interlace = struct.unpack('>IIBBBBB', data)
                    if not 0 < w <= 16000 or not 0 < h <= 16000 or method or filtering or interlace:
                        return None
                    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
                    if not channels or depth not in (1, 2, 4, 8, 16):
                        return None
                    dimensions = (w, h, channels, depth)
                elif kind == b'IDAT':
                    compressed.extend(data)
                elif kind == b'IEND':
                    ended = size == 0 and offset + 12 == len(body)
                    break
                offset += size + 12
            if not ended or not dimensions or not compressed:
                return None
            w, h, channels, depth = dimensions
            expected = (((w * channels * depth + 7) // 8) + 1) * h
            if expected > 64 * 1024 * 1024:
                return None
            decoder = zlib.decompressobj()
            pixels = decoder.decompress(bytes(compressed), expected + 1)
            if len(pixels) != expected or not decoder.eof:
                return None
            return 'image/png'
        except (ValueError, struct.error, zlib.error):
            return None
    if len(body) >= 4 and body.startswith(b'\xff\xd8\xff') and body.endswith(b'\xff\xd9'):
        # Require a dimensional start-of-frame and scan before the end marker.
        for match in re.finditer(b'\xff[\xc0-\xc3\xc5-\xc7\xc9-\xcb\xcd-\xcf]', body):
            pos = match.end()
            if pos + 8 <= len(body):
                h, w = struct.unpack('>HH', body[pos + 3:pos + 7])
                if 0 < w <= 16000 and 0 < h <= 16000 and b'\xff\xda' in body[pos + 7:]:
                    return 'image/jpeg'
    if len(body) >= 14 and body[:6] in (b'GIF87a', b'GIF89a') and body[-1:] == b';':
        w, h = struct.unpack('<HH', body[6:10])
        if 0 < w <= 16000 and 0 < h <= 16000 and b',' in body[13:]:
            return 'image/gif'
    if len(body) >= 30 and body[:4] == b'RIFF' and body[8:12] == b'WEBP' and body[12:16] in (b'VP8 ', b'VP8L', b'VP8X'):
        if int.from_bytes(body[4:8], 'little') + 8 == len(body):
            return 'image/webp'
    return None


def _affiliate_route(channel, url, env):
    try:
        p, _ = safe_url(url, resolve=False)
        query = parse_qs(p.query)
        if channel == 'rakuten':
            owner = env.get('RAKUTEN_AFFILIATE_ID')
            return bool(owner and p.hostname == 'hb.afl.rakuten.co.jp' and p.path.startswith('/ichiba/' + owner + '/'))
        if channel == 'amazon':
            owner = env.get('AMAZON_PARTNER_TAG')
            return bool(owner and p.hostname in ('amazon.co.jp', 'www.amazon.co.jp')
                        and re.fullmatch(r'/(?:[^/]+/)?(?:dp|gp/product)/[A-Z0-9]{10}/?', p.path)
                        and query.get('tag') == [owner])
        return channel == 'yahoo'
    except CatalogError:
        return False


def _camel(row):
    def key(k):
        return 'order' if k == 'sort_order' else re.sub(r'_([a-z])', lambda m: m[1].upper(), k)
    return {key(k): v for k, v in row.items()}


class Catalog:
    def __init__(self, env, fetcher=None, source_hints=None):
        self.env, self.fetcher = dict(env), fetcher
        self.source_hints = dict(source_hints or {})

    def health(self):
        return {'envKeys': {key: bool(self.env.get(key)) for key in ENV_KEYS},
                'readonly': True, 'networkChecked': False}

    def request(self, url, headers=None, allowed_domains=None):
        """Bounded GET; pinned DNS, no proxies, redirects rechecked before use."""
        headers = dict(headers or {})
        try:
            for hop in range(6):
                p, addresses = safe_url(url, resolve=self.fetcher is None)
                if allowed_domains and not any(p.hostname == d or p.hostname.endswith('.' + d) for d in allowed_domains):
                    raise CatalogError('manufacturer host rejected')
                if self.fetcher:
                    result = self.fetcher(url, dict(headers), 20)
                else:
                    for address in addresses:
                        conn = _PinnedHTTPS(p.hostname, address)
                        try:
                            conn.request('GET', p.path + ('?' + p.query if p.query else ''), headers=headers)
                            res = conn.getresponse()
                            result = {'status': res.status, 'headers': dict(res.getheaders()), 'body': res.read(MAX_BYTES + 1)}
                            break
                        except OSError:
                            if address == addresses[-1]:
                                raise
                        finally:
                            conn.close()
                status = result['status']
                rh = {k.lower(): v for k, v in result.get('headers', {}).items()}
                if status in (301, 302, 303, 307, 308):
                    # API credentials never travel through a redirect, even same host.
                    if any(k.lower() not in ('accept', 'user-agent', 'cache-control') for k in headers) or any(k.casefold() in ('applicationid', 'accesskey', 'apikey', 'token', 'key') for k in parse_qs(p.query)):
                        raise CatalogError('authenticated redirect refused')
                    url = urljoin(url, rh.get('location', ''))
                    headers = {}
                    continue
                body = result.get('body', b'')
                if not isinstance(body, bytes) or len(body) > MAX_BYTES or status != 200:
                    raise CatalogError('HTTP response rejected')
                return {'url': url, 'status': status, 'headers': rh, 'body': body}
            raise CatalogError('redirect limit exceeded')
        except Exception:
            raise CatalogError('catalog request failed') from None

    def _json(self, url, headers=None):
        try:
            return json.loads(self.request(url, headers)['body'])
        except Exception:
            raise CatalogError('catalog request failed') from None

    def image_digest(self, url):
        """Shared publisher transport: HTTPS/public DNS pinned at EVERY redirect.

        No credentials, bounded actual bytes, binary type checked; only digest
        metadata leaves this helper, never downloaded bytes or a raw exception.
        """
        res = self.request(url, {'Accept': 'image/*', 'Cache-Control': 'no-cache'})
        content_type = res['headers'].get('content-type', '').split(';')[0].lower()
        if _image_type(res['body']) != content_type or not content_type.startswith('image/'):
            raise CatalogError('image response invalid')
        return {'sha256': hashlib.sha256(res['body']).hexdigest(), 'size': len(res['body']), 'contentType': content_type}

    def catalog(self):
        if not all(self.env.get(k) for k in ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY')):
            raise CatalogError('catalog credentials missing')
        base = self.env['SUPABASE_URL'].rstrip('/')
        p, _ = safe_url(base, resolve=False)
        if p.query or p.fragment or p.path not in ('', '/'):
            raise CatalogError('invalid database origin')
        key = self.env['SUPABASE_SERVICE_ROLE_KEY']
        headers = {'apikey': key, 'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}
        result = {}
        for name, table, fields in (('articles', 'articles', ARTICLE_FIELDS), ('products', 'products', PRODUCT_FIELDS),
                                    ('categories', 'categories', CATEGORY_FIELDS), ('clicks', 'affiliate_clicks', CLICK_FIELDS)):
            rows, offset = [], 0
            while True:
                query = {'select': fields, 'limit': 500, 'offset': offset,
                         'order': 'clicked_at.asc,id.asc' if name == 'clicks' else 'id.asc'}
                batch = self._json(base + '/rest/v1/' + table + '?' + urlencode(query), headers)
                if not isinstance(batch, list) or any(not isinstance(r, dict) for r in batch):
                    raise CatalogError('invalid catalog response')
                allowed = set(fields.split(','))
                rows.extend(_camel({k: v for k, v in row.items() if k in allowed}) for row in batch)
                if len(batch) < 500:
                    break
                offset += len(batch)
                if offset >= 100000:
                    raise CatalogError('catalog pagination limit exceeded')
            result[name] = rows
        return self._public(result)

    def _public(self, value):
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        for key in ('SUPABASE_SERVICE_ROLE_KEY', 'BRAVE_API_KEY', 'RAKUTEN_ACCESS_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY'):
            secret = self.env.get(key)
            # Public referral IDs and APP_ID are intentionally excluded. Short
            # placeholders cannot identify a secret in ordinary public prose.
            if isinstance(secret, str) and len(secret) >= 16 and (secret in encoded or urlencode({'v': secret})[2:] in encoded):
                raise CatalogError('credential reflection refused')
        return value

    def gather(self, theme, catalog):
        """Return immutable catalogue claims plus observed evidence; never infer specs.

        theme.productIds explicitly selects 1–5 existing products of one category.
        Without IDs, choose the first 3–5 in theme.categoryId. No new product IDs.
        Manufacturer title+exact model+every catalogue spec must be corroborated;
        prices/availability remain unconfirmed and require upper reviewer scrutiny.
        """
        products = catalog.get('products', [])
        ids = theme.get('productIds')
        explicit = ids is not None
        if ids is None:
            ids = [p['id'] for p in products if p.get('categoryId') == theme.get('categoryId')][:5]
        if not isinstance(ids, list) or not (1 if explicit else 3) <= len(ids) <= 5 or len(set(ids)) != len(ids):
            raise CatalogError('select 1–5 explicit or 3–5 automatic distinct existing products')
        by_id = {p['id']: p for p in products}
        if any(pid not in by_id for pid in ids):
            raise CatalogError('unknown catalog product')
        selected = json.loads(json.dumps([by_id[pid] for pid in ids], ensure_ascii=False, allow_nan=False))
        if len({p.get('categoryId') for p in selected}) != 1 or not selected[0].get('categoryId'):
            raise CatalogError('products must share one category')
        references, images, details = [], [], []
        checked_at = datetime.now(JST).isoformat()
        for product in selected:
            pid, model = product['id'], _model(product)
            item = {'productId': pid, 'model': model, 'facts': False, 'images': False, 'affiliate': False,
                    'claims': [], 'destinations': [], 'issues': [], 'checkedAt': checked_at}
            maker_pages, mall_pages = [], []
            def page(url, kind):
                res = self.request(url, allowed_domains=domains if kind == 'manufacturer' else None)
                if not res['headers'].get('content-type', '').lower().startswith('text/html'):
                    raise CatalogError('HTML required')
                parsed = _Page(_decode_html(res['body'], res['headers'].get('content-type', '')))
                identity = _primary_identity(parsed, model, product.get('brand', '')) if kind == 'manufacturer' else None
                match = bool(identity) if kind == 'manufacturer' else (model_matches(model, parsed.title) and product.get('brand', '').casefold() in parsed.title.casefold())
                # Store evidence of exact comparisons, never user review text.
                if match:
                    references.append({'productId': pid, 'kind': kind, 'url': res['url'], 'checkedAt': checked_at,
                                       'text': 'Brand title and primary identity (' + (identity or 'title') + '): ' + model})
                return res, parsed, match
            try:
                domains = MAKERS.get(product.get('brand', '').casefold(), ())
                for url in self.source_hints.get(pid, []):
                    try:
                        host = urlsplit(url).hostname or ''
                        if not any(host == d or host.endswith('.' + d) for d in domains):
                            continue
                        res, parsed, match = page(url, 'manufacturer')
                        final_host = urlsplit(res['url']).hostname or ''
                        if match and any(final_host == d or final_host.endswith('.' + d) for d in domains):
                            maker_pages.append((res, parsed))
                    except (CatalogError, ValueError):
                        item['issues'].append('manufacturer page unavailable')
                specs = product.get('specs') or {}
                image_url = product.get('imageUrl', '')
                hints_complete = bool(model and maker_pages and specs and image_url
                    and all(isinstance(value, str) and value and any(
                        _spec_evidence(parsed, model, key, value, primary_identity=True, brand=product.get('brand', ''))
                        for _, parsed in maker_pages) for key, value in specs.items())
                    and any(image_url in [urljoin(res['url'], src) for src in parsed.images]
                            for res, parsed in maker_pages))
                if not hints_complete and self.env.get('BRAVE_API_KEY'):
                    data = self._json('https://api.search.brave.com/res/v1/web/search?' + urlencode({'q': product['brand'] + ' ' + product['name'] + ' 公式 仕様', 'count': 5}),
                                      {'X-Subscription-Token': self.env['BRAVE_API_KEY'], 'Accept': 'application/json'})
                    for found in data.get('web', {}).get('results', [])[:5]:
                        url = found.get('url', '')
                        host = urlsplit(url).hostname or ''
                        if any(host == d or host.endswith('.' + d) for d in domains):
                            try:
                                res, parsed, match = page(url, 'manufacturer')
                                final_host = urlsplit(res['url']).hostname or ''
                                if match and any(final_host == d or final_host.endswith('.' + d) for d in domains):
                                    maker_pages.append((res, parsed))
                            except CatalogError:
                                item['issues'].append('manufacturer page unavailable')
                if not hints_complete and self.env.get('RAKUTEN_APP_ID') and self.env.get('RAKUTEN_ACCESS_KEY'):
                    data = self._json('https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701?' + urlencode({
                        'applicationId': self.env['RAKUTEN_APP_ID'], 'accessKey': self.env['RAKUTEN_ACCESS_KEY'],
                        'keyword': product['name'], 'hits': 5, 'formatVersion': 2}),
                        {'Accept': 'application/json', 'Origin': 'https://camp-gear-lab.com', 'Referer': 'https://camp-gear-lab.com/'})
                    for raw in data.get('items', data.get('Items', []))[:5]:
                        raw = raw.get('item', raw.get('Item', raw))
                        if model_matches(model, raw.get('itemName', '')) and product['brand'].casefold() in raw.get('itemName', '').casefold():
                            url = raw.get('itemUrl', '')
                            if urlsplit(url).hostname == 'item.rakuten.co.jp':
                                try:
                                    res, parsed, match = page(url, 'mall')
                                    if match and urlsplit(res['url']).hostname == 'item.rakuten.co.jp':
                                        mall_pages.append((res, parsed))
                                except CatalogError:
                                    item['issues'].append('mall page unavailable')
            except CatalogError:
                item['issues'].append('research unavailable')
            specs = product.get('specs') or {}
            for key, value in specs.items():
                if not isinstance(value, str) or not value:
                    item['claims'].append({'field': key, 'verified': False})
                    continue
                proof = next(((res['url'], binding) for res, parsed in maker_pages
                              for binding in [_spec_evidence(parsed, model, key, value, primary_identity=True,
                                                            brand=product.get('brand', ''))] if binding), None)
                source, binding = proof if proof else (None, None)
                item['claims'].append({'field': key, 'text': value, 'url': source, 'binding': binding,
                                       'verified': proof is not None, 'checkedAt': checked_at})
                if proof:
                    references.append({'productId': pid, 'kind': 'manufacturer-spec', 'url': source,
                                       'checkedAt': checked_at, 'field': key,
                                       'text': binding['excerpt'], 'conditions': binding['conditions']})
            item['facts'] = bool(model and maker_pages and specs and all(c['verified'] for c in item['claims']))
            # Descriptions, subjective ratings, price and availability are NOT certified by specs.
            item['unverifiedFields'] = ['description', 'rating', 'price', 'availability']
            image_url = product.get('imageUrl', '')
            identity_source = next((res['url'] for res, parsed in maker_pages + mall_pages
                                    if image_url in [urljoin(res['url'], u) for u in parsed.images]), None)
            try:
                res = self.request(image_url)
                actual_type = _image_type(res['body'])
                declared_type = res['headers'].get('content-type', '').split(';')[0].lower()
                verified = bool(identity_source and actual_type and actual_type == declared_type and len(res['body']) >= 32)
                image = {'productId': pid, 'url': image_url, 'imageURL': image_url, 'finalUrl': res['url'],
                         'sha256': hashlib.sha256(res['body']).hexdigest(), 'size': len(res['body']),
                         'contentType': declared_type, 'identitySource': identity_source,
                         'checkedAt': checked_at, 'verified': verified}
                images.append(image)
                item['images'] = verified
            except CatalogError:
                item['issues'].append('image unavailable')
            for channel, field in (('rakuten', 'affiliateUrl'), ('amazon', 'amazonUrl'), ('yahoo', 'yahooUrl')):
                if not product.get(field):
                    continue
                try:
                    res, parsed, match = page(product[field], 'purchase')
                    host = urlsplit(res['url']).hostname or ''
                    allowed = (host == 'item.rakuten.co.jp' if channel == 'rakuten' else
                               host in ('amazon.co.jp', 'www.amazon.co.jp') if channel == 'amazon' else
                               host == 'store.shopping.yahoo.co.jp' and
                               bool(re.fullmatch(r'/[^/]+/[^/]+\.html', urlsplit(res['url']).path)))
                    verified = bool(match and allowed and _affiliate_route(channel, product[field], self.env))
                    item['destinations'].append({'channel': channel, 'url': product[field], 'finalUrl': res['url'],
                                                 'verified': verified, 'checkedAt': checked_at,
                                                 'text': 'catalog brand and exact model title check'})
                except CatalogError:
                    item['destinations'].append({'channel': channel, 'verified': False, 'checkedAt': checked_at})
            item['affiliate'] = bool(item['destinations'] and all(d['verified'] for d in item['destinations']))
            details.append(item)
        checks = {key: all(d[key] for d in details) for key in ('facts', 'images', 'affiliate')}
        existing = [{k: a.get(k) for k in ('id', 'title', 'slug', 'categoryId', 'excerpt')}
                    for a in catalog.get('articles', []) if a.get('status') == 'published'
                    and a.get('categoryId') == selected[0]['categoryId']][:5]
        counts = {}
        for click in catalog.get('clicks', []):
            if click.get('productId') in ids:
                key = (click['productId'], click.get('store', 'unknown'))
                counts[key] = counts.get(key, 0) + 1
        merchant_clicks = [{'productId': pid, 'store': store, 'clicks': count}
                           for (pid, store), count in sorted(counts.items())]
        return self._public({'theme': theme, 'catalog': selected, 'products': selected, 'productIds': ids,
                'existingArticles': existing, 'categories': [c for c in catalog.get('categories', []) if c.get('id') == selected[0]['categoryId']],
                'merchantClicks': merchant_clicks, 'references': references, 'images': images,
                'checks': checks, 'evidence': {'products': details}, 'blocked': not all(checks.values())})
