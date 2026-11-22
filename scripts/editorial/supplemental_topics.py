"""Pure, fail-closed resolver for the bounded supplemental apparel batch."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import unicodedata

from apparel_identity import ApparelIdentityError, apparel_contract


JST = timezone(timedelta(hours=9))
MANIFEST = Path(__file__).with_name('supplemental-apparel-20261116.json')
ROOT_FIELDS = {'schemaVersion', 'batchId', 'kind', 'notBefore', 'socialEligiblePeriod',
               'maxArticles', 'batchCallCap', 'status', 'apparelPolicy', 'slots'}
SLOT_FIELDS = {'slot', 'productIds', 'slug', 'title', 'categoryId', 'query', 'selectionReason'}
THEME_FIELDS = ('slug', 'title', 'categoryId', 'query', 'selectionReason')
_APPROVED_BATCH_BINDINGS = {
    'winter-depth-2026-11-22': {'batchId': 'winter-depth-2026-11-22', 'maxArticles': 3,
                              'batchCallCap': 96, 'socialEligiblePeriod': '2026-11-20'},
    'apparel-2026-11-16': {'batchId': 'apparel-2026-11-16', 'maxArticles': 3,
                           'batchCallCap': 96,
                           'socialEligiblePeriod': '2026-11-20'},
    'apparel-2026-11-22': {'batchId': 'apparel-2026-11-22', 'maxArticles': 3,
                           'batchCallCap': 96,
                           'socialEligiblePeriod': '2026-11-20'},
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def approved_batch_binding(batch_id):
    """Return a copy of one explicitly owner-approved supplemental batch binding."""
    if not isinstance(batch_id, str):
        raise ValueError('invalid supplemental bounds')
    binding = _APPROVED_BATCH_BINDINGS.get(batch_id)
    if binding is None:
        raise ValueError('invalid supplemental bounds')
    return json.loads(_canonical(binding))


def _theme_key(value):
    return (' '.join(unicodedata.normalize('NFKC', value).split()).casefold()
            if isinstance(value, str) and value.strip() else None)


def _aware(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('aware supplemental time required')
    return parsed.astimezone(JST)


def validate_batch(value):
    if not isinstance(value, dict) or set(value) != ROOT_FIELDS:
        raise ValueError('invalid supplemental manifest')
    binding = approved_batch_binding(value.get('batchId'))
    if (value.get('schemaVersion') != 1 or value.get('kind') != 'supplemental_article_batch'
            or value.get('maxArticles') != binding['maxArticles']
            or value.get('batchCallCap') != binding['batchCallCap']
            or value.get('socialEligiblePeriod') != binding['socialEligiblePeriod']):
        raise ValueError('invalid supplemental bounds')
    _aware(value.get('notBefore'))
    policy = value.get('apparelPolicy')
    if (not isinstance(policy, dict) or set(policy) !=
            {'version', 'requirements', 'missingEvidence', 'researchScope'}
            or policy.get('version') != 1
            or policy.get('missingEvidence') != 'hold'
            or not isinstance(policy.get('requirements'), list)
            or not all(isinstance(item, str) and item for item in policy['requirements'])):
        raise ValueError('invalid apparel policy')
    scope = policy.get('researchScope')
    if (not isinstance(scope, dict) or set(scope) != {'classes', 'comparison', 'claims'}
            or not all(isinstance(item, str) and item for item in scope.get('classes', []))
            or not all(isinstance(item, str) and item for item in scope.get('comparison', []))
            or not isinstance(scope.get('claims'), str) or not scope['claims']):
        raise ValueError('invalid apparel research scope')
    slots = value.get('slots')
    if not isinstance(slots, list) or len(slots) != 3:
        raise ValueError('exactly three supplemental slots required')
    for number, slot in enumerate(slots, 1):
        if (not isinstance(slot, dict) or set(slot) != SLOT_FIELDS or slot.get('slot') != number
                or not isinstance(slot.get('productIds'), list) or not slot['productIds']
                or len(slot['productIds']) != len(set(slot['productIds']))
                or not all(isinstance(item, str) and item
                           for item in slot['productIds'])):
            raise ValueError('invalid supplemental slot')
        for field in THEME_FIELDS:
            if slot[field] is not None and (not isinstance(slot[field], str) or not slot[field].strip()):
                raise ValueError('invalid supplemental theme')
    return json.loads(_canonical(value))


def load_batch(path=None):
    target = Path(path) if path else MANIFEST
    if not target.is_absolute():
        raise ValueError('supplemental manifest path must be absolute')
    return validate_batch(json.loads(target.read_text()))


def apparel_policy(manifest):
    value = validate_batch(manifest)
    policy = value['apparelPolicy']
    return {'batchId': value['batchId'], 'policy': policy,
            'fingerprint': _hash(policy)}


def batch_fingerprint(manifest):
    return _hash(validate_batch(manifest))


def resolve_batch(manifest, catalog, queued_themes, now):
    value = validate_batch(manifest)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware now required')
    if now.astimezone(JST) < _aware(value['notBefore']):
        return {'status': 'not_due', 'batchId': value['batchId'],
                'manifestFingerprint': _hash(value), 'slots': []}
    if not isinstance(catalog, dict) or not isinstance(catalog.get('products'), list):
        raise ValueError('live catalog required')
    products = catalog['products']
    existing = list(catalog.get('articles') or []) + list(queued_themes or [])
    used = {field: {_theme_key(item.get(field)) for item in existing
                    if isinstance(item, dict) and _theme_key(item.get(field))}
            for field in ('slug', 'title', 'query')}
    results = []
    for slot in value['slots']:
        reason = None
        if not all(isinstance(slot[field], str) and slot[field].strip() for field in THEME_FIELDS):
            reason = 'theme_not_registered'
        elif any(_theme_key(slot[field]) in used[field]
                 for field in ('slug', 'title', 'query')):
            reason = 'duplicate_theme'
        for field in ('slug', 'title', 'query'):
            key = _theme_key(slot[field])
            if key:
                used[field].add(key)
        matched = []
        if reason is None:
            for product_id in slot['productIds']:
                found = [product for product in products
                         if isinstance(product, dict) and product.get('id') == product_id]
                if len(found) != 1:
                    reason = 'catalog_product_not_verified'
                    break
                matched.append(found[0])
        contracts = []
        if reason is None:
            try:
                contracts = [apparel_contract(product) for product in matched]
            except ApparelIdentityError:
                reason = 'apparel_identity_invalid'
        if reason is None and any(not product.get(field) for product in matched
                                  for field in ('imageUrl', 'affiliateUrl', 'amazonUrl')):
            reason = 'missing_required_destination'
        if reason is None and any(product.get('categoryId') != slot['categoryId'] for product in matched):
            reason = 'category_mismatch'
        if reason:
            results.append({'slot': slot['slot'], 'status': 'source_hold', 'reason': reason})
            continue
        source = [{key: product.get(key) for key in
                   ('id', 'name', 'brand', 'categoryId', 'specs', 'imageUrl',
                    'affiliateUrl', 'amazonUrl')} for product in matched]
        for item, contract in zip(source, contracts):
            item['apparelContract'] = contract
        theme = {field: slot[field] for field in THEME_FIELDS}
        theme['productIds'] = list(slot['productIds'])
        results.append({'slot': slot['slot'], 'status': 'ready', 'theme': theme,
                        'sourceBinding': _hash(source)})
    ready = sum(item['status'] == 'ready' for item in results)
    status = 'ready' if ready == 3 else 'partial' if ready else 'source_hold'
    projection = [{'slot': item['slot'], 'status': item['status'],
                   'reason': item.get('reason'), 'sourceBinding': item.get('sourceBinding')}
                  for item in results]
    return {'status': status, 'batchId': value['batchId'], 'slots': results,
            'manifestFingerprint': _hash(value), 'stateFingerprint': _hash(projection),
            'readyCount': ready}
