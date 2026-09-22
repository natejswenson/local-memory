import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from memory_hub.clients import ClientManager
from memory_hub.jsonc import Document
from memory_hub.paths import HubPaths


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); (self.root / 'memory_hub').mkdir()
        for name in ('mcp_server.py', 'schemas.py'): (self.root / 'memory_hub' / name).write_text('# synthetic version')
        self.home = self.root / 'home'; self.home.mkdir()
        self.manager = ClientManager(HubPaths(self.root), self.home)

    def test_jsonc_preserves_comments_strings_trailing_commas_and_rejects_duplicates(self):
        raw = '{\n// keep http://example.test\n"existing": {"text": "/* string */",},\n}'
        changed = Document(raw).set(['mcp', 'local_memory_hub'], {'command': ['/synthetic/tool']})
        self.assertIn('// keep http://example.test', changed)
        self.assertEqual(Document(changed).root.value['existing'], {'text': '/* string */'})
        removed = Document(changed).remove(['mcp', 'local_memory_hub'])
        self.assertEqual(Document(removed).root.value['mcp'], {})
        for text in ('{"x":1,"x":2}', '{"nested":{"x":1,"x":2}}'):
            with self.assertRaises(ValueError): Document(text)

    def test_each_config_adapter_preserves_unrelated_settings_and_rolls_back(self):
        for client in ('codex', 'claude-code', 'claude-desktop', 'opencode', 'vscode'):
            path, namespace, _ = self.manager.location(client)
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = b'# preserve\nmodel = "synthetic"\n' if namespace == 'toml' else b'{// preserve\n"theme":"synthetic",\n}'
            path.write_bytes(raw)
            plan = self.manager.plan(client)
            result = self.manager.apply(plan, plan['plan_hash'])
            self.assertTrue(self.manager.inspect(client)['configured'])
            self.assertFalse(self.manager.inspect(client)['host_verified'])
            self.assertIn(b'preserve', path.read_bytes())
            rollback = self.manager.rollback(result['operation'])
            self.manager.rollback(result['operation'], True, rollback['plan_hash'])
            self.assertEqual(path.read_bytes(), raw)

    def test_stale_plan_collision_and_external_edit_rollback_are_refused(self):
        path, _, _ = self.manager.location('opencode'); path.parent.mkdir(parents=True)
        path.write_text('{}')
        plan = self.manager.plan('opencode'); path.write_text('{"changed":true}')
        with self.assertRaises(ValueError): self.manager.apply(plan, plan['plan_hash'])
        plan = self.manager.plan('opencode'); result = self.manager.apply(plan, plan['plan_hash'])
        path.write_text('{"newer":"user edit"}')
        rolled = self.manager.rollback(result['operation'], True)
        self.assertEqual(rolled['status'], 'recovery_required')
        self.assertEqual(json.loads(path.read_text()), {'newer': 'user edit'})

    def test_failure_after_first_write_restores_exact_inputs(self):
        path, _, instruction = self.manager.location('claude-code'); path.write_text('{"keep":true}')
        plan = self.manager.plan('claude-code')
        from memory_hub.clients import atomic
        def fail_once(destination, raw):
            if destination == instruction: raise OSError('Synthetic disk failure')
            return atomic(destination, raw)
        with patch('memory_hub.clients.atomic', side_effect=fail_once):
            with self.assertRaises(OSError): self.manager.apply(plan, plan['plan_hash'])
        self.assertEqual(path.read_text(), '{"keep":true}')
        self.assertFalse(instruction.exists())

    def test_app_counters_do_not_invalidate_transport_but_owned_config_does(self):
        path, _, _ = self.manager.location('claude-code'); path.write_text('{"launchCount":1}')
        plan = self.manager.plan('claude-code'); self.manager.apply(plan, plan['plan_hash'])
        data = json.loads(path.read_text()); data['launchCount'] = 2; path.write_text(json.dumps(data))
        self.assertFalse(self.manager.inspect('claude-code')['reverification_required'])
        data['mcpServers']['local_memory_hub']['args'].append('--changed'); path.write_text(json.dumps(data))
        self.assertTrue(self.manager.inspect('claude-code')['reverification_required'])
