#!/usr/bin/env python3
"""Read-only audit of a v2/v3 quarantine against CURRENT controls; never promote."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.skill_store import SkillStore, read, safe


def audit(quarantine, current_control, current_general=None, current_vault=None):
    try:
        quarantine, current_control = safe(quarantine), safe(current_control)
        if (quarantine == current_control or quarantine in current_control.parents
                or current_control in quarantine.parents):
            raise ValueError("Current control must be outside quarantine")
        vault, old_control = safe(quarantine / "vault"), safe(quarantine / "skill-control")
        if not vault.is_dir() or not old_control.is_dir() or not current_control.is_dir():
            raise ValueError("Expected version 2 quarantine and current control")
        live_config = read(current_control / "config.json", 262144)
        ledger_path = safe(current_control / "forgotten.json")
        ledger_bytes = read(ledger_path, 1024 * 1024) if ledger_path.exists() else b"{}"
        current = SkillStore(vault, current_control)
        current.config()
        ledger = current.forgotten()
        restored = SkillStore(vault, old_control)
        restored.config()  # Validate configuration before interpreting notes.
        notes = list(restored.notes.rglob("*.md"))
        if len(notes) > 10000:
            raise ValueError("Too many records")
        suppressed, invalid = [], []
        for path in notes:
            safe(path)
            # Suppression is by stable filename ID even if a historical body is malformed.
            if path.stem in ledger:
                suppressed.append(path.relative_to(quarantine).as_posix())
                continue
            try:
                record = restored.record(path)
                if restored.path(record["id"], record["skill"], record["subject"]) != path:
                    raise ValueError("Record destination mismatch")
            except (ValueError, TypeError, KeyError, OSError):
                invalid.append(path.relative_to(quarantine).as_posix())
        events = list(safe(old_control / "events").glob("*.json"))
        if len(events) > 10000:
            raise ValueError("Too many events")
        pending = 0
        for path in events:
            event = json.loads(read(path, 32768))
            if not isinstance(event, dict) or event.get("phase") not in {"complete", "forgotten"}:
                pending += 1
        same_config = read(old_control / "config.json", 262144) == live_config
        # Do not present an audit based on a ledger/configuration that changed during it.
        if ((read(ledger_path, 1024 * 1024) if ledger_path.exists() else b"{}") != ledger_bytes
                or read(current_control / "config.json", 262144) != live_config):
            raise ValueError("Current control changed")
        general = {"status": "not_checked", "reason": "Supply current general control and vault"}
        if (current_general is None) != (current_vault is None):
            raise ValueError("General audit requires both current paths")
        if current_general is not None:
            from memory_hub.restore_audit import audit_general
            general = audit_general(quarantine, current_general, current_vault)
        return {"status": "review_required", "activated": False, "records_checked": len(notes),
                "general_capture_audit": general,
                "current_ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
                "suppressed_records": suppressed[:50], "suppressed_count": len(suppressed),
                "invalid_records": invalid[:50], "invalid_count": len(invalid),
                "pending_recovery_events": pending, "configuration_matches_current": same_config,
                "next": "Preserve current suppression and configuration. Revalidate sources and reconcile pending events before any promotion."}
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "unavailable", "error": "RESTORE_OR_CURRENT_CONTROL_INVALID", "activated": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quarantine", type=Path, required=True)
    p.add_argument("--current-control", type=Path, default=ROOT / ".runtime/skill-memory")
    p.add_argument("--current-general", type=Path)
    p.add_argument("--current-vault", type=Path)
    a = p.parse_args()
    result = audit(a.quarantine, a.current_control, a.current_general, a.current_vault)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "review_required" else 1)
