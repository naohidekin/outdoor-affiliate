"""Local operator CLI for deterministic editorial status and bounded recovery."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3

from dispatcher import DeterministicDispatcher, execution_policy
from production_schedule import ProductionSchedule
from record_inspection import inspect_records
from stage_journal import read_status


JST = timezone(timedelta(hours=9))


def _root(value):
    root = Path(value)
    if not root.is_absolute() or root.resolve() in (Path('/'), Path.home().resolve()):
        raise ValueError('safe absolute state root required')
    return root.resolve()


def _database(root):
    path = root / 'ledger.sqlite3'
    if not path.is_file() or path.is_symlink():
        raise ValueError('editorial ledger not found')
    return path


def _rows(db_path):
    uri = 'file:' + str(db_path).replace('?', '%3f').replace('#', '%23') + '?mode=ro'
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        return [json.loads(row[0]) for row in db.execute(
            'SELECT data FROM jobs ORDER BY rowid')]


def status(state_root):
    root = _root(state_root)
    db_path = _database(root)
    jobs = _rows(db_path)
    stages = read_status(db_path)
    return {
        'status': 'read_only',
        'jobs': [{
            'id': job['id'], 'stage': job['stage'], 'revision': job.get('revision'),
            'approvalCurrent': bool(job.get('approval') and
                                    job['approval'].get('revision') == job.get('revision')),
            'published': (job.get('publication') or {}).get('verified') is True,
            'socialRevision': (job.get('social') or {}).get('revision'),
        } for job in jobs],
        'stages': {'counts': stages['counts'], 'byStage': stages['byStage'],
                   'records': stages['records']},
    }


class _ReadOnlyLedger:
    def __init__(self, root, config):
        self.db_path = _database(root)
        self.production_schedule = ProductionSchedule(config.get('productionSchedule'))

    def list_jobs(self):
        return _rows(self.db_path)


class _ReadOnlyRuntime:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.ledger = _ReadOnlyLedger(root, config)


def plan(state_root, config, *, now=None):
    root = _root(state_root)
    if Path(config['stateRoot']).resolve() != root:
        raise ValueError('config state root mismatch')
    execution_policy(config)
    return DeterministicDispatcher(_ReadOnlyRuntime(root, config)).plan(
        now or datetime.now(JST))


def _config(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError('config object required')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-root', required=True)
    parser.add_argument('--config')
    parser.add_argument('--job-id')
    parser.add_argument('--stage', choices=('draft', 'polish', 'final_review'))
    parser.add_argument('--input-key')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('command', choices=('status', 'records', 'plan', 'retry-stage'))
    args = parser.parse_args(argv)
    root = _root(args.state_root)
    if args.command == 'status':
        value = status(root)
    elif args.command == 'records':
        value = inspect_records(root)
    else:
        if not args.config:
            raise ValueError('config required')
        config = _config(args.config)
        if args.command == 'plan':
            value = plan(root, config)
        else:
            if not args.job_id or not args.stage or not args.input_key:
                raise ValueError('job stage and exact input key required')
            policy = execution_policy(config)
            if policy is not None and policy.suspended:
                value = {'status': 'suspended', 'mode': 'deterministic'}
            elif not args.execute:
                value = {'status': 'planned', 'operation': 'retry-stage',
                         'jobId': args.job_id, 'stage': args.stage,
                         'inputKey': args.input_key, 'executed': False}
            else:
                if Path(config['stateRoot']).resolve() != root:
                    raise ValueError('config state root mismatch')
                from runtime import Runtime
                with (root / 'runtime.flock').open('a') as lease:
                    os.chmod(lease.name, 0o600)
                    try:
                        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        value = {'status': 'busy'}
                    else:
                        runtime = Runtime(config)
                        value = runtime.retry_stage(args.job_id, args.stage, args.input_key)
                        runtime._save_usage()
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
