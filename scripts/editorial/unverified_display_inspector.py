"""Pure diagnostic for raw catalog values that may leak through display cards.

No network, file IO, model calls, mutation, approval or production hook. An empty
list means only 'no matching positive value explicitly marked unverified'; it is
NOT a verified-price verdict. Missing evidence never becomes verified evidence.
Malformed input raises ValueError rather than masquerading as a clean result.
"""
import math


def inspect_unverified_display(products, evidence):
    """Accept raw products and gather['evidence']; return IDs/field/reason only."""
    if not isinstance(products, list) or not isinstance(evidence, dict) or not isinstance(evidence.get('products'), list):
        raise ValueError('display diagnostic input invalid')
    ids = []
    for product in products:
        if not isinstance(product, dict) or not isinstance(product.get('id'), str) or not product['id'].strip():
            raise ValueError('display diagnostic product identity invalid')
        ids.append(product['id'])
    if len(ids) != len(set(ids)):
        raise ValueError('display diagnostic duplicate product identity')
    unverified = {}
    for item in evidence['products']:
        if (not isinstance(item, dict) or not isinstance(item.get('productId'), str)
                or not item['productId'].strip() or not isinstance(item.get('unverifiedFields'), list)
                or any(not isinstance(field, str) for field in item['unverifiedFields'])):
            raise ValueError('display diagnostic evidence invalid')
        unverified.setdefault(item['productId'], set()).update(item['unverifiedFields'])
    result = []
    for product in products:
        for field in ('price', 'rating'):
            value = product.get(field)
            if (field in unverified.get(product['id'], ()) and type(value) in (int, float)
                    and (type(value) is int or math.isfinite(value)) and value > 0):
                result.append({'productId': product['id'], 'field': field,
                               'reason': 'unverified_display_value'})
    return result
