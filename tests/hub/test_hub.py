import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[2] / 'bin/memory-hub'
loader = importlib.machinery.SourceFileLoader('hub', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
hub = importlib.util.module_from_spec(spec)
loader.exec_module(hub)


class HubTests(unittest.TestCase):
    def test_symlink_ancestor_and_dangling_leaf_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            outside = root / 'outside'
            outside.mkdir()
            with patch.object(hub, 'ROOT', root):
                (root / '.runtime').symlink_to(outside)
                with self.assertRaises(ValueError):
                    hub.initialize(True)
                self.assertEqual(list(outside.iterdir()), [])
                (root / '.runtime').unlink()
                config = root / '.runtime/pilot/config'
                config.mkdir(parents=True)
                (config / 'config.json').symlink_to(outside / 'missing')
                with self.assertRaises(ValueError):
                    hub.initialize(True)
                self.assertFalse((outside / 'missing').exists())

    def test_config_cannot_redirect_pilot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(hub, 'ROOT', root):
                hub.initialize(True)
                with patch.dict('os.environ', {'BASIC_MEMORY_CLOUD_API_KEY': 'synthetic'}):
                    env = hub.environment(True)
                    self.assertNotIn('BASIC_MEMORY_CLOUD_API_KEY', env)
                    self.assertEqual(env['BASIC_MEMORY_AUTO_UPDATE'], 'false')
                config = root / '.runtime/pilot/config/config.json'
                value = json.loads(config.read_text())
                value['projects']['local-memory']['path'] = str(root / 'elsewhere')
                config.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    hub.environment(True)

    def test_activation_requires_attestation_persisted_note_and_passing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(hub, 'ROOT', root):
                hub.initialize(False)
                hub.initialize(True)
                with self.assertRaises(ValueError):
                    hub.activate(False)
                with self.assertRaises(ValueError):
                    hub.activate(True)
                with self.assertRaises(ValueError):
                    hub.activate(True, '../escape.md')
                note = root / '.runtime/pilot/vault/Inbox/return.md'
                note.write_text('---\nkey: hub.desktop-return\ncapture_id: synthetic-id\n---\n')
                (root / '.runtime/engine-probe.json').write_text(json.dumps({'completed': 'test', 'checks': [{'passed': False}]}))
                (root / '.runtime/recovery-index-evidence.json').write_text('{"ok": true}')
                with self.assertRaises(ValueError):
                    hub.activate(True, 'Inbox/return.md')
                self.assertFalse(hub.activation_valid())
                (root / '.runtime/engine-probe.json').write_text(json.dumps({'completed': 'test', 'checks': [{'passed': True}]}))
                self.assertTrue(hub.activate(True, 'Inbox/return.md')['activated'])
                self.assertTrue(hub.activation_valid())


if __name__ == '__main__':
    unittest.main()

class LauncherIsolationTests(unittest.TestCase):
    def test_unrelated_cwd_cannot_replace_hub_modules(self):
        import subprocess
        launcher = Path(__file__).resolve().parents[2] / 'bin/memory-hub'
        if not (launcher.parent.parent / '.venv/bin/python').exists(): self.skipTest('Installed launcher venv required')
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp).resolve(); poison = cwd / 'memory_hub'; poison.mkdir()
            (poison / '__init__.py').write_text('raise RuntimeError("CWD_MODULE_EXECUTED")')
            result = subprocess.run([str(launcher), 'status', '--json'], cwd=cwd, capture_output=True, text=True)
            self.assertNotIn('CWD_MODULE_EXECUTED', result.stderr)
            self.assertEqual(json.loads(result.stdout)['writer_version'], 2)
