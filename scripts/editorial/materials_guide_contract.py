"""Offline, owner-scoped authority for one down/synthetic materials guide.

The runtime rejects model-supplied contracts and builds this from its ledger job
and verified gather. Retained metadata is bound into the reviewed bundle; it is
not a publication approval or a substitute for any existing source checks.
"""
import hashlib
import json
import re

from apparel_identity import (_ExcerptText, apparel_contract, binding_matches_product)

ARTICLE_ID = 'article-74c3128fef81fe81ff3f5658'
FIELD = 'materialsGuideComparisonContract'
REQUIRED_STATEMENT = ('これは今回の2製品の記載に基づく整理で、ダウンと化繊中綿全般の暖かさや'
                      '停滞時の適性を順位付けするものではありません。')
_JOB = {'id': ARTICLE_ID, 'kind': 'supplemental_article', 'batchId': 'apparel-2026-11-22',
        'batchSlot': 3, 'batchCallCap': 96}
_IDS = ['apparel-montbell-1101493', 'apparel-montbell-1101539']
_ENTITY = ('id', 'slug', 'title', 'categoryId', 'productIds')
_CHECKS = {'facts': True, 'images': True, 'affiliate': True}
_KIND = 'owner_materials_guide_v1'
_OBSERVED_CLAIMS = (
    ('material_generalization', re.compile(
        r'止まっている時間が長い(?:なら|・持ち運び重視なら)ダウン'
        r'|登り下りで汗をか(?:くなら|き(?:ながら)?着たまま(?:でいたい|動く)?なら)'
        r'|休憩や停滞が長くて|休憩時間が長い行程')),
    ('denier_thickness', re.compile(r'脇・肩・腕を少し厚めにしている')),
    ('average_basis', re.compile(
        r'特定のサイズ・個体の実測ではなく平均値|いずれも平均値・目安'
        r'|サイズによって前後する可能性|収納サイズも、きれいに畳んだ場合の目安'
        r'|実際のパッキングでは多少前後するもの')),
    ('emergency_recommendation', re.compile(r'非常用に持つ運用なら')),
    ('insurance_recommendation', re.compile(r'「保険」として持つなら')),
)


class _GuideText(_ExcerptText):
    """Disclosure evidence never comes from a collapsible details container."""
    def handle_starttag(self, tag, attrs):
        if tag == 'details':
            attrs = list(attrs) + [('hidden', '')]
        super().handle_starttag(tag, attrs)


def _reject_observed_claims(article, brief):
    fields = [('content', article.get('content')), ('brief.conclusion', brief.get('conclusion'))]
    faqs = article.get('faqs')
    if isinstance(faqs, list):
        fields.extend((f'faqs[{i}].answer', item.get('answer'))
                      for i, item in enumerate(faqs) if isinstance(item, dict))
    for field, text in fields:
        if not isinstance(text, str):
            continue
        text = re.sub(r'\s+', '', text)
        for code, pattern in _OBSERVED_CLAIMS:
            _require(not pattern.search(text), f'unsupported materials guide claim: {field}:{code}')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _source_projection(products):
    projection = []
    for product in products:
        item = {key: product.get(key) for key in
                ('id', 'name', 'brand', 'categoryId', 'specs', 'imageUrl', 'affiliateUrl', 'amazonUrl')}
        item['apparelContract'] = apparel_contract(product)
        projection.append(item)
    return projection


