"""Immutable, private new-article catalog corrections. No sources or side effects."""
import copy
from ledger import canonical, fingerprint, require
from revisions import PRODUCT_PATCH_FIELDS, _aware

RAW_FIELDS = {'baseProducts', 'candidateProducts', 'changeSummary'}
DERIVED_FIELDS = {'kind', 'productPatches'}


def validated_context(raw):
    require(isinstance(raw, dict) and set(raw) == RAW_FIELDS, 'catalog correction request fields invalid')
    require(isinstance(raw['changeSummary'], str) and raw['changeSummary'].strip()
            and len(raw['changeSummary']) <= 12000, 'catalog correction summary required')
    before, after = raw['baseProducts'], raw['candidateProducts']
    require(isinstance(before, list) and isinstance(after, list) and 1 <= len(before) <= 20
            and len(before) == len(after) and all(isinstance(p, dict) for p in before + after),
            'exact catalog product snapshots required')
    ids = [p.get('id') for p in before]
    require(all(isinstance(i, str) and i.strip() for i in ids) and len(ids) == len(set(ids))
            and ids == [p.get('id') for p in after], 'catalog product identities changed')
    patches = []
    for old, new in zip(before, after):
        require(set(old) == set(new), 'candidate product snapshot fields changed')
        require(isinstance(old.get('categoryId'), str) and old['categoryId'], 'product category required')
        for p in (old, new):
            _aware(p.get('createdAt')) if 'createdAt' in p else None
            _aware(p.get('updatedAt'))
        changes = {k: copy.deepcopy(new[k]) for k in new if canonical(old[k]) != canonical(new[k])}
        require(set(changes) <= PRODUCT_PATCH_FIELDS, 'protected product fields changed')
        require('yahooUrl' not in changes or new['yahooUrl'] == '', 'Yahoo route changes may only remove the optional URL')
        if changes:
            require(_aware(old['updatedAt']) != _aware(new['updatedAt']), 'patched product needs a new bound timestamp')
            patches.append(dict(id=old['id'], baseHash=fingerprint(old), candidateHash=fingerprint(new), fields=changes))
    result = copy.deepcopy(raw)
    result.update(kind='catalog_correction', productPatches=patches)
    return result


def validate_context(ctx):
    require(isinstance(ctx, dict) and set(ctx) == RAW_FIELDS | DERIVED_FIELDS, 'catalog correction binding required')
    require(canonical(validated_context({k: ctx[k] for k in RAW_FIELDS})) == canonical(ctx), 'catalog correction binding changed')
    return ctx


def validate_bundle(job, bundle):
    ctx = validate_context(job.get('catalogCorrectionContext'))
    require(job.get('kind') != 'article_revision' and 'revisionContext' not in bundle, 'new article correction required')
    require(canonical(bundle.get('catalogCorrectionContext')) == canonical(ctx), 'catalog correction context changed')
    require(not any(k in bundle for k in ('productOverrides', 'baseProductRows', 'productPatches')), 'unbound product correction refused')
    ids = [p['id'] for p in ctx['candidateProducts']]
    article, theme = bundle['article'], job['theme']
    require(theme.get('productIds') == ids == article.get('productIds'), 'selected theme products changed')
    require(article.get('status') == 'draft' and article.get('publishedAt') is None, 'new article must remain draft')
    require(theme.get('categoryId') == article.get('categoryId')
            and all(p['categoryId'] == article['categoryId'] for p in ctx['candidateProducts']), 'product category mismatch')
    require(canonical(bundle.get('products')) == canonical(ctx['candidateProducts']), 'candidate products changed')


def validate_live_context(ctx, liveproducts):
    validate_context(ctx)
    require(isinstance(liveproducts, list) and all(isinstance(p, dict) for p in liveproducts), 'live catalog required')
    # A complete catalog may contain unselected products; duplicate selected IDs fail.
    for expected in ctx['baseProducts']:
        found = [p for p in liveproducts if p.get('id') == expected['id']]
        require(len(found) == 1 and canonical(found[0]) == canonical(expected), 'catalog baseline changed')
    return ctx
