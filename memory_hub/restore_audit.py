"""Read-only comparison of restored capture receipts with current authoritative files."""
import hashlib
import json
from pathlib import PurePosixPath
import re
import uuid

from .skill_store import read, safe


def receipt_snapshot(control, vault):
    control, vault = safe(control), safe(vault)
    if not control.is_dir() or not vault.is_dir():
        raise ValueError("Current control and vault must exist")
    receipts = {}
    folder = safe(control / "receipts")
    activity_folder = safe(control / "activity/receipts")
    paths = sorted(folder.glob("*.json")) + sorted(activity_folder.glob("*.json"))
    if len(paths) > 10000:
        raise ValueError("Too many capture receipts")
    for path in paths:
        cid = str(uuid.UUID(path.stem))
        if cid != path.stem:
            raise ValueError("Invalid receipt ID")
        raw = read(safe(path), 16384)
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("version") != 1:
            raise ValueError("Invalid receipt version")
        relative = record.get("path")
        activity = path.parent == activity_folder
        valid_path = isinstance(relative, str) and bool(re.fullmatch(
            (r"Activity/\d{4}-\d{2}/" if activity else r"(?:Inbox|Preferences|Projects/(?!local-fitness/)[a-z0-9][a-z0-9._-]{0,79})/")
            + re.escape(cid) + r"\.md", relative))
        if not valid_path:
            raise ValueError("Invalid capture destination")
        if record.get("phase") not in {"pending", "committed"}:
            raise ValueError("Invalid capture phase")
        for field in ("request_sha256", "content_sha256"):
            if not isinstance(record.get(field), str) or not re.fullmatch("[0-9a-f]{64}", record[field]):
                raise ValueError("Invalid capture digest")
        note = safe(vault / PurePosixPath(relative))
        note_hash = hashlib.sha256(read(note, 65536)).hexdigest() if note.exists() else None
        receipts[("activity:" if activity else "capture:") + cid] = {"receipt_sha256": hashlib.sha256(raw).hexdigest(), "record": record,
                         "current_file_sha256": note_hash}
    return receipts


def audit_general(quarantine, current_control, current_vault):
    """Never authorize promotion; known receipt histories only, no inferred deletions."""
    quarantine, current_control, current_vault = map(safe, (quarantine, current_control, current_vault))
    for current in (current_control, current_vault):
        if current == quarantine or quarantine in current.parents or current in quarantine.parents:
            raise ValueError("Current state must be independent of quarantine")
    restored_vault = safe(quarantine / "vault")
    restored_control = safe(quarantine / "general-control")
    # Empty control directories are not archive members; v3 may legitimately omit one.
    old = receipt_snapshot(restored_control, restored_vault) if restored_control.exists() else {}
    if not restored_vault.is_dir():
        raise ValueError("Restored vault missing")
    live = receipt_snapshot(current_control, current_vault)
    issues = []
    for cid in sorted(set(old) | set(live)):
        prior, current = old.get(cid), live.get(cid)
        path = (prior or current)["record"]["path"]
        reasons = []
        if prior is None:
            reasons.append("capture_not_in_snapshot")
        elif current is None:
            reasons.append("current_receipt_missing")
        if prior:
            if prior["record"]["phase"] == "pending":
                reasons.append("restored_capture_pending")
            if prior["current_file_sha256"] != prior["record"]["content_sha256"]:
                reasons.append("restored_file_missing_or_changed")
        if current:
            if current["record"]["phase"] == "pending":
                reasons.append("current_capture_pending")
            if current["current_file_sha256"] is None:
                reasons.append("current_file_missing_do_not_resurrect")
            elif current["current_file_sha256"] != current["record"]["content_sha256"]:
                reasons.append("current_file_edited")
            if prior and prior["record"] != current["record"]:
                reasons.append("receipt_changed")
            if prior and prior["current_file_sha256"] != current["current_file_sha256"]:
                reasons.append("snapshot_differs_from_current_file")
        if reasons:
            issues.append({"path": path, "reasons": reasons})
    if live != receipt_snapshot(current_control, current_vault):
        raise ValueError("Current capture state changed during audit")
    if restored_control.exists() and old != receipt_snapshot(restored_control, restored_vault):
        raise ValueError("Restored capture state changed during audit")
    return {"status": "review_required", "activated": False, "restored_receipts": len(old),
            "current_receipts": len(live), "issues": issues[:50], "issue_count": len(issues),
            "omitted_issues": max(0, len(issues) - 50),
            "coverage": "Receipt-managed captures and activity only; older native/manual notes require separate review."}
