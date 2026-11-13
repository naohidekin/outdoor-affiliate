"""Operator-only, fixed-body display suppression review. No ledger write or delivery.

Caller holds the runtime lock and uses the ledger's guarded suppression API only
AFTER this function succeeds. Returned review is fresh, never an owner approval.
"""
import copy
import hashlib
import json
from pathlib import Path
from ledger import canonical, fingerprint, require
from catalog_corrections import validate_context, validate_bundle, validate_live_context
from quality import inspect_bundle, inspect_polish


def validate_fixed_candidate(job, candidate):
    require(candidate.get('articleId') == job['id'] and candidate.get('expectedRevision') == job['revision']
            and fingerprint(job['bundle']) == job['revision'], 'fixed candidate revision mismatch')
    require(not job.get('publication') and not job.get('approval'), 'fixed candidate already authorized')
    from ledger import validate_display_suppression
    new = candidate['bundle']
    require(candidate.get('candidateRevision') == fingerprint(new), 'fixed candidate fingerprint mismatch')
    context = validate_display_suppression(job['bundle'], new)
    bound = copy.deepcopy(job); bound['catalogCorrectionContext'] = context
    validate_bundle(bound, new)
    return bound


def _private_file(root, path, area):
    path = Path(path).resolve(); base = (Path(root) / area).resolve()
    require(base in path.parents and path.is_file(), 'private evidence path rejected')
    return path


def verify_polish_reuse(root, job, evidence, bundle):
    content = bundle['article']['content']
    require(content == job['bundle']['article']['content'], 'polish body changed')
    if isinstance(evidence, dict):
        # Historical qualified repair recorded the exact final bundle and result,
        # rather than a separate candidate.json. Operator pins the reviewed script.
        final_path = _private_file(root, evidence['finalRecord'], 'repair')
        result_path = _private_file(root, evidence['resultRecord'], 'repair')
        script_path = _private_file(root, evidence['script'], 'repair')
        script_hash = hashlib.sha256(script_path.read_bytes()).hexdigest()
        require(script_hash == evidence.get('expectedScriptSha256'), 'polish repair script changed')
        final, result = json.loads(final_path.read_text()), json.loads(result_path.read_text())
        require(final['id'] == job['id'] and final['revision'] == job['revision'] == fingerprint(final['bundle'])
                and canonical(final['bundle']) == canonical(job['bundle']), 'polish final record mismatch')
        require(result.get('status') == 'awaiting_astra_review' and result.get('revision') == job['revision']
                and result.get('published') is False and result.get('bodyCharacters') == len(content),
                'polish repair result mismatch')
        polish = final.get('review', {}).get('polish', {})
        require(final.get('review', {}).get('fingerprint') == job['revision'] and polish.get('validated') is True
                and polish.get('model') == 'gemini-3.8-flash', 'polish record missing')
        artifacts = [str(final_path), str(result_path), str(script_path)]
    else:
        directory = Path(evidence).resolve()
        expected = (Path(root) / 'research' / 'artifacts' / job['id']).resolve()
        require(directory.parent == expected, 'polish artifact directory rejected')
        source = json.loads((directory / 'source.json').read_text())
        candidate = json.loads((directory / 'candidate.json').read_text())
        require(source.get('kind') == 'source' and fingerprint(source['bundle']) == directory.name
                and candidate.get('kind') == 'candidate', 'polish artifact binding changed')
        polished = candidate['candidate']
        require(polished.get('model') == 'gemini-3.8-flash' and polished.get('content') == content,
                'polish output mismatch')
        require(inspect_polish(source['bundle']['article']['content'], content).get('passed') is True,
                'polish preservation failed')
        artifacts = [str(directory / 'source.json'), str(directory / 'candidate.json')]
    return {'model': 'gemini-3.8-flash', 'validated': True, 'reused': True,
            'newModelCall': False, 'contentSha256': hashlib.sha256(content.encode()).hexdigest(),
            'artifacts': artifacts, 'scope': 'same-body prior polish only; no quality-review reuse'}


