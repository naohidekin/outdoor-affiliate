"""Narrow compatibility for exact, owner-approved SNS revisions only."""
import hashlib
import json
import re

from ledger import fingerprint, valid_review
from wise_contract import FLOORS, PINNED, load_policy, passes


LEGACY_APPROVED_SOCIAL_POLICY_ID = (
    '6eeecd05024a54cd4b6ec7c4e781470caad7b0fc597bfbc20af0de3cc951491b')
_LEGACY_MANIFEST = {
    'schemaVersion': 1,
    'axes': ['Wit', 'Insight', 'Sincere', 'Empth', 'AI-free', 'Sense'],
    'floors': {'w': 2, 'i': 2, 's': 2, 'e': 2, 'ai': 3, 'sense': 2},
    'sources': {
        'wise-master.md': {
            'sha256': '7f3a5a347bca6ffb57eccf053b2eef5a4c40c79cae8032b6ad7dcb95a4cd6144',
            'ownerSource': 'naohide-context/rules/common/wise-master.md',
        },
        'sense-master.md': {
            'sha256': '5099cf3df213c1a63f45aca9b28a1c3a858a0492fe6a4ae2c819f9f9fd85b2f8',
            'ownerSource': 'naohide-context/rules/common/sense-master.md',
        },
    },
    'artifacts': {
        'SKILL.md': '6dcf364e2094d7714adbf281eb9a3f186f6e4fe13e040db39d386db0808b921a',
        'docs/WISE-GEARMAN.md': '43a983ac458c006426a2d241e800b65cad539a94b6d6b6ea1c246b1b4bedc5e2',
        'docs/sense-definition.md': 'e56ed9144bcaf544f1270fd4481fb77ad20351e98de364a065711fca82046c41',
    },
}


def _manifest_id(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _require_fixed_legacy_manifest(current):
    sources = _LEGACY_MANIFEST.get('sources') or {}
    source_hashes = {name: value.get('sha256') for name, value in sources.items()
                     if isinstance(value, dict)}
    if (_manifest_id(_LEGACY_MANIFEST) != LEGACY_APPROVED_SOCIAL_POLICY_ID
            or _LEGACY_MANIFEST.get('schemaVersion') != 1
            or _LEGACY_MANIFEST.get('axes') != current.get('axes')
            or _LEGACY_MANIFEST.get('floors') != FLOORS
            or current.get('floors') != FLOORS
            or source_hashes != PINNED
            or current.get('sourceHashes') != PINNED):
        raise ValueError('legacy_social_policy_manifest_invalid')


def require_approved_social_review(job, owner_id, repo=None):
    """Accept current policy or one fixed legacy policy after exact owner approval.

    This is deliberately job-scoped: it cannot validate article reviews or an SNS
    review that has not already been approved for the same immutable revision.
    """
    current = load_policy(repo)
    if not isinstance(job, dict) or job.get('stage') not in ('social_approved', 'social_scheduled'):
        raise ValueError('approved_social_policy_review_required')
    social = job.get('social') or {}
    proposal, review = social.get('proposal'), social.get('review')
    revision, approval = social.get('revision'), social.get('approval')
    if (not isinstance(proposal, dict) or not isinstance(review, dict)
            or not isinstance(revision, str) or re.fullmatch(r'[0-9a-f]{64}', revision) is None
            or fingerprint(proposal) != revision or review.get('fingerprint') != revision
            or not isinstance(owner_id, str) or not owner_id
            or not isinstance(approval, dict) or approval.get('action') != 'approved'
            or approval.get('revision') != revision or approval.get('user_id') != owner_id
            or not isinstance(approval.get('request_id'), str) or not approval['request_id']
            or review.get('passed') is not True or not passes(review.get('wiseScores'))):
        raise ValueError('approved_social_policy_review_required')
    valid_review(review, revision)
    policy_id = proposal.get('wisePolicy')
    if review.get('wisePolicy') != policy_id:
        raise ValueError('approved_social_policy_review_required')
    if policy_id == current['id']:
        return {'policy': current, 'compatibility': 'current'}
    if policy_id != LEGACY_APPROVED_SOCIAL_POLICY_ID:
        raise ValueError('approved_social_policy_review_required')
    _require_fixed_legacy_manifest(current)
    return {'policy': current, 'compatibility': 'legacy_approved_social_only'}
