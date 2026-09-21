"""Synthetic privacy boundaries plus inspection of the actual committed index."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_tree', ROOT / 'scripts/check_public_tree.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class PublicRepositoryTests(unittest.TestCase):
    def test_tracked_tree_has_no_private_paths_or_obvious_sensitive_text(self):
        self.assertEqual(policy.scan_index(ROOT), [])

    def test_private_artifacts_rejected_and_core_examples_allowed(self):
        for path in ('vault/note.md', '.runtime/control.json', '.local/profile.json',
                     '.env', 'copy/project-registry.json', 'snapshot.db', ':memory:.ses',
                     'backup.fernet', '.issueflow/run/state.json', 'AGENTS.local.md'):
            with self.subTest(path=path):
                self.assertTrue(policy.inspect_blob(path, b'synthetic'))
        for path in ('memory_hub/capture.py', 'tests/fixtures/example.json', '.env.example',
                     '.issueflow/README.md', '.issueflow/completion.json'):
            self.assertFalse(policy.inspect_blob(path, b'synthetic'))
        key = b'-----BEGIN ' + b'PRIVATE KEY-----\n' + b'A' * 64
        self.assertEqual(policy.inspect_blob('unexpected.txt', key), [('private-key', 1)])

    def test_checks_index_even_when_worktree_looks_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                subprocess.run(['git', '-C', tmp, *args], check=True, capture_output=True)
            git('init', '-q')
            path = Path(tmp) / 'example.txt'
            path.write_text('/' + 'Users' + '/synthetic-owner/private')
            git('add', 'example.txt')
            path.write_text('A harmless working-tree replacement')
            self.assertEqual(policy.scan_index(tmp), [('example.txt', 'absolute-home-path', 1)])
            git('add', 'example.txt')
            self.assertEqual(policy.scan_index(tmp), [])

    def test_effective_commit_email_must_be_public_noreply(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                subprocess.run(['git', '-C', tmp, *args], check=True, capture_output=True)
            git('init', '-q'); git('config', 'user.name', 'Synthetic Author')
            git('config', 'user.email', 'synthetic@example.invalid')
            self.assertFalse(policy.check_identity(tmp))
            git('config', 'user.email', '123+synthetic@users.noreply.github.com')
            self.assertTrue(policy.check_identity(tmp))


if __name__ == '__main__':
    unittest.main()
