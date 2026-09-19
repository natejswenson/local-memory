#!/usr/bin/env python3
"""Activate a verified, frozen migration snapshot into a new single-writer store.

This refuses existing destinations. Stop/drain legacy writers before invoking it.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from memory_hub.fitness_store import FitnessStore, atomic, safe  # noqa: E402
from stage import verify  # noqa: E402


def initialize(snapshot, vault, control, fitness_repo, port=8766):
    snapshot = safe(snapshot)
    vault = safe(vault)
    control = safe(control)
    result = verify(snapshot)
    if result["unparsed_lines"]:
        raise ValueError(
            "Unparsed preferences require explicit disposition before cutover"
        )
    if vault.exists() or control.exists():
        raise ValueError("Existing vault/control destination; refusing to re-import")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    vault.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copytree(snapshot / "staged", vault)
    control.mkdir(mode=0o700, parents=True)
    state = {
        "schema": 1,
        "store_id": str(uuid.uuid4()),
        "vault": str(vault),
        "allocation_floor": manifest["allocation_floor"],
        "revision": 0,
        "receipts": {},
        "import_snapshot": manifest["snapshot_id"],
    }
    atomic(control / "state.json", json.dumps(state).encode())
    atomic(control / "token", secrets.token_urlsafe(48).encode())
    # Parent is private (0700); the explicitly mounted token must be readable by
    # the container's non-host UID. The bind mount itself is read-only.
    (control / "token").chmod(0o644)
    config = {
        "control": str(control),
        "vault": str(vault),
        "token_file": str(control / "token"),
        "fitness_repo": str(safe(fitness_repo)),
        "bind": "127.0.0.1",
        "port": port,
        "backup_dir": str(control / "backups"),
    }
    atomic(control / "config.json", json.dumps(config, indent=2).encode())
    sys.path.insert(0, str(Path(fitness_repo) / "src"))
    from local_fitness import notes
    from local_fitness.agent import journal

    store = FitnessStore(vault, control, notes, journal, config["backup_dir"])
    store.backup()
    return {
        "initialized": True,
        "records": len(store.load()),
        "control": str(control),
        "vault": str(vault),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "vault", "control", "fitness-repo"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--port", type=int, default=8766)
    a = p.parse_args()
    os.umask(0o077)
    print(
        json.dumps(
            initialize(a.snapshot, a.vault, a.control, a.fitness_repo, a.port), indent=2
        )
    )
