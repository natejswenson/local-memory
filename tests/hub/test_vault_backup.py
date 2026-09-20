import hashlib
import importlib.util
import json
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location(
    "vault_backup", Path(__file__).resolve().parents[2] / "scripts/vault_backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class VaultBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        (self.vault / "note.md").write_text("Remember this.\n")
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian/app.json").write_text('{"theme":"dark"}')
        (self.vault / "index.sqlite").write_bytes(b"not canonical")
        self.destination = self.root / "backups"

    def test_roundtrip_private_permissions_and_retention(self):
        archive = None
        for _ in range(3):
            archive = backup.backup(self.vault, self.destination, retain=2)["archive"]
        self.assertEqual(len(list(self.destination.glob("*.zip"))), 2)
        self.assertEqual(Path(archive).stat().st_mode & 0o777, 0o600)
        target = self.root / "quarantine"
        result = backup.restore(archive, target)
        self.assertFalse(result["activated"])
        self.assertEqual((target / "note.md").read_bytes(), (self.vault / "note.md").read_bytes())
        self.assertTrue((target / ".obsidian/app.json").exists())
        self.assertFalse((target / "index.sqlite").exists())
        with self.assertRaises(ValueError):
            backup.restore(archive, target)
        self.assertTrue((target / "note.md").exists())

    def test_workspace_assets_and_skill_control_roundtrip_stay_quarantined(self):
        for name in ["view.base", "map.canvas", "image.png", "attachment.pdf"]:
            (self.vault / name).write_bytes(b"synthetic asset")
        control = self.root / "control"
        control.mkdir()
        (control / "config.json").write_text('{"version":1,"bindings":{}}')
        (control / "forgotten.json").write_text('{"old":{"operation":"synthetic"}}')
        result = backup.backup(self.vault, self.destination, skill_control=control)
        # Simulate forgetting after snapshot: restore must not roll this back.
        latest = '{"old":{"operation":"synthetic"},"new":{"operation":"later"}}'
        (control / "forgotten.json").write_text(latest)
        target = self.root / "quarantine"
        restored = backup.restore(result["archive"], target)
        self.assertTrue(restored["requires_current_ledger_reconciliation"])
        self.assertFalse(restored["activated"])
        self.assertEqual((control / "forgotten.json").read_text(), latest)
        self.assertTrue((target / "skill-control/forgotten.json").exists())
        self.assertFalse((target / "skill-control/writer.lock").exists())
        for name in ["view.base", "map.canvas", "image.png", "attachment.pdf"]:
            self.assertEqual((target / "vault" / name).read_bytes(), b"synthetic asset")

    def test_control_missing_or_changed_refuses_publication(self):
        with self.assertRaises(ValueError):
            backup.backup(self.vault, self.destination, skill_control=self.root / "missing")
        control = self.root / "control"
        control.mkdir()
        ledger = control / "forgotten.json"
        ledger.write_text('{}')
        original, calls = backup.inventory, 0

        def mutate(*args, **kw):
            nonlocal calls
            calls += 1
            if calls == 5:
                ledger.write_text('{"changed":true}')
            return original(*args, **kw)

        with patch.object(backup, "inventory", side_effect=mutate), self.assertRaises(ValueError):
            backup.backup(self.vault, self.destination, skill_control=control)
        self.assertEqual(list(self.destination.glob("*.zip")), [])

    def test_refuses_nested_destination_and_symlinks(self):
        with self.assertRaises(ValueError):
            backup.backup(self.vault, self.vault / "backups")
        external = self.root / "private.md"
        external.write_text("Do not follow")
        (self.vault / "link.md").symlink_to(external)
        with self.assertRaises(ValueError):
            backup.backup(self.vault, self.destination)
        self.assertFalse(self.destination.exists())

    def crafted(self, name, contents=b"hello", expected=None):
        archive = self.root / "crafted.zip"
        manifest = {"format": backup.FORMAT, "files": {name: expected or {
            "sha256": hashlib.sha256(contents).hexdigest(), "size": len(contents)}}}
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("manifest.json", json.dumps(manifest))
            stream.writestr("files/" + name, contents)
        return archive

    def test_path_traversal_rejected_before_creation(self):
        for name in ("../escape.md", "/escape.md", "a/../../escape.md", "a\\escape.md"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                backup.restore(self.crafted(name), self.root / "quarantine")
            self.assertFalse((self.root / "quarantine").exists())
        self.assertFalse((self.root / "escape.md").exists())

    def test_checksum_tampering_rejected(self):
        archive = self.crafted("note.md", expected={"size": 5, "sha256": "0" * 64})
        with self.assertRaises(ValueError):
            backup.restore(archive, self.root / "quarantine")
        self.assertFalse((self.root / "quarantine").exists())

    def test_archive_symlink_and_unlisted_file_rejected(self):
        archive = self.crafted("note.md")
        with zipfile.ZipFile(archive, "a") as stream:
            link = zipfile.ZipInfo("files/link.md")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            stream.writestr(link, "../private.md")
        with self.assertRaises(ValueError):
            backup.restore(archive, self.root / "quarantine")
        archive = self.crafted("note.md")
        with zipfile.ZipFile(archive, "a") as stream:
            stream.writestr("files/extra.md", "unlisted")
        with self.assertRaises(ValueError):
            backup.restore(archive, self.root / "quarantine")
        self.assertFalse((self.root / "quarantine").exists())

    def test_source_mutation_does_not_publish_or_prune(self):
        first = backup.backup(self.vault, self.destination)["archive"]
        original = backup.inventory
        calls = 0

        def changing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                (self.vault / "note.md").write_text("Changed during snapshot")
            return original(*args, **kwargs)

        with patch.object(backup, "inventory", side_effect=changing):
            with self.assertRaises(ValueError):
                backup.backup(self.vault, self.destination, retain=1)
        self.assertEqual(list(self.destination.iterdir()), [Path(first)])


if __name__ == "__main__":
    unittest.main()
