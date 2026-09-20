#!/usr/bin/env python3
"""Install allowlisted publication synchronization and a reviewable Codex activity hook."""
import argparse
import copy
import json
import os
from pathlib import Path
import plistlib
import shlex
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.activity import canonical
from memory_hub.skill_store import atomic, read, safe

LABEL = 'com.local-memory-hub.activity-sync'
MARKER = b'<!-- Managed by local-memory/scripts/install_activity.py v1 -->'


def install(home, apply=False):
    home = safe(home)
    hooks_path = safe(home / '.codex/hooks.json')
    plist = safe(home / 'Library/LaunchAgents' / (LABEL + '.plist'))
    config_path = safe(ROOT / '.runtime/activity-config.json')
    command = shlex.join([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/activity_hook.py')])
    old_hooks = read(hooks_path, 262144) if hooks_path.exists() else None
    hooks = json.loads(old_hooks) if old_hooks else {'hooks': {}}
    if not isinstance(hooks, dict) or not isinstance(hooks.get('hooks'), dict):
        raise ValueError('Invalid existing hooks configuration')
    changed = copy.deepcopy(hooks)
    groups = changed['hooks'].setdefault('PostToolUse', [])
    if not isinstance(groups, list):
        raise ValueError('Invalid hook groups')
    handler = {'type': 'command', 'command': command, 'timeout': 30, 'async': True}
    owned = [g for g in groups if any(h.get('command') == command for h in g.get('hooks', []))]
    if owned and (len(owned) != 1 or owned[0] != {'matcher': '*', 'hooks': [handler]}):
        raise ValueError('Existing activity hook customized; inspect before changing')
    if not owned:
        groups.append({'matcher': '*', 'hooks': [handler]})
    config = {'version': 1, 'enabled': True, 'sources': [
        {'skill': skill, 'path': str(home / '.claude' / skill / 'published.jsonl')}
        for skill in ('ghostwriter', 'ghostwriter-x')]}
    if config_path.exists():
        config = json.loads(read(config_path))  # Preserve previously selected sources/disable choice.
    logs = ROOT / '.runtime/live/activity-sync'
    settings = {'Label': LABEL, 'ProgramArguments': [str(ROOT / '.venv/bin/python'),
        str(ROOT / 'scripts/activity_memory.py'), 'sync', '--apply'],
        'WorkingDirectory': str(ROOT), 'RunAtLoad': True, 'StartInterval': 300,
        'StandardOutPath': str(logs / 'stdout.log'), 'StandardErrorPath': str(logs / 'stderr.log'), 'Umask': 0o077}
    previous = read(plist) if plist.exists() else None
    if previous and (MARKER not in previous or plistlib.loads(previous).get('ProgramArguments', [])[:2] != settings['ProgramArguments'][:2]):
        raise ValueError('Unmanaged activity job already exists')
    result = {'applied': apply, 'sources': config['sources'], 'hook': str(hooks_path),
              'hook_command': command, 'hook_activation': 'Requires Codex /hooks review and trust; not auto-trusted.',
              'plist': str(plist), 'loaded': False, 'interval_seconds': 300}
    if not apply:
        return result
    if not (ROOT / '.runtime/live/activation.json').is_file():
        raise ValueError('Activate live memory first')
    backups = ROOT / '.runtime/activity-install-backups'
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    if old_hooks and not (backups / 'hooks.json').exists():
        atomic(backups / 'hooks.json', old_hooks)
    for path in (logs, hooks_path.parent, plist.parent):
        safe(path).mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('stdout.log', 'stderr.log'):
        fd = os.open(safe(logs / name), os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    if (read(hooks_path, 262144) if hooks_path.exists() else None) != old_hooks:
        raise ValueError('Hook configuration changed')
    atomic(config_path, canonical(config))
    atomic(hooks_path, json.dumps(changed, indent=2).encode())
    atomic(plist, plistlib.dumps(settings).replace(b'<plist version=', MARKER + b'\n<plist version=', 1))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home', type=Path, default=Path.home())
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    print(json.dumps(install(a.home, a.apply), indent=2))
