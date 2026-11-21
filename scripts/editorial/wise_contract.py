"""Pinned owner WISE-AS source; offline validation, never a model paraphrase."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AXES = ('Wit', 'Insight', 'Sincere', 'Empth', 'AI-free', 'Sense')
FLOORS = dict(w=2, i=2, s=2, e=2, ai=3, sense=2)
# Reviewed owner snapshot. A changed manifest alone cannot bless changed semantics.
PINNED = {'wise-master.md': '7f3a5a347bca6ffb57eccf053b2eef5a4c40c79cae8032b6ad7dcb95a4cd6144', 'sense-master.md': '5099cf3df213c1a63f45aca9b28a1c3a858a0492fe6a4ae2c819f9f9fd85b2f8'}

ARTIFACTS = {'SKILL.md': 'bbe36130b55003ca8a35529bc68367f168cc565d075460acaca86849839d3dcc', 'docs/WISE-GEARMAN.md': '43a983ac458c006426a2d241e800b65cad539a94b6d6b6ea1c246b1b4bedc5e2', 'docs/sense-definition.md': 'e56ed9144bcaf544f1270fd4481fb77ad20351e98de364a065711fca82046c41'}

def load_policy(repo=None):
    repo = Path(repo) if repo else ROOT
    directory = repo / 'rules/common'
    contract = json.loads((directory / 'wise-contract.json').read_text())
    if (contract.get('schemaVersion') != 1 or contract.get('axes') != list(AXES)
            or contract.get('floors') != FLOORS):
        raise ValueError('wise_policy_contract_drift')
    if contract.get('artifacts') != ARTIFACTS:
        raise ValueError('wise_artifact_contract_drift')
    for name, digest in ARTIFACTS.items():
        if hashlib.sha256((repo / name).read_bytes()).hexdigest() != digest:
            raise ValueError('wise_explanation_drift')
    sources = contract.get('sources', {})
    raw = []
    for name, digest in PINNED.items():
        value = (directory / name).read_bytes()
        if (hashlib.sha256(value).hexdigest() != digest
                or sources.get(name, {}).get('sha256') != digest):
            raise ValueError('wise_owner_source_drift')
        raw.append(value.decode('utf-8'))
    binding = hashlib.sha256(json.dumps(contract, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode()).hexdigest()
    return {'id': binding, 'axes': list(AXES), 'floors': dict(FLOORS),
            'sourceHashes': dict(PINNED), 'text': '\n\n'.join(raw)}


def valid_scores(scores):
    return (isinstance(scores, dict) and set(scores) == set(FLOORS)
            and all(type(scores.get(key)) in (int, float) and math.isfinite(scores[key])
                    and 1 <= scores[key] <= 4 for key in FLOORS))


def passes(scores):
    return valid_scores(scores) and all(scores[key] >= floor for key, floor in FLOORS.items())


def require_current_review(artifact, review, repo=None):
    """Hold actions on old policy; never mutate historical approvals or receipts."""
    policy = load_policy(repo)
    if (not isinstance(artifact, dict) or artifact.get('wisePolicy') != policy['id']
            or not isinstance(review, dict) or review.get('passed') is not True or review.get('wisePolicy') != policy['id']
            or not passes(review.get('wiseScores'))):
        raise ValueError('current_wise_policy_review_required')
    return policy
