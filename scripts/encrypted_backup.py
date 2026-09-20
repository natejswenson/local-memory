#!/usr/bin/env python3
"""Authenticated encrypted recovery bundles; upload only the .fernet artifact.

Contains a coordinated hub snapshot, the matching fitness-owner archive, and
recovery source. Credentials and the encryption key are never bundle members.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.capture import exclusive_create
from memory_hub.skill_store import atomic, read, safe
from scripts.vault_backup import backup, restore
from scripts.fitness_migration.restore_store import restore as restore_fitness

LIMIT = 300 * 1024 * 1024
FORMAT = "local-memory-encrypted-recovery-v1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def key_at(path, create=False):
    path = safe(path)
    if not path.exists() and create:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        exclusive_create(path, Fernet.generate_key() + b"\n")
    if path.stat().st_mode & 0o077:
        raise ValueError("Recovery key must be private (0600)")
    key = read(path, 256).strip()
    Fernet(key)  # Validate without printing the secret.
    return key


def pack(components, key):
    if set(components) - {"hub.zip", "fitness.zip", "recovery-tools.zip"} or "hub.zip" not in components:
        raise ValueError("Unexpected recovery component")
    if sum(map(len, components.values())) > LIMIT:
        raise ValueError("Recovery bundle too large")
    manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(),
                "files": {name: {"sha256": sha(raw), "size": len(raw)} for name, raw in components.items()}}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, raw in components.items():
            archive.writestr(name, raw)
    return Fernet(key).encrypt(output.getvalue())


def unpack(ciphertext, key):
    if len(ciphertext) > LIMIT * 2:
        raise ValueError("Encrypted bundle too large")
    clear = Fernet(key).decrypt(ciphertext)
    with zipfile.ZipFile(io.BytesIO(clear)) as archive:
        names = archive.namelist()
        if (len(names) != len(set(names)) or "manifest.json" not in names
                or sum(i.file_size for i in archive.infolist()) > LIMIT + 65536
                or archive.getinfo("manifest.json").file_size > 65536):
            raise ValueError("Invalid recovery manifest")
        manifest = json.loads(archive.read("manifest.json"))
        files = manifest.get("files", {})
        if (manifest.get("format") != FORMAT or not isinstance(files, dict) or "hub.zip" not in files
                or set(files) - {"hub.zip", "fitness.zip", "recovery-tools.zip"}
                or set(names) != set(files) | {"manifest.json"}):
            raise ValueError("Unexpected recovery members")
        result = {}
        for name, expected in files.items():
            raw = archive.read(name)
            if expected != {"sha256": sha(raw), "size": len(raw)}:
                raise ValueError("Recovery checksum mismatch")
            result[name] = raw
        return result


def matching_fitness(control, hub_archive):
    """Require the owner archive to match both its current control and the hub snapshot."""
    control = safe(control)
    if (control / "pending.json").exists() or (control / "backup-error").exists():
        raise ValueError("Fitness recovery or backup error requires attention")
    state = json.loads(read(control / "state.json", 32 * 1024 * 1024))
    archives = sorted((control / "backups").glob("fitness-*.zip"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    with zipfile.ZipFile(hub_archive) as hub:
        hub_manifest = json.loads(hub.read("manifest.json"))["files"]
        fitness_files = {n.removeprefix("vault/Projects/local-fitness/"): info["sha256"]
                         for n, info in hub_manifest.items()
                         if n.startswith("vault/Projects/local-fitness/") and n.endswith(".md")}
    for path in archives:
        raw = read(safe(path), LIMIT)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            checks = json.loads(archive.read("checksums.json"))
            if set(archive.namelist()) != set(checks) | {"checksums.json"}:
                continue
            if sum(i.file_size for i in archive.infolist()) > LIMIT:
                raise ValueError("Fitness archive too large")
            if any(sha(archive.read(n)) != digest for n, digest in checks.items()):
                raise ValueError("Fitness archive checksum mismatch")
            if json.loads(archive.read("state.json")) != state:
                continue
            note_hashes = {n.removeprefix("notes/"): digest for n, digest in checks.items() if n.startswith("notes/")}
            if note_hashes == fitness_files:
                if json.loads(read(control / "state.json", 32 * 1024 * 1024)) != state:
                    raise ValueError("Fitness changed during backup")
                return raw
    raise ValueError("No fitness-owner archive matches the hub snapshot; wait for owner backup or repair it")


def recovery_source(root):
    output = io.BytesIO()
    files = [*root.glob("memory_hub/*.py"), *root.glob("memory_hub/*.json"),
             *root.glob("scripts/*.py"), *root.glob("scripts/fitness_migration/*.py"),
             root / "pyproject.toml", root / "uv.lock", root / "docs/hub-recovery.md"]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.writestr(path.relative_to(root).as_posix(), read(path, 2 * 1024 * 1024))
    return output.getvalue()


def create(root, key_path, destination):
    root, destination = safe(root), safe(destination)
    vault, key_path = safe(root / "vault"), safe(key_path)
    if destination == vault or vault in destination.parents:
        raise ValueError("Encrypted backups must be outside the vault")
    if key_path == destination or destination in key_path.parents or vault in key_path.parents:
        raise ValueError("Recovery key must be separate from the vault and upload directory")
    key = key_at(key_path, create=True)
    # All plaintext working copies stay in the ignored, private local runtime.
    staging = safe(root / ".runtime/encrypted-backup-work")
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as tmp:
        scratch = Path(tmp)
        controls = {"skill_control": root / ".runtime/skill-memory", "general_control": root / ".runtime/general-memory"}
        for path in controls.values():
            if not path.is_dir():
                raise ValueError("Required capture control is missing")
        hub = backup(root / "vault", scratch / "snapshots", **controls)
        components = {"hub.zip": read(Path(hub["archive"]), LIMIT), "recovery-tools.zip": recovery_source(root)}
        fitness = root / ".runtime/live/fitness"
        if (root / "vault/Projects/local-fitness").exists():
            components["fitness.zip"] = matching_fitness(fitness, hub["archive"])
        encrypted = pack(components, key)
        if unpack(encrypted, key) != components:
            raise ValueError("Encrypted readback mismatch")
        name = "memory-recovery-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".fernet"
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = destination / name
        exclusive_create(path, encrypted)
    result = {"status": "encrypted", "path": str(path), "sha256": sha(encrypted),
              "bytes": len(encrypted), "components": sorted(components), "verified": True,
              "key_path": str(key_path), "cloud_verified": False,
              "key_recovery": "Save the recovery key separately off this Mac; never upload it beside this archive."}
    atomic(root / ".runtime/encrypted-backup-status.json", json.dumps(result, indent=2).encode())
    return result


def recover(archive, key_path, quarantine):
    quarantine = safe(quarantine)
    if quarantine.exists() or not quarantine.parent.is_dir():
        raise ValueError("Restore requires a new quarantine under an existing directory")
    components = unpack(read(safe(archive), LIMIT * 2), key_at(key_path))
    quarantine.mkdir(mode=0o700)
    for name, raw in components.items():
        exclusive_create(quarantine / name, raw)
    result = {"activated": False, "hub": restore(quarantine / "hub.zip", quarantine / "hub")}
    if "fitness.zip" in components:
        result["fitness"] = restore_fitness(quarantine / "fitness.zip", quarantine / "fitness")
    result["review"] = "Reconcile current forgetting ledgers and capture receipts, validate fitness ownership, and review before promotion."
    return result


if __name__ == "__main__":
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["create", "restore"])
    p.add_argument("--key", type=Path, default=ROOT / ".runtime/recovery-key.txt")
    p.add_argument("--destination", type=Path, default=ROOT / ".runtime/drive-outbox")
    p.add_argument("--archive", type=Path)
    p.add_argument("--quarantine", type=Path)
    a = p.parse_args()
    if a.command == "restore" and (not a.archive or not a.quarantine):
        p.error("restore requires --archive and --quarantine")
    result = create(ROOT, a.key, a.destination) if a.command == "create" else recover(a.archive, a.key, a.quarantine)
    print(json.dumps(result, indent=2))
