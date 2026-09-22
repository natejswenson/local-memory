import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from memory_hub.backup_v4 import create, restore
from memory_hub.skill_store import atomic


class BackupV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.vault = self.root / 'vault'; self.vault.mkdir()
        self.control = self.root / 'general'; self.control.mkdir()
        (self.control / 'receipt.json').write_text('{"synthetic":true}')
        (self.vault / 'note.md').write_text('Synthetic note\n' * 1000)
        (self.vault / 'empty.md').write_text('')

    def make(self):
        return create(self.vault, self.root / 'backups', general_control=self.control, part_bytes=1024)

    def test_multipart_roundtrip_and_control_preservation(self):
        result = self.make(); self.assertGreater(result['parts'], 1)
        destination = self.root / 'quarantine'
        self.assertFalse(restore(result['archive'], destination)['activated'])
        self.assertEqual((destination / 'vault/note.md').read_bytes(), (self.vault / 'note.md').read_bytes())
        self.assertEqual((destination / 'general-control/receipt.json').read_bytes(), (self.control / 'receipt.json').read_bytes())
        self.assertEqual((destination / 'vault/empty.md').read_bytes(), b'')

    def test_missing_swapped_and_damaged_parts_fail_before_restore(self):
        result = self.make(); bundle = Path(result['archive']); part = bundle / 'part-000000.zip'
        original = part.read_bytes(); part.write_bytes(b'corrupt')
        with self.assertRaises(ValueError): restore(bundle, self.root / 'corrupt')
        self.assertFalse((self.root / 'corrupt').exists())
        part.write_bytes(original); other = self.make()
        part.write_bytes((Path(other['archive']) / part.name).read_bytes())
        with self.assertRaises(ValueError): restore(bundle, self.root / 'swapped')
        part.unlink()
        with self.assertRaises(OSError): restore(bundle, self.root / 'missing')

    def test_source_change_and_budget_fail_without_complete_snapshot(self):
        with self.assertRaises(ValueError): create(self.vault, self.root / 'backup', general_control=self.control, max_logical_bytes=10)
        from memory_hub.backup_v4 import inventory
        calls = 0
        def changing(*args):
            nonlocal calls
            calls += 1
            if calls == 2: (self.vault / 'note.md').write_text('changed')
            return inventory(*args)
        with patch('memory_hub.backup_v4.inventory', side_effect=changing):
            with self.assertRaises(ValueError): self.make()
        self.assertEqual(list((self.root / 'backups').glob('vault-v4-*')), [])

    def test_encrypted_parts_and_manifest_roundtrip(self):
        from memory_hub.encrypted_v4 import create as encrypt, restore as decrypt
        from memory_hub.paths import HubPaths
        import shutil
        paths = HubPaths(self.root)
        paths.control.mkdir(parents=True)
        shutil.copy(self.control / 'receipt.json', paths.control)
        # Recovery source is generic code from the test checkout, not user data.
        paths_source = Path(__file__).resolve().parents[2]
        with patch('scripts.encrypted_backup.recovery_source', return_value=b'synthetic recovery source'):
            result = encrypt(paths, self.root / 'key', self.root / 'encrypted', 1024 * 1024)
        restored = decrypt(result['path'], self.root / 'key', self.root / 'decrypted', 1024 * 1024)
        self.assertFalse(restored['activated'])
        self.assertEqual((self.root / 'decrypted/hub/vault/note.md').read_bytes(), (self.vault / 'note.md').read_bytes())
        manifest = Path(result['path']) / 'manifest.fernet'; raw = bytearray(manifest.read_bytes()); raw[-10] ^= 1; manifest.write_bytes(raw)
        from cryptography.fernet import InvalidToken
        with self.assertRaises(InvalidToken): decrypt(result['path'], self.root / 'key', self.root / 'tampered', 1024 * 1024)
