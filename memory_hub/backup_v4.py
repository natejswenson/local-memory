"""Streaming, bounded multipart snapshots. Restore only into new quarantine directories."""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid
import zipfile

from .capture import exclusive_create, locked
from .serialization import canonical
from .skill_store import atomic, read, safe
from scripts.vault_backup import selected, control_selected, relative_name, signature, sync_directory

FORMAT = 'local-memory-vault-and-controls-v4'
MAX_LOGICAL = 8 * 1024 ** 3
PART_BYTES = 32 * 1024 ** 2
CHUNK = 4 * 1024 ** 2
MANIFEST_BYTES = 128 * 1024 ** 2
MAX_FILES = 1000000


def file_digest(path, maximum):
    fd = os.open(safe(path), os.O_RDONLY | os.O_NOFOLLOW)
    digest, size = hashlib.sha256(), 0
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError('REGULAR_PART_REQUIRED')
        while data := stream.read(CHUNK):
            size += len(data)
            if size > maximum: raise ValueError('PART_TOO_LARGE')
            digest.update(data)
    return size, digest.hexdigest()


def inventory(roots, maximum):
    result, total = {}, 0
    for label, folder in roots.items():
        folder = safe(folder)
        if not folder.is_dir(): raise ValueError('BACKUP_SOURCE_MISSING')
        selector = selected if label == 'vault' else control_selected
        for root, dirs, files, fd in os.fwalk(folder, follow_symlinks=False):
            for name in sorted(dirs + files):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode): raise ValueError('BACKUP_SYMLINK_REFUSED')
                if name in dirs: continue
                relative = (Path(root) / name).relative_to(folder).as_posix()
                if not selector(relative): continue
                if not stat.S_ISREG(info.st_mode): raise ValueError('BACKUP_REGULAR_FILE_REQUIRED')
                total += info.st_size
                if total > maximum or len(result) >= MAX_FILES: raise ValueError('BACKUP_LOGICAL_BUDGET_EXCEEDED')
                result[label + '/' + relative] = (folder / relative, signature(info))
    return result


