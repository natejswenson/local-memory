"""Authenticated per-part encryption, with an authenticated ordering manifest."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import uuid
from cryptography.fernet import Fernet
from . import backup_v4
from .capture import exclusive_create
from .serialization import canonical
from .skill_store import atomic, read, safe

FORMAT = 'local-memory-encrypted-recovery-v2'


def create(paths, key_path, destination, maximum):
    from scripts.encrypted_backup import key_at, matching_fitness, recovery_source
    key_path, destination = safe(key_path), safe(destination)
    if (destination == paths.vault or paths.vault in destination.parents or key_path == destination
            or destination in key_path.parents or paths.vault in key_path.parents):
        raise ValueError('RECOVERY_KEY_AND_DESTINATION_MUST_BE_SEPARATE')
    cipher = Fernet(key_at(key_path, create=True))
    staging = safe(paths.runtime / 'encrypted-backup-work'); staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as tmp:
        scratch = Path(tmp)
        hub = backup_v4.create(paths.vault, scratch / 'hub', general_control=paths.control,
            skill_control=paths.skill_control if paths.skill_control.exists() else None, max_logical_bytes=maximum)
        bundle = Path(hub['archive']); manifest_raw = read(bundle / 'manifest.json', backup_v4.MANIFEST_BYTES)
        hub_manifest = json.loads(manifest_raw)
        identifier = hub_manifest['bundle_id']
        output = destination / ('memory-recovery-v2-' + identifier); output.mkdir(mode=0o700)
        manifest = dict(format=FORMAT, bundle_id=identifier, created_at=datetime.now(timezone.utc).isoformat(),
                        files={}, complete=True)
        def encrypt(name, raw):
            encrypted = cipher.encrypt(raw)
            exclusive_create(output / (name + '.fernet'), encrypted)
            if cipher.decrypt(read(output / (name + '.fernet'), len(encrypted))) != raw:
                raise ValueError('ENCRYPTED_READBACK_MISMATCH')
            manifest['files'][name + '.fernet'] = dict(clear_name=name, size=len(encrypted),
                sha256=hashlib.sha256(encrypted).hexdigest(), clear_sha256=hashlib.sha256(raw).hexdigest())
        for part in hub_manifest['parts']:
            encrypt(part['name'], read(bundle / part['name'], backup_v4.PART_BYTES + 4 * 1024 ** 2))
        encrypt('hub-manifest.json', manifest_raw)
        encrypt('recovery-tools.zip', recovery_source(paths.root))
        if (paths.vault / 'Projects/local-fitness').exists():
            encrypt('fitness.zip', matching_fitness(paths.state / 'fitness', bundle))
        exclusive_create(output / 'manifest.fernet', cipher.encrypt(canonical(manifest)))
        return dict(status='encrypted', verified=True, path=str(output), parts=len(manifest['files']),
                    format=FORMAT, cloud_verified=False, key_recovery='Keep the recovery key separately from encrypted data.')


def restore(bundle, key_path, quarantine, maximum):
    from scripts.encrypted_backup import key_at
    from scripts.fitness_migration.restore_store import restore as restore_fitness
    bundle, quarantine = safe(bundle), safe(quarantine)
    if quarantine.exists() or not quarantine.parent.is_dir(): raise ValueError('NEW_QUARANTINE_REQUIRED')
    cipher = Fernet(key_at(key_path))
    m = json.loads(cipher.decrypt(read(bundle / 'manifest.fernet', 2 * backup_v4.MANIFEST_BYTES)))
    if m.get('format') != FORMAT or m.get('complete') is not True or not isinstance(m.get('files'), dict):
        raise ValueError('INVALID_ENCRYPTED_MANIFEST')
    if str(uuid.UUID(m['bundle_id'])) != m['bundle_id']: raise ValueError('INVALID_BUNDLE_ID')
    if len(m['files']) > backup_v4.MAX_FILES: raise ValueError('ENCRYPTED_MANIFEST_TOO_LARGE')
    sizes = [v.get('size') for v in m['files'].values()]
    if any(type(n) is not int or n < 0 for n in sizes) or sum(sizes) > 2 * maximum + 2 * backup_v4.MANIFEST_BYTES + 600 * 1024 ** 2:
        raise ValueError('ENCRYPTED_LOGICAL_BUDGET_EXCEEDED')
    quarantine.mkdir(mode=0o700)
    hub = quarantine / 'hub-parts'; hub.mkdir(mode=0o700)
    for name, expected in m['files'].items():
        clear_name = expected['clear_name']
        import re
        if (name != clear_name + '.fernet' or clear_name not in {'hub-manifest.json', 'fitness.zip', 'recovery-tools.zip'}
                and not re.fullmatch(r'part-\d{6}\.zip', clear_name)):
            raise ValueError('INVALID_ENCRYPTED_MEMBER')
        maximum_part = 300 * 1024 ** 2 if clear_name in {'fitness.zip', 'recovery-tools.zip'} else backup_v4.MANIFEST_BYTES if clear_name == 'hub-manifest.json' else backup_v4.PART_BYTES + 4 * 1024 ** 2
        encrypted = read(bundle / name, maximum_part * 2)
        if len(encrypted) != expected['size'] or hashlib.sha256(encrypted).hexdigest() != expected['sha256']:
            raise ValueError('ENCRYPTED_PART_CHECKSUM_MISMATCH')
        raw = cipher.decrypt(encrypted)
        if len(raw) > maximum_part or hashlib.sha256(raw).hexdigest() != expected['clear_sha256']:
            raise ValueError('CLEAR_PART_CHECKSUM_MISMATCH')
        target = hub / ('manifest.json' if clear_name == 'hub-manifest.json' else clear_name)
        exclusive_create(target, raw)
    restored_manifest = json.loads(read(hub / 'manifest.json', backup_v4.MANIFEST_BYTES))
    if restored_manifest.get('bundle_id') != m['bundle_id']: raise ValueError('BUNDLE_IDENTITY_MISMATCH')
    has_fitness = any(name.startswith('vault/Projects/local-fitness/') for name in restored_manifest['files'])
    if has_fitness and 'fitness.zip.fernet' not in m['files']:
        raise ValueError('FITNESS_OWNER_ARCHIVE_REQUIRED')
    result = backup_v4.restore(hub, quarantine / 'hub', max_logical_bytes=maximum)
    if has_fitness: result['fitness'] = restore_fitness(hub / 'fitness.zip', quarantine / 'fitness')
    return result
