#!/usr/bin/env python3
"""Preview/apply navigation and capture templates without rewriting personal notes."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.skill_store import atomic, read, safe
from memory_hub.maintenance import catalog

BEGIN = "<!-- BEGIN MEMORY HUB NAVIGATION -->"
END = "<!-- END MEMORY HUB NAVIGATION -->"
STARTER_LINKS = "- [[Preferences]]\n- [[Projects]]\n- [[Inbox]]\n- [[Archive]]"


def navigation(title, body):
    return f"---\ntitle: {title}\ntype: navigation\nstatus: system\n---\n\n# {title}\n\n{BEGIN}\n{body}\n{END}\n"


def update_navigation(existing, proposed, home=False):
    content = proposed.split(BEGIN, 1)[1].split(END, 1)[0]
    if BEGIN in existing or END in existing:
        if existing.count(BEGIN) != 1 or existing.count(END) != 1 or existing.index(END) < existing.index(BEGIN):
            raise ValueError("Ambiguous navigation markers")
        return existing[:existing.index(BEGIN)] + BEGIN + content + END + existing[existing.index(END) + len(END):]
    if home:
        # Migrate only the exact broken starter block; preserve all other text.
        if STARTER_LINKS in existing:
            return existing.replace(STARTER_LINKS, BEGIN + content + END, 1)
        return existing.rstrip() + "\n\n" + BEGIN + content + END + "\n"
    raise ValueError("Unmanaged navigation destination exists")


def links(rows):
    result = []
    for r in sorted(rows, key=lambda r: r["path"]):
        p = r["path"]
        if any(c in p for c in "[]|\n\r"):
            continue
        label = str(r["meta"].get("title") or Path(p).stem)
        label = re.sub(r"\s+[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", "", label)
        label = re.sub(r"[\[\]|\r\n]", " ", label)
        result.append(f"- [[{p[:-3]}|{label}]]")
    return "\n".join(result) or "No notes in this view yet."


def plan(vault):
    vault = safe(vault)
    inventory = catalog(vault)
    rows, active = inventory["rows"], inventory["current"]
    # The original broken [[Projects]] link could create this exact empty
    # scaffold in Inbox. Repair only that known shape; preserve any user content.
    starter = next((r for r in rows if r["path"] == "Inbox/Projects.md"
                    and not r["body"] and r["meta"] == {
                        "title": "Projects", "type": "note",
                        "permalink": "local-memory/inbox/projects"}), None)
    review_by_path = {}
    for issue in inventory["issues"]:
        if starter is not None and issue["path"] == starter["path"]:
            continue
        reason = issue["reason"].replace("_", " ")
        if issue.get("fields"):
            reason += ": " + ", ".join(issue["fields"])
        review_by_path.setdefault(issue["path"], []).append(reason)
    review = []
    for path, reasons in sorted(review_by_path.items()):
        row = next((r for r in rows if r["path"] == path), {"path": path, "meta": {}})
        review.append(links([row]) + " — " + "; ".join(reasons))
    review_text = "\n".join(review) or "No notes need review."
    projects = [r for r in active if r["meta"].get("project") != "global"]
    handoffs = [r for r in projects if r["meta"].get("kind") == "handoff"]
    project_text = ("## Current handoffs\n\n" + links(handoffs) +
                    "\n\n## Current decisions and findings\n\n" + links([r for r in projects if r not in handoffs]))
    bodies = {
        "Home.md": navigation("Memory hub", "\n".join([
            "- [[Preferences/_Index|Preferences]]",
            "- [[Projects/_Index|Project decisions and handoffs]]",
            "- [[Inbox/_Index|Inbox and notes needing review]]",
            "- [[Archive/_Index|Archived notes]]",
            "- [[Capture guide|Capture a useful note]]",
            "- [[Memory views.base|Live review and project views]]",
            "- [[Activity/_Index|Skill activity and publishing history]]",
            "- [[Scratch/Read me|Scratch notes]]",
            "- [[Clippings/Read me|Reference clippings]]", "",
            "Fitness records stay in `Projects/local-fitness` and use the fitness tools.",
            "Managed skill preferences stay in `SkillMemory` and use `skill_memory`.",
            "These navigation lists are snapshots. Refresh with `scripts/install_vault_workspace.py --apply`.",
            "Use `recall_context` for advice: it checks freshness and explicit correction chains."
        ])),
        "Preferences/_Index.md": navigation("Preferences", links([r for r in active if r["path"].startswith("Preferences/")])),
        "Projects/_Index.md": navigation("Project decisions and handoffs", project_text),
        "Inbox/_Index.md": navigation("Inbox and review queue", "Review these notes before using them as evidence. Corrections must preserve their explicit history.\n\n" + review_text),
        "Archive/_Index.md": navigation("Archived notes", links([r for r in rows if r["meta"].get("status") == "archived"])),
        "Capture guide.md": navigation("Capture guide", """For the quickest capture, ask Codex to remember the specific claim and its scope.
