"""One restartable maintenance worker; source writers never render Atlas pages."""
from datetime import datetime, timezone
import json
import time
from .capture import locked
from .change_log import ChangeLog
from .serialization import canonical
from .skill_store import atomic, read, safe
from .writer_gate import features


def enqueue(vault, control):
    # Sequence records are the durable queue. No second per-capture file or
    # background process is needed to acknowledge verified source publication.
    return {'applied': False, 'reason': 'queued', 'high_water': ChangeLog(control).high_water()}


def run_once(paths, full=False):
    paths.require_ready()
    folder = safe(paths.runtime / 'maintenance')
    with locked(folder, timeout=.05):
        start = time.monotonic()
        flags = features(paths.control)
        high = ChangeLog(paths.control).high_water()
        previous_path = folder / 'status.json'
        previous = json.loads(read(previous_path)) if previous_path.exists() else {}
        result = {'status': 'ok', 'high_water': high, 'completed_at': None,
                  'views_checkpoint': previous.get('views_checkpoint', 0), 'issues': []}
        try:
            if flags.get('activity_index'):
                from .activity import ActivityStore
                from .activity_index import ActivityIndex
                result['activity_index'] = ActivityIndex(ActivityStore(paths.vault, paths.control)).maintain(full)
                if result['activity_index']['status'] != 'ok': result['issues'].append('ACTIVITY_INDEX_PARTIAL')
            if full or high != result['views_checkpoint'] or not previous:
                from .atlas import refresh
                from .projects import registry_path
                if registry_path(paths.vault).exists():
                    result['views'] = refresh(paths.vault, paths.control, True)
                result['views_checkpoint'] = high
        except (OSError, ValueError, TypeError, KeyError):
            result['issues'].append('MAINTENANCE_REQUIRES_REVIEW')
        result.update(status='warning' if result['issues'] else 'ok',
                      duration_seconds=round(time.monotonic() - start, 3),
                      completed_at=datetime.now(timezone.utc).isoformat())
        atomic(previous_path, canonical(result))
        if full or result['issues']:
            # Keep bounded operational evidence for the observation period,
            # without recording note bodies, queries, or raw tool transcripts.
            history_path = folder / 'observations.json'
            history = json.loads(read(history_path, 4 * 1024 * 1024)) if history_path.exists() else []
            from .operations import backup_status
            backup = backup_status(paths)
            sample = {k: result[k] for k in ('completed_at', 'status', 'high_water', 'views_checkpoint', 'duration_seconds', 'issues')}
            sample['backup_code'] = backup['code']
            sample['index_checkpoint'] = result.get('activity_index', {}).get('checkpoint')
            history.append(sample)
            atomic(history_path, canonical(history[-9000:]))
        return result


def run(paths, interval=5):
    if not 1 <= interval <= 60: raise ValueError('INVALID_WORKER_INTERVAL')
    last_full = 0
    while True:
        full = time.monotonic() - last_full >= 300
        try:
            run_once(paths, full=full)
        except ValueError:
            pass  # A competing worker owns the lease; next interval can retry.
        if full: last_full = time.monotonic()
        time.sleep(interval)
