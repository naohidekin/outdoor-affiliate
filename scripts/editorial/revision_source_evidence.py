"""Scoped fresh Catalog evidence attachment; no runtime, budget or publication API.

Main injects this Catalog wrapper under its existing runtime.flock. The supplied
source_data is a historical Astra review input, never a replacement for fresh
gather_revision. A required record sink must persist provenance before return.
"""
import copy
from datetime import datetime, timedelta, timezone
import re

from catalog import Catalog
from apparel_identity import apparel_contract
from ledger import fingerprint
from purchase_evidence import validate_purchase_evidence
from revisions import validate_context

JST = timezone(timedelta(hours=9))
ARTICLE = '3082b43c-a612-4ae0-926e-8bd86c6ab84e'
SLUG = 'autumn-camp-classic-fleece-comparison'
TNF, MONTBELL = 'fleece-tnf-na62650', 'fleece-montbell-1114881'
OFFICIAL_HINTS = {
    TNF: ['https://www.goldwin.co.jp/ap/item/i/m/NA62650'],
    MONTBELL: ['https://webshop.montbell.jp/goods/disp.php?product_id=1114881'],
}
AUTHOR_FIELDS = {'kind', 'actor', 'reference', 'revisionContextFingerprint',
                 'officialHintsFingerprint', 'sourceDataFingerprint',
                 'reviewedAt', 'expiresAt', 'purchaseEvidence'}


def _require(ok, reason):
    if not ok:
        raise ValueError('revision_source_evidence_' + reason)


