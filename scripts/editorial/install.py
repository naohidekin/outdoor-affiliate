#!/usr/bin/env python3
"""Install the new single-host runner; never copies credential files."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def install(config_path, load=False):
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text())
    if config.get('telegramEnabled', False):
        raise ValueError('telegram_must_be_disabled')
    repo = Path(config['repo']).resolve()
    script = repo / 'scripts/editorial/runtime.py'
    if not script.is_file() or not Path(config['envFile']).is_file() or not Path(config['geminiEnvFile']).is_file():
        raise ValueError('runtime_or_existing_credentials_unavailable')
    root = Path(config['stateRoot'])
    if not root.is_absolute() or root.resolve() in (Path('/'), Path.home().resolve()):
        raise ValueError('unsafe_state_root')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_mode & 0o077:
        raise ValueError('state_root_not_private')
    agents = Path.home() / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    logs = root / 'logs'
    logs.mkdir(mode=0o700, exist_ok=True)
    label = 'com.naohide.camp-slack-review'
    plist = {'Label': label, 'ProgramArguments': [sys.executable, str(script), '--config', str(config_path), 'tick'],
             'WorkingDirectory': str(repo), 'RunAtLoad': True, 'StartInterval': 300, 'ThrottleInterval': 60,
             'ProcessType': 'Background', 'EnvironmentVariables': {'TZ': 'Asia/Tokyo', 'PYTHONDONTWRITEBYTECODE': '1',
             'PATH': '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
             'StandardOutPath': str(logs / 'tick.out.log'), 'StandardErrorPath': str(logs / 'tick.err.log')}
    target = agents / (label + '.plist')
    backups = root / 'rollback'
    backups.mkdir(mode=0o700, exist_ok=True)
    backup = backups / target.name
    if target.exists() and not backup.exists():
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(target.read_bytes())
    if load:
        subprocess.run(['launchctl', 'bootout', 'gui/' + str(os.getuid()) + '/' + label], capture_output=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(plistlib.dumps(plist))
    temporary.chmod(0o600)
    os.replace(temporary, target)
    if load:
        subprocess.run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(target)], check=True, capture_output=True)
    return {'status': 'installed' if load else 'prepared', 'label': label, 'intervalSeconds': 300,
            'productionSlot': 'Wednesday 09:00 JST, login-resume recovery', 'telegramEnabled': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--load', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.config, args.load)))
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'reason': type(error).__name__}))
        sys.exit(1)
