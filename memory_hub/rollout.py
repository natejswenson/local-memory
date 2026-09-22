"""Explicit feature activation after a writer-compatibility release and recovery gates."""
import hashlib
import json
from datetime import datetime, timezone
from .capture import locked
from .managed_catalog import ManagedCatalog
from .serialization import canonical
from .skill_store import atomic, read, safe
from .writer_gate import WRITER_VERSION, features


def plan(paths):
    paths.require_ready()
    current = features(paths.control)
    catalog = ManagedCatalog(paths.vault, paths.control)
    adoption = {'status': 'already_adopted', 'plan_hash': None} if safe(catalog.path).exists() else catalog.preview()
    if adoption['status'] == 'already_adopted': catalog.load()
    gates = {}
    for gate in ('writer-upgrade', 'backup-restore'):
        path = safe(paths.control / (gate + '-evidence.json'))
        if path.exists():
            value = json.loads(read(path, 65536))
            valid = value.get('verified') is True and value.get('vault') == str(paths.vault)
            try:
                checked = datetime.fromisoformat(value['checked_at'])
                age = (datetime.now(timezone.utc) - checked).total_seconds()
                valid = valid and 0 <= age < 86400
            except (KeyError, TypeError, ValueError): valid = False
            if gate == 'writer-upgrade':
                valid = valid and value.get('minimum_writer_version') == WRITER_VERSION and value.get('legacy_writers_stopped') is True
            gates[gate] = dict(verified=valid, revision=hashlib.sha256(read(path, 65536)).hexdigest())
        else: gates[gate] = dict(verified=paths.pilot, synthetic_exemption=paths.pilot)
    result = dict(status='ready' if all(g['verified'] for g in gates.values()) and adoption['status'] != 'blocked' else 'blocked',
                  gates=gates, catalog_status=adoption['status'], catalog_plan_hash=adoption['plan_hash'],
                  current=current, proposed=dict(schema_version=1, activity_index=True, deferred_views=True, managed_catalog=True))
    result['plan_hash'] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def apply(paths, expected_plan_hash):
    preview = plan(paths)
    if preview['plan_hash'] != expected_plan_hash or preview['status'] != 'ready':
        raise ValueError('ROLLOUT_GATES_UNMET_OR_PLAN_STALE')
    catalog = ManagedCatalog(paths.vault, paths.control)
    if preview['catalog_status'] != 'already_adopted': catalog.adopt(preview['catalog_plan_hash'])
    with locked(paths.control):
        # Recheck gate evidence after catalog adoption, before changing semantics.
        verified = plan(paths)
        if verified['status'] != 'ready' or verified['gates'] != preview['gates'] or features(paths.control) != preview['current']:
            raise ValueError('ROLLOUT_GATES_CHANGED')
        atomic(paths.control / 'writer-version.json', canonical(dict(schema_version=1, minimum_writer_version=WRITER_VERSION, maintenance=False)))
        atomic(paths.control / 'features.json', canonical(preview['proposed']))
    return {'status': 'configured', 'code': 'FEATURES_ENABLED_INDEX_BUILD_REQUIRED', 'features': preview['proposed']}