def _aware(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(result.tzinfo is not None and result.utcoffset() is not None, 'timestamp')
        return result
    except (AttributeError, TypeError, ValueError):
        raise ValueError('revision_source_evidence_timestamp') from None


class RevisionSourceEvidence:
    """Delegate normal Catalog methods, overriding only this exact revision.

    author_evidence: kind=source_data, actor=Astra, reference, the three named
    fingerprints, reviewedAt/expiresAt (at most six hours), and one typed TNF
    Amazon NA reviewedBy=Astra. record(receipt) must raise on persistence failure.
    Main supplies author evidence; this adapter does not perform an Astra review.
    """
    def __init__(self, catalog, revision_context, *, context_fingerprint,
                 official_hints, source_data, author_evidence, record, clock=None):
        _require(isinstance(catalog, Catalog) and callable(record), 'catalog_and_record')
        validate_context(revision_context)
        _require(fingerprint(revision_context) == context_fingerprint, 'context_fingerprint')
        base = revision_context['baseArticle']
        _require(base['id'] == ARTICLE and base['slug'] == SLUG
                 and revision_context['targetProductIds'] == [TNF, MONTBELL], 'scope')
        for product, model, brand in zip(revision_context['candidateProducts'],
                                         ('NA62650', '1114881'), ('THE NORTH FACE', 'mont-bell')):
            contract = apparel_contract(product)
            _require(contract['model'] == model and contract['brand'] == brand
                     and contract['class'] == 'fleece' and contract['gender'] == "Men's"
                     and contract['optionState'] == 'selectable', 'product_scope')
        _require(official_hints == OFFICIAL_HINTS, 'official_hints')
        _require(isinstance(source_data, dict)
                 and source_data.get('products') == revision_context['candidateProducts']
                 and all(source_data.get('checks', {}).get(k) is True
                         for k in ('facts', 'images', 'affiliate')), 'historical_source_binding')
        self._binding = copy.deepcopy(revision_context)
        self._fingerprint = context_fingerprint
        self._hints = copy.deepcopy(official_hints)
        self._author = copy.deepcopy(author_evidence)
        self._source_hash = fingerprint(source_data)
        self._record = record
        self._clock = clock or (lambda: datetime.now(JST))
        # Clone configuration only. Catalog.request/fetcher and ordinary
        # gather_revision retain their normal transport and identity checks.
        self._original = catalog
        self._catalog = copy.copy(catalog)
        self._catalog.source_hints = dict(copy.deepcopy(catalog.source_hints), **self._hints)
        self._validate_author(self._now())

    def __getattr__(self, name):
        return getattr(self._original, name)

    def _now(self):
        value = self._clock()
        _require(isinstance(value, datetime) and value.tzinfo is not None
                 and value.utcoffset() is not None, 'clock')
        return value

    def _validate_author(self, now):
        a = self._author
        _require(isinstance(a, dict) and set(a) == AUTHOR_FIELDS
                 and a['kind'] == 'source_data' and a['actor'] == 'Astra'
                 and isinstance(a['reference'], str) and bool(a['reference'].strip()), 'author')
        _require(a['revisionContextFingerprint'] == self._fingerprint
                 and a['officialHintsFingerprint'] == fingerprint(self._hints)
                 and a['sourceDataFingerprint'] == self._source_hash
                 and re.fullmatch(r'[0-9a-f]{64}', self._source_hash), 'author_binding')
        reviewed, expires = _aware(a['reviewedAt']), _aware(a['expiresAt'])
        _require(reviewed <= now < expires <= reviewed + timedelta(hours=6), 'author_expired')
        evidence = a['purchaseEvidence']
        # Validate the original review time, without renewing it. Only the
        # fresh alternative destination's checkedAt may timestamp returned NA.
        validate_purchase_evidence({'products': self._binding['candidateProducts']}, evidence, now)
        _require(len(evidence) == 1 and evidence[0]['productId'] == TNF
                 and evidence[0]['channel'] == 'amazon' and evidence[0]['reviewedBy'] == 'Astra'
                 and _aware(evidence[0]['checkedAt']) <= reviewed, 'na_scope')

    def gather_revision(self, theme, catalog, binding):
        start = self._now()
        self._validate_author(start)
        validate_context(binding)
        _require(fingerprint(binding) == self._fingerprint and binding == self._binding, 'context_drift')
        _require(theme.get('slug') == SLUG and theme.get('productIds') == [TNF, MONTBELL]
                 and theme.get('categoryId') == self._binding['baseArticle'].get('categoryId'), 'theme')
        articles = catalog.get('revisionArticles', catalog.get('articles', []))
        live = [a for a in articles if a.get('id') == ARTICLE]
        _require(len(live) == 1 and fingerprint(live[0]) == binding['baseHash'], 'article_baseline')
        for base in binding['baseProducts']:
            rows = [p for p in catalog.get('products', []) if p.get('id') == base['id']]
            _require(rows == [base], 'product_baseline')
        fresh = self._catalog.gather_revision(copy.deepcopy(theme), copy.deepcopy(catalog),
                                              copy.deepcopy(binding))
        end = self._now()
        self._validate_author(end)
        _require(start <= end, 'clock')
        _require(isinstance(fresh, dict) and not fresh.get('blocked')
                 and 'purchaseEvidence' not in fresh and 'revisionSourceEvidence' not in fresh
                 and fresh.get('products') == fresh.get('catalog') == binding['candidateProducts']
                 and fresh.get('productIds') == [TNF, MONTBELL]
                 and all(fresh.get('checks', {}).get(k) is True
                         for k in ('facts', 'images', 'affiliate')), 'fresh_checks')
        details = fresh.get('evidence', {}).get('products', [])
        _require([d.get('productId') for d in details] == [TNF, MONTBELL], 'fresh_products')
        expected = {(TNF, 'rakuten'), (MONTBELL, 'rakuten'), (MONTBELL, 'amazon')}
        observed, alternative_time = set(), None
        for product, detail in zip(binding['candidateProducts'], details):
            _require(all(detail.get(k) is True for k in ('facts', 'images', 'affiliate'))
                     and start <= _aware(detail.get('checkedAt')) <= end, 'fresh_product_checks')
            for d in detail.get('destinations', []):
                pair = (product['id'], d.get('channel'))
                field = {'rakuten': 'affiliateUrl', 'amazon': 'amazonUrl'}.get(d.get('channel'))
                _require(pair in expected and pair not in observed and d.get('verified') is True
                         and d.get('url') == product.get(field)
                         and start <= _aware(d.get('checkedAt')) <= end, 'fresh_destinations')
                observed.add(pair)
                if pair == (TNF, 'rakuten'):
                    alternative_time = d['checkedAt']
        _require(observed == expected and binding['candidateProducts'][0].get('amazonUrl') == '',
                 'three_destinations')
        evidence = copy.deepcopy(self._author['purchaseEvidence'])
        evidence[0]['checkedAt'] = alternative_time
        result = validate_purchase_evidence(fresh, evidence, end)
        receipt = dict(kind='revision_source_evidence_v1', recordType='source_data',
                       actor='Astra', actorMeaning='Caller review input; not a new automated Astra review',
                       authorEvidence=copy.deepcopy(self._author),
                       revisionContextFingerprint=self._fingerprint,
                       historicalSourceDataFingerprint=self._source_hash,
                       freshSourceDataFingerprint=fingerprint(fresh),
                       officialHints=copy.deepcopy(self._hints), startedAt=start.isoformat(),
                       completedAt=end.isoformat(), freshVerifier='Catalog.gather_revision',
                       alternativeCheckedAt=alternative_time, amazonRefetched=False,
                       purchaseEvidence=copy.deepcopy(evidence))
        result['revisionSourceEvidence'] = copy.deepcopy(receipt)
        _require(self._record(copy.deepcopy(receipt)) is not False, 'record_failed')
        return result
