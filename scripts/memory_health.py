#!/usr/bin/env python3
"""Read-only general-note quality and backup-age summary; no note bodies in output."""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.recall import eligible
from memory_hub.maintenance import catalog
from memory_hub.skill_store import safe
import yaml


def health(vault, backups=None, details=False, limit=20):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Detail limit must be 1–50")
    try:
        inventory = catalog(vault)
        rows = inventory["rows"]
        quality = Counter()
        for row in rows:
            m = row["meta"]
            quality[eligible(row, date.today()) or "valid_metadata"] += 1
        result = {"status": "needs_repair" if not inventory["advice_ready"] else "warning" if inventory["issues"] else "ok", "general_notes": len(rows),
                  "statuses": dict(Counter(str(r["meta"].get("status", "missing")) for r in rows)),
                  "quality": dict(quality), "conflicting_groups": inventory["conflicting_groups"],
                  "review_reasons": dict(Counter(i["reason"] for i in inventory["issues"])),
                  "current_notes": len(inventory["current"]),
                  "owner_namespaces": "excluded; inspect through owner tools"}
        if details:
            result["issues"] = []
            for item in inventory["issues"][:limit]:
                result["issues"].append(item)
                if len(json.dumps(result).encode()) > 15000:
                    result["issues"].pop()
                    break
            result["omitted_issues"] = len(inventory["issues"]) - len(result["issues"])
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return {"status": "unavailable", "error": "VAULT_UNREADABLE_OR_INVALID"}
    if backups is not None:
        from scripts.vault_backup import ARCHIVE_NAME
        files = [p for p in safe(backups).glob("*.zip") if ARCHIVE_NAME.fullmatch(p.name) and not p.is_symlink()]
        latest = max((p.stat().st_mtime for p in files), default=None)
        age = None if latest is None else round((datetime.now(timezone.utc).timestamp() - latest) / 3600, 2)
        result["backup"] = {"archives": len(files), "latest_age_hours": age,
                            "over_24_hours": age is None or age > 24,
                            "integrity": "not checked; use quarantined restore"}
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vault", type=Path, default=ROOT / "vault")
    p.add_argument("--backups", type=Path)
    p.add_argument("--details", action="store_true", help="Include bounded note paths and repair reasons, never bodies")
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()
    result = health(a.vault, a.backups, a.details, a.limit)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "ok" else 1)
