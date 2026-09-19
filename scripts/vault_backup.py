#!/usr/bin/env python3
"""Private Markdown/settings snapshots. Restores are quarantined, never activated.

Run while writers are idle. Change detection rejects observed concurrent edits;
this is not a filesystem-atomic snapshot or a deletion-aware historical restore.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

FORMAT = "local-memory-vault-backup-v1"
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
ARCHIVE_NAME = re.compile(r"vault-\d{8}T\d{12}Z-[0-9a-f]{32}\.zip\Z")


def safe_path(value):
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    # Callers must canonicalize OS aliases (e.g. macOS /tmp) explicitly.
    # Symlinks anywhere in a supplied path are refused here.
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise ValueError(f"Symlink path refused: {part}")
    return path


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def selected(name):
    return name.lower().endswith(".md") or name.startswith(".obsidian/")


def inventory(vault, read=False):
    result, total = {}, 0
    for root, dirs, files, fd in os.fwalk(vault, follow_symlinks=False):
        for name in sorted(dirs + files):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("Vault contains a symlink; snapshot refused")
            if name in dirs:
                continue
            relative = (Path(root) / name).relative_to(vault).as_posix()
            if not selected(relative):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                raise ValueError("Unsupported or oversized vault file")
            total += info.st_size
            if total > MAX_TOTAL:
                raise ValueError("Snapshot exceeds 256 MiB limit")
            if not read:
                result[relative] = signature(info)
                continue
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(handle, "rb") as stream:
                if signature(os.fstat(stream.fileno())) != signature(info):
                    raise ValueError("Vault changed during backup")
                data = stream.read(MAX_FILE + 1)
                if signature(os.fstat(stream.fileno())) != signature(info):
                    raise ValueError("Vault changed during backup")
            if len(data) != info.st_size:
                raise ValueError("Vault changed during backup")
            result[relative] = (signature(info), data)
    return result


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(vault, destination, retain=7):
    vault, destination = safe_path(vault), safe_path(destination)
    if not vault.is_dir():
        raise ValueError("Vault must be an existing directory")
    if destination == vault or vault in destination.parents:
        raise ValueError("Backup destination must be outside the vault")
    if not isinstance(retain, int) or retain < 1:
        raise ValueError("Retention must be at least one")
    before = inventory(vault)
    content = inventory(vault, read=True)
    if before != {name: item[0] for name, item in content.items()}:
        raise ValueError("Vault changed during backup")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final = destination / f"vault-{stamp}-{uuid.uuid4().hex}.zip"
    manifest = {"format": FORMAT, "created_at": stamp, "files": {
        name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        for name, (_, data) in content.items()}}
    fd, temporary = tempfile.mkstemp(prefix=".vault-backup-", dir=destination)
    try:
        with os.fdopen(fd, "w+b") as stream:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
                for name, (_, data) in content.items():
                    archive.writestr("files/" + name, data)
            stream.flush()
            os.fsync(stream.fileno())
        if inventory(vault) != before:
            raise ValueError("Vault changed during backup")
        os.replace(temporary, final)
        sync_directory(destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    # Only this helper's precisely named archives are eligible for retention.
    snapshots = sorted(p for p in destination.iterdir()
                       if ARCHIVE_NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink())
    for old in snapshots[:-retain]:
        old.unlink()
    sync_directory(destination)
    return {"archive": str(final), "files": len(content), "retain": retain}


def relative_name(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("Unsafe archive path")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts) or PurePosixPath(name).is_absolute():
        raise ValueError("Unsafe archive path")
    if not selected(name):
        raise ValueError("Unexpected file in archive")
    return name


def restore(archive_path, quarantine):
    archive_path, quarantine = safe_path(archive_path), safe_path(quarantine)
    if quarantine.exists():
        raise ValueError("Restore requires a NEW quarantine directory")
    if not quarantine.parent.is_dir():
        raise ValueError("Quarantine parent must already exist")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("Duplicate entries or missing manifest")
        if sum(entry.file_size for entry in entries) > MAX_TOTAL + 1024 * 1024:
            raise ValueError("Archive exceeds size limit")
        for entry in entries:
            mode = entry.external_attr >> 16
            if (entry.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or entry.file_size > MAX_FILE):
                raise ValueError("Unsupported archive entry")
        if archive.getinfo("manifest.json").file_size > 1024 * 1024:
            raise ValueError("Manifest exceeds size limit")
        manifest = json.loads(archive.read("manifest.json"))
        if (not isinstance(manifest, dict) or manifest.get("format") != FORMAT
                or not isinstance(manifest.get("files"), dict)):
            raise ValueError("Unsupported manifest")
        files = manifest["files"]
        for name in files:
            relative_name(name)
        if set(names) != {"manifest.json", *("files/" + name for name in files)}:
            raise ValueError("Archive does not match manifest")
        content = {}
        for name, expected in files.items():
            data = archive.read("files/" + name)
            if expected != {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}:
                raise ValueError("Archive checksum mismatch")
            content[name] = data
    # Validate everything before creating anything. Never extractall() or merge.
    quarantine.mkdir(mode=0o700)
    try:
        for name, data in content.items():
            target = quarantine / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        sync_directory(quarantine)
    except Exception:
        shutil.rmtree(quarantine)
        raise
    return {"quarantine": str(quarantine), "files": len(content), "activated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup")
    create.add_argument("--vault", required=True)
    create.add_argument("--destination", required=True)
    create.add_argument("--retain", type=int, default=7)
    recover = commands.add_parser("restore")
    recover.add_argument("--archive", required=True)
    recover.add_argument("--quarantine", required=True)
    args = parser.parse_args()
    try:
        result = (backup(args.vault, args.destination, args.retain) if args.command == "backup"
                  else restore(args.archive, args.quarantine))
        print(json.dumps({"ok": True, **result}))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
