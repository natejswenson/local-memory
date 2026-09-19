import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

spec = importlib.util.spec_from_file_location("install", Path(__file__).parents[2] / "scripts/install_codex.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InstallTests(unittest.TestCase):
    def test_preserves_settings_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            original = 'model = "existing"\n[mcp_servers.existing]\ncommand = "keep-me"\n'
            (home / "config.toml").write_text(original)
            (home / "AGENTS.md").write_text("Existing instructions.\n")
            module.install(home, True)
            one = (home / "config.toml").read_text()
            module.install(home, True)
            self.assertEqual(one, (home / "config.toml").read_text())
            config = tomllib.loads(one)
            self.assertEqual(config['model'], 'existing')
            self.assertEqual(config['mcp_servers']['existing']['command'], 'keep-me')
            self.assertFalse(config['mcp_servers']['local_memory_hub']['enabled'])
            self.assertTrue((home / 'AGENTS.md').read_text().startswith('Existing instructions.'))
            self.assertEqual((home / 'local-memory-install-backup/config.toml').read_text(), original)

    def test_refuses_override_or_unmanaged_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            (home / 'AGENTS.override.md').write_text('Override')
            with self.assertRaises(ValueError):
                module.install(home, True)
            self.assertFalse((home / 'config.toml').exists())
            (home / 'AGENTS.override.md').unlink()
            (home / 'config.toml').write_text('[mcp_servers.local_memory_hub]\ncommand="other"\n')
            with self.assertRaises(ValueError):
                module.install(home, True)

    def test_refuses_redirected_directories_before_writes(self):
        for relative in ("local-memory-install-backup", "skills"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                home, external = root / "home", root / "external"
                home.mkdir()
                external.mkdir()
                (home / relative).symlink_to(external, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    module.install(home, True)
                self.assertEqual(list(external.iterdir()), [])
                self.assertFalse((home / "config.toml").exists())

    def test_refuses_symlink_home_and_dangling_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            actual = root / "actual"
            actual.mkdir()
            home = root / "home"
            home.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                module.install(home / "child", True)
            self.assertFalse((actual / "child").exists())
            config = actual / "config.toml"
            config.symlink_to(root / "uncreated.toml")
            with self.assertRaisesRegex(ValueError, "symlink"):
                module.install(actual, True)
            self.assertTrue(config.is_symlink())
            self.assertFalse((root / "uncreated.toml").exists())

    def test_rejects_removal_of_unrelated_settings_inside_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            original = '\n'.join([
                module.BEGIN, '[mcp_servers.local_memory_hub]', 'command="old"',
                '[profiles.work]', 'model="keep-this"', module.END, ''])
            config = home / "config.toml"
            config.write_text(original)
            with self.assertRaisesRegex(ValueError, "Unrelated configuration"):
                module.install(home, True)
            self.assertEqual(config.read_text(), original)
            self.assertFalse((home / "local-memory-install-backup").exists())

    def test_pilot_mode_is_enabled_and_preserved_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            module.install(home, True, 'pilot')
            module.install(home, True)
            server = tomllib.loads((home / 'config.toml').read_text())['mcp_servers']['local_memory_hub']
            self.assertTrue(server['enabled'])
            self.assertEqual(server['args'], ['mcp', '--pilot'])
            module.install(home, True, 'disabled')
            self.assertFalse(tomllib.loads((home / 'config.toml').read_text())['mcp_servers']['local_memory_hub']['enabled'])


if __name__ == '__main__':
    unittest.main()
