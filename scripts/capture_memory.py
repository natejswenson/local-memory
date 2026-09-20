#!/usr/bin/env python3
"""Preview or apply a complete capture; interactive drafts ask only claim/scope/source."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.capture import CaptureStore, validate
from memory_hub.recall import SUBJECTS
from memory_hub.skill_store import safe, read


def selected_note(vault, relative, expected=None):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] not in {"Scratch", "Clippings", "Inbox"}:
        raise ValueError("Select a note under Scratch, Clippings or Inbox")
    if path.suffix != ".md":
        raise ValueError("Select one Markdown note")
    raw = read(safe(vault / path), 65536)
    revision = hashlib.sha256(raw).hexdigest()
    if expected and revision != expected:
        raise ValueError("Source changed; preview again")
    text = raw.decode()
    if text.startswith("---\n"):
        parts = text[4:].split("\n---\n", 1)
        if len(parts) != 2:
            raise ValueError("Malformed source frontmatter")
        text = parts[1]
    return text.strip(), revision


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--title")
    p.add_argument("--subject", choices=sorted(SUBJECTS))
    p.add_argument("--source")
    p.add_argument("--kind", choices=["decision", "preference", "handoff"], default="decision")
    p.add_argument("--status", choices=["candidate", "active"], default="candidate")
    p.add_argument("--capture-id")
    p.add_argument("--key")
    p.add_argument("--supersedes")
    p.add_argument("--review-after")
    p.add_argument("--from-note")
    p.add_argument("--expected-revision")
    a = p.parse_args()
    vault = ROOT / "vault"
    revision = None
    if a.interactive:
        if a.from_note:
            p.error("Use interactive entry or --from-note, not both")
        body = input("Claim: ").strip()
        a.subject = a.subject or input("Scope (global/local-memory): ").strip()
        a.source = a.source or input("Source: ").strip()
    elif a.from_note:
        body, revision = selected_note(vault, a.from_note, a.expected_revision)
        if a.source:
            a.source += f"; vault:{a.from_note} sha256:{revision}"
        if a.apply and (not a.expected_revision or not a.capture_id):
            p.error("Applying a selected note requires the preview's --expected-revision and --capture-id")
    else:
        body = sys.stdin.read(6145)
    request = validate(dict(title=a.title or body.splitlines()[0][:100] if body else "",
        body=body, subject=a.subject, source=a.source, kind=a.kind, status=a.status,
        capture_id=a.capture_id or str(uuid.uuid4()), key=a.key, supersedes=a.supersedes,
        review_after=a.review_after))
    if not a.apply:
        print(json.dumps({"status": "preview", "request": request, "source_revision": revision}, ensure_ascii=False))
        return 0
    ready = json.loads(subprocess.check_output([str(ROOT / "bin/memory-hub"), "doctor"]))
    if not ready.get("ready"):
        raise ValueError("Live memory is unavailable; no fallback capture")
    result = CaptureStore(vault, ROOT / ".runtime/general-memory").capture(request)
    if result.get("verified"):
        from scripts.install_vault_workspace import install
        try:
            result["navigation"] = install(vault, ROOT / ".runtime/workspace-backups", True)
        except (ValueError, OSError):
            result["navigation"] = "refresh_required; capture succeeded"
    print(json.dumps(result))
    return 0 if result.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
