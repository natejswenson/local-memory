import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "install_backup", Path(__file__).resolve().parents[2] / "scripts/install_backup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.repo, self.home = self.base / "repo", self.base / "home"
        self.home.mkdir()
        (self.repo / "vault").mkdir(parents=True)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts/vault_backup.py").write_text("# fixture")
        (self.repo / ".venv/bin").mkdir(parents=True)
        runtime = self.base / "python"
        runtime.write_text("#!/bin/sh\nexit 0\n")
        runtime.chmod(0o700)
        (self.repo / ".venv/bin/python").symlink_to(runtime)
        self.addCleanup(patch.stopall)
        patch.object(module, "ROOT", self.repo).start()

    def test_preview_no_writes_then_install_is_idempotent(self):
        result = module.install(self.home)
        plist = Path(result["plist"])
        self.assertFalse(plist.exists())
        self.assertFalse(Path(result["destination"]).exists())
        self.assertFalse((self.repo / ".runtime").exists())
        module.install(self.home, True)
        contents = plist.read_bytes()
        data = plistlib.loads(contents)
        self.assertEqual(data["StartInterval"], 86400)
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["ProgramArguments"][-2:], ["--retain", "14"])
        self.assertEqual(data["ProgramArguments"][0], str(self.repo / ".venv/bin/python"))
        unrelated = plist.parent / "other.plist"
        unrelated.write_bytes(b"untouched")
        log = Path(data["StandardOutPath"])
        log.write_text("existing backup log")
        module.install(self.home, True)
        self.assertEqual(plist.read_bytes(), contents)
        self.assertEqual(unrelated.read_bytes(), b"untouched")
        self.assertEqual(log.read_text(), "existing backup log")
        self.assertEqual(plist.stat().st_mode & 0o777, 0o600)

    def test_unmanaged_plist_refused_before_side_effects(self):
        result = module.install(self.home)
        plist = Path(result["plist"])
        plist.parent.mkdir(parents=True)
        contents = plistlib.dumps({"Label": module.LABEL, "ProgramArguments": ["other"]})
        plist.write_bytes(contents)
        with self.assertRaisesRegex(ValueError, "Unmanaged"):
            module.install(self.home, True)
        self.assertEqual(plist.read_bytes(), contents)
        self.assertFalse(Path(result["destination"]).exists())

    def test_existing_skill_control_is_included_in_schedule(self):
        control = self.repo / ".runtime/skill-memory"
        control.mkdir(parents=True)
        result = module.install(self.home)
        args = result["configuration"]["ProgramArguments"]
        self.assertEqual(args[args.index("--skill-control") + 1], str(control))

    def test_redirected_launchagents_and_log_refused(self):
        result = module.install(self.home)
        external = self.base / "external"
        external.mkdir()
        (self.home / "Library").mkdir()
        agents = self.home / "Library/LaunchAgents"
        agents.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            module.install(self.home, True)
        self.assertEqual(list(external.iterdir()), [])
        agents.unlink()
        logfile = Path(result["configuration"]["StandardOutPath"])
        logfile.parent.mkdir(parents=True)
        logfile.symlink_to(external / "outside.log")
        with self.assertRaisesRegex(ValueError, "symlink"):
            module.install(self.home, True)
        self.assertFalse((external / "outside.log").exists())

    def test_other_installation_owned_plist_refused(self):
        result = module.install(self.home, True)
        plist = Path(result["plist"])
        data = plistlib.loads(plist.read_bytes())
        data["ProgramArguments"][0] = "/different/repo/.venv/bin/python"
        contents = plistlib.dumps(data).replace(b"<plist version=", module.MARKER + b"\n<plist version=", 1)
        plist.write_bytes(contents)
        with self.assertRaisesRegex(ValueError, "different installation"):
            module.install(self.home, True)
        self.assertEqual(plist.read_bytes(), contents)


if __name__ == "__main__":
    unittest.main()
