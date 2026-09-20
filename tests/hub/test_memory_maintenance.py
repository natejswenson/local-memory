from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from memory_hub.maintenance import catalog
from memory_hub.recall import recall_context
from scripts import new_memory_note as drafts
from scripts.memory_health import health
from scripts.install_vault_workspace import install


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()

    def note(self, name, body="Synthetic deployment decision.", **extra):
        meta = {"title": name, "type": "note", "permalink": f"local-memory/{name}",
                "project": "local-memory", "status": "active", "source": "Synthetic fixture",
                "capture_id": str(uuid.uuid4()), **extra}
        (self.vault / f"{name}.md").write_text("---\n" + json.dumps(meta) + "\n---\n" + body + "\n")

    def test_navigation_resolves_corrections_and_reports_repairs(self):
        self.note("old", key="deploy", review_after="2000-01-01")
        self.note("new", key="deploy", supersedes="local-memory/old")
        self.note("candidate", status="candidate")
        self.note("missing-source", source="")
        data = catalog(self.vault)
        self.assertEqual([r["meta"]["title"] for r in data["current"]], ["new"])
        self.assertFalse(any(i["path"] == "old.md" and i["reason"] == "overdue" for i in data["issues"]))
        install(self.vault, self.root / "backup", True)
        current = (self.vault / "Projects/_Index.md").read_text()
        self.assertIn("[[new|", current)
        self.assertNotIn("[[old|", current)
        review = (self.vault / "Inbox/_Index.md").read_text()
        self.assertIn("missing metadata: source", review)
        self.assertIn("[[candidate|", review)

    def test_invalid_replacement_cannot_revive_ancestor_in_navigation(self):
        self.note("old", key="deploy")
        self.note("new", key="deploy", supersedes="local-memory/old", source="")
        data = catalog(self.vault)
        self.assertEqual(data["current"], [])
        self.assertEqual(data["conflicting_groups"], 1)

    def test_malformed_note_gets_repair_location_without_becoming_advice(self):
        self.note("valid")
        (self.vault / "broken.md").write_text("---\ninvalid: [\n---\nPRIVATE_BODY_SENTINEL")
        result = health(self.vault, details=True)
        self.assertEqual(result["status"], "needs_repair")
        self.assertIn({"path": "broken.md", "reason": "malformed_frontmatter"}, result["issues"])
        self.assertNotIn("PRIVATE_BODY_SENTINEL", json.dumps(result))
        self.assertEqual(result["current_notes"], 0)
        self.assertEqual(recall_context(self.vault, subject="local-memory", query="deployment")["status"], "unavailable")
        install(self.vault, self.root / "backup", True)
        self.assertIn("broken", (self.vault / "Inbox/_Index.md").read_text())

    def test_duplicates_are_suggestions_and_health_is_bounded(self):
        for i in range(12):
            self.note(f"duplicate-{i}")
        result = health(self.vault, details=True, limit=3)
        self.assertEqual(result["review_reasons"]["duplicate_content"], 12)
        self.assertEqual(len(result["issues"]), 3)
        self.assertEqual(result["omitted_issues"], 9)
        self.assertLessEqual(len(result["issues"][0]["related"]), 3)
        self.assertEqual(len(list(self.vault.glob("*.md"))), 12)

    def test_backup_summary_import_works_as_module(self):
        result = health(self.vault, self.root / "backups")
        self.assertTrue(result["backup"]["over_24_hours"])

    def test_candidate_creation_metadata_retry_and_no_overwrite(self):
        draft = drafts.prepare(title="Deployment handoff", subject="local-memory", kind="handoff",
                               source="Synthetic instruction", body="Verified next deployment step.")
        self.assertEqual(list(self.vault.iterdir()), [])
        result = drafts.create(self.vault, draft)
        self.assertTrue(result["verified"])
        path = self.vault / result["path"]
        meta = json.loads(path.read_text()[4:].split("\n---\n")[0])
        self.assertEqual(meta["status"], "candidate")
        self.assertEqual(meta["review_after"], (date.today() + timedelta(days=7)).isoformat())
        self.assertEqual(drafts.create(self.vault, draft)["status"], "already_created")
        with self.assertRaises(ValueError):
            drafts.create(self.vault, {**draft, "content": draft["content"] + "different"})
        self.assertEqual(recall_context(self.vault, subject="local-memory", query="deployment")["records"], [])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_candidate_validation_and_destination_boundaries(self):
        args = dict(title="Decision", subject="local-memory", kind="decision", source="Synthetic", body="A claim.")
        for extra in [{"source": ""}, {"subject": "local-fitness"}, {"capture_id": "../escape"},
                      {"body": "x" * 8193}, {"kind": "handoff", "review_after": "2100-01-01"}]:
            with self.assertRaises(ValueError):
                drafts.prepare(**{**args, **extra})
        draft = drafts.prepare(**args)
        with self.assertRaises(ValueError):
            drafts.create(self.vault, {**draft, "path": "../escape.md"})
        (self.vault / "Inbox").symlink_to(self.root / "elsewhere")
        with self.assertRaises(ValueError):
            drafts.create(self.vault, draft)
