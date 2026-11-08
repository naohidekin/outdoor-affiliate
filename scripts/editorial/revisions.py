"""Targeted private revision bindings. No network, models, or public writes."""
import copy
import re
from ledger import fingerprint, require, timestamp

TARGETS = {'article-024': 'firepit-beginner-guide', 'article-005': 'single-burner-ranking',
           'article-002': 'landlock-vs-landnest-shelter'}
PRODUCT_PATCH_FIELDS = {'name', 'brand', 'specs', 'imageUrl', 'affiliateUrl', 'amazonUrl', 'price',
                        'description', 'rating', 'availability', 'updatedAt', 'yahooUrl'}
EDIT_FIELDS = ('title', 'content', 'excerpt', 'metaDescription', 'faqs', 'tags')


def _aware(value):
    require(isinstance(value, str), 'snapshot timestamp required')
    # Python 3.9 accepts only 3/6 fractional digits; PostgREST also emits .9/.48.
    normalized = re.sub(r'\.(\d+)(?=Z|[+-]\d{2}:\d{2}$)', lambda m:'.' + m[1][:6].ljust(6, '0'), value)
    return timestamp(normalized)


def validated_context(value):
    require(isinstance(value, dict) and set(value) == {
        'baseArticle', 'changeSummary', 'editorialCorrectionInstructions', 'verifiedAuthorFacts',
        'targetProductIds', 'productRemovalReasons', 'baseProducts', 'candidateProducts'}, 'revision request fields invalid; use bound baseProducts/candidateProducts')
    base = value['baseArticle']
    require(isinstance(base, dict) and base.get('id') in TARGETS
            and base.get('slug') == TARGETS[base['id']] and base.get('status') == 'published', 'revision target invalid')
    for field in ('createdAt', 'updatedAt', 'publishedAt'):
        _aware(base.get(field))
    require(isinstance(base.get('content'), str) and bool(base['content'].strip()), 'revision source required')
    original, selected = base.get('productIds'), value['targetProductIds']
    require(isinstance(original, list) and all(isinstance(i, str) and i for i in original)
            and len(original) == len(set(original)), 'revision base product IDs invalid')
    require(isinstance(selected, list) and 1 <= len(selected) <= 20
            and all(isinstance(i, str) and i in original for i in selected)
            and len(selected) == len(set(selected)), 'revision target product set invalid')
    removed = value['productRemovalReasons']
    require(isinstance(removed, dict) and set(removed) == set(original) - set(selected)
            and all(isinstance(r, str) and r.strip() for r in removed.values()), 'every removed product needs a reason')
    for field in ('changeSummary', 'editorialCorrectionInstructions'):
        require(isinstance(value[field], str) and value[field].strip() and len(value[field]) <= 12000,
                'revision correction specification required')
    facts = value['verifiedAuthorFacts']
    require(isinstance(facts, list) and len(facts) <= 30
            and all(isinstance(f, str) and f.strip() and len(f) <= 2000 for f in facts), 'verified author facts invalid')
    before, after = value['baseProducts'], value['candidateProducts']
    require(isinstance(before, list) and isinstance(after, list)
            and all(isinstance(p, dict) for p in before + after)
            and [p.get('id') for p in before] == selected == [p.get('id') for p in after],
            'revision exact base and candidate product snapshots required')
    patches = []
    for old, new in zip(before, after):
        require(set(old) == set(new), 'candidate product snapshot fields changed')
        changes = {k: copy.deepcopy(new[k]) for k in new if new[k] != old[k]}
        require(set(changes) <= PRODUCT_PATCH_FIELDS, 'protected product fields changed')
        require('yahooUrl' not in changes or new['yahooUrl'] == '', 'Yahoo route changes may only remove the optional URL')
        _aware(old.get('updatedAt'))
        _aware(new.get('updatedAt'))
        if changes:
            require(old['updatedAt'] != new['updatedAt'], 'patched product needs a new bound timestamp')
            patches.append(dict(id=old['id'], baseHash=fingerprint(old), candidateHash=fingerprint(new), fields=changes))
    result = copy.deepcopy(value)
    yahoo_notice = '商品同一性未確認のYahoo検索リンクを非表示'
    if any('yahooUrl' in p['fields'] for p in patches) and yahoo_notice not in result['changeSummary']:
        result['changeSummary'] += '。' + yahoo_notice
        require(len(result['changeSummary']) <= 12000, 'revision change summary too long')
    result.update(kind='article_revision', baseHash=fingerprint(base), productPatches=patches)
    return result


def validate_context(context):
    require(isinstance(context, dict), 'revision binding required')
    value = {k: v for k, v in context.items() if k not in ('kind', 'baseHash', 'productPatches')}
    require(validated_context(value) == context, 'revision baseline binding changed')
    return context


def validate_revision_bundle(job, bundle, require_presentation=True):
    context = validate_context(job['revisionContext'])
    if require_presentation or bundle.get('inheritedPresentationContext') is not None:
        from inherited_advice import validate_presentation
        validate_presentation(bundle.get('inheritedPresentationContext'), context['baseArticle']['slug'])
    require(bundle.get('revisionContext') == context, 'revision candidate context changed')
    require(not any(k in bundle for k in ('productOverrides', 'baseProductRows', 'productPatches')),
            'shared product changes require a separate approval workflow')
    article, base = bundle['article'], context['baseArticle']
    allowed = set(EDIT_FIELDS) | {'productIds', 'author', 'generationMeta'}
    for key in set(base) | set(article):
        if key not in allowed:
            require(article.get(key) == base.get(key), 'revision protected article field changed')
    require(article.get('productIds') == context['targetProductIds'], 'revision product set changed')
    require(bundle['products'] == context['candidateProducts'], 'revision candidate product records changed')
    prior_meta = copy.deepcopy(base.get('generationMeta') or {})
    next_meta = copy.deepcopy(article.get('generationMeta') or {})
    prior_meta.pop('socialCard', None)
    next_meta.pop('socialCard', None)
    require(prior_meta == next_meta, 'revision unrelated generation metadata changed')
    author = base.get('author') or ((base.get('generationMeta') or {}).get('editorialRuntime') or {}).get('author') or 'ギア男'
    require(article.get('author') == author, 'revision author changed')
    require(all(f in article.get('content', '') for f in context['verifiedAuthorFacts']), 'verified author fact removed')
