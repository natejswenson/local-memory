"""Explain general-note maintenance needs without changing claims or review dates."""
from collections import defaultdict
from datetime import date
import hashlib

from .recall import REQUIRED, SUBJECTS, eligible, resolve, scan


def catalog(vault, today=None):
    today = today or date.today()
    issues = []
    rows = scan(vault, issues=issues)
    groups, duplicates = defaultdict(list), defaultdict(list)
    current = []
    for row in rows:
        m = row["meta"]
        missing = [k for k in REQUIRED if not isinstance(m.get(k), str) or not m[k].strip()]
        if missing:
            issues.append({"path": row["path"], "reason": "missing_metadata", "fields": missing})
        if m.get("status") == "candidate":
            issues.append({"path": row["path"], "reason": "candidate"})
        elif m.get("status") not in ("active", "archived"):
            issues.append({"path": row["path"], "reason": "invalid_status"})
        if isinstance(m.get("project"), str) and m["project"] not in SUBJECTS:
            issues.append({"path": row["path"], "reason": "unregistered_subject"})
        reason = eligible(row, today)
        if (reason and not missing and m.get("status") != "archived"
                and not (reason == "overdue" and m.get("status") == "active" and m.get("key"))):
            issues.append({"path": row["path"], "reason": reason})
        if m.get("status") != "active" or not isinstance(m.get("project"), str):
            continue
        key = m.get("key")
        if key is not None and (not isinstance(key, str) or not key):
            issues.append({"path": row["path"], "reason": "invalid_key"})
            continue
        groups[(m["project"], "key" if key else "path", key or row["path"])].append(row)
    conflicts = 0
    for group in groups.values():
        try:
            if any(eligible(r, date.min) in {"invalid_metadata", "empty"} for r in group):
                raise ValueError("invalid_metadata")
            latest = resolve(group)
            if "supersedes" in latest["meta"] and not latest["meta"].get("key"):
                raise ValueError("invalid_key")
        except (ValueError, TypeError):
            conflicts += 1
            for row in group:
                issues.append({"path": row["path"], "reason": "correction_conflict"})
            continue
        if latest["meta"].get("key") and eligible(latest, today) == "overdue":
            issues.append({"path": latest["path"], "reason": "overdue"})
        if eligible(latest, today) is None and latest["meta"]["project"] in SUBJECTS:
            current.append(latest)
            digest = hashlib.sha256(latest["body"].strip().encode()).hexdigest()
            duplicates[(latest["meta"]["project"], digest)].append(latest["path"])
    for paths in duplicates.values():
        if len(paths) > 1:
            for path in paths:
                issues.append({"path": path, "reason": "duplicate_content",
                               "related": [p for p in paths[:4] if p != path][:3],
                               "related_count": len(paths) - 1})
    # Broken files may conceal correction metadata. No navigation page should
    # label surviving records current when strict recall cannot validate them.
    advice_ready = not any(i["reason"] in {"malformed_frontmatter", "unreadable_or_oversized"} for i in issues)
    return {"rows": rows, "current": current if advice_ready else [],
            "issues": sorted(issues, key=lambda i: (i["path"], i["reason"])),
            "advice_ready": advice_ready, "conflicting_groups": conflicts}
