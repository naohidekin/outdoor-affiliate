"""Targeted private revision bindings. No network, models, or public writes."""
import copy
import re
from urllib.parse import urlsplit
from ledger import fingerprint, require, timestamp

TARGETS = {'article-024': 'firepit-beginner-guide', 'article-005': 'single-burner-ranking',
           'article-002': 'landlock-vs-landnest-shelter',
           '3082b43c-a612-4ae0-926e-8bd86c6ab84e': 'autumn-camp-classic-fleece-comparison',
           'winter-camp-heating-comparison-p1': 'winter-camp-heating-comparison',
           'camp-kerosene-stove-8xzl2p': 'camp-kerosene-stove-comparison',
           'article-010': 'rainwear-ranking',
           'article-043': 'autumn-camp-clothing-layering-guide'}
PRODUCT_PATCH_FIELDS = {'name', 'brand', 'specs', 'imageUrl', 'affiliateUrl', 'amazonUrl', 'price',
                        'description', 'rating', 'availability', 'updatedAt', 'yahooUrl'}
EDIT_FIELDS = ('title', 'content', 'excerpt', 'metaDescription', 'faqs', 'tags')
ANALYSIS_KIND = 'routine_existing_improvement_v1'


def _analysis_binding(value, base, products):
    require(isinstance(value, dict) and set(value) == {
        'kind', 'period', 'targetUrl', 'rank', 'metricsReceipt', 'sourceProof',
        'baseArticleHash', 'baseProductsHash', 'constraints'},
        'routine analysis binding invalid')
    require(value['kind'] == ANALYSIS_KIND
            and isinstance(value['period'], str)
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['period'])
            and type(value['rank']) is int and 1 <= value['rank'] <= 3,
            'routine analysis period or rank invalid')
    try:
        target = urlsplit(value['targetUrl'])
    except (TypeError, ValueError):
        target = None
    require(target is not None and target.scheme == 'https'
            and target.hostname == 'camp-gear-lab.com' and target.port is None
            and target.username is None and target.password is None
            and not target.query and not target.fragment
            and target.path == '/articles/' + base.get('slug', '')
            and value['targetUrl'] == 'https://camp-gear-lab.com' + target.path,
            'routine target URL invalid')
    require(value['baseArticleHash'] == fingerprint(base)
            and value['baseProductsHash'] == fingerprint(products),
            'routine baseline hash invalid')
    metrics = value['metricsReceipt']
    require(isinstance(metrics, dict) and set(metrics) == {
        'sourceId', 'collectedAt', 'currentPeriod', 'ga4Period', 'opportunityHash',
        'candidateSetHash', 'protectedWinnerUrlsHash', 'gsc', 'ga4', 'intentEvidence'},
        'routine metrics receipt invalid')
    require(isinstance(metrics['sourceId'], str)
            and re.fullmatch(r'analytics:[a-f0-9]{64}', metrics['sourceId'])
            and all(isinstance(metrics[key], str) and re.fullmatch(r'[a-f0-9]{64}', metrics[key])
                    for key in ('opportunityHash', 'candidateSetHash', 'protectedWinnerUrlsHash')),
            'routine metrics source proof invalid')
    _aware(metrics['collectedAt'])
    for key in ('currentPeriod', 'ga4Period'):
        period = metrics[key]
        require(isinstance(period, dict) and set(period) == {
            'startDate', 'endDate', 'dateBasis'}
            and all(isinstance(period.get(field), str) and period[field]
                    for field in ('startDate', 'endDate', 'dateBasis')),
            'routine metric period invalid')
    gsc, ga4 = metrics['gsc'], metrics['ga4']
    require(isinstance(gsc, dict) and set(gsc) == {
        'clicks', 'impressions', 'ctr', 'position', 'metricScope'}
        and isinstance(ga4, dict) and set(ga4) == {
            'sessions', 'engagedSessions', 'keyEvents'},
            'routine metric values invalid')
    require(metrics['intentEvidence'] == {
        'status': 'unconnected',
        'reason': 'page_bound_private_query_classification_not_implemented',
        'rawQueriesExposed': False, 'serpEvidence': 'unconnected'},
        'routine intent evidence must remain unconnected')
    require(isinstance(gsc['impressions'], (int, float)) and not isinstance(gsc['impressions'], bool)
            and gsc['impressions'] >= 30
            and isinstance(gsc['position'], (int, float)) and not isinstance(gsc['position'], bool)
            and 3 < gsc['position'] <= 20,
            'routine metric threshold invalid')
    proof = value['sourceProof']
    require(isinstance(proof, dict) and set(proof) == {
        'sourceId', 'receiptHash', 'checkedAt', 'productIds', 'checks'}
        and isinstance(proof['sourceId'], str)
        and re.fullmatch(r'catalog-gather:[a-f0-9]{64}', proof['sourceId'])
        and isinstance(proof['receiptHash'], str)
        and re.fullmatch(r'[a-f0-9]{64}', proof['receiptHash'])
        and proof['sourceId'] == 'catalog-gather:' + proof['receiptHash']
        and proof['productIds'] == base.get('productIds')
        and proof['checks'] == {'facts': True, 'images': True, 'affiliate': True},
        'routine source proof invalid')
    _aware(proof['checkedAt'])
    require(value['constraints'] == {
        'allOriginalProductsKept': True, 'productChangesAllowed': False,
        'newFactsAllowed': False, 'ownerExperienceAllowed': False,
        'ctrIntentCheckRequired': True, 'causalGuarantee': False,
        'winnerProtection': {'topPosition': 3, 'topClicks': 3},
        'maxGrowthCandidates': 3, 'manualOwnerApprovalRequired': True,
        'independentAstraReviewRequired': True},
        'routine constraints changed')
    return copy.deepcopy(value)


