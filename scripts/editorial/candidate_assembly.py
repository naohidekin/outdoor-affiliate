"""Pure assembly of already-produced revision and polish records."""
import copy
from datetime import datetime, timedelta

from ledger import JST, canonical
from quality import inspect_polish
from revisions import validate_revision_bundle


TARGETS = frozenset({'article-005', 'article-024'})
NA_FIELDS = frozenset({'productId', 'channel', 'status', 'reason', 'checkedAt', 'reviewedBy'})
CHANNEL_FIELDS = {'amazon': 'amazonUrl', 'rakuten': 'affiliateUrl'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    try:
        return canonical(left) == canonical(right)
    except (TypeError, ValueError):
        return False


def _aware(value, message):
    _require(isinstance(value, str) and value.strip(), message)
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(message) from None
    _require(stamp.tzinfo is not None and stamp.utcoffset() is not None, message)
    return stamp.astimezone(JST)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def assemble_candidate(job, source_record, candidate_record, gathered,
                       purchase_evidence, polish_stage_output):
    """Bind existing artifacts for final QA without calling or writing anything."""
    _require(isinstance(job, dict) and job.get('kind') == 'article_revision',
             'article revision job required')
    context = job.get('revisionContext')
    base = context.get('baseArticle') if isinstance(context, dict) else None
    _require(isinstance(base, dict) and base.get('id') in TARGETS,
             'revision target not allowed')
    _require(all(job.get(field) is None for field in
                 ('approval', 'publication', 'review', 'bundle')),
             'revision candidate already processed')

    _require(isinstance(source_record, dict) and set(source_record) == {'kind', 'bundle'}
             and source_record.get('kind') == 'source'
             and isinstance(source_record.get('bundle'), dict),
             'source record invalid')
    source_bundle = copy.deepcopy(source_record['bundle'])
    _require('purchaseEvidence' not in source_bundle, 'source already has purchase evidence')
    _require(_same(source_bundle.get('revisionContext'), context),
             'source revision context mismatch')
    _require(_same(source_bundle.get('products'), context.get('candidateProducts')),
             'source candidate products mismatch')
    validate_revision_bundle(job, source_bundle, require_presentation=False)

    _require(isinstance(candidate_record, dict)
             and set(candidate_record) == {'kind', 'candidate'}
             and candidate_record.get('kind') == 'candidate'
             and isinstance(candidate_record.get('candidate'), dict),
             'candidate record invalid')
    _require(isinstance(polish_stage_output, dict)
             and isinstance(polish_stage_output.get('polished'), dict),
             'successful polish output required')
    polished = copy.deepcopy(candidate_record['candidate'])
    _require(_same(polished, polish_stage_output['polished']),
             'candidate does not match successful polish output')
    _require(polished.get('model') == 'gemini-3.8-flash'
             and _text(polished.get('content')), 'required Gemini polish missing')
    source_body = source_bundle.get('article', {}).get('content')
    preservation = inspect_polish(source_body, polished['content'])
    _require(preservation.get('passed') is True, 'polish preservation failed')

    _require(isinstance(gathered, dict), 'gathered evidence required')
    checks = gathered.get('checks')
    _require(isinstance(checks, dict)
             and all(checks.get(key) is True for key in ('facts', 'images', 'affiliate')),
             'gathered checks incomplete')
    products = context['candidateProducts']
    product_ids = context['targetProductIds']
    _require(_same(gathered.get('productIds'), product_ids)
             and _same(gathered.get('products'), products)
             and _same(gathered.get('catalog'), products),
             'gathered product selection mismatch')
    evidence = gathered.get('evidence')
    evidence_products = evidence.get('products') if isinstance(evidence, dict) else None
    _require(isinstance(evidence_products, list)
             and [item.get('productId') if isinstance(item, dict) else None
                  for item in evidence_products] == product_ids,
             'gathered product evidence mismatch')
    now = datetime.now(JST)
    for item in evidence_products:
        checked = _aware(item.get('checkedAt'), 'gathered checkedAt invalid')
        _require(timedelta(0) <= now - checked <= timedelta(hours=6),
                 'gathered evidence stale or future')

    _require(isinstance(purchase_evidence, list)
             and all(isinstance(item, dict) for item in purchase_evidence),
             'purchase evidence must be a list of objects')
    expected = set()
    by_id = {product['id']: product for product in products}
    for product in products:
        for channel, field in CHANNEL_FIELDS.items():
            if product.get(field) in (None, ''):
                expected.add((product['id'], channel))
        _require(any(_text(product.get(field)) for field in
                     ('affiliateUrl', 'amazonUrl', 'yahooUrl')),
                 'product has no remaining purchase destination')

    observed = []
    for item in purchase_evidence:
        _require(set(item) == NA_FIELDS, 'purchase evidence fields invalid')
        product_id, channel = item.get('productId'), item.get('channel')
        _require(product_id in by_id and channel in CHANNEL_FIELDS
                 and item.get('status') == 'NA', 'typed NA evidence invalid')
        _require(by_id[product_id].get(CHANNEL_FIELDS[channel]) in (None, ''),
                 'NA evidence requires an empty candidate URL')
        _require(_text(item.get('reason')) and _text(item.get('reviewedBy')),
                 'NA reason and reviewer required')
        checked = _aware(item.get('checkedAt'), 'NA checkedAt invalid')
        _require(timedelta(0) <= now - checked <= timedelta(hours=6),
                 'NA evidence stale or future')
        observed.append((product_id, channel))
    _require(len(observed) == len(set(observed)), 'duplicate NA evidence')
    _require(set(observed) == expected and len(observed) == len(expected),
             'NA evidence does not exactly cover missing required channels')

    final_bundle = copy.deepcopy(source_bundle)
    final_bundle['article']['content'] = polished['content']
    final_bundle['purchaseEvidence'] = copy.deepcopy(purchase_evidence)
    validate_revision_bundle(job, final_bundle, require_presentation=False)
    return source_bundle, final_bundle, copy.deepcopy(preservation), polished
