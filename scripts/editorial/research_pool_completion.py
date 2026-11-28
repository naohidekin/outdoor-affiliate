"""One owner-granted completion of the held 2026-11-27 regular research pool.

This module does not add a retry flag.  It archives the held pool, claims the
single completion before the paid planning request, and commits only a normal
three-theme pool that the existing producer can consume.
"""
import copy
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from daily_metrics import require_fresh_daily_metrics
from ledger import JST, canonical, fingerprint
from model_budget import BudgetHold, _config, _usage
from models import Models, ModelOutcomeUnknown, _strict_json
from regular_backfill import pending, regular, backfill
from catalog_corrections import validated_context as corrected_context, validate_context as checked_correction, validate_live_context
from runtime import atomic
from topic_index import build_article_index
from topic_selection import (bind_nonproduct_theme, collect_primary_sources,
                             select_proposals, validate_proposals, editorial_signals)


PERIOD = '2026-11-27'
VERSION = 1
KEY = 'research_pool_completion:v1:' + PERIOD
AUTHORIZATION = 'owner-20261128-finite-research-pool-completion'
SOURCE_FOLDER = '2026-11-27-owner-20261128'
FLEECE = ['apparel-montbell-1114881', 'apparel-montbell-1106832']
DOWN = ['apparel-montbell-1101493', 'apparel-montbell-1101606']
PRODUCT_IDS = FLEECE + DOWN
SOURCE_URLS = {
    'https://www.montbell.jp/generalpage/disp.php?id=504',
    'https://www.montbell.jp/generalpage/disp.php?id=507',
}
MAX_CONTEXT_BYTES = 256 * 1024
FILES = ('research_pool_completion.py', 'models.py', 'runtime.py', 'topic_selection.py',
         'topic_index.py', 'regular_backfill.py', 'model_budget.py')


def require(value, code):
    if not value:
        raise ValueError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, code):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and path.stat().st_size <= 2 * 1024 * 1024
            and not any(p.is_symlink() for p in (path, *path.parents)), code)
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError, TypeError):
        raise ValueError(code) from None
    require(isinstance(value, dict), code)
    return value, raw, _sha(raw)


def _paths(root):
    return {
        'marker': root / 'production-attempts' / (PERIOD + '.json'),
        'period_receipt': root / 'period-receipts' / (PERIOD + '.json'),
        'update_proposal': root / 'existing-update-proposals' / (PERIOD + '.json'),
        'context': root / 'research-contexts' / (PERIOD + '.json'),
        'public_feed': root / 'public-sources' / (PERIOD + '.json'),
    }


def _archive(root):
    return root / 'research-pool-completion' / PERIOD


def _artifact_path(root, response_id):
    require(isinstance(response_id, str) and 1 <= len(response_id) <= 160,
            'research_pool_completion_old_response_required')
    return root / 'model-artifacts' / (_sha(response_id.encode()) + '.json')


def _protocol():
    base = Path(__file__).parent
    return {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in FILES}


def _owner(value):
    require(isinstance(value, dict) and value.get('source') == 'codex'
            and set(value) == {'source', 'thread_id', 'message_id', 'text'}
            and all(isinstance(value.get(key), str) and value[key].strip()
                    and len(value[key]) <= 1000 for key in ('thread_id', 'message_id', 'text')),
            'research_pool_completion_owner_instruction_required')
    return copy.deepcopy(value)


def _db_value(db, key):
    row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _catalog_projection(live):
    return {key: copy.deepcopy(live[key]) for key in ('articles', 'products', 'categories')}


def _candidate_catalog(live, correction):
    value = _catalog_projection(live)
    if correction:
        validate_live_context(correction, live['products'])
        candidates = {p['id']: p for p in correction['candidateProducts']}
        value['products'] = [copy.deepcopy(candidates.get(p['id'], p)) for p in live['products']]
    return value


