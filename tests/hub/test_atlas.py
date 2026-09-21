"""Synthetic project scopes and a readable graph without rewriting source records."""
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
import uuid
from zoneinfo import ZoneInfo

from memory_hub.activity import ActivityStore
from memory_hub.atlas import refresh, local_day
from memory_hub.capture import CaptureStore
from memory_hub.projects import registry_path, resolve_subject
from memory_hub.recall import recall_context
from memory_hub.restore_audit import receipt_snapshot
from scripts.vault_backup import backup, restore


class AtlasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / 'vault'; self.vault.mkdir()
        self.control = self.root / '.runtime/general-memory'; self.control.mkdir(parents=True)
        self.config = {'version': 1, 'timezone': 'America/Chicago', 'projects': [
            {'subject': 'local-memory', 'title': 'Shared Memory', 'paths': ['/synthetic/memory'], 'topics': ['memory']},
            {'subject': 'synthetic-app', 'title': 'Synthetic App', 'paths': ['/synthetic/app', '/synthetic/app-worktree'], 'topics': ['developer-tools']}]}
        registry_path(self.vault).write_text(json.dumps(self.config))
        self.store = ActivityStore(self.vault, self.control)
        self.capture = CaptureStore(self.vault, self.control)

    def event(self, **overrides):
        return dict(event_id=str(uuid.uuid4()), skill='synthetic', subject='synthetic-app',
                    action='create-report', state='drafted', summary='Created the synthetic report draft.',
                    source='Synthetic fixture', source_id=str(uuid.uuid4()), occurred_at='2026-09-20T03:00:00+00:00', **overrides)

    def capture_note(self, subject='synthetic-app', **overrides):
        request = dict(title='Use the verified fixture', body='Synthetic reusable evidence.', subject=subject,
                       source='Synthetic test', kind='decision', status='active', capture_id=str(uuid.uuid4()))
        request.update(overrides)
        result = self.capture.capture(request)
        self.assertTrue(result['verified'], result)
        return result

    def test_scoped_capture_recall_worktree_and_unregistered_rejection(self):
        self.capture_note(); self.capture_note('global', title='Global synthetic preference')
        self.capture_note('local-memory', title='Other synthetic project')
        r = recall_context(self.vault, subject='synthetic-app', query='synthetic', max_notes=5)
        self.assertEqual({v['project'] for v in r['records']}, {'global', 'synthetic-app'})
        self.assertEqual(resolve_subject(self.vault, '/synthetic/app-worktree/src'), 'synthetic-app')
        self.assertEqual(resolve_subject(self.vault, '/elsewhere/app'), 'global')
        self.assertEqual(recall_context(self.vault, subject='unknown', query='synthetic')['status'], 'rejected')
        self.assertEqual(recall_context(self.vault, subject='local-fitness', query='synthetic')['status'], 'rejected')

    def test_graph_connected_readable_daily_and_source_hashes_unchanged(self):
        self.capture_note()
        self.assertTrue(self.store.record(self.event())['verified'])
        tool = self.event(); tool.update(skill='agent-tools', action='tool-call', summary='Tool invocation: synthetic', state='observed')
        self.assertTrue(self.store.record(tool)['verified'])
        sources = {p: hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('Projects', 'Activity') for p in (self.vault / folder).rglob('*.md')}
        result = refresh(self.vault, self.control, True)
        self.assertEqual(result['daily_summaries'], 1)
        self.assertEqual(result['technical_records'], 1)
        day = self.vault / 'Atlas/Journal/2026-09-19 - Daily summary.md'
        self.assertTrue(day.exists())
        self.assertIn('**Drafted**', day.read_text()); self.assertNotIn('Tool invocation: synthetic', day.read_text())
        self.assertEqual(sources, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
        files = {p.relative_to(self.vault).as_posix()[:-3]: p for p in (self.vault / 'Atlas').rglob('*.md')}
        graph = defaultdict(set)
        for source, p in files.items():
            for target in re.findall(r'\[\[([^\]|#]+)', p.read_text()):
                if target in files: graph[source].add(target); graph[target].add(source)
        seen, stack = set(), ['Atlas/Home']
        while stack:
            p = stack.pop()
            if p not in seen: seen.add(p); stack.extend(graph[p] - seen)
        self.assertEqual(seen, set(files))
        self.assertEqual(refresh(self.vault, self.control, True)['changed'], [])
        self.assertEqual(len(recall_context(self.vault, subject='synthetic-app', query='synthetic')['records']), 1)

    def test_personal_edits_preserved_and_unmanaged_destination_refused(self):
        refresh(self.vault, self.control, True)
        home = self.vault / 'Atlas/Home.md'
        home.write_text(home.read_text() + '\nMy personal addition.\n')
        refresh(self.vault, self.control, True)
        self.assertIn('My personal addition.', home.read_text())
        home.write_text('My own unmanaged home')
        before = {p: p.read_bytes() for p in (self.vault / 'Atlas').rglob('*') if p.is_file()}
        with self.assertRaises(ValueError): refresh(self.vault, self.control, True)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_edited_source_stops_refresh_and_stale_knowledge_is_retired(self):
        capture = self.capture_note()
        refresh(self.vault, self.control, True)
        source = self.vault / capture['path']
        source.write_text(source.read_text().replace('status: active', 'status: archived'))
        refresh(self.vault, self.control, True)
        human = self.vault / 'Atlas/Knowledge/Use the verified fixture.md'
        self.assertIn('no longer current', human.read_text())
        self.assertNotIn('![[Projects/', human.read_text())
        event = self.store.record(self.event()); p = self.vault / event['path']
        p.write_text(p.read_text() + '\nManual change')
        with self.assertRaises(ValueError): refresh(self.vault, self.control, True)

    def test_registry_and_receipts_survive_backup_without_activation(self):
        self.capture_note()
        snapshots = receipt_snapshot(self.control, self.vault)
        archive = backup(self.vault, self.root / 'backups', general_control=self.control)['archive']
        destination = self.root / 'restored'; restore(archive, destination)
        recovered = receipt_snapshot(destination / 'general-control', destination / 'vault')
        self.assertEqual(snapshots, recovered)
        self.assertTrue((destination / 'general-control/project-registry.json').exists())

    def test_registry_failure_is_unavailable_and_date_only_is_unchanged(self):
        registry_path(self.vault).write_text('{broken')
        self.assertEqual(recall_context(self.vault, subject='global', query='synthetic')['status'], 'unavailable')
        self.assertEqual(local_day('2026-09-20', ZoneInfo('America/Chicago')), '2026-09-20')


if __name__ == '__main__': unittest.main()
