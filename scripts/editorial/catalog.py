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

MAKERS.update({'primus': ('iwatani-primus.jp', 'iwatani-primus.co.jp', 'iwatani-i-collect.com'),
               'プリムス': ('iwatani-primus.jp', 'iwatani-primus.co.jp', 'iwatani-i-collect.com'),
               'msr': ('e-mot.co.jp', 'cascadedesigns.com', 'msrgear.com'),
               'jetboil': ('montbell.jp', 'jetboil.jp'),
               'ジェットボイル': ('montbell.jp', 'jetboil.jp'),
               'captain stag': ('captainstag.net',), 'キャプテンスタッグ': ('captainstag.net',),
               'iwatani': ('iwatani.co.jp',), 'イワタニ': ('iwatani.co.jp',),
               'picogrill': ('picogrill.ch',), 'ピコグリル': ('picogrill.ch',),
               'tokyocamp': ('tokyocamp.ooo',),
               'solo stove': ('store.upioutdoor.com', 'solostove.com'),
               'ソロストーブ': ('store.upioutdoor.com', 'solostove.com')})


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
        if (product.get('id') == 'burner-s-009' and product.get('brand', '').casefold() in ('iwatani', 'イワタニ')
                and value == 'CB-JCB'):
            return value
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
        self.identity_nodes, self._identity_scopes = [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.dom.append((tag, attrs))
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if not self.skip and tag in ('div', 'span', 'p', 'h1', 'h2'):
            self._identity_scopes.append({'kind': tag, 'parts': [], 'ancestors': tuple(self.dom)})
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
            i = next((i for i in range(len(self._identity_scopes) - 1, -1, -1) if self._identity_scopes[i]['kind'] == tag), None)
            if i is not None:
                item = self._identity_scopes[i]
                del self._identity_scopes[i:]
                text = ' '.join(' '.join(item.pop('parts')).split())
                if len(text) < 180 and (tag in ('h1', 'h2') or re.match(r'^(?:品番|型番|商品コード|No\.|(?:M|UK)-\d)', text)):
                    self.identity_nodes.append({**item, 'text': text})
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
            for scope in self._identity_scopes:
                scope['parts'].append(data)
        if self.in_title:
            self.title += data


SPEC_LABELS = {'model': ('model', 'modelNumber', '型番', '品番', 'モデル番号', 'メーカー品番'),
               'weight': ('weight', '重量', '質量', '重さ'),
               'size': ('size', 'サイズ', '寸法', '製品サイズ'), 'capacity': ('capacity', '容量')}
def _pairs(unit):
    cells = unit['cells']
    if unit.get('primary_pairs') is not None:
        return unit['primary_pairs']
    if unit['kind'] == 'tr':
        return [(cells[n][1], cells[n + 1][1]) for n in range(len(cells) - 1)
                if cells[n][0] in ('th', 'td') and cells[n + 1][0] == 'td']
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
    family = next((key for key, aliases in (
        ('primus', ('primus', 'プリムス')), ('msr', ('msr',)),
        ('jetboil', ('jetboil', 'ジェットボイル')), ('captain', ('captain stag', 'キャプテンスタッグ')),
        ('iwatani', ('iwatani', 'イワタニ')))
        if brand in aliases), None)
    if family:
        def scoped(u):
            if any(t in ('aside', 'nav', 'footer', 'template') for t, _ in u['ancestors']):
                return False
            return {'primus': lambda: _has_ancestor(u, 'div', 'class', 'block-goods-detail'),
                    'msr': lambda: _has_ancestor(u, 'div', 'class', 'elementor-28641'),
                    'jetboil': lambda: _has_ancestor(u, 'div', 'id', 'contents'),
                    'captain': lambda: _has_ancestor(u, 'section', 'class', 'item_main'),
                    'iwatani': lambda: _has_ancestor(u, 'main', 'id', 'main')}[family]()
        selected, codes = [], []
        for u in page.units:
            if not scoped(u): continue
            pairs = _pairs(u)
            if family == 'primus' and u['kind'] == 'dl' and 'block-goods-code' in u['class'].split():
                codes.extend(v for k, v in pairs if k == '商品コード')
            elif family == 'jetboil' and _has_ancestor(u, 'div', 'id', 'maindataCont'):
                codes.extend(v.lstrip('#') for k, v in pairs if k == '品番')
            elif family == 'iwatani' and u['kind'] == 'dl' and 'products_detail' in u['class'].split():
                codes.extend(v for k, v in pairs if k.rstrip(' ：:') == '商品コード')
            is_spec = ((family == 'primus' and 'block-goods-comment2' in u['class'].split()) or
                       (family == 'msr' and _has_ancestor(u, 'table', 'class', 'woocommerce-spec-table') and u['kind'] == 'tr') or
                       (family == 'jetboil' and _has_ancestor(u, 'div', 'class', 'column1') and u['kind'] == 'p' and '【重量】' in u['text']) or
                       (family == 'captain' and _has_ancestor(u, 'div', 'class', 'txt_product_spec') and u['kind'] == 'tr') or
                       (family == 'iwatani' and _has_ancestor(u, 'table', 'class', 'table_style01') and _has_ancestor(u, 'section', 'class', 'sec_box_wrap') and u['kind'] == 'tr'))
            if is_spec:
                if family in ('primus', 'jetboil'):
                    pairs = [(m[1], m[2].strip()) for m in re.finditer(r'【([^】]+)】([^【]+)', u['text'])]
                selected.append({**u, 'primary_pairs': pairs})
        if family in ('msr', 'captain'):
            for node in page.identity_nodes:
                header_code = (family == 'captain' and _has_ancestor(node, 'main', 'id', 'main')
                               and _has_ancestor(node, 'header', 'class', 'item_area_head')
                               and _has_ancestor(node, 'p', 'class', 'product_id')
                               and not any(t in ('aside', 'nav', 'footer', 'template') for t, _ in node['ancestors']))
                if not scoped(node) and not header_code: continue
                pattern = r'^品番\s*(\d+)(?:\s+カテゴリー\s+[^\d]+)?$' if family == 'msr' else r'^((?:M|UK)-\d+)$'
                m = re.fullmatch(pattern, node['text'])
                if m:
                    # UK authority comes only from the maker's primary header,
                    # never a SKU in a related item or arbitrary item_main text.
                    if family == 'captain' and m[1].startswith('UK-') and (
                            not header_code or node['kind'] != 'p'
                            or any(tag == 'section' for tag, _ in node['ancestors'])):
                        continue
                    codes.append(m[1])
        if family == 'captain' and any(code.startswith('UK-') for code in codes):
            # Do not collapse duplicate or conflicting UK primary identities.
            if len(codes) != 1:
                return []
            selected = [u for u in selected if _has_ancestor(u, 'main', 'id', 'main')
                        and not _has_ancestor(u, 'section', 'class', 'sec_other_item')]
        codes = list(dict.fromkeys(codes))
        if not selected or len(codes) != 1:
            return []
        return [{'kind': 'dl', 'cells': [], 'text': 'model ' + codes[0],
                 'primary_pairs': [('model', codes[0])], 'ancestors': (), 'class': ''}] + selected
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
        units = [unit for unit in page.structured if unit['kind'] == 'dl'
                and _has_ancestor(unit, 'article', 'id', 'product')
                and _has_ancestor(unit, 'ul', 'class', 'item-spec')]
        codes = list(dict.fromkeys(m[1] for node in page.identity_nodes
                     if _has_ancestor(node, 'article', 'id', 'product') and _has_ancestor(node, 'div', 'id', 'item')
                     and not any(t in ('aside', 'nav', 'footer', 'template') for t, _ in node['ancestors'])
                     for m in [re.fullmatch(r'No\.\s*(\d{6})', node['text'])] if m))
        if len(codes) > 1: return []
        if codes and units:
            units = [{'kind': 'dl', 'cells': [], 'text': 'model ' + codes[0],
                      'primary_pairs': [('model', codes[0])], 'ancestors': (), 'class': ''}] + units
        return units
    return []


def _structured_model_codes(units):
    model_labels = {label.casefold() for label in SPEC_LABELS['model']}
    return [(label.strip(), value.strip()) for unit in units
            for label, value in _pairs(unit) if label.strip().casefold() in model_labels]


def _primary_identity(page, model, brand):
    aliases = ({'snow peak', 'スノーピーク'}, {'primus', 'プリムス'}, {'jetboil', 'ジェットボイル'},
               {'captain stag', 'キャプテンスタッグ'}, {'iwatani', 'イワタニ', '岩谷産業'})
    brand_names = next((names for names in aliases if brand.casefold() in names), {brand.casefold()})
    if not any(name in page.title.casefold() for name in brand_names if name):
        return None
    units = _primary_units(page, brand)
    if brand.casefold() in ('soto', 'snow peak', 'スノーピーク', 'uniflame', 'ユニフレーム', 'primus', 'プリムス', 'msr', 'jetboil', 'ジェットボイル', 'captain stag', 'キャプテンスタッグ', 'iwatani', 'イワタニ') and not units:
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


def _fully_decoded_image_type(body):
    """Bounded full raster decode for the one malformed official MIME header.

    Marker inspection is only a cheap prefilter. Sharp must decode ALL pixels;
    absent dependencies, warnings, invalid data and timeout all fail closed.
    """
    import os
    from pathlib import Path
    import shutil
    import subprocess
    try:
        marker_type = _image_type(body)
        if marker_type not in ('image/jpeg', 'image/png') or not 0 < len(body) <= MAX_BYTES:
            return None
        node = shutil.which('node')
        if not node:
            return None
        script = r'''const fs=require('node:fs');
(async()=>{try{
 const sharp=require(process.argv[1]); const body=fs.readFileSync(0);
 if(!body.length||body.length>8*1024*1024)throw Error();
 const image=sharp(body,{failOn:'warning',limitInputPixels:16000000});
 const meta=await image.metadata();
 if(!['jpeg','png'].includes(meta.format)||!meta.width||!meta.height||meta.width*meta.height>16000000)throw Error();
 const decoded=await image.raw().toBuffer({resolveWithObject:true});
 if(!decoded.data.length||decoded.info.width!==meta.width||decoded.info.height!==meta.height)throw Error();
 process.stdout.write(JSON.stringify({format:meta.format,width:meta.width,height:meta.height}));
}catch{process.exitCode=1;}})();'''
        sharp = str(Path(__file__).resolve().parents[2] / 'node_modules' / 'sharp')
        value = subprocess.run([node, '-e', script, sharp], input=body, capture_output=True,
                               timeout=10, env={'PATH':os.path.dirname(node)+':/usr/bin:/bin', 'TZ':'Asia/Tokyo'})
        if value.returncode or not 0 < len(value.stdout) <= 512:
            return None
        proof = json.loads(value.stdout)
        decoded_type = {'jpeg':'image/jpeg', 'png':'image/png'}.get(proof.get('format'))
        if decoded_type != marker_type or not all(type(proof.get(k)) is int and proof[k] > 0 for k in ('width','height')):
            return None
        return decoded_type if proof['width'] * proof['height'] <= 16000000 else None
    except Exception:
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
    def __init__(self, env, fetcher=None, source_hints=None, source_notices=None):
        self.env, self.fetcher = dict(env), fetcher
        self.source_hints = dict(source_hints or {})
        self.source_notices = dict(source_notices or {})

    def health(self):
        return {'envKeys': {key: bool(self.env.get(key)) for key in ENV_KEYS},
                'readonly': True, 'networkChecked': False}

    def request(self, url, headers=None, allowed_domains=None, exact_domains=False):
        """Bounded GET; pinned DNS, redirects rechecked before each connection.

        Domain scopes retain their historical subdomain matching by default.
        exact_domains=True restricts an allowlist to the literal hostnames.
        """
        headers = dict(headers or {})
        try:
            for hop in range(6):
                p, addresses = safe_url(url, resolve=self.fetcher is None)
                # This public maker rejects the default stdlib client. Keep the
                # ordinary compatibility UA scoped to its exact official host;
                # redirects still discard headers and revalidate destinations.
                if p.hostname == 'www.iwatani.co.jp':
                    headers.setdefault('User-Agent', 'Mozilla/5.0')
                if (p.hostname, p.path) in {
                        ('soto.shinfuji.co.jp', '/products/st-233/'),
                        ('www.iwatani-primus.co.jp', '/products/primus/support/')}:
                    headers.setdefault('User-Agent', 'Mozilla/5.0')
                    headers.setdefault('Accept', 'text/html')
                if allowed_domains and not any(p.hostname == d or (not exact_domains and p.hostname.endswith('.' + d)) for d in allowed_domains):
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
                if p.hostname == 'img.snowpeak.co.jp' and rh.get('content-type') == 'image':
                    # The maker CDN advertises only "image" for valid rasters.
                    # Require full pixel decode, not marker/metadata inspection.
                    # Preserve provenance; never infer MIME from suffix/URL.
                    detected = _fully_decoded_image_type(body)
                    if detected not in ('image/jpeg', 'image/png'):
                        raise CatalogError('official raster decode failed')
                    rh['x-catalog-original-content-type'] = rh['content-type']
                    rh['content-type'] = detected
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
        proof = {'sha256': hashlib.sha256(res['body']).hexdigest(), 'size': len(res['body']), 'contentType': content_type}
        if res['headers'].get('x-catalog-original-content-type') == 'image':
            proof['declaredContentType'] = 'image'
        return proof

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

    def gather_revision(self, theme, catalog, binding):
        from revisions import validate_context
        validate_context(binding)
        ids = binding['targetProductIds']
        if theme.get('slug') != binding['baseArticle']['slug'] or theme.get('productIds') != ids:
            raise CatalogError('revision product selection not bound')
        # The exact same per-product verification runs, including unknown models and brands.
        public = dict(catalog, products=binding['candidateProducts'])
        parts = [self.gather(dict(theme, productIds=[pid]), public) for pid in ids]
        result = dict(theme=theme, productIds=list(ids),
                      checks={k: all(p['checks'][k] is True for p in parts) for k in ('facts', 'images', 'affiliate')},
                      evidence={'products': [item for p in parts for item in p['evidence']['products']]})
        for key in ('catalog', 'products', 'references', 'images'):
            result[key] = [item for p in parts for item in p[key]]
        result['existingArticles'] = [a for a in parts[0].get('existingArticles', []) if a.get('slug') != theme['slug']]
        result['categories'] = parts[0].get('categories', [])
        result['merchantClicks'] = [item for p in parts for item in p.get('merchantClicks', [])]
        result['blocked'] = not all(result['checks'].values())
        return self._public(result)

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
            fixed_firepit_ids = ('fp-001', 'fp-002', 'fp-004', 'fp-005')
            firepit_sources = {}

            def source_binding(res, parsed, key, value):
                primary = firepit_sources.get(parsed)
                if primary is not None:
                    expected = (primary['model'] if key in ('model', 'modelNumber', '型番', '品番', 'モデル番号')
                                else primary['specs'].get(key))
                    if isinstance(value, str) and value.strip() == expected:
                        return {'unit': 'fixed-official-firepit', 'model': primary['model'],
                                'field': key, 'value': value, 'excerpt': key + ': ' + value[:500],
                                'conditions': [primary['scope']]}
                    return None
                if pid in fixed_firepit_ids:
                    return None
                return _spec_evidence(parsed, model, key, value, primary_identity=True,
                                      brand=product.get('brand', ''))

            def source_images(res, parsed):
                primary = firepit_sources.get(parsed)
                if primary is not None:
                    return primary['imageUrls']
                return [urljoin(res['url'], src) for src in parsed.images]
            # Required notices are independent of optional product discovery. A
            # missing lifecycle source must never degrade into spec-only proof.
            notice_references = []
            try:
                domains = MAKERS.get(product.get('brand', '').casefold(), ())
                notices = self.source_notices.get(pid, [])
                if not isinstance(notices, list):
                    raise CatalogError('invalid required notices')
                for notice in notices:
                    if not isinstance(notice, dict) or not domains:
                        raise CatalogError('invalid required notice')
                    quotes = notice.get('quotes')
                    if not isinstance(quotes, list) or not quotes or any(
                            not isinstance(q, str) or not q.strip() for q in quotes):
                        raise CatalogError('invalid required notice quotes')
                    res = self.request(notice.get('url'), allowed_domains=domains)
                    if not res['headers'].get('content-type', '').lower().startswith('text/html'):
                        raise CatalogError('HTML required')
                    parsed = _Page(_decode_html(res['body'], res['headers'].get('content-type', '')))
                    text = ' '.join(parsed.text.split())
                    normalized = [' '.join(q.split()) for q in quotes]
                    if not all(q in text for q in normalized):
                        raise CatalogError('required notice quote missing')
                    notice_references.append({'productId': pid, 'kind': 'manufacturer-notice',
                                              'url': res['url'], 'checkedAt': checked_at,
                                              'text': ' '.join(normalized)})
            except (CatalogError, TypeError, ValueError):
                raise CatalogError('required notice unavailable') from None
            references.extend(notice_references)
            def page(url, kind):
                nonlocal model
                # These fixed public product pages return 429 JSON to an empty
                # UA but ordinary HTML to a normal browser UA. Send explicit
                # read-only headers once; no retry or verification bypass.
                headers = ({'Accept': 'text/html', 'User-Agent': 'Mozilla/5.0'}
                           if kind == 'manufacturer' and pid in fixed_firepit_ids else None)
                res = self.request(url, headers, allowed_domains=domains if kind == 'manufacturer' else None)
                if not res['headers'].get('content-type', '').lower().startswith('text/html'):
                    raise CatalogError('HTML required')
                html = _decode_html(res['body'], res['headers'].get('content-type', ''))
                parsed = _Page(html)
                identity = None
                if kind == 'manufacturer':
                    if pid in fixed_firepit_ids:
                        from primary_firepit import extract_primary
                        primary = extract_primary(product, res['url'], html)
                        if primary and (primary['model'] == model or
                                pid == 'fp-004' and not model and primary['model'] == 'HAKOSUKA'):
                            # Named model authority is granted only by the helper's
                            # exact fp-004 URL, visible title, full-body and material scope.
                            model = primary['model']
                            item['model'] = model
                            firepit_sources[parsed] = primary
                            identity = primary['scope']
                    else:
                        identity = _primary_identity(parsed, model, product.get('brand', ''))
                match = bool(identity) if kind == 'manufacturer' else (model_matches(model, parsed.title) and product.get('brand', '').casefold() in parsed.title.casefold())
                fixed_purchase_identity = None
                if kind == 'purchase' and pid in ('fp-004', 'tent-f03', 'tent-f06', 'tent-f-landlock-x'):
                    from primary_firepit import fixed_amazon_identity
                    fixed_purchase_identity = fixed_amazon_identity(pid, model, res['url'], html, parsed.title)
                    if fixed_purchase_identity and pid != 'fp-004':
                        match = True
                        identity = fixed_purchase_identity['scope']
                if kind == 'purchase' and pid in fixed_firepit_ids:
                    # Merchant aliases are authority derived from this exact
                    # observed maker SKU, never from a search snippet or title alone.
                    from primary_firepit import merchant_primary
                    merchant_body = merchant_primary(html)
                    title = parsed.title
                    compact = lambda text: re.sub(r'\s+', '', text).casefold()
                    brand_aliases = {'fp-001': ('picogrill', 'ピコグリル'),
                                     'fp-002': ('uniflame', 'ユニフレーム'),
                                     'fp-004': ('tokyocamp',),
                                     'fp-005': ('solostove', 'ソロストーブ')}
                    brand_ok = any(compact(brand) in compact(title) for brand in brand_aliases[pid])
                    if pid == 'fp-004' and fixed_purchase_identity:
                        brand_ok = True
                    accessory = re.search(r'交換|互換|ケースのみ|本体なし|本体別売|専用(?:ケース|バッグ|火床)|'
                                          r'ゴトクのみ|ロストルのみ|網のみ|スピットのみ|ピコグリル風|'
                                          r'replacement|compatible|case\s+only|carrying\s+case', title, re.I)
                    alias = False
                    if firepit_sources and brand_ok and not accessory:
                        alias = model_matches(model, title)
                        if pid == 'fp-001' and model == '0398.SP':
                            alias = alias or model_matches('398', title)
                        elif pid == 'fp-004' and model == 'HAKOSUKA':
                            alias = bool(alias or fixed_purchase_identity) and not re.search(r'titanium|チタン', title, re.I)
                        elif pid == 'fp-005' and model == 'SSRAN-SD-2':
                            kit_title = re.search(r'(?:rangerkit|レンジャーキット)2\.0(?![a-z0-9.])', compact(title))
                            alias = bool(kit_title and model_matches(model, merchant_body)
                                         and re.search(r'専用(?:の)?スタンド', merchant_body)
                                         and not re.search(r'本体のみ|スタンド別売|SSRANJP', merchant_body, re.I))
                    match = bool(firepit_sources and brand_ok and not accessory and alias)
                    if match:
                        bundle_verified = True
                        if pid == 'fp-001':
                            # A complete maker set contains two skewers. A seller's
                            # body title cannot certify that bundle, nor can a nearby
                            # replacement-parts or review paragraph supply it.
                            body_title = (re.search(r'焚き?火台|firepit|fire\s+pit', title, re.I)
                                          and not re.search(r'(?:用|専用).*?(?:串|スピット|skewer)|(?:串|スピット|skewer).*?(?:セット|set)', title, re.I))
                            counts = re.findall(r'(?:串|スピット|skewers?)\s*[×x:：]?\s*([0-9０-９]+)\s*(?:本|pcs)?', merchant_body, re.I)
                            normalized_counts = [int(value.translate(str.maketrans('０１２３４５６７８９', '0123456789'))) for value in counts]
                            bundle_verified = bool(body_title and normalized_counts
                                and all(count == 2 for count in normalized_counts)
                                and model_matches('398', merchant_body)
                                and not re.search(r'(?:picogrill|ピコグリル)\s*(?!398(?![0-9]))[0-9]{3,4}', merchant_body, re.I)
                                and not re.search(r'本体のみ|本体なし|本体別売|別売|交換|オプション|replacement|optional', merchant_body, re.I))
                        parsed.firepit_purchase_binding = {
                            'manufacturerModel': model,
                            'manufacturerSources': [primary['sourceUrl'] for primary in firepit_sources.values()],
                            'merchantModelAlias': '398' if pid == 'fp-001' else model,
                            'bundleVerified': bundle_verified,
                            'conditions': (['Manufacturer0398.SP includes two skewers; this merchant bundle count is unconfirmed.']
                                           if not bundle_verified else [])}
                        match = match and bundle_verified
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
                        source_binding(res, parsed, key, value)
                        for res, parsed in maker_pages) for key, value in specs.items())
                    and any(image_url in source_images(res, parsed)
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
                              for binding in [source_binding(res, parsed, key, value)] if binding), None)
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
                                    if image_url in source_images(res, parsed)), None)
            try:
                res = self.request(image_url)
                actual_type = _image_type(res['body'])
                declared_type = res['headers'].get('content-type', '').split(';')[0].lower()
                verified = bool(identity_source and actual_type and actual_type == declared_type and len(res['body']) >= 32)
                image = {'productId': pid, 'url': image_url, 'imageURL': image_url, 'finalUrl': res['url'],
                         'sha256': hashlib.sha256(res['body']).hexdigest(), 'size': len(res['body']),
                         'contentType': declared_type, 'identitySource': identity_source,
                         'checkedAt': checked_at, 'verified': verified}
                if res['headers'].get('x-catalog-original-content-type') == 'image':
                    image['declaredContentType'] = 'image'
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
                    if getattr(parsed, 'firepit_purchase_binding', None):
                        item['destinations'][-1]['identityBinding'] = parsed.firepit_purchase_binding
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
