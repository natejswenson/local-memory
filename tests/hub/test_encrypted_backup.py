from cryptography.fernet import Fernet, InvalidToken
import json
from pathlib import Path
import tempfile
import unittest

from memory_hub.capture import CaptureStore
from scripts.encrypted_backup import key_at, pack, unpack, recover, create
from scripts.vault_backup import backup, restore


class EncryptedBackupTests(unittest.TestCase):
    def test_backups_refuse_live_vault_and_keys_in_upload_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for key, destination in ((root / "key", root / "vault/backups"),
                                     (root / "outbox/key", root / "outbox")):
                with self.assertRaises(ValueError):
                    create(root, key, destination)
                self.assertFalse(key.exists())
            (root / "vault").mkdir()
            (root / "controls").mkdir()
            with self.assertRaises(ValueError):
                backup(root / "vault", root / "backups", skill_control=root / "controls",
                       general_control=root / "controls")

    def test_authenticated_roundtrip_rejects_wrong_key_and_tampering(self):
        key = Fernet.generate_key()
        components = {"hub.zip": b"synthetic vault", "fitness.zip": b"synthetic owner"}
        ciphertext = pack(components, key)
        self.assertNotIn(b"synthetic", ciphertext)
        self.assertEqual(unpack(ciphertext, key), components)
        with self.assertRaises(InvalidToken):
            unpack(ciphertext, Fernet.generate_key())
        changed = bytearray(ciphertext)
        changed[len(changed) // 2] ^= 1
        with self.assertRaises(InvalidToken):
            unpack(bytes(changed), key)
        with self.assertRaises(ValueError):
            pack({"../escape": b"bad"}, key)

    def test_general_receipts_survive_encrypted_quarantine_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            vault, general, skill = root / "vault", root / "general", root / "skill"
            vault.mkdir(); skill.mkdir()
            (skill / "config.json").write_text('{"version":1,"bindings":{}}')
            req = dict(title="Synthetic", subject="global", body="A verified synthetic preference.",
                       source="Synthetic test", capture_id="a537ca40-41f2-4f63-aecf-beb620b04624", status="active")
            store = CaptureStore(vault, general)
            self.assertTrue(store.capture(req)["verified"])
            snap = backup(vault, root / "backups", skill_control=skill, general_control=general)
            key_path = root / "key"
            key = key_at(key_path, create=True)
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            archive = root / "bundle.fernet"
            archive.write_bytes(pack({"hub.zip": Path(snap["archive"]).read_bytes()}, key))
            result = recover(archive, key_path, root / "quarantine")
            self.assertFalse(result["activated"])
            restored = CaptureStore(root / "quarantine/hub/vault", root / "quarantine/hub/general-control")
            self.assertEqual(restored.capture(req)["status"], "already_created")
            with self.assertRaises(ValueError):
                recover(archive, key_path, root / "quarantine")