def create(vault, destination, *, general_control, skill_control=None, max_logical_bytes=MAX_LOGICAL, part_bytes=PART_BYTES):
    if type(max_logical_bytes) is not int or not 1 <= max_logical_bytes <= MAX_LOGICAL:
        raise ValueError('INVALID_BACKUP_BUDGET')
    if type(part_bytes) is not int or not 1024 <= part_bytes <= PART_BYTES:
        raise ValueError('INVALID_BACKUP_PART_SIZE')
    roots = {'vault': safe(vault), 'general-control': safe(general_control)}
    if skill_control is not None: roots['skill-control'] = safe(skill_control)
    destination = safe(destination)
    for folder in roots.values():
        if folder == destination or folder in destination.parents or destination in folder.parents:
            raise ValueError('BACKUP_DESTINATION_MUST_BE_SEPARATE')
    values = list(roots.values())
    for i, left in enumerate(values):
        for right in values[i+1:]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError('BACKUP_SOURCE_ROOTS_MUST_BE_SEPARATE')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    with ExitStack() as locks:
        locks.enter_context(locked(roots['general-control']))
        if skill_control is not None:
            from .skill_store import SkillStore
            locks.enter_context(SkillStore(roots['vault'], roots['skill-control']).locked())
        before = inventory(roots, max_logical_bytes)
        bundle = str(uuid.uuid4())
        stage = Path(tempfile.mkdtemp(prefix='.building-v4-', dir=destination))
        manifest = dict(format=FORMAT, bundle_id=bundle, created_at=datetime.now(timezone.utc).isoformat(),
                        logical_bytes=sum(info[1][2] for info in before.values()), files={}, parts=[], complete=True)
        archive = None; used = 0; part = -1; entries = 0
        try:
            for name, (path, expected) in sorted(before.items()):
                fragments, offset, digest = [], 0, hashlib.sha256()
                fd = os.open(safe(path), os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as stream:
                    if signature(os.fstat(stream.fileno())) != expected: raise ValueError('SOURCE_CHANGED_DURING_BACKUP')
                    while offset < expected[2]:
                        if archive is None or used == part_bytes or entries >= 16000:
                            if archive is not None: archive.close()
                            part += 1; used = 0; entries = 0
                            part_name = f'part-{part:06}.zip'
                            archive = zipfile.ZipFile(stage / part_name, 'w', zipfile.ZIP_DEFLATED)
                            (stage / part_name).chmod(0o600)
                            archive.writestr('part.json', canonical(dict(bundle_id=bundle, part=part)))
                            manifest['parts'].append({'name': part_name})
                        data = stream.read(min(CHUNK, part_bytes - used, expected[2] - offset))
                        if not data: raise ValueError('SOURCE_CHANGED_DURING_BACKUP')
                        member = f'fragments/{len(manifest["files"]):07}-{offset:012}'
                        archive.writestr(member, data)
                        fragments.append(dict(part=part, member=member, offset=offset, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
                        digest.update(data); used += len(data); offset += len(data); entries += 1
                    if stream.read(1) or signature(os.fstat(stream.fileno())) != expected: raise ValueError('SOURCE_CHANGED_DURING_BACKUP')
                manifest['files'][name] = dict(size=offset, sha256=digest.hexdigest(), fragments=fragments)
            if archive is not None: archive.close(); archive = None
            if inventory(roots, max_logical_bytes) != before: raise ValueError('SOURCE_CHANGED_DURING_BACKUP')
            for part in manifest['parts']:
                path = stage / part['name']
                size, revision = file_digest(path, PART_BYTES + 4 * 1024 ** 2)
                part.update(size=size, sha256=revision)
                with path.open('rb') as stream: os.fsync(stream.fileno())
            payload = canonical(manifest)
            if len(payload) > MANIFEST_BYTES: raise ValueError('BACKUP_MANIFEST_BUDGET_EXCEEDED')
            atomic(stage / 'manifest.json', payload)
            final = destination / ('vault-v4-' + bundle)
            os.replace(stage, final); sync_directory(destination)
            return dict(status='created', archive=str(final), format=FORMAT, files=len(before),
                        logical_bytes=manifest['logical_bytes'], parts=len(manifest['parts']), verified=True,
                        general_control_included=True, skill_control_included=skill_control is not None)
        finally:
            if archive is not None: archive.close()
            # Interrupted stages are deliberately retained and never listed as complete snapshots.


def restore(bundle, quarantine, *, max_logical_bytes=MAX_LOGICAL):
    bundle, quarantine = safe(bundle), safe(quarantine)
    if quarantine.exists() or not quarantine.parent.is_dir(): raise ValueError('NEW_QUARANTINE_REQUIRED')
    m = json.loads(read(bundle / 'manifest.json', MANIFEST_BYTES))
    if (m.get('format') != FORMAT or m.get('complete') is not True or not isinstance(m.get('files'), dict)
            or len(m['files']) > MAX_FILES or type(m.get('logical_bytes')) is not int
            or not 0 <= m['logical_bytes'] <= min(max_logical_bytes, MAX_LOGICAL)):
        raise ValueError('INVALID_MULTIPART_MANIFEST')
    if str(uuid.UUID(m['bundle_id'])) != m['bundle_id']: raise ValueError('INVALID_BUNDLE_ID')
    if not isinstance(m.get('parts'), list) or len(m['parts']) > MAX_FILES: raise ValueError('INVALID_PARTS')
    total, members = 0, [set() for _ in m['parts']]
    for name, file in m['files'].items():
        relative_name(name, bundle=True)
        if type(file.get('size')) is not int or file['size'] < 0: raise ValueError('INVALID_FILE_SIZE')
        offset = 0
        for fragment in file['fragments']:
            part = fragment['part']; member = fragment['member']
            if (type(part) is not int or not 0 <= part < len(m['parts']) or fragment['offset'] != offset
                    or type(fragment['size']) is not int or not 0 < fragment['size'] <= CHUNK
                    or not isinstance(member, str) or not member.startswith('fragments/') or '..' in member
                    or member in members[part]): raise ValueError('INVALID_FRAGMENT')
            members[part].add(member); offset += fragment['size']
        if offset != file['size']: raise ValueError('FILE_FRAGMENT_SIZE_MISMATCH')
        total += offset
    if total != m['logical_bytes']: raise ValueError('LOGICAL_SIZE_MISMATCH')
    # Validate parts one at a time, without opening a potentially huge number of FDs.
    for i, part in enumerate(m['parts']):
        if part['name'] != f'part-{i:06}.zip': raise ValueError('INVALID_PART_NAME')
        size, revision = file_digest(bundle / part['name'], PART_BYTES + 4 * 1024 ** 2)
        if size != part['size'] or revision != part['sha256']:
            raise ValueError('PART_CHECKSUM_MISMATCH')
        with zipfile.ZipFile(safe(bundle / part['name'])) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != members[i] | {'part.json'}:
                raise ValueError('PART_MEMBERS_MISMATCH')
            if sum(item.file_size for item in archive.infolist()) > PART_BYTES + 65536:
                raise ValueError('PART_DECOMPRESSION_BUDGET_EXCEEDED')
            if json.loads(archive.read('part.json')) != dict(bundle_id=m['bundle_id'], part=i):
                raise ValueError('PART_IDENTITY_MISMATCH')
            for info in archive.infolist():
                if info.is_dir() or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                    raise ValueError('UNSAFE_PART_ENTRY')
    quarantine.mkdir(mode=0o700)
    assignments = [[] for _ in m['parts']]
    for name, file in m['files'].items():
        path = safe(quarantine / name); path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        exclusive_create(path, b'')
        for fragment in file['fragments']:
            assignments[fragment['part']].append((name, fragment))
    for i, part in enumerate(m['parts']):
        with zipfile.ZipFile(safe(bundle / part['name'])) as archive:
            for name, fragment in assignments[i]:
                info = archive.getinfo(fragment['member'])
                if info.file_size != fragment['size']: raise ValueError('FRAGMENT_SIZE_MISMATCH')
                raw = archive.read(fragment['member'])
                if hashlib.sha256(raw).hexdigest() != fragment['sha256']: raise ValueError('FRAGMENT_CHECKSUM_MISMATCH')
                path = safe(quarantine / name)
                fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
                with os.fdopen(fd, 'ab') as output:
                    if os.fstat(output.fileno()).st_size != fragment['offset']: raise ValueError('FRAGMENT_OFFSET_MISMATCH')
                    output.write(raw); output.flush(); os.fsync(output.fileno())
    for name, file in m['files'].items():
        digest = hashlib.sha256()
        with safe(quarantine / name).open('rb') as stream:
            while raw := stream.read(CHUNK): digest.update(raw)
        if digest.hexdigest() != file['sha256']: raise ValueError('FILE_CHECKSUM_MISMATCH')
    sync_directory(quarantine)
    return dict(status='verified', restored=str(quarantine), activated=False, files=len(m['files']),
                format=FORMAT, review='Reconcile forgetting ledgers and owner controls before any promotion.')
