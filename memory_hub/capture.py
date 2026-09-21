"""General memory capture: validated, immutable creates with durable retry receipts.

Receipts contain hashes, never note bodies. A committed-but-missing note is never
recreated. A pending receipt without a file requires inspection, not blind replay.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

import yaml

from .recall import SUBJECTS, identity, resolve, scan
from .skill_store import atomic, read, safe
from .projects import subjects as registered_subjects

KEYS = {
    "global": {"preferences.memory-hub.openai-auth", "preferences.memory-hub.central-activity"},
    "local-memory": {"project.local-memory.handoff"},
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def locked(control):
    control = safe(control)
    control.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(safe(control / "writer.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def exclusive_create(path, raw):
    """Publish a complete, fsynced file without replacing any existing destination."""
    path = safe(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".capture-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path, follow_symlinks=False)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temp)


def validate(request, subjects=SUBJECTS):
    allowed = {"project", "subject", "title", "body", "source", "kind", "status",
               "capture_id", "review_after", "key", "supersedes"}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError("UNKNOWN_CAPTURE_FIELD")
    r = {"project": "local-memory", "status": "candidate", "kind": "decision", **request}
    if r["project"] != "local-memory" or r.get("subject") not in subjects:
        raise ValueError("UNREGISTERED_SUBJECT")
    if r["kind"] not in {"decision", "preference", "handoff"} or r["status"] not in {"candidate", "active"}:
        raise ValueError("INVALID_KIND_OR_STATUS")
    for field, limit in (("title", 160), ("body", 6144), ("source", 512)):
        if not isinstance(r.get(field), str) or not r[field].strip() or len(r[field].encode()) > limit:
            raise ValueError("INVALID_" + field.upper())
        r[field] = r[field].strip()
    cid = r.get("capture_id")
    if not isinstance(cid, str) or str(uuid.UUID(cid)) != cid:
        raise ValueError("CANONICAL_CAPTURE_UUID_REQUIRED")
    for field in ("review_after", "key", "supersedes"):
        if r.get(field) is None:
            r.pop(field, None)
    if "review_after" in r:
        if not isinstance(r["review_after"], str):
            raise ValueError("INVALID_REVIEW_DATE")
        date.fromisoformat(r["review_after"])
    allowed_keys = KEYS.get(r["subject"], set()) | ({"project." + r["subject"] + ".handoff"} if r['subject'] != 'global' else set())
    if r.get("key") is not None and r["key"] not in allowed_keys:
        raise ValueError("UNREGISTERED_CORRECTION_KEY")
    if "supersedes" in r and (not isinstance(r["supersedes"], str) or not r.get("key")):
        raise ValueError("CORRECTION_REQUIRES_KEY_AND_IDENTITY")
    return r


class CaptureStore:
    def __init__(self, vault, control):
        self.vault, self.control = safe(vault), safe(control)
        if self.vault == self.control or self.vault in self.control.parents or self.control in self.vault.parents:
            raise ValueError("CONTROL_MUST_BE_SEPARATE")

    def capture(self, request):
        try:
            return self._capture(validate(request, registered_subjects(self.vault)))
        except (ValueError, TypeError, KeyError) as error:
            return {"status": "rejected", "error": str(error), "verified": False}
        except yaml.YAMLError:
            return {"status": "rejected", "error": "MALFORMED_MANAGED_METADATA", "verified": False}
        except OSError:
            return {"status": "unavailable", "error": "CAPTURE_IO_FAILURE", "verified": False}

    def _capture(self, r):
        if not self.vault.is_dir():
            raise OSError("Missing vault")
        fingerprint = digest(json.dumps(r, sort_keys=True, ensure_ascii=False).encode())
        cid = r["capture_id"]
        with locked(self.control):
            receipt_path = safe(self.control / "receipts" / (cid + ".json"))
            if receipt_path.exists():
                receipt = json.loads(read(receipt_path))
                if receipt.get("request_sha256") != fingerprint:
                    raise ValueError("CAPTURE_ID_CONFLICT")
                if receipt.get("phase") not in {"pending", "committed"}:
                    raise ValueError("INVALID_RECEIPT")
                relative = receipt.get("path", "")
                if relative != destination(r):
                    raise ValueError("INVALID_RECEIPT_PATH")
                path = safe(self.vault / relative)
                if not path.exists():
                    raise ValueError("CAPTURE_MISSING_REVIEW_REQUIRED")
                if digest(read(path, 16384)) != receipt.get("content_sha256"):
                    raise ValueError("CAPTURE_CHANGED_REVIEW_REQUIRED")
                receipt["phase"] = "committed"
                atomic(receipt_path, json.dumps(receipt).encode())
                return self.result(r, receipt, "already_created")

            today = date.today()
            review = r.get("review_after")
            if review and date.fromisoformat(review) < today:
                raise ValueError("OVERDUE_CAPTURE")
            if r["kind"] == "handoff":
                review = review or (today + timedelta(days=7)).isoformat()
                if date.fromisoformat(review) > today + timedelta(days=30):
                    raise ValueError("HANDOFF_REVIEW_EXCEEDS_30_DAYS")
            rows = scan(self.vault)  # Broken managed records must not conceal corrections.
            if any(row["meta"].get("capture_id") == cid for row in rows):
                raise ValueError("CAPTURE_ID_EXISTS_WITHOUT_RECEIPT")
            family = [row for row in rows if row["meta"].get("project") == r["subject"]
                      and row["meta"].get("status") == "active" and r.get("key")
                      and row["meta"].get("key") == r["key"]]
            if r["status"] == "active" and family:
                terminal = resolve(family)
                aliases = {terminal["path"], terminal["meta"].get("permalink"), terminal["meta"].get("capture_id")}
                if identity(r.get("supersedes", "")) not in aliases:
                    raise ValueError("CORRECTION_MUST_SUPERSEDE_CURRENT")
            elif r.get("supersedes"):
                raise ValueError("CORRECTION_PARENT_NOT_ACTIVE")
            stamp = datetime.now(timezone.utc).isoformat()
            relative = destination(r)
            meta = {"title": r["title"], "type": "note", "kind": r["kind"], "project": r["subject"],
                    "status": r["status"], "source": r["source"], "capture_id": cid,
                    "permalink": "local-memory/" + relative[:-3].lower(), "created": stamp, "modified": stamp}
            for field in ("key", "supersedes"):
                if field in r:
                    meta[field] = r[field]
            if review:
                meta["review_after"] = review
            raw = ("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n" + r["body"] + "\n").encode()
            receipt = {"version": 1, "request_sha256": fingerprint, "content_sha256": digest(raw),
                       "path": relative, "identity": meta["permalink"], "phase": "pending"}
            path = safe(self.vault / relative)
            if path.exists():
                raise ValueError("DESTINATION_EXISTS")
            atomic(receipt_path, json.dumps(receipt).encode())
            exclusive_create(path, raw)
            if read(path, 16384) != raw:
                raise ValueError("READBACK_MISMATCH")
            receipt["phase"] = "committed"
            atomic(receipt_path, json.dumps(receipt).encode())
            return self.result(r, receipt, "created")

    @staticmethod
    def result(r, receipt, status):
        return {"status": status, "capture_id": r["capture_id"], "path": receipt["path"],
                "identity": receipt["identity"], "revision": receipt["content_sha256"],
                "note_status": r["status"], "verified": True}


def destination(r):
    folder = "Inbox" if r["status"] == "candidate" else "Preferences" if r["subject"] == "global" else "Projects/" + r["subject"]
    return folder + "/" + r["capture_id"] + ".md"
