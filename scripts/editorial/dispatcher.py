"""Pure deterministic planning for the existing editorial runtime."""
from dataclasses import dataclass
from datetime import datetime
import json
import sqlite3

from ledger import valid_astra_review, valid_review


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str
    suspended: bool
    auto_ai_exceptions: bool = False


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

        waiting = False
        for job in [item for item in ready if item['stage'] != 'candidate']:
            stage = job['stage']
            if stage == 'review':
                try:
                    valid_review(job.get('review'), job.get('revision'))
                    if job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job:
                        valid_astra_review(job.get('astraReview'), job.get('revision'))
                except ValueError:
                    waiting = True
                    continue
                needed, blocked = self._delivery_needed(job['id'], 'article', now)
                if blocked:
                    base['blocked'].append({'jobId': job['id'], 'reason': blocked})
                elif needed:
                    base['actions'].append({'kind': 'deliver', 'jobId': job['id'],
                                            'deliveryKind': 'article'})
                else:
                    waiting = True
            elif stage == 'approved' and self.runtime.config.get('publicationEnabled') is True:
                base['actions'].append({'kind': 'publish', 'jobId': job['id']})
            elif stage == 'approved':
                waiting = True
            elif (stage == 'published' and job.get('kind') != 'article_revision'
                  and not job.get('social')):
                base['actions'].append({'kind': 'make_social', 'jobId': job['id']})
            elif stage == 'social_review':
                needed, blocked = self._delivery_needed(job['id'], 'social', now)
                if blocked:
                    base['blocked'].append({'jobId': job['id'], 'reason': blocked})
                elif needed:
                    base['actions'].append({'kind': 'deliver', 'jobId': job['id'],
                                            'deliveryKind': 'social'})
                else:
                    waiting = True
            elif (stage == 'social_approved'
                  and ((job.get('social') or {}).get('proposal') or {}).get('deliveryMode') == 'auto_x'
                  and self.runtime.config.get('socialPostingEnabled') is True):
                base['actions'].append({'kind': 'publish_social', 'jobId': job['id']})
            elif stage == 'social_approved':
                waiting = True
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

        # Complete an already actionable side effect before starting a model stage.
        if base['actions']:
            return base

        candidates = [job for job in ready if job['stage'] == 'candidate']
        revisions = [job for job in candidates if job.get('kind') == 'article_revision']
        if revisions and self.runtime.config.get('generationEnabled') is True:
            job = min(revisions, key=lambda item: item['priority'])
            base['actions'].append({'kind': 'produce_revision', 'jobId': job['id']})
            return base
        articles = [job for job in candidates if job.get('kind') != 'article_revision']
        if articles and self.runtime.config.get('generationEnabled') is True:
            base['actions'].append({'kind': 'produce', 'jobId': articles[0]['id']})
            return base
        # A delivered exact version waiting for its owner does not create new work.
        if waiting:
            return base
        if (self.runtime.config.get('generationEnabled') is True
                and self.runtime.ledger.production_schedule.is_due(now)):
            period = self.runtime.ledger.production_schedule.period_key(now)
            pending = [job for job in jobs if job.get('kind') != 'article_revision'
                       and not job.get('publication') and job['stage'] != 'rejected']
            period_count = sum(job.get('kind') != 'article_revision' and job['week'] == period
                               for job in jobs)
            if len(pending) < 3 and period_count < 3:
                base['actions'].append({'kind': 'produce', 'jobId': None})
        return base
