"""One-shot, read-only Astra semantic QA for corrected article revisions.

The caller holds ``runtime.flock``.  This adapter neither acquires a second
runtime lock nor grants owner approval.  It sends only an allow-listed public
projection through the host-pinned manager CLI transport.
"""
import copy
import json

from ledger import fingerprint, valid_astra_review, valid_review
import manager_cli
from model_budget import BudgetHold
from stage_journal import StageBlocked, StageUnknown
from wise_contract import require_current_review


STAGE = 'independent_review'
MODEL = 'gpt-6-astra'
TIMEOUT_SECONDS = 180
# The managed CLI cannot enforce a smaller generation-token limit.  Reserve the
# established conservative per-call bound instead of pretending 2,048 is hard.
RESERVED_OUTPUT_TOKENS = 16384
MAX_SNAPSHOT_BYTES = 131072

_ARTICLE_FIELDS = (
    'id', 'slug', 'title', 'content', 'excerpt', 'metaDescription', 'faqs',
    'tags', 'categoryId', 'productIds', 'status', 'publishedAt',
)
_BRIEF_FIELDS = (
    'purpose', 'reader', 'conclusion', 'headings', 'facts', 'numbers',
    'links', 'requiredExpressions', 'protected', 'style', 'length', 'cta',
    'format', 'externalSafe',
)
_PRODUCT_FIELDS = (
    'id', 'name', 'brand', 'description', 'specs', 'imageUrl', 'affiliateUrl',
    'amazonUrl', 'yahooUrl', 'price', 'rating', 'availability', 'categoryId',
)
_IMAGE_FIELDS = (
    'id', 'url', 'imageUrl', 'imageURL', 'finalUrl', 'role', 'productId',
    'alt', 'sha256', 'size', 'contentType', 'width', 'height', 'verified',
    'identitySource', 'apparelBinding',
)
_REFERENCE_FIELDS = (
    'id', 'kind', 'url', 'sourceUrl', 'title', 'claim', 'claims', 'text',
    'excerpt', 'conditions', 'scope', 'field', 'channel', 'model', 'productId',
    'excerptSHA256', 'sha256', 'size', 'contentType', 'verified', 'checkedAt',
    'apparelBinding',
)
_PURCHASE_FIELDS = (
    'productId', 'channel', 'status', 'reason', 'url', 'reviewedBy', 'checkedAt',
)
_QUALITY_FLAGS = ('facts', 'images', 'affiliate', 'medical', 'render')
_APPAREL_FIELDS = (
    'brand', 'class', 'colors', 'fabric', 'gender', 'imageUrls',
    'merchantChannel', 'merchantColor', 'merchantOptionState', 'merchantSize',
    'merchantVariant', 'model', 'optionState', 'sizes', 'sourceKind', 'weight',
)


class _StaleReview(ValueError):
    pass


def _project(value, fields):
    if not isinstance(value, dict):
        return {}
    return {key: copy.deepcopy(value[key]) for key in fields if key in value}


def _source_project(value, fields):
    result = _project(value, fields)
    if 'apparelBinding' in result:
        result['apparelBinding'] = _project(result['apparelBinding'], _APPAREL_FIELDS)
    return result


def _purchase_evidence(value):
    if isinstance(value, list):
        return [_project(item, _PURCHASE_FIELDS) for item in value
                if isinstance(item, dict)]
    if isinstance(value, dict):
        result = _project(value, _PURCHASE_FIELDS)
        for key in ('items', 'evidence', 'records'):
            if isinstance(value.get(key), list):
                result[key] = [_project(item, _PURCHASE_FIELDS)
                               for item in value[key] if isinstance(item, dict)]
        return result
    return []


