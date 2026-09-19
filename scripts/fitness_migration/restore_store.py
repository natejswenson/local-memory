#!/usr/bin/env python3
"""Restore a fitness backup to NEW, private quarantine paths; never switches clients."""

import argparse
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from memory_hub.fitness_store import atomic, safe, sha  # noqa: E402


def restore(archive, destination):
    archive = safe(archive)
    destination = safe(destination)
    if destination.exists():
        raise ValueError("Restore destination must not exist")
    with zipfile.ZipFile(archive) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError("Duplicate backup member")
        checks = json.loads(z.read("checksums.json"))
        if set(z.namelist()) != set(checks) | {"checksums.json"}:
            raise ValueError("Unexpected backup members")
        entries = {}
        for name, digest in checks.items():
            path = Path(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or (
                    name != "state.json"
                    and not (
                        len(path.parts) == 3
                        and path.parts[0] == "notes"
                        and path.parts[1] in ("Preferences", "Journal")
                        and path.suffix == ".md"
                    )
                )
            ):
                raise ValueError("Unsafe backup path")
            if z.getinfo(name).file_size > 32 * 1024 * 1024:
                raise ValueError("Oversized member")
            data = z.read(name)
            if sha(data) != digest:
                raise ValueError("Backup checksum mismatch")
            entries[name] = data
    state = json.loads(entries.pop("state.json"))
    vault = destination / "vault"
    control = destination / "control"
    for path in (control, vault / "Preferences", vault / "Journal"):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    state["vault"] = str(vault)
    for name, data in entries.items():
        atomic(vault / Path(name).relative_to("notes"), data)
    atomic(control / "state.json", json.dumps(state).encode())
    return {
        "restored": True,
        "vault": str(vault),
        "control": str(control),
        "records": len(entries),
        "activated": False,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    a = p.parse_args()
    os.umask(0o077)
    print(json.dumps(restore(a.archive, a.destination), indent=2))
