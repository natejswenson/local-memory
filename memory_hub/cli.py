"""Unified local operations. JSON results are shared with the MCP service layer."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from .paths import HubPaths
from .serialization import canonical
from .services import HubServices
from .skill_store import read, safe

COMMANDS = {'status', 'clients', 'connect', 'disconnect', 'verify', 'rollback', 'recall', 'capture',
            'activity', 'index', 'maintenance', 'views', 'backup', 'benchmark', 'catalog', 'changes', 'features'}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=sorted(COMMANDS | {'doctor'}))
    p.add_argument('action', nargs='?')
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--pilot', action='store_true')
    p.add_argument('--all', action='store_true'); p.add_argument('--details', action='store_true')
    p.add_argument('--json', action='store_true')
    p.add_argument('--client'); p.add_argument('--profile', default='default')
    p.add_argument('--mode', choices=['live', 'pilot'], default='pilot')
    p.add_argument('--apply', action='store_true'); p.add_argument('--expect-plan')
    p.add_argument('--operation'); p.add_argument('--synthetic', action='store_true')
    p.add_argument('--evidence', type=Path)
    p.add_argument('--request', type=Path); p.add_argument('--subject', default='global')
    p.add_argument('--query', default=''); p.add_argument('--skill'); p.add_argument('--state')
    p.add_argument('--since'); p.add_argument('--until'); p.add_argument('--stream', default='all')
    p.add_argument('--limit', type=int, default=10); p.add_argument('--cursor')
    p.add_argument('--once', action='store_true'); p.add_argument('--full', action='store_true')
    p.add_argument('--archive', type=Path); p.add_argument('--quarantine', type=Path)
    p.add_argument('--destination', type=Path); p.add_argument('--key', type=Path)
    p.add_argument('--suite', default='quick'); p.add_argument('--output', type=Path)
    return p


def run(a):
    paths = HubPaths(a.root, a.pilot); service = HubServices(paths)
    if a.command in {'status', 'doctor'}: return service.status(details=a.details or a.command == 'doctor')
    if a.command in {'clients', 'connect', 'disconnect', 'verify', 'rollback'}:
        from .clients import ClientManager
        manager = ClientManager(HubPaths(a.root))
        if a.command == 'clients': return {'status': 'ok', 'clients': manager.discover()}
        if a.command == 'rollback':
            if a.apply and not a.expect_plan: raise ValueError('EXPECTED_PLAN_REQUIRED')
            return manager.rollback(a.operation, a.apply, a.expect_plan)
        if not a.client: raise ValueError('CLIENT_REQUIRED')
        if a.command == 'verify':
            if a.evidence: return manager.verify_host(a.client, a.evidence, a.profile)
            if a.synthetic:
                from .verification import synthetic_roundtrip
                return asyncio.run(synthetic_roundtrip(a.root, a.client))
            return asyncio.run(manager.verify_transport(a.client, a.profile))
        plan = manager.plan(a.client, a.profile, a.mode, a.command == 'disconnect')
        if a.apply:
            if not a.expect_plan: raise ValueError('EXPECTED_PLAN_REQUIRED')
            return manager.apply(plan, a.expect_plan)
        return {k: v for k, v in plan.items() if not k.startswith('_')} | {'status': 'planned'}
    if a.command == 'recall': return service.recall(subject=a.subject, query=a.query)
    if a.command in {'capture', 'activity'}:
        if a.command == 'activity' and a.action == 'recall':
            return service.activity().recall(skill=a.skill, subject=None if a.subject == 'global' else a.subject,
                state=a.state, since=a.since, until=a.until, query=a.query, limit=a.limit, stream=a.stream, cursor=a.cursor)
        if not a.request: raise ValueError('REQUEST_FILE_REQUIRED')
        request = json.loads(read(a.request, 32768))
        if a.command == 'capture':
            if not a.apply:
                from .capture import validate
                from .projects import subjects
                validate(request, subjects(paths.vault))
                return {'status': 'planned', 'code': 'CAPTURE_VALIDATED_NOT_SAVED', 'capture_id': request.get('capture_id')}
            return service.capture(**request)
        if a.action != 'record': raise ValueError('EXPECTED_ACTIVITY_RECORD_OR_RECALL')
        return service.activity().record(request)
    if a.command == 'index':
        from .activity_index import ActivityIndex
        index = ActivityIndex(service.activity())
        if a.action == 'status':
            # Status never creates a database or reconciles source files.
            return {'status': 'ok', 'exists': safe(index.path).exists(), 'maintenance': service.status().get('maintenance')}
        if a.action == 'reconcile': return index.maintain(full=True)
        if a.action == 'rebuild': return index.rebuild()
        raise ValueError('EXPECTED_INDEX_STATUS_RECONCILE_OR_REBUILD')
    if a.command == 'changes':
        from .change_log import ChangeLog
        paths.require_ready()
        return ChangeLog(paths.control).recover(paths.vault, a.apply, a.expect_plan)
    if a.command == 'catalog':
        from .managed_catalog import ManagedCatalog
        paths.require_ready(); catalog = ManagedCatalog(paths.vault, paths.control)
        if a.apply:
            if not a.expect_plan: raise ValueError('EXPECTED_PLAN_REQUIRED')
            return catalog.adopt(a.expect_plan)
        plan = catalog.preview()
        return {k: v for k, v in plan.items() if k != 'catalog'} | {'records': len(plan['catalog']['records'])}
    if a.command == 'features':
        from .rollout import plan, apply
        return apply(paths, a.expect_plan) if a.apply else plan(paths)
    if a.command == 'maintenance':
        if a.action == 'install':
            from scripts.install_maintenance import plan, install
            if a.apply: return install(paths.root, a.expect_plan)
            return {k:v for k,v in plan(paths.root).items() if not k.startswith('_')} | {'status': 'planned'}
        from .worker import run_once, run as worker
        if a.action != 'run': raise ValueError('EXPECTED_MAINTENANCE_RUN')
        return run_once(paths, a.full) if a.once else worker(paths)
    if a.command == 'views':
        from .atlas import refresh
        paths.require_ready()
        return refresh(paths.vault, paths.control, a.apply)
    if a.command == 'backup':
        from .operations import backup_status, backup_create, backup_verify
        if a.action == 'status': return backup_status(paths)
        if a.action == 'create': return backup_create(paths, a.destination, a.key)
        if a.action == 'verify': return backup_verify(paths, a.archive, a.quarantine, a.key)
        raise ValueError('EXPECTED_BACKUP_STATUS_CREATE_OR_VERIFY')
    if a.command == 'benchmark':
        from .benchmark import benchmark
        result = benchmark(a.suite)
        if a.output:
            from .skill_store import atomic
            atomic(a.output, canonical(result))
        return result
    raise ValueError('UNKNOWN_COMMAND')


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        result = run(a)
        status = result.get('status', 'ok')
        result.setdefault('code', status.upper())
        code = 0 if status in {'ok', 'planned', 'configured', 'adopted', 'recorded', 'already_recorded', 'created', 'already_created', 'encrypted', 'verified'} else 1 if status in {'partial', 'warning', 'needs_repair'} else 3
    except (OSError, ValueError, TypeError, KeyError) as error:
        # Do not echo arbitrary parser exceptions containing private source text.
        message = str(error)
        code_name = message if message.isupper() and message.replace('_', '').isalnum() else 'OPERATION_REQUIRES_REVIEW'
        result = {'status': 'unavailable', 'code': code_name}; code = 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__': raise SystemExit(main())