def _public_snapshot(job):
    bundle = job['bundle']
    review = job['review']
    source_flags = review.get('evidence') if isinstance(review.get('evidence'), dict) else {}
    source_flags = {key: copy.deepcopy(source_flags.get(key)) for key in _QUALITY_FLAGS}
    if any(value is False or value is None for value in source_flags.values()):
        raise ValueError('independent_review_quality_flags_incomplete')

    # A routine revision carries a compact, already-verified source receipt in
    # its private context.  Export only its booleans, never the context/base.
    context = job.get('revisionContext')
    binding = context.get('analysisBinding') if isinstance(context, dict) else None
    proof = binding.get('sourceProof') if isinstance(binding, dict) else None
    actual_source_flags = proof.get('checks') if isinstance(proof, dict) else None
    if not isinstance(actual_source_flags, dict):
        actual_source_flags = {key: source_flags.get(key) for key in ('facts', 'images', 'affiliate')}
    else:
        actual_source_flags = {
            key: copy.deepcopy(actual_source_flags.get(key))
            for key in ('facts', 'images', 'affiliate')
        }

    snapshot = {
        'reviewKind': 'independent_corrected_article_semantic_qa_v1',
        'articleId': job['id'],
        'revision': job['revision'],
        'bundleHash': fingerprint(bundle),
        'publicBundle': {
            'article': _project(bundle.get('article'), _ARTICLE_FIELDS),
            'brief': _project(bundle.get('brief'), _BRIEF_FIELDS),
            'products': [_project(item, _PRODUCT_FIELDS)
                         for item in bundle.get('products', []) if isinstance(item, dict)],
            'images': [_source_project(item, _IMAGE_FIELDS)
                       for item in bundle.get('images', []) if isinstance(item, dict)],
            'references': [_source_project(item, _REFERENCE_FIELDS)
                           for item in bundle.get('references', []) if isinstance(item, dict)],
            'purchaseEvidence': _purchase_evidence(bundle.get('purchaseEvidence')),
        },
        'checks': {
            'originalQualityFlags': source_flags,
            'actualSourceFlags': actual_source_flags,
            'originalReviewFingerprint': review.get('fingerprint'),
            'originalReviewPassed': review.get('passed') is True,
        },
    }
    references = snapshot['publicBundle']['references']
    if (not references or any(not isinstance(item.get('url'), str)
            or not item['url'].strip() or not isinstance(item.get('text'), str)
            or not item['text'].strip() for item in references)):
        raise ValueError('independent_review_source_claim_evidence_incomplete')
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError('independent_review_input_too_large')
    return snapshot


def _schema():
    text = {'type': 'string', 'minLength': 1, 'maxLength': 500}
    issue = {
        'type': 'object',
        'properties': {
            'code': {'type': 'string', 'enum': [
                'factual_source_mismatch', 'unsupported_claim',
                'item_variant_mismatch', 'link_evidence_mismatch',
                'image_evidence_mismatch', 'quality_regression',
                'insufficient_evidence',
            ]},
            'location': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'detail': text,
        },
        'required': ['code', 'location', 'detail'],
        'additionalProperties': False,
    }
    action = {
        'type': 'object',
        'properties': {
            'action': {'type': 'string', 'const': 'quality_review'},
            'jobId': {'type': 'string', 'minLength': 1, 'maxLength': 160},
            'revision': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
            'passed': {'type': 'boolean'},
            'issues': {'type': 'array', 'items': issue, 'maxItems': 12},
        },
        'required': ['action', 'jobId', 'revision', 'passed', 'issues'],
        'additionalProperties': False,
    }
    return {
        'type': 'object',
        'properties': {
            'stateFingerprint': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
            'summary': {'type': 'string', 'maxLength': 500},
            'actions': {'type': 'array', 'items': action, 'minItems': 1, 'maxItems': 1},
        },
        'required': ['stateFingerprint', 'summary', 'actions'],
        'additionalProperties': False,
    }


PROMPT = """Perform one independent, read-only semantic QA of the supplied corrected article.
Use only the supplied public bundle, source brief, evidence, and checks. Do not use tools,
browse, rewrite, edit, suggest replacement prose, or infer missing evidence. Check every
factual claim against its source support and check item/model/variant identity, destination
links, and image evidence for consistency. All original quality flags remain mandatory;
never replace or weaken them. A pass requires specific passing evidence for all five check
categories and no issue. Unknown or insufficient evidence is not a pass. This review can
never grant, imply, request, or record owner approval, publication approval, or permission
to publish. Return exactly one quality_review action in the required schema. Set jobId and
revision to the supplied exact values. Record every mismatch as a bounded issue."""