def _source_readiness(runtime, products, correction, now):
    folder = runtime.root / 'planning-completions' / SOURCE_FOLDER
    indexed = {item.get('id'): item for item in products if isinstance(item, dict)}
    changed = {p['id'] for p in correction['productPatches']} if correction else set()
    proofs = {}
    for product_id in PRODUCT_IDS:
        product = indexed.get(product_id)
        require(product is not None, 'research_pool_completion_catalog_product_missing')
        suffix = '-candidate-source.json' if product_id in changed else '-source.json'
        proof, _, digest = _read(folder / (product_id + suffix),
                                 'research_pool_completion_product_source_required')
        require(proof.get('productIds') == [product_id] and proof.get('products') == [product]
                and proof.get('blocked') is False
                and proof.get('checks') == {'facts': True, 'images': True, 'affiliate': True},
                'research_pool_completion_product_source_not_ready')
        evidence = (proof.get('evidence') or {}).get('products', [])
        require(len(evidence) == 1 and evidence[0].get('productId') == product_id,
                'research_pool_completion_product_evidence_missing')
        at = datetime.fromisoformat(evidence[0]['checkedAt'].replace('Z', '+00:00'))
        require(at.tzinfo is not None and timedelta(0) <= now - at <= timedelta(hours=6)
                and all(evidence[0].get(k) is True for k in ('facts','images','affiliate'))
                and all(any(d.get('channel') == channel and d.get('verified') is True
                            for d in evidence[0].get('destinations', [])) for channel in ('amazon','rakuten')),
                'research_pool_completion_product_source_stale_or_incomplete')
        proofs[product_id] = digest
    return {'path': str(folder), 'requiredProductIds': list(PRODUCT_IDS), 'proofSha256': proofs}