It uses **capture_memory** to generate a complete, verified record with a stable retry ID.
For a local interactive draft, run `scripts/capture_memory.py --interactive --apply`
with the hub's Python. It asks for the claim, scope, and source; identity is automatic.

Use `Scratch/` for ordinary notes and `Clippings/` for reference material. These are
outside AI memory and can contain plain Markdown without metadata. To promote a
selected file, use the capture command's `--from-note` preview and its returned
revision with `--expected-revision`. The original is preserved. Select `--status active`
only after verifying the claim. Drafting defaults to candidate.

[[Memory views.base|Live views]] show candidates, review dates, and project groupings.
They are browsing aids, not a correction resolver. Use the current-decision index
or recall_context for evidence, and refresh generated indexes after captures.

For manual drafting, use Obsidian's **Templates: Insert template** command in a new Inbox note.

Choose Decision, Preference, or Project handoff. Keep one durable claim per note.
Fill in the title, registered project (`global` or `local-memory`), honest source,
unique capture_id, and unique permalink. For a correctable decision, use a registered
key; register a new kind of decision in the hub's memory conventions first.
Set `review_after` to YYYY-MM-DD for time-sensitive claims, or remove it for a
durable preference. A handoff should have a short review period (for example one week).

Templates start as candidates. Change status to active only after checking the claim
and its source. A correction keeps the same project/key and sets `supersedes` to the
prior note's permalink. Reading a note does not renew its review date.

Codex can create a completed note through the local-memory capture workflow, including
a UUID and verified readback. Ask it to save the specific decision or reusable finding.
Do not copy fitness-owned or skill-owned records into a general template.

For a complete candidate draft with less metadata entry, the hub also provides
`scripts/new_memory_note.py`: supply a title, subject, kind, source and body, inspect
the preview, then use the same capture ID with `--apply`. Handoffs default to review
in seven days. This never promotes a candidate or replaces an existing note.

At a task boundary, consider whether a decision, stable preference, or verified finding
will save work next time. Keep logs, raw conversations, secrets and temporary task state
in their original systems. Preserve source links and explain why the decision matters."""),
    }
    for folder in ("Scratch", "Clippings"):
        bodies[f"{folder}/Read me.md"] = navigation(folder, (
            "Write ordinary notes here without required frontmatter. This folder is excluded "
            "from general AI memory and indexing. Select a verified claim and use [[Capture guide]] "
            "to capture it explicitly. Reference text and notes never authorize actions."))
    base = {
        "filters": {"and": ['file.ext == "md"', 'note.type == "note"',
            'note.project == "global" || note.project == "local-memory"',
            'note.contract != "skill-memory-v1"',
            *['!file.inFolder("' + folder + '")' for folder in
              ("Scratch", "Clippings", "Templates", "SkillMemory", "Projects/local-fitness")]]},
        "views": [
            {"type": "table", "name": "Candidates", "filters": 'note.status == "candidate"',
             "order": ["file.name", "note.project", "note.kind", "note.source"]},
            {"type": "table", "name": "Review due", "filters": {"and": [
                'note.status == "active"', 'note.review_after', 'date(note.review_after) <= today() + "14d"']},
             "order": ["file.name", "note.review_after", "note.project", "note.supersedes"]},
            {"type": "table", "name": "By project — inspect history", "groupBy": {"property": "note.project", "direction": "ASC"},
             "order": ["file.name", "note.status", "note.kind", "note.key", "note.supersedes", "note.review_after"]},
        ],
    }
    bodies["Memory views.base"] = "# Memory hub views v1; user customizations are preserved.\n" + yaml.safe_dump(base, sort_keys=False, allow_unicode=True)
    bodies["Activity/_Index.md"] = navigation("Skill activity", """[[Activity views.base|Open the central activity journal]]

