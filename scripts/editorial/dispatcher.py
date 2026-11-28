"""Pure deterministic planning for the existing editorial runtime."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import sqlite3

from ledger import valid_astra_review, valid_review


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str
    suspended: bool
    auto_ai_exceptions: bool = False


def social_feature_enabled(config, feature):
    if feature not in ('socialGenerationEnabled', 'socialReviewEnabled'):
        raise ValueError('invalid social feature')
    if feature not in config:
        return execution_policy(config) is None
    if type(config[feature]) is not bool:
        raise ValueError('invalid social feature flag')
    return config[feature]


def buffer_social_start(config):
    value = config.get('bufferSocialStartPeriod')
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('invalid bufferSocialStartPeriod') from None
    if parsed.weekday() != 4:
        raise ValueError('invalid bufferSocialStartPeriod')
    return value


def buffer_social_eligible(job, config, now=None):
    start = buffer_social_start(config)
    if job.get('kind') == 'supplemental_article':
        current = now or datetime.now(timezone(timedelta(hours=9)))
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError('aware buffer eligibility time required')
        return (start is not None and job.get('socialEligiblePeriod') == start
                and current.astimezone(timezone(timedelta(hours=9))).date() >= date.fromisoformat(start))
    return (start is not None and job.get('kind') != 'article_revision'
            and isinstance(job.get('week'), str) and job['week'] >= start)


def buffer_social_outstanding(jobs):
    stages = {'social_review', 'social_held', 'social_approved', 'social_scheduled'}
    return sum(job.get('stage') in stages
               and ((job.get('social') or {}).get('proposal') or {}).get('deliveryMode') == 'buffer_x'
               and not (job.get('social') or {}).get('publication') for job in jobs)


def execution_policy(config):
    """Return the opt-in policy, rejecting every malformed policy fail-closed."""
    if 'executionPolicy' not in config:
        return None
    value = config['executionPolicy']
    try:
        if not isinstance(value, dict) or set(value) - {'mode', 'suspended', 'exceptions'}:
            raise ValueError()
        if value.get('mode') != 'deterministic' or type(value.get('suspended')) is not bool:
            raise ValueError()
        exceptions = value.get('exceptions', {})
        if (not isinstance(exceptions, dict) or set(exceptions) - {'autoAI'}
                or type(exceptions.get('autoAI', False)) is not bool):
            raise ValueError()
        if exceptions.get('autoAI', False) is True:
            raise ValueError()
        return ExecutionPolicy('deterministic', value['suspended'], exceptions.get('autoAI', False))
    except (KeyError, TypeError, ValueError):
        raise ValueError('invalid executionPolicy') from None


class DeterministicDispatcher:
    """Describe one bounded progression step without performing an effect."""

    UNRESOLVED_MANAGER = {'evaluating', 'executing', 'requires_reconciliation'}

    def __init__(self, runtime):
        self.runtime = runtime

    def _state(self):
        effects = {}
        manager = []
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            for job_id, status in db.execute(
                    "SELECT job_id,status FROM effects WHERE status IN ('in_flight','unknown')"):
                effects.setdefault(job_id, []).append(status)
            for job_id, raw in db.execute("SELECT job_id,data FROM effects WHERE status='failed'"):
                try:
                    prewrite = json.loads(raw).get('reason') == 'publication_prewrite_failed'
                except (TypeError, ValueError):
                    prewrite = True
                if prewrite:
                    effects.setdefault(job_id, []).append('prewrite_failed')
            for key, raw in db.execute(
                    "SELECT key,value FROM meta WHERE key LIKE 'editorial_manager:%'"):
                try:
                    value = json.loads(raw)
                except (TypeError, ValueError):
                    value = {'status': 'requires_reconciliation'}
                if value.get('status') in self.UNRESOLVED_MANAGER:
                    action = value.get('action') if isinstance(value.get('action'), dict) else {}
                    manager.append(action.get('job_id', action.get('jobId')))
        return effects, manager

    def _delivery_needed(self, job_id, kind, now):
        with sqlite3.connect(self.runtime.ledger.db_path) as db:
            rows = db.execute(
                'SELECT data FROM requests WHERE job_id=? AND kind=? ORDER BY rowid DESC',
                (job_id, kind)).fetchall()
        active = next((json.loads(row[0]) for row in rows
                       if json.loads(row[0]).get('status') in ('created', 'delivered')), None)
        if active is None:
            return True, None
        if active['status'] == 'delivered':
            return datetime.fromisoformat(active['expires_at']) <= now, None
        marker = self.runtime.root / 'deliveries' / (active['request_id'] + '.json')
        if marker.exists():
            return False, 'delivery_requires_reconciliation'
        return True, None

    def _buffer_journal(self, job):
        revision = (job.get('social') or {}).get('revision')
        path = self.runtime.root / 'buffer-publications' / (str(revision) + '.json')
        if not path.exists():
            return None
        try:
            if path.is_symlink() or path.stat().st_mode & 0o777 != 0o600:
                raise ValueError()
            value = json.loads(path.read_text())
            if value.get('revision') != revision:
                raise ValueError()
            return value
        except (OSError, ValueError):
            return {'phase': 'requires_reconciliation', 'pending': True}

    def plan(self, now):
        policy = execution_policy(self.runtime.config)
        if policy is None or policy.mode != 'deterministic':
            raise ValueError('deterministic executionPolicy required')
        base = {'mode': 'deterministic', 'status': 'ready', 'actions': [], 'blocked': [],
                'exceptionAI': policy.auto_ai_exceptions}
        if policy.suspended:
            return dict(base, status='suspended')

        jobs = self.runtime.ledger.list_jobs()
        effects, manager = self._state()
        if manager:
            ids = sorted({job_id for job_id in manager if job_id})
            base['blocked'] = ([{'jobId': job_id,
                                 'reason': 'manager_execution_requires_reconciliation'} for job_id in ids]
                               if ids else [{'jobId': None,
                                             'reason': 'manager_execution_requires_reconciliation'}])
            return base

        ready = []
        for job in jobs:
            if job['id'] in effects:
                base['blocked'].append({'jobId': job['id'],
                                        'reason': 'effect_requires_reconciliation'})
            else:
                ready.append(job)

        article_waiting = False
        for job in [item for item in ready if item['stage'] != 'candidate']:
            stage = job['stage']
            if stage == 'review':
                try:
                    valid_review(job.get('review'), job.get('revision'), job.get('bundle'))
                    if job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job:
                        try:
                            valid_astra_review(job.get('astraReview'), job.get('revision'))
                        except ValueError:
                            if self.runtime.config.get('independentReviewEnabled') is True:
                                base['actions'].append({'kind': 'deliver', 'jobId': job['id'],
                                                        'deliveryKind': 'article'})
                            article_waiting = True
                            continue
                except ValueError:
                    article_waiting = True
                    continue
                needed, blocked = self._delivery_needed(job['id'], 'article', now)
                if blocked:
                    base['blocked'].append({'jobId': job['id'], 'reason': blocked})
                elif needed:
                    base['actions'].append({'kind': 'deliver', 'jobId': job['id'],
                                            'deliveryKind': 'article'})
                else:
                    article_waiting = True
            elif stage == 'approved' and self.runtime.config.get('publicationEnabled') is True:
                if job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job:
                    try:
                        valid_astra_review(job.get('astraReview'), job.get('revision'))
                    except ValueError:
                        base['blocked'].append({
                            'jobId': job['id'],
                            'reason': 'independent_article_review_required',
                        })
                        continue
                base['actions'].append({'kind': 'publish', 'jobId': job['id']})
            elif stage == 'approved':
                article_waiting = True
            elif (stage == 'published' and job.get('kind') != 'article_revision'
                  and not job.get('social')
                  and social_feature_enabled(self.runtime.config, 'socialGenerationEnabled')):
                start = buffer_social_start(self.runtime.config)
                if start is None:
                    base['actions'].append({'kind': 'make_social', 'jobId': job['id']})
                elif (buffer_social_eligible(job, self.runtime.config, now)
                      and buffer_social_outstanding(jobs) < 3
                      and self.runtime._social_audit_success(job)):
                    base['actions'].append({'kind': 'make_social', 'jobId': job['id']})
            elif (stage == 'social_review'
                  and social_feature_enabled(self.runtime.config, 'socialReviewEnabled')):
                start = buffer_social_start(self.runtime.config)
                proposal = ((job.get('social') or {}).get('proposal') or {})
                if (start is not None and (proposal.get('deliveryMode') != 'buffer_x'
                                           or not buffer_social_eligible(job, self.runtime.config, now))):
                    continue
                needed, blocked = self._delivery_needed(job['id'], 'social', now)
                if blocked:
                    base['blocked'].append({'jobId': job['id'], 'reason': blocked})
                elif needed:
                    base['actions'].append({'kind': 'deliver', 'jobId': job['id'],
                                            'deliveryKind': 'social'})
            elif (stage == 'social_approved'
                  and ((job.get('social') or {}).get('proposal') or {}).get('deliveryMode') == 'auto_x'
                  and self.runtime.config.get('socialPostingEnabled') is True):
                base['actions'].append({'kind': 'publish_social', 'jobId': job['id']})
            elif (stage == 'social_approved'
                  and ((job.get('social') or {}).get('proposal') or {}).get('deliveryMode') == 'buffer_x'
                  and self.runtime.config.get('bufferPostingEnabled') is True):
                journal = self._buffer_journal(job)
                if journal and journal.get('phase') == 'deferred' and not journal.get('pending'):
                    from buffer_publisher import deferred_result
                    try:
                        waiting = deferred_result(journal, now)
                    except ValueError:
                        base['blocked'].append({'jobId': job['id'],
                                                'reason': 'buffer_defer_marker_invalid'})
                        continue
                    if waiting:
                        if waiting.get('nextEligibleAt') is None:
                            base['blocked'].append({'jobId': job['id'], 'reason': waiting['reason']})
                        continue
                if journal and (journal.get('pending')
                                or journal.get('phase') not in ('deferred', 'scheduled', 'verified')):
                    base['blocked'].append({'jobId': job['id'],
                                            'reason': 'buffer_publication_requires_reconciliation'})
                else:
                    base['actions'].append({'kind': 'publish_buffer_social', 'jobId': job['id']})
            elif (stage == 'social_scheduled'
                  and ((job.get('social') or {}).get('proposal') or {}).get('deliveryMode') == 'buffer_x'
                  and self.runtime.config.get('bufferPostingEnabled') is True):
                schedule = (job.get('social') or {}).get('bufferSchedule') or {}
                journal = self._buffer_journal(job)
                if (schedule.get('nextCheckAt') is None or schedule.get('duePolls', 0) >= 3
                        or journal is None or journal.get('pending')
                        or journal.get('phase') not in ('scheduled', 'verified')):
                    base['blocked'].append({'jobId': job['id'],
                                            'reason': 'buffer_publication_requires_reconciliation'})
                    continue
                if journal.get('phase') == 'verified':
                    base['actions'].append({'kind': 'publish_buffer_social', 'jobId': job['id']})
                    continue
                try:
                    due = datetime.fromisoformat(schedule['nextCheckAt'].replace('Z', '+00:00'))
                except (AttributeError, KeyError, TypeError, ValueError):
                    base['blocked'].append({'jobId': job['id'],
                                            'reason': 'buffer_schedule_requires_reconciliation'})
                else:
                    if due.tzinfo is None or due.utcoffset() is None:
                        base['blocked'].append({'jobId': job['id'],
                                                'reason': 'buffer_schedule_requires_reconciliation'})
                    elif now >= due:
                        base['actions'].append({'kind': 'publish_buffer_social', 'jobId': job['id']})
            elif stage == 'social_posted':
                revision = (job.get('social') or {}).get('revision')
                marker = self.runtime.root / 'social-posted-notices' / (str(revision) + '.json')
                try:
                    notice = json.loads(marker.read_text())
                except (OSError, ValueError):
                    notice = None
                if isinstance(notice, dict) and notice.get('status') == 'verified':
                    continue
                if marker.exists():
                    base['blocked'].append({'jobId': job['id'],
                                            'reason': 'social_notice_requires_reconciliation'})
                else:
                    base['actions'].append({'kind': 'notify_social', 'jobId': job['id']})

        # Social generation is a model stage, not a publication/delivery effect.
        social_actions = [action for action in base['actions'] if action['kind'] == 'make_social']
        base['actions'] = [action for action in base['actions'] if action['kind'] != 'make_social']
        # Complete an already actionable side effect before starting a model stage.
        if base['actions']:
            return base

        candidates = [job for job in ready if job['stage'] == 'candidate']
        revisions = [job for job in candidates if job.get('kind') == 'article_revision']
        if revisions and self.runtime.config.get('generationEnabled') is True:
            job = min(revisions, key=lambda item: item['priority'])
            base['actions'].append({'kind': 'produce_revision', 'jobId': job['id']})
            return base
        articles = [job for job in candidates if job.get('kind') not in
                    ('article_revision', 'supplemental_article')]
        if articles and self.runtime.config.get('generationEnabled') is True:
            base['actions'].append({'kind': 'produce', 'jobId': articles[0]['id']})
            return base
        supplemental = [job for job in candidates
                        if job.get('kind') == 'supplemental_article']
        if supplemental and self.runtime.config.get('generationEnabled') is True:
            base['actions'].append({'kind': 'produce_supplemental',
                                    'jobId': supplemental[0]['id']})
            return base
        from regular_backfill import pending as is_pending
        pending = [job for job in jobs if is_pending(job)]
        # Owner waiting may fill the separately authorized batch, but cannot take
        # a slot from an incomplete regular production period.
        if article_waiting:
            regular_incomplete = False
            if (self.runtime.config.get('generationEnabled') is True
                    and self.runtime.ledger.production_schedule.is_due(now)):
                period = self.runtime.ledger.production_schedule.period_key(now)
                period_count = sum(job.get('kind') not in
                                   ('article_revision','supplemental_article')
                                   and job.get('week') == period for job in jobs)
                regular_incomplete = period_count < 3
            if (regular_incomplete and len(pending) < 3
                    and self.runtime.config.get('publicationEnabled') is True):
                base['actions'].append({'kind': 'produce', 'jobId': None})
                return base
            if (not regular_incomplete and self.runtime.config.get('generationEnabled') is True
                    and len(pending) < 3 and self.runtime.supplemental_due(now)):
                base['actions'].append({'kind':'produce_supplemental','jobId':None})
            base['actions'] = base['actions'] or social_actions
            return base
        if (self.runtime.config.get('generationEnabled') is True
                and self.runtime.ledger.production_schedule.is_due(now)):
            period = self.runtime.ledger.production_schedule.period_key(now)
            period_count = sum(job.get('kind') not in ('article_revision', 'supplemental_article')
                               and job['week'] == period
                               for job in jobs)
            if len(pending) < 3 and period_count < 3:
                base['actions'].append({'kind': 'produce', 'jobId': None})
                return base
        if (self.runtime.config.get('generationEnabled') is True and len(pending) < 3
                and self.runtime.supplemental_due(now)):
            base['actions'].append({'kind': 'produce_supplemental', 'jobId': None})
        base['actions'] = base['actions'] or social_actions
        return base
