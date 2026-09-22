"""Application services shared by CLI and the small MCP server."""
import json
import sqlite3
from .paths import HubPaths
from .skill_store import read, safe
from .writer_gate import WRITER_VERSION, features


class HubServices:
    def __init__(self, paths: HubPaths):
        self.paths = paths
        self._ranker = None
        self._ranker_loaded = False

    def recall(self, **request):
        self.paths.require_ready()
        from .recall import recall_context
        if not self._ranker_loaded:
            from .semantic import configured_ranker
            self._ranker = configured_ranker(self.paths.root) if not self.paths.pilot else None
            self._ranker_loaded = True
        return recall_context(self.paths.vault, semantic_ranker=self._ranker, **request)

    def capture(self, **request):
        self.paths.require_ready()
        from .capture import CaptureStore
        result = CaptureStore(self.paths.vault, self.paths.control).capture(request)
        if result.get('verified'):
            try:
                from .atlas import refresh_if_configured
                result['navigation'] = refresh_if_configured(self.paths.vault, self.paths.control)
            except (OSError, ValueError, TypeError, KeyError):
                result['navigation'] = {'applied': False, 'reason': 'refresh_required; capture saved'}
        return result

    def activity(self):
        self.paths.require_ready()
        from .activity import ActivityStore
        return ActivityStore(self.paths.vault, self.paths.control)

    def skill(self, request):
        self.paths.require_ready()
        from .skill_store import SkillStore
        return SkillStore(self.paths.vault, self.paths.skill_control).request(request)

    def status(self, details=False):
        from datetime import datetime, timezone
        result = {**self.paths.readiness(), 'contract_version': 2, 'writer_version': WRITER_VERSION,
                  'checked_at': datetime.now(timezone.utc).isoformat(), 'issues': []}
        try:
            flags = features(self.paths.control)
            result.update(features=flags, status='ok' if result['ready'] else 'unavailable')
            for name, relative in [('integrations', 'integrations.json'), ('operations', 'operations.json')]:
                path = safe(self.paths.control / relative)
                if path.exists():
                    value = json.loads(read(path, 262144))
                    if name == 'integrations':
                        from .clients import ClientManager
                        manager = ClientManager(self.paths)
                        result['clients'] = [{k: row.get(k) for k in ('client', 'profile', 'reload_required')} |
                                             {'coverage': manager.inspect(row['client'], row['profile'])}
                                             for row in value.get('bindings', {}).values()]
            checkpoint = self.paths.runtime / 'maintenance/status.json'
            if safe(checkpoint).exists():
                result['maintenance'] = json.loads(read(checkpoint))
            from .operations import backup_status
            result['backup'] = backup_status(self.paths)
            if result['backup']['status'] != 'ok': result['issues'].append(result['backup']['code'])
            from .change_log import ChangeLog
            result['high_water'] = ChangeLog(self.paths.control).high_water()
            if flags.get('activity_index'):
                import sqlite3
                from urllib.parse import quote
                if safe(self.paths.index).exists():
                    db = sqlite3.connect('file:' + quote(str(self.paths.index)) + '?mode=ro', uri=True, timeout=.25)
                    try:
                        settings = {row[0]: json.loads(row[1]) for row in db.execute('SELECT key,value FROM settings')}
                        result['index'] = {k: settings.get(k) for k in ('checkpoint', 'reconciled_at', 'version')}
                        result['index']['source_issues'] = db.execute('SELECT count(*) FROM issues').fetchone()[0]
                        if result['index']['source_issues']: result['issues'].append('ACTIVITY_SOURCES_NEED_REVIEW')
                        if (settings.get('checkpoint') or 0) < result['high_water']: result['issues'].append('ACTIVITY_INDEX_CATCHING_UP')
                    finally: db.close()
                else: result['issues'].append('ACTIVITY_INDEX_NOT_BUILT')
            if flags.get('deferred_views'):
                from datetime import timedelta
                finished = result.get('maintenance', {}).get('completed_at')
                if not finished or datetime.now(timezone.utc) - datetime.fromisoformat(finished) > timedelta(minutes=5):
                    result['issues'].append('MAINTENANCE_OVERDUE')
            if details:
                from scripts.memory_health import health
                result['general'] = health(self.paths.vault, details=True)
                if result['general'].get('review_reasons'):
                    result['issues'].append('GENERAL_RECORDS_NEED_REVIEW')
            if result['issues'] and result['status'] == 'ok':
                result['status'] = 'warning'
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            result.update(status='unavailable', ready=False)
            result['issues'].append('CONTROL_STATE_UNAVAILABLE')
        return result