def _configuration(runtime):
    if runtime.config.get('independentReviewEnabled') is not True:
        return None
    manager = runtime.config.get('editorialManager')
    command = manager.get('command') if isinstance(manager, dict) else None
    if (not isinstance(command, list) or not command
            or not all(isinstance(part, str) and part for part in command)):
        raise ValueError('independent_review_unconfigured')
    return command


def _eligible(runtime, job):
    if not isinstance(job, dict) or not isinstance(job.get('id'), str):
        raise ValueError('independent_review_job_required')
    current = runtime.ledger.get_job(job['id'])
    if not isinstance(job.get('revision'), str) or job['revision'] != current.get('revision'):
        raise _StaleReview('independent_review_expected_revision_changed')
    if (current.get('stage') != 'review'
            or not (current.get('kind') == 'article_revision'
                    or 'catalogCorrectionContext' in current)
            or current.get('approval') or current.get('publication')):
        raise ValueError('independent_review_not_eligible')
    bundle, revision = current.get('bundle'), current.get('revision')
    if not isinstance(bundle, dict) or fingerprint(bundle) != revision:
        raise _StaleReview('independent_review_revision_mismatch')
    valid_review(current.get('review'), revision, bundle)
    require_current_review(bundle, current.get('review'), runtime.config.get('repo'))
    return current


def _decision_receipt(response, job_id, revision):
    decision = response.get('decision') if isinstance(response, dict) else None
    actions = decision.get('actions') if isinstance(decision, dict) else None
    action = actions[0] if isinstance(actions, list) and len(actions) == 1 else None
    if not isinstance(action, dict):
        raise ValueError('independent_review_response_invalid')
    passed = (action.get('action') == 'quality_review'
              and action.get('jobId') == job_id
              and action.get('revision') == revision
              and action.get('passed') is True and action.get('issues') == [])
    return {
        'kind': 'independent_article_review_v1',
        'fingerprint': revision,
        'passed': passed,
        'issues': copy.deepcopy(action.get('issues', [])),
        'requestedModel': response.get('requestedModel', MODEL),
        'actualModel': response.get('actualModel'),
        'usage': copy.deepcopy(response.get('usage')),
        'actualInvoiceUsd': None,
        'outputCapEnforced': False,
        'reservedOutputTokens': RESERVED_OUTPUT_TOKENS,
    }


def _usage_record(receipt):
    return [{
        'requestedModel': receipt.get('requestedModel'),
        'actualModel': receipt.get('actualModel'),
        'usage': copy.deepcopy(receipt.get('usage')),
        'actualInvoiceUsd': receipt.get('actualInvoiceUsd'),
    }]


