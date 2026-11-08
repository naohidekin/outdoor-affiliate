"""Read-only corrected-publication permit. Trusted caller controls root and owner env.

The JSON request is never authority. Only a matching existing private ledger record
and claimed effect can verify it. This helper changes no state and returns no IDs.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

# The standalone permit check must not create import caches either.
sys.dont_write_bytecode = True

from catalog_corrections import validate_bundle
from ledger import canonical, fingerprint, require, timestamp, valid_astra_review, valid_review


def _private(path, mode, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == mode
            and (stat.S_ISDIR(info.st_mode) if directory else
                 stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
            'private owned path required')
    return info


def _root(raw):
    path = Path(raw)
    require(path.is_absolute() and path != Path('/'), 'absolute private state root required')
    require('..' not in path.parts, 'canonical root required')
    for part in (path, *path.parents):
        require(not stat.S_ISLNK(part.lstat().st_mode), 'symlink path refused')
    _private(path, 0o700, directory=True)
    return path


def _journal_clear(root, revision):
    folder = root / 'catalog-corrections'
    if not os.path.lexists(folder):
        return
    _private(folder, 0o700, directory=True)
    for path in folder.iterdir():
        require(re.fullmatch(r'[a-f0-9]{64}\.json', path.name) is not None,
                'journal reconciliation required')
        _private(path, 0o600)
        saved = json.loads(path.read_text())
        require(isinstance(saved, dict) and saved.get('status') == 'complete'
                and path.name != revision + '.json', 'journal reconciliation required')


def verify(request, environ=None):
    """Return a boolean, fail closed on malformed requests or unavailable evidence."""
    try:
        env = os.environ if environ is None else environ
        root = _root(env['CAMP_EDITORIAL_STATE_ROOT'])
        owner = env['CAMP_EDITORIAL_OWNER_ID']
        require(isinstance(owner, str) and owner.strip(), 'owner required')
        require(isinstance(request, dict) and request.get('action') == 'publish-corrected', 'corrected action required')
        bundle, revision = request['bundle'], request['revision']
        require(isinstance(bundle, dict) and re.fullmatch(r'[a-f0-9]{64}', revision) is not None,
                'manifest required')
        require(fingerprint(bundle) == revision, 'input fingerprint changed')
        id = bundle['article']['id']
        require(isinstance(id, str) and id, 'article identity required')
        path = root / 'ledger.sqlite3'
        before = _private(path, 0o600)
        # mode=ro never initializes a ledger; no Ledger constructor or writable transaction.
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            row = db.execute('SELECT value FROM meta WHERE key=?', ('owner_id',)).fetchone()
            require(row is not None and row[0] == owner, 'ledger owner mismatch')
            row = db.execute('SELECT data FROM jobs WHERE id=?', (id,)).fetchone()
            require(row is not None, 'actual job required')
            job = json.loads(row[0])
            require(job['id'] == id and job['stage'] == 'approved' and job.get('publication') is None
                    and job.get('kind') != 'article_revision', 'approved unpublished new job required')
            require(job['revision'] == revision == fingerprint(job['bundle'])
                    and canonical(job['bundle']) == canonical(bundle), 'actual manifest mismatch')
            validate_bundle(job, bundle)
            valid_review(job.get('review'), revision)
            valid_astra_review(job.get('astraReview'), revision)
            approval = job['approval']
            require(isinstance(approval, dict) and approval.get('user_id') == owner
                    and approval.get('revision') == revision, 'actual owner approval required')
            source = approval.get('source', 'authenticated-slack-receiver')
            require((source == 'codex' and approval.get('action') in (None, 'approved'))
                    or (source == 'authenticated-slack-receiver' and approval.get('action') == 'approved'),
                    'actual approval action required')
            require(isinstance(approval.get('request_id'), str) and approval['request_id'].strip(),
                    'actual request evidence required')
            timestamp(approval['at'])
            expected = dict(revision=revision, approverId=owner,
                            evidence=dict(requestId=approval['request_id'], approvedAt=approval['at'], source=source))
            require(canonical(request.get('approval')) == canonical(expected), 'bound approval mismatch')
            effect = db.execute('SELECT status FROM effects WHERE job_id=? AND kind=?', (id, 'publish')).fetchone()
            require(effect is not None and effect[0] == 'in_flight', 'claimed publication effect required')
            _journal_clear(root, revision)
            after = _private(path, 0o600)
            require((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino), 'ledger replaced')
        return True
    except Exception:
        return False


def main():
    try:
        request = json.load(sys.stdin)
        verified = verify(request)
    except Exception:
        verified = False
    print(json.dumps({'verified': verified}))


if __name__ == '__main__':
    main()
