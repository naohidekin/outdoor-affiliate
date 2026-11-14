"""Owner-invoked review work while the normal editorial runtime stays suspended."""
import hashlib
import json
from pathlib import Path

from runtime import Runtime


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
