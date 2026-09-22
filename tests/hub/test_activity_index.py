import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from memory_hub.activity import ActivityStore
from memory_hub.activity_index import ActivityIndex
from memory_hub.skill_store import atomic
from memory_hub.serialization import canonical


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.vault = self.root / 'vault'; self.vault.mkdir()
        self.control = self.root / '.runtime/general-memory'
        atomic(self.control / 'features.json', canonical({'schema_version': 1, 'activity_index': True}))
        self.store = ActivityStore(self.vault, self.control); self.index = ActivityIndex(self.store)

    def event(self, **edits):
        return dict(event_id=str(uuid.uuid4()), skill='synthetic', subject='global', action='test',
                    state='completed', summary='Synthetic memory result', source='Test fixture', source_id='fixture',
                    occurred_at='2026-09-21T12:00:00+00:00', **edits)

    def test_query_stream_source_verification_and_incremental_visibility(self):
        a = self.store.record(self.event()); self.assertTrue(a['verified'])
        self.assertEqual(self.store.recall(query='memory')['matching_events'], 1)
        b = self.event(); b['action'] = 'tool-call'; self.store.record(b)
        self.assertEqual(self.store.recall(stream='outcomes')['matching_events'], 1)
        self.assertEqual(self.store.recall(stream='telemetry')['matching_events'], 1)
        with patch.object(self.store, 'paths', side_effect=AssertionError('Warm recall must not scan')):
            self.assertEqual(len(self.store.recall()['records']), 2)
        path = self.vault / a['path']; path.write_text(path.read_text() + '\nchanged')
        result = self.store.recall(stream='outcomes')
        self.assertEqual(result['records'], []); self.assertEqual(result['status'], 'partial')
        self.assertFalse(self.store.record(b | {'summary': 'changed'})['verified'])

    def test_cursor_snapshots_survive_appends_and_bind_to_filters(self):
        for _ in range(4): self.store.record(self.event())
        for query in ('', 'memory'):
            first = self.store.recall(query=query, limit=1)
            self.assertTrue(first['next_cursor'])
            event = self.event(); event['occurred_at'] = '2026-09-22'; self.store.record(event)
            next_page = self.store.recall(query=query, limit=10, cursor=first['next_cursor'])
            self.assertEqual(next_page['matching_events'], first['matching_events'])
            ids = {r['event_id'] for r in first['records'] + next_page['records']}
            self.assertEqual(len(ids), first['matching_events'])
            self.assertNotIn(event['event_id'], ids)
            self.assertEqual(self.store.recall(query='different', cursor=first['next_cursor'])['status'], 'unavailable')

    def test_log_ack_failure_recovers_and_budget_is_bounded(self):
        event = self.event()
        with patch('memory_hub.change_log.ChangeLog.committed', side_effect=OSError('crash')):
            self.assertTrue(self.store.record(event)['verified'])
        self.assertEqual(self.store.recall()['matching_events'], 1)
        self.assertEqual(self.store.record(event)['status'], 'already_recorded')
        small = self.store.recall(max_context_bytes=512)
        self.assertLessEqual(len(canonical(small)), 512); self.assertIsNone(small['next_cursor'])

    def test_rebuild_removes_deleted_source_and_cache_is_disposable(self):
        a = self.store.record(self.event()); self.store.recall()
        (self.vault / a['path']).unlink()
        self.index.rebuild()
        self.assertEqual(self.store.recall()['records'], [])
        self.assertFalse(self.store.record(self.event() | {'event_id': a['event_id']})['verified'])

    def test_above_legacy_capacity_with_streaming_rebuild(self):
        # Build synthetic source/receipt files without 10,001 unrelated fsyncs.
        import yaml
        folder = self.vault / 'Activity/2026-09'; folder.mkdir(parents=True)
        receipts = self.control / 'activity/receipts'; receipts.mkdir(parents=True)
        for i in range(10001):
            event = self.event(); event.update(contract='activity-v1', type='activity',
                recorded_at='2026-09-21T12:00:00+00:00', evidence_kind='agent-report', artifacts=[])
            if i: event['action'] = 'tool-call'
            raw = ('---\n' + yaml.safe_dump(event) + '---\n\nSynthetic result\n').encode()
            relative = 'Activity/2026-09/' + event['event_id'] + '.md'
            (self.vault / relative).write_bytes(raw)
            (receipts / (event['event_id'] + '.json')).write_text(json.dumps(dict(phase='committed', path=relative, content_sha256=hashlib.sha256(raw).hexdigest())))
        self.assertEqual(self.index.maintain(full=True)['indexed_events'], 10001)
        self.assertEqual(self.store.recall(stream='outcomes')['matching_events'], 1)
        self.assertEqual(self.store.recall(stream='telemetry')['matching_events'], 10000)

    def test_corrupt_cache_rebuild_and_malformed_source_are_contained(self):
        good = self.store.record(self.event()); self.store.recall()
        self.index.path.write_bytes(b'not a sqlite database')
        self.assertEqual(self.store.recall()['status'], 'unavailable')
        self.index.rebuild()
        self.assertEqual(len(self.store.recall()['records']), 1)
        (self.vault / good['path']).write_text('---\ninvalid: [\n---\n')
        result = self.store.recall()
        self.assertEqual(result['status'], 'partial'); self.assertEqual(result['records'], [])
