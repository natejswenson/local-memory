import json
from pathlib import Path
import plistlib
import tempfile
import tomllib
import unittest
from scripts.install_fitness import install, install_mcp, mcp_configuration, BEGIN, END


class InstallerTests(unittest.TestCase):
    def test_preserves_unrelated_config_repairs_comments_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            repo, compose, control, home = [
                root / s for s in ("repo", "compose", "control", "home")
            ]
            for d in (
                repo,
                compose,
                control,
                home / ".codex",
                home / "Library/LaunchAgents",
            ):
                d.mkdir(parents=True)
            (control / "config.json").write_text(
                json.dumps({"fitness_repo": str(repo), "port": 8766})
            )
            (repo / ".env").write_text("EXISTING=synthetic\n")
            (compose / ".env").write_text("DOMAIN=synthetic\n")
            original = "services:\n  local-fitness:\n    environment:\n      - TZ=America/Chicago\n    volumes:\n      - ./data:/data\n  other:\n    environment:\n      - OTHER=yes\n"
            (compose / "docker-compose.yml").write_text(original)
            (home / ".codex/config.toml").write_text(
                'model = "synthetic"\n[mcp_servers.other]\ncommand="keep"\n'
            )
            job = home / "Library/LaunchAgents/com.localfitness.brief.plist"
            settings = {
                "Label": "com.localfitness.brief",
                "RunAtLoad": False,
                "ProgramArguments": ["fixture"],
                "StartCalendarInterval": {"Hour": 8},
            }
            job.write_bytes(
                plistlib.dumps(settings).replace(
                    b"<dict>", b"<!-- bad -- comment -->\n<dict>", 1
                )
            )
            self.assertFalse(install(repo, compose, control, home)["applied"])
            self.assertEqual((compose / "docker-compose.yml").read_text(), original)
            install(repo, compose, control, home, True)
            self.assertEqual(plistlib.loads(job.read_bytes()), settings)
            cfg = tomllib.loads((home / ".codex/config.toml").read_text())
            self.assertEqual(cfg["mcp_servers"]["other"]["command"], "keep")
            self.assertEqual(cfg["mcp_servers"]["fitness"]["args"], ["mcp-stdio"])
            self.assertNotIn("enabled_tools", cfg["mcp_servers"]["fitness"])
            self.assertNotIn("fitness_memory", cfg["mcp_servers"])
            changed = (compose / "docker-compose.yml").read_text()
            self.assertEqual(
                changed.split("  other:")[1], original.split("  other:")[1]
            )
            self.assertEqual(changed.count("LOCAL_FITNESS_MEMORY_URL"), 1)
            self.assertIn("host.docker.internal", changed)
            self.assertTrue((control / "installation-backup/manifest.json").exists())
            self.assertIn("EXISTING=synthetic", (repo / ".env").read_text())
            daemon = plistlib.loads((home / 'Library/LaunchAgents/com.local-memory-hub.fitness.plist').read_bytes())
            self.assertNotIn('TZ', daemon['EnvironmentVariables'])
            self.assertIn('TZ=America/Chicago', changed)

    def test_upgrade_memory_only_without_losing_other_servers(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve()
            (home / ".codex").mkdir()
            path = home / ".codex/config.toml"
            old = (
                'model = "synthetic"\n[mcp_servers.other]\ncommand="keep"\n'
                + BEGIN
                + '\n[mcp_servers.fitness_memory]\ncommand="old"\n'
                'args=["mcp-stdio","--memory-only"]\nenabled_tools=["list_user_notes"]\n'
                + END
                + "\n"
            )
            path.write_text(old)
            install_mcp(home / "repo", home, True)
            cfg = tomllib.loads(path.read_text())
            self.assertEqual(set(cfg["mcp_servers"]), {"other", "fitness"})
            self.assertEqual(cfg["mcp_servers"]["fitness"]["args"], ["mcp-stdio"])
            self.assertNotIn("enabled_tools", cfg["mcp_servers"]["fitness"])
            self.assertEqual(cfg["mcp_servers"]["other"]["command"], "keep")
            backup = next((home / ".codex/local-memory-install-backup").glob("*.toml"))
            self.assertEqual(backup.read_text(), old)
            self.assertFalse(install_mcp(home / "repo", home, True)["changed"])

    def test_refuses_unmanaged_full_server(self):
        old = (
            '[mcp_servers.fitness]\ncommand="unrelated"\n'
            + BEGIN
            + '\n[mcp_servers.fitness_memory]\ncommand="old"\n'
            + END
        )
        with self.assertRaisesRegex(ValueError, "Unmanaged fitness"):
            mcp_configuration(old, Path("/synthetic/repo"))
