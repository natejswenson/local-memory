import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
from scripts import install_activity, activity_memory


class ActivityInstallTests(unittest.TestCase):
    def test_daemon_readiness_uses_its_own_python(self):
        with patch.object(activity_memory.subprocess, 'check_output', return_value=b'{"ready":true}') as run:
            activity_memory.ready()
        self.assertEqual(run.call_args.args[0], [activity_memory.sys.executable,
                         str(activity_memory.ROOT / 'bin/memory-hub'), 'doctor'])

    def test_preserves_hooks_and_repeated_install_and_requires_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); project = root / 'project'; home = root / 'home'
            (home / '.codex').mkdir(parents=True)
            original = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': '/safe/existing'}]}]}}
            path = home / '.codex/hooks.json'; path.write_text(json.dumps(original))
            with patch.object(install_activity, 'ROOT', project):
                preview = install_activity.install(home)
                self.assertFalse(preview['applied'])
                with self.assertRaises(ValueError):
                    install_activity.install(home, True)
                self.assertEqual(json.loads(path.read_text()), original)
                (project / '.runtime/live').mkdir(parents=True)
                (project / '.runtime/live/activation.json').write_text('{}')
                result = install_activity.install(home, True)
                one = path.read_bytes(); install_activity.install(home, True)
                self.assertEqual(path.read_bytes(), one)
                self.assertEqual(json.loads(one)['hooks']['Stop'], original['hooks']['Stop'])
                self.assertEqual(len(json.loads(one)['hooks']['PostToolUse']), 1)
                job = plistlib.loads(Path(result['plist']).read_bytes())
                self.assertEqual(job['StartInterval'], 300)
                self.assertTrue(job['RunAtLoad'])
                self.assertNotIn('notify', json.loads(one))

    def test_rejects_symlink_and_unmanaged_job_before_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); home = root / 'home'; home.mkdir()
            (home / '.codex').symlink_to(root / 'outside')
            with self.assertRaises(ValueError):
                install_activity.install(home, True)
