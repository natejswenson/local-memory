import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastmcp import FastMCP, Client
from memory_hub.activity import ActivityStore, canonical
from memory_hub.activity_sources import sync_sources
from memory_hub.recall import recall_context
from scripts.activity_hook import hook_event
from scripts.guarded_mcp import register_activity, OwnershipGuard
from scripts.vault_backup import backup, restore


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / 'vault'; self.vault.mkdir()
        self.control = self.root / 'general'
        self.store = ActivityStore(self.vault, self.control)
        self.event = dict(event_id=str(uuid.uuid4()), skill='ghostwriter', subject='publishing',
            action='publish', state='published', summary='Synthetic deployment post',
            source='Synthetic publisher receipt', source_id='post-1', occurred_at='2026-09-19',
            artifacts=['https://www.linkedin.com/feed/update/urn:li:share:123'], evidence_kind='source-log')

    def test_idempotent_concurrent_publish_and_changed_retry_refused(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.store.record(self.event), range(3)))
        self.assertEqual([r['status'] for r in results].count('recorded'), 1)
        self.assertTrue(all(r['verified'] for r in results))
        self.assertFalse(self.store.record({**self.event, 'summary': 'Changed'})['verified'])
        self.assertEqual(len(list(self.vault.rglob('*.md'))), 1)
        self.assertEqual(self.store.recall(state='published')['matching_events'], 1)
        self.assertEqual(recall_context(self.vault, subject='global', query='deployment')['records'], [])

    def test_deleted_or_edited_events_never_reimported(self):
        r = self.store.record(self.event); path = self.vault / r['path']
        path.write_text(path.read_text() + 'edited')
        self.assertFalse(self.store.record(self.event)['verified'])
        self.assertEqual(self.store.recall()['status'], 'unavailable')
        path.unlink()
        self.assertFalse(self.store.record(self.event)['verified'])
        self.assertFalse(path.exists())

    def test_invalid_scope_status_timestamp_artifact_and_secrets(self):
        for edit in ({'skill': '../escape'}, {'state': 'success-ish'}, {'occurred_at': '2026-09-19T10:00:00'},
                     {'occurred_at': '2026-W38-6T12:00:00+00:00'},
                     {'artifacts': ['https://example.com/?token=secret']}, {'details': 'api_key=verysecretvalue'},
                     {'event_id': 'unknown'}, {'artifacts': ['vault:../outside']}):
            self.assertFalse(self.store.record({**self.event, **edit})['verified'], edit)
        self.assertEqual(list(self.vault.rglob('*.md')), [])

    def test_pending_receipt_recovers_after_publication_but_not_before(self):
        from memory_hub.capture import exclusive_create
        def interrupted(path, raw):
            exclusive_create(path, raw)
            raise OSError('Interrupted acknowledgement')
        with patch('memory_hub.activity.exclusive_create', side_effect=interrupted):
            self.assertFalse(self.store.record(self.event)['verified'])
        self.assertEqual(self.store.record(self.event)['status'], 'already_recorded')
        another = {**self.event, 'event_id': str(uuid.uuid4())}
        with patch('memory_hub.activity.exclusive_create', side_effect=OSError('Before publication')):
            self.assertFalse(self.store.record(another)['verified'])
        self.assertFalse(self.store.record(another)['verified'])

    def test_filter_dates_states_pagination_and_budgets(self):
        for i, state in enumerate(('drafted', 'scheduled', 'published', 'failed')):
            self.assertTrue(self.store.record({**self.event, 'event_id': str(uuid.uuid4()),
                'state': state, 'occurred_at': f'2026-09-{15+i}', 'details': 'Evidence ' * 100})['verified'])
        self.assertEqual(self.store.recall(state='published')['matching_events'], 1)
        self.assertEqual(self.store.recall(since='2026-09-16', until='2026-09-17')['matching_events'], 2)
        self.assertEqual(self.store.recall(skill='issueflow')['matching_events'], 0)
        result = self.store.recall(limit=1)
        self.assertEqual(result['next_offset'], 1)
        self.assertNotEqual(result['records'][0]['event_id'], self.store.recall(limit=1, offset=1)['records'][0]['event_id'])
        small = self.store.recall(max_context_bytes=512)
        self.assertLessEqual(len(canonical(small)), 512)
        self.assertEqual(small['status'], 'partial')
        self.assertEqual(self.store.recall(query='deployment')['matching_events'], 4)

    def test_import_confirmed_post_log_retries_and_preserves_original(self):
        source = self.root / 'published.jsonl'
        rows = [{'url': 'https://www.linkedin.com/posts/synthetic-123', 'date': '2026-09-19',
                 'first_line': 'Synthetic published evidence', 'api_token': 'NEVER_COPY_SECRET'},
                {'date': '2026-09-19', 'first_line': 'Unconfirmed draft'}]
        raw = '\n'.join(json.dumps(r) for r in rows).encode(); source.write_bytes(raw)
        specs = [{'skill': 'ghostwriter', 'path': str(source)}]
        self.assertEqual(sync_sources(self.vault, self.control, specs)['sources'][0]['eligible'], 1)
        self.assertEqual(list(self.vault.rglob('*.md')), [])
        one = sync_sources(self.vault, self.control, specs, True)
        self.assertEqual(one['sources'][0]['created'], 1)
        self.assertEqual(one['status'], 'partial')
        self.assertEqual(sync_sources(self.vault, self.control, specs, True)['sources'][0]['unchanged'], 1)
        self.assertEqual(source.read_bytes(), raw)
        self.assertNotIn('NEVER_COPY_SECRET', '\n'.join(p.read_text() for p in self.vault.rglob('*.md')))

    def test_hook_ignores_memory_calls_drops_inputs_outputs_and_keeps_unknown(self):
        payload = dict(hook_event_name='PostToolUse', session_id='session', tool_use_id='call',
            tool_name='Bash', cwd='/work/project', tool_input={'command': 'SECRET INPUT'},
            tool_response={'output': 'SECRET OUTPUT'})
        event = hook_event(payload, self.store)
        self.assertNotIn('SECRET', json.dumps(event)); self.assertEqual(event['state'], 'observed')
        self.assertTrue(self.store.record(event)['verified'])
        self.assertEqual(self.store.record(hook_event(payload, self.store))['status'], 'already_recorded')
        self.assertIsNone(hook_event({**payload, 'tool_name': 'mcp__local_memory_hub__record_activity'}, self.store))
        failure = hook_event({**payload, 'tool_use_id': 'fail', 'tool_response': {'exit_code': 1}}, self.store)
        self.assertEqual(failure['state'], 'failed')

    def test_backup_carries_receipts_and_mcp_surface_roundtrip(self):
        async def run():
            server = FastMCP('synthetic-activity')
            register_activity(server, lambda: self.store); server.add_middleware(OwnershipGuard())
            async with Client(server) as client:
                self.assertEqual({t.name for t in await client.list_tools()}, {'record_activity', 'recall_activity'})
                self.assertTrue((await client.call_tool('record_activity', {'request': self.event})).data['verified'])
                self.assertEqual((await client.call_tool('recall_activity', {'state': 'published'})).data['matching_events'], 1)
        asyncio.run(run())
        archive = backup(self.vault, self.root / 'backups', general_control=self.control)['archive']
        restore(archive, self.root / 'restored')
        restored = ActivityStore(self.root / 'restored/vault', self.root / 'restored/general-control')
        self.assertEqual(restored.record(self.event)['status'], 'already_recorded')
        self.assertEqual(restored.recall()['matching_events'], 1)

    def test_redirected_activity_paths_refused(self):
        outside = self.root / 'outside'; outside.mkdir()
        (self.vault / 'Activity').symlink_to(outside)
        self.assertFalse(self.store.record(self.event)['verified'])
        self.assertEqual(self.store.recall()['status'], 'unavailable')
        self.assertEqual(list(outside.iterdir()), [])
