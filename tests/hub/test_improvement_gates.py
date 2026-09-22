import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
from memory_hub.capture import CaptureStore
from memory_hub.paths import HubPaths
from memory_hub.rollout import plan, apply
from memory_hub.serialization import canonical
from memory_hub.skill_store import atomic
from memory_hub.worker import run_once


class GateTests(unittest.TestCase):
    def test_synthetic_rollout_and_dynamic_writer_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = HubPaths(Path(tmp).resolve(), True); paths.vault.mkdir(parents=True)
            preview = plan(paths); self.assertEqual(preview['status'], 'ready')
            apply(paths, preview['plan_hash'])
            store = CaptureStore(paths.vault, paths.control)
            request = dict(capture_id=str(uuid.uuid4()), title='Synthetic', body='Synthetic durable marker',
                           subject='global', source='Synthetic test', status='active')
            self.assertTrue(store.capture(request)['verified'])
            atomic(paths.control / 'writer-version.json', canonical(dict(schema_version=1, minimum_writer_version=999)))
            request['capture_id'] = str(uuid.uuid4())
            self.assertFalse(store.capture(request)['verified'])

    def test_live_activation_does_not_fake_writer_restart_or_restore_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = HubPaths(Path(tmp).resolve()); paths.vault.mkdir()
            atomic(paths.state / 'activation.json', canonical(dict(desktop_verified=True, vault=str(paths.vault))))
            preview = plan(paths); self.assertEqual(preview['status'], 'blocked')
            with self.assertRaises(ValueError): apply(paths, preview['plan_hash'])
            self.assertFalse((paths.control / 'features.json').exists())

    def test_deferred_activity_write_does_not_render_atlas(self):
        from memory_hub.activity import ActivityStore
        with tempfile.TemporaryDirectory() as tmp:
            paths = HubPaths(Path(tmp).resolve(), True); paths.vault.mkdir(parents=True)
            preview = plan(paths); apply(paths, preview['plan_hash'])
            event = dict(event_id=str(uuid.uuid4()), skill='synthetic', subject='global', action='test', state='completed',
                         summary='Synthetic outcome', source='Synthetic test', source_id='test', occurred_at='2026-09-21')
            with patch('memory_hub.atlas.plan', side_effect=AssertionError('No synchronous view rendering')):
                self.assertTrue(ActivityStore(paths.vault, paths.control).record(event)['verified'])
            result = run_once(paths)
            self.assertEqual(result['activity_index']['indexed_events'], 1)
