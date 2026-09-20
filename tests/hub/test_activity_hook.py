"""Native image-sized hook payloads; never exercise the personal vault."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import activity_hook as hook


class ActivityHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'vault').mkdir()
        (self.root / '.runtime/live').mkdir(parents=True)
        (self.root / '.runtime/live/activation.json').write_text('{}')
        (self.root / '.runtime/activity-config.json').write_text('{"enabled":true}')
        self.payload = dict(hook_event_name='PostToolUse', tool_name='image_gen__imagegen',
                            session_id='synthetic-session', tool_use_id='synthetic-call',
                            cwd='/work/synthetic', tool_response={'isError': False})

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, payload=None, raw=None):
        data = raw if raw is not None else json.dumps(payload or self.payload).encode()
        stdout = io.StringIO()
        with patch.object(hook, 'ROOT', self.root), patch.object(hook.sys, 'stdin', io.TextIOWrapper(io.BytesIO(data))), contextlib.redirect_stdout(stdout):
            self.assertEqual(hook.main(), 0)
        return stdout.getvalue()

    def health(self, name='hook-status.json'):
        return json.loads((self.root / '.runtime/general-memory/activity' / name).read_text())

    def test_image_sized_output_records_metadata_only_and_retry_is_idempotent(self):
        self.payload['tool_input'] = {'prompt': 'SENSITIVE PROMPT MUST NOT BE SAVED'}
        self.payload['tool_response']['image_url'] = 'data:image/png;base64,' + 'A' * (3 * 1024 * 1024)
        self.assertEqual(self.invoke(), '')
        self.assertEqual(self.health()['status'], 'recorded')
        self.assertTrue(self.health()['verified'])
        notes = list((self.root / 'vault').rglob('*.md'))
        self.assertEqual(len(notes), 1)
        body = notes[0].read_text()
        self.assertLess(len(body), 4096)
        self.assertIn('image_gen__imagegen', body)
        self.assertNotIn('data:image', body)
        self.assertNotIn('SENSITIVE PROMPT', body)
        self.assertEqual(self.invoke(), '')
        self.assertEqual(self.health()['status'], 'already_recorded')
        self.assertEqual(len(list((self.root / 'vault').rglob('*.md'))), 1)

    def test_oversize_input_has_actionable_bounded_health_and_does_not_block_tool(self):
        with patch.object(hook, 'MAX_PAYLOAD_BYTES', 128):
            output = self.invoke(raw=b'A' * 129)
        self.assertIn('tool outcome was not changed', output)
        self.assertEqual(self.health()['error_code'], 'HOOK_PAYLOAD_TOO_LARGE')
        self.assertEqual(self.health()['stage'], 'input')
        self.assertEqual(self.health()['input_limit_bytes'], 128)
        failure = self.health('hook-last-failure.json')
        self.assertEqual(list((self.root / 'vault').rglob('*.md')), [])
        self.assertEqual(self.invoke(), '')
        self.assertEqual(self.health()['status'], 'recorded')
        self.assertEqual(self.health('hook-last-failure.json'), failure)

    def test_invalid_json_or_identity_never_echoes_raw_input(self):
        output = self.invoke(raw=b'{SENSITIVE RAW BODY')
        self.assertNotIn('SENSITIVE', output)
        self.assertEqual(self.health()['stage'], 'input')
        self.payload.pop('tool_use_id')
        output = self.invoke()
        self.assertNotIn('synthetic', output)
        self.assertEqual(self.health()['stage'], 'identity')
        self.assertEqual(list((self.root / 'vault').rglob('*.md')), [])

    def test_memory_tools_skip_even_with_large_response(self):
        self.payload['tool_name'] = 'mcp__local_memory_hub__record_activity'
        self.payload['tool_response'] = {'body': 'A' * (2 * 1024 * 1024)}
        self.assertEqual(self.invoke(), '')
        self.assertEqual(self.health()['status'], 'skipped')
        self.assertEqual(list((self.root / 'vault').rglob('*.md')), [])

    def test_write_rejection_is_reported_without_private_reason(self):
        with patch.object(hook.ActivityStore, 'record', return_value={'status': 'unavailable', 'verified': False, 'error': 'SENSITIVE'}):
            output = self.invoke()
        self.assertIn('activity recording failed', output)
        self.assertNotIn('SENSITIVE', output)
        self.assertEqual(self.health()['error_code'], 'ACTIVITY_WRITE_UNAVAILABLE')
        self.assertEqual(self.health()['stage'], 'record')

    def test_health_write_failure_still_preserves_tool_outcome(self):
        with patch.object(hook, 'atomic', side_effect=OSError('SENSITIVE PATH')):
            output = self.invoke(raw=b'bad json')
        self.assertIn('tool outcome was not changed', output)
        self.assertNotIn('SENSITIVE', output)

    def test_disabled_hook_does_not_read_large_payload_or_write_notes(self):
        (self.root / '.runtime/activity-config.json').write_text('{"enabled":false}')
        self.assertEqual(self.invoke(raw=b'not JSON'), '')
        self.assertFalse((self.root / '.runtime/general-memory/activity/hook-status.json').exists())
