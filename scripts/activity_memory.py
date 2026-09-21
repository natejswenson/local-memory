#!/usr/bin/env python3
"""Record, query or synchronize the central Obsidian activity journal."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.activity import ActivityStore
from memory_hub.activity_sources import sync_sources
from memory_hub.skill_store import read


def ready():
    result = json.loads(subprocess.check_output([sys.executable, str(ROOT / 'bin/memory-hub'), 'doctor']))
    if not result.get('ready'):
        raise ValueError('Activated memory required')


def sync(apply=False):
    config = json.loads(read(ROOT / '.runtime/activity-config.json'))
    if config.get('enabled') is not True:
        raise ValueError('Activity integration disabled')
    if apply:
        ready()
    return sync_sources(ROOT / 'vault', ROOT / '.runtime/general-memory', config['sources'], apply)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['record', 'recall', 'sync', 'status'])
    p.add_argument('--apply', action='store_true', help='Apply source synchronization; default is preview')
    p.add_argument('--skill'); p.add_argument('--subject'); p.add_argument('--state')
    p.add_argument('--since'); p.add_argument('--until'); p.add_argument('--query', default='')
    p.add_argument('--limit', type=int, default=10); p.add_argument('--offset', type=int, default=0)
    args = p.parse_args()
    store = ActivityStore(ROOT / 'vault', ROOT / '.runtime/general-memory')
    if args.command == 'sync':
        result = sync(args.apply)
    elif args.command == 'status':
        result = json.loads(read(ROOT / '.runtime/general-memory/activity/sync-status.json'))
    else:
        ready()
        if args.command == 'record':
            result = store.record(json.loads(sys.stdin.read(32769)))
        else:
            result = store.recall(**{k: getattr(args, k) for k in ('skill', 'subject', 'state', 'since', 'until', 'query', 'limit', 'offset')})
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] in {'ok', 'recorded', 'already_recorded'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
