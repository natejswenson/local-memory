#!/usr/bin/env python3
"""Export a stopped/restored vault to NEW legacy-shaped files, never a live DB.

The journal.sqlite artifact contains only journal rows and allocation history.
Operational measurements/settings must never be rolled back from a stale full DB.
"""

from contextlib import closing
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from memory_hub.fitness_store import FitnessStore, SCHEMA, atomic, safe  # noqa: E402


def export(store, destination):
    destination = safe(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    with store.lock:
        store.recover()
        records = store.load()
        state = store.state()
        for status, name in (
            ("active", "user_notes.md"),
            ("archived", "user_notes.archive.md"),
        ):
            selected = sorted(
                (
                    v
                    for v in records.values()
                    if v[0]["kind"] == "preference" and v[0]["status"] == status
                ),
                key=lambda v: v[0]["fitness_position"],
            )
            text = "".join(
                f"- {m['fitness_timestamp']} — {t}\n"
                if m["fitness_timestamp"]
                else f"- {t}\n"
                for m, t, _ in selected
            )
            atomic(destination / name, text.encode())
        with closing(sqlite3.connect(destination / "journal.sqlite")) as conn, conn:
            conn.executescript(SCHEMA)
            for m, t, _ in records.values():
                if m["kind"] == "coach-journal":
                    conn.execute(
                        "INSERT INTO coach_journal VALUES(?,?,?,?,?,?,?,?)",
                        (
                            m["fitness_entry_id"],
                            m["fitness_created_at"],
                            m["fitness_entry_date"],
                            m["fitness_source"],
                            m["fitness_source_key"],
                            m["fitness_seq"],
                            t,
                            int(m["status"] == "archived"),
                        ),
                    )
            conn.execute("DELETE FROM sqlite_sequence WHERE name='coach_journal'")
            conn.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES('coach_journal',?)",
                (state["allocation_floor"],),
            )
        (destination / "journal.sqlite").chmod(0o600)
        atomic(
            destination / "export.json",
            json.dumps(
                {
                    "store_id": state["store_id"],
                    "revision": state["revision"],
                    "records": len(records),
                    "live_applied": False,
                }
            ).encode(),
        )
    return {"exported": True, "records": len(records), "live_applied": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("vault", "control", "destination", "fitness-repo"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    os.umask(0o077)
    sys.path.insert(0, str(a.fitness_repo / "src"))
    from local_fitness import notes
    from local_fitness.agent import journal

    print(
        json.dumps(
            export(FitnessStore(a.vault, a.control, notes, journal), a.destination),
            indent=2,
        )
    )
