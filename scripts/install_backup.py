#!/usr/bin/env python3
"""Preview/install the daily macOS backup agent. Never runs launchctl."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.local-memory-hub.backup"
MARKER = b"<!-- Managed by local-memory/scripts/install_backup.py v1 -->"


def reject_symlinks(path):
    for item in [*reversed(path.parents), path]:
        if item.is_symlink():
            raise ValueError(f"Refusing symlink: {item}")


def install(home=None, apply=False):
    home = Path(home if home is not None else Path.home()).expanduser().absolute()
    vault = ROOT / "vault"
    executable = ROOT / ".venv/bin/python"
    script = ROOT / "scripts/vault_backup.py"
    destination = home / "Library/Application Support/local-memory-hub/backups"
    logs = ROOT / ".runtime/live/backups"
    plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
    stdout, stderr = logs / "stdout.log", logs / "stderr.log"
    for path in (home, vault, script, executable.parent, destination, plist, logs, stdout, stderr):
        reject_symlinks(path)
    for path in (plist, stdout, stderr):
        if path.exists() and not path.is_file():
            raise ValueError(f"Expected a regular file: {path}")
    # A standard venv intentionally links its interpreter; retain the absolute
    # venv executable in ProgramArguments so its environment is selected.
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Install the virtual environment before scheduling backups")
    if not script.is_file() or not vault.is_dir():
        raise ValueError("Backup helper and canonical vault must exist")
    if destination == vault or vault in destination.parents:
        raise ValueError("Backup destination must be outside the canonical vault")
    settings = {
        "Label": LABEL,
        "ProgramArguments": [str(executable), str(script), "backup", "--vault", str(vault),
                             "--destination", str(destination), "--retain", "14"],
        "RunAtLoad": True,
        "StartInterval": 86400,
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(stdout),
        "StandardErrorPath": str(stderr),
        "Umask": 0o077,
    }
    before = plist.read_bytes() if plist.exists() else None
    if before is not None:
        try:
            previous = plistlib.loads(before)
        except Exception as error:
            raise ValueError("Existing backup plist is invalid; refusing replacement") from error
        if not isinstance(previous, dict) or MARKER not in before or previous.get("Label") != LABEL:
            raise ValueError("Unmanaged backup plist already exists")
        if previous.get("ProgramArguments", [])[:2] != settings["ProgramArguments"][:2]:
            raise ValueError("Existing backup plist belongs to a different installation")
    summary = {"applied": apply, "loaded": False, "plist": str(plist),
               "destination": str(destination), "configuration": settings,
               "note": "Installation does not load/reload launchd; validate and load separately."}
    if not apply:
        return summary
    for directory in (destination, logs, plist.parent):
        reject_symlinks(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Existing logs are not truncated. New logs are private before launchd opens them.
    for logfile in (stdout, stderr):
        reject_symlinks(logfile)
        fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    payload = plistlib.dumps(settings, sort_keys=False).replace(b"<plist version=", MARKER + b"\n<plist version=", 1)
    fd, temporary = tempfile.mkstemp(prefix=".memory-backup-", dir=plist.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        reject_symlinks(plist)
        current = plist.read_bytes() if plist.exists() else None
        if current != before:
            raise ValueError("Backup plist changed during installation")
        os.replace(temporary, plist)
        directory_fd = os.open(plist.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=str(Path.home()), help="User home containing Library/LaunchAgents")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This installer requires macOS")
    try:
        print(json.dumps(install(args.home, args.apply), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