def _aware(value):
    require(isinstance(value, str), 'snapshot timestamp required')
    # Python 3.9 accepts only 3/6 fractional digits; PostgREST also emits .9/.48.
    normalized = re.sub(r'\.(\d+)(?=Z|[+-]\d{2}:\d{2}$)', lambda m:'.' + m[1][:6].ljust(6, '0'), value)
    return timestamp(normalized)


def validated_context(value):
    require(isinstance(value, dict) and set(value) in ({
        'baseArticle', 'changeSummary', 'editorialCorrectionInstructions', 'verifiedAuthorFacts',
        'targetProductIds', 'productRemovalReasons', 'baseProducts', 'candidateProducts'}, {
        'baseArticle', 'changeSummary', 'editorialCorrectionInstructions', 'verifiedAuthorFacts',
        'targetProductIds', 'productRemovalReasons', 'baseProducts', 'candidateProducts',
        'analysisBinding'}), 'revision request fields invalid; use bound baseProducts/candidateProducts')
    base = value['baseArticle']
    analysis = value.get('analysisBinding')
    if analysis is None:
        require(isinstance(base, dict) and base.get('id') in TARGETS
                and base.get('slug') == TARGETS[base['id']] and base.get('status') == 'published', 'revision target invalid')
    else:
        require(isinstance(base, dict) and isinstance(base.get('id'), str) and base['id']
                and isinstance(base.get('slug'), str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', base['slug'])
                and base.get('status') == 'published', 'routine revision target invalid')
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
    if analysis is not None:
        require(selected == original and removed == {} and before == after
                and [p.get('id') for p in before] == original
                and value['verifiedAuthorFacts'] == [] and not patches,
                'routine revision must preserve products and author facts')
        analysis = _analysis_binding(analysis, base, before)
    result = copy.deepcopy(value)
    yahoo_notice = '商品同一性未確認のYahoo検索リンクを非表示'
    if any('yahooUrl' in p['fields'] for p in patches) and yahoo_notice not in result['changeSummary']:
        result['changeSummary'] += '。' + yahoo_notice
        require(len(result['changeSummary']) <= 12000, 'revision change summary too long')
    result.update(kind='article_revision', baseHash=fingerprint(base), productPatches=patches)
    if analysis is not None:
        result['analysisBinding'] = analysis
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
