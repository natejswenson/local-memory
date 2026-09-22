import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from fastmcp import Client
from memory_hub.mcp_server import create_server
from memory_hub.paths import HubPaths


class CoreTests(unittest.TestCase):
    def test_typed_contract_roundtrip_and_profile_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = HubPaths(Path(tmp).resolve(), True); paths.vault.mkdir(parents=True)
            async def run():
                async with Client(create_server(paths)) as client:
                    names = {t.name for t in await client.list_tools()}
                    self.assertEqual(len(names), 5); self.assertNotIn('read_note', names)
                    event = dict(event_id=str(uuid.uuid4()), skill='synthetic', subject='global', action='test',
                        state='completed', summary='Synthetic result', source='Synthetic test', source_id='test', occurred_at='2026-09-21')
                    result = (await client.call_tool('record_activity', {'request': event})).data
                    self.assertTrue(result['verified'])
                    self.assertEqual((await client.call_tool('recall_activity', {'stream': 'outcomes'})).data['matching_events'], 1)
                    with self.assertRaises(Exception): await client.call_tool('record_activity', {'request': event | {'unknown': True}})
                async with Client(create_server(paths, 'core+skills')) as client:
                    self.assertIn('skill_memory', {t.name for t in await client.list_tools()})
            asyncio.run(run())

    def test_core_construction_does_not_import_native_engine_or_model(self):
        script = "from memory_hub.mcp_server import create_server; from memory_hub.paths import HubPaths; from pathlib import Path; import sys; create_server(HubPaths(Path.cwd(), True)); assert 'basic_memory.mcp.server' not in sys.modules; assert 'sentence_transformers' not in sys.modules"
        subprocess.run([sys.executable, '-c', script], check=True, capture_output=True)

    def test_synthetic_profile_is_never_live_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); paths = HubPaths(root, True); paths.vault.mkdir(parents=True)
            self.assertEqual(paths.readiness()['activation'], 'synthetic')
            self.assertFalse(HubPaths(root).readiness()['ready'])
