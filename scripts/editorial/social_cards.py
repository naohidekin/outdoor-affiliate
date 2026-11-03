"""Deterministic, revision-bound article social cards. No model or image synthesis."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from catalog import Catalog, _image_type, safe_url


BUCKET = 'editorial-social-cards'
TEMPLATE_VERSION = 'lake-sky-social-card-v1'
MAX_CARD_BYTES = 2 * 1024 * 1024


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _heading(title):
    parts = title.split('｜')
    return parts[1] if len(parts) == 2 and all(part.strip() for part in parts) else title


class SocialCards:
    def __init__(self, config, env, catalog=None, renderer=None, storage=None):
        self.config, self.env = dict(config), dict(env)
        self.catalog = catalog or Catalog(env)
        self.renderer = renderer or self._render
        self.storage = storage or self._store

    def _node(self, script, payload, *, setup=False):
        child_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR') if key in os.environ}
        if script == 'social-card-storage.mjs':
            child_env.update({key: self.env[key] for key in ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY') if key in self.env})
        child_env['TZ'] = 'Asia/Tokyo'
        cmd = [self.config.get('node', 'node'), str(Path(__file__).with_name(script))]
        if setup:
            cmd.append('--setup')
        try:
            result = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                                    text=True, env=child_env, timeout=120)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('social_card_transport_failed') from None
        limit = 32768 if script == 'render-social-card.mjs' else 8192
        _require(result.returncode == 0 and len(result.stdout) <= limit, 'social_card_transport_failed')
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise ValueError('social_card_transport_failed') from None
        _require(isinstance(value, dict), 'social_card_transport_failed')
        return value

    def _render(self, spec, output_path):
        payload = {**spec, 'outputPath': str(output_path)}
        value = self._node('render-social-card.mjs', payload)
        _require(value.get('passed') is True and value.get('version') == TEMPLATE_VERSION,
                 'social_card_render_failed')
        data = output_path.read_bytes()
        _require(value.get('pngSha256') == hashlib.sha256(data).hexdigest() and
                 [s.get('sha256') for s in value.get('sources', [])] ==
                 [p['sha256'] for p in spec['products']], 'social_card_render_evidence_invalid')
        shown = value.get('displayText') or {}
        renderer = value.get('renderer') or {}
        _require(shown.get('title') == spec['title'] and shown.get('heading') == spec['heading'] and
                 shown.get('productNames') == [p['name'] for p in spec['products']] and
                 value.get('networkRequests') == 0 and isinstance(value.get('layout'), dict) and
                 re.fullmatch(r'[a-f0-9]{64}', str(value.get('contentHash', ''))) and
                 isinstance(renderer.get('engine'), str) and renderer['engine'] and
                 isinstance(renderer.get('fontFamily'), str) and renderer['fontFamily'],
                 'social_card_render_evidence_invalid')
        crop = [{'productId': spec['products'][i]['productId'], 'sha256': source['sha256'],
                 'originalWidth': source.get('originalWidth'), 'originalHeight': source.get('originalHeight'),
                 'crop': source.get('crop'), 'displaySha256': source.get('displaySha256')}
                for i, source in enumerate(value['sources'])]
        evidence = {'contentHash': value['contentHash'], 'displayText': shown,
                    'layout': value['layout'], 'sourceCrops': crop,
                    'renderEngine': renderer['engine'], 'fontFamily': renderer['fontFamily']}
        _require(len(json.dumps(evidence, ensure_ascii=False)) <= 16000, 'social_card_render_evidence_invalid')
        return {'bytes': data, 'evidence': evidence}

    def _store(self, data, path):
        return self._node('social-card-storage.mjs', {'path': path, 'dataBase64': base64.b64encode(data).decode('ascii')})

    def build(self, bundle):
        _require(isinstance(bundle, dict) and isinstance(bundle.get('article'), dict)
                 and isinstance(bundle.get('products'), list) and isinstance(bundle.get('images'), list), 'social_card_bundle_invalid')
        article = bundle['article']
        _require(isinstance(article.get('title'), str) and article['title'].strip()
                 and isinstance(article.get('productIds'), list) and article['productIds'], 'social_card_article_invalid')
        _require(not (article.get('generationMeta') or {}).get('socialCard'), 'social_card_already_bound')
        products = {p.get('id'): p for p in bundle['products'] if isinstance(p, dict)}
        _require(len(products) == len(bundle['products']) == len(article['productIds'])
                 and set(products) == set(article['productIds']), 'social_card_products_invalid')
        sources = []
        for product_id in article['productIds'][:2]:
            product = products[product_id]
            matches = [i for i in bundle['images'] if isinstance(i, dict) and i.get('productId') == product_id
                       and i.get('url') == product.get('imageUrl') and i.get('verified') is True]
            _require(len(matches) == 1, 'social_card_source_missing_or_ambiguous')
            proof = matches[0]
            _require(re.fullmatch(r'[a-f0-9]{64}', str(proof.get('sha256', '')))
                     and type(proof.get('size')) is int and 0 < proof['size'] <= 8 * 1024 * 1024,
                     'social_card_source_proof_invalid')
            try:
                response = self.catalog.request(proof['url'], {'Accept': 'image/*', 'Cache-Control': 'no-cache'})
                data = response['body']
                content_type = response['headers'].get('content-type', '').split(';')[0].lower()
                _require(_image_type(data) == content_type and content_type in ('image/png', 'image/jpeg', 'image/webp')
                         and hashlib.sha256(data).hexdigest() == proof['sha256'] and len(data) == proof['size']
                         and (proof.get('contentType') is None or proof['contentType'] == content_type),
                         'social_card_source_mismatch')
            except Exception:
                raise ValueError('social_card_source_mismatch') from None
            _require(isinstance(product.get('name'), str) and product['name'].strip(), 'social_card_product_name_invalid')
            sources.append({'productId': product_id, 'name': product['name'], 'sha256': proof['sha256'],
                            'dataUrl': 'data:' + content_type + ';base64,' + base64.b64encode(data).decode('ascii')})
        _require(1 <= len(sources) <= 2, 'social_card_source_count_invalid')
        spec = {'title': article['title'], 'heading': _heading(article['title']),
                'products': [{'productId': s['productId'], 'name': s['name'], 'sha256': s['sha256'],
                              'dataUrl': s['dataUrl'], 'verified': True}
                             for s in sources]}
        with tempfile.TemporaryDirectory(prefix='camp-social-card-') as directory:
            output = Path(directory) / 'card.png'
            try:
                rendered = self.renderer(spec, output)
            except Exception:
                raise ValueError('social_card_render_failed') from None
        _require(isinstance(rendered, dict) and isinstance(rendered.get('evidence'), dict),
                 'social_card_render_evidence_invalid')
        card = rendered.get('bytes')
        _require(isinstance(card, bytes) and 0 < len(card) <= MAX_CARD_BYTES and _image_type(card) == 'image/png'
                 and len(card) >= 24 and struct.unpack('>II', card[16:24]) == (1200, 630),
                 'social_card_png_invalid')
        digest = hashlib.sha256(card).hexdigest()
        path = digest[:2] + '/' + digest + '.png'
        _require(bool(self.env.get('SUPABASE_URL')) and bool(self.env.get('SUPABASE_SERVICE_ROLE_KEY')),
                 'social_card_storage_unconfigured')
        base = self.env['SUPABASE_URL'].rstrip('/')
        parsed, _ = safe_url(base, resolve=False)
        _require(parsed.path in ('', '/') and not parsed.query and not parsed.fragment,
                 'social_card_storage_unconfigured')
        try:
            stored = self.storage(card, path)
            _require(isinstance(stored, dict) and stored.get('verified') is True and stored.get('path') == path
                     and stored.get('sha256') == digest and stored.get('size') == len(card),
                     'social_card_upload_unverified')
            url = stored.get('url')
            _require(url == base + '/storage/v1/object/public/' + BUCKET + '/' + path,
                     'social_card_storage_url_invalid')
            public = self.catalog.request(url, {'Accept': 'image/png', 'Cache-Control': 'no-cache'})
            _require(public['headers'].get('content-type', '').split(';')[0].lower() == 'image/png'
                     and public['body'] == card, 'social_card_public_readback_mismatch')
        except Exception:
            raise ValueError('social_card_storage_unverified') from None
        manifest = {'url': url, 'finalUrl': url, 'sha256': digest, 'size': len(card),
                    'contentType': 'image/png', 'width': 1200, 'height': 630,
                    'sources': [{'productId': s['productId'], 'sha256': s['sha256']} for s in sources],
                    'templateVersion': TEMPLATE_VERSION, 'rendererEvidence': rendered['evidence']}
        result = copy.deepcopy(bundle)
        result['article'].setdefault('generationMeta', {})['socialCard'] = manifest
        result['images'].append({'role': 'social-card', 'verified': True, **manifest})
        return result
