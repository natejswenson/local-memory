#!/usr/bin/env python3
"""Preview/install the owned local maintenance LaunchAgent; no cloud activity."""
import hashlib
import json
from pathlib import Path
import plistlib
import sys
import uuid
from memory_hub.serialization import canonical
from memory_hub.skill_store import atomic, read, safe

LABEL = 'com.local-memory-hub.maintenance'
MARKER = b'<!-- Managed by local-memory/scripts/install_maintenance.py v1 -->'


def plan(root, home=None):
    root, home = safe(root), safe(home or Path.home())
    path = safe(home / 'Library/LaunchAgents' / (LABEL + '.plist'))
    old = read(path, 262144) if path.exists() else None
    args = [str(root / 'bin/memory-hub'), 'maintenance', 'run']
    if old is not None:
        previous = plistlib.loads(old)
        if MARKER not in old or previous.get('ProgramArguments') != args:
            raise ValueError('UNMANAGED_MAINTENANCE_AGENT')
    logs = root / '.runtime/maintenance'
    cfg = dict(Label=LABEL, ProgramArguments=args, RunAtLoad=True, KeepAlive=True,
               ThrottleInterval=10, WorkingDirectory=str(root), Umask=0o077,
               StandardOutPath=str(logs / 'stdout.log'), StandardErrorPath=str(logs / 'stderr.log'))
    after = plistlib.dumps(cfg).replace(b'<plist version=', MARKER + b'\n<plist version=', 1)
    public = dict(path=str(path), before=hashlib.sha256(old).hexdigest() if old else None,
                  after=hashlib.sha256(after).hexdigest(), loaded=False)
    return public | {'plan_hash': hashlib.sha256(canonical(public)).hexdigest(), '_before': old, '_after': after}


def install(root, expected_plan_hash, home=None):
    proposal = plan(root, home)
    if proposal['plan_hash'] != expected_plan_hash: raise ValueError('MAINTENANCE_PLAN_STALE')
    backup = safe(root / '.runtime/integration-backups' / str(uuid.uuid4()))
    if proposal['_before'] is not None: atomic(backup / 'maintenance.before', proposal['_before'])
    atomic(backup / 'maintenance.after', proposal['_after'])
    for name in ('stdout.log', 'stderr.log'):
        path = safe(root / '.runtime/maintenance' / name)
        if not path.exists(): atomic(path, b'')
    atomic(Path(proposal['path']), proposal['_after'])
    return {k:v for k,v in proposal.items() if not k.startswith('_')} | {'status': 'configured', 'loaded': False}
