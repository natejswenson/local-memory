#!/usr/bin/env python3
"""Snapshot and stage fitness prose privately. Deliberately has no live apply mode."""

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import uuid

from inventory import inventory, load_notes


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink paths are not supported")
    return path


def write_private(path, raw):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


def encode_note(metadata, text):
    # JSON object syntax is also YAML, without date coercion or hand-built escaping.
    return (
        "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n" + text
    ).encode()


def decode_note(raw):
    prefix, encoded, text = raw.decode("utf-8").split("\n", 2)
    if prefix != "---" or not text.startswith("---\n"):
        raise ValueError("Invalid staged note framing")
    return json.loads(encoded), text[4:]


def snapshot(repo, settings, output):
    report = inventory(repo, settings)
    live = safe_path(report["preferences"][0]["path"])
    archive = safe_path(report["preferences"][1]["path"])
    database = safe_path(report["journal"]["path"])
    output = safe_path(output)
    for source in (live, archive, database):
        if output == source or source in output.parents:
            raise ValueError("Output overlaps source")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    source_dir = output / "source"
    source_dir.mkdir(mode=0o700)
    # Same persistent lock pathname as notes.py; never truncate/unlink the lock.
    lock = safe_path(live.with_name(live.name + ".lock"))
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for src, name in ((live, "user_notes.md"), (archive, "user_notes.archive.md")):
            raw = src.read_bytes() if src.exists() else b""
            write_private(source_dir / name, raw)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(source_dir / "fitness.db")) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise ValueError("SQLite backup integrity check failed")
        (source_dir / "fitness.db").chmod(0o600)
    finally:
        os.close(fd)
    # The snapshot is immutable input. Rebuild a new staging directory after changes;
    # never guess how moving preference line positions map across snapshots.
    snapshot_id = str(uuid.uuid4())
    manifest = {
        "schema": 1,
        "snapshot_id": snapshot_id,
        "mode": "staged-only",
        "source_files": {p.name: digest(p.read_bytes()) for p in source_dir.iterdir()},
        "original_paths": {
            "live": str(live),
            "archive": str(archive),
            "database": str(database),
        },
    }
    write_private(
        output / "snapshot.json", (json.dumps(manifest, indent=2) + "\n").encode()
    )
    return output


def stage(repo, snapshot_dir):
    snapshot_dir = safe_path(snapshot_dir)
    spec = json.loads((snapshot_dir / "snapshot.json").read_text())
    source_dir = snapshot_dir / "source"
    for name, checksum in spec["source_files"].items():
        if (
            Path(name).name != name
            or digest((source_dir / name).read_bytes()) != checksum
        ):
            raise ValueError("Source snapshot changed")
    destination = snapshot_dir / "staged"
    destination.mkdir(mode=0o700, exist_ok=False)
    for name in ("Preferences", "Journal"):
        (destination / name).mkdir(mode=0o700)
    notes = load_notes(Path(repo))
    namespace = uuid.UUID(spec["snapshot_id"])
    records, unparsed = [], []

    def emit(kind, identity, text, status, extra):
        record_id = str(uuid.uuid5(namespace, identity))
        relative = f"{kind}/{record_id}.md"
        metadata = {
            "title": f"Fitness {kind.lower()} {record_id}",
            "type": "note",
            "permalink": f"projects/local-fitness/{kind.lower()}/{record_id}",
            "project": "local-fitness",
            "owner": "local-fitness",
            "status": status,
            "capture_id": record_id,
            "fitness_schema": 1,
            "kind": "preference" if kind == "Preferences" else "coach-journal",
            "source": "local-fitness migration snapshot",
            **extra,
        }
        raw = encode_note(metadata, text)
        write_private(destination / relative, raw)
        records.append(
            {
                "identity": identity,
                "path": relative,
                "sha256": digest(raw),
                "text_sha256": digest(text.encode()),
                "status": status,
                "capture_id": record_id,
            }
        )

    for name, status in (
        ("user_notes.md", "active"),
        ("user_notes.archive.md", "archived"),
    ):
        for ordinal, line in enumerate((source_dir / name).read_text().splitlines()):
            parsed = notes._parse_line(line)
            if parsed is None:
                if line.strip():
                    unparsed.append({"source": name, "line": ordinal})
                continue
            emit(
                "Preferences",
                f"{name}:{ordinal}",
                parsed.text,
                status,
                {"fitness_timestamp": parsed.timestamp, "fitness_position": ordinal},
            )
    database = source_dir / "fitness.db"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM coach_journal ORDER BY entry_id").fetchall()
        floor = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='coach_journal'"
        ).fetchone()
        for row in rows:
            r = dict(row)
            emit(
                "Journal",
                f"coach_journal:{r['entry_id']}",
                r["text"],
                "archived" if r["archived"] else "active",
                {
                    "fitness_entry_id": r["entry_id"],
                    "fitness_created_at": r["created_at"],
                    "fitness_entry_date": r["entry_date"],
                    "fitness_source": r["source"],
                    "fitness_source_key": r["source_key"],
                    "fitness_seq": r["seq"],
                },
            )
    manifest = {
        **spec,
        "records": records,
        "unparsed": unparsed,
        "allocation_floor": floor[0] if floor else 0,
        "counts": dict(Counter(r["path"].split("/")[0] for r in records)),
        "eligible_for_cutover": False,
        "reason": "Storage adapter, shared write/read guards and runtime gates not yet verified",
    }
    write_private(
        snapshot_dir / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode()
    )
    verify(snapshot_dir)
    return manifest


def verify(snapshot_dir):
    snapshot_dir = safe_path(snapshot_dir)
    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    source = snapshot_dir / "source"
    for name, expected in manifest["source_files"].items():
        if Path(name).name != name or digest((source / name).read_bytes()) != expected:
            raise ValueError("Source snapshot checksum mismatch")
    observed_ids = set()
    for row in manifest["records"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe manifest path")
        path = safe_path(snapshot_dir / "staged" / relative)
        raw = path.read_bytes()
        meta, text = decode_note(raw)
        if digest(raw) != row["sha256"] or digest(text.encode()) != row["text_sha256"]:
            raise ValueError("Staged record checksum mismatch")
        if (
            meta["capture_id"] != row["capture_id"]
            or meta["capture_id"] in observed_ids
        ):
            raise ValueError("Duplicate or mismatched identity")
        observed_ids.add(meta["capture_id"])
    actual = {
        str(p.relative_to(snapshot_dir / "staged"))
        for p in (snapshot_dir / "staged").rglob("*.md")
    }
    if actual != {r["path"] for r in manifest["records"]}:
        raise ValueError("Unexpected or missing staged files")
    return {
        "verified_records": len(observed_ids),
        "counts": manifest["counts"],
        "unparsed_lines": len(manifest["unparsed"]),
        "allocation_floor": manifest["allocation_floor"],
        "eligible_for_cutover": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["prepare", "verify"])
    p.add_argument("--repo", type=Path)
    p.add_argument("--directory", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    # Never stage private records inside a live Obsidian vault.
    root = Path(__file__).resolve().parents[2]
    output = safe_path(args.directory)
    if root / "vault" == output or root / "vault" in output.parents:
        p.error("Staging must be outside the live vault")
    if args.command == "prepare":
        if not args.repo:
            p.error("--repo is required for prepare")
        from dotenv import dotenv_values

        settings = {**dotenv_values(args.repo / ".env"), **os.environ}
        snapshot(args.repo, settings, output)
        stage(args.repo, output)
    print(json.dumps(verify(output), indent=2))


if __name__ == "__main__":
    main()
