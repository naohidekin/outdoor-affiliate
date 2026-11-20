"""Two fixed owner-approved revision publications while normal automation stays suspended."""
import copy
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
from pathlib import Path

from ledger import JST, SCOPE, fingerprint, valid_astra_review, valid_review
from manual_review import ManualReview, _revision_target
from runtime import Runtime, atomic, reason, safe_publication_diagnostic, stamp


TARGETS = {
    'revision-24e819b2d97352db90bb048c': {
        'baseId': 'article-005',
        'revision': '4e758957164c1c307cfce417544184f503825f3ffb2f75e0b1b76f2770ca17fe',
        'cardTs': '1794686781.240169',
    },
    'revision-a3842d6293c8b7a2a386b68a': {
        'baseId': 'article-024',
        'revision': 'a017e4e45ca441249f5b0e9b7ceecad556c287cb74524b6173ae7dae115c8221',
        'cardTs': '1794686800.550379',
    },
}


def _aware(value):
    if not isinstance(value, str):
        raise ValueError('manual_publication_aware_time_required')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('manual_publication_aware_time_required') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('manual_publication_aware_time_required')
    return parsed.astimezone(JST)


class ManualPublication(ManualReview):
    """Bounded approval, publication and audit operations for two exact revisions."""

    def __init__(self, config_path, runtime_lock):
        super().__init__(config_path)
        self._runtime_lock = runtime_lock

    def _forbidden(self, *_args, **_kwargs):
        raise ValueError('manual_publication_review_entrypoint_forbidden')

    queue_revision = _forbidden
    prepare_revision = _forbidden
    complete_review = _forbidden
    deliver_review = _forbidden

    def _require_root_flock(self):
        rt = self._runtime
        rt._require_running()
        expected = (Path(rt.root) / 'runtime.flock').resolve()
        try:
            actual = Path(self._runtime_lock.name).resolve()
            self._runtime_lock.fileno()
        except (AttributeError, OSError, TypeError, ValueError):
            raise ValueError('manual_publication_root_flock_required') from None
        if actual != expected:
            raise ValueError('manual_publication_root_flock_required')
        with expected.open('a') as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                fcntl.flock(probe, fcntl.LOCK_UN)
                raise ValueError('manual_publication_root_flock_required')
        try:
            fcntl.flock(self._runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('manual_publication_root_flock_required') from None

    @staticmethod
    def _target(job_id):
        target = TARGETS.get(job_id)
        if target is None:
            raise ValueError('manual_publication_target_forbidden')
        return target

    def _exact_job(self, job_id, *, stage=None):
        target = self._target(job_id)
        job = self._runtime.ledger.get_job(job_id)
        if (job.get('kind') != 'article_revision'
                or _revision_target(job) != target['baseId']
                or job.get('revision') != target['revision']
                or fingerprint(job.get('bundle')) != target['revision']
                or (stage is not None and job.get('stage') != stage)):
            raise ValueError('manual_publication_exact_revision_required')
        return job, target

    def accept_slack_approval(self, job_id):
        self._require_root_flock()
        target = self._target(job_id)
        current, _ = self._exact_job(job_id)
        if current.get('stage') not in ('review', 'approved') or current.get('publication'):
            raise ValueError('manual_publication_review_state_required')
        scope = self._runtime.config.get('slack')
        if not isinstance(scope, dict) or any(not scope.get(key) for key in SCOPE):
            raise ValueError('manual_publication_scope_invalid')
        bound_scope = {key: scope[key] for key in SCOPE}
        spool = Path(self._runtime.config['spoolDir'])
        matches = []
        for path in sorted(spool.glob('*.json')):
            if path.is_symlink() or path.stat().st_size > 16384:
                continue
            try:
                raw = path.read_bytes()
                event = json.loads(raw)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                continue
            if (isinstance(event, dict)
                    and event.get('article_id') == job_id
                    and event.get('manifest_hash') == target['revision']
                    and event.get('message_ts') == target['cardTs']
                    and event.get('action_id') == 'camp_review_approve'
                    and event.get('user_id') == bound_scope['user_id']
                    and all(event.get(key) == bound_scope[key] for key in SCOPE)):
                matches.append((path, event, hashlib.sha256(raw).hexdigest()))
        if len(matches) != 1:
            raise ValueError('manual_publication_exact_spool_event_required')
        path, event, event_hash = matches[0]
        with self._runtime.ledger._tx() as db:
            row = db.execute('SELECT job_id,kind,data FROM requests WHERE id=?',
                             (event.get('request_id'),)).fetchone()
        if row is None:
            raise ValueError('manual_publication_exact_article_request_required')
        try:
            request = json.loads(row[2])
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError('manual_publication_exact_article_request_required') from None
        request_status = 'decided' if current.get('stage') == 'approved' else 'delivered'
        if (row[0] != job_id or row[1] != 'article'
                or not isinstance(request, dict) or request.get('kind') != 'article'
                or request.get('status') != request_status
                or request.get('article_id') != job_id
                or request.get('manifest_hash') != target['revision']
                or request.get('card_ts') != target['cardTs']
                or request.get('scope') != bound_scope):
            raise ValueError('manual_publication_exact_article_request_required')
        event = copy.deepcopy(event)
        event['card_ts'] = event['message_ts']
        decided = self._runtime.ledger.decide(event, bound_scope)
        approval = decided.get('approval') or {}
        if (decided.get('id') != job_id or decided.get('stage') != 'approved'
                or decided.get('revision') != target['revision']
                or approval.get('action') != 'approved'
                or approval.get('user_id') != bound_scope['user_id']
                or approval.get('revision') != target['revision']):
            raise ValueError('manual_publication_approval_mismatch')
        authority = {
            'schemaVersion': 1, 'jobId': job_id, 'revision': target['revision'],
            'cardTs': target['cardTs'], 'requestId': event['request_id'],
            'eventId': event['event_id'], 'eventHash': event_hash,
            'scope': bound_scope,
        }
        authority_path = Path(self._runtime.root) / 'manual-publication-authority' / (job_id + '.json')
        if authority_path.exists():
            if json.loads(authority_path.read_text()) != authority:
                raise ValueError('manual_publication_authority_reconciliation_required')
        else:
            atomic(authority_path, authority)
        processed = spool / 'editorial-processed'
        processed.mkdir(mode=0o700, exist_ok=True)
        destination = processed / path.name
        if destination.exists():
            raise ValueError('manual_publication_spool_reconciliation_required')
        path.rename(destination)
        return {'status': 'approved', 'id': job_id, 'revision': target['revision'],
                'cardTs': target['cardTs'], 'processed': str(destination),
                'authority': str(authority_path)}

    def _bound_authority(self, job, target):
        path = Path(self._runtime.root) / 'manual-publication-authority' / (job['id'] + '.json')
        try:
            authority = json.loads(path.read_text())
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            raise ValueError('manual_publication_bound_authority_required') from None
        if (not isinstance(authority, dict) or set(authority) != {
                'schemaVersion', 'jobId', 'revision', 'cardTs', 'requestId',
                'eventId', 'eventHash', 'scope'}
                or authority.get('schemaVersion') != 1
                or authority.get('jobId') != job['id']
                or authority.get('revision') != target['revision']
                or authority.get('cardTs') != target['cardTs']
                or authority.get('scope') != {key: self._runtime.config['slack'][key] for key in SCOPE}
                or not isinstance(authority.get('eventHash'), str)):
            raise ValueError('manual_publication_bound_authority_required')
        processed = Path(self._runtime.config['spoolDir']) / 'editorial-processed'
        matches = []
        for event_path in processed.glob('*.json'):
            if event_path.is_symlink() or event_path.stat().st_size > 16384:
                continue
            raw = event_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() == authority['eventHash']:
                matches.append((event_path, raw))
        if len(matches) != 1:
            raise ValueError('manual_publication_processed_event_required')
        try:
            native = json.loads(matches[0][1])
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError('manual_publication_processed_event_required') from None
        with self._runtime.ledger._tx() as db:
            request_row = db.execute('SELECT job_id,kind,data FROM requests WHERE id=?',
                                     (authority['requestId'],)).fetchone()
            decision_row = db.execute('SELECT data FROM decisions WHERE id=?',
                                      (authority['eventId'],)).fetchone()
        if request_row is None or decision_row is None:
            raise ValueError('manual_publication_bound_authority_required')
        try:
            request = json.loads(request_row[2])
            decision = json.loads(decision_row[0])
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError('manual_publication_bound_authority_required') from None
        expected_event = copy.deepcopy(native)
        expected_event['card_ts'] = native.get('message_ts')
        approval = job.get('approval') or {}
        event = decision.get('event') if isinstance(decision, dict) else None
        result = decision.get('result') if isinstance(decision, dict) else None
        if (request_row[0] != job['id'] or request_row[1] != 'article'
                or request.get('kind') != 'article' or request.get('status') != 'decided'
                or request.get('article_id') != job['id']
                or request.get('manifest_hash') != target['revision']
                or request.get('card_ts') != target['cardTs']
                or request.get('scope') != authority['scope']
                or native.get('event_id') != authority['eventId']
                or native.get('request_id') != authority['requestId']
                or native.get('message_ts') != target['cardTs']
                or native.get('manifest_hash') != target['revision']
                or native.get('article_id') != job['id']
                or native.get('action_id') != 'camp_review_approve'
                or native.get('user_id') != self._runtime.ledger.owner_id
                or any(native.get(key) != authority['scope'][key] for key in SCOPE)
                or native.get('nonce') != request.get('nonce')
                or event != expected_event
                or not isinstance(result, dict) or result.get('id') != job['id']
                or result.get('stage') != 'approved'
                or result.get('revision') != target['revision']
                or result.get('approval') != approval
                or approval.get('request_id') != authority['requestId']):
            raise ValueError('manual_publication_bound_authority_required')
        return authority

    def publish_revision(self, job_id):
        self._require_root_flock()
        job, target = self._exact_job(job_id, stage='approved')
        approval = job.get('approval') or {}
        if (job.get('publication') or approval.get('action') != 'approved'
                or approval.get('user_id') != self._runtime.ledger.owner_id
                or approval.get('revision') != target['revision']):
            raise ValueError('manual_publication_current_owner_approval_required')
        self._bound_authority(job, target)
        valid_review(job.get('review'), target['revision'], job.get('bundle'))
        valid_astra_review(job.get('astraReview'), target['revision'])
        if not self._runtime.ledger.claim_effect(job_id, 'publish'):
            raise ValueError('manual_publication_effect_requires_reconciliation')
        try:
            result = Runtime._publish(self._runtime, 'publish-revision', copy.deepcopy(job))
            self._runtime.ledger.record_publication(job_id, target['revision'], result)
            self._runtime.ledger.finish_effect(job_id, 'publish', {'status': 'success', **result})
        except Exception as error:
            diagnostic = safe_publication_diagnostic(getattr(error, 'diagnostic', None))
            self._runtime.ledger.finish_effect(job_id, 'publish', {
                'status': 'unknown', 'reason': 'publication_requires_reconciliation',
                **({'diagnostic': diagnostic} if diagnostic else {}),
            })
            raise
        return {'status': 'published', 'id': job_id, 'revision': target['revision'],
                'publication': result}

    def audit_revision(self, job_id):
        self._require_root_flock()
        job, target = self._exact_job(job_id)
        publication = job.get('publication') or {}
        readback = publication.get('readback') or {}
        if (job.get('stage') != 'published'
                or publication.get('verified') is not True
                or publication.get('revision') != target['revision']
                or readback.get('verified') is not True
                or readback.get('fingerprint') != target['revision']):
            raise ValueError('manual_publication_verified_publication_required')
        key = fingerprint({'id': job_id, 'revision': target['revision'],
                           'publication': publication})
        path = Path(self._runtime.root) / 'post-publication-audits' / (key + '.json')
        if path.exists():
            audit = json.loads(path.read_text())
            if (not isinstance(audit, dict) or audit.get('auditKey') != key
                    or audit.get('id') != job_id or audit.get('revision') != target['revision']
                    or audit.get('publication') != publication
                    or not isinstance(audit.get('attempts'), list)):
                raise ValueError('manual_publication_audit_reconciliation_required')
        else:
            audit = {'schemaVersion': 1, 'id': job_id, 'revision': target['revision'],
                     'publication': publication, 'auditKey': key,
                     'status': 'pending', 'attempts': []}
        now = datetime.now(JST)
        status = audit.get('status')
        attempts = audit['attempts']
        allowed = {'pending', 'in_flight', 'unknown', 'requires_reconciliation',
                   'success', 'failed', 'unverified'}
        if (status not in allowed or len(attempts) > 3
                or any(not isinstance(attempt, dict)
                       or attempt.get('status') not in ('success', 'failed', 'unverified')
                       or not isinstance(attempt.get('result'), dict)
                       or not isinstance(attempt.get('at'), str)
                       for attempt in attempts)
                or status == 'pending' and attempts
                or status in ('success', 'failed', 'unverified') and not attempts):
            raise ValueError('manual_publication_audit_reconciliation_required')
        try:
            for attempt in attempts:
                _aware(attempt['at'])
        except ValueError:
            raise ValueError('manual_publication_audit_reconciliation_required') from None
        if status in ('in_flight', 'unknown', 'requires_reconciliation'):
            return self._audit_summary(audit, path)
        due = status == 'pending'
        if status in ('failed', 'unverified') and len(audit['attempts']) < 3:
            due = bool(audit.get('nextAttemptAt') and _aware(audit['nextAttemptAt']) <= now)
        if not due:
            return self._audit_summary(audit, path)
        audit.update(status='in_flight', startedAt=stamp())
        atomic(path, audit)
        try:
            auditor = self._runtime.post_auditor
            if auditor is None:
                from post_publication_audit import PostPublicationAudit
                auditor = self._runtime.post_auditor = PostPublicationAudit(
                    self._runtime.config, self._runtime.env)
            checked = auditor.check(copy.deepcopy(job))
            if not isinstance(checked, dict) or type(checked.get('passed')) is not bool:
                raise ValueError('post_audit_result_invalid')
            checked = json.loads(json.dumps(checked, allow_nan=False))
            reported = checked.get('status')
            unverified = (reported not in (None, 'passed', 'success', 'failed')
                          or checked.get('verified') is False
                          or reported == 'failed' and checked['passed'])
            outcome = 'unverified' if unverified else ('success' if checked['passed'] else 'failed')
        except Exception as error:
            checked = {'passed': False, 'status': 'unverified',
                       'issues': [{'code': 'post_audit_check_unavailable',
                                   'reason': reason(error)}]}
            outcome = 'unverified'
        audit['attempts'].append({'at': stamp(), 'status': outcome, 'result': checked})
        audit.update(status=outcome, result=checked, completedAt=stamp(),
                     nextAttemptAt=(now + timedelta(minutes=30)).isoformat()
                     if outcome != 'success' and len(audit['attempts']) < 3 else None,
                     action='' if outcome == 'success' else
                     ('Inspect audit evidence; manual recheck available in 30 minutes'
                      if len(audit['attempts']) < 3 else
                      'Inspect audit evidence and correct or reconcile manually; retry limit reached'))
        atomic(path, audit)
        return self._audit_summary(audit, path)

    @staticmethod
    def _audit_summary(audit, path):
        result = {key: audit.get(key) for key in
                  ('id', 'auditKey', 'revision', 'status', 'result', 'nextAttemptAt', 'action')}
        result.update(attempts=len(audit.get('attempts', [])), receipt=str(path))
        return result