def prepare_fixed_price_review(runtime, id, candidate_path, polish_evidence, live_context):
    """Fresh bounded checks, one polish and one review; NO writer/ledger mutation.

    Caller must invoke only with approved model budget. Tests use injected fakes.
    Any failure leaves the live job untouched. Fresh polish artifacts and usage
    are saved privately. polish_evidence is retained for caller compatibility but
    is never accepted as production proof. Caller must hold runtime.flock.
    """
    candidate = json.loads(Path(candidate_path).read_text())
    job = runtime.ledger.get_job(id)
    bound = validate_fixed_candidate(job, candidate)
    bundle = copy.deepcopy(candidate['bundle'])
    context = copy.deepcopy(live_context)
    validate_live_context(bound['catalogCorrectionContext'], context['products'])
    by_id = {p['id']: p for p in bundle['products']}
    context['products'] = [copy.deepcopy(by_id.get(p['id'], p)) for p in context['products']]
    context['catalog'] = copy.deepcopy(context['products'])
    gathered = runtime.catalog.gather(job['theme'], context)
    require(all(gathered.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate')),
            'fresh source verification failed')
    for image in bundle['images']:
        if image.get('role') == 'social-card':
            proof = runtime.catalog.image_digest(image['url'])
            require(all(proof.get(k) == image.get(k) for k in ('sha256', 'size', 'contentType')),
                    'social image changed')
        else:
            require(any(p.get('verified') is True and all(p.get(k) == image.get(k)
                        for k in ('productId', 'url', 'sha256', 'size', 'contentType'))
                        for p in gathered.get('images', [])), 'fresh image binding mismatch')
    # Production deliberately never accepts historical polish as fresh evidence.
    # One normal provider call; preserve its actual output even when rejected.
    from runtime import atomic
    source_content = bundle['article']['content']
    artifact_dir = Path(runtime.root) / 'fixed-display-reviews' / id / fingerprint(bundle)
    require(not (artifact_dir / 'polish-intent.json').exists(), 'fresh polish already attempted; reconcile without retry')
    atomic(artifact_dir / 'polish-intent.json', {'status':'started', 'expectedRevision':job['revision'],
        'candidateRevision':fingerprint(bundle),'contentSha256':hashlib.sha256(source_content.encode()).hexdigest()})
    atomic(artifact_dir / 'polish-source.json', {'content':source_content,'brief':bundle['brief']})
    try:
        polished = runtime.models.polish(source_content, bundle['brief'])
        atomic(artifact_dir / 'polish-output.json', polished)
    finally:
        runtime._save_usage()
    require(polished.get('model') == 'gemini-3.8-flash' and polished.get('content') == source_content,
            'fresh polish changed fixed body; stop without adopting or retrying')
    preservation = inspect_polish(source_content, polished['content'])
    require(preservation.get('passed') is True, 'fresh polish preservation failed')
    polish = {'model':polished['model'],'validated':True,'reused':False,'newModelCall':True,
        'contentSha256':hashlib.sha256(source_content.encode()).hexdigest(),
        'usage':copy.deepcopy(polished.get('usage', {})),
        'artifacts':[str(artifact_dir / 'polish-source.json'),str(artifact_dir / 'polish-output.json')]}
    atomic(artifact_dir / 'polish-proof.json', polish)
    public = {k:v for k,v in bundle.items() if k not in ('catalogCorrectionContext','revisionContext')}
    structural = inspect_bundle(public)
    require(structural.get('passed') is True, 'fixed structure failed')
    preview = runtime.renderer(bundle, bound)
    clicks = preview.get('clicksVerified', {})
    require(preview.get('passed') is True and isinstance(clicks, dict)
            and bool(clicks.get('desktop')) and bool(clicks.get('mobile')), 'fresh render failed')
    medical = runtime._medical(bundle['article'])
    require(medical.get('passed') is True, 'fresh medical failed')
    flags = {k: True for k in ('facts','images','affiliate','render','medical')}
    approved_theme = copy.deepcopy(job['theme'])
    if isinstance(approved_theme.get('selectionReason'), str):
        approved_theme['selectionReason'] = approved_theme['selectionReason'].split(' EDITORIAL RECOVERY REQUIREMENTS')[0]
    try:
        review = runtime.models.review(public, {'evidence':flags,'structural':structural,
            'source':gathered.get('evidence', {}),'approvedTheme':approved_theme,'preview':preview,
            'polishPreservation':dict(preservation, freshExactBody=True, contentSha256=polish['contentSha256']),
            'editorialRules':context['editorialRules'],'medical':medical,
            'sourceContent':job['bundle']['article']['content']})
    finally:
        runtime._save_usage()
    require(review.get('passed') is True, 'fresh final review failed')
    require(runtime.ledger.get_job(id)['revision'] == job['revision'], 'fixed revision changed during review')
    review = dict(review, fingerprint=fingerprint(bundle), evidence=flags, polish=polish)
    return {'expectedRevision':job['revision'],'bundle':bundle,'review':review,
            'gathered':gathered,'preview':preview,'medical':medical,'polishProof':polish,
            'requiresIndependentReview':True,'requiresOwnerApproval':True,'applied':False}
