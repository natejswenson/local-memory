#!/usr/bin/env python3
"""PostToolUse journal: bounded metadata only, never raw arguments, outputs or transcripts."""
import json
from pathlib import Path
import re
import sys
import uuid
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.activity import ActivityStore, canonical, stamp
from memory_hub.skill_store import read, atomic, safe


def hook_event(payload, store):
    if not isinstance(payload, dict) or payload.get('hook_event_name') != 'PostToolUse':
        return None
    name = payload.get('tool_name')
    session, call = payload.get('session_id'), payload.get('tool_use_id')
    if not all(isinstance(v, str) and 0 < len(v) <= 256 for v in (name, session, call)):
        raise ValueError('Missing stable hook identity')
    if 'local_memory_hub' in name or name in {'record_activity', 'recall_activity'}:
        return None
    # This is deliberately a tool-call receipt, not a business-success inference.
    response = payload.get('tool_response')
    state = 'observed'
    if isinstance(response, dict):
        if response.get('isError') is True or response.get('is_error') is True:
            state = 'failed'
        elif type(response.get('exit_code')) is int:
            state = 'completed' if response['exit_code'] == 0 else 'failed'
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'local-memory:tool:' + session + ':' + call))
    when = stamp()
    receipt = store.control / 'activity/receipts' / (event_id + '.json')
    if receipt.exists():
        meta = json.loads(read(receipt))
        path = meta['path']
        if not re.fullmatch(r'Activity/\d{4}-\d{2}/' + re.escape(event_id) + r'\.md', path):
            raise ValueError('Invalid receipt')
        note = store.vault / path
        if note.exists():
            when = yaml.safe_load(read(note, 32768).decode()[4:].split('\n---\n', 1)[0])['occurred_at']
    # Do not copy source paths or shell commands; they may contain private arguments.
    subject = re.sub('[^a-z0-9._-]', '-', Path(str(payload.get('cwd', 'unknown'))).name.lower())[:80].strip('-') or 'unknown'
    return dict(event_id=event_id, skill='agent-tools', subject=subject, action='tool-call',
        state=state, summary='Tool invocation: ' + name, details='Tool result observed. This receipt does not establish that a post, deployment or other external action succeeded. Inputs and output bodies were not retained.',
        source='Host PostToolUse event', source_id=session + ':' + call, occurred_at=when,
        evidence_kind='tool-result', artifacts=[])


def main():
    if not (ROOT / '.runtime/live/activation.json').is_file():
        return 0
    store = ActivityStore(ROOT / 'vault', ROOT / '.runtime/general-memory')
    status = {'checked_at': stamp(), 'status': 'skipped'}
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Oversized hook payload')
        config = json.loads(read(ROOT / '.runtime/activity-config.json'))
        if config.get('enabled') is not True:
            return 0
        event = hook_event(json.loads(raw), store)
        if event:
            result = store.record(event)
            status.update(status=result['status'], verified=result.get('verified', False))
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        status['status'] = 'unavailable'
    atomic(store.control / 'activity/hook-status.json', canonical(status))
    # Never block, replace tool output, grant permission, or reinvoke the agent.
    if status['status'] == 'unavailable':
        print(json.dumps({'systemMessage': 'Local Obsidian activity recording failed; the tool outcome was not changed. Inspect activity hook health.'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
