"""Emit the canonical Python-owned nonproduct bundle fixture for JS tests."""
import base64
from datetime import datetime
import hashlib
import json
import struct
import zlib

from topic_selection import JST, editorial_context, nonproduct_affiliate_review


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _png(width=1200, height=630):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    raw = (b'\x00' + b'\x3a\x70\x8f' * width) * height
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def fixture():
    checked = datetime(2026, 11, 20, 10, tzinfo=JST).isoformat()
    url = 'https://www.coleman.co.jp/customersupport/faq/'
    excerpt = '十分に乾燥させてから保管します。'
    receipt = {'id': 'coleman-care', 'url': url, 'canonicalUrl': url, 'checkedAt': checked,
               'httpStatus': 200, 'excerpt': excerpt, 'claimScope': 'tent-care'}
    reference = {**receipt, 'id': 'public:coleman-care', 'title': 'coleman-care',
                 'kind': 'public-primary', 'scope': 'tent-care',
                 'receiptSha256': hashlib.sha256(_canonical(receipt).encode()).hexdigest(),
                 'excerptSha256': hashlib.sha256(excerpt.encode()).hexdigest()}
    source_receipt = hashlib.sha256(_canonical([reference['receiptSha256']]).encode()).hexdigest()
    data = _png()
    digest = hashlib.sha256(data).hexdigest()
    steps = [{'kind': 'editorial_outline', 'text': text}
             for text in ('準備する', '乾燥を確認する', '保管する')]
    display = {'title': 'テントの乾かし方', 'heading': 'テントの乾かし方', 'steps': steps,
               'badge': 'キャンプのヒント', 'disclaimer': 'Camp Gear Lab編集部の図解'}
    renderer = {'passed': True, 'evidencePassed': True,
                'version': 'editorial-illustration-v1', 'width': 1200, 'height': 630,
                'pngSha256': digest, 'bytes': len(data), 'contentHash': 'c' * 64,
                'displayText': display, 'layout': {'width': 1200, 'height': 630},
                'renderer': {'engine': 'fixture', 'platform': 'offline', 'fontFamily': 'sans-serif'},
                'networkRequests': 0, 'sourceIds': [reference['id']],
                'sourceReceiptSha256': source_receipt}
    image = {'id': 'illustration:' + digest[:20], 'role': 'eyecatch',
             'ownership': 'owned_editorial_illustration', 'depictsRealProduct': False,
             'referenceIds': [reference['id']], 'compositionSha256': renderer['contentHash'],
             'url': 'https://fixture.example/editorial.png',
             'finalUrl': 'https://fixture.example/editorial.png', 'sha256': digest,
             'size': len(data), 'contentType': 'image/png', 'width': 1200, 'height': 630,
             'verified': True, 'checkedAt': checked, 'rendererEvidence': renderer}
    theme = {'nonProductContract': {'references': [reference], 'images': [image],
             'sourceReceiptSha256': source_receipt,
             'allowedClaimScopes': ['tent-care']}}
    context = editorial_context(theme, [image])
    bundle = {'article': {'id': 'editorial-nonproduct-fixture', 'slug': 'tent-dry-fixture', 'status': 'draft',
              'title': display['title'], 'content': '## 手順\n図解です。', 'excerpt': 'fixture',
              'metaDescription': 'fixture', 'faqs': [], 'categoryId': 'tent',
              'author': 'ギア男', 'productIds': [], 'eyecatch': image['url'],
              'createdAt': checked, 'updatedAt': checked, 'publishedAt': None,
              'generationMeta': {'editorialContext': context}},
              'products': [], 'references': [reference], 'images': [image],
              'commercialRoute': {'status': 'not_applicable',
                                  'reason': 'verified_nonproduct_article',
                                  'verifiedBy': 'deterministic_contract_v1'}}
    expected_readback = {'productIds': [], 'editorialContext': context,
        'commercialRoute': {'status': 'not_applicable', 'measured': False,
                            'sponsoredCtaCount': 0, 'reason': 'verified_nonproduct_article',
                            'verifiedBy': 'deterministic_contract_v1'},
        'imageProofs': [{key: image[key] for key in ('id', 'url', 'sha256', 'size', 'contentType')}]}
    return {'schemaVersion': 1, 'bundle': bundle, 'imageDataBase64': base64.b64encode(data).decode(),
            'reviewAffiliateEvidence': nonproduct_affiliate_review(bundle),
            'expectedPublicationReadback': expected_readback,
            'expectedPreview': {'clicksVerified': {'desktop': [], 'mobile': []},
                                'sponsoredCtaCount': {'desktop': 0, 'mobile': 0},
                                'allAnchorsVerified': True}}


if __name__ == '__main__':
    print(_canonical(fixture()))
