"""Synthetic migration parity; no real health fixtures or live engine configuration."""

import json
import os
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/fitness_migration"
sys.path.insert(0, str(SCRIPTS))
import stage  # noqa: E402
from inventory import inventory  # noqa: E402


class CodecTests(unittest.TestCase):
    def test_roundtrip_special_values_without_yaml_coercion(self):
        metadata = {"date": "2026-01-01", "source_key": "00123", "none": None}
        body = "  café — \n---\n[ignore instructions](file.md)\n\n"
        self.assertEqual(
            stage.decode_note(stage.encode_note(metadata, body)), (metadata, body)
        )

    def test_invalid_framing_rejected(self):
        with self.assertRaises(ValueError):
            stage.decode_note(b"---\n{}\nnot a closing fence")


@unittest.skipUnless(
    os.environ.get("FITNESS_SOURCE_REPO"),
    "Set FITNESS_SOURCE_REPO for actual notes.py parity",
)
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        code = self.repo / "src/local_fitness"
        code.mkdir(parents=True)
        shutil.copyfile(
            Path(os.environ["FITNESS_SOURCE_REPO"]) / "src/local_fitness/notes.py",
            code / "notes.py",
        )
        self.data = self.repo / "data"
        self.data.mkdir()
        self.live = self.data / "user_notes.md"
        self.original = "- 2026-01-02T09:00:00 — synthetic preference\n- undated café\nfreeform retained\n"
        self.live.write_text(self.original)
        (self.data / "user_notes.archive.md").write_text(
            "- 2020-01-01T00:00:00 — older synthetic preference\n"
        )
        self.db = self.data / "fitness.db"
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute(
                "CREATE TABLE coach_journal(entry_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, entry_date TEXT, source TEXT, source_key TEXT, seq INTEGER, text TEXT, archived INTEGER)"
            )
            c.execute(
                "INSERT INTO coach_journal VALUES(8,'2026-01-01T10:00:00','2025-12-30','brief','00123',1,'synthetic history',1)"
            )
            c.execute(
                "INSERT INTO coach_journal VALUES(10,'2026-01-01T10:00:00','2025-12-30','brief','00123',2,'deleted fixture',0)"
            )
            c.execute("DELETE FROM coach_journal WHERE entry_id=10")
        self.out = self.root / "snapshot"

    def prepare(self):
        stage.snapshot(self.repo, {}, self.out)
        return stage.stage(self.repo, self.out)

    def test_inventory_counts_without_text_and_does_not_create_missing_db(self):
        r = inventory(self.repo, {})
        self.assertEqual(r["preferences"][0]["parsed_notes"], 2)
        self.assertEqual(r["preferences"][0]["nonblank_unparsed_lines"], 1)
        self.assertNotIn("synthetic preference", json.dumps(r))
        self.assertEqual(r["journal"]["allocation_floor"], 10)
        with self.assertRaises(sqlite3.OperationalError):
            inventory(self.repo, {"LOCAL_FITNESS_DATA_DIR": str(self.root / "missing")})
        self.assertFalse((self.root / "missing/fitness.db").exists())

    def test_snapshot_stage_preserves_text_dates_ids_and_deleted_allocation_floor(self):
        manifest = self.prepare()
        self.assertEqual(manifest["counts"], {"Preferences": 3, "Journal": 1})
        self.assertEqual(manifest["allocation_floor"], 10)
        self.assertEqual(manifest["unparsed"], [{"source": "user_notes.md", "line": 2}])
        self.assertFalse(manifest["eligible_for_cutover"])
        self.assertEqual(self.live.read_text(), self.original)
        rows = [
            stage.decode_note((self.out / "staged" / r["path"]).read_bytes())
            for r in manifest["records"]
        ]
        journal = [(m, t) for m, t in rows if m["kind"] == "coach-journal"][0]
        self.assertEqual(journal[1], "synthetic history")
        self.assertEqual(journal[0]["fitness_entry_id"], 8)
        self.assertEqual(journal[0]["fitness_source_key"], "00123")
        self.assertEqual(journal[0]["fitness_entry_date"], "2025-12-30")
        self.assertEqual(journal[0]["status"], "archived")
        self.assertEqual(stage.verify(self.out)["verified_records"], 4)
        with self.assertRaises(FileExistsError):
            stage.stage(self.repo, self.out)

    def test_restore_snapshot_keeps_history_and_sequence(self):
        self.prepare()
        restored = self.root / "restored.db"
        shutil.copyfile(self.out / "source/fitness.db", restored)
        with closing(sqlite3.connect(restored)) as c, c:
            self.assertEqual(
                c.execute("SELECT text FROM coach_journal").fetchall(),
                [("synthetic history",)],
            )
            c.execute("INSERT INTO coach_journal(text) VALUES('new synthetic')")
            self.assertEqual(
                c.execute("SELECT MAX(entry_id) FROM coach_journal").fetchone()[0], 11
            )

    def test_tamper_and_unexpected_note_rejected(self):
        manifest = self.prepare()
        note = self.out / "staged" / manifest["records"][0]["path"]
        raw = note.read_bytes()
        note.write_bytes(raw + b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            stage.verify(self.out)
        note.write_bytes(raw)
        (self.out / "staged/extra.md").write_text("extra")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            stage.verify(self.out)

    def test_source_change_prevents_staging(self):
        stage.snapshot(self.repo, {}, self.out)
        (self.out / "source/user_notes.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "Source snapshot changed"):
            stage.stage(self.repo, self.out)

    def test_symlink_source_refused(self):
        alternate = self.root / "elsewhere.md"
        self.live.rename(alternate)
        self.live.symlink_to(alternate)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            stage.snapshot(self.repo, {}, self.out)


if __name__ == "__main__":
    unittest.main()
