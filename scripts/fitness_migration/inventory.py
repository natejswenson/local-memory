#!/usr/bin/env python3
"""Read-only fitness migration inventory; output contains no note text or secrets."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import sqlite3
from contextlib import closing
import sys

PATH_KEYS = ("LOCAL_FITNESS_DATA_DIR", "LOCAL_FITNESS_NOTES_PATH")


def load_notes(repo):
    spec = importlib.util.spec_from_file_location(
        "fitness_migration_notes", repo / "src/local_fitness/notes.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def inventory(repo, settings, launch_agents=None):
    repo = Path(repo).resolve()
    notes_module = load_notes(repo)
    data = Path(settings.get("LOCAL_FITNESS_DATA_DIR") or repo / "data")
    live = Path(settings.get("LOCAL_FITNESS_NOTES_PATH") or data / "user_notes.md")
    if not data.is_absolute() or not live.is_absolute():
        raise ValueError(
            "Relative deployment paths require an explicit working-directory audit"
        )
    result = {
        "schema": 1,
        "repo": str(repo),
        "data": str(data),
        "preferences": [],
        "jobs": [],
        "scope": "read-only; no cutover approval",
    }
    for path in (live, notes_module._archive_path(live)):
        if path.is_symlink():
            raise ValueError("Symlink source needs explicit migration handling")
        raw = path.read_bytes() if path.exists() else b""
        text = raw.decode("utf-8")
        parsed = [notes_module._parse_line(line) for line in text.splitlines()]
        handles = [n.handle for n in parsed if n is not None]
        result["preferences"].append(
            {
                "path": str(path),
                "exists": path.exists(),
                "bytes": len(raw),
                "parsed_notes": len(handles),
                "duplicate_handles": len(handles) - len(set(handles)),
                "nonblank_unparsed_lines": sum(
                    bool(line.strip()) and note is None
                    for line, note in zip(text.splitlines(), parsed)
                ),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    database = data / "fitness.db"
    # Never create a missing DB and never invoke schema migrations during inventory.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        with conn:
            conn.execute("BEGIN")
            counts = conn.execute(
                "SELECT archived, COUNT(*) FROM coach_journal GROUP BY archived"
            ).fetchall()
            floor = conn.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='coach_journal'"
            ).fetchone()
            result["journal"] = {
                "path": str(database),
                "counts_by_archived": dict(counts),
                "allocation_floor": floor[0] if floor else 0,
            }
    if launch_agents:
        for path in sorted(Path(launch_agents).glob("com.localfitness*.plist")):
            try:
                job = plistlib.loads(path.read_bytes())
                result["jobs"].append(
                    {
                        "file": path.name,
                        "valid_plist": True,
                        "label": job.get("Label"),
                        "working_directory": job.get("WorkingDirectory"),
                        "path_overrides": {
                            k: job.get("EnvironmentVariables", {}).get(k)
                            for k in PATH_KEYS
                        },
                    }
                )
            except Exception as exc:
                result["jobs"].append(
                    {
                        "file": path.name,
                        "valid_plist": False,
                        "error_class": type(exc).__name__,
                    }
                )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--launch-agents", type=Path)
    args = parser.parse_args()
    from dotenv import dotenv_values

    settings = {**dotenv_values(args.repo / ".env"), **os.environ}
    report = inventory(args.repo, settings, args.launch_agents)
    # Exclusive output avoids silently replacing previous migration evidence.
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
