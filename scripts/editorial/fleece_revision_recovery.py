"""Evidence pins for one known-failed two-product fleece revision retry."""
import hashlib
import json

from ledger import fingerprint

JOB = 'revision-4cefcebe89527e18972d37b9'
OLD_KEY = 'stage_journal:v1:ce6912a4dcb976bca06d653bbc391430a8476c544f2057f9674555481a427db7'
TARGETS = ['fleece-tnf-na62650', 'fleece-montbell-1114881']
REASON = 'Article product IDs do not match supplied products'
RESPONSE = 'msg_011ChJjEpHjigbh9kQyLV1Lo'
ARTIFACT_SHA = '138647813878d91225d593f7dd8d7f759f2ee0a0af9fc8516ca033c9e2a8384d'
SOURCE_SHA = 'ea0736cd2b5264e7e05d2eec3ab86f11311b4500b1f1294dd868fb09b25fb8f4'
CONTEXT_SHA = '1380b44bacce6de88881434da9569e03d3ba925425c0c1a8d221697e92f89377'


def eligible(job, key, binding):
    return (job.get('id') == JOB and key == OLD_KEY
            and (job.get('error') or {}).get('reason') == REASON
            and job.get('review') is None
            and fingerprint(binding) == CONTEXT_SHA
            and binding.get('targetProductIds') == TARGETS
            and job.get('theme', {}).get('productIds') == TARGETS
            and job.get('theme', {}).get('slug') == 'autumn-camp-classic-fleece-comparison')


def require_old_response(record):
    responses = [row.get('responseId') for batch in record.get('usageBatches', [])
                 for row in batch.get('records', [])]
    if record.get('failureType') != 'ModelError' or responses != [RESPONSE]:
        raise ValueError('fleece_recovery_old_response_changed')


def load_proof(root, job, key):
    """Read original bytes before fresh gather can replace the research snapshot."""
    if not eligible(job, key, job.get('revisionContext')):
        raise ValueError('fleece_recovery_scope')
    artifact_path = root / 'model-artifacts' / (hashlib.sha256(RESPONSE.encode()).hexdigest() + '.json')
    source_path = root / 'research' / (JOB + '.json')
    for path, expected in ((artifact_path, ARTIFACT_SHA), (source_path, SOURCE_SHA)):
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('fleece_recovery_evidence_changed')
    artifact = json.loads(artifact_path.read_text())
    source = json.loads(source_path.read_text())
    candidate = json.loads(artifact['content'])
    if (artifact.get('responseId') != RESPONSE or artifact.get('model') != 'claude-opus-4-8'
            or source.get('theme') != job['theme'] or source.get('productIds') != TARGETS
            or [p.get('id') for p in source.get('catalog', [])] != TARGETS
            or candidate.get('article', {}).get('productIds') != TARGETS[::-1]
            or candidate.get('brief', {}).get('format') != 'comparison'):
        raise ValueError('fleece_recovery_evidence_binding')
    return dict(kind='fleeceProductOrderRecovery', oldStageKey=OLD_KEY, responseId=RESPONSE,
                artifactSha256=ARTIFACT_SHA, oldSourceSha256=SOURCE_SHA,
                revisionContextSha256=CONTEXT_SHA, targetProductIds=list(TARGETS),
                savedWriterReused=False, inheritedAttempts=1, maxAttempts=2)
