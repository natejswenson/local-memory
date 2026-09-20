import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml

spec = importlib.util.spec_from_file_location("workspace", Path(__file__).parents[2] / "scripts/install_vault_workspace.py")
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


class WorkspaceTests(unittest.TestCase):
    def test_bases_exclusions_handoff_kind_and_scratch_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            vault = root / "vault"
            (vault / "Scratch").mkdir(parents=True)
            scratch = vault / "Scratch/idea.md"
            scratch.write_text("Plain scratch note")
            workspace.install(vault, root / "backup", True)
            self.assertEqual(scratch.read_text(), "Plain scratch note")
            self.assertIn("kind: handoff", (vault / "Templates/Project handoff.md").read_text())
            base = yaml.safe_load((vault / "Memory views.base").read_text())
            self.assertEqual(len(base["views"]), 3)
            self.assertIn('!file.inFolder("SkillMemory")', base["filters"]["and"])
            custom = (vault / "Memory views.base").read_text() + "# My change\n"
            (vault / "Memory views.base").write_text(custom)
            workspace.install(vault, root / "backup", True)
            self.assertEqual((vault / "Memory views.base").read_text(), custom)
    def test_exact_empty_starter_redirects_but_user_content_is_preserved(self):
        starter = '---\ntitle: Projects\ntype: note\npermalink: local-memory/inbox/projects\n---\n\n'
        for body in ("", "My personal project notes.\n"):
            with self.subTest(body=bool(body)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                vault = root / "vault"
                (vault / "Inbox").mkdir(parents=True)
                note = vault / "Inbox/Projects.md"
                note.write_text(starter + body)
                workspace.install(vault, root / "backup", True)
                if body:
                    self.assertEqual(note.read_text(), starter + body)
                else:
                    self.assertIn("type: navigation", note.read_text())
                    self.assertIn("[[Projects/_Index|", note.read_text())
                    backups = list((root / "backup").glob("*/Inbox/Projects.md"))
                    self.assertEqual(backups[0].read_text(), starter)
                    self.assertNotIn("Projects.md", (vault / "Inbox/_Index.md").read_text())
                    self.assertEqual(workspace.install(vault, root / "backup", True)["changed"], [])

    def test_preserves_notes_settings_custom_text_and_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            vault = root / "vault"
            vault.mkdir()
            home = vault / "Home.md"
            home.write_text('---\ntype: navigation\n---\nMy introduction.\n\n' + workspace.STARTER_LINKS + '\nMy footer.\n')
            inbox = vault / "Inbox"
            inbox.mkdir()
            old_note = inbox / "Projects.md"
            old_note.write_text('---\ntitle: Projects\ntype: note\n---\n')
            obsidian = vault / ".obsidian"
            obsidian.mkdir()
            (obsidian / "templates.json").write_text('{"dateFormat":"YYYY","folder":"Templates"}')
            preview = workspace.install(vault, root / "backup")
            self.assertFalse((vault / "Templates").exists())
            workspace.install(vault, root / "backup", True)
            self.assertIn('My introduction.', home.read_text())
            self.assertIn('My footer.', home.read_text())
            self.assertIn('[[Projects/_Index|', home.read_text())
            self.assertTrue(old_note.exists())
            self.assertIn('YYYY', (obsidian / 'templates.json').read_text())
            self.assertEqual(workspace.install(vault, root / "backup", True)["changed"], [])
            template = vault / "Templates/Decision.md"
            template.write_text('Custom template')
            workspace.install(vault, root / "backup", True)
            self.assertEqual(template.read_text(), 'Custom template')
            self.assertTrue(list((root / "backup").glob('*/Home.md')))

    def test_unmanaged_page_or_symlink_refused_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            vault = root / "vault"
            (vault / "Preferences").mkdir(parents=True)
            page = vault / "Preferences/_Index.md"
            page.write_text('---\ntype: navigation\n---\nPersonal index')
            with self.assertRaises(ValueError):
                workspace.install(vault, root / "backup", True)
            self.assertFalse((vault / "Home.md").exists())
            page.unlink()
            (vault / "Templates").symlink_to(root / "elsewhere")
            with self.assertRaises(ValueError):
                workspace.install(vault, root / "backup", True)
            self.assertFalse((vault / "Home.md").exists())
