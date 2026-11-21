"""Verified source enrichment for an existing untouched job; no model execution.

Registry/receipt validation is reusable. The current apply policy is closed to the
Thermos pilot. A receipt is an operator handoff, never owner/publication approval.
"""
import copy
from datetime import datetime
import re

from topic_selection import (JST, _aware, _canonical, _sha, reverify_bound_public_sources,
                             validate_nonproduct_contract)


PILOT_JOB_ID = 'article-98d3334c7e9afbfb222c19b1'
PILOT_SLUG = 'thermos-bottle-compatible-parts-search-guide'
EDITABLE = {'sourceIds', 'nonProductContract', 'outline', 'selectionReason'}
VERSION = 1


class SourceEnrichmentError(ValueError):
    pass


def _need(value, reason):
    if not value:
        raise SourceEnrichmentError(reason)


def _hash(value):
    return _sha(_canonical(value))


def _eligible(job):
    _need(isinstance(job, dict) and job.get('id') == PILOT_JOB_ID,
          'source_enrichment_pilot_job_required')
    theme = job.get('theme')
    _need(isinstance(theme, dict) and theme.get('slug') == PILOT_SLUG and
          theme.get('categoryId') == 'tumbler' and theme.get('productIds') == [] and
          isinstance(job.get('week'), str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', job['week']),
          'source_enrichment_identity_required')
    _need(job.get('kind') != 'article_revision' and job.get('stage') in ('candidate', 'error', 'held') and
          all(job.get(k) is None for k in
              ('bundle', 'revision', 'review', 'astraReview', 'approval', 'publication', 'social')),
          'source_enrichment_untouched_job_required')
    validate_nonproduct_contract(theme)


def _transition(job, proposed):
    _eligible(job)
    _need(isinstance(proposed, dict), 'source_enrichment_theme_required')
    old = job['theme']
    _need({k: v for k, v in old.items() if k not in EDITABLE} ==
          {k: v for k, v in proposed.items() if k not in EDITABLE},
          'source_enrichment_fixed_theme_changed')
    validate_nonproduct_contract(proposed)
    _need(isinstance(proposed.get('selectionReason'), str) and
          1 <= len(proposed['selectionReason'].strip()) <= 500 and
          isinstance(proposed.get('outline'), list) and 3 <= len(proposed['outline']) <= 5 and
          all(isinstance(t, str) and t.strip() and len(t) <= 40 for t in proposed['outline']),
          'source_enrichment_outline_or_reason_invalid')
    _need([i for i in old['sourceIds'] if not i.startswith('public:')] ==
          [i for i in proposed['sourceIds'] if not i.startswith('public:')],
          'source_enrichment_nonpublic_sources_changed')
    before = old['nonProductContract']['references']
    after = proposed['nonProductContract']['references']
    by_id = {r['id']: r for r in after}
    _need(all(r['id'] in by_id for r in before), 'source_enrichment_old_source_dropped')
    mutable = {'excerpt', 'excerptSha256', 'receiptSha256', 'checkedAt'}
    for ref in before:
        updated = by_id[ref['id']]
        _need({k: v for k, v in ref.items() if k not in mutable} ==
              {k: v for k, v in updated.items() if k not in mutable},
              'source_enrichment_old_source_identity_changed')
        parts = updated['excerpt'].split('\n\n')
        cursor = 0
        for part in ref['excerpt'].split('\n\n'):
            try:
                cursor = parts.index(part, cursor) + 1
            except ValueError:
                raise SourceEnrichmentError('source_enrichment_old_excerpt_changed') from None
    _need(before != after, 'source_enrichment_sources_unchanged')


def prepare(job, proposed_theme, request, *, now=None):
    """Validate the transition and re-fetch every proposed exact public HTML URL.

    `request` is the caller's hardened public HTTP reader (or an offline fixture).
    This does not write the ledger, reserve budget, or initiate model work.
    """
    job, proposed = copy.deepcopy((job, proposed_theme))
    _transition(job, proposed)
    at = _aware(now) if now is not None else datetime.now(JST)
    _need(at is not None, 'source_enrichment_aware_time_required')
    at = at.astimezone(JST)
    recheck = reverify_bound_public_sources(
        request, proposed['nonProductContract']['references'], now=at)
    value = {'schemaVersion': VERSION, 'kind': 'verified_source_enrichment',
             'jobId': job['id'], 'week': job['week'], 'expectedJobHash': _hash(job),
             'expectedThemeHash': _hash(job['theme']), 'previousTheme': job['theme'],
             'proposedTheme': proposed, 'preparedAt': at.isoformat(), 'sourceRecheck': recheck}
    value['receiptSha256'] = _hash(value)
    validate(job, value)
    return value


def validate(job, receipt):
    """Offline CAS + complete receipt checks; no trust in a plain verified flag."""
    fields = {'schemaVersion', 'kind', 'jobId', 'week', 'expectedJobHash', 'expectedThemeHash',
              'previousTheme', 'proposedTheme', 'preparedAt', 'sourceRecheck', 'receiptSha256'}
    _need(isinstance(receipt, dict) and set(receipt) == fields and
          type(receipt['schemaVersion']) is int and receipt['schemaVersion'] == VERSION and
          receipt['kind'] == 'verified_source_enrichment', 'source_enrichment_receipt_invalid')
    _eligible(job)
    _need(receipt['jobId'] == job['id'] and receipt['week'] == job['week'] and
          receipt['expectedJobHash'] == _hash(job) and
          receipt['expectedThemeHash'] == _hash(job['theme']) and
          receipt['previousTheme'] == job['theme'], 'source_enrichment_cas_conflict')
    _need(receipt['receiptSha256'] == _hash({k: v for k, v in receipt.items() if k != 'receiptSha256'}),
          'source_enrichment_receipt_hash_mismatch')
    _transition(job, receipt['proposedTheme'])
    at = _aware(receipt['preparedAt'])
    check = receipt['sourceRecheck']
    _need(at is not None and isinstance(check, dict) and
          set(check) == {'schemaVersion', 'status', 'checkedAt', 'observations'} and
          type(check['schemaVersion']) is int and check['schemaVersion'] == 1 and check['status'] == 'verified' and
          check['checkedAt'] == receipt['preparedAt'] and isinstance(check['observations'], list),
          'source_enrichment_fresh_recheck_required')
    refs = receipt['proposedTheme']['nonProductContract']['references']
    _need(len(check['observations']) == len(refs), 'source_enrichment_recheck_incomplete')
    for ref, observation in zip(refs, check['observations']):
        _need(isinstance(observation, dict) and set(observation) ==
              {'sourceId', 'url', 'checkedAt', 'httpStatus', 'boundExcerptSha256', 'responseSha256'} and
              observation['sourceId'] == ref['id'] and observation['url'] == ref['url'] and
              observation['checkedAt'] == receipt['preparedAt'] and
              type(observation['httpStatus']) is int and observation['httpStatus'] == 200 and
              observation['boundExcerptSha256'] == ref['excerptSha256'] and
              isinstance(observation['responseSha256'], str) and
              re.fullmatch(r'[a-f0-9]{64}', observation['responseSha256']) and
              _aware(ref['checkedAt']) <= at, 'source_enrichment_recheck_mismatch')
    return copy.deepcopy(receipt)


def apply(ledger, job_id, receipt):
    """Transaction-only operator handoff. No generation or automatic production."""
    _need(job_id == PILOT_JOB_ID, 'source_enrichment_pilot_job_required')
    receipt = copy.deepcopy(receipt)
    with ledger._tx() as db:
        job = ledger._get(db, job_id)
        checked = validate(job, receipt)
        _need(not db.execute('SELECT 1 FROM requests WHERE job_id=?', (job_id,)).fetchone() and
              not db.execute('SELECT 1 FROM effects WHERE job_id=?', (job_id,)).fetchone(),
              'source_enrichment_side_effects_require_reconciliation')
        history = job.get('sourceEnrichments', [])
        _need(isinstance(history, list), 'source_enrichment_history_invalid')
        job['sourceEnrichments'] = copy.deepcopy(history) + [checked]
        job['theme'] = copy.deepcopy(checked['proposedTheme'])
        job.update(stage='held', holdReason='source_enrichment_ready', error=None)
        return ledger._put(db, job, 'source_enriched')
