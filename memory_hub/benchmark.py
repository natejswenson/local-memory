"""Deterministic synthetic benchmarks; no personal vault reads or model downloads."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import statistics
import tempfile
import time
import uuid
from .activity import ActivityStore
from .activity_index import ActivityIndex
from .recall import recall_context
from .serialization import canonical
from .skill_store import atomic


def measure(call, samples=20):
    values = []
    for _ in range(samples):
        start = time.perf_counter(); result = call(); values.append((time.perf_counter() - start)*1000)
        if result.get('status') not in {'ok', 'partial'}: raise ValueError('BENCHMARK_OPERATION_FAILED')
    values.sort()
    return dict(p50_ms=round(statistics.median(values), 3), p95_ms=round(values[max(0, int(len(values)*.95)-1)], 3), p99_ms=round(values[-1], 3), samples=samples)


def seed_activity(vault, control, count):
    folder = vault / 'Activity/2026-09'; folder.mkdir(parents=True, exist_ok=True)
    receipts = control / 'activity/receipts'; receipts.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        event = str(uuid.UUID(int=i+1))
        meta = dict(contract='activity-v1', type='activity', event_id=event, skill='synthetic', subject='benchmark',
                    action='test' if i % 100 == 0 else 'tool-call', state='completed', summary='Synthetic benchmark outcome',
                    occurred_at='2026-09-21T12:00:00+00:00', recorded_at='2026-09-21T12:00:00+00:00',
                    source='Synthetic benchmark fixture', source_id=str(i), artifacts=[], evidence_kind='tool-result')
        raw = b'---\n' + canonical(meta) + b'\n---\n\nSynthetic benchmark outcome.\n'
        relative = 'Activity/2026-09/' + event + '.md'
        (vault / relative).write_bytes(raw)
        (receipts / (event + '.json')).write_bytes(canonical(dict(phase='committed', path=relative, content_sha256=hashlib.sha256(raw).hexdigest())))


def benchmark(suite='quick'):
    if suite not in {'quick', 'scale'}: raise ValueError('UNKNOWN_BENCHMARK_SUITE')
    report = dict(status='ok', synthetic=True, suite=suite, recorded_at=datetime.now(timezone.utc).isoformat(),
                  python=platform.python_version(), platform=platform.system(), cases={})
    with tempfile.TemporaryDirectory(prefix='memory-benchmark-') as temp:
        root = Path(temp).resolve(); vault = root / 'vault'; vault.mkdir()
        for size in (100, 1500):
            folder = vault / 'Preferences'; folder.mkdir(exist_ok=True)
            for i in range(size):
                meta = dict(title=f'Synthetic note {i}', type='note', project='global', status='active', source='Synthetic fixture',
                            capture_id=str(uuid.UUID(int=i+1)), permalink=f'benchmark/note-{i}')
                (folder / f'{i}.md').write_bytes(b'---\n' + canonical(meta) + b'\n---\n\nSynthetic latency marker.\n')
            report['cases'][f'general_{size}'] = measure(lambda: recall_context(vault, query='latency'))
        control = root / '.runtime/general-memory'
        atomic(control / 'features.json', canonical(dict(schema_version=1, activity_index=True)))
        store = ActivityStore(vault, control); index = ActivityIndex(store)
        for size in ([10000, 100000] if suite == 'scale' else [10000]):
            seed_activity(vault, control, size)
            start = time.perf_counter(); index.maintain(full=True)
            report['cases'][f'index_{size}'] = {'rebuild_seconds': round(time.perf_counter()-start, 3)}
            report['cases'][f'activity_{size}'] = measure(lambda: store.recall(stream='outcomes', skill='synthetic', limit=10))
            report['cases'][f'activity_text_{size}'] = measure(lambda: store.recall(stream='outcomes', query='benchmark', limit=10))
    report['peak_process_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == 'Darwin' else 1024)
    thresholds = {'general_100': 50, 'general_1500': 200, 'activity_10000': 100, 'activity_100000': 250,
                  'activity_text_10000': 500, 'activity_text_100000': 500}
    report['targets'] = {name: dict(target_p95_ms=target, passed=report['cases'][name]['p95_ms'] <= target)
                         for name, target in thresholds.items() if name in report['cases']}
    if not all(r['passed'] for r in report['targets'].values()): report['status'] = 'partial'
    return report
