#!/usr/bin/env python3
"""Prepare a complete candidate note; create only on --apply, never overwrite."""
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.recall import SUBJECTS
from memory_hub.projects import subjects as registered_subjects
from memory_hub.skill_store import read, safe


def prepare(*, title, subject, kind, source, body, capture_id=None, review_after=None, key=None, subjects=SUBJECTS):
    if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 160
            or subject not in subjects or kind not in {"decision", "preference", "handoff"}
            or not isinstance(source, str) or not 1 <= len(source.strip().encode()) <= 512
            or not isinstance(body, str) or not body.strip() or len(body.encode()) > 8192):
        raise ValueError("Title, registered subject, kind, source and a body up to 8192 bytes are required")
    capture_id = capture_id or str(uuid.uuid4())
    if str(uuid.UUID(capture_id)) != capture_id:
        raise ValueError("capture_id must be a canonical UUID")
    if kind == "handoff" and not review_after:
        review_after = (date.today() + timedelta(days=7)).isoformat()
    if review_after and date.fromisoformat(review_after) < date.today():
        raise ValueError("Draft review date must not already be overdue")
    if kind == "handoff" and date.fromisoformat(review_after) > date.today() + timedelta(days=30):
        raise ValueError("Handoffs must be reviewed within 30 days")
    m = {"title": title.strip(), "type": "note", "kind": kind, "project": subject,
         "status": "candidate", "source": source.strip(), "capture_id": capture_id,
         "permalink": f"local-memory/inbox/{capture_id}"}
    if review_after:
        m["review_after"] = review_after
    if key:
        if not isinstance(key, str) or not 1 <= len(key) <= 160:
            raise ValueError("Invalid correction key")
        m["key"] = key
    return {"capture_id": capture_id, "path": f"Inbox/{capture_id}.md",
            "content": "---\n" + json.dumps(m, ensure_ascii=False, indent=2) + "\n---\n\n" + body.strip() + "\n"}


def create(vault, draft):
    vault = safe(vault)
    if not vault.is_dir():
        raise ValueError("Vault does not exist")
    expected_path = f"Inbox/{draft['capture_id']}.md"
    if str(uuid.UUID(draft["capture_id"])) != draft["capture_id"] or draft["path"] != expected_path:
        raise ValueError("Invalid candidate destination")
    path = safe(vault / expected_path)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    raw = draft["content"].encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if read(path, 16384) != raw:
            raise ValueError("Capture ID already has different content; nothing overwritten")
        return {"status": "already_created", "capture_id": draft["capture_id"], "path": expected_path, "verified": True}
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if read(path, 16384) != raw:
        raise ValueError("Readback mismatch; inspect before retry")
    return {"status": "candidate_created", "capture_id": draft["capture_id"], "path": expected_path, "verified": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vault", type=Path, default=ROOT / "vault")
    p.add_argument("--title", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--kind", choices=["decision", "preference", "handoff"], required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--capture-id")
    p.add_argument("--review-after")
    p.add_argument("--key")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    draft = prepare(title=a.title, subject=a.subject, kind=a.kind, source=a.source,
                    body=sys.stdin.read(8193), capture_id=a.capture_id, review_after=a.review_after, key=a.key,
                    subjects=registered_subjects(a.vault))
    print(json.dumps(create(a.vault, draft) if a.apply else {"status": "preview", **draft}, ensure_ascii=False))
