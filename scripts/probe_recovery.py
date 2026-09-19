#!/usr/bin/env python3
"""Restore a synthetic snapshot, rebuild its index, and verify MCP retrieval."""
import argparse
import asyncio
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from vault_backup import restore

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / '.venv/bin/basic-memory'
loader = importlib.machinery.SourceFileLoader('hub_recovery', str(ROOT / 'bin/memory-hub'))
spec = importlib.util.spec_from_loader(loader.name, loader)
hub = importlib.util.module_from_spec(spec)
loader.exec_module(hub)


async def probe(archive, identifier, marker):
    started = time.monotonic()
    # Only this explicitly synthetic temporary restore is removed on exit.
    with tempfile.TemporaryDirectory(prefix='recovery-probe-', dir=ROOT / '.runtime') as directory:
        work = Path(directory)
        restored = restore(archive, work / 'vault')
        hub.ROOT = work
        hub.initialize(False)
        env = hub.environment(False)
        with (ROOT / '.runtime/recovery-probe.stderr.log').open('a') as log:
            subprocess.run([str(ENGINE), 'reindex', '--search', '--project', 'local-memory'],
                           env=env, stdout=log, stderr=log, check=True, timeout=60)
            params = StdioServerParameters(command=str(ENGINE),
                                           args=['mcp', '--project', 'local-memory'], env=env)
            async with stdio_client(params, errlog=log) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    read = await session.call_tool('read_note', {
                        'project': 'local-memory', 'identifier': identifier,
                        'include_frontmatter': True, 'output_format': 'json'})
                    search = await session.call_tool('search_notes', {
                        'project': 'local-memory', 'query': marker,
                        'search_type': 'text', 'output_format': 'json'})
                    read_value = read.model_dump(mode='json')
                    search_value = search.model_dump(mode='json')
                    read_ok = not read.is_error and marker in json.dumps(read_value)
                    search_ok = not search.is_error and identifier in json.dumps(search_value)
        evidence = {
            'ok': read_ok and search_ok, 'archive': str(archive),
            'scope': 'synthetic quarantine; fresh index; no production activation',
            'files_restored': restored['files'], 'identifier': identifier,
            'first_read_has_marker': read_ok, 'rebuilt_search_has_identifier': search_ok,
            'elapsed_seconds': round(time.monotonic() - started, 2),
        }
        (ROOT / '.runtime/recovery-index-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence, indent=2))
        return evidence['ok']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic-archive', required=True, type=Path)
    parser.add_argument('--identifier', required=True)
    parser.add_argument('--marker', required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(probe(args.synthetic_archive, args.identifier, args.marker)) else 1)