def ensure_review(runtime, job):
    """Ensure one exact-revision Astra QA and return a non-throwing status.

    Configuration, eligibility, budget, transport, refusal, stale-revision and
    known semantic failures are all represented as statuses.  No automatic retry
    path exists: the exact journal record has ``maxAttempts=1``.
    """
    provider_called = False
    try:
        command = _configuration(runtime)
        if command is None:
            return {'status': 'disabled'}
        current = _eligible(runtime, job)
        try:
            valid_astra_review(current.get('astraReview'), current['revision'])
        except ValueError:
            pass
        else:
            return {'status': 'passed', 'cached': True,
                    'revision': current['revision'], 'called': False}

        snapshot = _public_snapshot(current)
        inputs = {
            'reviewKind': snapshot['reviewKind'],
            'revision': current['revision'],
            'bundleHash': snapshot['bundleHash'],
            # One journal identity per exact bundle revision.  Review metadata
            # changing around the same immutable bundle must not buy a new call.
            'dependencies': {'exactRevision': current['revision']},
            'schemaVersion': {'stage': 1, 'input': 'sanitized-public-review-v1',
                              'output': 'independent-review-receipt-v1'},
        }
        stage_key = runtime.stage_journal.key(current['id'], STAGE, inputs)
        usage_records = None

        def operation():
            nonlocal provider_called, usage_records
            with runtime.model_budget.scope(runtime._budget_article_id(current['id']), STAGE):
                try:
                    reservation = runtime.model_budget.reserve({
                        'model': MODEL,
                        'max_tokens': RESERVED_OUTPUT_TOKENS,
                        'messages': [{'role': 'user', 'content': json.dumps(
                            {'snapshot': snapshot, 'instructions': PROMPT},
                            ensure_ascii=False, sort_keys=True, separators=(',', ':'))}],
                    }, model=MODEL)
                except BudgetHold as error:
                    return {
                        'kind': 'independent_article_review_v1',
                        'fingerprint': current['revision'],
                        'status': 'budget_hold',
                        'passed': False,
                        'issues': [],
                        'reason': error.reason_code,
                        'requestedModel': MODEL,
                        'actualModel': None,
                        'usage': None,
                        'actualInvoiceUsd': None,
                        'outputCapEnforced': False,
                        'reservedOutputTokens': RESERVED_OUTPUT_TOKENS,
                    }
                provider_called = True
                try:
                    response = manager_cli.call(command, snapshot, PROMPT, _schema(),
                                                timeout=TIMEOUT_SECONDS)
                    receipt = _decision_receipt(response, current['id'], current['revision'])
                    usage_records = _usage_record(receipt)
                    usage = response.get('usage') if isinstance(response, dict) else None
                    if not isinstance(usage, dict):
                        raise ValueError('independent_review_usage_missing')
                except Exception as error:
                    runtime.model_budget.settle(reservation, outcome='unknown')
                    unknown = StageUnknown('independent review outcome unknown',
                                           stage_key=stage_key)
                    unknown.__cause__ = error
                    raise unknown
                runtime.model_budget.settle(reservation, usage=usage, outcome='success')
                return receipt

        try:
            receipt = runtime.stage_journal.run(current['id'], STAGE, inputs,
                                                operation, max_attempts=1)
        finally:
            if provider_called:
                runtime.stage_journal.record_usage(
                    current['id'], STAGE, stage_key,
                    usage_records if usage_records is not None else [], reason='initial')
                flush = getattr(runtime, '_flush_budget_notifications', None)
                if callable(flush):
                    flush()

        if receipt.get('passed') is not True:
            if receipt.get('status') == 'budget_hold':
                return {'status': 'budget_hold', 'reason': receipt.get('reason'),
                        'called': False, 'outputCapEnforced': False}
            return {'status': 'failed', 'revision': current['revision'],
                    'issues': copy.deepcopy(receipt.get('issues', [])),
                    'called': provider_called, 'outputCapEnforced': False}

        latest = runtime.ledger.get_job(current['id'])
        if (latest.get('revision') != current['revision']
                or fingerprint(latest.get('bundle')) != current['revision']):
            return {'status': 'stale', 'revision': current['revision'],
                    'called': provider_called}
        review = {
            'passed': True,
            'issues': [],
            'reviewedBy': 'Astra',
            'fingerprint': current['revision'],
            'evidence': {'independentReview': receipt},
        }
        saved = runtime.ledger.record_astra_review(current['id'], current['revision'], review)
        return {'status': 'passed', 'cached': not provider_called,
                'revision': current['revision'], 'called': provider_called,
                'outputCapEnforced': False,
                'recorded': saved.get('astraReview') is not None}
    except BudgetHold as error:
        return {'status': 'budget_hold', 'reason': error.reason_code, 'called': False}
    except StageBlocked as error:
        return {'status': 'failed', 'reason': 'attempt_exhausted',
                'stageStatus': error.status, 'called': False}
    except StageUnknown as error:
        return {'status': 'unknown', 'reason': 'reconciliation_required',
                'stageStatus': error.status, 'called': provider_called}
    except _StaleReview:
        return {'status': 'stale', 'reason': 'expected_revision_changed',
                'called': False}
    except (KeyError, TypeError, ValueError):
        return {'status': 'blocked', 'reason': 'invalid_or_stale_review_state',
                'called': False}
