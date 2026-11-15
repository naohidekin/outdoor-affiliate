"""Lossless, request-scoped projection for repeated long JSON values."""
import copy
import hashlib
import json


MIN_VALUE_BYTES = 256
ENVELOPE_KEY = '$modelInputProjection'


def _serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _wire_bytes(value):
    # Model input is embedded as a JSON string in messages[].content.
    return len(json.dumps(_serialized(value), ensure_ascii=False, allow_nan=False).encode('utf-8'))


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _candidate(value):
    if not isinstance(value, (dict, list, str)):
        return None
    encoded = _canonical(value)
    if len(encoded.encode('utf-8')) < MIN_VALUE_BYTES:
        return None
    return type(value).__name__ + ':' + encoded


def _reference_key(value):
    used = set()
    def visit(item):
        if isinstance(item, dict):
            used.update(item)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    key = '$modelInputRef'
    while key in used:
        key += '_'
    return key


def _projection_checksum(reference_key, instruction, definitions, data):
    bound = {'referenceKey': reference_key, 'instruction': instruction,
             'definitions': definitions, 'data': data}
    return hashlib.sha256(_canonical(bound).encode('utf-8')).hexdigest()


def _projection_parts(value):
    if not isinstance(value, dict) or set(value) != {ENVELOPE_KEY, 'definitions', 'data'}:
        return None
    metadata, definitions = value.get(ENVELOPE_KEY), value.get('definitions')
    if (not isinstance(metadata, dict)
            or set(metadata) != {'version', 'referenceKey', 'instruction', 'checksum'}
            or metadata.get('version') != 1 or not isinstance(metadata.get('referenceKey'), str)
            or not isinstance(metadata.get('instruction'), str) or not isinstance(metadata.get('checksum'), str)
            or not isinstance(definitions, dict)):
        return None
    expected = _projection_checksum(metadata['referenceKey'], metadata['instruction'], definitions, value['data'])
    return (metadata, definitions) if metadata['checksum'] == expected else None


def project_model_input(data):
    """Deduplicate only repeated long JSON structures when the full envelope is shorter."""
    try:
        original = _serialized(data)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError('JSON model input required') from None
    counts = {}
    valid_keys = True
    def count(item):
        nonlocal valid_keys
        key = _candidate(item)
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
        if isinstance(item, dict):
            if any(not isinstance(name, str) for name in item):
                valid_keys = False
            for child in item.values():
                count(child)
        elif isinstance(item, list):
            for child in item:
                count(child)
    try:
        count(data)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return copy.deepcopy(data)
    selected = {key for key, total in counts.items() if total > 1}
    if not selected or not valid_keys:
        return copy.deepcopy(data)
    reference_key = _reference_key(data)
    ids, definitions = {}, {}
    def replace(item):
        key = _candidate(item)
        if key in selected:
            if key not in ids:
                name = 'r' + str(len(ids) + 1)
                ids[key] = name
                definitions[name] = copy.deepcopy(item)
            return {reference_key: ids[key]}
        if isinstance(item, dict):
            return {name: replace(child) for name, child in item.items()}
        if isinstance(item, list):
            return [replace(child) for child in item]
        return copy.deepcopy(item)
    projected = replace(data)
    instruction = ("Lossless request-scoped references: replace each object containing only '" +
                   reference_key + "' with the exact JSON value at definitions[its id] before reasoning. "
                   "Preserve every fact, number, URL and qualifier; references are not summaries.")
    checksum = _projection_checksum(reference_key, instruction, definitions, projected)
    envelope = {
        ENVELOPE_KEY: {'version': 1, 'referenceKey': reference_key,
                       'instruction': instruction, 'checksum': checksum},
        'definitions': definitions, 'data': projected,
    }
    return envelope if _wire_bytes(envelope) < _wire_bytes(data) else copy.deepcopy(data)


def model_input_sizes(data):
    """Return exact UTF-8 serialized sizes for offline projection measurement."""
    projected = project_model_input(data)
    used = _projection_parts(projected) is not None
    return {'plainBytes': _wire_bytes(data), 'projectedBytes': _wire_bytes(projected),
            'projected': used}


def restore_model_input(value):
    """Decode a projected value exactly; ordinary JSON values are copied unchanged."""
    parts = _projection_parts(value)
    if parts is None:
        return copy.deepcopy(value)
    metadata, definitions = parts
    reference_key = metadata['referenceKey']
    def restore(item):
        if isinstance(item, dict) and set(item) == {reference_key}:
            name = item[reference_key]
            if not isinstance(name, str) or name not in definitions:
                raise ValueError('unknown model input reference')
            return copy.deepcopy(definitions[name])
        if isinstance(item, dict):
            return {name: restore(child) for name, child in item.items()}
        if isinstance(item, list):
            return [restore(child) for child in item]
        return copy.deepcopy(item)
    return restore(value['data'])
