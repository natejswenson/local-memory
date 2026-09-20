"""Opt-in Markdown preferences and source-first writing mirrors for trusted clients.

Skill identity is routing, not a security principal. Shared-profile consent is
required in private configuration. Never use this store for restricted sharing.
"""

from __future__ import annotations
from contextlib import contextmanager
from datetime import date, timedelta
import stat
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from .skill_contract import (
    CONTRACT,
    RATIONALE,
    canonical,
    digest,
    policies,
    validate_value,
)

MAX_NOTE = 16384


def safe(path):
    p = Path(os.path.abspath(path))
    for part in (p, *p.parents):
        if part.is_symlink():
            raise ValueError("UNSAFE_PATH")
    return p


def read(path, limit=MAX_NOTE):
    p = safe(path)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError("UNSAFE_FILE")
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("OVERSIZE")
    return raw


def atomic(path, raw):
    p = safe(path)
    safe(p.parent).mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=p.parent, prefix=".skill-memory-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, p)
        fd = os.open(p.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def put(path, value):
    atomic(path, (canonical(value) + "\n").encode())


def valid_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("INVALID_ID")
    return value


class SkillStore:
    def __init__(self, vault, control):
        self.vault = safe(vault)
        self.control = safe(control)
        self.notes = safe(self.vault / "SkillMemory")

    def config(self):
        p = self.control / "config.json"
        if not safe(p).exists():
            return {"version": 1, "bindings": {}}
        c = json.loads(read(p, 262144))
        if (
            not isinstance(c, dict)
            or c.get("version") != 1
            or not isinstance(c.get("bindings"), dict)
        ):
            raise ValueError("INVALID_CONFIG")
        return c

    @contextmanager
    def locked(self):
        safe(self.control).mkdir(parents=True, exist_ok=True, mode=0o700)
        p = safe(self.control / "writer.lock")
        fd = os.open(p, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("BUSY")
            yield

    def binding(self, skill, subject):
        if skill not in policies():
            raise ValueError("UNKNOWN_SKILL")
        if not isinstance(subject, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,79}", subject
        ):
            raise ValueError("INVALID_SUBJECT")
        subjects = self.config()["bindings"].get(skill, {})
        if not isinstance(subjects, dict):
            raise ValueError("INVALID_BINDING")
        b = subjects.get(subject, {})
        if not isinstance(b, dict):
            raise ValueError("INVALID_BINDING")
        if policies()[skill]["mode"] == "deferred" or b.get("enabled") is not True:
            return None
        if b.get("shared_profile") is not True:
            raise ValueError("SHARING_NOT_ACKNOWLEDGED")
        return b

    def source(self, b):
        p = b.get("source_path")
        if not isinstance(p, str) or not Path(p).is_absolute():
            raise ValueError("SOURCE_UNREGISTERED")
        path = safe(p)
        if (
            path == self.vault
            or self.vault in path.parents
            or self.control in path.parents
        ):
            raise ValueError("UNSAFE_SOURCE")
        return path, read(path, 1024 * 1024)

    def scope(self, skill, subject):
        if skill not in policies():
            raise ValueError("UNKNOWN_SKILL")
        return safe(self.notes / skill / digest(subject))

    def path(self, id, skill, subject):
        return safe(self.scope(skill, subject) / (valid_id(id) + ".md"))

    def record(self, path):
        raw = read(path)
        text = raw.decode()
        if not text.startswith("---\n"):
            raise ValueError("INVALID_NOTE")
        front, body = text[4:].split("\n---\n", 1)
        r = json.loads(front)
        if not isinstance(r, dict):
            raise ValueError("INVALID_NOTE")
        if r.get("contract") != CONTRACT or r.get("id") != path.stem:
            raise ValueError("INVALID_NOTE")
        # JSON frontmatter is also valid YAML. Body holds the editable value.
        value = body[:-1] if body.endswith("\n") else body
        if r.get("value_type") != "string":
            value = json.loads(value)
        r["value"] = validate_value(r["skill"], r["key"], value)
        r["revision"] = digest(raw)
        return r

    def encode(self, r):
        m = {k: v for k, v in r.items() if k not in ("value", "revision")}
        m["value_type"] = "string" if isinstance(r["value"], str) else "json"
        body = r["value"] if isinstance(r["value"], str) else canonical(r["value"])
        return (
            "---\n"
            + json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n---\n"
            + body
            + "\n"
        ).encode()

    def forgotten(self):
        path = safe(self.control / "forgotten.json")
        ledger = json.loads(read(path, 1024 * 1024)) if path.exists() else {}
        if not isinstance(ledger, dict) or any(
            not isinstance(v, dict) for v in ledger.values()
        ):
            raise ValueError("INVALID_LEDGER")
        return ledger

    def suppressed(self, id):
        return valid_id(id) in self.forgotten()

    def dependencies(self, r, b):
        if r["key"] not in RATIONALE:
            if "dependencies" in r or "review_after" in r:
                raise ValueError("IRRELEVANT_METADATA")
            return
        deps = r.get("dependencies")
        expiry = r.get("review_after")
        if not isinstance(deps, list) or not 1 <= len(deps) <= 8:
            raise ValueError("DEPENDENCIES_REQUIRED")
        when = date.fromisoformat(expiry)
        if not date.today() <= when <= date.today() + timedelta(days=30):
            raise ValueError("STALE_EVIDENCE")
        base = b.get("repo_path")
        if not isinstance(base, str) or not Path(base).is_absolute():
            raise ValueError("REPOSITORY_UNREGISTERED")
        base = safe(base)
        for dep in deps:
            if not isinstance(dep, dict) or set(dep) != {"path", "revision"}:
                raise ValueError("INVALID_DEPENDENCY")
            rel = dep["path"]
            if (
                not isinstance(rel, str)
                or Path(rel).is_absolute()
                or ".." in Path(rel).parts
            ):
                raise ValueError("INVALID_DEPENDENCY")
            if digest(read(safe(base / rel), 1024 * 1024)) != dep["revision"]:
                raise ValueError("STALE_EVIDENCE")

    def records(self, skill, subject):
        directory = self.scope(skill, subject)
        if not directory.exists():
            return []
        paths = list(directory.glob("*.md"))
        forgotten = self.forgotten()
        if len(paths) > 2000:
            raise ValueError("CAPACITY")
        result = []
        for p in paths:
            if p.stem in forgotten:
                continue
            r = self.record(p)
            if r.get("skill") == skill and r.get("subject") == subject:
                if r.get("status") != "active":
                    raise ValueError("INACTIVE_NOTE")
                result.append(r)
        return result

    def current(self, records, key):
        rows = [r for r in records if r["key"] == key]
        ids = {r["id"] for r in rows}
        replaced = set()
        for r in rows:
            old = r.get("supersedes")
            if old:
                if old not in ids or old == r["id"]:
                    raise ValueError("CONFLICT")
                replaced.add(old)
        terminals = [r for r in rows if r["id"] not in replaced]
        # Cycles, disconnected chains, and forks cannot select a winner.
        if len(terminals) != 1:
            if rows:
                raise ValueError("CONFLICT")
            return None
        visited = set()
        node = terminals[0]
        while node:
            if node["id"] in visited:
                raise ValueError("CONFLICT")
            visited.add(node["id"])
            parent = node.get("supersedes")
            node = (
                next((r for r in rows if r["id"] == parent), None) if parent else None
            )
        if visited != ids:
            raise ValueError("CONFLICT")
        return terminals[0]

    def public(self, r):
        return {
            k: r[k]
            for k in ("id", "key", "value", "source", "revision", "source_revision")
            if k in r
        }

    def recall(self, q, b):
        keys = q.get("keys")
        policy = policies()[q["skill"]]
        if (
            not isinstance(keys, list)
            or not 1 <= len(keys) <= 8
            or len(set(keys)) != len(keys)
            or any(k not in policy["keys"] + policy["read_keys"] for k in keys)
        ):
            raise ValueError("KEY_NOT_ALLOWED")
        budget = q.get("max_context_bytes", 4096)
        if type(budget) is not int or not 256 <= budget <= 4096:
            raise ValueError("INVALID_BUDGET")
        result = {
            "status": "ok",
            "records": [],
            "conflict_keys": [],
            "withheld_keys": [],
            "trust": "untrusted-data",
        }
        for key in keys:
            owner, subject, ownerb = q["skill"], q["subject"], b
            try:
                if key in policy["read_keys"] or key in b.get("reads", {}):
                    selection = b.get("reads", {}).get(key)
                    if not isinstance(selection, dict):
                        raise ValueError("SHARING_UNREGISTERED")
                    owner, subject = selection["skill"], selection["subject"]
                    ownerb = self.binding(owner, subject)
                    if not ownerb or q["skill"] not in ownerb.get("readers", []):
                        raise ValueError("SHARING_UNREGISTERED")
                    # Consumer must select the exact configured voice file, and verify its revision.
                    if policies()[owner]["mode"] == "owner":
                        selected, _ = self.source(b)
                        owned, body = self.source(ownerb)
                        if selected != owned or q.get(
                            "expected_source_revision"
                        ) != digest(body):
                            raise ValueError("SOURCE_STALE")
                    elif key in RATIONALE:
                        if not b.get("repo_path") or safe(b["repo_path"]) != safe(
                            ownerb.get("repo_path", "")
                        ):
                            raise ValueError("REPOSITORY_UNREGISTERED")
                r = self.current(self.records(owner, subject), key)
                if not r:
                    continue
                self.dependencies(r, ownerb)
                if policies()[owner]["mode"] == "owner":
                    _, body = self.source(ownerb)
                    if r.get("source_revision") != digest(body):
                        raise ValueError("SOURCE_STALE")
                    receipt = json.loads(
                        read(self.control / "events" / f"{r['id']}.json", 32768)
                    )
                    if receipt.get("note_digest") != r["revision"]:
                        raise ValueError("MIRROR_CHANGED")
                item = self.public(r)
                candidate = {**result, "records": result["records"] + [item]}
                if len(canonical(candidate).encode()) > budget:
                    result["withheld_keys"].append(key)
                else:
                    result["records"].append(item)
            except (ValueError, KeyError, TypeError, OSError):
                result["conflict_keys"].append(key)
        if result["conflict_keys"]:
            result["status"] = "conflict"
        while len(canonical(result).encode()) > budget and result["records"]:
            result["withheld_keys"].append(result["records"].pop()["key"])
        if len(canonical(result).encode()) > budget:
            return {
                "status": "conflict",
                "error": "CONTEXT_BUDGET_EXCEEDED",
                "records": [],
            }
        return result

    def inspect(self, q, b):
        """Maintenance handles, including stale evidence; never advice context."""
        keys = q.get("keys")
        if (
            not isinstance(keys, list)
            or not 1 <= len(keys) <= 8
            or any(k not in policies()[q["skill"]]["keys"] for k in keys)
        ):
            raise ValueError("KEY_NOT_ALLOWED")
        if any(k in b.get("reads", {}) for k in keys):
            raise ValueError("OWNER_REQUIRED")
        result = {
            "status": "inspection",
            "records": [],
            "trust": "maintenance-handles-only",
        }
        result["conflict_keys"] = []
        rows = self.records(q["skill"], q["subject"])
        for key in dict.fromkeys(keys):
            try:
                r = self.current(rows, key)
            except ValueError:
                result["conflict_keys"].append(key)
                continue
            if r is None:
                continue
            item = {k: r[k] for k in ("id", "key", "revision", "source")}
            item["state"] = "current"
            item["evidence_state"] = "valid"
            try:
                self.dependencies(r, b)
                if policies()[q["skill"]]["mode"] == "owner":
                    _, body = self.source(b)
                    receipt = json.loads(
                        read(self.control / "events" / f"{r['id']}.json", 32768)
                    )
                    if (
                        r.get("source_revision") != digest(body)
                        or receipt.get("note_digest") != r["revision"]
                    ):
                        item["evidence_state"] = "stale"
            except (ValueError, KeyError, TypeError, OSError, AttributeError):
                item["evidence_state"] = "stale"
            result["records"].append(item)
            if len(canonical(result).encode()) > 4096:
                return {
                    "status": "conflict",
                    "error": "INSPECTION_CAPACITY_REQUEST_FEWER_KEYS",
                    "records": [],
                }
        return result

    def recover_event(self, event, path, b):
        r = event["record"]
        if event.get("source_revision"):
            _, body = self.source(b)
            if digest(body) != event["source_revision"]:
                return {"status": "conflict", "error": "SOURCE_STALE"}
        if self.suppressed(r["id"]):
            return {"status": "conflict", "error": "FORGOTTEN_EVENT"}
        self.dependencies(r, b)
        prior = self.current(
            [
                row
                for row in self.records(r["skill"], r["subject"])
                if row["id"] != r["id"]
            ],
            r["key"],
        )
        if (prior and r.get("supersedes") != prior["id"]) or (
            not prior and r.get("supersedes")
        ):
            return {"status": "conflict", "error": "LINEAGE_CHANGED"}
        target = self.path(r["id"], r["skill"], r["subject"])
        raw = self.encode(r)
        if len(raw) > MAX_NOTE:
            raise ValueError("OVERSIZE")
        if target.exists() and read(target) != raw:
            return {"status": "conflict", "error": "DESTINATION_CHANGED"}
        atomic(target, raw)
        observed = self.record(target)
        if observed["value"] != r["value"]:
            raise ValueError("READBACK_FAILED")
        event["phase"] = "complete"
        event.pop("record", None)
        event["result"] = {
            "status": "saved",
            "record": self.public(observed),
            "verified": True,
        }
        # Complete receipt stores no body; repeat read-back is from Markdown.
        event["result"].pop("record")
        put(path, event)
        return {"status": "saved", "record": self.public(observed), "verified": True}

    def capture(self, q, b):
        key = q.get("key")
        value = validate_value(q["skill"], key, q.get("value"))
        if key in b.get("reads", {}):
            raise ValueError("OWNER_REQUIRED")
        id = valid_id(q.get("capture_id"))
        path = safe(self.control / "events" / f"{id}.json")
        fingerprint = digest(canonical(q))
        if path.exists():
            event = json.loads(read(path, 32768))
            if not isinstance(event, dict):
                raise ValueError("INVALID_EVENT")
            if event.get("fingerprint") != fingerprint:
                return {"status": "conflict", "error": "CAPTURE_ID_REUSED"}
            if self.suppressed(id):
                return {"status": "conflict", "error": "FORGOTTEN_EVENT"}
            if event["phase"] == "complete":
                if (
                    event.get("source_revision")
                    and digest(self.source(b)[1]) != event["source_revision"]
                ):
                    return {"status": "conflict", "error": "SOURCE_STALE"}
                observed = self.record(self.path(id, q["skill"], q["subject"]))
                if (
                    digest(self.encode({**observed, "revision": None}))
                    != event["note_digest"]
                ):
                    return {"status": "conflict", "error": "DESTINATION_CHANGED"}
                return {
                    "status": "saved",
                    "record": self.public(observed),
                    "verified": True,
                }
            return self.recover_event(event, path, b)
        old = self.current(self.records(q["skill"], q["subject"]), key)
        if (old and q.get("supersedes") != old["id"]) or (
            not old and q.get("supersedes")
        ):
            raise ValueError("CORRECTION_REQUIRES_CURRENT_ID")
        source = q.get("source")
        if (
            not isinstance(source, str)
            or not source.strip()
            or len(source.encode()) > 512
        ):
            raise ValueError("INVALID_PROVENANCE")
        r = {
            "contract": CONTRACT,
            "id": id,
            "skill": q["skill"],
            "subject": q["subject"],
            "key": key,
            "value": value,
            "source": source,
            "status": "active",
            "created": date.today().isoformat(),
        }
        for k in ("dependencies", "review_after", "supersedes"):
            if k in q:
                r[k] = q[k]
        self.dependencies(r, b)
        event = {"fingerprint": fingerprint, "phase": "prepared", "record": r}
        source_body = None
        if policies()[q["skill"]]["mode"] == "owner":
            source_path, body = self.source(b)
            before = digest(body)
            if q.get("expected_source_revision") != before:
                raise ValueError("SOURCE_STALE")
            source_body = (
                body
                + b"\n\n"
                + value.encode()
                + f"\n<!-- skill-memory-event:{id} -->\n".encode()
            )
            if len(source_body) > 1024 * 1024:
                raise ValueError("SOURCE_CAPACITY")
            r["source_revision"] = digest(source_body)
            event.update(source_before=before, source_revision=r["source_revision"])
        encoded = self.encode(r)
        if len(encoded) > MAX_NOTE:
            raise ValueError("OVERSIZE")
        event["note_digest"] = digest(encoded)
        put(
            path, event
        )  # Durable before source replacement; retry never blindly overwrites source.
        if source_body is not None:
            if digest(read(source_path, 1024 * 1024)) != event["source_before"]:
                return {"status": "conflict", "error": "SOURCE_STALE"}
            try:
                atomic(source_path, source_body)
                if read(source_path, 1024 * 1024) != source_body:
                    raise ValueError("SOURCE_READBACK_FAILED")
                event["phase"] = "source_committed"
                put(path, event)
            except OSError:
                if read(source_path, 1024 * 1024) == source_body:
                    return {
                        "status": "source_saved_memory_pending",
                        "capture_id": id,
                        "source_revision": r["source_revision"],
                    }
                raise
        try:
            return self.recover_event(event, path, b)
        except OSError:
            if source_body is not None:
                return {
                    "status": "source_saved_memory_pending",
                    "capture_id": id,
                    "source_revision": r["source_revision"],
                }
            raise

    def finish_forget(self, ledger, operation, skill, subject):
        for id, item in ledger.items():
            if (
                item.get("operation") != operation
                or item["skill"] != skill
                or item["subject"] != subject
            ):
                continue
            self.path(id, skill, subject).unlink(missing_ok=True)
            event = safe(self.control / "events" / f"{id}.json")
            if event.exists():
                put(event, {"phase": "forgotten"})
        return {
            "status": "forgotten",
            "source_retained": True,
            "backup_retention": "Backups may retain data; keep suppression ledger on restore.",
        }

    def forget(self, q, b):
        id = valid_id(q.get("id"))
        ledger = self.forgotten()
        if id in ledger:
            prior = ledger[id]
            if any(
                prior[k] != v
                for k, v in {
                    "skill": q["skill"],
                    "subject": q["subject"],
                    "revision": q.get("expected_revision"),
                }.items()
            ):
                raise ValueError("STALE_HANDLE")
            return self.finish_forget(
                ledger, prior["operation"], q["skill"], q["subject"]
            )
        r = self.record(self.path(id, q["skill"], q["subject"]))
        if (
            r["skill"] != q["skill"]
            or r["subject"] != q["subject"]
            or r["revision"] != q.get("expected_revision")
        ):
            raise ValueError("STALE_HANDLE")
        rows = self.records(q["skill"], q["subject"])
        current = self.current(rows, r["key"])
        if current is None or current["id"] != id:
            raise ValueError("NOT_CURRENT")
        for row in rows:
            if row["key"] == r["key"]:
                ledger[row["id"]] = {
                    "skill": q["skill"],
                    "subject": q["subject"],
                    "revision": row["revision"],
                    "operation": id,
                }
        # One atomic intent suppresses the whole lineage before any note is removed.
        if len(canonical(ledger).encode()) > 1024 * 1024:
            raise ValueError("CAPACITY")
        put(self.control / "forgotten.json", ledger)
        return self.finish_forget(ledger, id, q["skill"], q["subject"])

    def request(self, q):
        try:
            if not isinstance(q, dict) or len(canonical(q).encode()) > 32768:
                raise ValueError("INVALID_REQUEST")
            op = q.get("op")
            common = {"contract", "skill", "subject", "op"}
            fields = {
                "status": set(),
                "inspect": {"keys"},
                "recall": {"keys", "max_context_bytes", "expected_source_revision"},
                "capture": {
                    "key",
                    "value",
                    "capture_id",
                    "source",
                    "supersedes",
                    "dependencies",
                    "review_after",
                    "expected_source_revision",
                },
                "forget": {"id", "expected_revision"},
            }
            if (
                q.get("contract") != CONTRACT
                or op not in fields
                or set(q) - common - fields[op]
            ):
                raise ValueError("INVALID_REQUEST")
            b = self.binding(q.get("skill"), q.get("subject"))
            if b is None:
                return {"status": "disabled"}
            if op == "status":
                result = {
                    "status": "ready",
                    "backend": "obsidian",
                    "contract": CONTRACT,
                }
                if policies()[q["skill"]]["mode"] == "owner" or b.get("source_path"):
                    _, body = self.source(b)
                    result["source_revision"] = digest(body)
                return result
            with self.locked():
                if op == "recall":
                    return self.recall(q, b)
                if op == "inspect":
                    return self.inspect(q, b)
                if op == "capture":
                    return self.capture(q, b)
                return self.forget(q, b)
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as e:
            # Never return filesystem paths or user-provided text in errors.
            code = str(e)
            code = code if re.fullmatch(r"[A-Z_]{1,64}", code) else "INVALID_DATA"
            return {
                "status": "unavailable"
                if code == "BUSY"
                else "conflict"
                if code
                in (
                    "CONFLICT",
                    "SOURCE_STALE",
                    "STALE_HANDLE",
                    "CORRECTION_REQUIRES_CURRENT_ID",
                )
                else "rejected",
                "error": code,
            }
        except OSError:
            return {"status": "unavailable", "error": "STORAGE_UNAVAILABLE"}
