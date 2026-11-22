"""One pinned paid response, locally revalidated; no writer API or usage replay."""
import copy
import hashlib
import json
import os

from ledger import fingerprint
from stage_journal import OperationResult

JOB = 'article-42e59288744a55545f896d2d'
OLD_KEY = 'stage_journal:v1:9bea6f14849b6986c77873dec1381395a942a74f04ef4591fd93726bd3fb130d'
RESPONSE = 'msg_011ChJgWArotujLpo5yjmaP5'
ARTIFACT_SHA = '22e71230e4ebfabc1bd6b476bb8e9f81c62de7397f68bc4c5ffc2722a62de8ba'
SOURCE_SHA = '3395a378c8443753a99a942b3b03b557621c23e9da332a1addda9b391b9ae965'


def require(ok, reason):
    if not ok:
        raise ValueError('saved_output_local_revalidation_' + reason)


def load(root, id, key):
    require(id == JOB and key == OLD_KEY, 'scope')
    path = root / 'model-artifacts' / (hashlib.sha256(RESPONSE.encode()).hexdigest() + '.json')
    source_path = root / 'research' / (id + '.json')
    require(path.is_file() and not path.is_symlink() and source_path.is_file()
            and not source_path.is_symlink(), 'files')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ARTIFACT_SHA, 'artifact_sha')
    artifact = json.loads(raw)
    source = json.loads(source_path.read_text())
    require(artifact.get('responseId') == RESPONSE and artifact.get('model') == 'claude-opus-4-8'
            and fingerprint(source) == SOURCE_SHA, 'source_or_response')
    candidate = json.loads(artifact['content'])
    require(set(candidate) == {'article', 'brief'}, 'response_shape')
    return source, candidate


class SavedOutputLocalRevalidation:
    def __init__(self, runtime, id, key):
        self.runtime, self.id, self.key = runtime, id, key
        self.source, self.candidate = load(runtime.root, id, key)
        self.path = runtime.root / 'saved-output-local-revalidations' / (id + '.json')
        self.value = dict(kind='savedOutputLocalRevalidation', status='in_flight', jobId=id,
            oldStageKey=key, responseId=RESPONSE, artifactSha256=ARTIFACT_SHA,
            oldSourceSha256=SOURCE_SHA, oldSourceSnapshot=copy.deepcopy(self.source),
            bodySha256=fingerprint(self.candidate['article']['content']), briefSha256=fingerprint(self.candidate['brief']),
            writerApiCalls=0, paidUsageReplayed=False)
        self.output = None

    def claim(self):
        require(self.path.parent.resolve() == self.runtime.root.resolve() / 'saved-output-local-revalidations', 'receipt_path')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(self.value, stream, ensure_ascii=False)

    def bind(self, job, context, inputs):
        require(job['id'] == self.id and self.output is None, 'binding')
        expected = copy.deepcopy(self.source)
        require(set(context) - set(self.source) <= {'wisePolicy', 'CLAUDE', 'SKILL'}, 'unexpected_context_fields')
        articles = context.get('existingArticles')
        require(isinstance(articles, list) and 1 <= len(articles) <= 5, 'navigation')
        expected['existingArticles'] = copy.deepcopy(articles)
        if 'apparelSourcing' in expected:
            expected['apparelSourcing']['existingSamePositionArticles'] = copy.deepcopy(articles)
        current = {key: copy.deepcopy(context.get(key)) for key in self.source}
        normalize = self.runtime._source_dependencies
        require(normalize(current) == normalize(expected), 'non_navigation_source_drift')
        require(inputs['dependencies']['source'] == normalize(context), 'stage_context_binding')
        # Invoke the current pure validator directly, never Models.draft/_call.
        from models import Models
        validator = Models({}, request=lambda *_: (_ for _ in ()).throw(AssertionError('writer API forbidden')))
        output = validator._validate_draft(copy.deepcopy(self.candidate), job['theme'], copy.deepcopy(context))
        require(output['article'] == self.candidate['article']
                and output['brief'] == self.candidate['brief'], 'literal_changed')
        self.output = output
        self.value.update(newContextSha256=fingerprint(context), newSourceDependenciesSha256=fingerprint(normalize(context)),
                          correctedArticleSummaries=copy.deepcopy(articles), outputSha256=fingerprint(output),
                          newStageKey=self.runtime.stage_journal.key(job['id'], 'draft', inputs))
        self.value['bindingSha256'] = fingerprint({k: v for k, v in self.value.items() if k != 'status'})
        from runtime import atomic
        atomic(self.path, self.value)

    def operation(self):
        require(self.output is not None, 'unvalidated')
        return OperationResult(copy.deepcopy(self.output), {
            'kind': 'savedOutputLocalRevalidation', 'responseId': RESPONSE, 'artifactSha256': ARTIFACT_SHA,
            'oldStageKey': self.key, 'writerApiCalls': 0, 'paidUsageReplayed': False,
            'receiptBindingSha256': self.value['bindingSha256'], 'newStageKey': self.value['newStageKey'],
            'newContextSha256': self.value['newContextSha256']})

    def finish(self, completed):
        from runtime import atomic
        self.value['status'] = 'completed' if completed else 'requires_reconciliation'
        atomic(self.path, self.value)
