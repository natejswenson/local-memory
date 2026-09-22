import json
from pathlib import Path
import tempfile
import unittest
import uuid
from memory_hub.capture import CaptureStore
from memory_hub.managed_catalog import ManagedCatalog
from memory_hub.recall import recall_context
from memory_hub.serialization import canonical
from memory_hub.skill_store import atomic


class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve(); self.vault = root / 'vault'; self.vault.mkdir()
        self.control = root / '.runtime/general-memory'; self.store = CaptureStore(self.vault, self.control)
        self.catalog = ManagedCatalog(self.vault, self.control)

    def capture(self, **changes):
        request = dict(capture_id=str(uuid.uuid4()), subject='global', title='Synthetic preference',
                       body='Use synthetic colors', source='Synthetic test', kind='preference', status='active',
                       key='preferences.memory-hub.openai-auth') | changes
        return self.store.capture(request)

    def adopt(self):
        plan = self.catalog.preview(); self.assertEqual(plan['status'], 'ready')
        self.catalog.adopt(plan['plan_hash'])
        atomic(self.control / 'features.json', canonical(dict(schema_version=1, managed_catalog=True)))

    def test_freeform_malformed_notes_do_not_disable_managed_recall(self):
        self.assertTrue(self.capture()['verified']); self.adopt()
        (self.vault / 'Personal scratch.md').write_text('---\ninvalid: [\n---\nfreeform')
        result = recall_context(self.vault, query='colors')
        self.assertEqual(result['status'], 'ok'); self.assertEqual(len(result['records']), 1)

    def test_missing_and_drifted_corrections_never_revive_ancestor(self):
        old = self.capture(); self.adopt()
        new = self.capture(body='Use synthetic blue', supersedes=old['identity'])
        self.assertTrue(new['verified'], new)
        path = self.vault / new['path']; raw = path.read_bytes()
        path.unlink()
        self.assertEqual(recall_context(self.vault, query='colors')['records'], [])
        path.write_bytes(raw.replace(b'status: active', b'status: archived'))
        self.assertEqual(recall_context(self.vault, query='colors')['records'], [])
        path.write_bytes(raw)
        self.assertIn('blue', recall_context(self.vault, query='synthetic')['records'][0]['content'])

    def test_lost_control_fails_closed_and_adoption_races_are_rejected(self):
        self.capture(); plan = self.catalog.preview(); self.capture(key=None)
        with self.assertRaises(ValueError): self.catalog.adopt(plan['plan_hash'])
        self.adopt(); self.catalog.path.unlink()
        self.assertEqual(recall_context(self.vault, query='colors')['status'], 'unavailable')

    def test_damaged_source_is_partial_even_without_matching_surviving_text(self):
        saved = self.capture(body='Unusual copper compass'); self.adopt()
        (self.vault / saved['path']).unlink()
        result = recall_context(self.vault, query='copper compass')
        self.assertEqual(result['status'], 'partial')
        self.assertIn('managed_source_requires_review', result['withheld'])
