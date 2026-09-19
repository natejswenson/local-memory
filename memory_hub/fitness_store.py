"""Markdown authority with one host writer and recoverable multi-file commits.

Business rules are delegated to local-fitness using disposable legacy-shaped
workspaces. SQLite here is a temporary query/execution index, never authority.
"""

from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import uuid
import zipfile

MAX_NOTE = 128 * 1024
SCHEMA = """CREATE TABLE coach_journal(entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
created_at TEXT,entry_date TEXT,source TEXT,source_key TEXT,seq INTEGER,text TEXT,archived INTEGER DEFAULT 0);
CREATE UNIQUE INDEX event_key ON coach_journal(source,source_key,seq) WHERE source_key IS NOT NULL;"""
READS = {
    "notes.read_notes",
    "notes.render_for_prompt",
    "journal.list_entries",
    "journal.has_event",
    "journal.search_entries",
    "revision",
    "snapshot",
}
WRITES = {
    "notes.append_note",
    "notes.update_note",
    "notes.delete_note",
    "journal.save_entry",
    "journal.delete_entry",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink memory paths are refused")
    return path


def atomic(path, data):
    path = safe(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".memory-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def encode(meta, text):
    return ("---\n" + json.dumps(meta, ensure_ascii=False) + "\n---\n" + text).encode()


def decode(raw):
    if len(raw) > MAX_NOTE or not raw.startswith(b"---\n"):
        raise ValueError("Invalid or oversized memory note")
    front, body = raw[4:].split(b"\n---\n", 1)

    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("Duplicate metadata key")
            result[k] = v
        return result

    try:
        meta = json.loads(front, object_pairs_hook=pairs)
    except json.JSONDecodeError:
        import yaml

        class Loader(yaml.SafeLoader):
            pass

        def mapping(loader, node):
            return pairs(loader.construct_pairs(node))

        Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        meta = yaml.load(front, Loader=Loader)
    if not isinstance(meta, dict):
        raise ValueError("Invalid metadata")
    return meta, body.decode("utf-8")


class FitnessStore:
    def __init__(self, vault, control, notes, journal, backup_dir=None):
        self.vault = safe(vault)
        self.control = safe(control)
        self.notes = notes
        self.journal = journal
        self.backup_dir = safe(backup_dir) if backup_dir else None
        self.lock = threading.RLock()
        if not self.vault.is_dir():
            raise ValueError("Memory vault is missing")
        self.state_path = self.control / "state.json"
        self.pending = self.control / "pending.json"
        if not self.state_path.is_file():
            raise ValueError(
                "Memory store is not initialized; refusing an empty fallback"
            )
        self.recover()
        self.load()

    def state(self):
        state = json.loads(self.state_path.read_text())
        if state.get("schema") != 1 or state.get("vault") != str(self.vault):
            raise ValueError("Memory control state/vault mismatch")
        return state

    def load(self, folder=None, *, root=None, state=None):
        state = self.state() if state is None else state
        vault = self.vault if root is None else safe(root)
        records = {}
        identifiers = set()
        events = set()
        ids = set()
        if not vault.is_dir():
            raise ValueError("Memory vault is missing")
        for required in ("Preferences", "Journal"):
            if not safe(vault / required).is_dir():
                raise ValueError("Memory record directory is missing")
        positions = set()
        base = safe(vault / folder) if folder else vault
        for path in sorted(base.rglob("*")):
            safe(path)
            if path.is_dir():
                continue
            if path.suffix != ".md":
                raise ValueError("Unexpected file in fitness record subtree")
            if path.stat().st_size > 65536:
                raise ValueError("Oversized fitness record")
            raw = path.read_bytes()
            meta, text = decode(raw)
            text = text.rstrip("\n")
            record_id = meta.get("capture_id")
            if (
                meta.get("fitness_schema") != 1
                or meta.get("owner") != "local-fitness"
                or meta.get("project") != "local-fitness"
                or meta.get("status") not in ("active", "archived")
                or not isinstance(record_id, str)
                or str(uuid.UUID(record_id)) != record_id
                or record_id in identifiers
            ):
                raise ValueError("Invalid or duplicate fitness identity/lifecycle")
            kind = meta.get("kind")
            folder = {"preference": "Preferences", "coach-journal": "Journal"}.get(kind)
            if (
                folder is None
                or path.relative_to(vault).as_posix() != f"{folder}/{record_id}.md"
            ):
                raise ValueError(
                    "Fitness note moved or identity changed; repair required"
                )
            expected = f"projects/local-fitness/{folder.lower()}/{record_id}"
            if meta.get("permalink") != expected:
                raise ValueError("Invalid fitness permalink")
            if kind == "preference":
                if (
                    not isinstance(meta.get("fitness_timestamp"), str)
                    or type(meta.get("fitness_position")) is not int
                ):
                    raise ValueError("Invalid preference metadata")
                position = (meta["status"], meta["fitness_position"])
                if position in positions:
                    raise ValueError("Duplicate preference position")
                positions.add(position)
                if "\n" in text or not text.strip():
                    raise ValueError("Preference body must be one nonempty line")
            else:
                for field in ("fitness_entry_id", "fitness_seq"):
                    if type(meta.get(field)) is not int or meta[field] < 1:
                        raise ValueError("Invalid journal integer identity")
                for field in (
                    "fitness_created_at",
                    "fitness_entry_date",
                    "fitness_source",
                ):
                    if not isinstance(meta.get(field), str):
                        raise ValueError("Invalid journal date/source")
                if (
                    meta["fitness_source"] not in self.journal.VALID_SOURCES
                    or not 0 < len(text.strip()) <= 240
                ):
                    raise ValueError("Invalid journal body/source")
                key = meta.get("fitness_source_key")
                if key is not None and not isinstance(key, str):
                    raise ValueError("Invalid event key")
                event = (meta["fitness_source"], key, meta["fitness_seq"])
                if meta["fitness_entry_id"] in ids or (
                    key is not None and event in events
                ):
                    raise ValueError("Duplicate journal ID/event")
                if meta["fitness_entry_id"] > state["allocation_floor"]:
                    raise ValueError("Journal allocation history mismatch")
                ids.add(meta["fitness_entry_id"])
                events.add(event)
            identifiers.add(record_id)
            records[path.relative_to(vault).as_posix()] = (meta, text, raw)
        return records

    def validate_candidate(self, records, state):
        """Apply the same restart/read invariants before acknowledging a write."""
        with tempfile.TemporaryDirectory(prefix="fitness-candidate-") as temp:
            root = Path(temp).resolve()
            for folder in ("Preferences", "Journal"):
                (root / folder).mkdir()
            for relative, (_, _, raw) in records.items():
                parts = Path(relative).parts
                if len(parts) != 2 or parts[0] not in ("Preferences", "Journal"):
                    raise ValueError("Unsafe candidate record path")
                (root / relative).write_bytes(raw)
            self.load(root=root, state=state)

    def result_records(self, result, records):
        """Bind content-bearing acknowledgments to exact live record revisions."""
        references = {}
        if isinstance(result, dict) and "text" in result:
            for key, (meta, text, raw) in records.items():
                if text != result["text"]:
                    continue
                if (
                    meta["kind"] == "preference"
                    and result.get("handle")
                    == self.notes._handle(meta["fitness_timestamp"], text)
                ) or (
                    meta["kind"] == "coach-journal"
                    and result.get("entry_id") == meta["fitness_entry_id"]
                ):
                    references[key] = sha(raw)
            return references or None
        if isinstance(result, (list, tuple)):
            for item in result:
                found = self.result_records(item, records)
                if found is None:
                    return None
                references.update(found)
        return references

    def retire_receipts(self, state, records):
        """Keep retry identity, but erase results invalidated by edits/deletion.

        Replaying a retired request raises ValueError, never recreates a record.
        Historical backup retention remains a separate deletion boundary.
        """
        changed = False
        for request_id, receipt in state["receipts"].items():
            if receipt.get("retired"):
                continue
            refs = receipt.get("records")
            if refs is None:
                refs = self.result_records(receipt.get("result"), records)
            if refs is None or any(
                k not in records or sha(records[k][2]) != digest
                for k, digest in refs.items()
            ):
                state["receipts"][request_id] = {
                    "fingerprint": receipt["fingerprint"],
                    "retired": True,
                }
                changed = True
        return changed

    def recover(self):
        if not self.pending.exists():
            return
        pending = json.loads(self.pending.read_text())
        if pending.get("store_id") != self.state()["store_id"]:
            raise ValueError("Pending transaction belongs to another store")
        for relative, change in pending["changes"].items():
            parts = Path(relative).parts
            if (
                len(parts) != 2
                or parts[0] not in ("Preferences", "Journal")
                or Path(relative).suffix != ".md"
            ):
                raise ValueError("Unsafe pending transaction path")
            path = safe(self.vault / relative)
            before = sha(path.read_bytes()) if path.exists() else None
            after = change["after"]
            after_hash = sha(after.encode()) if after is not None else None
            if before not in (change["before"], after_hash):
                raise ValueError(
                    "Manual edit conflicts with pending transaction; preserved for recovery"
                )
            if after is None:
                path.unlink(missing_ok=True)
                fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            elif before != after_hash:
                atomic(path, after.encode())
        atomic(self.state_path, json.dumps(pending["state"]).encode())
        self.pending.unlink()
        fd = os.open(self.control, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def commit(self, before, after, state):
        changes = {}
        for path in before.keys() | after.keys():
            previous = before[path][2] if path in before else None
            current = after[path][2] if path in after else None
            if previous != current:
                live = safe(self.vault / path)
                actual = live.read_bytes() if live.exists() else None
                if actual != previous:
                    raise ValueError("Concurrent manual edit; retry after validation")
                changes[path] = {
                    "before": sha(previous) if previous is not None else None,
                    "after": current.decode() if current is not None else None,
                }
        atomic(
            self.pending,
            json.dumps(
                {"store_id": state["store_id"], "changes": changes, "state": state}
            ).encode(),
        )
        self.recover()

    def backup(self):
        if not self.backup_dir:
            return
        self.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        state = self.state()
        records = self.load()
        digest = sha(
            "".join(k + sha(v[2]) for k, v in sorted(records.items())).encode()
        )[:16]
        target = (
            self.backup_dir
            / f"fitness-{state['store_id']}-{state['revision']:012d}-{digest}.zip"
        )
        if target.exists():
            return
        fd, tmp = tempfile.mkstemp(dir=self.backup_dir, prefix=".fitness-")
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
                entries = {
                    "state.json": json.dumps(state).encode(),
                    **{f"notes/{k}": v[2] for k, v in records.items()},
                }
                for name, data in entries.items():
                    archive.writestr(name, data)
                archive.writestr(
                    "checksums.json",
                    json.dumps({k: sha(v) for k, v in entries.items()}),
                )
            with open(tmp, "rb") as stream:
                os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        for old in sorted(
            self.backup_dir.glob(f"fitness-{state['store_id']}-*.zip"),
            key=lambda p: p.stat().st_mtime_ns,
        )[:-14]:
            old.unlink()

    def request(self, operation, args, request_id=None):
        if operation not in READS | WRITES:
            raise ValueError("Unsupported memory operation")
        with self.lock:
            self.recover()
            state = self.state()
            folder = (
                ("Preferences" if operation.startswith("notes.") else "Journal")
                if operation in READS and operation not in ("revision", "snapshot")
                else None
            )
            records = self.load(folder)
            if operation == "revision":
                return sha(
                    "".join(k + sha(v[2]) for k, v in sorted(records.items())).encode()
                )
            if operation == "snapshot":
                return {k: {"metadata": v[0], "text": v[1]} for k, v in records.items()}
            fingerprint = sha(json.dumps([operation, args], sort_keys=True).encode())
            if operation in WRITES:
                if not request_id or str(uuid.UUID(request_id)) != request_id:
                    raise ValueError("A UUID request_id is required for writes")
                receipt = state["receipts"].get(request_id)
                if receipt:
                    if receipt["fingerprint"] != fingerprint:
                        raise ValueError("Request ID reused with another payload")
                    if self.retire_receipts(state, records):
                        atomic(self.state_path, json.dumps(state).encode())
                    if state["receipts"][request_id].get("retired"):
                        raise ValueError(
                            "Request retired after record update or deletion"
                        )
                    return receipt["result"]
            with tempfile.TemporaryDirectory(prefix="fitness-memory-") as temp:
                result, after, floor = self.execute(
                    operation, args, records, Path(temp), state["allocation_floor"]
                )
            if operation in WRITES:
                state["allocation_floor"] = floor
                self.validate_candidate(after, state)
                self.retire_receipts(state, after)
                state["revision"] += 1
                state["receipts"][request_id] = {
                    "fingerprint": fingerprint,
                    "result": result,
                    "records": self.result_records(result, after),
                }
                self.commit(records, after, state)
                # Backup failure must not turn a committed write into an apparent failure.
                try:
                    self.backup()
                except Exception:
                    import logging

                    logging.exception("Fitness memory committed, but backup failed")
            return result

    def execute(self, operation, args, records, temp, floor):
        after = dict(records)
        if operation.startswith("notes."):
            paths = {
                "active": temp / "user_notes.md",
                "archived": temp / "user_notes.archive.md",
            }
            grouped = {
                s: sorted(
                    [
                        (k, v)
                        for k, v in records.items()
                        if v[0]["kind"] == "preference" and v[0]["status"] == s
                    ],
                    key=lambda x: x[1][0]["fitness_position"],
                )
                for s in paths
            }
            for status, path in paths.items():
                path.write_text(
                    "".join(
                        f"- {m['fitness_timestamp']} — {t}\n"
                        if m["fitness_timestamp"]
                        else f"- {t}\n"
                        for _, (m, t, _) in grouped[status]
                    )
                )
            name = operation.split(".")[1]
            result = getattr(self.notes, name)(**args, path=paths["active"])
            if name == "read_notes":
                result = [asdict(n) for n in result]
            elif name == "append_note":
                result = asdict(result)
            elif name == "update_note" and result is not None:
                result = [asdict(result[0]), result[1]]
            if operation in READS:
                return result, after, floor
            old = {}
            for key, value in records.items():
                if value[0]["kind"] == "preference":
                    old.setdefault(
                        (value[0]["fitness_timestamp"], value[1]), []
                    ).append((key, value))
                    after.pop(key)
            updated_record = None
            if name in ("update_note", "delete_note") and result is not None:
                selected = next(
                    (
                        (k, v)
                        for k, v in grouped["active"]
                        if self.notes._handle(v[0]["fitness_timestamp"], v[1])
                        == args["handle"]
                    ),
                    None,
                )
                if selected:
                    k, v = selected
                    old[(v[0]["fitness_timestamp"], v[1])].remove(selected)
                    updated_record = (k, v[0])
            for status, path in paths.items():
                for n in self.notes.read_notes(path):
                    matches = old.get((n.timestamp, n.text), [])
                    if matches:
                        key, (meta, _, _) = matches.pop(0)
                        meta = dict(meta)
                    else:
                        # An update changes its revision handle, while record identity stays stable.
                        if (
                            name == "update_note"
                            and status == "active"
                            and result
                            and n.handle == result[0]["handle"]
                            and updated_record
                        ):
                            key, meta = updated_record
                            meta = dict(meta)
                        else:
                            key, meta = self.new_record("Preferences")
                    meta.update(
                        status=status,
                        fitness_timestamp=n.timestamp,
                        fitness_position=n.position,
                    )
                    after[key] = (meta, n.text, encode(meta, n.text))
            return result, after, floor
        database = temp / "journal.db"
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.executescript(SCHEMA)
            for meta, text, _ in records.values():
                if meta["kind"] == "coach-journal":
                    conn.execute(
                        "INSERT INTO coach_journal VALUES(?,?,?,?,?,?,?,?)",
                        (
                            meta["fitness_entry_id"],
                            meta["fitness_created_at"],
                            meta["fitness_entry_date"],
                            meta["fitness_source"],
                            meta["fitness_source_key"],
                            meta["fitness_seq"],
                            text,
                            int(meta["status"] == "archived"),
                        ),
                    )
            conn.execute("DELETE FROM sqlite_sequence WHERE name='coach_journal'")
            conn.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES('coach_journal',?)",
                (floor,),
            )
            try:
                conn.executescript(self.journal.db.FTS_SCHEMA)
                conn.execute(
                    "INSERT INTO coach_journal_fts(coach_journal_fts) VALUES('rebuild')"
                )
            except sqlite3.OperationalError:
                pass
        result = getattr(self.journal, operation.split(".")[1])(
            **args, db_path=database
        )
        if operation in READS:
            return result, after, floor
        old = {
            v[0]["fitness_entry_id"]: (k, v[0])
            for k, v in records.items()
            if v[0]["kind"] == "coach-journal"
        }
        for key in list(after):
            if after[key][0]["kind"] == "coach-journal":
                after.pop(key)
        with closing(sqlite3.connect(database)) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT * FROM coach_journal"):
                key, meta = old.get(row["entry_id"]) or self.new_record("Journal")
                meta = dict(meta)
                meta.update(
                    status="archived" if row["archived"] else "active",
                    **{
                        f"fitness_{k}": row[k]
                        for k in (
                            "entry_id",
                            "created_at",
                            "entry_date",
                            "source",
                            "source_key",
                            "seq",
                        )
                    },
                )
                after[key] = (meta, row["text"], encode(meta, row["text"]))
            floor = conn.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='coach_journal'"
            ).fetchone()[0]
        return result, after, floor

    @staticmethod
    def new_record(folder):
        identity = str(uuid.uuid4())
        return f"{folder}/{identity}.md", {
            "title": f"Fitness {folder.lower()} {identity}",
            "type": "note",
            "permalink": f"projects/local-fitness/{folder.lower()}/{identity}",
            "project": "local-fitness",
            "owner": "local-fitness",
            "capture_id": identity,
            "fitness_schema": 1,
            "kind": "preference" if folder == "Preferences" else "coach-journal",
            "source": "local-fitness tools",
        }
