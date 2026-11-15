"""Pure attachment of caller-provided purchase NA evidence."""
import copy
from datetime import datetime, timedelta
from urllib.parse import urlsplit


NA_FIELDS = frozenset({'productId', 'channel', 'status', 'reason', 'checkedAt', 'reviewedBy'})
CHANNEL_FIELDS = {'amazon': 'amazonUrl', 'rakuten': 'affiliateUrl'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _aware(value, message):
    _require(isinstance(value, str) and value.strip(), message)
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(message) from None
    _require(stamp.tzinfo is not None and stamp.utcoffset() is not None, message)
    return stamp


def _channel_url(channel, value):
    if not _text(value):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme != 'https' or parsed.username or parsed.password or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if channel == 'amazon':
        return host == 'amazon.co.jp' or host.endswith('.amazon.co.jp')
    return host in {'hb.afl.rakuten.co.jp', 'pt.afl.rakuten.co.jp',
                    'transition.afl.rakuten.co.jp', 'item.rakuten.co.jp', 'm.rakuten.co.jp'}


def validate_purchase_evidence(bundle, evidence, now):
    """Return a copied bundle with fresh, exact, caller-supplied NA evidence attached."""
    _require(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None,
             'aware current time required')
    _require(isinstance(bundle, dict) and 'purchaseEvidence' not in bundle,
             'unmodified bundle required')
    products = bundle.get('products')
    _require(isinstance(products, list) and products and all(isinstance(p, dict) for p in products),
             'bundle products required')
    ids = [product.get('id') for product in products]
    _require(all(_text(product_id) for product_id in ids) and len(ids) == len(set(ids)),
             'unique product IDs required')
    by_id = {product['id']: product for product in products}
    expected = set()
    for product in products:
        for channel, field in CHANNEL_FIELDS.items():
            if product.get(field) in (None, ''):
                other = 'amazon' if channel == 'rakuten' else 'rakuten'
                _require(_channel_url(other, product.get(CHANNEL_FIELDS[other])),
                         'missing channel requires another verified destination')
                expected.add((product['id'], channel))
    _require(expected and isinstance(evidence, list) and evidence
             and all(isinstance(item, dict) for item in evidence),
             'purchase evidence required')
    observed = []
    for item in evidence:
        _require(set(item) == NA_FIELDS and item.get('status') == 'NA',
                 'typed NA evidence fields invalid')
        product_id, channel = item.get('productId'), item.get('channel')
        _require(product_id in by_id and channel in CHANNEL_FIELDS
                 and by_id[product_id].get(CHANNEL_FIELDS[channel]) in (None, ''),
                 'NA evidence does not match a missing channel')
        _require(_text(item.get('reason')) and _text(item.get('reviewedBy')),
                 'NA reason and reviewer required')
        checked = _aware(item.get('checkedAt'), 'NA checkedAt invalid')
        _require(timedelta(0) <= now - checked <= timedelta(hours=6),
                 'NA evidence stale or future')
        observed.append((product_id, channel))
    _require(len(observed) == len(set(observed)) and set(observed) == expected
             and len(observed) == len(expected), 'NA evidence must exactly cover missing channels')
    result = copy.deepcopy(bundle)
    result['purchaseEvidence'] = copy.deepcopy(evidence)
    return result