def _guide(bundle):
    article, brief = bundle.get('article'), bundle.get('brief')
    products, refs = bundle.get('products'), bundle.get('references')
    _require(isinstance(article, dict) and article.get('id') == ARTICLE_ID
             and article.get('productIds') == _IDS and article.get('categoryId') == 'wear'
             and all(isinstance(article.get(k), str) and article[k].strip()
                     for k in ('slug', 'title')),
             'exact materials guide article required')
    _require(isinstance(brief, dict) and brief.get('format') == 'guide'
             and article.get('genre', 'guide') == 'guide', 'materials guide format required')
    _reject_observed_claims(article, brief)
    content = article.get('content')
    _require(isinstance(content, str) and not re.search(r'\{\{\s*ranking\b', content, re.I)
             and not re.search(r'ランキング|[0-9０-９]+\s*位|おすすめ[0-9０-９]+選', article['title']),
             'materials guide cannot use ranking format')
    # Require the supplied disclosure as a visible paragraph, never code,
    # comments, hidden HTML, alt text, metadata or a reference excerpt.
    visible = re.sub(r'(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}\1[ \t]*(?:\n|$)|\Z)', '', content)
    visible = re.sub(r'(?m)^(?: {4}|\t).*$', '', visible)
    visible = re.sub(r'(`+).*?\1', '', visible, flags=re.S)
    page = _GuideText()
    page.feed(visible)
    _require(REQUIRED_STATEMENT in [line.strip() for line in ''.join(page.parts).splitlines()],
             'visible materials guide statement required')
    _require(isinstance(products, list) and len(products) == 2
             and [p.get('id') for p in products if isinstance(p, dict)] == _IDS,
             'exact materials guide products required')
    _require(isinstance(refs, list) and all(isinstance(r, dict) for r in refs),
             'materials guide references required')
    for product, model, kind in zip(products, ('1101493', '1101539'), ('down', 'active-layer')):
        contract = apparel_contract(product)
        _require(contract['model'] == model and contract['class'] == kind
                 and contract['gender'] == "Men's" and product.get('brand') == 'mont-bell',
                 'materials guide classification must remain unchanged')
        for source, channel in (('manufacturer', None), ('purchase', 'amazon'), ('purchase', 'rakuten')):
            matching = [r for r in refs if r.get('productId') == product['id']
                        and r.get('kind') == source and (channel is None or r.get('channel') == channel)
                        and binding_matches_product(r.get('apparelBinding'), product, channel)]
            _require(len(matching) == 1, 'exact manufacturer and both merchant bindings required')
    return article, products, refs


def build_materials_guide_contract(job, gathered, bundle):
    """Return metadata only, from a trusted current job + fresh verified gather.

    Oneoff callers may attach the returned value at FIELD before polish; the
    runtime recomputes it at the final deterministic gate. No body is rewritten.
    """
    _require(isinstance(job, dict) and all(job.get(k) == v for k, v in _JOB.items()),
             'owner materials guide job required')
    article, products, refs = _guide(bundle)
    theme = job.get('theme') or {}
    _require(all(article.get(k) == theme.get(k) for k in ('slug', 'title', 'categoryId', 'productIds')),
             'materials guide job entity mismatch')
    _require(isinstance(gathered, dict) and gathered.get('products') == products
             and gathered.get('references') == refs and isinstance(gathered.get('checks'), dict)
             and all(gathered['checks'].get(k) is True for k in _CHECKS),
             'current verified materials guide gather required')
    details = (gathered.get('evidence') or {}).get('products')
    _require(isinstance(details, list) and len(details) == 2
             and [d.get('productId') for d in details if isinstance(d, dict)] == _IDS
             and all(all(d.get(k) is True for k in _CHECKS) for d in details),
             'materials guide per-product gather checks required')
    source = _hash(_source_projection(products))
    _require(job.get('sourceBinding') == source, 'current materials guide source binding mismatch')
    return {'kind': _KIND, 'ownerGrant': '20261122-slot3-materials-guide',
            'job': dict(_JOB), 'articleEntity': {k: article[k] for k in _ENTITY},
            'sourceBinding': source, 'productsSha256': _hash(products),
            'referencesSha256': _hash(refs), 'gatherChecks': dict(_CHECKS)}


def validate_materials_guide_contract(bundle):
    """Validate retained authority and current evidence before the narrow exception."""
    article, products, refs = _guide(bundle)
    proof = bundle.get(FIELD)
    expected = {'kind': _KIND, 'ownerGrant': '20261122-slot3-materials-guide',
                'job': dict(_JOB), 'articleEntity': {k: article[k] for k in _ENTITY},
                'sourceBinding': _hash(_source_projection(products)),
                'productsSha256': _hash(products), 'referencesSha256': _hash(refs),
                'gatherChecks': dict(_CHECKS)}
    _require(isinstance(proof, dict) and proof == expected, 'materials guide authority binding invalid')
    return True


def bind_materials_guide_contract(job, gathered, bundle):
    """Runtime-only attach/revalidate; every other job keeps the original gate."""
    if job.get('id') != ARTICLE_ID:
        _require(FIELD not in bundle, 'materials guide contract on unauthorized job')
        return None
    proof = build_materials_guide_contract(job, gathered, bundle)
    _require(FIELD not in bundle or bundle[FIELD] == proof, 'model or stale materials guide contract')
    bundle[FIELD] = proof
    return proof