def _state(runtime, hashes, owner_instruction, now, catalog_correction=None):
    runtime._require_running()
    require(now.tzinfo is not None and now.utcoffset() is not None,
            'research_pool_completion_aware_time_required')
    require_fresh_daily_metrics(runtime.config, now=now)
    require(runtime.ledger.production_schedule.period_key(now) == PERIOD,
            'research_pool_completion_current_period_required')
    limits = _config(runtime.config.get('modelBudget'))
    require(limits['article']['calls'] == 32 and limits['period']['calls'] == 128,
            'research_pool_completion_existing_budget_required')
    paths = _paths(runtime.root)
    values = {}
    for name, path in paths.items():
        value, _, digest = _read(path, 'research_pool_completion_' + name + '_required')
        require(hashes.get(name) == digest, 'research_pool_completion_input_drift')
        values[name] = value
    marker, receipt = values['marker'], values['period_receipt']
    require(marker.get('status') == 'selection_hold' and marker.get('period') == PERIOD
            and marker.get('holdReason') == 'insufficient_qualified_period_pool'
            and marker.get('eligibleCount') == 1 and marker.get('unfilled') == 2
            and marker.get('selection') == 'hold',
            'research_pool_completion_exact_hold_required')
    decisions = receipt.get('decisions')
    pinned_rows = [row for row in decisions or [] if isinstance(row, dict)
                   and row.get('status') == 'hold'
                   and row.get('reason') == 'insufficient_qualified_period_pool']
    require(receipt.get('period') == PERIOD and receipt.get('status') == 'hold'
            and receipt.get('eligibleCount') == 1 and receipt.get('unfilled') == 2
            and len(pinned_rows) == 1 and isinstance(pinned_rows[0].get('proposal'), dict),
            'research_pool_completion_pinned_proposal_required')
    pinned = copy.deepcopy(pinned_rows[0]['proposal'])
    require(pinned in marker.get('proposals', []) and pinned.get('productIds') == FLEECE,
            'research_pool_completion_exact_pinned_fleece_required')
    live = runtime.catalog.catalog()
    require(isinstance(live, dict) and isinstance(live.get('products'), list)
            and isinstance(live.get('articles'), list), 'research_pool_completion_live_catalog_required')
    correction = (checked_correction(catalog_correction) if catalog_correction and
                  catalog_correction.get('kind') else corrected_context(catalog_correction)
                  if catalog_correction else None)
    if correction:
        require([p['id'] for p in correction['baseProducts']] == DOWN,
                'research_pool_completion_correction_pair_mismatch')
    candidate = _candidate_catalog(live, correction)
    source_readiness = _source_readiness(runtime, candidate['products'], correction, now)
    owner = _owner(owner_instruction)
    with sqlite3.connect(runtime.ledger.db_path) as db:
        repair = _db_value(db, 'research_response_recovery:v1:' + PERIOD)
        require(isinstance(repair, dict) and repair.get('repairsUsed') == 1
                and repair.get('maxRepairs') == 1 and repair.get('resultStatus') == 'selection_hold'
                and repair.get('status') in ('held', 'completed'),
                'research_pool_completion_used_repair_required')
        usage_rows = [dict(zip([item[0] for item in cursor.description], row))
                      for cursor in [db.execute('SELECT * FROM model_budget_reservations '
                          'WHERE article_id=? AND period_key=? ORDER BY created_at,reservation_id',
                          ('research:' + PERIOD, PERIOD))] for row in cursor.fetchall()]
        require(len(usage_rows) == 2 and all(row.get('stage') == 'research'
                and row.get('status') == 'settled' and row.get('outcome') == 'success'
                and row.get('response_id') for row in usage_rows),
                'research_pool_completion_settled_research_history_required')
        response_id = marker.get('responseId')
        artifact, _, artifact_sha = _read(_artifact_path(runtime.root, response_id),
                                         'research_pool_completion_old_artifact_required')
        checker = runtime.models if isinstance(runtime.models, Models) else Models(runtime.env)
        checker._safe_public(artifact)
        record = next((row for row in usage_rows if row['response_id'] == response_id), None)
        raw_proposals = _strict_json(artifact.get('content', '')).get('proposals', [])
        require(record is not None and artifact.get('responseId') == response_id
                and artifact.get('model') == record['model']
                and _usage(artifact.get('usage')) == (record['actual_input_tokens'], record['actual_output_tokens'])
                and pinned in raw_proposals, 'research_pool_completion_old_artifact_binding')
        require(not db.execute("SELECT 1 FROM effects WHERE status IN ('in_flight','unknown') LIMIT 1").fetchone()
                and not db.execute("SELECT 1 FROM model_budget_reservations "
                    "WHERE period_key=? AND status IN ('reserved','in_flight','unknown') LIMIT 1",
                    (PERIOD,)).fetchone(),
                'research_pool_completion_unknown_state')
        jobs = [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs')]
        require(not any(regular(job) and job.get('week') == PERIOD for job in jobs)
                and sum(pending(job) for job in jobs) <= 1
                and db.execute('SELECT 1 FROM meta WHERE key=?',
                               ('regular_selection:v1:' + PERIOD,)).fetchone() is None,
                'research_pool_completion_pending_or_selection_cap')
        require(_db_value(db, KEY) is None, 'research_pool_completion_already_claimed')
    return {'schemaVersion': VERSION, 'period': PERIOD, 'stateRoot': str(runtime.root),
            'runtimeConfigSha256': fingerprint(runtime.config), 'protocol': _protocol(),
            'inputSha256': copy.deepcopy(hashes), 'pinnedProposal': pinned,
            'pinnedProposalSha256': fingerprint(pinned),
            'ownerInstruction': owner, 'ownerInstructionSha256': fingerprint(owner),
            'repairRecord': {'sha256': fingerprint(repair), 'repairsUsed': 1,
                             'status': repair['status']},
            'oldResearchUsage': {'sha256': fingerprint(usage_rows),
                                 'settledCalls': len(usage_rows)},
            'heldModelArtifact': {'responseId': response_id, 'sha256': artifact_sha},
            'liveCatalogSha256': fingerprint(_catalog_projection(live)), 'sourceReadiness': source_readiness,
            'catalogCorrectionContext': copy.deepcopy(correction),
            'budgetCapsSha256': fingerprint(limits), 'maxOwnerCompletions': 1,
            'newDirections': [
                {'kind': 'exact_product_pair', 'productIds': list(DOWN),
                 'decision': 'Plasma 1000 and Light Alpine down comparison'},
                {'kind': 'verified_nonproduct', 'productIds': [],
                 'decision': 'hard shell and soft shell comparison',
                 'requiredPrimaryUrls': sorted(SOURCE_URLS)}],
            'ownerArticleApproval': False, 'ownerSNSApproval': False,
            'publication': 'prohibited'}


def prepare(runtime, *, owner_instruction, marker, period_receipt, update_proposal,
            context, public_feed, now=None, catalog_correction=None):
    """Read-only eligibility and exact-state manifest."""
    hashes = {'marker': marker, 'period_receipt': period_receipt,
              'update_proposal': update_proposal, 'context': context,
              'public_feed': public_feed}
    return _state(runtime, hashes, owner_instruction, now or datetime.now(JST), catalog_correction)


def owner_grant(manifest):
    return {'authorization': AUTHORIZATION, 'period': PERIOD,
            'ownerInstructionSha256': manifest['ownerInstructionSha256'],
            'inputSha256': copy.deepcopy(manifest['inputSha256']),
            'manifestSha256': fingerprint(manifest)}


def _compact_existing(index):
    from search_demand import classify_topic
    result = []
    for row in index:
        item = {key: row.get(key) for key in ('id', 'slug', 'title', 'categoryId')}
        facets = classify_topic(' '.join(str(row.get(key) or '') for key in
                                         ('title', 'query', 'excerpt')))
        if row.get('categoryId') == 'wear' or facets.get('garments'):
            item['headings'] = [str(value)[:80] for value in row.get('headings', [])[:8]]
        result.append(item)
    return result


def _safe_signals(signals, index, pinned):
    from search_demand import classify_topic
    articles = {row.get('slug'): row for row in index}
    keep = set(pinned.get('sourceIds', []))
    selected = []
    for signal in signals:
        if not isinstance(signal, dict) or not isinstance(signal.get('id'), str):
            continue
        kind = signal.get('kind')
        relevant = signal['id'] in keep
        if kind == 'public_reference':
            relevant = signal.get('url') in SOURCE_URLS
        elif kind == 'own_site_query_demand':
            facets = signal.get('facets') if isinstance(signal.get('facets'), dict) else {}
            relevant = bool(set(facets.get('garments', [])) &
                            {'fleece', 'down', 'hard_shell', 'soft_shell'})
        elif kind in ('gsc', 'ga4', 'own_site_gsc_period_comparison'):
            locator = str(signal.get('locator', '')).rstrip('/').split('/')[-1]
            article = articles.get(locator)
            facets = classify_topic(' '.join(str(article.get(key) or '') for key in
                ('title', 'query', 'excerpt')) + ' ' + ' '.join(article.get('headings', []))) if article else {}
            relevant = bool(article and article.get('categoryId') == 'wear'
                            and (facets.get('garments') or 'apparel' in facets.get('gearTypes', [])))
        if relevant and kind in ('public_reference', 'own_site_query_demand', 'gsc', 'ga4',
                                 'own_site_gsc_period_comparison'):
            selected.append(copy.deepcopy(signal))
    ids = [item['id'] for item in selected]
    require(len(ids) == len(set(ids)) and set(pinned.get('sourceIds', [])) <= set(ids),
            'research_pool_completion_safe_signal_missing')
    return selected


def _paid_context(runtime, base, live, feed, index, manifest):
    compact = _compact_existing(index)
    full = runtime._research_context(base, feed=feed, existing_summaries=compact)
    signals = _safe_signals(full.get('editorialSignals', []), index,
                            manifest['pinnedProposal'])
    focus = _focused_demand(runtime)
    known = {item['id'] for item in signals}
    signals.extend(item for item in focus['signals'] if item['id'] not in known)
    products = {item.get('id'): item for item in live['products'] if isinstance(item, dict)}
    public = [copy.deepcopy(item) for item in feed.get('sources', [])
              if item.get('url') in SOURCE_URLS]
    require({item.get('url') for item in public} == SOURCE_URLS,
            'research_pool_completion_primary_sources_required')
    queued = [{key: copy.deepcopy(theme.get(key)) for key in
               ('slug', 'title', 'categoryId', 'productIds')}
              for theme in base.get('queuedThemes', []) if isinstance(theme, dict)]
    context = {
        'catalog': [{key: copy.deepcopy(products[pid].get(key)) for key in
                     ('id', 'name', 'brand', 'categoryId', 'specs')} for pid in PRODUCT_IDS],
        'categories': [copy.deepcopy(item) for item in full.get('categories', [])
                       if item.get('id') == 'wear'],
        'existingArticles': compact, 'queuedThemes': queued,
        'editorialSignals': signals, 'publicSources': public,
        'focusedDemandProvenance': focus['provenance'],
        'pinnedProposal': copy.deepcopy(manifest['pinnedProposal']),
        'completionDirections': copy.deepcopy(manifest['newDirections']),
        'externalTrend': {'status': 'unconnected', 'records': [],
                          'limitations': 'No market volume or trend inference.'},
        'instructions': ('Return exactly the two supplied completion directions. '
            'Do not repeat or replace pinnedProposal. Exact product sets are immutable. '
            'Own-site controlled-facet query groups and related-page proxies are different evidence types. '
            'Use the observed query group when available and name its actual sample size. '
            'A generic Montbell down-comparison group does not prove demand for this exact two-product pair. '
            'The shell direction has related-page proxy evidence only, not a directly observed shell-comparison query. '
            'Neither evidence type proves market volume or trend. Full article overlap is checked locally. '
            'State the correct evidence type and its limits in selectionReason; keep it under 300 characters. '
            'The shell guide is about roles only, not temperature suitability, model recommendations or route safety. '
            'Include the exact source IDs for both the softshell and layering pages. '
            'Current softshell breathability exceptions must not be generalized away. '
            'Catalog purchase variants differ: the Light Alpine Amazon option is dark-gray XL, Rakuten is selectable; '
            'this is only private correction preparation and grants no owner/publication approval.'),
    }
    encoded = canonical(context).encode()
    require(len(encoded) <= MAX_CONTEXT_BYTES, 'research_pool_completion_context_too_large')
    require('rawQueries' not in context and 'queries' not in context,
            'research_pool_completion_raw_query_forbidden')
    checker = runtime.models if isinstance(runtime.models, Models) else Models(runtime.env)
    checker._safe_public(context)
    return context


def _focused_demand(runtime):
    """Privately reproject observed apparel rows omitted by the usual 40-group cap."""
    if not runtime.config.get('seoStateRoot'):
        return {'signals': [], 'provenance': {'status': 'unavailable'}}
    from daily_metrics import _validated_snapshot
    from search_demand import classify_topic, project_search_demand
    path = Path(runtime.config['seoStateRoot']) / 'metrics/latest.json'
    require(path.stat().st_size <= 4 * 1024 * 1024,
            'research_pool_completion_metrics_oversized')
    snapshot = _validated_snapshot(json.loads(path.read_text()), datetime.now(JST))
    current = snapshot['current']
    wanted = {'fleece', 'down', 'hard_shell', 'soft_shell'}
    rows = [row for row in current.get('queries', []) if isinstance(row, dict)
            and wanted.intersection(classify_topic(row.get('query', ''))['garments'])]
    demand = project_search_demand(rows, {k: current[k] for k in ('startDate','endDate','dateBasis')})
    projected = {'status': 'ok', 'evidence': {'current': {'searchDemand': demand}}}
    values = editorial_signals(projected, {'sources': []})
    return {'signals': [item for item in values if item.get('kind') == 'own_site_query_demand'],
            'provenance': {'status': 'observed_subset', 'snapshotSha256': fingerprint(snapshot),
                'selectedRowCount': len(rows), 'filterGarments': sorted(wanted),
                'rawQueriesExposed': False, 'marketDemand': False, 'trendVerified': False}}


def _archive_inputs(root, manifest):
    archive = _archive(root)
    require(not any(p.is_symlink() for p in (archive, *archive.parents)),
            'research_pool_completion_unsafe_archive')
    require(not archive.exists(), 'research_pool_completion_archive_exists')
    archive.mkdir(parents=True)
    for name, path in _paths(root).items():
        raw = path.read_bytes()
        require(_sha(raw) == manifest['inputSha256'][name],
                'research_pool_completion_input_drift')
        with (archive / ('old-' + name.replace('_', '-') + '.json')).open('xb') as output:
            output.write(raw)
    atomic(archive / 'manifest.json', manifest)
    old = manifest['heldModelArtifact']
    raw = _artifact_path(root, old['responseId']).read_bytes()
    require(_sha(raw) == old['sha256'], 'research_pool_completion_old_artifact_drift')
    with (archive / 'old-model-artifact.json').open('xb') as output:
        output.write(raw)
    return archive


def _set_receipt(runtime, value):
    with runtime.ledger._tx() as db:
        current = _db_value(db, KEY)
        if current is None:
            db.execute('INSERT INTO meta VALUES (?,?)', (KEY, canonical(value)))
        else:
            db.execute('UPDATE meta SET value=? WHERE key=?', (canonical(value), KEY))


def _terminal(runtime, receipt, status, reason):
    value = copy.deepcopy(receipt)
    value.update(status=status, result={'status': 'held', 'reason': reason,
                                       'period': PERIOD, 'retryable': False})
    _set_receipt(runtime, value)
    atomic(_archive(runtime.root) / 'receipt.json', value)
    return value['result']


def _strict_two(proposals, signal_ids):
    require(isinstance(proposals, list) and len(proposals) == 2,
            'research_pool_completion_exact_two_required')
    product = [item for item in proposals if item.get('productIds') == DOWN]
    nonproduct = [item for item in proposals if item.get('productIds') == []]
    require(len(product) == 1 and len(nonproduct) == 1
            and product[0].get('topicType') == 'product'
            and nonproduct[0].get('topicType') == 'knowhow'
            and all(item.get('categoryId') == 'wear' and item.get('proposedAction') == 'new'
                    and set(item.get('sourceIds', [])) <= signal_ids for item in proposals),
            'research_pool_completion_direction_mismatch')
    from search_demand import classify_topic
    product_text = ' '.join(str(product[0].get(key, '')) for key in ('title','query','readerQuestion'))
    product_facets = classify_topic(product_text)
    require('comparison' in product_facets['intents'] and 'down' in product_facets['garments']
            and re.search(r'プラズマ\s*1000|plasma\s*1000', product_text, re.I)
            and re.search(r'ライトアルパイン|light\s*alpine', product_text, re.I),
            'research_pool_completion_down_comparison_required')
    facets = classify_topic(' '.join(str(nonproduct[0].get(key, '')) for key in
                                     ('title', 'query', 'readerQuestion')))
    require({'hard_shell', 'soft_shell'} <= set(facets.get('garments', []))
            and 'comparison' in facets.get('intents', [])
            and {'public:montbell-softshell-roles', 'public:montbell-layering'} <=
                set(nonproduct[0].get('sourceIds', [])),
            'research_pool_completion_shell_direction_mismatch')
    return proposals


def execute(runtime, manifest, *, owner_grant, now=None):
    """Claim once, make one bounded planning call, then commit a normal pool."""
    now = now or datetime.now(JST)
    require(owner_grant == globals()['owner_grant'](manifest),
            'research_pool_completion_owner_grant_required')
    runtime._require_running()
    with (runtime.root / 'runtime.flock').open('a') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy', 'period': PERIOD}
        with runtime.ledger._tx() as db:
            prior = _db_value(db, KEY)
        if prior is not None:
            require(prior.get('manifestSha256') == fingerprint(manifest),
                    'research_pool_completion_manifest_changed')
            if prior.get('status') == 'completed':
                marker = prior['finalMarker']
                for name, digest in prior.get('committedArtifacts', {}).items():
                    require(_sha(_paths(runtime.root)[name].read_bytes()) == digest,
                            'research_pool_completion_completed_artifact_drift')
                path = _paths(runtime.root)['marker']
                if _sha(path.read_bytes()) == manifest['inputSha256']['marker']:
                    atomic(path, marker)
                require(json.loads(path.read_text()) == marker,
                        'research_pool_completion_completed_marker_drift')
                return copy.deepcopy(prior['result'])
            raise ValueError('research_pool_completion_requires_reconciliation')
        current = _state(runtime, manifest['inputSha256'], manifest['ownerInstruction'], now,
                         manifest.get('catalogCorrectionContext'))
        require(current == manifest and fingerprint(runtime.config) == manifest['runtimeConfigSha256'],
                'research_pool_completion_manifest_changed')
        require(owner_grant == globals()['owner_grant'](current),
                'research_pool_completion_owner_grant_required')
        archive = _archive_inputs(runtime.root, manifest)
        receipt = {'schemaVersion': VERSION, 'status': 'claimed', 'period': PERIOD,
                   'manifestSha256': fingerprint(manifest), 'ownerGrant': owner_grant,
                   'attemptsUsed': 1, 'maxAttempts': 1,
                   'ownerArticleApproval': False, 'ownerSNSApproval': False,
                   'publication': 'prohibited'}
        _set_receipt(runtime, receipt)
        atomic(archive / 'receipt.json', receipt)
        created = []
        try:
            require_fresh_daily_metrics(runtime.config, now=now)
            base = runtime._context()
            live = runtime.catalog.catalog()
            require(fingerprint(_catalog_projection(live)) == manifest['liveCatalogSha256'],
                    'research_pool_completion_catalog_drift')
            live = _candidate_catalog(live, manifest.get('catalogCorrectionContext'))
            base = copy.deepcopy(base)
            base['products'] = live['products']
            base['catalog'] = live['products']
            index = build_article_index(live['articles'])
            fresh_feed_path = archive / 'fresh-public-sources.json'
            feed = collect_primary_sources(runtime.catalog.request, period=PERIOD,
                                           output_path=fresh_feed_path, now=now)
            paid = _paid_context(runtime, base, live, feed, index, manifest)
            atomic(archive / 'paid-context.json', paid)
            evidence = {'catalogSha256': fingerprint(live['products']),
                        'articleIndexSha256': fingerprint(index),
                        'existingProjectionSha256': fingerprint(paid['existingArticles']),
                        'signalsSha256': fingerprint(paid['editorialSignals']),
                        'primaryFeedSha256': fingerprint(feed),
                        'paidContextSha256': fingerprint(paid)}
            receipt.update(status='evidence_ready', freshEvidence=evidence)
            _set_receipt(runtime, receipt)
            atomic(archive / 'receipt.json', receipt)
            result = runtime._measured_model_call('research:' + PERIOD, 'research',
                'claude-sonnet-4-6', lambda: runtime.models.research_mixed(paid))
            require(isinstance(result, dict) and set(result) == {'proposals'},
                    'research_pool_completion_partial_response_forbidden')
            new = _strict_two(result['proposals'], {item['id'] for item in paid['editorialSignals']})
            catalog_ids = {item['id'] for item in paid['catalog']}
            existing_ids = {item['id'] for item in paid['existingArticles']}
            pinned = validate_proposals([manifest['pinnedProposal']], catalog_ids=catalog_ids,
                existing_ids=existing_ids, category_ids={'wear'})[0]
            proposals = [pinned, *new]
            selection = select_proposals(proposals, signals=paid['editorialSignals'],
                existing=index, queued=base.get('queuedThemes', []), feed=feed, limit=3)
            atomic(archive / 'new-proposals.json', {'proposals': new})
            atomic(archive / 'selection-result.json', selection)
            if selection.get('status') != 'selected' or len(selection.get('selected', [])) != 3:
                return _terminal(runtime, receipt, 'held', 'insufficient_qualified_period_pool')
            themes = [bind_nonproduct_theme(item, feed) for item in selection['selected']]
            period_receipt = {'schemaVersion': 1, 'period': PERIOD, 'at': now.isoformat(),
                'selectionPolicy': 'relevant-search-demand-v2', 'status': 'selected',
                'holdReason': None, 'eligibleCount': 3, 'unfilled': 0,
                'proposalCount': 3, 'decisions': selection['decisions'],
                'selectedSlugs': [item['slug'] for item in themes],
                'sourceIds': [item['id'] for item in paid['editorialSignals']],
                'existingIndex': {'articleCount': len(index), 'fingerprint': fingerprint(index),
                                  'modelProjection': 'all_identity_related_headings_max8'},
                'completion': {'key': KEY, 'manifestSha256': fingerprint(manifest),
                               'freshEvidence': evidence}}
            update = {'schemaVersion': 1, 'period': PERIOD, 'private': True,
                      'selectionPolicy': 'relevant-search-demand-v2',
                      'status': 'no_update_proposals', 'publication': 'prohibited', 'proposals': []}
            marker = {'status': 'generated', 'period': PERIOD, 'themes': themes,
                      'proposals': proposals, 'selection': 'selected', 'holdReason': None,
                      'eligibleCount': 3, 'unfilled': 0, 'at': now.isoformat(),
                      'researchContextSha256': fingerprint(paid),
                      'researchPoolCompletionKey': KEY,
                      'manifestSha256': fingerprint(manifest)}
            atomic(_paths(runtime.root)['period_receipt'], period_receipt)
            atomic(_paths(runtime.root)['update_proposal'], update)
            atomic(_paths(runtime.root)['context'], paid)
            atomic(_paths(runtime.root)['public_feed'], feed)
            completed = copy.deepcopy(receipt)
            corrections = {}
            if manifest.get('catalogCorrectionContext'):
                down = next(item for item in themes if item.get('productIds') == DOWN)
                corrections[down['slug']] = manifest['catalogCorrectionContext']
            created = backfill(runtime.ledger, PERIOD, themes, now, catalog_corrections=corrections)
            completed.update(status='completed', finalMarker=marker,
                committedArtifacts={name: _sha(path.read_bytes()) for name, path in _paths(runtime.root).items()
                                    if name != 'marker'},
                result={'status': 'ready_for_normal_producer', 'period': PERIOD,
                        'selectedSlugs': period_receipt['selectedSlugs'],
                        'createdJobIds': [job['id'] for job in created],
                        'demandLimitations': 'see selected decisions for controlled-facet query-group versus related-page-proxy basis; exact product-pair demand, market demand and trends are unverified',
                        'ownerArticleApproval': False, 'ownerSNSApproval': False})
            _set_receipt(runtime, completed)
            atomic(archive / 'receipt.json', completed)
            atomic(_paths(runtime.root)['marker'], marker)  # commit point for normal producer
            return copy.deepcopy(completed['result'])
        except ModelOutcomeUnknown:
            _terminal(runtime, receipt, 'unknown', 'model_outcome_unknown')
            raise
        except BudgetHold:
            return _terminal(runtime, receipt, 'held', 'model_budget_hold')
        except Exception as error:
            for job in created:
                runtime.ledger.set_stage(job['id'], 'held', {
                    'reason': 'research_pool_completion_requires_reconciliation',
                    'at': now.isoformat()})
            code = str(error)
            _terminal(runtime, receipt, 'held', code if re.fullmatch(
                r'research_pool_completion_[a-z0-9_]{1,140}', code) else type(error).__name__)
            raise
        finally:
            runtime._save_usage()
