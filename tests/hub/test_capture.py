from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from memory_hub.capture import CaptureStore
from memory_hub.recall import recall_context


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.store = CaptureStore(self.vault, self.root / "control")
        self.request = dict(title="Synthetic deployment", body="Deployment requires validation.",
                            subject="local-memory", source="Synthetic test instruction",
                            capture_id=str(uuid.uuid4()), status="active")

    def test_verified_capture_and_concurrent_identical_retries(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.store.capture(self.request), range(3)))
        self.assertEqual(sum(r["status"] == "created" for r in results), 1)
        self.assertTrue(all(r["verified"] for r in results))
        self.assertEqual(len(list(self.vault.rglob("*.md"))), 1)
        self.assertEqual(recall_context(self.vault, subject="local-memory", query="deployment")["records"][0]["content"], self.request["body"])
        self.assertEqual(self.store.capture({**self.request, "body": "changed"})["error"], "CAPTURE_ID_CONFLICT")

    def test_invalid_inputs_cannot_create_or_overwrite(self):
        for change in ({"subject": "local-fitness"}, {"subject": "SkillMemory"}, {"overwrite": True},
                       {"source": ""}, {"capture_id": "../escape"}, {"key": "unregistered"},
                       {"review_after": "2000-01-01"}, {"body": "x" * 6145}):
            result = self.store.capture({**self.request, **change})
            self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(list(self.vault.rglob("*.md")), [])

    def test_edited_or_deleted_capture_never_recreated_on_retry(self):
        created = self.store.capture(self.request)
        path = self.vault / created["path"]
        path.write_text(path.read_text() + "Manual edit")
        self.assertEqual(self.store.capture(self.request)["error"], "CAPTURE_CHANGED_REVIEW_REQUIRED")
        path.unlink()
        self.assertEqual(self.store.capture(self.request)["error"], "CAPTURE_MISSING_REVIEW_REQUIRED")
        self.assertFalse(path.exists())

    def test_pending_receipt_recovers_only_when_file_matches(self):
        created = self.store.capture(self.request)
        receipt_path = self.store.control / "receipts" / (self.request["capture_id"] + ".json")
        receipt = json.loads(receipt_path.read_text())
        receipt["phase"] = "pending"
        receipt_path.write_text(json.dumps(receipt))
        self.assertEqual(self.store.capture(self.request)["status"], "already_created")
        self.assertEqual(json.loads(receipt_path.read_text())["phase"], "committed")
        (self.vault / created["path"]).unlink()
        receipt_path.write_text(json.dumps(receipt))
        self.assertEqual(self.store.capture(self.request)["error"], "CAPTURE_MISSING_REVIEW_REQUIRED")

    def test_crash_before_publication_leaves_visible_pending_state(self):
        with patch("memory_hub.capture.exclusive_create", side_effect=OSError("synthetic crash")):
            self.assertEqual(self.store.capture(self.request)["status"], "unavailable")
        self.assertEqual(self.store.capture(self.request)["error"], "CAPTURE_MISSING_REVIEW_REQUIRED")
        self.assertEqual(list(self.vault.rglob("*.md")), [])

    def test_correction_requires_current_parent_and_never_revives_old_fact(self):
        first = self.store.capture({**self.request, "key": "project.local-memory.handoff"})
        second = {**self.request, "capture_id": str(uuid.uuid4()), "key": "project.local-memory.handoff",
                  "body": "Release requires a smoke check."}
        self.assertEqual(self.store.capture(second)["error"], "CORRECTION_MUST_SUPERSEDE_CURRENT")
        second["supersedes"] = first["identity"]
        result = self.store.capture(second)
        self.assertTrue(result["verified"])
        found = recall_context(self.vault, subject="local-memory", query="deployment")
        self.assertEqual([r["identity"] for r in found["records"]], [result["identity"]])
        third = {**second, "capture_id": str(uuid.uuid4())}
        self.assertEqual(self.store.capture(third)["error"], "CORRECTION_MUST_SUPERSEDE_CURRENT")

    def test_symlink_and_malformed_managed_note_refused(self):
        (self.vault / "Projects").symlink_to(self.root / "elsewhere")
        self.assertFalse(self.store.capture(self.request)["verified"])
        (self.vault / "Projects").unlink()
        (self.vault / "broken.md").write_text("plain unmanaged text in the managed namespace")
        self.assertFalse(self.store.capture(self.request)["verified"])
        (self.vault / "broken.md").write_text("---\ntitle: [invalid\n---\nMalformed YAML")
        self.assertFalse(self.store.capture(self.request)["verified"])
