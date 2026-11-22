"""Read a bounded, fresh managed-browser capture and run the same maker gate.

No browser launch, refetch, retry, runtime flags or credential access. The caller
must explicitly acquire a fresh public DOM; expired or incomplete evidence holds.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from official_patagonia_apparel import R1_URL, inspect_official_patagonia

JST = timezone(timedelta(hours=9))
MAX_AGE = timedelta(minutes=15)
MAX_BYTES = 3 * 1024 * 1024


class BrowserSourceHold(ValueError):
    pass


def load_r1_capture(product, receipt_path, image_url=None, *, now=None):
    try:
        receipt_path = Path(receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if (receipt.get('schemaVersion') != 1 or receipt.get('model') != '40275'
                or receipt.get('requestedUrl') != R1_URL or receipt.get('finalUrl') != R1_URL
                or receipt.get('transport') != 'managed-chrome-rendered-dom'
                or receipt.get('captureCount') != 1 or receipt.get('domReadPasses') != 2
                or receipt.get('identicalPasses') is not True or receipt.get('readChunkChars') != 80000):
            return None
        stamp = datetime.fromisoformat(receipt['capturedAtJST'])
        current = now if now is not None else datetime.now(JST)
        if stamp.utcoffset() != timedelta(hours=9) or current.tzinfo is None:
            return None
        age = current - stamp
        if not timedelta(0) <= age <= MAX_AGE:
            return None
        source = Path(receipt['path'])
        if (source.name != '40275-browser-dom.html' or source.is_symlink()
                or source.resolve().parent != receipt_path.resolve().parent):
            return None
        with source.open('rb') as stream:
            body = stream.read(MAX_BYTES + 1)
        if (not body or len(body) > MAX_BYTES or len(body) != receipt.get('domBytes')
                or hashlib.sha256(body).hexdigest() != receipt.get('domSHA256')):
            return None
        html = body.decode('utf-8')
        binding = inspect_official_patagonia(product, R1_URL, html, image_url)
        if binding is None:
            return None
        return {'html': html, 'binding': binding, 'provenance': receipt}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def r1_fallback_fetcher(product, receipt_path, upstream):
    """Explicit Catalog fetcher adapter; normal transport once, snapshot once.

    The upstream must be the existing bounded public transport. This adapter
    never runs a renderer. A fresh capture must already have been supplied.
    The renderer's normalized success status is not an origin HTTP assertion.
    """
    def fetch(url, headers, timeout):
        if url != R1_URL:
            return upstream(url, headers, timeout)
        if any(k.casefold() not in ('user-agent', 'accept', 'accept-language', 'cache-control')
               for k in headers):
            raise BrowserSourceHold('Public manufacturer headers required')
        response = None
        try:
            response = upstream(url, headers, timeout)
            body = response.get('body')
            if (response.get('status') == 200 and isinstance(body, bytes) and len(body) <= MAX_BYTES
                    and response.get('url', url) == R1_URL
                    and inspect_official_patagonia(product, R1_URL, body.decode('utf-8'),
                                                   product.get('imageUrl')) is not None):
                return response
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        captured = load_r1_capture(product, receipt_path, product.get('imageUrl'))
        if captured is None:
            raise BrowserSourceHold('Fresh exact R1 renderer evidence required')
        provenance = captured['provenance']
        return {'status': 200, 'headers': {'content-type': 'text/html; charset=utf-8',
                'x-editorial-source-transport': provenance['transport'],
                'x-editorial-source-dom-sha256': provenance['domSHA256'],
                'x-editorial-source-captured-at': provenance['capturedAtJST']},
                'body': captured['html'].encode('utf-8'), 'sourceProvenance': provenance,
                'originHttpStatus': None}
    return fetch