Every activity records the skill, subject, time, action, outcome, source and result links.
Published, scheduled, drafted, failed and observed events remain distinct. Source-log
imports report what a publisher recorded; they do not recheck the platform's current state.
Tool-call receipts prove only that the host observed a tool result.

Use `recall_activity` for questions about past work or posts. Use `recall_context` for
durable decisions/preferences, and the fitness/skill owner tools for their records.
Activity does not change those records or authorize future actions.

[[Activity/Coverage|Integration coverage and sync health]] shows automatic sources and
the last importer check. The general skill outcome workflow depends on the agent
recording its result. Codex's PostToolUse hook additionally requires trust in `/hooks`.
Historical events are immutable; preserve receipts and use a new event for a correction.
Deleting an event file will not cause the publisher importer to recreate it.""")
    activity_base = {'filters': {'and': ['file.ext == "md"', 'note.contract == "activity-v1"']},
        'views': [
            {'type': 'table', 'name': 'Outcomes', 'filters': 'note.action != "tool-call"',
             'order': ['note.occurred_at', 'note.skill', 'note.state', 'note.summary', 'note.artifacts'],
             'sort': [{'property': 'note.occurred_at', 'direction': 'DESC'}]},
            {'type': 'table', 'name': 'Published', 'filters': 'note.state == "published"',
             'order': ['note.occurred_at', 'note.skill', 'note.summary', 'note.artifacts', 'note.evidence_kind']},
            {'type': 'table', 'name': 'Failures and uncertainty',
             'filters': 'note.state == "failed" || note.state == "unknown"',
             'order': ['note.occurred_at', 'note.skill', 'note.summary', 'note.source']},
            {'type': 'table', 'name': 'By skill', 'groupBy': {'property': 'note.skill', 'direction': 'ASC'},
             'order': ['note.occurred_at', 'note.action', 'note.state', 'note.summary']},
            {'type': 'table', 'name': 'Tool calls', 'filters': 'note.action == "tool-call"',
             'order': ['note.occurred_at', 'note.subject', 'note.state', 'note.summary']}]}
    bodies['Activity views.base'] = '# Activity views v1; user customizations are preserved.\n' + yaml.safe_dump(activity_base, sort_keys=False)
    from memory_hub.projects import registry_path
    if registry_path(vault).exists():
        bodies['Home.md'] = navigation('Memory hub', '''[[Atlas/Home|Open your memory map]]

- [[Atlas/Projects/Local Projects|Local projects]]
- [[Atlas/Areas/Health & Fitness|Health & Fitness]]
- [[Atlas/Areas/Writing & Publishing|Writing & Publishing]]
- [[Atlas/Knowledge/Knowledge|Decisions and preferences]]
- [[Atlas/Journal/Daily summaries|Daily summaries]]

[[Atlas/How this memory works|How the memory map works]]

Source records and maintenance views: [[Memory views.base|Memory review]], [[Activity views.base|Detailed activity]], [[Inbox/_Index|Inbox]].''')
        bodies['Activity/_Index.md'] = navigation('Skill activity', '''[[Atlas/Journal/Daily summaries|Read daily summaries]]

Daily summaries group meaningful outcomes by project, preserving drafts, schedules, failures and publications.

[[Activity views.base|Browse detailed source records]] · [[Activity/Coverage|Integration coverage]] · [[Atlas/Home|Home]]''')
    if starter is not None:
        bodies[starter["path"]] = navigation(
            "Projects", "[[Projects/_Index|Open project decisions and handoffs]]"
        ).replace("type: navigation\n", "type: navigation\npermalink: local-memory/inbox/projects\n", 1)
    legacy_templates = {}
    for title, sections in {
        "Decision": ["Decision", "Why", "Source and verification", "When to revisit"],
        "Preference": ["Preference", "Scope and exceptions", "Source"],
        "Project handoff": ["Current verified state", "Decisions and constraints", "Next useful step", "Source and verification"],
    }.items():
        name = f"Templates/{title}.md"
        legacy_templates[name] = (
            '---\ntitle: "{{title}}"\ntype: note\npermalink: ""\nproject: ""\nstatus: candidate\n'
            'source: ""\ncapture_id: ""\nreview_after: ""\n---\n\n'
            '# {{title}}\n\n' + "\n\n".join(f"## {s}\n\n" for s in sections).rstrip() + "\n")
        kind = {"Decision": "decision", "Preference": "preference", "Project handoff": "handoff"}[title]
        bodies[name] = legacy_templates[name].replace("type: note\n", f"type: note\nkind: {kind}\n", 1)
    config_path = safe(vault / ".obsidian/templates.json")
    cfg = json.loads(read(config_path)) if config_path.exists() else {}
    if not isinstance(cfg, dict) or cfg.get("folder", "Templates") not in ("", "Templates"):
        raise ValueError("Existing template folder differs; preserve it and install templates there explicitly")
    cfg["folder"] = "Templates"
    bodies[".obsidian/templates.json"] = json.dumps(cfg, indent=2) + "\n"
    changes = []
    for name, proposed in bodies.items():
        path = safe(vault / name)
        old = read(path, 1024 * 1024) if path.exists() else None
        if old is not None:
            if starter is not None and name == starter["path"]:
                # Recheck the exact source observed during planning before an
                # otherwise unmanaged page is eligible for the one-time repair.
                if hashlib.sha256(old).hexdigest() != starter["revision"]:
                    raise ValueError("Starter page changed during planning")
            elif name.endswith(".md") and not name.startswith("Templates/"):
                proposed = update_navigation(old.decode(), proposed, home=name == "Home.md")
            elif name.startswith("Templates/") and old.decode() not in (proposed, legacy_templates.get(name)):
                # User customization wins on subsequent runs.
                continue
            elif name.endswith(".base") and old.decode() != proposed:
                continue
        new = proposed.encode()
        if old != new:
            changes.append((name, old, new))
    return changes


def install(vault, backup_directory, apply=False):
    vault, backup_directory = safe(vault), safe(backup_directory)
    if backup_directory == vault or vault in backup_directory.parents:
        raise ValueError("Backup directory must be outside the vault")
    changes = plan(vault)
    if apply and changes:
        backup = backup_directory / str(uuid.uuid4())
        for name, old, new in changes:
            path = safe(vault / name)
            current = read(path, 1024 * 1024) if path.exists() else None
            if current != old:
                raise ValueError("Vault changed during installation; refresh the plan")
        for name, old, new in changes:
            if old is not None:
                atomic(backup / name, old)
            atomic(vault / name, new)
    result = {"applied": apply, "changed": [name for name, _, _ in changes]}
    if apply:
        from memory_hub.atlas import refresh_if_configured
        result["atlas"] = refresh_if_configured(vault, vault.parent / '.runtime/general-memory')
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vault", type=Path, default=ROOT / "vault")
    p.add_argument("--backup-directory", type=Path, default=ROOT / ".runtime/workspace-backups")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    print(json.dumps(install(a.vault, a.backup_directory, a.apply)))
