"""Read-only final audit. Persistence, retry policy and notifications belong to Runtime.

The default transport runs the entire audit in a killable, credential-free process
group (180 seconds). An injected catalogue is a trusted offline-test boundary.
All public GETs use Catalog's pinned DNS and redirect/byte limits.
"""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

def _emit_result(value):
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import Catalog, _affiliate_route, _decode_html, _image_type, _model, _Page, model_matches, safe_url
from audit_requests import AuditRequests

SITE = 'https://camp-gear-lab.com'
LIMIT = 8 * 1024 * 1024


def _result(checks):
    status = 'failed' if any(c['status'] == 'failed' for c in checks) else (
        'unverified' if not checks or any(c['status'] == 'unverified' for c in checks) else 'passed')
    return {'passed': status == 'passed', 'status': status,
            'issues': [c['name'] + ': ' + c['reason'] for c in checks if c['status'] != 'passed'], 'checks': checks}


def _check(name, status, reason):
    return {'name': name, 'status': status, 'reason': reason}


def _child_env():
    return {**{k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR') if k in os.environ},
            'TZ': 'Asia/Tokyo', 'PYTHONDONTWRITEBYTECODE': '1'}


def _audit_model(product):
    model = _model(product)
    if model:
        return model
    # Explicit alphabetic identifiers are valid only when bound to the approved name.
    for key in ('model', 'modelNumber', '型番', '品番', 'モデル番号'):
        value = (product.get('specs') or {}).get(key)
        if isinstance(value, str) and re.fullmatch(r'[A-Z][A-Z_-]{2,39}', value) and model_matches(value, product.get('name', '')):
            return value
    return ''


def _merchant_identity(product, model, title):
    from merchant_identity import inspect_merchant_identity
    return inspect_merchant_identity(product, model, title)['status'] == 'passed'


def _merchant_observation(name, product, model, title, final_url, route_matched):
    """Bounded diagnostic only; query/userinfo never retained, not approval evidence."""
    parts = urlsplit(final_url)
    compact = lambda value: re.sub(r'\s+', '', value).casefold()
    return {'name': name, 'productId': product.get('id'),
            'title': re.sub(r'\s+', ' ', title).strip()[:512],
            'finalPage': (parts.scheme + '://' + (parts.hostname or '') + parts.path)[:2048],
            'routeMatched': route_matched is True,
            'modelFound': model_matches(model, title),
            'brandFound': bool(product.get('brand')) and compact(product['brand']) in compact(title),
            'identityMatched': _merchant_identity(product, model, title)}


def _with_merchant_observations(result, observations):
    # The child reader caps stdout at 65536 bytes. Preserve the legacy verdict
    # even when diagnostics would exceed its budget (JSON defaults to ASCII).
    base_size = len(json.dumps(result).encode('utf-8'))
    budget = min(8192, 60000 - base_size - 128)
    if budget < 2:
        return result
    kept = []
    for observation in observations:
        candidate = kept + [observation]
        if len(json.dumps(candidate).encode('utf-8')) > budget:
            break
        kept = candidate
    return dict(result, merchantObservations=kept,
                merchantObservationsTruncated=len(kept) < len(observations))


class _Source(HTMLParser):
    """Actual main/article markup only: never hydration strings or template data."""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.stack, self.hashes, self.titles, self.meta = [], [], [], {}
        self.title_parts = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        skipped = any(t in ('script', 'style', 'template', 'noscript') for t in self.stack)
        if not skipped:
            if tag == 'article' and 'main' in self.stack:
                self.hashes.append(attrs.get('data-review-content-sha256'))
            if tag == 'h1' and 'main' in self.stack and 'article' in self.stack:
                self.title_parts = []
            if tag == 'meta' and 'head' in self.stack:
                key = attrs.get('property') or attrs.get('name')
                self.meta.setdefault(key, []).append(attrs.get('content'))
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag == 'h1' and self.title_parts is not None:
            self.titles.append(''.join(self.title_parts).strip())
            self.title_parts = None
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[index:]

    def handle_data(self, data):
        if self.title_parts is not None and not any(t in ('script', 'style', 'template', 'noscript') for t in self.stack):
            self.title_parts.append(data)


class PostPublicationAudit:
    def __init__(self, config, env, catalog=None):
        self.config = dict(config)
        # Account identifiers only. Never pass database/API credentials onward.
        self.env = {k: env[k] for k in ('AMAZON_PARTNER_TAG', 'RAKUTEN_AFFILIATE_ID') if k in env}
        self.catalog = catalog

    def check(self, job):
        if self.catalog is not None:
            try:
                return self._audit(job)
            except Exception:
                return _result([_check('audit', 'unverified', 'audit_unavailable')])
            finally:
                if getattr(self, '_request_pool', None) is not None:
                    self._request_pool.close()
                    self._request_pool = None
        payload = {'job': job, 'env': self.env,
                   'config': {k: self.config[k] for k in ('repo', 'node') if k in self.config}}
        # Temporary output caps the data read into memory; no raw stderr escapes.
        with tempfile.TemporaryFile() as output:
            child = None
            try:
                child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve())],
                    stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL,
                    env=_child_env(), start_new_session=True)
                child.communicate(json.dumps(payload).encode(), timeout=180)
                if child.returncode:
                    raise ValueError()
                output.seek(0)
                data = output.read(65537)
                if len(data) > 65536:
                    raise ValueError()
                value = json.loads(data)
                if value.get('status') not in ('passed', 'failed', 'unverified') or not isinstance(value.get('checks'), list):
                    raise ValueError()
                return value
            except Exception:
                # A bounded worker can finish its verdict while outstanding GETs
                # still prevent child exit. Keep its evidence, but never call a
                # terminated/incomplete process successful.
                try:
                    output.seek(0)
                    raw = output.read(65537)
                    value = json.loads(raw) if len(raw) <= 65536 else {}
                    checks = value.get('checks')
                    if not isinstance(checks, list) or not checks or any(
                            not isinstance(c, dict) or c.get('status') not in ('passed', 'failed', 'unverified')
                            or not re.fullmatch(r'[a-z0-9_.-]{1,80}', c.get('name', ''))
                            or not re.fullmatch(r'[a-z0-9_]{1,100}', c.get('reason', '')) for c in checks):
                        raise ValueError()
                    return _with_merchant_observations(_result(checks + [
                        _check('transport', 'unverified', 'audit_process_timeout_or_incomplete')]),
                        value.get('merchantObservations', []))
                except Exception:
                    return _result([_check('audit', 'unverified', 'audit_timeout_or_unavailable')])
            finally:
                if child is not None:
                    # Includes pending browser/image-helper grandchildren.
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait()

    def _browser(self, payload):
        child = subprocess.run([self.config.get('node', 'node'), str(Path(__file__).with_name('post-publication-audit.mjs'))],
            input=json.dumps(payload), capture_output=True, text=True, env=_child_env(), timeout=85)
        if child.returncode or len(child.stdout) > 65536:
            raise ValueError()
        value = json.loads(child.stdout)
        checks = value.get('checks')
        if not isinstance(checks, list) or not checks or len(checks) > 256 or any(
                not isinstance(c, dict) or c.get('status') not in ('passed', 'failed', 'unverified')
                or not re.fullmatch(r'[a-z0-9_.-]{1,80}', c.get('name', ''))
                or not re.fullmatch(r'[a-z0-9_]{1,100}', c.get('reason', '')) for c in checks):
            raise ValueError()
        return value

    def _audit(self, job):
        checks, started = [], time.monotonic()
        def add(name, ok, good, bad, status='failed'):
            checks.append(_check(name, 'passed' if ok else status, good if ok else bad))
        def budget():
            return time.monotonic() - started <= 150
        catalog = self.catalog or Catalog({})
        try:
            bundle = job['bundle']
            article, products, images = bundle['article'], bundle['products'], bundle['images']
            content, title, slug = article['content'], article['title'], article['slug']
            url = job['publication']['url']
            safe_url(url, resolve=False)
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', slug) or url != SITE + '/articles/' + slug:
                raise ValueError()
            if not isinstance(content, str) or not content.strip() or not isinstance(title, str) or not title.strip():
                raise ValueError()
            product_limit, image_limit = 12, 24
            if job.get('kind') == 'article_revision':
                from revisions import validate_revision_bundle
                validate_revision_bundle(job, bundle)
                product_limit, image_limit = 20, 41
            if len(content.encode()) > LIMIT or not isinstance(products, list) or not isinstance(images, list) or len(products) > product_limit or len(images) > image_limit:
                raise ValueError()
            ids = article['productIds']
            if not isinstance(ids, list) or len(set(ids)) != len(ids) or set(ids) != {p['id'] for p in products} or len(products) != len(ids):
                raise ValueError()
        except Exception:
            return _result([_check('input', 'failed', 'invalid_publication_binding')])
        digest = hashlib.sha256(content.encode()).hexdigest()
        if job['publication'].get('contentHash') not in (None, digest):
            return _result([_check('approved_body', 'failed', 'publication_body_hash_mismatch')])
        try:
            response = catalog.request(url, {'Accept': 'text/html', 'Cache-Control': 'no-cache'}, allowed_domains=('camp-gear-lab.com',))
            if response['status'] != 200 or response['url'] != url or len(response['body']) > LIMIT:
                return _result([_check('public_source', 'failed', 'public_response_binding_mismatch')])
            if not response['headers'].get('content-type', '').lower().startswith('text/html'):
                return _result([_check('public_source', 'unverified', 'public_html_unavailable')])
            html = _decode_html(response['body'], response['headers'].get('content-type', ''))
            source = _Source(html)
        except Exception:
            return _result([_check('public_source', 'unverified', 'public_get_unavailable')])
        add('public_title', source.titles == [title], 'public_title_exact', 'public_title_mismatch')
        add('approved_body', source.hashes == [digest], 'approved_body_hash_exact', 'approved_body_hash_mismatch')
        card = (article.get('generationMeta') or {}).get('socialCard')
        if card:
            proofs = [i for i in images if i.get('role') == 'social-card']
            add('social_manifest', len(proofs) == 1 and card.get('width') == 1200 and card.get('height') == 630
                and all(card.get(k) == proofs[0].get(k) for k in ('url', 'sha256', 'size', 'contentType')),
                'social_manifest_bound', 'social_manifest_mismatch')
            add('social_metadata', all(source.meta.get(key) == [card.get('url')] for key in ('og:image', 'twitter:image')),
                'social_metadata_exact', 'social_metadata_mismatch')
        # Legacy OG overrides are deliberately not inferred from ordinary product images.
        for n, product in enumerate(products):
            proof = [i for i in images if i.get('productId') == product['id'] and i.get('url') == product.get('imageUrl')]
            add('product_image_binding.' + str(n), len(proof) == 1, 'product_image_bound', 'product_image_proof_missing')
        # One bounded pool per live audit. Catalog still validates DNS, redirects,
        # host allowlists and byte limits; reuse here never crosses an audit run.
        catalog = self._request_pool = AuditRequests(catalog, started + 150)
        for image in images:
            try:
                parsed, _ = safe_url(image['url'], resolve=False)
                catalog.prefetch(image['url'], {'Accept': 'image/*', 'Cache-Control': 'no-cache'},
                                 allowed_domains=(parsed.hostname,), exact_domains=True)
            except Exception:
                pass  # Normal image check below records the failure.
        for product in products:
            for channel, field in (('rakuten', 'affiliateUrl'), ('amazon', 'amazonUrl')):
                href = product.get(field)
                if href and _affiliate_route(channel, href, self.env):
                    domains = ('amazon.co.jp',) if channel == 'amazon' else ('hb.afl.rakuten.co.jp', 'pt.afl.rakuten.co.jp', 'item.rakuten.co.jp', 'm.rakuten.co.jp')
                    catalog.prefetch(href, {'Accept': 'text/html'}, allowed_domains=domains)
        for n, image in enumerate(images):
            if not budget():
                checks.append(_check('images_remaining', 'unverified', 'audit_budget_exhausted'))
                break
            name = 'image.' + str(n)
            if image.get('verified') is not True or not re.fullmatch(r'[a-f0-9]{64}', str(image.get('sha256', ''))) or type(image.get('size')) is not int or not 0 < image['size'] <= LIMIT:
                checks.append(_check(name, 'failed', 'approved_image_proof_invalid'))
                continue
            try:
                parsed, _ = safe_url(image['url'], resolve=False)
                response = catalog.request(image['url'], {'Accept': 'image/*', 'Cache-Control': 'no-cache'},
                                           allowed_domains=(parsed.hostname,), exact_domains=True)
                body = response['body']
                kind = response['headers'].get('content-type', '').split(';')[0].lower()
                if response['status'] != 200 or not isinstance(body, bytes) or not 0 < len(body) <= LIMIT or _image_type(body) != kind or not kind.startswith('image/'):
                    raise ValueError()
                actual = {'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body), 'contentType': kind}
                add(name, actual['sha256'] == image['sha256'] and actual['size'] == image['size']
                    and actual['contentType'].startswith('image/') and image.get('contentType', actual['contentType']) == actual['contentType'],
                    'approved_image_bytes_exact', 'approved_image_bytes_mismatch')
            except Exception:
                checks.append(_check(name, 'unverified', 'public_image_get_unavailable'))
        # Never let a browser bypass a rejected/mismatched public source.
        if source.hashes == [digest] and source.titles == [title]:
            try:
                if not budget():
                    raise TimeoutError()
                observed = self._browser({'url': url, 'html': html, 'bundle': {'article': article,
                    'products': products, 'images': images}, 'repo': self.config.get('repo', str(Path(__file__).resolve().parents[2]))})
                checks.extend(observed['checks'])
                for name in ('desktop', 'mobile'):
                    if not any(c['name'] == name for c in observed['checks']):
                        checks.append(_check(name, 'unverified', 'viewport_evidence_missing'))
            except Exception:
                checks.append(_check('browser', 'unverified', 'browser_timeout_or_unavailable'))
        observations = []
        for n, product in enumerate(products):
            for channel, field in (('rakuten', 'affiliateUrl'), ('amazon', 'amazonUrl')):
                if not budget():
                    checks.append(_check('destinations_remaining', 'unverified', 'audit_budget_exhausted'))
                    return _with_merchant_observations(_result(checks), observations)
                name = 'destination.' + str(n) + '.' + channel
                href = product.get(field)
                if not href:
                    checks.append(_check(name, 'unverified', 'approved_merchant_url_missing'))
                    continue
                if not self.env.get('RAKUTEN_AFFILIATE_ID' if channel == 'rakuten' else 'AMAZON_PARTNER_TAG'):
                    checks.append(_check(name, 'unverified', 'affiliate_account_binding_missing'))
                    continue
                if not _affiliate_route(channel, href, self.env):
                    checks.append(_check(name, 'failed', 'affiliate_account_or_route_mismatch'))
                    continue
                model = _audit_model(product)
                if not model or not product.get('brand'):
                    checks.append(_check(name, 'unverified', 'approved_product_model_or_brand_missing'))
                    continue
                try:
                    domains = ('amazon.co.jp',) if channel == 'amazon' else ('hb.afl.rakuten.co.jp', 'pt.afl.rakuten.co.jp', 'item.rakuten.co.jp', 'm.rakuten.co.jp')
                    response = catalog.request(href, {'Accept': 'text/html'}, allowed_domains=domains)
                    final, approved = urlsplit(response['url']), urlsplit(href)
                    same = False
                    if channel == 'amazon':
                        asin = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)', approved.path)
                        final_asin = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)', final.path)
                        same = bool(asin and final_asin and asin[1] == final_asin[1] and final.hostname in ('amazon.co.jp', 'www.amazon.co.jp')
                            and product.get('asin', asin[1]) == asin[1]
                            and parse_qs(final.query).get('tag', [self.env['AMAZON_PARTNER_TAG']]) == [self.env['AMAZON_PARTNER_TAG']])
                    else:
                        targets = parse_qs(approved.query).get('pc', [])
                        same = len(targets) == 1 and final.hostname == 'item.rakuten.co.jp' and bool(re.fullmatch(r'/[^/]+/[^/]+/?', final.path))
                        if same:
                            target, _ = safe_url(targets[0], resolve=False)
                            same = target.hostname == final.hostname and target.path.rstrip('/') == final.path.rstrip('/')
                    kind = response['headers'].get('content-type', '')
                    if response['status'] != 200 or not kind.lower().startswith('text/html'):
                        checks.append(_check(name, 'unverified', 'merchant_html_unavailable'))
                        continue
                    page = _Page(_decode_html(response['body'], kind))
                    observations.append(_merchant_observation(name, product, model, page.title, response['url'], same))
                    if re.search(r'captcha|robot check|access denied|just a moment|ロボット', page.title, re.I):
                        checks.append(_check(name, 'unverified', 'merchant_challenge_unverified'))
                        continue
                    from merchant_identity import inspect_merchant_identity
                    decision = inspect_merchant_identity(product, model, page.title)
                    primary = None
                    if channel == 'amazon' and same and decision['status'] == 'unverified':
                        # The same narrow primary-node binding already used by
                        # pre-publication research; never infer from reviews or ads.
                        from primary_firepit import fixed_amazon_identity
                        primary = fixed_amazon_identity(product['id'], model, response['url'],
                                                        _decode_html(response['body'], kind), page.title)
                    identity = decision['status'] == 'passed' or bool(primary)
                    observations[-1]['primaryBindingVerified'] = bool(primary)
                    observations[-1]['identityMatched'] = identity
                    if not same:
                        checks.append(_check(name, 'failed', 'merchant_destination_or_product_identity_mismatch'))
                    elif identity:
                        checks.append(_check(name, 'passed', 'merchant_destination_and_title_model_verified'))
                    else:
                        checks.append(_check(name, decision['status'], decision['reason']))
                except Exception:
                    checks.append(_check(name, 'unverified', 'merchant_get_unavailable'))
        return _with_merchant_observations(_result(checks), observations)


if __name__ == '__main__':
    # -I removes the script directory from sys.path; bootstrap only this fixed directory.
    try:
        payload = json.loads(sys.stdin.buffer.read(2 * LIMIT + 1))
        audit = PostPublicationAudit(payload['config'], payload['env'], catalog=Catalog({}))
        value = audit.check(payload['job'])
    except Exception:
        value = _result([_check('audit', 'unverified', 'audit_input_or_transport_unavailable')])
    _emit_result(value)
