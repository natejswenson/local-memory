"""Resolve actual private operational configuration and report measurable health."""
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
from .skill_store import read, safe


def configuration(paths):
    file = safe(paths.control / 'operations.json')
    value = json.loads(read(file, 262144)) if file.exists() else {}
    if value and value.get('schema_version') != 1: raise ValueError('INVALID_OPERATIONS_CONFIGURATION')
    if not value.get('backup_destination'):
        plist = safe(Path.home() / 'Library/LaunchAgents/com.local-memory-hub.backup.plist')
        if plist.exists() and not paths.pilot:
            args = plistlib.loads(read(plist, 262144)).get('ProgramArguments', [])
            if '--vault' in args and args[args.index('--vault')+1] == str(paths.vault) and '--destination' in args:
                value['backup_destination'] = args[args.index('--destination')+1]
    return value


def backup_status(paths):
    cfg = configuration(paths); destination = cfg.get('backup_destination')
    if not destination: return {'status': 'warning', 'code': 'BACKUP_DESTINATION_UNCONFIGURED', 'archives': 0}
    destination = safe(Path(destination))
    from scripts.vault_backup import ARCHIVE_NAME
    files = [p for p in destination.iterdir() if not p.is_symlink() and
             ((p.is_file() and ARCHIVE_NAME.fullmatch(p.name)) or
              (p.is_dir() and p.name.startswith('vault-v4-') and (p / 'manifest.json').is_file()) or
              (p.is_dir() and p.name.startswith('memory-recovery-v2-') and (p / 'manifest.fernet').is_file()))] if destination.exists() else []
    latest = max((p.stat().st_mtime for p in files), default=None)
    age = None if latest is None else round((datetime.now(timezone.utc).timestamp() - latest) / 3600, 2)
    return {'status': 'ok' if age is not None and age <= 24 else 'warning', 'code': 'BACKUP_CURRENT' if age is not None and age <= 24 else 'BACKUP_OVERDUE',
            'destination': str(destination), 'archives': len(files), 'latest_age_hours': age,
            'integrity': 'not established by age; verify a quarantined restore',
            'format': cfg.get('backup_format', 'v3'), 'logical_budget_bytes': cfg.get('max_logical_bytes')}


def backup_create(paths, destination=None, key=None):
    paths.require_ready(); cfg = configuration(paths)
    destination = destination or cfg.get('backup_destination')
    if not destination: raise ValueError('BACKUP_DESTINATION_REQUIRED')
    if cfg.get('backup_format') == 'v4':
        maximum = cfg.get('max_logical_bytes')
        if type(maximum) is not int: raise ValueError('EXPLICIT_LOGICAL_BUDGET_REQUIRED')
        if key:
            from .encrypted_v4 import create
            return create(paths, key, destination, maximum)
        from .backup_v4 import create
        return create(paths.vault, destination, general_control=paths.control,
                      skill_control=paths.skill_control if paths.skill_control.exists() else None, max_logical_bytes=maximum)
    if key:
        from scripts.encrypted_backup import create
        if paths.pilot: raise ValueError('LEGACY_ENCRYPTION_REQUIRES_LIVE_ROOT')
        return create(paths.root, key, destination)
    from scripts.vault_backup import backup
    return backup(paths.vault, destination, general_control=paths.control,
                  skill_control=paths.skill_control if paths.skill_control.exists() else None) | {'status': 'created'}


def backup_verify(paths, archive, quarantine, key=None):
    if not archive or not quarantine: raise ValueError('ARCHIVE_AND_NEW_QUARANTINE_REQUIRED')
    archive = safe(archive)
    maximum = configuration(paths).get('max_logical_bytes', 256 * 1024 ** 2)
    if archive.is_dir():
        if (archive / 'manifest.fernet').exists():
            if not key: raise ValueError('RECOVERY_KEY_REQUIRED')
            from .encrypted_v4 import restore
            return restore(archive, key, quarantine, maximum)
        from .backup_v4 import restore
        return restore(archive, quarantine, max_logical_bytes=maximum)
    if archive.suffix == '.fernet':
        if not key: raise ValueError('RECOVERY_KEY_REQUIRED')
        from scripts.encrypted_backup import recover
        return recover(archive, key, quarantine) | {'status': 'verified'}
    from scripts.vault_backup import restore
    return restore(archive, quarantine) | {'status': 'verified'}
