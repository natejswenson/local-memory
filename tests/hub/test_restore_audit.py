import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from memory_hub.capture import CaptureStore
from memory_hub.activity import ActivityStore
from memory_hub.restore_audit import audit_general
from memory_hub.skill_store import SkillStore, put
from scripts.vault_backup import backup, restore
from scripts.audit_memory_restore import audit


class RestoreAuditTests(unittest.TestCase):
    def test_activity_deleted_after_snapshot_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            vault, control = root / 'vault', root / 'general'
            vault.mkdir()
            request = dict(event_id=str(uuid.uuid4()), skill='fixture', subject='fixture',
                           action='test', state='completed', summary='Synthetic outcome',
                           source='Synthetic fixture', source_id='fixture', occurred_at='2026-09-19')
            saved = ActivityStore(vault, control).record(request)
            self.assertTrue(saved['verified'])
            archive = backup(vault, root / 'backups', general_control=control)['archive']
            quarantine = root / 'quarantine'
            restore(archive, quarantine)
            self.assertEqual(audit_general(quarantine, control, vault)['issue_count'], 0)
            (vault / saved['path']).unlink()
            result = audit_general(quarantine, control, vault)
            self.assertIn('current_file_missing_do_not_resurrect', result['issues'][0]['reasons'])
            self.assertFalse((vault / saved['path']).exists())

    def general_fixture(self, root):
        vault, control = root / "vault", root / "general"
        vault.mkdir()
        request = {"title": "Synthetic decision", "subject": "global", "body": "PRIVATE_SENTINEL",
                   "source": "Synthetic test", "capture_id": str(uuid.uuid4()), "status": "active"}
        saved = CaptureStore(vault, control).capture(request)
        self.assertTrue(saved["verified"])
        archive = backup(vault, root / "backups", general_control=control)["archive"]
        quarantine = root / "quarantine"
        restore(archive, quarantine)
        return vault, control, request, saved, quarantine

    def test_general_deleted_and_edited_notes_flagged_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control, request, saved, quarantine = self.general_fixture(Path(tmp).resolve())
            clean = audit_general(quarantine, control, vault)
            self.assertEqual(clean["issue_count"], 0)
            note = vault / saved["path"]
            note.write_text(note.read_text() + "Changed intentionally")
            changed = audit_general(quarantine, control, vault)
            self.assertIn("current_file_edited", changed["issues"][0]["reasons"])
            note.unlink()
            deleted = audit_general(quarantine, control, vault)
            self.assertIn("current_file_missing_do_not_resurrect", deleted["issues"][0]["reasons"])
            self.assertFalse(note.exists())
            self.assertTrue((quarantine / "vault" / saved["path"]).exists())
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(deleted))

    def test_general_missing_receipt_and_newer_captures_need_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control, request, saved, quarantine = self.general_fixture(Path(tmp).resolve())
            (control / "receipts" / (request["capture_id"] + ".json")).unlink()
            result = audit_general(quarantine, control, vault)
            self.assertIn("current_receipt_missing", result["issues"][0]["reasons"])
            request["capture_id"] = str(uuid.uuid4())
            self.assertTrue(CaptureStore(vault, control).capture(request)["verified"])
            result = audit_general(quarantine, control, vault)
            self.assertEqual(result["issue_count"], 2)
            self.assertTrue(any("capture_not_in_snapshot" in i["reasons"] for i in result["issues"]))

    def test_general_pending_and_malformed_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control, request, saved, quarantine = self.general_fixture(Path(tmp).resolve())
            receipt = control / "receipts" / (request["capture_id"] + ".json")
            data = json.loads(receipt.read_text())
            data["phase"] = "pending"
            receipt.write_text(json.dumps(data))
            self.assertIn("current_capture_pending", audit_general(quarantine, control, vault)["issues"][0]["reasons"])
            data["path"] = "../escape.md"
            receipt.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                audit_general(quarantine, control, vault)

    def test_general_detects_concurrent_file_change_and_rejects_rolled_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control, request, saved, quarantine = self.general_fixture(Path(tmp).resolve())
            from memory_hub.restore_audit import receipt_snapshot
            calls = 0
            def changing(*args):
                nonlocal calls
                calls += 1
                if calls == 3:
                    (vault / saved["path"]).unlink()
                return receipt_snapshot(*args)
            with patch("memory_hub.restore_audit.receipt_snapshot", side_effect=changing):
                with self.assertRaises(ValueError):
                    audit_general(quarantine, control, vault)
            with self.assertRaises(ValueError):
                audit_general(quarantine, quarantine / "general-control", quarantine / "vault")

    def test_forgetting_after_snapshot_is_reported_without_changing_either_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            vault, control = root / "vault", root / "control"
            vault.mkdir()
            control.mkdir()
            put(control / "config.json", {"version": 1, "bindings": {
                "issuecreator": {"fixture": {"enabled": True, "shared_profile": True}}}})
            store = SkillStore(vault, control)
            base = {"contract": "skill-memory-v1", "skill": "issuecreator", "subject": "fixture"}
            saved = store.request({**base, "op": "capture", "key": "issue.acceptance-style",
                                   "value": "Observable outcomes.", "source": "Synthetic instruction",
                                   "capture_id": str(uuid.uuid4())})
            self.assertEqual(saved["status"], "saved")
            archive = backup(vault, root / "backups", skill_control=control)["archive"]
            gone = store.request({**base, "op": "forget", "id": saved["record"]["id"],
                                  "expected_revision": saved["record"]["revision"]})
            self.assertEqual(gone["status"], "forgotten")
            quarantine = root / "quarantine"
            restore(archive, quarantine)
            before = (control / "forgotten.json").read_bytes()
            result = audit(quarantine, control)
            self.assertEqual(result["status"], "review_required")
            self.assertEqual(result["suppressed_count"], 1)
            self.assertFalse(result["activated"])
            self.assertEqual((control / "forgotten.json").read_bytes(), before)
            self.assertTrue((quarantine / result["suppressed_records"][0]).exists())
            self.assertNotIn("Observable outcomes", json.dumps(result))
            self.assertEqual(store.request({**base, "op": "recall", "keys": ["issue.acceptance-style"]})["records"], [])

    def test_missing_or_rolled_together_control_is_not_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(audit(root, root / "skill-control")["status"], "unavailable")
            self.assertEqual(audit(root / "absent", root / "missing")["status"], "unavailable")
