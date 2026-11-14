"""Owner-invoked review work while the normal editorial runtime stays suspended."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

from runtime import Runtime
from ledger import JST, fingerprint, timestamp


ALLOWED_BASE_ARTICLE_IDS = frozenset({'article-005', 'article-024'})
ALLOWED_SOCIAL_JOB_IDS = frozenset({
    'article-8baa356ebcdfb7a27ae7235f',
    'article-a3aecafc99811088f6d1e98c',
})
DISABLED_CONFIG_FLAGS = (
    'generationEnabled',
    'publicationEnabled',
    'catalogCorrectionsPublicationEnabled',
    'postPublicationAuditEnabled',
    'indexTrackingEnabled',
    'socialPostingEnabled',
    'reportsEnabled',
)
REVIEW_SUPPLEMENT = {
    'url': 'https://snowpeak-ec.s3.amazonaws.com/sys-master/AmazonS3Images/hd3/h39/'
           '8879616065566/ST-032RS_manual.pdf',
    'model': 'ST-032RS',
    'productId': 'fp-003',
    'sha256': '27b1c4c6f9bda381548f5bc269417748c005827816913bc8564dd55dfda4c5cb',
    'size': 191121,
    'contentType': 'application/pdf',
    'reviewedBy': 'Astra',
}
REVIEW_SUPPLEMENT_CLAIMS = (
    '本製品は屋外専用となっております。屋内やテントの中、車中など密ぺいされた場所や狭い空間では絶対に使用しないでください。',
    '片付けの際は本体が冷めていることを確認のうえ行ってください。',
    '緊急時以外は本体に水をかけるなどの温度変化を与えないでください。変形・破損などの原因となります。',
)


def _reject_publisher(*_args, **_kwargs):
    raise ValueError('manual_review_publisher_forbidden')


def _require_manual_config(config):
    policy = config.get('executionPolicy')
    manager = config.get('editorialManager')
    if (not isinstance(policy, dict) or policy.get('suspended') is not True
            or any(config.get(field) is not False for field in DISABLED_CONFIG_FLAGS)
            or config.get('socialCardsEnabled') is not True
            or config.get('telegramEnabled', False) is not False
            or not isinstance(manager, dict) or manager.get('enabled') is not False):
        raise ValueError('manual_review_requires_suspended_unpublished_config')


class _ScopedRuntime(Runtime):
    """Runtime whose only running guard is the pinned manual-review config."""

    def __init__(self, config, config_path, config_digest, **kwargs):
        self._manual_config_path = Path(config_path)
        self._manual_config_digest = config_digest
        kwargs.pop('publisher', None)
        super().__init__(config, publisher=_reject_publisher, **kwargs)

    def _require_running(self):
        try:
            current = hashlib.sha256(self._manual_config_path.read_bytes()).hexdigest()
        except OSError:
            raise ValueError('manual_review_config_changed') from None
        if current != self._manual_config_digest:
            raise ValueError('manual_review_config_changed')

    def _forbidden(self, *_args, **_kwargs):
        raise ValueError('manual_review_entrypoint_forbidden')

    produce = _forbidden
    _publish = _forbidden
    _produce_requested_revision = _forbidden
    retry = _forbidden
    retry_stage = _forbidden
    research_issues = _forbidden
    consume = _forbidden
    _post_publication_audits = _forbidden
    _queue_manager_work = _forbidden
    _evaluate_manager = _forbidden
    tick = _forbidden
    make_social = _forbidden
    hold_social_refresh = _forbidden
    refresh_social_images = _forbidden
    enable_social_autopost = _forbidden
    publish_social = _forbidden
    notify_social_posted = _forbidden
    preflight = _forbidden
    prepare_social_handoff = _forbidden


def _revision_target(job):
    if job.get('kind') != 'article_revision':
        return None
    context = job.get('revisionContext')
    base = context.get('baseArticle') if isinstance(context, dict) else None
    return base.get('id') if isinstance(base, dict) else None


class ManualReview:
    """Three bounded manual actions; no approval or publication operation."""

    def __init__(self, config_path):
        path = Path(config_path)
        try:
            raw = path.read_bytes()
            config = json.loads(raw)
        except (OSError, UnicodeError, ValueError):
            raise ValueError('manual_review_config_unreadable') from None
        if not isinstance(config, dict):
            raise ValueError('manual_review_config_invalid')
        _require_manual_config(config)
        digest = hashlib.sha256(raw).hexdigest()
        self._runtime = _ScopedRuntime(config, path, digest)

    def queue_revision(self, specification):
        self._runtime._require_running()
        base = specification.get('baseArticle') if isinstance(specification, dict) else None
        if not isinstance(base, dict) or base.get('id') not in ALLOWED_BASE_ARTICLE_IDS:
            raise ValueError('manual_review_target_forbidden')
        return self._runtime.request_revisions([specification])

    def prepare_revision(self, job_id):
        self._runtime._require_running()
        jobs = self._runtime.ledger.list_jobs()
        requested = next((job for job in jobs if job.get('id') == job_id), None)
        target = _revision_target(requested) if isinstance(requested, dict) else None
        if target not in ALLOWED_BASE_ARTICLE_IDS:
            raise ValueError('manual_review_candidate_required')
        candidates = [job for job in jobs
                      if _revision_target(job) == target
                      and job.get('stage') == 'candidate'
                      and not job.get('approval') and not job.get('publication')]
        if len(candidates) != 1 or candidates[0].get('id') != job_id:
            raise ValueError('manual_review_candidate_required')
        return self._runtime._make_article(candidates[0], self._runtime._context())

    def deliver_review(self, job_id):
        self._runtime._require_running()
        job = self._runtime.ledger.get_job(job_id)
        if (_revision_target(job) in ALLOWED_BASE_ARTICLE_IDS
                and job.get('stage') == 'review'
                and not job.get('approval') and not job.get('publication')):
            return self._runtime.deliver(job_id, 'article')
        social = job.get('social')
        if (job_id in ALLOWED_SOCIAL_JOB_IDS and job.get('stage') == 'social_review'
                and isinstance(social, dict) and not social.get('approval')
                and not social.get('publication')):
            return self._runtime.deliver(job_id, 'social')
        raise ValueError('manual_review_delivery_forbidden')

    def complete_review(self, job_id, purchase_evidence, review_supplement=None):
        """Finish QA from this task's intact successful writer/polish artifacts."""
        from candidate_assembly import assemble_candidate
        from revisions import EDIT_FIELDS
        rt = self._runtime
        rt._require_running()
        job = rt.ledger.get_job(job_id)
        if (_revision_target(job) not in ALLOWED_BASE_ARTICLE_IDS or job.get('stage') != 'error'
                or (job.get('error') or {}).get('reason') != 'article_structure_or_affiliate_failed'
                or any(job.get(k) for k in ('bundle', 'review', 'approval', 'publication'))):
            raise ValueError('manual_review_intact_candidate_required')
        spec = {k: copy.deepcopy(v) for k, v in job['revisionContext'].items()
                if k not in ('kind', 'baseHash', 'productPatches')}
        result = rt.request_revisions([spec])  # Live baseline/product CAS read.
        if result['jobs'][0]['id'] != job_id:
            raise ValueError('manual_review_job_changed')
        records = {}
        for stage in ('draft', 'polish'):
            found = rt.stage_journal.status(job_id=job_id, stage=stage)['records']
            if len(found) != 1 or found[0]['status'] != 'succeeded':
                raise ValueError('manual_review_successful_stages_required')
            records[stage] = found[0]
        paths = list((rt.root / 'research' / 'artifacts' / job_id).glob('*/source.json'))
        if len(paths) != 1:
            raise ValueError('manual_review_unique_source_required')
        def read_json(path):
            if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('manual_review_artifact_invalid')
            return json.loads(path.read_text())
        source = read_json(paths[0])
        candidate = read_json(paths[0].with_name('candidate.json'))
        gathered = read_json(rt.root / 'research' / (job_id + '.json'))
        context = rt._context()
        gathered_inputs = copy.deepcopy(gathered)
        gathered_inputs.update({
            'CLAUDE': context['editorialRules'],
            'SKILL': (Path(rt.config['repo']) / 'SKILL.md').read_text(),
        })
        source_dependencies = rt._source_dependencies(gathered_inputs)
        routes = rt._model_routes()
        draft_inputs = {
            'theme': copy.deepcopy(job['theme']),
            'dependencies': {
                'source': source_dependencies,
                'routes': routes,
                'revisionContext': copy.deepcopy(job.get('revisionContext')),
                'catalogCorrectionContext': copy.deepcopy(job.get('catalogCorrectionContext')),
            },
            'schemaVersion': {'stage': 1, 'input': 'theme+verified-source', 'output': 'article+brief'},
        }
        draft_key = rt.stage_journal.key(job_id, 'draft', draft_inputs)
        if records['draft'].get('stageKey') != draft_key:
            raise ValueError('manual_review_stage_key_mismatch')
        with rt.ledger._tx() as db:
            record = rt.stage_journal._load(db, draft_key)
            draft_output = rt.stage_journal._existing(record, draft_key)
        expected = copy.deepcopy(draft_output)
        base = spec['baseArticle']
        article = copy.deepcopy(base)
        article.update({key: expected['article'][key] for key in EDIT_FIELDS})
        article.update(author=expected['article']['author'], productIds=list(spec['targetProductIds']))
        expected.update(article=article, revisionContext=copy.deepcopy(job['revisionContext']))
        expected['brief']['protected'] = list(dict.fromkeys(
            expected['brief'].get('protected', []) + spec['verifiedAuthorFacts']))
        if gathered.get('images'):
            expected['images'] = copy.deepcopy(gathered['images'])
        expected['affiliateConfig'] = {'amazonPartnerTag': rt.env.get('AMAZON_PARTNER_TAG', '')}
        if (paths[0].parent.name != fingerprint(source['bundle'])
                or fingerprint(expected) != fingerprint(source['bundle'])):
            raise ValueError('manual_review_writer_artifact_mismatch')
        source_bundle = source['bundle']
        polish_inputs = {
            'content': source_bundle['article']['content'],
            'brief': copy.deepcopy(source_bundle['brief']),
            'dependencies': {
                'sourceBundle': rt._source_dependencies(source_bundle),
                'verifiedSource': source_dependencies,
                'routes': routes,
            },
            'schemaVersion': {'stage': 1, 'input': 'exact-source+brief', 'output': 'polish+preservation'},
        }
        polish_key = rt.stage_journal.key(job_id, 'polish', polish_inputs)
        if records['polish'].get('stageKey') != polish_key:
            raise ValueError('manual_review_stage_key_mismatch')
        with rt.ledger._tx() as db:
            record = rt.stage_journal._load(db, polish_key)
            polish_output = rt.stage_journal._existing(record, polish_key)
        if review_supplement is not None:
            fixed = set(REVIEW_SUPPLEMENT)
            if (spec['baseArticle']['id'] != 'article-024'
                    or 'fp-003' not in spec['targetProductIds']
                    or not isinstance(review_supplement, dict)
                    or set(review_supplement) != fixed | {'checkedAt', 'claims'}
                    or any(review_supplement.get(key) != value
                           for key, value in REVIEW_SUPPLEMENT.items())
                    or review_supplement.get('claims') != list(REVIEW_SUPPLEMENT_CLAIMS)
                    or not isinstance(review_supplement.get('checkedAt'), str)):
                raise ValueError('manual_review_supplement_invalid')
            try:
                checked = datetime.fromisoformat(
                    review_supplement['checkedAt'].replace('Z', '+00:00'))
            except (TypeError, ValueError):
                raise ValueError('manual_review_supplement_invalid') from None
            if checked.tzinfo is None or checked.utcoffset() is None:
                raise ValueError('manual_review_supplement_invalid')
            checked = checked.astimezone(JST)
            age = timestamp() - checked
            if not timedelta(0) <= age <= timedelta(hours=6):
                raise ValueError('manual_review_supplement_invalid')
            supplement = copy.deepcopy(review_supplement)
            for value in (gathered, gathered_inputs):
                evidence = value.get('evidence')
                if not isinstance(evidence, dict) or 'reviewSupplements' in evidence:
                    raise ValueError('manual_review_supplement_invalid')
                evidence['reviewSupplements'] = [copy.deepcopy(supplement)]
            source_dependencies = rt._source_dependencies(gathered_inputs)
        source_bundle, bundle, preservation, polished = assemble_candidate(
            job, source, candidate, gathered, purchase_evidence, polish_output)
        try:
            return rt._finish_article_review(job, context, gathered, bundle, source_bundle,
                                             preservation, polished, source_dependencies)
        finally:
            rt._save_usage()
