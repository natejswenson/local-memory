import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from memory_hub.fitness_store import FitnessStore, atomic


@unittest.skipUnless(
    os.environ.get("FITNESS_SOURCE_REPO"), "Requires fitness source for contract parity"
)
class StoreTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(os.environ["FITNESS_SOURCE_REPO"]) / "src"))
        from local_fitness import notes
        from local_fitness.agent import journal

        self.notes, self.journal = notes, journal
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / "vault"
        self.control = self.root / "control"
        self.control.mkdir()
        self.vault.mkdir()
        for name in ("Preferences", "Journal"):
            (self.vault / name).mkdir()
        atomic(
            self.control / "state.json",
            json.dumps(
                {
                    "schema": 1,
                    "vault": str(self.vault),
                    "store_id": str(uuid.uuid4()),
                    "allocation_floor": 0,
                    "revision": 0,
                    "receipts": {},
                }
            ).encode(),
        )
        self.store = self.open()

    def open(self):
        return FitnessStore(
            self.vault, self.control, self.notes, self.journal, self.root / "backups"
        )

    def call(self, operation, **args):
        return self.store.request(operation, args, str(uuid.uuid4()))

    def test_preferences_stale_handles_and_stable_identity(self):
        created = self.call("notes.append_note", text="synthetic café")
        identity = next(self.vault.glob("Preferences/*.md")).name
        updated = self.call(
            "notes.update_note", handle=created["handle"], new_text="revised synthetic"
        )
        self.assertNotEqual(updated[0]["handle"], created["handle"])
        self.assertEqual(next(self.vault.glob("Preferences/*.md")).name, identity)
        self.assertIsNone(self.call("notes.delete_note", handle=created["handle"]))
        self.assertEqual(self.call("notes.read_notes")[0]["text"], "revised synthetic")
        self.call("notes.delete_note", handle=updated[0]["handle"])
        self.assertEqual(self.call("notes.read_notes"), [])

    def test_idempotent_retry_survives_restart_and_rejects_payload_change(self):
        rid = str(uuid.uuid4())
        args = {"text": "synthetic retry"}
        one = self.store.request("notes.append_note", args, rid)
        self.store = self.open()
        self.assertEqual(self.store.request("notes.append_note", args, rid), one)
        self.assertEqual(len(self.call("notes.read_notes")), 1)
        with self.assertRaises(ValueError):
            self.store.request("notes.append_note", {"text": "changed"}, rid)

    def test_recovery_after_durable_log_before_commit(self):
        original = self.store.recover
        calls = 0

        def crash():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic crash")
            original()

        self.store.recover = crash
        rid = str(uuid.uuid4())
        args = {"text": "durably pending"}
        with self.assertRaises(OSError):
            self.store.request("notes.append_note", args, rid)
        self.assertTrue(self.store.pending.exists())
        self.store = self.open()
        self.assertEqual(
            self.store.request("notes.append_note", args, rid)["text"],
            "durably pending",
        )
        self.assertEqual(len(self.call("notes.read_notes")), 1)

    def test_journal_archive_id_allocation_and_source_exclusion_inputs(self):
        for i in range(61):
            self.call(
                "journal.save_entry",
                text=f"synthetic history {i}",
                source="brief",
                source_key=str(i),
                entry_date="2026-01-01",
            )
        self.assertEqual(len(self.call("journal.list_entries", limit=100)), 60)
        self.assertEqual(
            len(self.call("journal.list_entries", limit=100, include_archived=True)), 61
        )
        rows, mode = self.call("journal.search_entries", query="history", limit=100)
        self.assertEqual(len(rows), 61)
        self.assertIn(mode, ("fts", "like"))
        self.call("journal.delete_entry", entry_id=61)
        self.store = self.open()
        record = self.call("journal.save_entry", text="after deletion", source="chat")
        self.assertEqual(record["entry_id"], 62)
        self.assertEqual(
            self.call("journal.list_entries", on_or_before="2025-01-01"), []
        )

    def test_concurrent_writes_and_duplicate_events(self):
        import sqlite3

        def write(i):
            return self.call(
                "journal.save_entry",
                text=f"entry {i}",
                source="brief",
                source_key=str(i),
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(12)))
        with self.assertRaises(sqlite3.IntegrityError):
            write(0)
        self.assertEqual(len(self.call("journal.list_entries")), 12)

    def test_invalid_manual_edit_refused_without_overwrite(self):
        self.call("notes.append_note", text="synthetic")
        path = next(self.vault.glob("Preferences/*.md"))
        path.write_text("broken")
        with self.assertRaises(ValueError):
            self.call("notes.append_note", text="another")
        self.assertEqual(path.read_text(), "broken")

    def test_invalid_write_never_publishes_unreadable_records(self):
        self.call("journal.save_entry", text="valid existing fixture", source="chat")
        state_before = self.store.state_path.read_bytes()
        files_before = {p.name: p.read_bytes() for p in self.vault.glob("Journal/*.md")}
        for seq in (0, -1, 1.5, "invalid"):
            with self.subTest(seq=seq), self.assertRaises(ValueError):
                self.call(
                    "journal.save_entry", text="invalid fixture", source="chat", seq=seq
                )
            self.assertEqual(self.store.state_path.read_bytes(), state_before)
            self.assertFalse(self.store.pending.exists())
            self.assertEqual(
                {p.name: p.read_bytes() for p in self.vault.glob("Journal/*.md")},
                files_before,
            )
            self.assertEqual(len(self.call("journal.list_entries")), 1)
        with self.assertRaises(ValueError):
            self.call(
                "journal.save_entry",
                text="oversized metadata",
                source="chat",
                source_key="x" * 66000,
            )
        self.assertEqual(self.store.state_path.read_bytes(), state_before)
        self.store = self.open()
        self.assertEqual(len(self.call("journal.list_entries")), 1)

    def test_preference_correction_and_forget_retire_content_receipts(self):
        original_id, update_id, delete_id = (str(uuid.uuid4()) for _ in range(3))
        original_args = {"text": "synthetic superseded preference"}
        original = self.store.request("notes.append_note", original_args, original_id)
        update_args = {
            "handle": original["handle"],
            "new_text": "synthetic corrected preference",
        }
        updated = self.store.request("notes.update_note", update_args, update_id)
        self.assertNotIn(original_args["text"], self.store.state_path.read_text())
        with self.assertRaisesRegex(ValueError, "retired"):
            self.store.request("notes.append_note", original_args, original_id)
        self.assertEqual(
            self.store.request("notes.update_note", update_args, update_id), updated
        )
        delete_args = {"handle": updated[0]["handle"]}
        deleted = self.store.request("notes.delete_note", delete_args, delete_id)
        self.assertNotIn(update_args["new_text"], self.store.state_path.read_text())
        self.store = self.open()
        with self.assertRaisesRegex(ValueError, "retired"):
            self.store.request("notes.update_note", update_args, update_id)
        self.assertEqual(
            self.store.request("notes.delete_note", delete_args, delete_id), deleted
        )
        self.assertEqual(self.call("notes.read_notes"), [])

    def test_journal_forget_retires_legacy_receipt_without_references(self):
        request_id = str(uuid.uuid4())
        args = {"text": "synthetic forgotten journal", "source": "chat"}
        created = self.store.request("journal.save_entry", args, request_id)
        state = self.store.state()
        state["receipts"][request_id].pop(
            "records"
        )  # Pre-fix persisted receipt format.
        atomic(self.store.state_path, json.dumps(state).encode())
        self.call("journal.delete_entry", entry_id=created["entry_id"])
        self.assertNotIn(args["text"], self.store.state_path.read_text())
        self.store = self.open()
        with self.assertRaisesRegex(ValueError, "retired"):
            self.store.request("journal.save_entry", args, request_id)
        self.assertEqual(self.call("journal.list_entries"), [])

    def test_backup_restores_records_and_next_id(self):
        import zipfile

        self.call("journal.save_entry", text="backup fixture", source="chat")
        backup = next((self.root / "backups").glob("*.zip"))
        with zipfile.ZipFile(backup) as z:
            state = json.loads(z.read("state.json"))
            self.assertEqual(state["allocation_floor"], 1)
            self.assertEqual(
                len([n for n in z.namelist() if n.startswith("notes/")]), 1
            )

    def test_restore_reverse_export_and_deleted_id_floor(self):
        from scripts.fitness_migration.restore_store import restore
        from scripts.fitness_migration.export_legacy import export
        import sqlite3

        self.call("notes.append_note", text="synthetic preserved preference")
        self.call(
            "journal.save_entry", text="synthetic retained journal", source="chat"
        )
        self.call("journal.save_entry", text="synthetic deleted journal", source="chat")
        self.call("journal.delete_entry", entry_id=2)
        before = self.call("snapshot")
        archive = max(
            (self.root / "backups").glob("*.zip"), key=lambda p: p.stat().st_mtime_ns
        )
        result = restore(archive, self.root / "restored")
        restored = FitnessStore(
            result["vault"], result["control"], self.notes, self.journal
        )
        self.assertEqual(restored.request("snapshot", {}), before)
        destination = self.root / "export"
        export(restored, destination)
        self.assertEqual(
            self.notes.render_for_prompt(destination / "user_notes.md"),
            self.call("notes.render_for_prompt"),
        )
        with sqlite3.connect(destination / "journal.sqlite") as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name='coach_journal'"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                conn.execute("SELECT text FROM coach_journal").fetchall(),
                [("synthetic retained journal",)],
            )
        added = restored.request(
            "journal.save_entry",
            {"text": "after restored deletion", "source": "chat"},
            str(uuid.uuid4()),
        )
        self.assertEqual(added["entry_id"], 3)

    def test_manual_edit_gets_new_backup_without_application_revision(self):
        self.call("notes.append_note", text="original synthetic")
        path = next(self.vault.glob("Preferences/*.md"))
        path.write_text(
            path.read_text().replace("original synthetic", "edited synthetic")
        )
        self.store.backup()
        self.assertEqual(len(list((self.root / "backups").glob("*.zip"))), 2)
        self.assertEqual(self.call("notes.read_notes")[0]["text"], "edited synthetic")
