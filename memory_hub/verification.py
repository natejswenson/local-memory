"""Reproducible transport acceptance; never represented as host or model evidence."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from .capture import CaptureStore
from .paths import HubPaths
from .serialization import canonical
from .skill_store import atomic


async def synthetic_roundtrip(root, client='transport'):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    run_id = str(uuid.uuid4())
    installation = root / '.runtime/client-tests' / run_id
    paths = HubPaths(installation, True); paths.vault.mkdir(mode=0o700, parents=True)
    nonce = 'syntheticnonce' + uuid.uuid4().hex
    store = CaptureStore(paths.vault, paths.control)
    request = dict(capture_id=str(uuid.uuid4()), title='Synthetic cross-client seed', subject='global',
                   body=nonce, source='Synthetic transport acceptance', status='active',
                   kind='preference', key='preferences.memory-hub.openai-auth')
    seeded = store.capture(request)
    report = dict(run_id=run_id, requested_client=client, evidence_kind='transport-harness', host_verified=False,
                  workflow_verified=False, checked_at=datetime.now(timezone.utc).isoformat(), checks={})
    def transport():
        return StdioTransport(command=sys.executable, args=['-m', 'memory_hub.mcp_server', '--root', str(installation), '--pilot'],
                              env={'PYTHONPATH': str(root), 'HF_HUB_OFFLINE': '1'})
    start = time.perf_counter()
    async with Client(transport(), timeout=15) as session:
        tools = await session.list_tools()
        report['startup_ms'] = round((time.perf_counter() - start) * 1000, 2)
        report['checks']['core_surface'] = {t.name for t in tools} == {'memory_status', 'recall_context', 'capture_memory', 'record_activity', 'recall_activity'}
        recalled = (await session.call_tool('recall_context', {'query': nonce, 'subject': 'global'})).data
        report['checks']['read_seed'] = any(nonce in row['content'] for row in recalled['records'])
        capture = dict(capture_id=str(uuid.uuid4()), title='Synthetic return', body=nonce + ' return',
                       source='Synthetic MCP tool return', subject='global', status='active')
        saved = (await session.call_tool('capture_memory', capture)).data
        report['checks']['verified_capture'] = saved.get('verified') is True
        report['checks']['same_request_retry'] = (await session.call_tool('capture_memory', capture)).data.get('status') == 'already_created'
        correction = request | dict(capture_id=str(uuid.uuid4()), body=nonce + ' corrected', supersedes=seeded['identity'])
        # A second independent MCP process publishes the explicit correction.
        async with Client(transport(), timeout=15) as second:
            report['checks']['second_client_correction'] = (await second.call_tool('capture_memory', correction)).data.get('verified') is True
        current = (await session.call_tool('recall_context', {'keys': [request['key']]})).data
        report['checks']['correction_visible'] = len(current['records']) == 1 and current['records'][0]['content'].endswith('corrected')
    try:
        await session.call_tool('memory_status', {})
        report['checks']['disconnected_unavailable'] = False
    except Exception:
        report['checks']['disconnected_unavailable'] = True
    async with Client(transport(), timeout=15) as restarted:
        report['checks']['retry_after_restart'] = (await restarted.call_tool('capture_memory', capture)).data.get('status') == 'already_created'
    report['status'] = 'ok' if all(report['checks'].values()) else 'partial'
    atomic(installation / 'evidence.json', canonical(report))
    return report
